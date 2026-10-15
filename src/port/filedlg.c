/* filedlg.c - GetOpenFileNameA and GetSaveFileNameA (comdlg32): the common file dialogs, drawn as Windows 98's Explorer-style ones are, on the dialog renderer of ui.c.
 *
 * The dialog is an ordinary modal dialog (wm_dialog_box) made of standard controls (a "Look in" combo box and an Up one level button, a list of the folder's
 * folders and files, a file name edit box, a "Files of type" combo box, Open or Save and Cancel), with a window procedure of the port's own (a host function the dialog
 * machinery calls as it calls the game's): it does the clicks on the list, the combo boxes' drop-down lists and the typing, which the standard controls do not.
 * Names are the guest's (backslashes, "C:\..." as paths.c maps them); what the user chose goes into lpstrFile as such, with nFileOffset and nFileExtension.
 *
 * OPENFILENAMEA (the 76-byte form the game fills in): 0 lStructSize, 4 hwndOwner, 8 hInstance, 12 lpstrFilter, 16 lpstrCustomFilter, 20 nMaxCustFilter, 24 nFilterIndex,
 * 28 lpstrFile, 32 nMaxFile, 36 lpstrFileTitle, 40 nMaxFileTitle, 44 lpstrInitialDir, 48 lpstrTitle, 52 Flags, 56 nFileOffset (WORD), 58 nFileExtension (WORD),
 * 60 lpstrDefExt, 64 lCustData, 68 lpfnHook, 72 lpTemplateName. Not done: hooks and templates, the places bar, multiple selection, the read-only box. */
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>

#include "filedlg.h"
#include "gdi_int.h"
#include "sched.h"
#include "wm.h"

#define P(a) ((char *)(G + (a)))

enum { OFN_OVERWRITEPROMPT = 0x2, OFN_PATHMUSTEXIST = 0x800, OFN_FILEMUSTEXIST = 0x1000, OFN_ENABLEHOOK = 0x20, OFN_ENABLETEMPLATE = 0x40, OFN_ALLOWMULTISELECT = 0x200 };
enum { ID_LIST = 0x460, ID_TYPE = 0x470, ID_LOOKIN = 0x471, ID_UP = 0x472, ID_NAME = 0x480, ID_STATUS = 0x500, ID_YES = 0x501, ID_NO = 0x502, ID_POPUP = 0x6F0 };

extern char guest_cwd[260];

/* ---- paths and filters ---------------------------------------------------------------------------------------------------------- */
int fd_parse_filter(const char *s, size_t cap, FdFilter *out, int max)
{
    int n = 0;
    size_t i = 0;

    while (n < max && i < cap && s[i]) {
        const char *desc = s + i, *pat;
        size_t dl = strnlen(desc, cap - i), pl;

        i += dl + 1;
        if (i >= cap || !s[i])
            break;                                          /* a description without a pattern */
        pat = s + i;
        pl = strnlen(pat, cap - i);
        i += pl + 1;
        snprintf(out[n].desc, sizeof(out[n].desc), "%.*s", (int)dl, desc);
        snprintf(out[n].pat, sizeof(out[n].pat), "%.*s", (int)pl, pat);
        n++;
    }
    return n;
}

int fd_has_wild(const char *s) { return strpbrk(s, "*?") != NULL; }

static int ci_eq(char a, char b) { return tolower((unsigned char)a) == tolower((unsigned char)b); }

int fd_wild_match(const char *p, const char *n)
{
    const char *star = NULL, *sn = NULL;

    if (!strcmp(p, "*.*"))
        return 1;
    while (*n) {
        if (*p == '*') {
            star = p++;
            sn = n;
        } else if (*p == '?' || (*p && ci_eq(*p, *n))) {
            p++;
            n++;
        } else if (star) {
            p = star + 1;
            n = ++sn;
        } else
            return 0;
    }
    while (*p == '*')
        p++;
    return !*p;
}

int fd_filter_match(const char *patterns, const char *name)
{
    char one[160];
    const char *s = patterns;

    while (*s) {
        size_t n = strcspn(s, ";"), a = 0, b = n;

        while (a < b && s[a] == ' ')
            a++;
        while (b > a && s[b - 1] == ' ')
            b--;
        snprintf(one, sizeof(one), "%.*s", (int)(b - a), s + a);
        if (one[0] && fd_wild_match(one, name))
            return 1;
        s += n;
        if (*s == ';')
            s++;
    }
    return 0;
}

static const char *last_sep(const char *path)
{
    const char *a = strrchr(path, '\\'), *b = strrchr(path, '/');

    return a && b ? (a > b ? a : b) : a ? a : b;
}

void fd_name_of(const char *path, char *out, size_t cap)
{
    const char *sep = last_sep(path);

    snprintf(out, cap, "%s", sep ? sep + 1 : path);
}

void fd_dir_of(const char *path, char *out, size_t cap)
{
    const char *sep = last_sep(path);
    size_t n;

    if (!sep) {
        snprintf(out, cap, "%s", "");
        return;
    }
    n = (size_t)(sep - path);
    if (n == 2 && path[1] == ':')
        n = 3;                                              /* "C:\" keeps its backslash */
    snprintf(out, cap, "%.*s", (int)n, path);
}

int fd_parent(const char *dir, char *out, size_t cap)
{
    char tmp[600];

    if (strlen(dir) <= 3) {
        snprintf(tmp, sizeof(tmp), "%s", dir);
        snprintf(out, cap, "%s", tmp);
        return 0;
    }
    fd_dir_of(dir, tmp, sizeof(tmp));
    snprintf(out, cap, "%s", tmp);
    return 1;
}

void fd_join(const char *dir, const char *name, char *out, size_t cap)
{
    size_t n = strlen(dir);
    char tmp[1200];

    snprintf(tmp, sizeof(tmp), "%s%s%s", dir, n && dir[n - 1] != '\\' && dir[n - 1] != '/' ? "\\" : "", name);
    snprintf(out, cap, "%s", tmp);
}

void fd_resolve(const char *cur, const char *typed, char *out, size_t cap)
{
    char t[600], full[700];
    size_t a = 0, n = strlen(typed);

    while (a < n && (typed[a] == ' ' || typed[a] == '\t' || typed[a] == '"'))
        a++;
    while (n > a && (typed[n - 1] == ' ' || typed[n - 1] == '\t' || typed[n - 1] == '"'))
        n--;
    snprintf(t, sizeof(t), "%.*s", (int)(n - a), typed + a);
    n = strlen(t);
    while (n > 1 && (t[n - 1] == '\\' || t[n - 1] == '/') && !(n == 3 && t[1] == ':'))
        t[--n] = 0;
    if ((n >= 3 && isalpha((unsigned char)t[0]) && t[1] == ':' && (t[2] == '\\' || t[2] == '/')) || t[0] == '\\' || t[0] == '/')
        snprintf(full, sizeof(full), "%s", t);
    else
        fd_join(cur, t, full, sizeof(full));
    paths_normalize(full, out, cap);
}

int fd_has_ext(const char *name)
{
    char n[300];

    fd_name_of(name, n, sizeof(n));
    return strchr(n, '.') != NULL;
}

void fd_add_defext(char *path, size_t cap, const char *defext)
{
    size_t n = strlen(path);

    if (!defext || !*defext || fd_has_ext(path))
        return;
    while (*defext == '.' || *defext == '*')                /* the game hands over "*.SVG" where ".SVG" is meant */
        defext++;
    if (*defext && !fd_has_wild(defext) && n + 1 + strlen(defext) < cap)
        snprintf(path + n, cap - n, ".%s", defext);
}

void fd_offsets(const char *path, int *file_offset, int *file_extension)
{
    const char *sep = last_sep(path), *name = sep ? sep + 1 : path, *dot = strrchr(name, '.');

    *file_offset = (int)(name - path);
    *file_extension = dot ? (int)(dot + 1 - path) : 0;
}

/* ---- the dialog ------------------------------------------------------------------------------------------------------------------ */
typedef struct FdEnt { char name[260]; int dir; } FdEnt;

static struct Fd {
    int save, nflt, cur, popup, prompting, last_row, rowh, prow;
    uint32_t ofn, flags, hdlg, last_ms;
    char dir[520], wild[160], defext[16], pending[520], initname[300];
    FdFilter flt[16];
} fd;

static Window *ctl(int id) { return wm_dlg_item(fd.hdlg, (uint32_t)id); }

static void set_text(Window *w, const char *s)
{
    if (!w)
        return;
    free(w->title);
    w->title = strdup(s);
    wm_dirty = 1;
}

static void status(const char *s) { set_text(ctl(ID_STATUS), s); }

/* 0 none, 1 a file, 2 a folder: of the guest path as the game sees it (the installed folder and the overlay together) */
static int kind_of(const char *guest)
{
    char host[1300];
    struct stat st;

    if (!paths_host(guest, 0, host, sizeof(host)) || stat(host, &st) != 0)
        return 0;
    return S_ISDIR(st.st_mode) ? 2 : 1;
}

static int ent_less(const void *a, const void *b)
{
    const FdEnt *x = a, *y = b;

    if (x->dir != y->dir)
        return y->dir - x->dir;
    return strcasecmp(x->name, y->name);
}

typedef struct { FdEnt *e; int n, cap; const char *pat; } Lister;

static void list_cb(const char *name, int is_dir, void *ctx)
{
    Lister *l = ctx;

    if (name[0] == '.' || strlen(name) >= sizeof(l->e[0].name))
        return;
    if (!is_dir && !fd_filter_match(l->pat, name))
        return;
    if (l->n == l->cap) {
        l->cap = l->cap ? l->cap * 2 : 64;
        l->e = realloc(l->e, (size_t)l->cap * sizeof(*l->e));
    }
    snprintf(l->e[l->n].name, sizeof(l->e[0].name), "%s", name);
    l->e[l->n++].dir = is_dir;
}

static void refill(void)
{
    Lister l = {NULL, 0, 0, fd.wild[0] ? fd.wild : fd.flt[fd.cur].pat};
    Window *list = ctl(ID_LIST);
    int i;

    paths_list(fd.dir, list_cb, &l);
    if (l.n > 1)
        qsort(l.e, (size_t)l.n, sizeof(*l.e), ent_less);
    wm_list_reset(list);
    for (i = 0; i < l.n; i++)
        wm_list_add(list, l.e[i].name, (uint32_t)l.e[i].dir);
    list->top = 0;
    list->sel = -1;
    free(l.e);
    wm_dirty = 1;
}

static void dir_label(char *out, size_t cap)
{
    char name[300];

    fd_name_of(fd.dir, name, sizeof(name));
    snprintf(out, cap, "%s", strlen(fd.dir) <= 3 ? fd.dir : name);
}

static void set_dir(const char *dir)
{
    Window *lookin = ctl(ID_LOOKIN), *up = ctl(ID_UP);
    char label[300], parent[520];

    snprintf(fd.dir, sizeof(fd.dir), "%s", dir);
    fd.wild[0] = 0;
    dir_label(label, sizeof(label));
    wm_list_reset(lookin);
    wm_list_add(lookin, label, 0);
    lookin->sel = 0;
    if (up)
        up->enabled = fd_parent(fd.dir, parent, sizeof(parent));
    refill();
}

static void name_text(const char *s)
{
    Window *e = ctl(ID_NAME);

    set_text(e, s);
    if (e) {
        e->caret = (int)strlen(s);
        e->has_caret = 1;
    }
}

static void ensure_visible(Window *l, int rowh)
{
    int rows = (l->h - 4) / rowh;

    if (rows < 1)
        rows = 1;
    if (l->sel >= 0 && l->sel < l->top)
        l->top = l->sel;
    if (l->sel >= l->top + rows)
        l->top = l->sel - rows + 1;
    if (l->top < 0)
        l->top = 0;
    wm_dirty = 1;
}

/* a click, or Return, on a folder of the list or a name typed that is one */
static void enter_dir(const char *path)
{
    set_dir(path);
    name_text("");
    status("");
}

static void popup_close(void)
{
    Window *pop = ctl(ID_POPUP);

    if (pop)
        pop->visible = 0;
    fd.popup = 0;
    wm_dirty = 1;
}

/* the folders from the drive down to the current one: index k is the folder after k + 1 names */
static int chain(char parts[][300], int max)
{
    char tmp[520], *seg, *save;
    int n = 0;

    snprintf(parts[n++], 300, "%.3s", fd.dir);
    snprintf(tmp, sizeof(tmp), "%s", fd.dir + (strlen(fd.dir) > 3 ? 3 : strlen(fd.dir)));
    for (seg = strtok_r(tmp, "\\", &save); seg && n < max; seg = strtok_r(NULL, "\\", &save))
        snprintf(parts[n++], 300, "%s", seg);
    return n;
}

static void chain_path(int k, char *out, size_t cap)
{
    char parts[40][300];
    int n = chain(parts, 40), i;

    if (k >= n)
        k = n - 1;
    snprintf(out, cap, "%s", parts[0]);
    for (i = 1; i <= k; i++)
        fd_join(out, parts[i], out, cap);
}

static void popup_open(int kind)
{
    Window *pop = ctl(ID_POPUP), *combo = ctl(kind == 1 ? ID_LOOKIN : ID_TYPE), *w;
    int i, rows, n, nw = wm_window_count();
    double top = 0;

    if (!pop || !combo)
        return;
    wm_list_reset(pop);
    if (kind == 1) {
        char parts[40][300], line[340];

        n = chain(parts, 40);
        for (i = 0; i < n; i++) {
            snprintf(line, sizeof(line), "%*s%s", 3 * i, "", parts[i]);
            wm_list_add(pop, line, (uint32_t)i);
        }
        pop->sel = n - 1;
    } else {
        for (i = 0; i < fd.nflt; i++)
            wm_list_add(pop, fd.flt[i].desc, (uint32_t)i);
        pop->sel = fd.cur;
    }
    rows = pop->nitems < 8 ? pop->nitems : 8;
    pop->x = combo->x;
    pop->y = combo->y + 21;
    pop->w = combo->w;
    pop->h = rows * fd.prow + 4;
    pop->top = 0;
    for (i = 0; i < nw; i++) {                                  /* above every sibling */
        w = wm_window_at_index(i);
        if (w && w->parent == fd.hdlg && w != pop && w->z > top)
            top = w->z;
    }
    pop->z = top + 1;
    pop->visible = 1;
    fd.popup = kind;
    ensure_visible(pop, fd.prow);
    wm_dirty = 1;
}

static void popup_pick(int row)
{
    Window *pop = ctl(ID_POPUP);
    int kind = fd.popup;

    if (!pop || row < 0 || row >= pop->nitems)
        return;
    popup_close();
    if (kind == 1) {
        char path[520];

        chain_path((int)pop->items[row].data, path, sizeof(path));
        if (strcmp(path, fd.dir))
            enter_dir(path);
    } else if (kind == 2) {
        Window *type = ctl(ID_TYPE);

        fd.cur = row;
        fd.wild[0] = 0;
        wm_list_reset(type);
        wm_list_add(type, fd.flt[row].desc, 0);
        type->sel = 0;
        refill();
    }
}

/* what the user chose: lpstrFile, the offsets, the title, the filter; the dialog ends */
static void finish(const char *path)
{
    uint32_t file = RD32(fd.ofn + 28), nmax = RD32(fd.ofn + 32), title = RD32(fd.ofn + 36), tmax = RD32(fd.ofn + 40);
    size_t n = strlen(path);
    int fo, fe;
    Window *dlg = wm_window(fd.hdlg);
    char name[300];

    fd.prompting = 0;
    if (!file || n + 1 > nmax) {
        status("The file name is too long.");
        return;
    }
    memcpy(P(file), path, n + 1);
    fd_offsets(path, &fo, &fe);
    WR16(fd.ofn + 56, fo);
    WR16(fd.ofn + 58, fe);
    fd_name_of(path, name, sizeof(name));
    if (title && tmax) {
        size_t m = strlen(name) < tmax - 1 ? strlen(name) : tmax - 1;

        memcpy(P(title), name, m);
        P(title)[m] = 0;
    }
    WR32(fd.ofn + 24, fd.cur + 1);
    port_trace("file dialog: %s -> %s", fd.save ? "Save" : "Open", path);
    if (dlg) {
        dlg->ended = 1;
        dlg->result = 1;
    }
}

static void prompt(int on)
{
    Window *yes = ctl(ID_YES), *no = ctl(ID_NO);

    fd.prompting = on;
    if (yes)
        yes->visible = on;
    if (no)
        no->visible = on;
    wm_dirty = 1;
}

static void do_ok(void)
{
    Window *e = ctl(ID_NAME), *list = ctl(ID_LIST);
    char typed[520], path[520], folder[520], msg[700];
    int kind;

    if (fd.popup) {
        Window *pop = ctl(ID_POPUP);

        popup_pick(pop ? pop->sel : -1);
        return;
    }
    if (fd.prompting) {                                         /* Return answers the question Yes */
        char p[520];

        snprintf(p, sizeof(p), "%s", fd.pending);
        prompt(0);
        finish(p);
        return;
    }
    snprintf(typed, sizeof(typed), "%s", e ? e->title : "");
    {
        char *a = typed;
        size_t n = strlen(a);

        while (*a == ' ')
            a++;
        while (n && a[n - 1] == ' ')
            a[--n] = 0;
        memmove(typed, a, strlen(a) + 1);
    }
    status("");
    if (!typed[0]) {
        if (list && list->sel >= 0 && list->sel < list->nitems && list->items[list->sel].data == 1) {      /* a folder chosen in the list opens */
            fd_resolve(fd.dir, list->items[list->sel].text, path, sizeof(path));
            enter_dir(path);
        } else
            status("Type the name of a file.");
        return;
    }
    if (fd_has_wild(typed)) {                                   /* "*.dck": a pattern is shown, not chosen (a folder before it is entered) */
        char dir[520], pat[300];

        fd_dir_of(typed, dir, sizeof(dir));
        fd_name_of(typed, pat, sizeof(pat));
        if (dir[0] && !fd_has_wild(dir)) {
            fd_resolve(fd.dir, dir, folder, sizeof(folder));
            if (kind_of(folder) != 2) {
                snprintf(msg, sizeof(msg), "%s: The path does not exist.", typed);
                status(msg);
                return;
            }
            if (strcmp(folder, fd.dir))
                set_dir(folder);
        }
        snprintf(fd.wild, sizeof(fd.wild), "%s", pat);
        refill();
        return;
    }
    fd_resolve(fd.dir, typed, path, sizeof(path));
    kind = kind_of(path);
    if (kind == 2) {                                            /* a folder: go into it */
        enter_dir(path);
        return;
    }
    {
        size_t n = strlen(typed);

        if (typed[n - 1] == '\\' || typed[n - 1] == '/') {
            snprintf(msg, sizeof(msg), "%s: The path does not exist.", typed);
            status(msg);
            return;
        }
    }
    fd_dir_of(path, folder, sizeof(folder));
    if (kind_of(folder) != 2) {
        snprintf(msg, sizeof(msg), "%s: The path does not exist. Check the path and try again.", typed);
        status(msg);
        return;
    }
    if (!fd.save) {
        if (!kind && !fd_has_ext(path) && fd.defext[0]) {       /* "deck" finds "deck.dck" */
            char with[520];

            snprintf(with, sizeof(with), "%s", path);
            fd_add_defext(with, sizeof(with), fd.defext);
            if (kind_of(with) == 1) {
                snprintf(path, sizeof(path), "%s", with);
                kind = 1;
            }
        }
        if (!kind && (fd.flags & OFN_FILEMUSTEXIST)) {
            snprintf(msg, sizeof(msg), "%s: File not found. Check the file name and try again.", typed);
            status(msg);
            return;
        }
        finish(path);
        return;
    }
    fd_add_defext(path, sizeof(path), fd.defext);
    if ((fd.flags & OFN_OVERWRITEPROMPT) && kind_of(path) == 1) {
        char name[300];

        fd_name_of(path, name, sizeof(name));
        snprintf(msg, sizeof(msg), "%s already exists. Do you want to replace it?", name);
        status(msg);
        snprintf(fd.pending, sizeof(fd.pending), "%s", path);
        prompt(1);
        return;
    }
    finish(path);
}

static void cancel(void)
{
    Window *dlg = wm_window(fd.hdlg);

    if (fd.popup) {
        popup_close();
        return;
    }
    if (fd.prompting) {
        prompt(0);
        status("");
        return;
    }
    if (dlg) {
        dlg->ended = 1;
        dlg->result = 0;
    }
}

static void select_row(Window *list, int row)
{
    if (row < 0 || row >= list->nitems)
        return;
    list->sel = row;
    ensure_visible(list, fd.rowh);
    if (list->items[row].data != 1) {                           /* a file's name goes into the edit box */
        name_text(list->items[row].text);
        status("");
    }
}

static void crect(const Window *dlg, const Window *w, int *x0, int *y0, int *x1, int *y1)
{
    int a, b, c, d, ox, oy;

    wm_abs_rect(w, &a, &b, &c, &d);
    wm_client_origin(dlg, &ox, &oy);
    *x0 = a - ox; *y0 = b - oy; *x1 = c - ox; *y1 = d - oy;
}

static void click(Window *dlg, int x, int y)
{
    Window *list = ctl(ID_LIST), *pop = ctl(ID_POPUP), *lookin = ctl(ID_LOOKIN), *type = ctl(ID_TYPE), *e = ctl(ID_NAME);
    int x0, y0, x1, y1;

    if (fd.popup && pop) {
        crect(dlg, pop, &x0, &y0, &x1, &y1);
        if (x >= x0 && x < x1 && y >= y0 && y < y1) {
            int row = pop->top + (y - y0 - 2) / fd.prow;

            if (pop->nitems > (y1 - y0 - 4) / fd.prow && x >= x1 - 18) {          /* its scroll bar */
                int rows = (y1 - y0 - 4) / fd.prow;

                pop->top += y < (y0 + y1) / 2 ? -1 : 1;
                if (pop->top > pop->nitems - rows)
                    pop->top = pop->nitems - rows;
                if (pop->top < 0)
                    pop->top = 0;
                wm_dirty = 1;
                return;
            }
            popup_pick(row);
            return;
        }
        {
            int was = fd.popup, inside = 0;

            crect(dlg, was == 1 ? lookin : type, &x0, &y0, &x1, &y1);
            inside = x >= x0 && x < x1 && y >= y0 && y < y0 + 21;
            popup_close();
            if (inside)
                return;                                         /* a click on its own combo box only closes it */
        }
    }
    if (lookin && (crect(dlg, lookin, &x0, &y0, &x1, &y1), x >= x0 && x < x1 && y >= y0 && y < y0 + 21)) {
        popup_open(1);
        return;
    }
    if (type && (crect(dlg, type, &x0, &y0, &x1, &y1), x >= x0 && x < x1 && y >= y0 && y < y0 + 21)) {
        popup_open(2);
        return;
    }
    if (list) {
        crect(dlg, list, &x0, &y0, &x1, &y1);
        if (x >= x0 && x < x1 && y >= y0 && y < y1) {
            int rows = (y1 - y0 - 4) / fd.rowh;

            if (list->nitems > rows && x >= x1 - 18) {                            /* the scroll bar: the arrows and the track */
                int bw = 16, h = y1 - y0 - 4 - 2 * bw, th = h * rows / list->nitems, ty;
                int maxtop = list->nitems - rows;

                if (th < 8)
                    th = 8;
                ty = y0 + 2 + bw + (list->top > 0 ? (h - th) * (list->top > maxtop ? maxtop : list->top) / maxtop : 0);
                if (y < y0 + 2 + bw)
                    list->top--;
                else if (y >= y1 - 2 - bw)
                    list->top++;
                else if (y < ty)
                    list->top -= rows;
                else if (y >= ty + th)
                    list->top += rows;
                if (list->top > maxtop)
                    list->top = maxtop;
                if (list->top < 0)
                    list->top = 0;
                wm_dirty = 1;
                return;
            }
            {
                int row = list->top + (y - y0 - 2) / fd.rowh;
                uint32_t now = port_now_ms();

                if (row >= 0 && row < list->nitems) {
                    int dbl = row == fd.last_row && now - fd.last_ms <= 500;

                    select_row(list, row);
                    fd.last_row = dbl ? -1 : row;
                    fd.last_ms = now;
                    if (dbl) {
                        if (list->items[row].data == 1) {
                            char path[520];

                            fd_resolve(fd.dir, list->items[row].text, path, sizeof(path));
                            enter_dir(path);
                        } else
                            do_ok();
                    }
                }
            }
            return;
        }
    }
    if (e) {                                                    /* a click in the edit box puts the cursor there */
        crect(dlg, e, &x0, &y0, &x1, &y1);
        if (x >= x0 && x < x1 && y >= y0 && y < y1) {
            int k, n = (int)strlen(e->title), best = n;

            for (k = 0; k <= n; k++)
                if (x0 + 3 + ui_text_width(dlg->dlg_face, dlg->dlg_pt, 0, e->title, (size_t)k) >= x) {
                    best = k;
                    break;
                }
            e->caret = best;
            wm_dirty = 1;
        }
    }
}

static void key(int vk)
{
    Window *list = ctl(ID_LIST), *e = ctl(ID_NAME);
    int rows;

    if (fd.popup) {
        Window *pop = ctl(ID_POPUP);

        if (pop && (vk == 0x26 || vk == 0x28) && pop->nitems) {
            pop->sel += vk == 0x26 ? -1 : 1;
            pop->sel = pop->sel < 0 ? 0 : pop->sel >= pop->nitems ? pop->nitems - 1 : pop->sel;
            ensure_visible(pop, fd.prow);
        }
        return;
    }
    rows = list ? (list->h - 4) / fd.rowh : 1;
    if (vk == 0x26 || vk == 0x28 || vk == 0x21 || vk == 0x22) {
        int step = vk == 0x26 ? -1 : vk == 0x28 ? 1 : vk == 0x21 ? -rows : rows, row;

        if (!list || !list->nitems)
            return;
        row = list->sel < 0 ? (step > 0 ? 0 : list->nitems - 1) : list->sel + step;
        select_row(list, row < 0 ? 0 : row >= list->nitems ? list->nitems - 1 : row);
        return;
    }
    if (!e)
        return;
    {
        int n = (int)strlen(e->title);

        if (e->has_caret == 2 && (vk == 0x25 || vk == 0x27 || vk == 0x24 || vk == 0x23)) {
            e->has_caret = 1;
            e->caret = vk == 0x25 || vk == 0x24 ? 0 : n;
            wm_dirty = 1;
            return;
        }
        if (e->caret > n)
            e->caret = n;
        if (vk == 0x25 && e->caret > 0)
            e->caret--;
        else if (vk == 0x27 && e->caret < n)
            e->caret++;
        else if (vk == 0x24)
            e->caret = 0;
        else if (vk == 0x23)
            e->caret = n;
        else if (vk == 0x2E && e->caret < n) {                  /* Delete */
            memmove(e->title + e->caret, e->title + e->caret + 1, (size_t)(n - e->caret));
        }
        wm_dirty = 1;
    }
}

static void typed_char(int ch)
{
    Window *e = ctl(ID_NAME);
    int n;

    if (!e || fd.popup || fd.prompting)
        return;
    if (e->has_caret == 2 && (ch == 8 || (ch >= 32 && ch != 127 && ch < 256))) {      /* replaces the selection */
        e->title[0] = 0;
        e->caret = 0;
    }
    e->has_caret = 1;
    n = (int)strlen(e->title);
    if (e->caret > n)
        e->caret = n;
    if (ch == 8) {
        if (e->caret > 0) {
            memmove(e->title + e->caret - 1, e->title + e->caret, (size_t)(n - e->caret + 1));
            e->caret--;
        }
    } else if (ch >= 32 && ch != 127 && ch < 256 && n < 259) {
        e->title = realloc(e->title, (size_t)n + 2);
        memmove(e->title + e->caret + 1, e->title + e->caret, (size_t)(n - e->caret + 1));
        e->title[e->caret++] = (char)ch;
    } else
        return;
    wm_dirty = 1;
}

static uint32_t fd_proc(const uint32_t *a)
{
    uint32_t msg = a[1], wp = a[2], lp = a[3];
    Window *dlg = wm_window(a[0]);

    if (msg == WM_INITDIALOG) {
        Window *e, *type;
        int h, i;

        fd.hdlg = a[0];
        dlg->own_mouse = 1;                                    /* its list and drop-downs are its own: the mouse reaches this procedure, not the standard controls' */
        ui_font_metrics(dlg->dlg_face, dlg->dlg_pt, 0, &h, NULL, NULL);
        fd.prow = h + 1;
        fd.rowh = h + 1 < 16 ? 16 : h + 1;
        fd.last_row = -1;
        e = ctl(ID_NAME);
        type = ctl(ID_TYPE);
        if (e)
            e->has_caret = 1;
        if (ctl(ID_LIST))
            ctl(ID_LIST)->lb_icons = 1;
        wm_list_reset(type);
        wm_list_add(type, fd.flt[fd.cur].desc, 0);
        type->sel = 0;
        {
            char start[520];

            snprintf(start, sizeof(start), "%s", fd.dir);
            for (i = 0; i < 40 && kind_of(start) != 2; i++)                  /* a folder that is not there: the nearest one that is */
                if (!fd_parent(start, start, sizeof(start))) {
                    fd_resolve("C:\\", guest_cwd, start, sizeof(start));
                    break;
                }
            set_dir(start);
            name_text(fd.initname);
            if (e && fd.initname[0])
                e->has_caret = 2;                                       /* the offered name is selected: typing replaces it */
        }
        return 1;
    }
    if (msg == WM_COMMAND) {
        switch (wp & 0xFFFF) {
        case 1: do_ok(); break;
        case 2: cancel(); break;
        case ID_UP: {
            char up[520];

            if (fd_parent(fd.dir, up, sizeof(up)))
                enter_dir(up);
            break;
        }
        case ID_YES: do_ok(); break;
        case ID_NO: cancel(); break;
        default: break;
        }
        return 1;
    }
    if (msg == WM_LBUTTONDOWN || msg == WM_LBUTTONDBLCLK) {
        click(dlg, (int16_t)(lp & 0xFFFF), (int16_t)(lp >> 16));
        return 1;
    }
    if (msg == WM_KEYDOWN) {
        key((int)wp);
        return 1;
    }
    if (msg == WM_CHAR) {
        typed_char((int)wp);
        return 1;
    }
    if (msg == WM_CLOSE) {
        cancel();
        return 1;
    }
    return 0;
}

/* ---- the template ---------------------------------------------------------------------------------------------------------------- */
static uint8_t tb[4096];
static size_t to;

static void t16(unsigned v) { tb[to++] = (uint8_t)v; tb[to++] = (uint8_t)(v >> 8); }
static void t32(uint32_t v) { t16(v & 0xFFFF); t16(v >> 16); }
static void twide(const char *s) { do t16((unsigned char)*s); while (*s++); }
static void titem(uint32_t style, int x, int y, int cx, int cy, unsigned id, unsigned cls, const char *text)
{
    while (to & 3)
        tb[to++] = 0;
    t32(style | WS_CHILD); t32(0);
    t16((unsigned)x); t16((unsigned)y); t16((unsigned)cx); t16((unsigned)cy); t16(id);
    t16(0xFFFF); t16(cls);
    twide(text);
    t16(0);
}

enum { C_BUTTON = 0x80, C_EDIT = 0x81, C_STATIC = 0x82, C_LISTBOX = 0x83, C_COMBOBOX = 0x85 };
#define V WS_VISIBLE
#define TAB WS_TABSTOP

static uint32_t build_and_run(uint32_t ofn, int save)
{
    static uint32_t proc;
    uint32_t owner = RD32(ofn + 4);
    const char *title = RD32(ofn + 48) ? P(RD32(ofn + 48)) : save ? "Save As" : "Open";

    if (!proc)
        proc = port_host_function(fd_proc);
    to = 0;
    t32(0x80C800C4u); t32(0); t16(14);                                     /* popup, caption, system menu, modal frame, 3-D look, font set; 14 controls */
    t16(0); t16(0); t16(272); t16(188);
    t16(0); t16(0);                                                        /* no menu, the dialog class */
    twide(title);
    t16(8); twide("MS Sans Serif");
    titem(V, 7, 9, 32, 8, 0xFFFF, C_STATIC, "Look &in:");
    titem(V | TAB, 42, 6, 150, 13, ID_LOOKIN, C_COMBOBOX, "");
    titem(V | TAB, 198, 5, 60, 14, ID_UP, C_BUTTON, "&Up one level");
    titem(V | TAB | 0x800000u | 0x200000u | 1u, 7, 24, 258, 100, ID_LIST, C_LISTBOX, "");
    titem(V, 7, 131, 42, 8, 0xFFFF, C_STATIC, "File &name:");
    titem(V | TAB | 0x80u, 53, 128, 145, 13, ID_NAME, C_EDIT, "");
    titem(V | TAB | 1u, 206, 128, 59, 14, 1, C_BUTTON, save ? "&Save" : "&Open");
    titem(V, 7, 149, 45, 8, 0xFFFF, C_STATIC, "Files of &type:");
    titem(V | TAB, 53, 146, 145, 13, ID_TYPE, C_COMBOBOX, "");
    titem(V | TAB, 206, 146, 59, 14, 2, C_BUTTON, "Cancel");
    titem(V, 7, 167, 195, 20, ID_STATUS, C_STATIC, "");
    titem(TAB, 206, 167, 28, 14, ID_YES, C_BUTTON, "&Yes");
    titem(0, 237, 167, 28, 14, ID_NO, C_BUTTON, "&No");
    titem(0x800000u | 0x200000u, 53, 159, 145, 40, ID_POPUP, C_LISTBOX, "");          /* the drop-down list of the two combo boxes: hidden until one opens */
    if (!wm_window(owner))
        owner = 0;
    return wm_dialog_box(tb, 0, owner, proc, 0) == 1;
}

static uint32_t open_or_save(const uint32_t *a, int save)
{
    uint32_t ofn = a[0], filt = RD32(ofn + 12), file = RD32(ofn + 28), idir = RD32(ofn + 44), ext = RD32(ofn + 60);
    char initial[520] = "", name[300] = "";

    memset(&fd, 0, sizeof(fd));
    fd.save = save;
    fd.ofn = ofn;
    fd.flags = RD32(ofn + 52);
    if (filt) {
        char raw[2048];

        memcpy(raw, P(filt), sizeof(raw) - 2);
        raw[sizeof(raw) - 1] = raw[sizeof(raw) - 2] = 0;
        fd.nflt = fd_parse_filter(raw, sizeof(raw), fd.flt, 16);
    }
    if (!fd.nflt) {
        snprintf(fd.flt[0].desc, sizeof(fd.flt[0].desc), "All Files (*.*)");
        snprintf(fd.flt[0].pat, sizeof(fd.flt[0].pat), "*.*");
        fd.nflt = 1;
    }
    fd.cur = (int)RD32(ofn + 24) - 1;
    if (fd.cur < 0 || fd.cur >= fd.nflt)
        fd.cur = 0;
    if (ext)
        snprintf(fd.defext, sizeof(fd.defext), "%s", P(ext));
    if (idir && P(idir)[0])
        snprintf(initial, sizeof(initial), "%s", P(idir));
    if (file && P(file)[0]) {                                  /* the name the program offers; a path in it names the folder when the program named none */
        char given[520], dir[520];

        snprintf(given, sizeof(given), "%.519s", P(file));
        fd_name_of(given, name, sizeof(name));
        fd_dir_of(given, dir, sizeof(dir));
        if (!initial[0] && dir[0])
            snprintf(initial, sizeof(initial), "%s", dir);
    }
    fd_resolve(guest_cwd, initial[0] ? initial : guest_cwd, fd.dir, sizeof(fd.dir));
    port_trace("file dialog: %s, folder '%s', file '%s', defext '%s', flags 0x%x, %d filter(s), first '%s' (%s)%s", save ? "Save" : "Open", fd.dir, name, fd.defext,
               fd.flags, fd.nflt, fd.flt[fd.cur].desc, fd.flt[fd.cur].pat, fd.flags & (OFN_ENABLEHOOK | OFN_ENABLETEMPLATE) ? " (hook or template ignored)" : "");
    snprintf(fd.initname, sizeof(fd.initname), "%s", name);
    return build_and_run(ofn, save);
}

static uint32_t GetOpenFileNameA(const uint32_t *a) { return open_or_save(a, 0); }
static uint32_t GetSaveFileNameA(const uint32_t *a) { return open_or_save(a, 1); }

const WinApi FILEDLG_APIS[] = {
    {"comdlg32.dll", "GetOpenFileNameA", GetOpenFileNameA}, {"comdlg32.dll", "GetSaveFileNameA", GetSaveFileNameA},
    {0, 0, 0},
};

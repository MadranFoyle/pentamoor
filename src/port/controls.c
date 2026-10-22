/* controls.c - the built-in controls (BUTTON, STATIC, EDIT, COMBOBOX, LISTBOX, SCROLLBAR), dialogs, scroll bars. Port of the rest of
 * winemu/user32.py. */
#include <ctype.h>
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "gdi.h"
#include "gdi_int.h"
#include "sched.h"
#include "wm.h"

#define P(a) ((char *)(G + (a)))

static int cmp_ci(const char *a, const char *b) { return strcasecmp(a, b); }

static void put_cstr(uint32_t addr, const char *s, size_t n)
{
    memcpy(G + addr, s, n);
    G[addr + n] = 0;
}

static Item *add_item(Window *w, int at, const char *text)
{
    w->items = realloc(w->items, (size_t)(w->nitems + 1) * sizeof(*w->items));
    memmove(&w->items[at + 1], &w->items[at], (size_t)(w->nitems - at) * sizeof(*w->items));
    w->items[at].text = strdup(text);
    w->items[at].data = 0;
    w->nitems++;
    return &w->items[at];
}

static int item_text_less(const void *a, const void *b) { return cmp_ci(((const Item *)a)->text, ((const Item *)b)->text); }

/* Shell-style pattern match, as fnmatch(pattern, name, 0): * ? [set] [!set] [a-z] and a backslash that makes the next character literal. (fnmatch is
 * POSIX and not on Windows; the one matcher is used everywhere so the hosts agree.) */
int port_glob(const char *p, const char *s)
{
    while (*p) {
        if (*p == '*') {
            while (*p == '*')
                p++;
            if (!*p)
                return 1;
            for (; *s; s++)
                if (port_glob(p, s))
                    return 1;
            return 0;
        }
        if (!*s)
            return 0;
        if (*p == '?') {
            p++;
            s++;
            continue;
        }
        if (*p == '[') {
            const char *q = p + 1;
            int neg = 0, ok = 0, first = 1;

            if (*q == '!' || *q == '^') {
                neg = 1;
                q++;
            }
            for (; *q && (*q != ']' || first); q++, first = 0) {
                if (q[1] == '-' && q[2] && q[2] != ']') {
                    if ((unsigned char)*s >= (unsigned char)*q && (unsigned char)*s <= (unsigned char)q[2])
                        ok = 1;
                    q += 2;
                } else if (*q == *s)
                    ok = 1;
            }
            if (*q) {                                   /* a closed set */
                if (ok == neg)
                    return 0;
                p = q + 1;
                s++;
                continue;
            }                                           /* no closing bracket: the bracket is itself */
        }
        if (*p == '\\' && p[1])
            p++;
        if (*p != *s)
            return 0;
        p++;
        s++;
    }
    return !*s;
}

/* A DIR request in progress (paths_list calls back for each name). */
typedef struct { Window *w; char pattern[300]; int found; } DirList;

static void dir_entry(const char *name, int is_dir, void *ctx)
{
    DirList *dl = ctx;
    char up[300];
    size_t i;

    if (is_dir)
        return;
    for (i = 0; name[i] && i < sizeof(up) - 1; i++)
        up[i] = (char)((name[i] >= 'a' && name[i] <= 'z') ? name[i] - 32 : name[i]);
    up[i] = 0;
    if (port_glob(dl->pattern, up)) {
        add_item(dl->w, dl->w->nitems, up);
        dl->found++;
    }
}

void wm_list_reset(Window *w)
{
    int i;

    for (i = 0; i < w->nitems; i++)
        free(w->items[i].text);
    w->nitems = 0;
    w->sel = -1;
}

void wm_list_add(Window *w, const char *text, uint32_t data)
{
    add_item(w, w->nitems, text)->data = data;
}

/* A list index the message names (a negative one, LB_ERR, is no item: the indexes are unsigned in the arguments). */
#define IDX_OK(wp) ((int32_t)(wp) >= 0 && (int32_t)(wp) < w->nitems)

/* The built-in behaviour of BUTTON, STATIC, EDIT, COMBOBOX and LISTBOX windows. */
uint32_t wm_control_message(Window *w, const char *cls, uint32_t msg, uint32_t wp, uint32_t lp)
{
    int cb = !strcasecmp(cls, "COMBOBOX");

    if (msg == WM_SETTEXT) {
        free(w->title);
        w->title = strdup(P(lp));
        return 1;
    }
    if (msg == WM_GETTEXT) {
        size_t n = strlen(w->title);

        if (n > (wp ? wp - 1 : 0))
            n = wp ? wp - 1 : 0;
        put_cstr(lp, w->title, n);
        return (uint32_t)n;
    }
    if (msg == WM_GETTEXTLENGTH)
        return (uint32_t)strlen(w->title);
    if (msg == 0x30) {                  /* WM_SETFONT */
        w->hfont = wp;
        return 0;
    }
    if (msg == 0x31)                    /* WM_GETFONT: the game's own button painting asks for it, to draw in the dialog's face */
        return w->hfont;
    if (msg == WM_ENABLE) {
        w->enabled = wp != 0;
        return 0;
    }
    if (!strcasecmp(cls, "BUTTON")) {
        if (msg == 0xF1) {            /* BM_SETCHECK */
            w->checked = (int)wp;
            return 0;
        }
        if (msg == 0xF0)              /* BM_GETCHECK */
            return (uint32_t)w->checked;
        return 0;
    }
    if (!strcasecmp(cls, "COMBOBOX") || !strcasecmp(cls, "LISTBOX")) {
        int sorted = (w->style & (cb ? 0x100u : 0x2u)) != 0;

        if (msg == (cb ? 0x143u : 0x180u)) {                   /* ADDSTRING */
            const char *text = P(lp);
            int i = w->nitems, k;

            if (sorted)
                for (k = 0; k < w->nitems; k++)
                    if (cmp_ci(w->items[k].text, text) > 0) {
                        i = k;
                        break;
                    }
            add_item(w, i, text);
            if (w->sel >= i)
                w->sel++;
            return (uint32_t)i;
        }
        if (msg == (cb ? 0x145u : 0x18Du)) {                   /* DIR: list the files matching a pattern (the installed folder's and the overlay's together) */
            char spec[600], folder[600], *slash;
            DirList dl;

            paths_normalize(P(lp), spec, sizeof(spec));
            slash = strrchr(spec, '\\');
            snprintf(dl.pattern, sizeof(dl.pattern), "%s", slash + 1);
            for (char *c = dl.pattern; *c; c++)
                if (*c >= 'a' && *c <= 'z')
                    *c = (char)(*c - 32);
            snprintf(folder, sizeof(folder), "%.*s", (int)(slash - spec), spec);
            dl.w = w;
            dl.found = 0;
            paths_list(folder, dir_entry, &dl);
            if (sorted && w->nitems > 1)
                qsort(w->items, (size_t)w->nitems, sizeof(*w->items), item_text_less);
            return dl.found ? (uint32_t)(w->nitems - 1) : 0xFFFFFFFFu;
        }
        if (msg == (cb ? 0x14Au : 0x181u)) {                   /* INSERTSTRING */
            int i = (int32_t)wp < 0 ? w->nitems : (int)wp;

            if (i > w->nitems)
                i = w->nitems;
            add_item(w, i, P(lp));
            return (uint32_t)i;
        }
        if (msg == (cb ? 0x144u : 0x182u)) {                   /* DELETESTRING */
            if (IDX_OK(wp)) {
                free(w->items[wp].text);
                memmove(&w->items[wp], &w->items[wp + 1], (size_t)(w->nitems - (int)wp - 1) * sizeof(*w->items));
                w->nitems--;
            }
            return (uint32_t)w->nitems;
        }
        if (msg == (cb ? 0x14Bu : 0x184u)) {                   /* RESETCONTENT */
            int i;

            for (i = 0; i < w->nitems; i++)
                free(w->items[i].text);
            w->nitems = 0;
            w->sel = -1;
            return 0;
        }
        if (!cb && msg == 0x197) {                             /* LB_SETTOPINDEX */
            w->top = IDX_OK(wp) ? (int)wp : 0;
            return 0;
        }
        if (!cb && msg == 0x18E)                               /* LB_GETTOPINDEX */
            return (uint32_t)w->top;
        if (msg == (cb ? 0x146u : 0x18Bu))                     /* GETCOUNT */
            return (uint32_t)w->nitems;
        if (msg == (cb ? 0x14Eu : 0x186u)) {                   /* SETCURSEL */
            w->sel = IDX_OK(wp) ? (int32_t)wp : -1;
            return w->sel >= 0 ? (uint32_t)w->sel : 0xFFFFFFFFu;
        }
        if (msg == (cb ? 0x147u : 0x188u))                     /* GETCURSEL */
            return (uint32_t)w->sel;
        if (msg == (cb ? 0x148u : 0x189u)) {                   /* GETLBTEXT */
            if (IDX_OK(wp)) {
                put_cstr(lp, w->items[wp].text, strlen(w->items[wp].text));
                return (uint32_t)strlen(w->items[wp].text);
            }
            return 0xFFFFFFFFu;
        }
        if (msg == (cb ? 0x149u : 0x18Au))                     /* GETLBTEXTLEN */
            return IDX_OK(wp) ? (uint32_t)strlen(w->items[wp].text) : 0xFFFFFFFFu;
        if (msg == (cb ? 0x150u : 0x199u))                     /* GETITEMDATA */
            return IDX_OK(wp) ? w->items[wp].data : 0xFFFFFFFFu;
        if (msg == (cb ? 0x151u : 0x19Au)) {                   /* SETITEMDATA */
            if (IDX_OK(wp)) {
                w->items[wp].data = lp;
                return 1;
            }
            return 0xFFFFFFFFu;
        }
        if (msg == (cb ? 0x14Cu : 0x18Fu) || msg == (cb ? 0x14Du : 0x18Cu)) {     /* FINDSTRING / SELECTSTRING */
            const char *want = P(lp);
            int i;

            for (i = 0; i < w->nitems; i++)
                if (!strncasecmp(w->items[i].text, want, strlen(want))) {
                    if (msg == (cb ? 0x14Du : 0x18Cu))
                        w->sel = i;
                    return (uint32_t)i;
                }
            return 0xFFFFFFFFu;
        }
    }
    return 0;
}

/* ---- dialog items ------------------------------------------------------------------------------------------------------------- */
Window *wm_dlg_item(uint32_t hdlg, uint32_t id)
{
    int i, n = wm_window_count();

    if (!wm_window(hdlg))
        return NULL;
    for (i = 0; i < n; i++) {
        Window *c = wm_window_at_index(i);

        if (c && c->parent == hdlg && c->id == id)
            return c;
    }
    return NULL;
}

static uint32_t GetDlgItem(const uint32_t *a) { Window *c = wm_dlg_item(a[0], a[1]); return c ? c->hwnd : 0; }

static uint32_t SendDlgItemMessageA(const uint32_t *a)
{
    Window *c = wm_dlg_item(a[0], a[1]);

    return c ? wm_send(c->hwnd, a[2], a[3], a[4]) : 0;
}

static uint32_t SetDlgItemTextA(const uint32_t *a)
{
    Window *c = wm_dlg_item(a[0], a[1]);

    if (c) {
        free(c->title);
        c->title = strdup(P(a[2]));
    }
    return 1;
}

static uint32_t GetDlgItemTextA(const uint32_t *a)
{
    Window *c = wm_dlg_item(a[0], a[1]);
    size_t n = c ? strlen(c->title) : 0;

    if (a[3] == 0)
        return 0;
    if (n > a[3] - 1)
        n = a[3] - 1;
    put_cstr(a[2], c ? c->title : "", n);
    return (uint32_t)n;
}

static uint32_t SetDlgItemInt(const uint32_t *a)
{
    Window *c = wm_dlg_item(a[0], a[1]);

    if (c) {
        char buf[32];

        snprintf(buf, sizeof(buf), a[3] ? "%d" : "%u", a[3] ? (int)a[2] : (int)0);
        if (!a[3])
            snprintf(buf, sizeof(buf), "%u", a[2]);
        free(c->title);
        c->title = strdup(buf);
    }
    return 1;
}

static uint32_t GetDlgItemInt(const uint32_t *a)
{
    Window *c = wm_dlg_item(a[0], a[1]);
    long v = c ? atol(c->title) : 0;

    if (a[2])
        WR32(a[2], 1);
    return (uint32_t)v;
}

static uint32_t CheckDlgButton(const uint32_t *a) { Window *c = wm_dlg_item(a[0], a[1]); if (c) c->checked = (int)a[2]; return 1; }
static uint32_t IsDlgButtonChecked(const uint32_t *a) { Window *c = wm_dlg_item(a[0], a[1]); return c ? (uint32_t)c->checked : 0; }

static uint32_t CheckRadioButton(const uint32_t *a)
{
    uint32_t id;

    for (id = a[1]; id <= a[2]; id++) {
        Window *c = wm_dlg_item(a[0], id);

        if (c)
            c->checked = id == a[3];
    }
    return 1;
}

/* What Windows does by itself when an automatic button is clicked, before it tells the parent (BN_CLICKED): an automatic check box (BS_AUTOCHECKBOX
 * 3, BS_AUTO3STATE 6) flips, an automatic radio button (BS_AUTORADIOBUTTON 9) becomes the checked one of its group: the controls from the one with
 * WS_GROUP at or before it up to the next one with WS_GROUP, in creation order. The game relies on it (the setup dialog's Gauntlet / Single Duel). */
void wm_button_auto_check(Window *w)
{
    int kind = (int)(w->style & 0xF), i, n = wm_window_count(), at = -1, lo, hi;

    if (kind == 3) {
        w->checked = !w->checked;
        return;
    }
    if (kind == 6) {
        w->checked = (w->checked + 1) % 3;
        return;
    }
    if (kind != 9)
        return;
    for (i = 0; i < n; i++)
        if (wm_window_at_index(i) == w)
            at = i;
    if (at < 0)
        return;
    for (lo = at; lo > 0; lo--) {
        Window *c = wm_window_at_index(lo);

        if (c->parent == w->parent && (c->style & 0x20000u))
            break;
    }
    for (hi = at + 1; hi < n; hi++) {
        Window *c = wm_window_at_index(hi);

        if (c->parent == w->parent && (c->style & 0x20000u))
            break;
    }
    for (i = lo; i < hi; i++) {
        Window *c = wm_window_at_index(i);

        if (c->parent == w->parent && !c->proc && (c->style & 0xF) == 9)
            c->checked = c == w;
    }
}

/* ---- drop-down combo boxes ----------------------------------------------------------------------------------------------------- */
/* Clicking the closed box puts the list down (CBN_DROPDOWN); the list takes the mouse and the keys until it is closed: a click on a row chooses it
 * (CBN_SELCHANGE, CBN_SELENDOK, CBN_CLOSEUP), a click anywhere else closes it (CBN_SELENDCANCEL, CBN_CLOSEUP). The pointer highlights the row under it; Up, Down, PageUp,
 * PageDown, Home, End and letters move the choice (a CBN_SELCHANGE each), Enter accepts, Esc goes back to the choice from before; the wheel and the scroll bar scroll. */
static uint32_t combo_hwnd;
static int combo_drag;                                          /* the left button is holding the scroll bar's thumb */

int wm_combo_open(void) { return combo_hwnd && wm_window(combo_hwnd) ? (int)combo_hwnd : 0; }

static void combo_notify(Window *w, uint32_t code) { wm_post(w->parent, WM_COMMAND, (code << 16) | (w->id & 0xFFFF), w->hwnd); }

static void combo_close(Window *w)
{
    w->dropped = 0;
    combo_hwnd = 0;
    combo_drag = 0;
    wm_dirty = 1;
}

static int combo_rows(Window *w)
{
    int x0, y0, x1, y1, rowh, rows;

    ui_combo_geometry(w, &x0, &y0, &x1, &y1, &rowh, &rows);
    return rows;
}

static void combo_show(Window *w, int item)                    /* scroll so that `item` is in the list */
{
    int rows = combo_rows(w);

    if (item < w->top)
        w->top = item;
    if (item >= w->top + rows)
        w->top = item - rows + 1;
    if (w->top > w->nitems - rows)
        w->top = w->nitems - rows;
    if (w->top < 0)
        w->top = 0;
}

void wm_combo_drop(Window *w)
{
    if (!w->enabled || w->nitems < 1)
        return;
    if (combo_hwnd && combo_hwnd != w->hwnd && wm_window(combo_hwnd))
        combo_close(wm_window(combo_hwnd));
    w->dropped = 1;
    w->orig_sel = w->sel;
    w->hot = w->sel;
    w->top = 0;
    combo_hwnd = w->hwnd;
    combo_show(w, w->sel < 0 ? 0 : w->sel);
    combo_notify(w, 7);                                         /* CBN_DROPDOWN */
    wm_dirty = 1;
}

static void combo_choose(Window *w, int item)                  /* the choice moves to `item` */
{
    if (item < 0 || item >= w->nitems)
        return;
    w->hot = item;
    combo_show(w, item);
    if (w->sel != item) {
        w->sel = item;
        combo_notify(w, 1);                                     /* CBN_SELCHANGE */
    }
    wm_dirty = 1;
}

static void combo_finish(Window *w, int accept)
{
    if (!accept && w->sel != w->orig_sel) {
        w->sel = w->orig_sel;
        combo_notify(w, 1);
    }
    combo_notify(w, accept ? 9u : 10u);                         /* CBN_SELENDOK / CBN_SELENDCANCEL */
    combo_close(w);
    combo_notify(w, 8);                                         /* CBN_CLOSEUP */
}

static int combo_scroll_to(Window *w, int rows, int y, int y0, int y1)       /* the thumb follows the pointer on the bar's track */
{
    int track = y1 - y0 - 2 * 16, span = w->nitems - rows;

    if (track <= 0 || span <= 0)
        return 0;
    w->top = (y - y0 - 16) * span / track;
    if (w->top < 0)
        w->top = 0;
    if (w->top > span)
        w->top = span;
    wm_dirty = 1;
    return 1;
}

int wm_combo_mouse(int kind, int x, int y)
{
    Window *w = wm_window(combo_hwnd);
    int lx0, ly0, lx1, ly1, rowh, rows, inside, bx0, by0, bx1, by1;

    if (!w)
        return combo_hwnd = 0;
    ui_combo_geometry(w, &lx0, &ly0, &lx1, &ly1, &rowh, &rows);
    wm_abs_rect(w, &bx0, &by0, &bx1, &by1);
    inside = x >= lx0 && x < lx1 && y >= ly0 && y < ly1;
    if (kind == IN_UP || kind == IN_RUP) {
        combo_drag = 0;
        return 1;
    }
    if (kind == IN_MOVE) {
        if (combo_drag)
            combo_scroll_to(w, rows, y, ly0 + 1, ly1 - 1);
        else if (inside && x < (w->nitems > rows ? lx1 - 17 : lx1 - 1)) {
            int k = w->top + (y - ly0 - 1) / rowh;

            if (k >= 0 && k < w->nitems && k != w->hot) {
                w->hot = k;
                wm_dirty = 1;
            }
        }
        return 1;
    }
    if (kind == IN_RDOWN) {
        combo_finish(w, 0);
        return 1;
    }
    /* IN_DOWN */
    if (inside && w->nitems > rows && x >= lx1 - 17) {            /* the scroll bar */
        if (y < ly0 + 1 + 16)
            w->top = w->top > 0 ? w->top - 1 : 0;
        else if (y >= ly1 - 1 - 16)
            w->top = w->top < w->nitems - rows ? w->top + 1 : w->top;
        else {
            combo_drag = 1;
            combo_scroll_to(w, rows, y, ly0 + 1, ly1 - 1);
        }
        wm_dirty = 1;
        return 1;
    }
    if (inside) {
        int k = w->top + (y - ly0 - 1) / rowh;

        if (k >= 0 && k < w->nitems) {
            combo_choose(w, k);
            combo_finish(w, 1);
        }
        return 1;
    }
    if (x >= bx0 && x < bx1 && y >= by0 && y < by1) {            /* the closed box again: closes the list, keeping the choice made so far */
        combo_finish(w, 1);
        return 1;
    }
    combo_finish(w, 0);
    return 1;
}

/* A press on a list box: the row becomes the choice (LBN_SELCHANGE), a second press on it within half a second is a double click (LBN_DBLCLK). */
void wm_listbox_click(Window *w, int y)
{
    static uint32_t last_hwnd, last_t;
    static int last_row;
    int k = ui_listbox_row(w, y);
    uint32_t now = port_now_ms();

    if (!w->enabled || k < 0 || k >= w->nitems)
        return;
    w->sel = k;
    wm_dirty = 1;
    wm_post(w->parent, WM_COMMAND, (1u << 16) | (w->id & 0xFFFF), w->hwnd);
    if (last_hwnd == w->hwnd && last_row == k && now - last_t <= 500) {
        wm_post(w->parent, WM_COMMAND, (2u << 16) | (w->id & 0xFFFF), w->hwnd);
        last_hwnd = 0;
    } else {
        last_hwnd = w->hwnd;
        last_row = k;
        last_t = now;
    }
}

void wm_combo_wheel(int clicks)
{
    Window *w = wm_window(combo_hwnd);

    if (w) {
        w->top -= clicks * 3;
        combo_show(w, w->top);
        wm_dirty = 1;
    }
}

int wm_combo_key(uint32_t vk, int down, int ch)
{
    Window *w = wm_window(combo_hwnd);
    int rows, k, n;

    if (!w)
        return 0;
    if (!down)
        return 1;
    rows = combo_rows(w);
    k = w->hot < 0 ? 0 : w->hot;
    if (vk == 0x0D) {
        combo_finish(w, 1);
    } else if (vk == 0x1B) {
        combo_finish(w, 0);
    } else if (vk == 0x26 || vk == 0x28 || vk == 0x21 || vk == 0x22 || vk == 0x24 || vk == 0x23) {
        k = vk == 0x26 ? k - 1 : vk == 0x28 ? k + 1 : vk == 0x21 ? k - rows + 1 : vk == 0x22 ? k + rows - 1 : vk == 0x24 ? 0 : w->nitems - 1;
        combo_choose(w, k < 0 ? 0 : k >= w->nitems ? w->nitems - 1 : k);
    } else if (ch >= 32 && ch < 127) {                           /* the next row that starts with the letter */
        for (n = 1; n <= w->nitems; n++) {
            int i = (k + n) % w->nitems;

            if (toupper((unsigned char)w->items[i].text[0]) == toupper(ch)) {
                combo_choose(w, i);
                break;
            }
        }
    }
    return 1;
}

static uint32_t EndDialog(const uint32_t *a)
{
    Window *w = wm_window(a[0]);

    if (w) {
        w->ended = 1;
        w->result = a[1];
    }
    return 1;
}

/* ---- dialog templates: DLGTEMPLATE and the extended DLGTEMPLATEEX -------------------------------------------------------------- */
typedef struct DlgItem {
    uint32_t style, exstyle, id;
    int x, y, cx, cy;
    char cls[64], text[2048];
} DlgItem;

typedef struct Dlg {
    char title[128];
    uint32_t style, exstyle;
    int x, y, cx, cy, count, pt;      /* pt: the font's point size (DS_SETFONT), 0 for the system font */
    char face[40];
    DlgItem *items;
} Dlg;

static uint16_t rd16(const uint8_t *d, uint32_t o) { return (uint16_t)(d[o] | d[o + 1] << 8); }
static uint32_t rd32(const uint8_t *d, uint32_t o) { return (uint32_t)d[o] | (uint32_t)d[o + 1] << 8 | (uint32_t)d[o + 2] << 16 | (uint32_t)d[o + 3] << 24; }

/* A UTF-16 string at d+o into out (as Latin-1); returns the offset after its terminator. */
static uint32_t wstr(const uint8_t *d, uint32_t o, char *out, size_t cap)
{
    size_t n = 0;

    for (;;) {
        uint16_t c = rd16(d, o);

        o += 2;
        if (!c)
            break;
        if (n + 1 < cap)
            out[n++] = (char)(c < 256 ? c : '?');
    }
    out[n] = 0;
    return o;
}

/* An ordinal (0xFFFF, n) or a string, as the menu / class / title fields of a template are: ordinal in *ord (or -1), string in out. */
static uint32_t ordinal_or_str(const uint8_t *d, uint32_t o, int *ord, char *out, size_t cap)
{
    *ord = -1;
    out[0] = 0;
    if (rd16(d, o) == 0xFFFF) {
        *ord = rd16(d, o + 2);
        return o + 4;
    }
    if (rd16(d, o) == 0)
        return o + 2;
    return wstr(d, o, out, cap);
}

static void parse_dialog(const uint8_t *d, Dlg *out)
{
    int ext = rd16(d, 0) == 1 && rd16(d, 2) == 0xFFFF, ord, i;
    uint32_t o;
    char tmp[64];

    memset(out, 0, sizeof(*out));
    if (ext) {
        out->exstyle = rd32(d, 8);
        out->style = rd32(d, 12);
        out->count = rd16(d, 16);
        out->x = (int16_t)rd16(d, 18); out->y = (int16_t)rd16(d, 20); out->cx = (int16_t)rd16(d, 22); out->cy = (int16_t)rd16(d, 24);
        o = 26;
    } else {
        out->style = rd32(d, 0);
        out->exstyle = rd32(d, 4);
        out->count = rd16(d, 8);
        out->x = (int16_t)rd16(d, 10); out->y = (int16_t)rd16(d, 12); out->cx = (int16_t)rd16(d, 14); out->cy = (int16_t)rd16(d, 16);
        o = 18;
    }
    o = ordinal_or_str(d, o, &ord, tmp, sizeof(tmp));                 /* menu */
    o = ordinal_or_str(d, o, &ord, tmp, sizeof(tmp));                 /* window class */
    o = wstr(d, o, out->title, sizeof(out->title));
    if (out->style & 0x40) {                                          /* DS_SETFONT */
        out->pt = rd16(d, o);
        o += 2;
        if (ext)
            o += 4;
        o = wstr(d, o, out->face, sizeof(out->face));
    }
    out->items = calloc((size_t)out->count + 1, sizeof(DlgItem));
    for (i = 0; i < out->count; i++) {
        DlgItem *it = &out->items[i];
        int cord;
        static const char *const names[] = {"BUTTON", "EDIT", "STATIC", "LISTBOX", "SCROLLBAR", "COMBOBOX"};
        uint32_t extra;

        o = (o + 3) & ~3u;
        if (ext) {
            it->exstyle = rd32(d, o + 4); it->style = rd32(d, o + 8);
            it->x = (int16_t)rd16(d, o + 12); it->y = (int16_t)rd16(d, o + 14); it->cx = (int16_t)rd16(d, o + 16); it->cy = (int16_t)rd16(d, o + 18);
            it->id = rd32(d, o + 20);
            o += 24;
        } else {
            it->style = rd32(d, o); it->exstyle = rd32(d, o + 4);
            it->x = (int16_t)rd16(d, o + 8); it->y = (int16_t)rd16(d, o + 10); it->cx = (int16_t)rd16(d, o + 12); it->cy = (int16_t)rd16(d, o + 14);
            it->id = rd16(d, o + 16);
            o += 18;
        }
        o = ordinal_or_str(d, o, &cord, it->cls, sizeof(it->cls));
        if (cord >= 0x80 && cord <= 0x85)
            snprintf(it->cls, sizeof(it->cls), "%s", names[cord - 0x80]);
        else if (cord >= 0)
            snprintf(it->cls, sizeof(it->cls), "#%d", cord);
        o = ordinal_or_str(d, o, &ord, it->text, sizeof(it->text));
        extra = rd16(d, o);
        o += 2 + extra;
    }
}

/* What the dialog's own procedure says about the colours of its controls (WM_CTLCOLORSTATIC and the rest: a text colour, a background brush, or a null brush for text
 * over its artwork), asked once the dialog has been set up. Windows asks again every time a control is drawn; the answers the game gives do not change. */
void wm_query_ctl_colors(Window *dlg, Window *c)
{
    uint32_t msg, hdc, brush;

    if (!c || !c->cname)
        return;
    if (!strcasecmp(c->cname, "STATIC"))
        msg = 0x138;
    else if (!strcasecmp(c->cname, "BUTTON"))
        msg = 0x135;
    else if (!strcasecmp(c->cname, "EDIT"))
        msg = 0x133;
    else if (!strcasecmp(c->cname, "LISTBOX"))
        msg = 0x134;
    else
        return;
    hdc = gdi_color_query_dc();
    brush = wm_send(dlg->hwnd, msg, hdc, c->hwnd);
    gdi_color_query_result(hdc, brush, c->ctl_fg, c->ctl_bg, &c->ctl_transparent, &c->ctl_has_bg);
    c->ctl_has_fg = 1;
    c->ctl_valid = 1;
}

static void ctl_colors(Window *dlg)
{
    int i, n = wm_window_count();

    for (i = 0; i < n; i++) {
        Window *c = wm_window_at_index(i);

        if (!c || c->parent != dlg->hwnd || !c->cname)
            continue;
        wm_query_ctl_colors(dlg, c);
    }
}

static uint32_t dialog_stack[8];
static int ndialogs;

/* Make the dialog a template (in host memory) describes: its window and controls, then WM_INITDIALOG to `proc` (a guest address) and the colours its controls are given. A modal dialog
 * (DialogBox) is shown at once, centred, and put on the dialog stack; a modeless one (CreateDialog) is shown only if its template says WS_VISIBLE, and a child window (the Magic Shell's
 * pages are WS_CHILD dialogs inside its main window) is where the template puts it in its parent. */
static Window *dialog_make(const uint8_t *tmpl_bytes, uint32_t tmpl, uint32_t parent, uint32_t proc, uint32_t param, int modal)
{
    uint32_t hdlg, first = 0, args[4];
    Dlg dd;
    Window *win;
    int i, w, h, bx, by, cw, ch, child;
    uint32_t dlg_font = 0;

    parse_dialog(tmpl_bytes, &dd);
    child = (dd.style & WS_CHILD) != 0 && !modal;
    {   /* dialog units: a quarter of the font's average character width across, an eighth of its height down (the system font's 8 x 16 without DS_SETFONT) */
        int height = 16, avg = 8, nl = 0, nt = 0;
        const char *face = dd.pt ? dd.face : "MS Sans Serif";

        if (dd.pt)
            ui_font_metrics(face, dd.pt, 0, &height, NULL, &avg);
        bx = avg;
        by = height;
        if (getenv("PORT_DLU") && dd.pt) sscanf(getenv("PORT_DLU"), "%dx%d", &bx, &by);
        /* the frame Windows 98 draws round a dialog: a one-pixel border, or the three-pixel dialog frame with a 19-pixel caption */
        if ((dd.style & 0xC00000u) == 0xC00000u || (dd.exstyle & 1u) || (dd.style & 0x80u))
            nl = 3;
        else if (dd.style & 0x800000u)
            nl = 1;
        if ((dd.style & 0xC00000u) == 0xC00000u)
            nt = nl + 19;
        else
            nt = nl;
        cw = ui_dlu_x(dd.cx, bx);
        ch = ui_dlu_y(dd.cy, by);
        w = cw + 2 * nl;
        h = ch + nt + nl;
        {   /* a template at 0, 0 is centred on the screen, and moved so that its top left corner stays visible when it is bigger (the Stats window is wider than 640); a child is where it says */
            int px = (screen_w - w) / 2, py = (screen_h - h) / 2;

            if (child) {
                px = ui_dlu_x(dd.x, bx);
                py = ui_dlu_y(dd.y, by);
            }
            px = px < 0 && !child ? 0 : px;
            py = py < 0 && !child ? 0 : py;
            win = wm_new_window("#32770", parent, dd.style, dd.exstyle, px, py, w, h, dd.title, 0, param);
        }
        win->nc_l = win->nc_r = win->nc_b = nl;
        win->nc_t = nt;
        win->dlg_pt = dd.pt ? dd.pt : 8;
        snprintf(win->dlg_face, sizeof(win->dlg_face), "%s", dd.pt ? dd.face : "MS Sans Serif");
        gdi_resize_surface(win);             /* the surface covers the client area, now that the frame is known */
    }
    win->dlgproc = proc;
    win->visible = modal || (dd.style & WS_VISIBLE) != 0;
    win->ended = 0;
    win->is_dialog = modal;
    win->invalid = win->erase = 1;       /* a dialog is drawn when it is shown (those that paint themselves, like the deck builder's Stats, do it on WM_PAINT) */
    hdlg = win->hwnd;
    if (dd.pt)                           /* DS_SETFONT: Windows makes the dialog's font and sets it on every control */
        dlg_font = gdi_dialog_font(dd.face, dd.pt);
    win->hfont = dlg_font;
    for (i = 0; i < dd.count; i++) {
        DlgItem *it = &dd.items[i];
        Window *c = wm_new_window(it->cls, hdlg, it->style, it->exstyle, ui_dlu_x(it->x, bx), ui_dlu_y(it->y, by), ui_dlu_x(it->cx, bx), ui_dlu_y(it->cy, by), it->text, it->id, 0);

        c->id = it->id;
        c->hfont = dlg_font;
        c->visible = (it->style & WS_VISIBLE) != 0;
        c->checked = 0;
        if (!first && (it->style & WS_TABSTOP))
            first = c->hwnd;
    }
    if (modal && ndialogs < 8)
        dialog_stack[ndialogs++] = hdlg;
    port_trace("%s: template %u '%s' with %d controls, proc 0x%08x", modal ? "DialogBoxParam" : "CreateDialogParam", tmpl, dd.title, dd.count, proc);
    free(dd.items);
    args[0] = hdlg; args[1] = WM_INITDIALOG; args[2] = first; args[3] = param;
    guest_call(proc, 4, args);
    ctl_colors(win);
    return win;
}

/* Run the modal dialog: its window and controls are made, `proc` gets WM_INITDIALOG, and the messages are served until EndDialog; returns EndDialog's result. DialogBoxParamA reads the
 * template from the program's resources, the file dialogs (filedlg.c) build theirs. */
uint32_t wm_dialog_box(const uint8_t *tmpl_bytes, uint32_t tmpl, uint32_t parent, uint32_t proc, uint32_t param)
{
    Window *win = dialog_make(tmpl_bytes, tmpl, parent, proc, param, 1);
    uint32_t hdlg = win->hwnd;

    while (!win->ended) {
        uint32_t msgbuf[7];
        extern int wm_next_message_for(uint32_t *out);

        wm_process_sent();
        if (wm_pump_hook)
            wm_pump_hook();
        if (wm_next_message_for(msgbuf)) {
            if (msgbuf[1] == WM_TIMER && msgbuf[3]) {
                uint32_t targs[4] = {msgbuf[0], WM_TIMER, msgbuf[2], port_now_ms()};

                guest_call(msgbuf[3], 4, targs);
            } else
                wm_send(msgbuf[0], msgbuf[1], msgbuf[2], msgbuf[3]);
            continue;
        }
        sched_sleep(0.003);
    }
    ndialogs--;
    {
        uint32_t r = win->result;

        wm_destroy(hdlg);
        return r;
    }
}

static uint32_t DialogBoxParamA(const uint32_t *a)
{
    uint32_t addr, size;

    if (!pe_find_resource(a[0], 5, a[1], &addr, &size)) {
        port_trace("DialogBoxParam(template=%u): no such resource", a[1]);
        return 0xFFFFFFFFu;
    }
    return wm_dialog_box(G + addr, a[1], a[2], a[3], a[4]);
}

/* CreateDialogParamA(instance, template, parent, procedure, parameter): the same dialog, modeless: the window is returned (0, and the last error ERROR_RESOURCE_NAME_NOT_FOUND, if the
 * template is not in the program) and the caller's own message loop serves it. */
static uint32_t CreateDialogParamA(const uint32_t *a)
{
    uint32_t addr, size;
    Window *win;

    if (!pe_find_resource(a[0], 5, a[1], &addr, &size)) {
        port_trace("CreateDialogParam(template=%s): no such resource", a[1] > 0xFFFF ? P(a[1]) : "(number)");
        k32_set_last_error(1814);                          /* ERROR_RESOURCE_NAME_NOT_FOUND */
        return 0;
    }
    win = dialog_make(G + addr, a[1], a[2], a[3], a[4], 0);
    return win->hwnd;
}

/* The tab stops of a dialog in the order the template gave them (the order the controls were made in): the next (or previous) one that can take the focus after `from`, or `from`. */
static uint32_t next_tab_stop(Window *dlg, uint32_t from, int back)
{
    int i, n = wm_window_count(), at = -1, step = back ? -1 : 1, k;

    for (i = 0; i < n; i++) {
        Window *c = wm_window_at_index(i);

        if (c && c->hwnd == from)
            at = i;
    }
    for (k = 1; k <= n; k++) {
        int j = ((at < 0 ? (back ? n : -1) : at) + step * k % n + n) % n;
        Window *c = wm_window_at_index(j);

        if (c && c->parent == dlg->hwnd && (c->style & WS_TABSTOP) && c->visible && c->enabled)
            return c->hwnd;
    }
    return from;
}

/* IsDialogMessageA(dialog, &msg): the keyboard interface of a modeless dialog, for a message that is for the dialog or one of its controls. Esc is IDCANCEL, Enter presses the default push
 * button (the focused one, if it is a push button, else the one the template made the default, else IDOK), Tab and Shift+Tab move between the tab stops; the key is then used up (TRUE).
 * Any other message is the caller's to translate and dispatch (FALSE). */
static uint32_t IsDialogMessageA(const uint32_t *a)
{
    Window *dlg = wm_window(a[0]), *target;
    uint32_t hwnd = RD32(a[1]), msg = RD32(a[1] + 4), wp = RD32(a[1] + 8), id = 0;
    int is_in = 0;

    if (!dlg)
        return 0;
    for (target = wm_window(hwnd); target; target = target->parent ? wm_window(target->parent) : NULL)
        if (target->hwnd == dlg->hwnd) {
            is_in = 1;
            break;
        }
    if (!is_in || msg != WM_KEYDOWN)
        return 0;
    if (wp == 0x1B) {                                                           /* VK_ESCAPE */
        wm_post(dlg->hwnd, WM_COMMAND, 2u, 0);
        return 1;
    }
    if (wp == 0x0D) {                                                           /* VK_RETURN */
        Window *f = wm_window(hwnd), *def = NULL;
        int i, n = wm_window_count();

        if (f && f != dlg && !strcasecmp(f->cname, "BUTTON") && ((f->style & 0xF) == 0 || (f->style & 0xF) == 1)) {
            wm_post(dlg->hwnd, WM_COMMAND, f->id & 0xFFFFu, f->hwnd);
            return 1;
        }
        for (i = 0; i < n && !def; i++) {
            Window *c = wm_window_at_index(i);

            if (c && c->parent == dlg->hwnd && !strcasecmp(c->cname, "BUTTON") && (c->style & 0xF) == 1 && c->visible && c->enabled)
                def = c;
        }
        id = def ? def->id : 1u;
        wm_post(dlg->hwnd, WM_COMMAND, id & 0xFFFFu, def ? def->hwnd : 0);
        return 1;
    }
    if (wp == 0x09) {                                                           /* VK_TAB: Shift moves backwards */
        uint32_t to = next_tab_stop(dlg, hwnd, wm_keys[0x10] != 0);

        if (to && to != hwnd)
            wm_set_focus(to);
        return 1;
    }
    return 0;
}

uint32_t wm_top_dialog(void) { return ndialogs ? dialog_stack[ndialogs - 1] : 0; }
int wm_dialog_count(void) { return ndialogs; }
uint32_t wm_dialog_at(int i) { return dialog_stack[i]; }

/* Host input: click a button in the topmost dialog (a WM_COMMAND with BN_CLICKED to its procedure). */
int wm_press_dialog_button(uint32_t id)
{
    uint32_t h = wm_top_dialog();
    Window *c = h ? wm_dlg_item(h, id) : NULL;

    if (!c || !c->visible)
        return 0;
    wm_post(h, WM_COMMAND, id & 0xFFFF, c->hwnd);
    return 1;
}


static uint32_t wsprintfA(const uint32_t *a)
{
    /* cdecl: (buffer, format, ...): the arguments follow on the stack, which lift_call copied to a[2...] */
    return (uint32_t)c_format(P(a[0]), 4096, P(a[1]), (uint32_t)(port_sp + 4 + 8));
}

/* ---- scroll bars --------------------------------------------------------------------------------------------------------------- */
static int *scroll(Window *w, uint32_t bar) { return w->scroll[bar & 3]; }
static uint32_t SetScrollRange(const uint32_t *a)
{
    Window *w = wm_window(a[0]);

    if (w) {
        int *sc = scroll(w, a[1]);

        sc[0] = (int32_t)a[2];
        sc[1] = (int32_t)a[3];
        sc[2] = sc[2] < sc[0] ? sc[0] : sc[2] > sc[1] ? sc[1] : sc[2];
    }
    return 1;
}
static uint32_t GetScrollRange(const uint32_t *a)
{
    Window *w = wm_window(a[0]);
    int *sc = w ? scroll(w, a[1]) : (int[3]){0, 0, 0};

    WR32(a[2], (uint32_t)sc[0]);
    WR32(a[3], (uint32_t)sc[1]);
    return 1;
}
static uint32_t SetScrollPos(const uint32_t *a)
{
    Window *w = wm_window(a[0]);
    int *sc, old, v = (int32_t)a[2];

    if (!w)
        return 0;
    sc = scroll(w, a[1]);
    old = sc[2];
    sc[2] = v < sc[0] ? sc[0] : v > sc[1] ? sc[1] : v;
    return (uint32_t)old;
}
static uint32_t GetScrollPos(const uint32_t *a)
{
    Window *w = wm_window(a[0]);

    return w ? (uint32_t)scroll(w, a[1])[2] : 0;
}
static uint32_t zero(const uint32_t *a) { (void)a; return 0; }

const WinApi CONTROLS_APIS[] = {
    {"user32.dll", "GetDlgItem", GetDlgItem}, {"user32.dll", "SendDlgItemMessageA", SendDlgItemMessageA},
    {"user32.dll", "SetDlgItemTextA", SetDlgItemTextA}, {"user32.dll", "GetDlgItemTextA", GetDlgItemTextA},
    {"user32.dll", "SetDlgItemInt", SetDlgItemInt}, {"user32.dll", "GetDlgItemInt", GetDlgItemInt},
    {"user32.dll", "CheckDlgButton", CheckDlgButton}, {"user32.dll", "IsDlgButtonChecked", IsDlgButtonChecked},
    {"user32.dll", "CheckRadioButton", CheckRadioButton}, {"user32.dll", "EndDialog", EndDialog},
    {"user32.dll", "DialogBoxParamA", DialogBoxParamA}, {"user32.dll", "CreateDialogParamA", CreateDialogParamA}, {"user32.dll", "IsDialogMessageA", IsDialogMessageA}, {"user32.dll", "wsprintfA", wsprintfA},
    {"user32.dll", "SetScrollRange", SetScrollRange}, {"user32.dll", "GetScrollRange", GetScrollRange},
    {"user32.dll", "SetScrollPos", SetScrollPos}, {"user32.dll", "GetScrollPos", GetScrollPos}, {"user32.dll", "LoadBitmapA", zero},
    {0, 0, 0},
};

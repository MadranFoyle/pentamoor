/* user32.c - window classes, windows, the message queue and its pump, timers. Port of winemu/user32.py. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "gdi.h"
#include "gdi_int.h"
#include "sched.h"
#include "wm.h"
#include "movie.h"

#define P(a) ((char *)(G + (a)))
#define HWND_BASE 0x10010u

/* ---- state ---------------------------------------------------------------------------------------------------------------------- */
static Class *classes;
static int nclasses, capclasses;
static Window **windows;            /* by (hwnd - HWND_BASE) / 4; destroyed windows leave NULL */
static int nwindows, capwindows;
static uint32_t next_hwnd = HWND_BASE;
static double zcount;

typedef struct Msg { uint32_t hwnd, msg, wp, lp; } Msg;
static Msg *queue;
static int nqueue, capqueue;

typedef struct Timer { uint32_t hwnd, id, delay, proc, next; int used; } Timer;
static Timer *timers;
static int ntimers, captimers;

typedef struct Sent { uint32_t hwnd, msg, wp, lp, result, tid; int done, running; } Sent;
static Sent *sent[64];
static int nsent;

int wm_dirty;
int wm_cursor_x = 320, wm_cursor_y = 240;
uint8_t wm_keys[256];
void (*wm_pump_hook)(void);
static int quit_all = -1;              /* the host asked the program to stop (window closed): -1 when not */
static uint32_t focus_hwnd, active_hwnd, capture_hwnd, desktop_hwnd;
static uint32_t last_error;

int wm_window_count(void) { return nwindows; }
Window *wm_window_at_index(int i) { return i >= 0 && i < nwindows ? windows[i] : NULL; }

Window *wm_window(uint32_t hwnd)
{
    uint32_t i;

    if (hwnd < HWND_BASE || (hwnd - HWND_BASE) % 4)
        return NULL;
    i = (hwnd - HWND_BASE) / 4;
    return i < (uint32_t)nwindows ? windows[i] : NULL;
}

char *wm_strdup_guest(uint32_t addr)
{
    return strdup(P(addr));
}

static char *lower_dup(const char *s)
{
    char *r = strdup(s), *p;

    for (p = r; *p; p++)
        if (*p >= 'A' && *p <= 'Z')
            *p += 32;
    return r;
}

static Class *find_class(const char *name)
{
    int i;

    for (i = 0; i < nclasses; i++)
        if (!strcasecmp(classes[i].name, name))
            return &classes[i];
    return NULL;
}

/* ---- classes -------------------------------------------------------------------------------------------------------------------- */
static uint32_t RegisterClassA(const uint32_t *a)
{
    uint32_t style = RD32(a[0]), proc = RD32(a[0] + 4), cbcls = RD32(a[0] + 8), cbwnd = RD32(a[0] + 12), hinst = RD32(a[0] + 16);
    uint32_t cursor = RD32(a[0] + 24), bg = RD32(a[0] + 28), name = RD32(a[0] + 36);
    char key[96];
    Class *c;

    if (name > 0xFFFF) {
        char *l = lower_dup(P(name));
        snprintf(key, sizeof(key), "%s", l);
        free(l);
    } else
        snprintf(key, sizeof(key), "#%u", name);
    port_trace("RegisterClassA(%s): style 0x%x, procedure 0x%08x, %u bytes per window", key, style, proc, cbwnd);
    c = find_class(key);
    if (!c) {
        if (nclasses == capclasses) {
            capclasses = capclasses ? capclasses * 2 : 32;
            classes = realloc(classes, (size_t)capclasses * sizeof(*classes));
        }
        c = &classes[nclasses++];
    }
    memset(c, 0, sizeof(*c));
    snprintf(c->name, sizeof(c->name), "%s", key);
    c->style = style;
    c->proc = proc;
    c->cbwnd = cbwnd;
    c->hinst = hinst;
    c->cursor = cursor;
    c->bg = bg;
    c->extra = cbcls;
    return 0xC000u + (uint32_t)nclasses;
}

uint32_t wm_class_background(const Window *w)
{
    return w->cls ? w->cls->bg : 0;
}

/* ---- windows -------------------------------------------------------------------------------------------------------------------- */
Window *wm_new_window(const char *cname, uint32_t parent, uint32_t style, uint32_t exstyle, int x, int y, int w, int h, const char *title,
                      uint32_t menu, uint32_t param)
{
    Window *win = calloc(1, sizeof(*win));
    Class *c = find_class(cname);

    win->hwnd = next_hwnd;
    next_hwnd += 4;
    win->cname = strdup(cname);
    win->cls = c;
    win->proc = c ? c->proc : 0;
    win->parent = parent;
    win->style = style;
    win->exstyle = exstyle;
    win->x = x;
    win->y = y;
    win->w = w;
    win->h = h;
    if (!c && !strcasecmp(cname, "COMBOBOX") && (style & 3) >= 2 && h > COMBO_CLOSED_H) {   /* a drop-down combo box is only its closed box; the height asked for is its list's */
        win->drop_h = h;
        win->h = COMBO_CLOSED_H;
    }
    win->title = strdup(title ? title : "");
    win->enabled = 1;
    win->id = (style & WS_CHILD) ? menu : 0;
    win->invalid = 1;
    win->erase = !(style & WS_CHILD);       /* a new top-level window's update region is marked for erasing (see next_message) */
    win->param = param;
    win->builtin = c == NULL;
    win->hinst = c ? c->hinst : 0;
    win->tid = sched_tid();
    win->sel = -1;
    win->nextra = c ? (int)c->cbwnd : 0;
    win->extra = calloc((size_t)(win->nextra > 0 ? win->nextra : 1), 1);
    win->ownerdraw = !c && !strcasecmp(cname, "BUTTON") && (style & 0xF) == 0xB;       /* BS_OWNERDRAW: the parent paints it (WM_DRAWITEM) */
    win->z = ++zcount;
    if (nwindows == capwindows) {
        capwindows = capwindows ? capwindows * 2 : 256;
        windows = realloc(windows, (size_t)capwindows * sizeof(*windows));
    }
    windows[nwindows++] = win;
    gdi_resize_surface(win);
    return win;
}

void wm_client_size(const Window *w, int *cw, int *ch)
{
    *cw = w->w - w->nc_l - w->nc_r > 0 ? w->w - w->nc_l - w->nc_r : 0;
    *ch = w->h - w->nc_t - w->nc_b > 0 ? w->h - w->nc_t - w->nc_b : 0;
}

void wm_abs_rect(const Window *w, int *x0, int *y0, int *x1, int *y1)
{
    int x = w->x, y = w->y;
    const Window *cur = w, *p = w->parent ? wm_window(w->parent) : NULL;

    while (p && !((cur->style & WS_POPUP) && !(cur->style & WS_CHILD))) {    /* a popup's parent is its owner: its position is the screen's */
        x += p->x + p->nc_l;                 /* a child is placed in its parent's client area */
        y += p->y + p->nc_t;
        cur = p;
        p = p->parent ? wm_window(p->parent) : NULL;
    }
    *x0 = x;
    *y0 = y;
    *x1 = x + w->w;
    *y1 = y + w->h;
}

void wm_client_origin(const Window *w, int *x, int *y)
{
    int x1, y1;

    wm_abs_rect(w, x, y, &x1, &y1);
    *x += w->nc_l;
    *y += w->nc_t;
}

static int owner_alive(uint32_t tid)
{
    GThread *t = sched_thread_by_id(tid);

    return t && !sched_thread_done(t);
}

/* Windows with the same parent as `w` (itself included), bottom to top: returned as an array the caller frees. */
static Window **siblings(const Window *w, int *n)
{
    Window **out = malloc((size_t)(nwindows + 1) * sizeof(*out));
    int i, j, k;

    *n = 0;
    for (i = 0; i < nwindows; i++)
        if (windows[i] && windows[i]->parent == w->parent)
            out[(*n)++] = windows[i];
    for (j = 1; j < *n; j++) {            /* insertion sort by z */
        Window *t = out[j];

        for (k = j - 1; k >= 0 && out[k]->z > t->z; k--)
            out[k + 1] = out[k];
        out[k + 1] = t;
    }
    return out;
}

/* Restack `win` among its siblings. `after`: 0 / -1 (HWND_TOP, HWND_TOPMOST) to the top, 1 (HWND_BOTTOM) to the bottom, -2 (HWND_NOTOPMOST)
 * to the top, or a sibling's handle: directly below that window. */
static void set_z(Window *win, uint32_t after)
{
    int n, i, no = 0;
    Window **sib = siblings(win, &n), **others = malloc((size_t)(n + 1) * sizeof(*others));

    for (i = 0; i < n; i++)
        if (sib[i] != win)
            others[no++] = sib[i];
    if (after == 0 || after == 0xFFFFFFFFu || after == 0xFFFFFFFEu || !no) {
        if (no)
            win->z = others[no - 1]->z + 1.0;
    } else if (after == 1) {
        win->z = others[0]->z - 1.0;
    } else {
        Window *ref = wm_window(after);
        int idx = -1;

        if (!ref || ref->parent != win->parent || ref == win)
            goto out;
        for (i = 0; i < no; i++)
            if (others[i] == ref)
                idx = i;
        {
            double below = idx > 0 ? others[idx - 1]->z : ref->z - 2.0;

            win->z = (below + ref->z) / 2.0;
        }
    }
    if (no > 1) {                           /* the gaps have worn thin: number the siblings again */
        double mn = 1e30;

        for (i = 0; i + 1 < no; i++) {
            double d = others[i + 1]->z - others[i]->z;

            if (d < 0)
                d = -d;
            if (d < mn)
                mn = d;
        }
        if (mn < 1e-6) {
            free(sib);
            sib = siblings(win, &n);
            for (i = 0; i < n; i++)
                sib[i]->z = (double)i;
        }
    }
out:
    free(sib);
    free(others);
}

/* ---- sending -------------------------------------------------------------------------------------------------------------------- */
static int sent_done(void *p) { return ((Sent *)p)->done; }

uint32_t wm_send(uint32_t hwnd, uint32_t msg, uint32_t wp, uint32_t lp)
{
    Window *win = wm_window(hwnd);

    if (!win)
        return 0;
    if (win->tid != sched_tid() && owner_alive(win->tid)) {
        /* a window made by another thread has its procedure run on that thread: the sender waits until the owner next pumps */
        Sent *rec = calloc(1, sizeof(*rec));
        int i;

        rec->hwnd = hwnd; rec->msg = msg; rec->wp = wp; rec->lp = lp; rec->tid = win->tid;
        if (nsent == 64)
            port_fatal("too many cross-thread messages pending");
        sent[nsent++] = rec;
        sched_block(sent_done, rec, -1);
        i = (int)rec->result;
        free(rec);
        return (uint32_t)i;
    }
    return wm_send_local(hwnd, msg, wp, lp);
}

void wm_process_sent(void)
{
    for (;;) {
        Sent *rec = NULL;
        int i;

        for (i = 0; i < nsent; i++)
            if (sent[i]->tid == sched_tid() && !sent[i]->done && !sent[i]->running) {
                rec = sent[i];
                break;
            }
        if (!rec)
            return;
        rec->running = 1;               /* nested pumps inside its handler must not run it again */
        rec->result = wm_send_local(rec->hwnd, rec->msg, rec->wp, rec->lp);
        rec->done = 1;
        for (i = 0; i < nsent; i++)
            if (sent[i] == rec) {
                memmove(&sent[i], &sent[i + 1], (size_t)(nsent - i - 1) * sizeof(*sent));
                nsent--;
                break;
            }
    }
}

uint32_t wm_send_local(uint32_t hwnd, uint32_t msg, uint32_t wp, uint32_t lp)
{
    Window *win = wm_window(hwnd);
    uint32_t args[4], r;

    if (!win)
        return 0;
    args[0] = hwnd; args[1] = msg; args[2] = wp; args[3] = lp;
    {
        static int log = -1;

        if (log < 0)
            log = getenv("PORT_MSGLOG") != NULL;
        if (log && msg != WM_NCHITTEST && msg != WM_SETCURSOR && msg != WM_TIMER && msg != WM_PAINT && msg != WM_ERASEBKGND)
            fprintf(stderr, "    [msg] %s 0x%x msg 0x%x wp 0x%x lp 0x%x\n", win->cname, hwnd, msg, wp, lp);
    }
    if (win->dlgproc) {                    /* dialog procedures return BOOL: nonzero = handled */
        r = guest_call(win->dlgproc, 4, args);
        if (msg >= 0x132 && msg <= 0x138)  /* WM_CTLCOLOR...: the result is the brush itself */
            return r;
        if (r)
            return msg == WM_INITDIALOG ? 1 : 1;
        if (msg == WM_PAINT)               /* the dialog's own default: begin the paint, so WM_ERASEBKGND reaches the procedure */
            return wm_default_proc(hwnd, msg, wp, lp);
        return wm_default_proc(hwnd, msg, wp, lp);
    }
    if (win->proc)
        return guest_call(win->proc, 4, args);
    return wm_default_proc(hwnd, msg, wp, lp);
}

/* DefWindowProc. WM_PAINT begins a paint, which sends WM_ERASEBKGND to the window's own procedure (games draw their backgrounds there);
 * a zero result falls back to the class brush. */
uint32_t wm_default_proc(uint32_t hwnd, uint32_t msg, uint32_t wp, uint32_t lp)
{
    Window *win = wm_window(hwnd);

    if (!win)
        return 0;
    if (msg == WM_PAINT) {
        win->invalid = 0;
        if (win->erase || win->erase == 0) {
            if (win->erase) {
                win->erase = 0;
                if (!gdi_send_erase(win, 0))
                    gdi_erase_background(win);
            }
        }
        return 0;
    }
    if (msg == WM_ERASEBKGND)
        return gdi_erase_background(win) ? 1 : 0;
    if (msg == WM_NCCREATE || msg == WM_NCHITTEST)
        return 1;
    if (msg == WM_CLOSE) {
        /* DefWindowProc(WM_CLOSE) is DestroyWindow: the window's procedure gets WM_DESTROY first (Spells of the Ancients 2.15's main window answers it with PostQuitMessage, and
         * without it the game's Quit ended the game's own loops and then waited for a WM_QUIT that never came); then the window and its children go. */
        if (win->proc && wm_window(hwnd) == win) {
            uint32_t args[4] = {hwnd, WM_DESTROY, 0, 0};

            guest_call(win->proc, 4, args);
        }
        wm_destroy(hwnd);
        return 0;
    }
    if (msg == 0x112 && (wp & 0xFFF0u) == 0xF060u) {      /* WM_SYSCOMMAND SC_CLOSE (the Magic Shell's own close button sends it to itself): DefWindowProc turns it into WM_CLOSE */
        wm_send(hwnd, WM_CLOSE, 0, 0);
        return 0;
    }
    if (msg == 0x112 && (wp & 0xFFF0u) == 0xF010u) {      /* WM_SYSCOMMAND SC_MOVE (0xF012 is a drag by the mouse): the modal loop that moves the window with the pointer */
        int x0, y0, x1, y1, px0 = 0, py0 = 0, grab_x, grab_y;
        Window *par = win->parent ? wm_window(win->parent) : NULL;

        wm_abs_rect(win, &x0, &y0, &x1, &y1);
        if (par)
            wm_abs_rect(par, &px0, &py0, &x1, &y1);
        grab_x = wm_cursor_x - x0;
        grab_y = wm_cursor_y - y0;
        while (wm_keys[1] && quit_all < 0 && wm_window(hwnd)) {       /* until the left button comes up */
            int nx = wm_cursor_x - grab_x - px0, ny = wm_cursor_y - grab_y - py0;

            if (nx != win->x || ny != win->y) {
                win->x = nx;
                win->y = ny;
                wm_dirty = 1;
            }
            if (wm_pump_hook)
                wm_pump_hook();
            sched_sleep(0.005);
        }
        {   /* the modal loop took the mouse messages of the drag: they are not for anyone else */
            int i, k = 0;

            for (i = 0; i < nqueue; i++)
                if (!((queue[i].msg >= 0x200 && queue[i].msg <= 0x20A) || queue[i].msg == WM_SETCURSOR || queue[i].msg == WM_NCHITTEST))
                    queue[k++] = queue[i];
            nqueue = k;
        }
        return 0;
    }
    if (win->cname) {
        if (!strcasecmp(win->cname, "MCIWNDCLASS"))
            return wm_movie_message(win, msg, wp, lp);
        if (!strcasecmp(win->cname, "BUTTON") || !strcasecmp(win->cname, "STATIC") || !strcasecmp(win->cname, "EDIT") ||
            !strcasecmp(win->cname, "COMBOBOX") || !strcasecmp(win->cname, "LISTBOX") || !strcasecmp(win->cname, "SCROLLBAR") || !strcasecmp(win->cname, "msctls_updown32"))
            return wm_control_message(win, win->cname, msg, wp, lp);
        if (!strcmp(win->cname, "#32770") && msg == WM_CLOSE) {
            win->ended = 1;
            win->result = 2;
        }
    }
    return 0;
}

static uint32_t DefWindowProcA(const uint32_t *a)
{
    return wm_default_proc(a[0], a[1], a[2], a[3]);
}

static uint32_t CallWindowProcA(const uint32_t *a)
{
    uint32_t args[4] = {a[1], a[2], a[3], a[4]};

    if (!a[0] || import_by_slot_or_stub(a[0]))
        return wm_default_proc(a[1], a[2], a[3], a[4]);
    return guest_call(a[0], 4, args);
}

static uint32_t SendMessageA(const uint32_t *a) { return wm_send(a[0], a[1], a[2], a[3]); }

/* ---- creating and destroying -------------------------------------------------------------------------------------------------- */
static uint32_t CreateWindowExA(const uint32_t *a)
{
    uint32_t exstyle = a[0], cls = a[1], title = a[2], style = a[3], parent = a[8], menu = a[9], hinst = a[10], param = a[11];
    int x = (int32_t)a[4], y = (int32_t)a[5], w = (int32_t)a[6], h = (int32_t)a[7];
    char cname[96];
    Window *win;
    uint32_t hwnd, cs, rect;

    if (cls > 0xFFFF)
        snprintf(cname, sizeof(cname), "%s", P(cls));
    else
        snprintf(cname, sizeof(cname), "#%u", cls);
    if (x == (int32_t)0x80000000)
        x = 0;
    if (y == (int32_t)0x80000000)
        y = 0;
    if (w == (int32_t)0x80000000)
        w = screen_w;
    if (h == (int32_t)0x80000000)
        h = screen_h;
    win = wm_new_window(cname, parent, style, exstyle, x, y, w, h, title > 0xFFFF ? P(title) : "", menu, param);
    hwnd = win->hwnd;
    port_trace("CreateWindowEx(class=%s, title=%s, style=0x%08x, %dx%d at %d,%d) -> hwnd 0x%x%s", cname, win->title, style, w, h, x, y, hwnd,
               win->proc ? "" : "  [builtin control]");
    (void)hinst;
    if (!win->proc) {
        win->visible = (style & WS_VISIBLE) != 0;      /* a built-in control created with WS_VISIBLE is shown from the start */
        win->invalid = 1;
        wm_dirty = 1;
        return hwnd;
    }
    cs = heap_alloc(48);
    WR32(cs, param); WR32(cs + 4, hinst); WR32(cs + 8, menu); WR32(cs + 12, parent); WR32(cs + 16, (uint32_t)h); WR32(cs + 20, (uint32_t)w);
    WR32(cs + 24, (uint32_t)y); WR32(cs + 28, (uint32_t)x); WR32(cs + 32, style); WR32(cs + 36, title); WR32(cs + 40, cls); WR32(cs + 44, exstyle);
    if (!wm_send(hwnd, WM_NCCREATE, 0, cs)) {
        wm_destroy(hwnd);
        heap_free(cs);
        return 0;
    }
    rect = heap_alloc(16);
    WR32(rect, (uint32_t)x); WR32(rect + 4, (uint32_t)y); WR32(rect + 8, (uint32_t)(x + win->w)); WR32(rect + 12, (uint32_t)(y + win->h));
    wm_send(hwnd, WM_NCCALCSIZE, 0, rect);
    heap_free(rect);
    if ((int32_t)wm_send(hwnd, WM_CREATE, 0, cs) == -1) {
        wm_destroy(hwnd);
        heap_free(cs);
        return 0;
    }
    heap_free(cs);
    if (style & WS_CHILD) {
        /* CreateWindow ends by positioning the window, which DefWindowProc turns into WM_SIZE and WM_MOVE, visible or not. (Top-level windows
         * get theirs in show().) A child that lays out its controls in WM_SIZE needs it. */
        int cw, ch;

        wm_client_size(win, &cw, &ch);
        wm_send(hwnd, WM_SIZE, 0, (uint32_t)(cw & 0xFFFF) | ((uint32_t)ch << 16));
        wm_send(hwnd, WM_MOVE, 0, (uint32_t)(win->x & 0xFFFF) | ((uint32_t)(win->y & 0xFFFF) << 16));
    }
    if (style & WS_VISIBLE)
        wm_show(hwnd, 1);
    return hwnd;
}

void wm_destroy(uint32_t hwnd)
{
    Window *win = wm_window(hwnd);
    int i;

    if (!win)
        return;
    windows[(hwnd - HWND_BASE) / 4] = NULL;
    wm_movie_release(win);
    for (i = 0; i < nwindows; i++)
        if (windows[i] && windows[i]->parent == hwnd)
            wm_destroy(windows[i]->hwnd);
    gdi_release_surface(win);
}

static uint32_t DestroyWindow(const uint32_t *a)
{
    Window *win = wm_window(a[0]);

    if (!win)
        return 0;
    if (win->proc) {
        uint32_t args[4] = {a[0], WM_DESTROY, 0, 0};

        guest_call(win->proc, 4, args);
    }
    wm_destroy(a[0]);
    return 1;
}

void wm_show(uint32_t hwnd, int cmd)
{
    Window *win = wm_window(hwnd);
    int was;

    if (!win)
        return;
    was = win->visible;
    win->visible = cmd != 0;
    if (cmd && !was) {
        wm_dirty = 1;
        win->invalid = 1;
        if (!(win->style & WS_CHILD))
            win->erase = 1;                 /* a window just shown is erased before it is painted (see next_message) */
        wm_send(hwnd, WM_SHOWWINDOW, 1, 0);
        if (!(win->style & WS_CHILD)) {
            int cw, ch;

            active_hwnd = focus_hwnd = hwnd;
            wm_send(hwnd, WM_ACTIVATEAPP, 1, 1);
            wm_send(hwnd, WM_ACTIVATE, 1, 0);
            wm_send(hwnd, WM_SETFOCUS, 0, 0);
            wm_client_size(win, &cw, &ch);
            wm_send(hwnd, WM_SIZE, 0, (uint32_t)(cw & 0xFFFF) | ((uint32_t)ch << 16));
            wm_send(hwnd, WM_MOVE, 0, (uint32_t)(win->x & 0xFFFF) | ((uint32_t)win->y << 16));
        }
    }
    if (!cmd && was) {                  /* hiding a visible window tells it (the game's attack window hides its sword and shield from here) */
        wm_dirty = 1;
        wm_send(hwnd, WM_SHOWWINDOW, 0, 0);
    }
    last_error = (uint32_t)was;
}

static uint32_t ShowWindow(const uint32_t *a)
{
    Window *w = wm_window(a[0]);
    int was = w ? w->visible : 0;

    wm_show(a[0], (int)a[1]);
    return (uint32_t)was;
}

/* Windows hands out no WM_PAINT for a window with an empty client area (it has no update region): the game keeps its hidden opponent hand as zero-size card windows, and a paint there
 * made its card painter load every art at 1x2 pixels, which then served the Urza's Glasses list (a grey and a black half instead of the picture). The window stays invalid, so it paints when it grows. */
static int has_client_area(const Window *w)
{
    int cw = 0, ch = 0;

    wm_client_size(w, &cw, &ch);
    return cw > 0 && ch > 0;
}

static uint32_t UpdateWindow(const uint32_t *a)
{
    Window *w = wm_window(a[0]);

    if (w && w->invalid && w->visible && has_client_area(w))
        wm_send(a[0], WM_PAINT, 0, 0);
    return 1;
}

static uint32_t InvalidateRect(const uint32_t *a)
{
    Window *w = wm_window(a[0]);

    if (w) {
        w->invalid = 1;
        if (a[2])
            w->erase = 1;
        wm_dirty = 1;
    }
    return 1;
}

static uint32_t one(const uint32_t *a) { (void)a; return 1; }
static uint32_t zero(const uint32_t *a) { (void)a; return 0; }

/* ---- geometry ------------------------------------------------------------------------------------------------------------------- */
static void put_rect(uint32_t p, int l, int t, int r, int b)
{
    WR32(p, (uint32_t)l); WR32(p + 4, (uint32_t)t); WR32(p + 8, (uint32_t)r); WR32(p + 12, (uint32_t)b);
}

static uint32_t GetClientRect(const uint32_t *a)
{
    Window *w = wm_window(a[0]);
    int cw, ch;

    if (!w)
        return 0;
    wm_client_size(w, &cw, &ch);
    put_rect(a[1], 0, 0, cw, ch);
    return 1;
}

static uint32_t GetWindowRect(const uint32_t *a)
{
    Window *w = wm_window(a[0]);
    int x0, y0, x1, y1;

    if (!w)
        return 0;
    wm_abs_rect(w, &x0, &y0, &x1, &y1);
    put_rect(a[1], x0, y0, x1, y1);
    return 1;
}

static void geometry_changed(Window *win, int ox, int oy, int ow, int oh)
{
    uint32_t hwnd = win->hwnd;

    if (!win->proc && !win->dlgproc)         /* (a modeless dialog's procedure lays out its controls in WM_SIZE too: the Magic Shell's pages do) */
        return;
    if (win->w != ow || win->h != oh) {
        int cw, ch;

        wm_client_size(win, &cw, &ch);
        wm_send(hwnd, WM_SIZE, 0, (uint32_t)(cw & 0xFFFF) | ((uint32_t)(ch & 0xFFFF) << 16));
    }
    if (win->x != ox || win->y != oy)
        wm_send(hwnd, WM_MOVE, 0, (uint32_t)(win->x & 0xFFFF) | ((uint32_t)(win->y & 0xFFFF) << 16));
}

static uint32_t MoveWindow(const uint32_t *a)
{
    Window *win = wm_window(a[0]);

    if (win) {
        int ox = win->x, oy = win->y, ow = win->w, oh = win->h;

        win->x = (int32_t)a[1]; win->y = (int32_t)a[2]; win->w = (int32_t)a[3]; win->h = (int32_t)a[4];
        gdi_resize_surface(win);
        win->invalid = 1;
        wm_dirty = 1;
        geometry_changed(win, ox, oy, ow, oh);
    }
    return 1;
}

static uint32_t SetWindowPos(const uint32_t *a)
{
    Window *win = wm_window(a[0]);
    uint32_t after = a[1], flags = a[6];

    if (win) {
        int ox = win->x, oy = win->y, ow = win->w, oh = win->h;

        if (!(flags & 2)) {
            win->x = (int32_t)a[2];
            win->y = (int32_t)a[3];
        }
        if (!(flags & 1)) {
            win->w = (int32_t)a[4];
            win->h = (int32_t)a[5];
            gdi_resize_surface(win);
        }
        if (flags & 0x40)
            wm_show(a[0], 1);
        else if (flags & 0x80)
            wm_show(a[0], 0);
        if (!(flags & 4))                    /* SWP_NOZORDER */
            set_z(win, after);
        win->invalid = 1;
        wm_dirty = 1;
        geometry_changed(win, ox, oy, ow, oh);
    }
    return 1;
}

static void origin(uint32_t hwnd, int *ox, int *oy)
{
    Window *w = hwnd ? wm_window(hwnd) : NULL;

    *ox = *oy = 0;
    if (w)
        wm_client_origin(w, ox, oy);
}

static void shift_points(uint32_t p, uint32_t n, int dx, int dy)
{
    uint32_t i;

    for (i = 0; i < n; i++) {
        WR32(p + 8 * i, RD32(p + 8 * i) + (uint32_t)dx);
        WR32(p + 8 * i + 4, RD32(p + 8 * i + 4) + (uint32_t)dy);
    }
}

static uint32_t ClientToScreen(const uint32_t *a) { int ox, oy; origin(a[0], &ox, &oy); shift_points(a[1], 1, ox, oy); return 1; }
static uint32_t ScreenToClient(const uint32_t *a) { int ox, oy; origin(a[0], &ox, &oy); shift_points(a[1], 1, -ox, -oy); return 1; }

static uint32_t MapWindowPoints(const uint32_t *a)
{
    int fx, fy, tx, ty;

    origin(a[0], &fx, &fy);
    origin(a[1], &tx, &ty);
    shift_points(a[2], a[3], fx - tx, fy - ty);
    return (uint32_t)((fx - tx) & 0xFFFF) | ((uint32_t)((fy - ty) & 0xFFFF) << 16);
}

static uint32_t GetSystemMetrics(const uint32_t *a)
{
    switch (a[0]) {
    case 0: return (uint32_t)screen_w; case 1: return (uint32_t)screen_h; case 4: return 19; case 5: return 1; case 6: return 1; case 7: return 3; case 8: return 3;
    case 15: return 19; case 32: return 4; case 33: return 4; case 3: return 16; case 2: return 16; case 28: return 4; case 29: return 4;
    case 16: return (uint32_t)screen_w; case 17: return (uint32_t)screen_h - 40;
    default: return 0;
    }
}

/* ---- rectangles ----------------------------------------------------------------------------------------------------------------- */
static uint32_t SetRect(const uint32_t *a) { put_rect(a[0], (int32_t)a[1], (int32_t)a[2], (int32_t)a[3], (int32_t)a[4]); return 1; }
static uint32_t CopyRect(const uint32_t *a) { memmove(G + a[0], G + a[1], 16); return 1; }
static uint32_t OffsetRect(const uint32_t *a)
{
    int32_t l = (int32_t)RD32(a[0]), t = (int32_t)RD32(a[0] + 4), r = (int32_t)RD32(a[0] + 8), b = (int32_t)RD32(a[0] + 12);

    put_rect(a[0], l + (int32_t)a[1], t + (int32_t)a[2], r + (int32_t)a[1], b + (int32_t)a[2]);
    return 1;
}
static uint32_t InflateRect(const uint32_t *a)
{
    int32_t l = (int32_t)RD32(a[0]), t = (int32_t)RD32(a[0] + 4), r = (int32_t)RD32(a[0] + 8), b = (int32_t)RD32(a[0] + 12);

    put_rect(a[0], l - (int32_t)a[1], t - (int32_t)a[2], r + (int32_t)a[1], b + (int32_t)a[2]);
    return 1;
}
static uint32_t IsRectEmpty(const uint32_t *a)
{
    return (int32_t)RD32(a[0] + 8) <= (int32_t)RD32(a[0]) || (int32_t)RD32(a[0] + 12) <= (int32_t)RD32(a[0] + 4);
}
static uint32_t PtInRect(const uint32_t *a)
{
    int32_t l = (int32_t)RD32(a[0]), t = (int32_t)RD32(a[0] + 4), r = (int32_t)RD32(a[0] + 8), b = (int32_t)RD32(a[0] + 12);
    int32_t x = (int32_t)a[1], y = (int32_t)a[2];

    return l <= x && x < r && t <= y && y < b;
}
static uint32_t UnionRect(const uint32_t *a)
{
    int32_t l1 = (int32_t)RD32(a[1]), t1 = (int32_t)RD32(a[1] + 4), r1 = (int32_t)RD32(a[1] + 8), b1 = (int32_t)RD32(a[1] + 12);
    int32_t l2 = (int32_t)RD32(a[2]), t2 = (int32_t)RD32(a[2] + 4), r2 = (int32_t)RD32(a[2] + 8), b2 = (int32_t)RD32(a[2] + 12);

    put_rect(a[0], l1 < l2 ? l1 : l2, t1 < t2 ? t1 : t2, r1 > r2 ? r1 : r2, b1 > b2 ? b1 : b2);
    return 1;
}

/* The overlap of two rectangles into the first argument; an empty overlap zeroes it and returns 0. */
static uint32_t IntersectRect(const uint32_t *a)
{
    int32_t l1 = (int32_t)RD32(a[1]), t1 = (int32_t)RD32(a[1] + 4), r1 = (int32_t)RD32(a[1] + 8), b1 = (int32_t)RD32(a[1] + 12);
    int32_t l2 = (int32_t)RD32(a[2]), t2 = (int32_t)RD32(a[2] + 4), r2 = (int32_t)RD32(a[2] + 8), b2 = (int32_t)RD32(a[2] + 12);
    int32_t l = l1 > l2 ? l1 : l2, t = t1 > t2 ? t1 : t2, r = r1 < r2 ? r1 : r2, b = b1 < b2 ? b1 : b2;

    if (l >= r || t >= b) {
        put_rect(a[0], 0, 0, 0, 0);
        return 0;
    }
    put_rect(a[0], l, t, r, b);
    return 1;
}
static uint32_t EqualRect(const uint32_t *a) { return memcmp(G + a[0], G + a[1], 16) == 0; }
static uint32_t SetRectEmpty(const uint32_t *a) { put_rect(a[0], 0, 0, 0, 0); return 1; }

/* The Windows 98 standard scheme, indexed by COLOR_xxx (0 scrollbar ... 24 tooltip background); a COLORREF is 0x00BBGGRR. */
static uint32_t GetSysColor(const uint32_t *a)
{
    static const uint8_t c[25][3] = {{192, 192, 192}, {58, 110, 165}, {0, 0, 128}, {128, 128, 128}, {192, 192, 192}, {255, 255, 255}, {0, 0, 0},
                                     {0, 0, 0}, {0, 0, 0}, {255, 255, 255}, {192, 192, 192}, {192, 192, 192}, {128, 128, 128}, {0, 0, 128},
                                     {255, 255, 255}, {192, 192, 192}, {128, 128, 128}, {128, 128, 128}, {0, 0, 0}, {192, 192, 192},
                                     {255, 255, 255}, {0, 0, 0}, {192, 192, 192}, {0, 0, 0}, {255, 255, 225}};

    if (a[0] > 24)
        return 0;
    return (uint32_t)c[a[0]][0] | (uint32_t)c[a[0]][1] << 8 | (uint32_t)c[a[0]][2] << 16;
}

/* SetParent(child, newparent): returns the previous parent. The child keeps its position, now relative to the new parent's client area. */
static uint32_t SetParent(const uint32_t *a)
{
    Window *w = wm_window(a[0]);
    uint32_t old;

    if (!w)
        return 0;
    old = w->parent;
    w->parent = a[1];
    return old;
}

/* ---- window state --------------------------------------------------------------------------------------------------------------- */
static uint32_t GetWindowLongA(const uint32_t *a)
{
    Window *w = wm_window(a[0]);
    int32_t idx = (int32_t)a[1];

    if (!w)
        return 0;
    switch (idx) {
    case -4: return w->proc;
    case -16: return w->style;
    case -20: return w->exstyle;
    case -21: return w->userdata;
    case -12: return w->id;
    case -6: return w->hinst;
    case -8: return w->parent;
    }
    if (idx < 0 || idx + 4 > w->nextra)
        return 0;
    return *(uint32_t *)(w->extra + idx);
}

static uint32_t SetWindowLongA(const uint32_t *a)
{
    Window *w = wm_window(a[0]);
    int32_t idx = (int32_t)a[1];
    uint32_t old;

    if (!w)
        return 0;
    switch (idx) {
    case -4: old = w->proc; w->proc = a[2]; w->subclassed = w->subclassed || w->builtin; w->builtin = 0; return old;
    case -16: old = w->style; w->style = a[2]; return old;
    case -20: old = w->exstyle; w->exstyle = a[2]; return old;
    case -21: old = w->userdata; w->userdata = a[2]; return old;
    case -12: old = w->id; w->id = a[2]; return old;
    case -6: old = w->hinst; w->hinst = a[2]; return old;
    case -8: old = w->parent; w->parent = a[2]; return old;
    }
    if (idx < 0)
        return 0;
    if (idx + 4 > w->nextra) {
        w->extra = realloc(w->extra, (size_t)idx + 4);
        memset(w->extra + w->nextra, 0, (size_t)(idx + 4 - w->nextra));
        w->nextra = idx + 4;
    }
    old = *(uint32_t *)(w->extra + idx);
    *(uint32_t *)(w->extra + idx) = a[2];
    return old;
}

static uint32_t GetWindowWord(const uint32_t *a)
{
    Window *w = wm_window(a[0]);
    int32_t idx = (int32_t)a[1];

    if (!w || idx < 0 || idx + 2 > w->nextra)
        return 0;
    return *(uint16_t *)(w->extra + idx);
}

static uint32_t SetWindowWord(const uint32_t *a)
{
    Window *w = wm_window(a[0]);
    int32_t idx = (int32_t)a[1];
    uint32_t old;

    if (!w || idx < 0)
        return 0;
    if (idx + 2 > w->nextra) {
        w->extra = realloc(w->extra, (size_t)idx + 2);
        memset(w->extra + w->nextra, 0, (size_t)(idx + 2 - w->nextra));
        w->nextra = idx + 2;
    }
    old = *(uint16_t *)(w->extra + idx);
    *(uint16_t *)(w->extra + idx) = (uint16_t)a[2];
    return old;
}

static uint32_t GetParent(const uint32_t *a) { Window *w = wm_window(a[0]); return w ? w->parent : 0; }

/* children of `parent`, top of the stacking order first */
static Window **children_top_down(uint32_t parent, int *n)
{
    Window **out = malloc((size_t)(nwindows + 1) * sizeof(*out));
    int i, j, k;

    *n = 0;
    for (i = 0; i < nwindows; i++)
        if (windows[i] && windows[i]->parent == parent && windows[i]->hwnd != parent)
            out[(*n)++] = windows[i];
    for (j = 1; j < *n; j++) {
        Window *t = out[j];

        for (k = j - 1; k >= 0 && out[k]->z < t->z; k--)
            out[k + 1] = out[k];
        out[k + 1] = t;
    }
    return out;
}

/* EnumChildWindows(parent, function, lParam): the function (BOOL CALLBACK f(HWND, LPARAM)) is called for each child of the window and then for the children of that child, in stacking order, top
 * first, until it returns FALSE. A window destroyed by an earlier call is not called. Returns TRUE (the value is not used). */
static int enum_children(uint32_t parent, uint32_t fn, uint32_t lparam, int depth)
{
    int n, i;
    Window **kids = children_top_down(parent, &n);
    uint32_t *handles = malloc((size_t)(n + 1) * sizeof(*handles));
    int go = 1;

    for (i = 0; i < n; i++)
        handles[i] = kids[i]->hwnd;
    free(kids);
    for (i = 0; i < n && go; i++) {
        uint32_t args[2] = {handles[i], lparam};

        if (!wm_window(handles[i]))
            continue;
        if (!guest_call(fn, 2, args))
            go = 0;
        else if (depth < 16)
            go = enum_children(handles[i], fn, lparam, depth + 1);
    }
    free(handles);
    return go;
}

static uint32_t EnumChildWindows(const uint32_t *a)
{
    if (a[1] && wm_window(a[0]))
        enum_children(a[0], a[1], a[2], 0);
    return 1;
}

static uint32_t GetTopWindow(const uint32_t *a)
{
    int n;
    Window **k = children_top_down(a[0], &n);
    uint32_t r = n ? k[0]->hwnd : 0;

    free(k);
    return r;
}

/* GW_HWNDFIRST 0 / LAST 1 / NEXT 2 / PREV 3 walk the siblings in stacking order (NEXT goes down, PREV up); GW_OWNER 4; GW_CHILD 5. */
static uint32_t GetWindow(const uint32_t *a)
{
    Window *w = wm_window(a[0]);
    int n, i, idx = -1, j;
    Window **order;
    uint32_t r = 0;

    if (!w)
        return 0;
    if (a[1] == 5) {
        order = children_top_down(a[0], &n);
        r = n ? order[0]->hwnd : 0;
        free(order);
        return r;
    }
    if (a[1] == 4)
        return 0;
    order = children_top_down(w->parent, &n);
    if (a[1] == 0)
        r = n ? order[0]->hwnd : 0;
    else if (a[1] == 1)
        r = n ? order[n - 1]->hwnd : 0;
    else {
        for (i = 0; i < n; i++)
            if (order[i] == w)
                idx = i;
        j = a[1] == 2 ? idx + 1 : idx - 1;
        r = (idx >= 0 && j >= 0 && j < n) ? order[j]->hwnd : 0;
    }
    free(order);
    return r;
}

static uint32_t GetDlgCtrlID(const uint32_t *a) { Window *w = wm_window(a[0]); return w ? w->id : 0; }
static uint32_t IsWindowVisible(const uint32_t *a) { Window *w = wm_window(a[0]); return w && w->visible; }

/* EnableWindow: a disabled control is drawn grey and takes no mouse; the result is whether it was disabled before. WM_ENABLE tells the window. */
static uint32_t EnableWindow(const uint32_t *a)
{
    Window *w = wm_window(a[0]);
    int was, now = a[1] != 0;

    if (!w)
        return 0;
    was = !w->enabled;
    if (was == now) {
        w->enabled = now;
        w->invalid = 1;
        wm_dirty = 1;
        wm_send(w->hwnd, WM_ENABLE, (uint32_t)now, 0);
    }
    return (uint32_t)was;
}
static uint32_t BringWindowToTop(const uint32_t *a)
{
    Window *w = wm_window(a[0]);

    if (w) {
        set_z(w, 0);
        wm_dirty = 1;
    }
    return 1;
}
static uint32_t GetWindowThreadProcessId(const uint32_t *a) { if (a[1]) WR32(a[1], 1); return 1; }
static uint32_t GetClassNameA(const uint32_t *a)
{
    Window *w = wm_window(a[0]);
    size_t n;

    if (!w)
        return 0;
    n = strlen(w->cname);
    if (n >= a[2])
        n = a[2] ? a[2] - 1 : 0;
    memcpy(P(a[1]), w->cname, n);
    P(a[1])[n] = 0;
    return (uint32_t)n;
}

static uint32_t SetFocus(const uint32_t *a) { uint32_t old = focus_hwnd; focus_hwnd = a[0]; return old; }
void wm_set_focus(uint32_t hwnd) { focus_hwnd = hwnd; wm_dirty = 1; }
static uint32_t GetFocus(const uint32_t *a) { (void)a; return focus_hwnd; }
static uint32_t SetActiveWindow(const uint32_t *a) { active_hwnd = a[0]; return 0; }
static uint32_t SetCapture(const uint32_t *a) { capture_hwnd = a[0]; return 0; }
static uint32_t GetCapture(const uint32_t *a) { (void)a; return capture_hwnd; }
static uint32_t ReleaseCapture(const uint32_t *a) { (void)a; capture_hwnd = 0; return 1; }

static uint32_t SetWindowTextA(const uint32_t *a)
{
    Window *w = wm_window(a[0]);

    if (w) {
        free(w->title);
        w->title = strdup(P(a[1]));
    }
    return 1;
}

static uint32_t GetWindowTextA(const uint32_t *a)
{
    Window *w = wm_window(a[0]);
    size_t n = w ? strlen(w->title) : 0;

    if (a[2] == 0)
        return 0;
    if (n > a[2] - 1)
        n = a[2] - 1;
    if (w)
        memcpy(P(a[1]), w->title, n);
    P(a[1])[n] = 0;
    return (uint32_t)n;
}

/* GetWindowTextLengthA(hwnd): the length of the window's text, without the terminator (0 for a window that is not there). */
static uint32_t GetWindowTextLengthA(const uint32_t *a)
{
    Window *w = wm_window(a[0]);

    return w && w->title ? (uint32_t)strlen(w->title) : 0;
}

/* ---- characters (the ANSI code page 1252) --------------------------------------------------------------------------------------------- */
static int ansi_is_lower(unsigned c) { return (c >= 'a' && c <= 'z') || (c >= 0xDF && c <= 0xFF && c != 0xF7) || c == 0x9A || c == 0x9C || c == 0x9E; }
static int ansi_is_upper(unsigned c) { return (c >= 'A' && c <= 'Z') || (c >= 0xC0 && c <= 0xDE && c != 0xD7) || c == 0x8A || c == 0x8C || c == 0x8E || c == 0x9F; }

static unsigned ansi_lower(unsigned c)
{
    if (c >= 'A' && c <= 'Z')
        return c + 32;
    if (c >= 0xC0 && c <= 0xDE && c != 0xD7)
        return c + 32;
    return c == 0x8A ? 0x9A : c == 0x8C ? 0x9C : c == 0x8E ? 0x9E : c == 0x9F ? 0xFF : c;
}

static unsigned ansi_upper(unsigned c)
{
    if (c >= 'a' && c <= 'z')
        return c - 32;
    if (c >= 0xE0 && c <= 0xFE && c != 0xF7)
        return c - 32;
    return c == 0x9A ? 0x8A : c == 0x9C ? 0x8C : c == 0x9E ? 0x8E : c == 0xFF ? 0x9F : c;
}

/* CharLowerA / CharUpperA(text): a string is converted where it is and its address returned; a value whose high word is zero is one character (in the low word), and the converted
 * character comes back the same way. Letters are those of code page 1252 (the German sharp s, 0xDF, has no capital; 0xFF is capital 0x9F). */
static uint32_t case_map(uint32_t arg, unsigned (*map)(unsigned))
{
    uint32_t i;

    if (arg <= 0xFFFFu)
        return map(arg & 0xFFu);
    for (i = 0; G[arg + i]; i++)
        G[arg + i] = (uint8_t)map(G[arg + i]);
    return arg;
}
static uint32_t CharLowerA(const uint32_t *a) { return case_map(a[0], ansi_lower); }
static uint32_t CharUpperA(const uint32_t *a) { return case_map(a[0], ansi_upper); }

/* IsCharAlphaNumericA(char): a letter or digit of code page 1252 (the superscript digits count as digits, as they do for Windows). */
static uint32_t IsCharAlphaNumericA(const uint32_t *a)
{
    unsigned c = a[0] & 0xFFu;

    return (c >= '0' && c <= '9') || ansi_is_lower(c) || ansi_is_upper(c) || c == 0xAA || c == 0xB5 || c == 0xBA || c == 0xB2 || c == 0xB3 || c == 0xB9;
}

/* ShowScrollBar(window, bar, show): a scroll bar control (SB_CTL, 2) is a window of its own and is shown or hidden as one; the bars of an ordinary window (SB_HORZ, SB_VERT, SB_BOTH) are
 * not drawn here, so there is nothing to show. */
static uint32_t ShowScrollBar(const uint32_t *a)
{
    Window *w = wm_window(a[0]);

    if (w && a[1] == 2 && w->cname && !strcasecmp(w->cname, "SCROLLBAR")) {
        if (w->visible != (a[2] != 0)) {
            w->visible = a[2] != 0;
            w->invalid = 1;
            wm_dirty = 1;
        }
    }
    return 1;
}

/* ---- cursor, keyboard state ------------------------------------------------------------------------------------------------------ */
static uint32_t cursor_now;
static uint32_t SetCursor(const uint32_t *a) { uint32_t old = cursor_now; cursor_now = a[0]; return old; }
static uint32_t GetCursor(const uint32_t *a) { (void)a; return cursor_now; }
static uint32_t LoadCursorA(const uint32_t *a) { return gdi_new_object(GDI_CURSOR, a[1], 0); }
static uint32_t LoadIconA(const uint32_t *a) { return gdi_new_object(GDI_ICON, a[1], 0); }
static uint32_t LoadAcceleratorsA(const uint32_t *a) { return gdi_new_object(GDI_ACCEL, a[1], 0); }
static uint32_t GetDoubleClickTime(const uint32_t *a) { (void)a; return 500; }
static uint32_t GetCursorPos(const uint32_t *a) { WR32(a[0], (uint32_t)wm_cursor_x); WR32(a[0] + 4, (uint32_t)wm_cursor_y); return 1; }
static uint32_t SetCursorPos(const uint32_t *a) { wm_cursor_x = (int32_t)a[0]; wm_cursor_y = (int32_t)a[1]; return 1; }
static uint32_t WindowFromPoint(const uint32_t *a)                 /* WindowFromPoint(x, y): the point is passed by value, two words */
{
    int i;
    uint32_t h = wm_hit_test((int32_t)a[0], (int32_t)a[1]);

    if (h)
        return h;
    for (i = nwindows - 1; i >= 0; i--)
        if (windows[i] && windows[i]->visible && !(windows[i]->style & WS_CHILD))
            return windows[i]->hwnd;
    return 0;
}
static uint32_t GetKeyState(const uint32_t *a) { return a[0] < 256 && wm_keys[a[0]] ? 0x8000 : 0; }

/* ---- the queue ------------------------------------------------------------------------------------------------------------------ */
void wm_post(uint32_t hwnd, uint32_t msg, uint32_t wp, uint32_t lp)
{
    if (nqueue == capqueue) {
        capqueue = capqueue ? capqueue * 2 : 256;
        queue = realloc(queue, (size_t)capqueue * sizeof(*queue));
    }
    queue[nqueue++] = (Msg){hwnd, msg, wp, lp};
}

static uint32_t PostMessageA(const uint32_t *a) { wm_post(a[0], a[1], a[2], a[3]); return 1; }

static uint32_t PostQuitMessage(const uint32_t *a)
{

    *sched_quit_flag() = 1;           /* WM_QUIT belongs to the calling thread's queue (the deck editor's thread must not end the game) */
    *sched_quit_code() = a[0];
    return 0;
}

static uint32_t GetMessageTime(const uint32_t *a) { (void)a; return port_now_ms(); }

static uint32_t DispatchMessageA(const uint32_t *a)
{
    uint32_t hwnd = RD32(a[0]), msg = RD32(a[0] + 4), wp = RD32(a[0] + 8), lp = RD32(a[0] + 12);

    if (msg == WM_TIMER && lp) {
        uint32_t args[4] = {hwnd, WM_TIMER, wp, port_now_ms()};

        guest_call(lp, 4, args);
        return 0;
    }
    if (msg == WM_PAINT) {
        uint32_t r = wm_send(hwnd, msg, wp, lp);
        Window *w = wm_window(hwnd);

        if (w)
            w->painting = 0;                           /* answered (a procedure that never began a paint leaves no update region behind) */
        return r;
    }
    return wm_send(hwnd, msg, wp, lp);
}

static int owned(uint32_t hwnd)
{
    Window *w = wm_window(hwnd);

    return !w || w->tid == sched_tid();
}

static uint32_t drawitem_struct(Window *win)
{
    uint32_t hdc = gdi_window_dc(win->hwnd);
    int cw, ch;

    if (!win->odmem)
        win->odmem = heap_alloc(0x40);
    wm_client_size(win, &cw, &ch);
    WR32(win->odmem, 4); WR32(win->odmem + 4, win->id & 0xFFFF); WR32(win->odmem + 8, 0); WR32(win->odmem + 12, 1);
    WR32(win->odmem + 16, 0); WR32(win->odmem + 20, win->hwnd); WR32(win->odmem + 24, hdc); WR32(win->odmem + 28, 0);
    WR32(win->odmem + 32, 0); WR32(win->odmem + 36, (uint32_t)cw); WR32(win->odmem + 40, (uint32_t)ch); WR32(win->odmem + 44, 0);
    gdi_clear_surface(win);
    wm_dirty = 1;
    return win->odmem;
}

/* A pending message for the calling thread, or 0. Synthesizes WM_PAINT for invalid visible windows and WM_TIMER for due timers. Queues are per
 * thread, as in Windows: a window's messages go to the thread that created it. */
static int msg_filter_min, msg_filter_max;
static int in_filter(uint32_t msg) { return (!msg_filter_min && !msg_filter_max) || (msg >= (uint32_t)msg_filter_min && msg <= (uint32_t)msg_filter_max); }

/* hwnd_filter: only this window's messages (0: all); the range of messages wanted is set by the caller (PeekMessage and GetMessage's min and max). */
static int next_message(int remove, uint32_t hwnd_filter, Msg *out)
{
    int i;
    uint32_t t;

    for (i = 0; i < nqueue; i++)
        if ((!hwnd_filter || queue[i].hwnd == hwnd_filter) && in_filter(queue[i].msg) && owned(queue[i].hwnd)) {
            *out = queue[i];
            if (remove) {
                memmove(&queue[i], &queue[i + 1], (size_t)(nqueue - i - 1) * sizeof(*queue));
                nqueue--;
            }
            return 1;
        }
    t = port_now_ms();
    for (i = 0; i < ntimers; i++) {
        Timer *tm = &timers[i];

        if (in_filter(WM_TIMER) && tm->used && tm->next <= t && (tm->hwnd == 0 || (wm_window(tm->hwnd) && owned(tm->hwnd)))) {
            tm->next = t + (tm->delay ? tm->delay : 1);
            *out = (Msg){tm->hwnd, WM_TIMER, tm->id, tm->proc};
            return 1;
        }
    }
    for (i = 0; remove && i < nwindows; i++) {  /* a standard control on an ordinary window that needs painting: Windows asks the parent how to colour it (WM_CTLCOLOR...) each time it draws it; the compositor
                                                 * draws the control later (compose.c), so the answer is taken here, on the thread that owns the window, and kept */
        Window *w = windows[i], *p;

        if (w && (w->builtin || w->subclassed) && w->invalid && w->visible && (!w->proc || w->subclassed) && !w->dlgproc && !w->ownerdraw && w->cname && w->tid == sched_tid() && (p = wm_window(w->parent)) && (p->proc || p->dlgproc) &&
            !ui_in_modal_dialog(p)) {
            w->invalid = 0;
            wm_query_ctl_colors(p, w);
            wm_dirty = 1;
        }
    }
    for (i = 0; i < nwindows; i++) {
        Window *w = windows[i];

        if (in_filter(WM_PAINT) && w && w->invalid && w->visible && (w->proc || w->dlgproc) && !w->ownerdraw && w->tid == sched_tid() && has_client_area(w)) {
            uint32_t hwnd = w->hwnd;

            if (remove) {
                w->invalid = 0;
                w->painting = 1;                              /* the update region stays until the procedure's BeginPaint (or its return): a paint routine reads it first (GetUpdateRect) */
                if (w->erase && w->proc && !w->dlgproc) {
                    /* Windows sends WM_ERASEBKGND ahead of the WM_PAINT it hands out for a window whose update region is marked for erasing,
                     * whether or not the procedure then begins a paint. STATWIN.DLL's window never does: it answers WM_PAINT with an
                     * InvalidateRect and draws everything in WM_ERASEBKGND (it showed black). */
                    w->erase = 0;
                    gdi_send_erase(w, 0);                     /* its result does not matter: a procedure that wants the class brush asks DefWindowProc for it */
                }
            }
            *out = (Msg){hwnd, WM_PAINT, 0, 0};
            return 1;
        }
    }
    for (i = 0; i < nwindows; i++) {           /* owner-draw buttons: the parent is asked to paint them */
        Window *w = windows[i], *p;

        if (in_filter(WM_DRAWITEM) && w && w->ownerdraw && w->invalid && w->visible && w->w > 0 && w->h > 0 && w->tid == sched_tid() && (p = wm_window(w->parent)) &&
            p->visible) {
            if (remove) {
                w->invalid = 0;
                *out = (Msg){w->parent, WM_DRAWITEM, w->id, drawitem_struct(w)};
            } else
                *out = (Msg){w->parent, WM_DRAWITEM, w->id, 0};
            return 1;
        }
    }
    return 0;
}

static void write_msg(uint32_t p, const Msg *m)
{
    WR32(p, m->hwnd); WR32(p + 4, m->msg); WR32(p + 8, m->wp); WR32(p + 12, m->lp);
    WR32(p + 16, port_now_ms()); WR32(p + 20, (uint32_t)wm_cursor_x); WR32(p + 24, (uint32_t)wm_cursor_y);
}

static __thread int polled_sleep;

static uint32_t PeekMessageA(const uint32_t *a)
{
    Msg m;

    for (;;) {
        wm_process_sent();
        if (wm_pump_hook)
            wm_pump_hook();
        if (quit_all >= 0 && !*sched_quit_flag()) {
            write_msg(a[0], &(Msg){0, WM_QUIT, (uint32_t)quit_all, 0});
            if (a[4] & 1)
                quit_all = -1;
            return 1;
        }
        if (*sched_quit_flag()) {
            write_msg(a[0], &(Msg){0, WM_QUIT, *sched_quit_code(), 0});
            if (a[4] & 1)
                *sched_quit_flag() = 0;
            return 1;
        }
        msg_filter_min = (int)a[2]; msg_filter_max = (int)a[3];
        if (!next_message(a[4] & 1, a[1], &m)) {
            /* A thread that keeps polling an empty queue is spinning: after a few misses it sleeps (the retry then returns "no message"
             * straight away), so idle waits are cheap. It backs off from 1 ms, doubling to 16 ms. */
            int *polls = sched_empty_polls();

            (*polls)++;
            if (*polls > 3 && !polled_sleep) {
                int step = (*polls - 4) / 4;
                double back;

                polled_sleep = 1;
                if (step > 5)
                    step = 5;
                back = 0.001 * (double)(1 << step);
                if (back > 0.016)
                    back = 0.016;
                sched_sleep(back);
                continue;
            }
            polled_sleep = 0;
            return 0;
        }
        *sched_empty_polls() = 0;
        write_msg(a[0], &m);
        return 1;
    }
}

static uint32_t GetMessageA(const uint32_t *a)
{
    Msg m;

    for (;;) {
        wm_process_sent();
        if (wm_pump_hook)
            wm_pump_hook();
        if (*sched_quit_flag()) {
            write_msg(a[0], &(Msg){0, WM_QUIT, *sched_quit_code(), 0});
            *sched_quit_flag() = 0;                /* the loop ends; a later loop on this thread starts clean */
            return 0;
        }
        if (quit_all >= 0) {
            write_msg(a[0], &(Msg){0, WM_QUIT, (uint32_t)quit_all, 0});
            return 0;
        }
        msg_filter_min = (int)a[2]; msg_filter_max = (int)a[3];
        if (next_message(1, a[1], &m)) {
            write_msg(a[0], &m);
            return 1;
        }
        sched_sleep(0.003);                        /* idle: let other threads run, then look again */
    }
}

void wm_quit_all(int code) { quit_all = code; }

static uint32_t SetTimer(const uint32_t *a)
{
    int i;
    uint32_t id = a[1] ? a[1] : (uint32_t)ntimers + 1;
    uint32_t delay = a[2] ? a[2] : 1;

    for (i = 0; i < ntimers; i++)
        if (timers[i].used && timers[i].hwnd == a[0] && timers[i].id == id)
            break;
    if (i == ntimers) {
        if (ntimers == captimers) {
            captimers = captimers ? captimers * 2 : 16;
            timers = realloc(timers, (size_t)captimers * sizeof(*timers));
        }
        ntimers++;
    }
    timers[i] = (Timer){a[0], id, delay, a[3], port_now_ms() + delay, 1};
    return id;
}

static uint32_t KillTimer(const uint32_t *a)
{
    int i;

    for (i = 0; i < ntimers; i++)
        if (timers[i].used && timers[i].hwnd == a[0] && timers[i].id == a[1])
            timers[i].used = 0;
    return 1;
}

/* ---- painting ------------------------------------------------------------------------------------------------------------------ */
static uint32_t GetDC(const uint32_t *a)
{
    return gdi_window_dc(a[0] && wm_window(a[0]) ? a[0] : wm_desktop());
}

uint32_t wm_desktop(void)
{
    if (!desktop_hwnd) {
        Window *w = wm_new_window("#desktop", 0, 0, 0, 0, 0, screen_w, screen_h, "", 0, 0);

        w->visible = 1;
        desktop_hwnd = w->hwnd;
    }
    return desktop_hwnd;
}

uint32_t wm_main_hwnd(void)
{
    int i;

    for (i = 0; i < nwindows; i++) {
        Window *w = windows[i];

        if (w && w->visible && !(w->style & WS_CHILD) && w->proc && w->hwnd != desktop_hwnd)
            return w->hwnd;
    }
    return 0;
}

/* Where a key goes: the window with the keyboard focus (the game's duel window, once it is shown, is a window of another thread than the
 * first one, and the message pump that reads the Cancel/Done keys is that thread's), else the first top-level window; before both, a held movie window. */
/* A clip that STATWIN has painted over (video.c, DrawVidBackground) is waiting for a key or a click on its own thread; it is not drawn, so the screen is black while it waits.
 * 0 if no clip is held. */
uint32_t wm_held_clip(void)
{
    int i;

    for (i = 0; i < nwindows; i++)
        if (windows[i] && windows[i]->visible && movie_window_held(windows[i]))
            return windows[i]->hwnd;
    return 0;
}

uint32_t wm_key_target(void)
{
    Window *w;
    uint32_t held = wm_held_clip();

    if (held)
        return held;
    w = wm_window(focus_hwnd);
    if (w && !w->proc && w->visible && w->enabled && w->cname && !strcasecmp(w->cname, "EDIT") && !wm_top_dialog())
        return w->hwnd;                                     /* an edit box on an ordinary window or page that has the focus takes the keys (modal dialogs have their own path) */
    while (w && (!w->proc || !w->visible))
        w = wm_window(w->parent);
    return w ? w->hwnd : wm_main_hwnd();
}

/* A text field to type into: the modal dialog that is open has an edit control that is shown and enabled (the file dialogs' name box). The game's own name box is not a window
 * (textfocus.c). */
int wm_text_focus(void)
{
    uint32_t d = wm_top_dialog();
    int i;

    if (!d)
        return 0;
    for (i = 0; i < nwindows; i++) {
        Window *w = windows[i];

        if (w && w->parent == d && w->cname && !strcasecmp(w->cname, "EDIT") && w->visible && w->enabled)
            return 1;
    }
    return 0;
}

static uint32_t BeginPaint(const uint32_t *a)
{
    Window *win = wm_window(a[0]);
    uint32_t h = gdi_window_dc(a[0]);
    int cw = 0, ch = 0, i;

    if (win)
        wm_client_size(win, &cw, &ch);
    WR32(a[1], h); WR32(a[1] + 4, 1); WR32(a[1] + 8, 0); WR32(a[1] + 12, 0); WR32(a[1] + 16, (uint32_t)cw); WR32(a[1] + 20, (uint32_t)ch);
    for (i = 24; i < 64; i += 4)
        WR32(a[1] + (uint32_t)i, 0);
    if (win) {
        win->invalid = 0;
        win->painting = 0;                          /* BeginPaint validates the update region */
        gdi_forget_texts(win);                      /* the text on a window is what its latest paint wrote */
        if (win->erase) {                           /* the update region was marked for erasing */
            win->erase = 0;
            gdi_send_erase(win, h);
        }
    }
    return h;
}

static uint32_t GetDesktopWindow(const uint32_t *a) { (void)a; return wm_desktop_hwnd(); }

/* ReleaseDC(hwnd, hdc). The desktop's context (GetDC(NULL), which Spells of the Ancients opens, uses and releases for every character it measures) is let go. A window's own is kept as it
 * was: a window class with CS_OWNDC has one context for good (Windows hands the same one out at each GetDC, and a program may go on using it after ReleaseDC), and the first build never let
 * one go. */
static uint32_t ReleaseDC(const uint32_t *a)
{
    if (!a[0] || !wm_window(a[0]) || a[0] == wm_desktop_hwnd())
        gdi_release_dc(a[1]);
    return 1;
}

/* GetUpdateRect(hwnd, &rect, erase): the part of the window that needs painting. A window here is invalid as a whole or not at all (InvalidateRect marks the window), so the
 * rectangle is the client area, or empty. Returns whether there is one. */
static uint32_t GetUpdateRect(const uint32_t *a)
{
    Window *w = wm_window(a[0]);
    int cw = 0, ch = 0;

    if (w && (w->invalid || w->painting) && w->visible && has_client_area(w)) {
        wm_client_size(w, &cw, &ch);
        if (a[1])
            put_rect(a[1], 0, 0, cw, ch);
        return 1;
    }
    if (a[1])
        put_rect(a[1], 0, 0, 0, 0);
    return 0;
}

/* GetUpdateRgn(hwnd, hrgn, erase): the same area as a region (the port's regions are rectangles): NULLREGION (1) or SIMPLEREGION (2), ERROR (0) for a window or region that is not. */
static uint32_t GetUpdateRgn(const uint32_t *a)
{
    Window *w = wm_window(a[0]);
    int cw = 0, ch = 0, painting;
    Region *r = obj_get(a[1], O_REGION);

    if (!w || !r)
        return 0;
    painting = (w->invalid || w->painting) && w->visible && has_client_area(w);
    if (painting)
        wm_client_size(w, &cw, &ch);
    r->l = 0; r->t = 0; r->r = painting ? cw : 0; r->b = painting ? ch : 0;
    return painting ? 2 : 1;
}

/* RegisterWindowMessageA: one number from 0xC000 up for each different string, the same number for the same string (without regard to case, as Windows' atoms are). */
static uint32_t RegisterWindowMessageA(const uint32_t *a)
{
    static char *names[64];
    static int n;
    int i;

    for (i = 0; i < n; i++)
        if (!strcasecmp(names[i], P(a[0])))
            return 0xC000u + (uint32_t)i;
    if (n == 64)
        return 0;
    names[n] = strdup(P(a[0]));
    return 0xC000u + (uint32_t)n++;
}

/* ChangeDisplaySettingsA(devmode, flags): the game asks for a screen mode (640x480) for itself. The window here is the screen the game sees at the size it is given, whatever the
 * desktop is, so the mode is always "set" (DISP_CHANGE_SUCCESSFUL) and nothing of the host's display is changed. */
static uint32_t ChangeDisplaySettingsA(const uint32_t *a) { (void)a; return 0; }

const WinApi USER32_APIS[] = {
    {"user32.dll", "GetDesktopWindow", GetDesktopWindow},
    {"user32.dll", "GetUpdateRect", GetUpdateRect}, {"user32.dll", "GetUpdateRgn", GetUpdateRgn}, {"user32.dll", "RegisterWindowMessageA", RegisterWindowMessageA},
    {"user32.dll", "ChangeDisplaySettingsA", ChangeDisplaySettingsA},
    {"user32.dll", "RegisterClassA", RegisterClassA}, {"user32.dll", "SetClassLongA", zero}, {"user32.dll", "DefWindowProcA", DefWindowProcA},
    {"user32.dll", "CallWindowProcA", CallWindowProcA}, {"user32.dll", "CreateWindowExA", CreateWindowExA},
    {"user32.dll", "DestroyWindow", DestroyWindow}, {"user32.dll", "ShowWindow", ShowWindow}, {"user32.dll", "UpdateWindow", UpdateWindow},
    {"user32.dll", "InvalidateRect", InvalidateRect}, {"user32.dll", "ScrollWindow", one}, {"user32.dll", "GetClientRect", GetClientRect},
    {"user32.dll", "GetWindowRect", GetWindowRect}, {"user32.dll", "MoveWindow", MoveWindow}, {"user32.dll", "SetWindowPos", SetWindowPos},
    {"user32.dll", "AdjustWindowRect", one}, {"user32.dll", "ClientToScreen", ClientToScreen}, {"user32.dll", "ScreenToClient", ScreenToClient},
    {"user32.dll", "MapWindowPoints", MapWindowPoints}, {"user32.dll", "GetSystemMetrics", GetSystemMetrics},
    {"user32.dll", "SetRect", SetRect}, {"user32.dll", "CopyRect", CopyRect}, {"user32.dll", "OffsetRect", OffsetRect},
    {"user32.dll", "InflateRect", InflateRect}, {"user32.dll", "IsRectEmpty", IsRectEmpty}, {"user32.dll", "PtInRect", PtInRect},
    {"user32.dll", "UnionRect", UnionRect}, {"user32.dll", "IntersectRect", IntersectRect}, {"user32.dll", "GetSysColor", GetSysColor},
    {"user32.dll", "SetParent", SetParent}, {"user32.dll", "UnregisterClassA", one},
    {"user32.dll", "EqualRect", EqualRect}, {"user32.dll", "SetRectEmpty", SetRectEmpty}, {"user32.dll", "GetWindowLongA", GetWindowLongA}, {"user32.dll", "SetWindowLongA", SetWindowLongA},
    {"user32.dll", "GetWindowWord", GetWindowWord}, {"user32.dll", "SetWindowWord", SetWindowWord}, {"user32.dll", "GetParent", GetParent},
    {"user32.dll", "GetTopWindow", GetTopWindow}, {"user32.dll", "GetWindow", GetWindow}, {"user32.dll", "GetDlgCtrlID", GetDlgCtrlID},
    {"user32.dll", "IsWindowVisible", IsWindowVisible}, {"user32.dll", "IsIconic", zero}, {"user32.dll", "EnableWindow", EnableWindow},
    {"user32.dll", "SetWindowRgn", one}, {"user32.dll", "LockWindowUpdate", one}, {"user32.dll", "BringWindowToTop", BringWindowToTop},
    {"user32.dll", "SetForegroundWindow", one}, {"user32.dll", "GetWindowThreadProcessId", GetWindowThreadProcessId},
    {"user32.dll", "EnumChildWindows", EnumChildWindows}, {"user32.dll", "GetClassNameA", GetClassNameA},
    {"user32.dll", "MessageBeep", one}, {"user32.dll", "FindWindowA", zero}, {"user32.dll", "FindWindowExA", zero},
    {"user32.dll", "SetFocus", SetFocus}, {"user32.dll", "GetFocus", GetFocus}, {"user32.dll", "SetActiveWindow", SetActiveWindow},
    {"user32.dll", "SetCapture", SetCapture}, {"user32.dll", "GetCapture", GetCapture}, {"user32.dll", "ReleaseCapture", ReleaseCapture},
    {"user32.dll", "SetWindowTextA", SetWindowTextA}, {"user32.dll", "GetWindowTextA", GetWindowTextA}, {"user32.dll", "ShowCursor", zero},
    {"user32.dll", "SetCursor", SetCursor}, {"user32.dll", "GetCursor", GetCursor}, {"user32.dll", "LoadCursorA", LoadCursorA}, {"user32.dll", "LoadIconA", LoadIconA},
    {"user32.dll", "GetWindowTextLengthA", GetWindowTextLengthA}, {"user32.dll", "CharLowerA", CharLowerA}, {"user32.dll", "CharUpperA", CharUpperA},
    {"user32.dll", "IsCharAlphaNumericA", IsCharAlphaNumericA}, {"user32.dll", "ShowScrollBar", ShowScrollBar},
    {"user32.dll", "DestroyIcon", one}, {"user32.dll", "DestroyCursor", one}, {"user32.dll", "LoadAcceleratorsA", LoadAcceleratorsA},
    {"user32.dll", "TranslateAcceleratorA", zero}, {"user32.dll", "GetDoubleClickTime", GetDoubleClickTime},
    {"user32.dll", "GetCursorPos", GetCursorPos}, {"user32.dll", "SetCursorPos", SetCursorPos}, {"user32.dll", "WindowFromPoint", WindowFromPoint},
    {"user32.dll", "GetKeyState", GetKeyState}, {"user32.dll", "GetAsyncKeyState", GetKeyState}, {"user32.dll", "SendMessageA", SendMessageA},
    {"user32.dll", "PostMessageA", PostMessageA}, {"user32.dll", "PostQuitMessage", PostQuitMessage}, {"user32.dll", "GetMessageTime", GetMessageTime},
    {"user32.dll", "TranslateMessage", zero}, {"user32.dll", "DispatchMessageA", DispatchMessageA}, {"user32.dll", "PeekMessageA", PeekMessageA},
    {"user32.dll", "GetMessageA", GetMessageA}, {"user32.dll", "SetTimer", SetTimer}, {"user32.dll", "KillTimer", KillTimer},
    {"user32.dll", "GetDC", GetDC}, {"user32.dll", "GetWindowDC", GetDC}, {"user32.dll", "ReleaseDC", ReleaseDC}, {"user32.dll", "BeginPaint", BeginPaint},
    {"user32.dll", "EndPaint", one}, {0, 0, 0},
};

/* The next message for the calling thread, removed from its queue (the dialog loop's pump). */
int wm_next_message_for(uint32_t *out)
{
    Msg m;

    msg_filter_min = msg_filter_max = 0;
    if (!next_message(1, 0, &m))
        return 0;
    out[0] = m.hwnd; out[1] = m.msg; out[2] = m.wp; out[3] = m.lp;
    return 1;
}

uint32_t wm_get_capture(void) { return capture_hwnd; }
uint32_t wm_next_hwnd(void) { return next_hwnd; }           /* the handle the next window gets: a window with a handle at or above it was created after now */
uint32_t wm_desktop_hwnd(void) { return desktop_hwnd; }

void wm_dump(FILE *f)
{
    int i, n = wm_window_count();

    for (i = 0; i < n; i++) {
        Window *w = wm_window_at_index(i);
        int x0, y0, x1, y1;

        if (!w)
            continue;
        wm_abs_rect(w, &x0, &y0, &x1, &y1);
        fprintf(f, "  win 0x%x parent 0x%x %s%s '%s' (%d,%d)-(%d,%d) z=%g style=0x%x tid=%u%s%s id=%u%s%s\n", w->hwnd, w->parent, w->cname, w->builtin ? "*" : "", w->title ? w->title : "",
                x0, y0, x1, y1, w->z, w->style, w->tid, w->visible ? " visible" : "", w->proc ? "" : " noproc", w->id, w->checked ? " checked" : "",
                w->enabled ? "" : " disabled");
    }
}

void wm_dump_queue(FILE *f)
{
    int i;

    fprintf(f, "  queue (%d):", nqueue);
    for (i = 0; i < nqueue && i < 30; i++)
        fprintf(f, " [0x%x msg 0x%x wp 0x%x lp 0x%x]", queue[i].hwnd, queue[i].msg, queue[i].wp, queue[i].lp);
    fputc('\n', f);
}

/* input.c - the host's mouse and keyboard as window messages: which window is under the pointer, double clicks, built-in push buttons,
 * the dialog manager's Enter and Escape. Port of the end of winemu/user32.py. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "gdi.h"
#include "sched.h"
#include "wm.h"

uint32_t wm_get_capture(void);
uint32_t wm_next_hwnd(void);
uint32_t wm_desktop_hwnd(void);
uint32_t wm_top_dialog(void);
int wm_popup_open(void);
int wm_popup_mouse(int kind, int x, int y);
int wm_popup_key(uint32_t vk, int down);
int wm_popup_swallow_up(void);

static uint32_t hover_hwnd, press_hwnd;
uint32_t wm_pressed_button(void) { return press_hwnd; }
static uint32_t last_down_t, last_down_h;
static uint32_t clip_press;                  /* the held clip a left press went to (its release goes there too) */
static uint32_t press_target, press_serial; /* the window a left press went to, and the handle the next window would have got then (windows from there on came after the press) */
static int last_down_x, last_down_y;

static uint32_t top_of(uint32_t h)
{
    const Window *w;

    while ((w = wm_window(h)) && (w->style & WS_CHILD) && w->parent && wm_window(w->parent))      /* an owned popup (the deck builder's window is owned by the main window) is a top-level window */
        h = w->parent;
    return h;
}

static int popup_depth(const Window *w)
{
    int d = 0;

    while (w) {
        if ((w->style & WS_POPUP) && !(w->style & WS_CHILD))
            d++;
        w = w->parent ? wm_window(w->parent) : NULL;
    }
    return d;
}

/* The topmost visible window under a screen point. Z-order: windows under a WS_POPUP window are above those that are not; among siblings a
 * higher `z` is above (creation order, changed by BringWindowToTop and SetWindowPos); a child is above its parent. */
/* A list box or combo box of a dialog that does its own mouse (filedlg.c): the click goes to the dialog. */
static int own_mouse_control(const Window *w)
{
    const Window *p = w->parent ? wm_window(w->parent) : NULL;

    return p && p->own_mouse;
}

/* Whether the pointer can be on this window at all (before its place in the stacking order is looked at): it has a window procedure of the game's, a dialog procedure or a movie, or
 * it is a push button, or a combo or list box the window layer itself clicks. */
int wm_is_hit_target(const Window *w)
{
    int builtin_button = !w->proc && (!strcasecmp(w->cname, "BUTTON") || ((!strcasecmp(w->cname, "COMBOBOX") || !strcasecmp(w->cname, "LISTBOX")) && !own_mouse_control(w))) && w->w > 0 && w->enabled;

    return w->proc || w->dlgproc || w->movie || builtin_button;
}

static uint32_t window_at(int x, int y)
{
    int i, n = wm_window_count();
    uint32_t best = 0;
    double best_key[10];
    int best_depth = -1, best_len = 0;

    for (i = 0; i < n; i++) {
        Window *w = wm_window_at_index(i), *a;
        int ok = 1, x0, y0, x1, y1, depth, len = 0;
        double key[10];

        if (!w)
            continue;
        if (!w->visible || !wm_is_hit_target(w) || w->hwnd == wm_desktop_hwnd())
            continue;
        for (a = w; a->parent && wm_window(a->parent);) {      /* every ancestor must be visible */
            a = wm_window(a->parent);
            ok = ok && a->visible;
        }
        if (!ok)
            continue;
        wm_abs_rect(w, &x0, &y0, &x1, &y1);
        if (!(x0 <= x && x < x1 && y0 <= y && y < y1))
            continue;
        depth = popup_depth(w);
        /* the key: the z of the top-level ancestor first, down to the window itself (a child is above its parent) */
        {
            const Window *chain[10];
            int c = 0, k;

            for (a = w; a && c < 10; a = a->parent ? wm_window(a->parent) : NULL)
                chain[c++] = a;
            for (k = c - 1; k >= 0; k--)
                key[len++] = chain[k]->z;
        }
        {
            int better = best_depth < 0 || depth > best_depth;

            if (!better && depth == best_depth) {
                int k;

                for (k = 0; k < len && k < best_len; k++)
                    if (key[k] != best_key[k]) {
                        better = key[k] > best_key[k];
                        goto decided;
                    }
                better = len > best_len;
            }
decided:
            if (better) {
                best = w->hwnd;
                best_depth = depth;
                best_len = len;
                memcpy(best_key, key, sizeof(double) * (size_t)len);
            }
        }
    }
    return best;
}

uint32_t wm_hit_test(int x, int y) { return window_at(x, y); }

/* kind: IN_MOVE | IN_DOWN | IN_UP | IN_RDOWN | IN_RUP. (x, y) are screen pixels; the message goes to the window under the pointer (or the
 * capturing window) with client coordinates. */
int wm_inject_mouse(int kind, int x, int y)
{
    uint32_t h;
    Window *tw;
    int x0, y0, x1, y1, lx, ly, dbl = 0;
    uint32_t msg, keys;

    if (kind == IN_WHEEL) {                            /* only the list of a combo box that is down uses the wheel */
        if (wm_combo_open())
            wm_combo_wheel(y);
        return 1;
    }
    wm_cursor_x = x;
    wm_cursor_y = y;
    if (wm_popup_open())                               /* an open popup menu takes the mouse */
        return wm_popup_mouse(kind, x, y);
    if (wm_combo_open())                               /* so does the list of a combo box that is down */
        return wm_combo_mouse(kind, x, y);
    if ((kind == IN_UP || kind == IN_RUP) && wm_popup_swallow_up())
        return 1;
    if (kind == IN_DOWN || kind == IN_UP) {
        /* A held clip (the wait after STATWIN's crystal ball and hit clips) takes the left button wherever it lands: the screen is black then, there is nothing to aim at,
         * and the clip's own thread is the one that reads the click (the main window's thread cannot). The release goes where its press went. */
        uint32_t held = wm_held_clip();

        if ((kind == IN_DOWN && held) || (kind == IN_UP && clip_press)) {
            Window *cw = wm_window(held ? held : clip_press);

            if (cw) {
                int cx0, cy0, cx1, cy1;

                wm_abs_rect(cw, &cx0, &cy0, &cx1, &cy1);
                clip_press = kind == IN_DOWN ? cw->hwnd : 0;
                wm_post(cw->hwnd, kind == IN_DOWN ? WM_LBUTTONDOWN : WM_LBUTTONUP, kind == IN_DOWN ? 1 : 0,
                        ((uint32_t)((y - cy0 - cw->nc_t) & 0xFFFF) << 16) | (uint32_t)((x - cx0 - cw->nc_l) & 0xFFFF));
                return 1;
            }
            clip_press = 0;
        }
    }
    h = wm_get_capture();
    if (!h) {
        h = window_at(x, y);
        if (kind == IN_UP && press_target) {
            /* The release of a press goes to the window that took the press when a top-level window has come up under the pointer since: the game
             * reacts to a press at once (the village's "Edit deck" opens the deck builder on it), the original took a good part of a second to put
             * that window on the screen (it reads its card lists first), so a click of the usual length was over before it was there and the main
             * window got its own release. Here the window is up in a few milliseconds and the release would land on it, leaving the main window's
             * button "down" for good: the game then waits for that release (0x40a3e1, which it runs when the builder returns) with the screen
             * not yet redrawn, black, until the next click anywhere. */
            const Window *pt = wm_window(press_target);

            if (pt && pt->visible && h && h != press_target && top_of(h) != top_of(press_target) && top_of(h) >= press_serial)
                h = press_target;
        }
    }
    if (kind == IN_UP)
        press_target = 0;
    if (!h)
        h = wm_main_hwnd();
    if (!h)
        return 0;
    tw = wm_window(h);
    if (!tw)
        return 0;
    if (kind == IN_DOWN) {
        press_target = h;
        press_serial = wm_next_hwnd();
    }
    if (kind == IN_DOWN) {        /* a second press at the same spot within the double-click time is WM_LBUTTONDBLCLK, for windows whose class asks (CS_DBLCLKS) */
        uint32_t now = port_now_ms();

        if (last_down_h == h && now - last_down_t <= 500 && abs(x - last_down_x) <= 4 && abs(y - last_down_y) <= 4 && tw->cls && (tw->cls->style & 8)) {
            dbl = 1;
            last_down_h = 0;
        } else {
            last_down_t = now;
            last_down_x = x;
            last_down_y = y;
            last_down_h = h;
        }
    }
    msg = dbl ? WM_LBUTTONDBLCLK : kind == IN_MOVE ? WM_MOUSEMOVE : kind == IN_DOWN ? WM_LBUTTONDOWN : kind == IN_UP ? WM_LBUTTONUP :
          kind == IN_RDOWN ? WM_RBUTTONDOWN : WM_RBUTTONUP;
    keys = (kind == IN_DOWN) ? 1 : 0;
    wm_keys[1] = (uint8_t)(kind == IN_DOWN || (kind == IN_MOVE && wm_keys[1]) ? 1 : kind == IN_UP ? 0 : wm_keys[1]);
    wm_abs_rect(tw, &x0, &y0, &x1, &y1);
    lx = x - x0 - tw->nc_l;
    ly = y - y0 - tw->nc_t;
    if (!tw->proc && !strcasecmp(tw->cname, "COMBOBOX") && (tw->style & 3) >= 2 && !own_mouse_control(tw)) {        /* a drop-down combo box: a press puts its list down */
        if (kind == IN_DOWN)
            wm_combo_drop(tw);
        return 1;
    }
    if (!tw->proc && !strcasecmp(tw->cname, "LISTBOX") && !own_mouse_control(tw)) {        /* a built-in list box: a press chooses the row under it */
        if (kind == IN_DOWN || dbl)
            wm_listbox_click(tw, y);
        return 1;
    }
    if (!tw->proc && !strcasecmp(tw->cname, "BUTTON")) {        /* a built-in push button: click = WM_COMMAND */
        if (!tw->enabled) {                                      /* a disabled control gets no mouse */
            press_hwnd = 0;
            return 1;
        }
        if (kind == IN_DOWN) {
            press_hwnd = h;
            tw->invalid = 1;
            wm_dirty = 1;
        } else if (kind == IN_UP && press_hwnd == h) {
            press_hwnd = 0;
            tw->invalid = 1;
            wm_dirty = 1;
            wm_button_auto_check(tw);
            wm_post(tw->parent, WM_COMMAND, tw->id & 0xFFFF, h);   /* BN_CLICKED */
        }
        return 1;
    }
    if ((kind == IN_DOWN || dbl || kind == IN_RDOWN) && !tw->proc && (tw->style & WS_CHILD) && wm_window(tw->parent) && strcasecmp(tw->cname, "STATIC")) {
        int px0, py0, px1, py1;

        wm_abs_rect(wm_window(tw->parent), &px0, &py0, &px1, &py1);     /* a click on a built-in child (a movie window, an edit box) is reported to its parent */
        wm_post(tw->parent, WM_PARENTNOTIFY, (msg & 0xFFFF) | ((tw->id & 0xFFFF) << 16), (uint32_t)(((y - py0) & 0xFFFF) << 16) | (uint32_t)((x - px0) & 0xFFFF));
    }
    if ((kind == IN_MOVE || kind == IN_DOWN || kind == IN_RDOWN) && hover_hwnd != h) {
        uint32_t old = hover_hwnd;

        hover_hwnd = h;
        if (old && wm_window(old))
            wm_post(old, WM_SETCURSOR, old, 0x200u << 16);               /* WM_SETCURSOR for the old one */
        wm_post(h, WM_NCHITTEST, 0, ((uint32_t)y << 16) | (uint32_t)(x & 0xFFFF));
        wm_post(h, WM_SETCURSOR, h, (msg << 16) | 1);                      /* HTCLIENT */
        if (kind != IN_MOVE)
            wm_post(h, WM_MOUSEMOVE, 0, ((uint32_t)(ly & 0xFFFF) << 16) | (uint32_t)(lx & 0xFFFF));
    }
    wm_post(h, msg, keys, ((uint32_t)(ly & 0xFFFF) << 16) | (uint32_t)(lx & 0xFFFF));
    return 1;
}

/* Whether a dialog has a button the dialog manager can press with Enter: a visible, enabled push button (plain, default or owner-drawn) among its children. */
static int dialog_has_push_button(uint32_t hdlg)
{
    int i, n = wm_window_count();

    for (i = 0; i < n; i++) {
        Window *c = wm_window_at_index(i);
        uint32_t kind;

        if (!c || c->parent != hdlg || !c->visible || !c->enabled || !c->cname || strcasecmp(c->cname, "BUTTON"))
            continue;
        kind = c->style & 0xFu;
        if (kind == 0 || kind == 1 || kind == 0xB)           /* BS_PUSHBUTTON, BS_DEFPUSHBUTTON, BS_OWNERDRAW */
            return 1;
    }
    return 0;
}

/* One half of a key press, as a keyboard sends it: WM_KEYDOWN (and WM_CHAR when it types something) or WM_KEYUP, with the scan code in
 * lParam; the key's state (GetKeyState) follows. */
int wm_inject_key(uint32_t vk, uint32_t scancode, int down, int ch, int repeat)
{
    uint32_t h, sc = (scancode & 0xFF) << 16;

    if (wm_popup_open())
        return wm_popup_key(vk, down);
    if (wm_combo_open())
        return wm_combo_key(vk, down, down ? ch : -1);
    if (wm_top_dialog()) {
        uint32_t hdlg = wm_top_dialog();

        if ((vk == 0x1B || vk == 0x0D) && !(wm_window(hdlg) && wm_window(hdlg)->own_keys)) {   /* the dialog manager: Esc is IDCANCEL, Enter is IDOK, sent to the open dialog if it has such a control */
            uint32_t cid = vk == 0x1B ? 2 : 1;
            Window *c = wm_dlg_item(hdlg, cid);

            if (c) {
                if (down && !repeat)
                    wm_post(hdlg, WM_COMMAND, cid, c->hwnd);
                return 1;
            }
        }
        /* Enter in a dialog with no IDOK control, no default push button and no button that could have the focus (the one that says "You won!" when it is not a Gauntlet's: its
         * two buttons are hidden): the dialog manager (IsDialogMessage, which the original's DialogBox loop runs every key through) takes the key and sends the dialog WM_COMMAND with
         * IDOK and no control, and the procedure of that dialog answers it with nothing; it never sees WM_CHAR 13, though it has a case for it. Checked in the original: Enter does
         * not close it, a click does (docs/notes/duel-won-black-screen.md). Space is not a dialog key (WM_CHAR, closes it), and Esc is IDCANCEL there (the procedure closes on that too),
         * which the code below delivers as the character; the difference is the dialog's result (0 or 1), which nothing reads. */
        if (vk == 0x0D && !(wm_window(hdlg) && wm_window(hdlg)->own_keys) && !dialog_has_push_button(hdlg)) {
            if (down && !repeat)
                wm_post(hdlg, WM_COMMAND, 1, 0);
            return 1;
        }
        /* a key of a modal dialog is for the dialog (a dialog without such buttons reads Space and Esc itself as characters) */
        if (down) {
            wm_post(hdlg, WM_KEYDOWN, vk, 1 | sc | (repeat ? 0x40000000u : 0));
            if (ch >= 0)
                wm_post(hdlg, WM_CHAR, (uint32_t)ch, 1 | sc | (repeat ? 0x40000000u : 0));
        } else {
            wm_post(hdlg, WM_KEYUP, vk, 0xC0000001u | sc);
        }
        return 1;
    }
    h = wm_key_target();
    if (!h)
        return 0;
    if (down) {
        if (vk < 256)
            wm_keys[vk] = 1;
        wm_post(h, WM_KEYDOWN, vk, 1 | sc | (repeat ? 0x40000000u : 0));
        if (ch >= 0)
            wm_post(h, WM_CHAR, (uint32_t)ch, 1 | sc | (repeat ? 0x40000000u : 0));
    } else {
        if (vk < 256)
            wm_keys[vk] = 0;
        wm_post(h, WM_KEYUP, vk, 0xC0000001u | sc);
    }
    return 1;
}

/* A character with no key press: Latin-1 text that no US key types (an input method, the Steam Deck's keyboard). The edit boxes of the port's own dialogs read WM_CHAR. */
int wm_inject_char(int ch)
{
    uint32_t h;

    if (wm_popup_open() || wm_combo_open())
        return 0;
    h = wm_top_dialog();
    if (!h)
        h = wm_key_target();
    if (!h)
        return 0;
    wm_post(h, WM_CHAR, (uint32_t)ch, 1);
    return 1;
}

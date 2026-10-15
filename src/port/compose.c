/* compose.c - the screen: every visible window painted parents before children, children offset by their parent; then what Windows itself draws and
 * the game never does (built-in push buttons, dialogs, the open popup menu). Port of compose() in winemu/run.py. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "gdi_int.h"
#include "movie.h"

void ui_dialog(uint8_t *rgb, int sw, int sh, Window *d, uint32_t pressed, void (*paint_child)(void *ctx, Window *child, int ox, int oy), void *ctx);

typedef struct Scene { uint8_t *rgb; } Scene;

static void px(Scene *s, int x, int y, const uint8_t c[3])
{
    if (x < 0 || y < 0 || x >= SCREEN_W || y >= SCREEN_H)
        return;
    memcpy(s->rgb + 3 * ((size_t)y * SCREEN_W + (size_t)x), c, 3);
}

static void rect(Scene *s, int x0, int y0, int x1, int y1, const uint8_t *fill, const uint8_t *outline)     /* inclusive corners */
{
    int x, y;

    for (y = y0; y <= y1; y++)
        for (x = x0; x <= x1; x++) {
            if (outline && (x == x0 || x == x1 || y == y0 || y == y1))
                px(s, x, y, outline);
            else if (fill)
                px(s, x, y, fill);
        }
}

static void line_h(Scene *s, int x0, int x1, int y, const uint8_t c[3]) { int x; for (x = x0; x <= x1; x++) px(s, x, y, c); }
static void line_v(Scene *s, int x, int y0, int y1, const uint8_t c[3]) { int y; for (y = y0; y <= y1; y++) px(s, x, y, c); }

/* Text on the composed screen in the fallback face at a pixel size. */
static void text(Scene *s, int x, int y, const char *str, int size, const uint8_t color[3])
{
    text_on_rgb(s->rgb, SCREEN_W, SCREEN_H, x, y, str, size, color);
}

/* ---- the window tree ------------------------------------------------------------------------------------------------------------------ */
static void paint(Scene *s, Window *win, int ox, int oy)
{
    Surface *sf = win->surface;
    int x = ox + win->x, y = oy + win->y, i, n = wm_window_count();       /* (x, y): the window's own corner; its client area (surface, children) starts inside its frame */

    if (sf && (win->proc || win->ownerdraw || win->movie) && !(win->movie && movie_window_held(win))) {
        int cx = x + win->nc_l, cy = y + win->nc_t;
        int x0 = cx > 0 ? cx : 0, y0 = cy > 0 ? cy : 0, x1 = cx + sf->w < SCREEN_W ? cx + sf->w : SCREEN_W, y1 = cy + sf->h < SCREEN_H ? cy + sf->h : SCREEN_H;

        if (x1 > x0 && y1 > y0) {
            int yy;
            uint8_t *tmp = malloc((size_t)(x1 - x0) * (size_t)(y1 - y0) * 3);

            const uint8_t *alpha = win->movie ? movie_window_alpha(win) : NULL;      /* a see-through clip leaves what is under it where it is black */
            uint8_t *touched = NULL;

            if (!alpha && win->see_through) {      /* a window that erased nothing: only what it drew is on top of its parent */
                touched = malloc((size_t)sf->w * (size_t)sf->h);
                surface_touched(sf, touched);
                alpha = touched;
            }

            surface_rgb(sf, x0 - cx, y0 - cy, x1 - cx, y1 - cy, tmp);
            for (yy = 0; yy < y1 - y0; yy++) {
                uint8_t *dst = s->rgb + 3 * ((size_t)(y0 + yy) * SCREEN_W + (size_t)x0);
                const uint8_t *src = tmp + 3 * (size_t)yy * (size_t)(x1 - x0);

                if (!alpha) {
                    memcpy(dst, src, (size_t)(x1 - x0) * 3);
                } else {
                    const uint8_t *am = alpha + (size_t)(y0 + yy - cy) * (size_t)sf->w + (size_t)(x0 - cx);
                    int xx;

                    for (xx = 0; xx < x1 - x0; xx++)
                        if (am[xx])
                            memcpy(dst + 3 * xx, src + 3 * xx, 3);
                }
            }
            free(tmp);
            free(touched);
        }
    }
    {   /* the children, bottom to top */
        Window **kids = malloc((size_t)(n + 1) * sizeof(*kids));
        int nk = 0, j, k;

        for (i = 0; i < n; i++) {
            Window *c = wm_window_at_index(i);

            if (c && c->parent == win->hwnd && c->hwnd != win->hwnd)
                kids[nk++] = c;
        }
        for (j = 1; j < nk; j++) {
            Window *t = kids[j];

            for (k = j - 1; k >= 0 && kids[k]->z > t->z; k--)
                kids[k + 1] = kids[k];
            kids[k + 1] = t;
        }
        for (j = 0; j < nk; j++)
            if (kids[j]->visible && !kids[j]->is_dialog)          /* a dialog owned by this window is drawn from the dialog stack, not here (it would come out twice, offset) */
                paint(s, kids[j], x + win->nc_l, y + win->nc_t);
        free(kids);
    }
}

/* Built-in push buttons that live on ordinary windows (the prompt bar's Done button): the game never paints them, Windows does. */
static void draw_buttons(Scene *s)
{
    int i, n = wm_window_count();
    extern uint32_t wm_pressed_button(void);
    uint32_t pressed = wm_pressed_button();

    for (i = 0; i < n; i++) {
        Window *w = wm_window_at_index(i), *a;
        int ok = 1, in_dialog = 0, x0, y0, x1, y1, tw, pr;
        static const uint8_t grey[3] = {192, 192, 192}, white[3] = {255, 255, 255}, shade[3] = {96, 96, 96}, mid[3] = {128, 128, 128}, black[3] = {0, 0, 0};
        const uint8_t *light, *dark;
        char label[128];
        size_t o = 0, k;

        if (!w || strcasecmp(w->cname, "BUTTON") || w->proc || w->ownerdraw || !w->visible || w->w <= 0 || w->h <= 0 || ((w->style & 0xF) != 0 && (w->style & 0xF) != 1))
            continue;
        for (a = w; a->parent && wm_window(a->parent);) {
            a = wm_window(a->parent);
            ok = ok && a->visible;
            in_dialog = in_dialog || a->is_dialog || a->dlgproc;
        }
        if (!ok || in_dialog || !w->title[0])
            continue;
        wm_abs_rect(w, &x0, &y0, &x1, &y1);
        pr = pressed == w->hwnd;
        rect(s, x0, y0, x1 - 1, y1 - 1, grey, NULL);
        light = pr ? mid : white;
        dark = pr ? white : shade;
        line_h(s, x0, x1 - 1, y0, light);
        line_v(s, x0, y0, y1 - 1, light);
        line_h(s, x0, x1 - 1, y1 - 1, dark);
        line_v(s, x1 - 1, y0, y1 - 1, dark);
        for (k = 0; w->title[k] && o + 1 < sizeof(label); k++)
            if (w->title[k] != '&')
                label[o++] = w->title[k];
        label[o] = 0;
        tw = text_extent(label, 11);
        text(s, x0 + (x1 - x0 - tw) / 2 + (pr ? 1 : 0), y0 + (y1 - y0 - 11) / 2 - 1 + (pr ? 1 : 0), label, 11, black);
    }
}

static void paint_dialog_child(void *ctx, Window *child, int ox, int oy) { paint((Scene *)ctx, child, ox - 0, oy - 0); }

/* Open dialogs, as Windows 98 draws them (ui.c): over everything else, the one opened last on top, except for an ordinary top-level window made after the dialog
 * that is open (the deck builder, which the duel program's setup dialog starts and which then works beside it): that is above the dialog, so those are drawn in
 * the order they were made, dialogs and windows alike. `tops` are the visible top-level windows, `nt` of them, by stacking order. */
static void draw_dialog(Scene *s, Window *win)
{
    extern uint32_t wm_pressed_button(void);

    ui_dialog(s->rgb, SCREEN_W, SCREEN_H, win, wm_pressed_button(), paint_dialog_child, s);
}

static void draw_dialogs_and_late_tops(Scene *s, Window **late, int nlate)
{
    int d = 0, nd = wm_dialog_count(), l = 0;

    while (d < nd || l < nlate) {
        Window *win = d < nd ? wm_window(wm_dialog_at(d)) : NULL;

        if (d < nd && !win) {
            d++;
            continue;
        }
        if (l < nlate && (!win || late[l]->hwnd < win->hwnd)) {
            paint(s, late[l++], 0, 0);
            continue;
        }
        draw_dialog(s, win);
        d++;
    }
}

/* The list of a combo box that is down, over the dialogs. */
static void draw_combo_list(Scene *s)
{
    Window *w = wm_window((uint32_t)wm_combo_open());

    if (w)
        ui_combo_list(s->rgb, SCREEN_W, SCREEN_H, w);
}

/* The open popup menu (menus.c), if any, over the screen. */
static void draw_popup(Scene *s)
{
    int li, nl = wm_popup_levels();
    static const uint8_t face[3] = {240, 240, 240}, edge[3] = {60, 60, 60}, sep[3] = {150, 150, 150}, navy[3] = {0, 0, 128}, black[3] = {0, 0, 0},
                         grey[3] = {150, 150, 150}, white[3] = {255, 255, 255};

    for (li = 0; li < nl; li++) {
        int x, y, w, h, i;
        const char *txt;
        uint32_t flags;
        int y0, y1, hot;

        wm_popup_geometry(li, &x, &y, &w, &h);
        rect(s, x, y, x + w - 1, y + h - 1, face, edge);
        for (i = 0; wm_popup_row(li, i, &txt, &flags, &y0, &y1, &hot); i++) {
            int isgrey = (flags & 3) != 0;
            const uint8_t *col;
            char label[128], accel[64];
            const char *tab;

            if (flags & 0x800) {
                line_h(s, x + 3, x + w - 4, (y0 + y1) / 2, sep);
                continue;
            }
            hot = hot && !isgrey;
            if (hot)
                rect(s, x + 2, y0, x + w - 3, y1 - 1, navy, NULL);
            col = hot ? white : isgrey ? grey : black;
            if (flags & 8)
                text(s, x + 6, y0 + 2, "v", 12, col);
            tab = strchr(txt, '\t');
            snprintf(label, sizeof(label), "%.*s", tab ? (int)(tab - txt) : (int)strlen(txt), txt);
            {
                char *amp;

                while ((amp = strchr(label, '&')))
                    memmove(amp, amp + 1, strlen(amp));
            }
            text(s, x + 20, y0 + 2, label, 12, col);
            if (tab) {
                snprintf(accel, sizeof(accel), "%s", tab + 1);
                text(s, x + w - 8 - text_extent(accel, 12), y0 + 2, accel, 12, col);
            }
            if (flags & 0x10)
                text(s, x + w - 12, y0 + 2, ">", 12, col);
        }
    }
}

/* STATWIN's wait after its two clips (crystal ball, then the wizard's hit): the clips are erased and the game waits for a click or a key with nothing else on the screen,
 * which looks like a freeze. If the whole screen is black, say what it waits for. (The original had the statistics window under the clips; ours is not drawn.) */
static void draw_held_hint(Scene *s)
{
    static const uint8_t grey[3] = {170, 170, 170};
    static const char msg[] = "Click or press a key to continue";
    size_t i, n = (size_t)SCREEN_W * SCREEN_H * 3;

    for (i = 0; i < n; i++)
        if (s->rgb[i])
            return;
    text(s, (SCREEN_W - text_extent(msg, 14)) / 2, SCREEN_H - 40, msg, 14, grey);
}

void compose_screen(uint8_t *rgb)
{
    Scene s = {rgb};

    movie_tick();
    int i, n = wm_window_count(), j, k;
    Window **tops = malloc((size_t)(n + 1) * sizeof(*tops));
    int nt = 0;

    memset(rgb, 0, (size_t)SCREEN_W * SCREEN_H * 3);
    for (i = 0; i < n; i++) {
        Window *w = wm_window_at_index(i);

        if (w && w->visible && !(w->style & WS_CHILD) && w->hwnd != wm_desktop_hwnd() && !w->is_dialog)
            tops[nt++] = w;
    }
    for (j = 1; j < nt; j++) {
        Window *t = tops[j];

        for (k = j - 1; k >= 0 && tops[k]->z > t->z; k--)
            tops[k + 1] = tops[k];
        tops[k + 1] = t;
    }
    {
        Window **late = malloc((size_t)(nt + 1) * sizeof(*late));
        int nlate = 0;
        uint32_t first_dialog = wm_dialog_count() ? wm_dialog_at(0) : 0;

        for (j = 0; j < nt; j++) {
            if (first_dialog && tops[j]->hwnd > first_dialog)
                late[nlate++] = tops[j];
            else
                paint(&s, tops[j], 0, 0);
        }
        for (j = 1; j < nlate; j++) {                    /* by when they were made */
            Window *t = late[j];

            for (k = j - 1; k >= 0 && late[k]->hwnd > t->hwnd; k--)
                late[k + 1] = late[k];
            late[k + 1] = t;
        }
        draw_buttons(&s);
        draw_dialogs_and_late_tops(&s, late, nlate);
        free(late);
    }
    free(tops);
    draw_combo_list(&s);
    draw_popup(&s);
    if (wm_held_clip())
        draw_held_hint(&s);
}

int compose_write_ppm(const char *path)
{
    uint8_t *rgb = malloc((size_t)SCREEN_W * SCREEN_H * 3);
    FILE *f = fopen(path, "wb");

    if (!f) {
        free(rgb);
        return 0;
    }
    compose_screen(rgb);
    fprintf(f, "P6\n%d %d\n255\n", SCREEN_W, SCREEN_H);
    fwrite(rgb, 3, (size_t)SCREEN_W * SCREEN_H, f);
    fclose(f);
    free(rgb);
    return 1;
}

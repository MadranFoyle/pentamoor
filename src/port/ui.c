/* ui.c - how Windows 98 draws a dialog and the standard controls in it: the frame and caption, push buttons, check boxes, radio buttons, group boxes, static text,
 * edit boxes, list boxes, combo boxes and spin buttons. A dialog is made of windows, and the game's dialog templates name only classes and styles; what the
 * controls look like is the system's. The colours are the Windows 98 standard scheme; the text is the dialog's own font (DS_SETFONT) from the game's font files when it
 * has them, else the host's sans serif. What a control's parent said about its colours (WM_CTLCOLOR..., controls.c) is applied: a text colour, a brush, or none at all
 * (the control draws over the dialog's artwork).
 *
 * Everything here draws on the composed screen (compose.c): an RGB buffer. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "gdi_int.h"
#include "sched.h"

typedef struct Canvas { uint8_t *rgb; int w, h; } Canvas;

static const uint8_t FACE[3] = {192, 192, 192}, HILIGHT[3] = {255, 255, 255}, LIGHT[3] = {223, 223, 223}, SHADOW[3] = {128, 128, 128}, DARK[3] = {0, 0, 0},
                     NAVY[3] = {0, 0, 128}, WINDOW[3] = {255, 255, 255}, BLACK[3] = {0, 0, 0};

static void put(Canvas *c, int x, int y, const uint8_t col[3])
{
    if (x >= 0 && y >= 0 && x < c->w && y < c->h)
        memcpy(c->rgb + 3 * ((size_t)y * (size_t)c->w + (size_t)x), col, 3);
}

static void fill(Canvas *c, int x0, int y0, int x1, int y1, const uint8_t col[3])    /* x1, y1 exclusive */
{
    int x, y;

    for (y = y0; y < y1; y++)
        for (x = x0; x < x1; x++)
            put(c, x, y, col);
}

static void hline(Canvas *c, int x0, int x1, int y, const uint8_t col[3]) { fill(c, x0, y, x1, y + 1, col); }
static void vline(Canvas *c, int x, int y0, int y1, const uint8_t col[3]) { fill(c, x, y0, x + 1, y1, col); }

/* A frame of `w` pixels in two colours: `tl` on the top and left, `br` on the bottom and right (corners to br). */
static void bevel(Canvas *c, int x0, int y0, int x1, int y1, const uint8_t tl[3], const uint8_t br[3])
{
    hline(c, x0, x1 - 1, y0, tl);
    vline(c, x0, y0, y1 - 1, tl);
    hline(c, x0, x1, y1 - 1, br);
    vline(c, x1 - 1, y0, y1, br);
}

/* ---- text ---------------------------------------------------------------------------------------------------------------------------- */
typedef struct UiFont { const char *face; int pt, bold; int height, ascent; } UiFont;

/* A control that is not in a dialog (the Magic Shell's radio buttons and labels sit on its main window) is drawn in the font its window was given (WM_SETFONT), at the pixel size
 * Windows would realise: set for the length of one draw_control, face and pixels (`pt` below is then minus the pixels, which ui_pixel_size reads as such). */
static const char *ctl_face;
static int ctl_px, ctl_bold;

static UiFont ui_font(const Window *dlg, int bold)
{
    UiFont f;

    if (ctl_face) {
        f.face = ctl_face;
        f.pt = -ctl_px;
        f.bold = ctl_bold || bold;
        ui_font_metrics(f.face, f.pt, f.bold, &f.height, &f.ascent, NULL);
        return f;
    }
    f.face = dlg && dlg->dlg_face[0] ? dlg->dlg_face : "MS Sans Serif";
    f.pt = dlg && dlg->dlg_pt ? dlg->dlg_pt : 8;
    f.bold = bold;
    ui_font_metrics(f.face, f.pt, bold, &f.height, &f.ascent, NULL);
    return f;
}

static int text_w(const UiFont *f, const char *s, size_t n) { return ui_text_width(f->face, f->pt, f->bold, s, n); }

static void text_at(Canvas *c, const UiFont *f, int x, int y, const char *s, size_t n, const uint8_t col[3])
{
    ui_text_draw(c->rgb, c->w, c->h, x, y, s, n, f->face, f->pt, f->bold, col);
}

/* A label without its `&`, and where the underlined character is (-1: none). */
static size_t strip_amp(const char *in, char *out, size_t cap, int *underline)
{
    size_t o = 0, k;

    *underline = -1;
    for (k = 0; in[k] && o + 1 < cap; k++) {
        if (in[k] == '&' && in[k + 1] == '&') {
            out[o++] = '&';
            k++;
        } else if (in[k] == '&') {
            if (*underline < 0 && in[k + 1])
                *underline = (int)o;
        } else
            out[o++] = in[k];
    }
    out[o] = 0;
    return o;
}

/* One line of text at a position, with its mnemonic underlined; disabled text is embossed. */
static void label_line(Canvas *c, const UiFont *f, int x, int y, const char *s, size_t n, int underline, const uint8_t col[3], int disabled)
{
    if (disabled) {
        text_at(c, f, x + 1, y + 1, s, n, HILIGHT);
        text_at(c, f, x, y, s, n, SHADOW);
    } else
        text_at(c, f, x, y, s, n, col);
    if (underline >= 0 && (size_t)underline < n) {
        int ux = x + text_w(f, s, (size_t)underline), uw = text_w(f, s + underline, 1);

        hline(c, ux, ux + uw, y + f->ascent + 1, disabled ? SHADOW : col);
    }
}

/* Text wrapped to a width (DT_WORDBREAK), each line aligned (0 left, 1 centre, 2 right); returns the height used. With no canvas nothing is drawn: it only measures, and
 * `widest` (if given) is the width of the longest line. */
static int wrapped_text(Canvas *c, const UiFont *f, int x, int y, int width, const char *s, int align, int wrap, const uint8_t col[3], int disabled, int underline, int *widest)
{
    size_t n = strlen(s), at = 0;
    int line = 0;

    for (;;) {
        size_t fit = at, we = at;
        int hard = 0;

        for (;;) {                                         /* take words while they fit */
            while (we < n && s[we] != ' ' && s[we] != '\n')
                we++;
            if (wrap && we > at && fit > at && text_w(f, s + at, we - at) > width)
                break;                                     /* this word does not fit: the line ends before it */
            fit = we;
            if (we >= n || s[we] == '\n') {
                hard = 1;
                break;
            }
            we++;                                          /* the space */
        }
        {
            size_t end = fit, lw_end;
            int lw, tx, ul;

            lw_end = end;
            while (lw_end > at && (s[lw_end - 1] == '\r' || s[lw_end - 1] == ' '))
                lw_end--;
            lw = text_w(f, s + at, lw_end - at);
            tx = align == 1 ? x + (width - lw) / 2 : align == 2 ? x + width - lw : x;
            ul = underline >= (int)at && underline < (int)lw_end ? underline - (int)at : -1;
            if (c)
                label_line(c, f, tx, y + line * f->height, s + at, lw_end - at, ul, col, disabled);
            if (widest && lw > *widest)
                *widest = lw;
        }
        line++;
        if (fit >= n)
            break;
        at = fit + (s[fit] == ' ' || s[fit] == '\n' ? 1 : 0);
        if (hard && at > n)
            break;
        if (at >= n && !hard)
            break;
    }
    return line * f->height;
}

/* ---- the pieces ------------------------------------------------------------------------------------------------------------------------- */
static void arrow(Canvas *c, int cx, int cy, int dir, const uint8_t col[3])       /* a small triangle: 0 up, 1 down, 2 left, 3 right */
{
    int i;

    for (i = 0; i < 4; i++) {
        if (dir == 0) hline(c, cx - i, cx + i + 1, cy - 2 + i, col);
        else if (dir == 1) hline(c, cx - i, cx + i + 1, cy + 2 - i, col);
        else if (dir == 2) vline(c, cx - 2 + i, cy - i, cy + i + 1, col);
        else vline(c, cx + 2 - i, cy - i, cy + i + 1, col);
    }
}

/* A raised push-button face (and its sunken look when pressed). */
static void button_face(Canvas *c, int x0, int y0, int x1, int y1, int pressed, int is_default)
{
    if (is_default) {
        bevel(c, x0, y0, x1, y1, DARK, DARK);
        x0++; y0++; x1--; y1--;
    }
    fill(c, x0, y0, x1, y1, FACE);
    if (pressed) {
        bevel(c, x0, y0, x1, y1, SHADOW, SHADOW);
    } else {
        bevel(c, x0, y0, x1, y1, HILIGHT, DARK);
        bevel(c, x0 + 1, y0 + 1, x1 - 1, y1 - 1, LIGHT, SHADOW);
    }
}

/* The sunken frame of an edit box, list box or combo box. */
static void sunken(Canvas *c, int x0, int y0, int x1, int y1)
{
    bevel(c, x0, y0, x1, y1, SHADOW, HILIGHT);
    bevel(c, x0 + 1, y0 + 1, x1 - 1, y1 - 1, DARK, LIGHT);
}

static void vscrollbar(Canvas *c, int x0, int y0, int x1, int y1, int nitems, int visible, int top)
{
    int h = y1 - y0, bw = x1 - x0, thumb_h, thumb_y;

    fill(c, x0, y0, x1, y1, LIGHT);
    button_face(c, x0, y0, x1, y0 + bw, 0, 0);
    arrow(c, (x0 + x1) / 2, y0 + bw / 2, 0, BLACK);
    button_face(c, x0, y1 - bw, x1, y1, 0, 0);
    arrow(c, (x0 + x1) / 2, y1 - bw / 2 - 1, 1, BLACK);
    thumb_h = nitems > visible && nitems > 0 ? (h - 2 * bw) * visible / nitems : h - 2 * bw;
    if (thumb_h < 8)
        thumb_h = 8;
    thumb_y = y0 + bw;
    if (nitems > visible && top > 0)                       /* the thumb follows the first shown item */
        thumb_y += (h - 2 * bw - thumb_h) * (top > nitems - visible ? nitems - visible : top) / (nitems - visible);
    if (thumb_y + thumb_h > y1 - bw)
        thumb_h = y1 - bw - thumb_y;
    if (thumb_h > 0)
        button_face(c, x0, thumb_y, x1, thumb_y + thumb_h, 0, 0);
}

/* ---- the dialog and its controls ------------------------------------------------------------------------------------------------------- */
static void draw_frame(Canvas *c, const Window *d, int x0, int y0, int x1, int y1)
{
    UiFont cf = ui_font(NULL, 1);

    if (d->nc_l == 1) {
        bevel(c, x0, y0, x1, y1, BLACK, BLACK);
        return;
    }
    if (d->nc_l < 3)
        return;
    bevel(c, x0, y0, x1, y1, LIGHT, DARK);
    bevel(c, x0 + 1, y0 + 1, x1 - 1, y1 - 1, HILIGHT, SHADOW);
    bevel(c, x0 + 2, y0 + 2, x1 - 2, y1 - 2, FACE, FACE);
    if (d->nc_t > d->nc_l) {                               /* the caption: navy to blue, the title in bold white, the close box */
        int cx0 = x0 + 3, cx1 = x1 - 3, cy0 = y0 + 3, cy1 = y0 + d->nc_t - 1, x;
        int bx1 = cx1 - 2, bx0 = bx1 - 16, by0 = cy0 + 2, by1 = by0 + 14;
        static const uint8_t white[3] = {255, 255, 255};

        for (x = cx0; x < cx1; x++) {
            uint8_t col[3];
            int t = cx1 - cx0 > 1 ? (x - cx0) * 255 / (cx1 - cx0 - 1) : 0;

            col[0] = (uint8_t)(0 + 16 * t / 255);
            col[1] = (uint8_t)(0 + 132 * t / 255);
            col[2] = (uint8_t)(128 + 80 * t / 255);
            vline(c, x, cy0, cy1, col);
        }
        text_at(c, &cf, cx0 + 3, cy0 + (cy1 - cy0 - cf.height) / 2, d->title, strlen(d->title), white);
        if (d->style & 0x80000u) {                          /* WS_SYSMENU */
            int i;

            button_face(c, bx0, by0, bx1, by1, 0, 0);
            for (i = 0; i < 7; i++) {
                put(c, bx0 + 4 + i / 1 - 1 + 0, by0 + 3 + i, BLACK);
                put(c, bx0 + 5 + i - 1, by0 + 3 + i, BLACK);
                put(c, bx0 + 10 - i - 1 + 0, by0 + 3 + i, BLACK);
                put(c, bx0 + 11 - i - 1, by0 + 3 + i, BLACK);
            }
        }
    }
}

static const Window *dialog_of(const Window *w)
{
    while (w && !w->is_dialog && !w->dlgproc)
        w = w->parent ? wm_window(w->parent) : NULL;
    return w;
}

static void draw_button(Canvas *c, const Window *w, const Window *dlg, int x0, int y0, int x1, int y1, int pressed)
{
    UiFont f = ui_font(dlg, 0);
    char label[256];
    int ul, kind = (int)(w->style & 0xF), disabled = !w->enabled || (w->style & 0x08000000u), ty;
    const uint8_t *fg = w->ctl_has_fg && !disabled ? w->ctl_fg : BLACK;
    size_t n = strip_amp(w->title, label, sizeof(label), &ul);

    ty = y0 + (y1 - y0 - f.height) / 2;
    if (kind == 0 || kind == 1 || kind == 8 || kind == 10) {                       /* push buttons */
        int tw = text_w(&f, label, n), off = pressed ? 1 : 0;

        button_face(c, x0, y0, x1, y1, pressed, kind == 1);
        label_line(c, &f, x0 + (x1 - x0 - tw) / 2 + off, ty + off, label, n, ul, fg, disabled);
    } else if (kind == 7) {                                                       /* group box */
        int top = y0 + f.height / 2, tw = text_w(&f, label, n);
        int gx0 = x0 + 6, gx1 = x0 + 6 + tw + 4;
        int open_gap = n && w->ctl_transparent && !w->ctl_has_bg;                /* the parent gave no brush (the Magic Shell's pages): artwork shows through, so the frame is left out under the label */

        if (!w->ctl_transparent)
            fill(c, x0, y0, x1, y1, w->ctl_has_bg ? w->ctl_bg : FACE);
        if (open_gap) {
            hline(c, x0, gx0, top, SHADOW);                                          /* the frame, two lines thick, its top edge in two pieces */
            hline(c, gx1 < x1 - 1 ? gx1 : x1 - 1, x1 - 1, top, SHADOW);
            vline(c, x0, top, y1 - 1, SHADOW);
            hline(c, x0, x1, y1 - 1, HILIGHT);
            vline(c, x1 - 1, top, y1, HILIGHT);
            hline(c, x0 + 1, gx0, top + 1, HILIGHT);
            hline(c, gx1 < x1 - 2 ? gx1 : x1 - 2, x1 - 2, top + 1, HILIGHT);
            vline(c, x0 + 1, top + 1, y1 - 2, HILIGHT);
            hline(c, x0 + 1, x1 - 1, y1 - 2, SHADOW);
            vline(c, x1 - 2, top + 1, y1 - 1, SHADOW);
        } else {
            bevel(c, x0, top, x1, y1, SHADOW, HILIGHT);
            bevel(c, x0 + 1, top + 1, x1 - 1, y1 - 1, HILIGHT, SHADOW);
        }
        if (n) {                       /* the label sits on a strip of the face colour that hides the frame, over artwork too (Windows 98's DUEL.EXE setup dialog shows it so) */
            if (!open_gap)
                fill(c, gx0, y0, gx1, y0 + f.height, w->ctl_has_bg ? w->ctl_bg : FACE);
            label_line(c, &f, x0 + 8, y0, label, n, ul, fg, disabled);
        }
    } else if (kind == 2 || kind == 3 || kind == 5 || kind == 6) {                 /* check boxes */
        int by = y0 + (y1 - y0 - 13) / 2;

        fill(c, x0, by, x0 + 13, by + 13, WINDOW);
        sunken(c, x0, by, x0 + 13, by + 13);
        if (w->checked) {
            int i;

            for (i = 0; i < 3; i++) {
                vline(c, x0 + 3 + i, by + 5 + i, by + 8 + i, disabled ? SHADOW : BLACK);
            }
            for (i = 0; i < 4; i++)
                vline(c, x0 + 6 + i, by + 7 - i, by + 10 - i, disabled ? SHADOW : BLACK);
        }
        label_line(c, &f, x0 + 18, y0 + (y1 - y0 - f.height - 2) / 2, label, n, ul, fg, disabled);     /* a check box's or radio button's text sits a pixel above the centre */
    } else if (kind == 4 || kind == 9) {                                          /* radio buttons: a 12 x 12 round box */
        int rx = x0, ry = y0 + (y1 - y0 - 12) / 2, px, py;

        for (py = 0; py < 12; py++)
            for (px = 0; px < 12; px++) {
                double dx = px - 5.5, dy = py - 5.5, d = dx * dx + dy * dy;
                int upper = px + py < 11;

                if (d <= 16)
                    put(c, rx + px, ry + py, WINDOW);
                else if (d <= 25)
                    put(c, rx + px, ry + py, upper ? DARK : LIGHT);
                else if (d <= 36)
                    put(c, rx + px, ry + py, upper ? SHADOW : HILIGHT);
                if (w->checked && d <= 5)
                    put(c, rx + px, ry + py, disabled ? SHADOW : BLACK);
            }
        label_line(c, &f, x0 + 18, y0 + (y1 - y0 - f.height - 2) / 2, label, n, ul, fg, disabled);     /* a check box's or radio button's text sits a pixel above the centre */
    }
}

/* The four icons of a message box, 32 x 32 and drawn here rather than loaded: a blue "?" in a circle (MB_ICONQUESTION), a yellow triangle with "!" (MB_ICONEXCLAMATION), a red
 * circle with a white cross (MB_ICONERROR), a blue "i" in a circle (MB_ICONINFORMATION). */
static void draw_msg_icon(Canvas *c, int x0, int y0, char kind)
{
    static const uint8_t RED[3] = {255, 0, 0}, BLUE[3] = {0, 0, 255}, YEL[3] = {255, 255, 0}, WHITE[3] = {255, 255, 255};
    int px, py;
    UiFont f = {"MS Sans Serif", 19, 1, 0, 0};
    char g[2] = {kind == 'x' ? 'X' : kind, 0};

    ui_font_metrics(f.face, f.pt, 1, &f.height, &f.ascent, NULL);
    for (py = 0; py < 32; py++)
        for (px = 0; px < 32; px++) {
            double dx = px - 15.5, dy = py - 15.5, d = dx * dx + dy * dy;

            if (kind == '!') {                                            /* the triangle: from the apex down, widening by a pixel every two rows */
                int half = 1 + py * 14 / 28;

                if (py >= 2 && py < 30 && px >= 16 - half && px < 16 + half)
                    put(c, x0 + px, y0 + py, (px == 16 - half || px == 15 + half || py == 29) ? DARK : YEL);
            } else if (d <= 15.0 * 15.0)
                put(c, x0 + px, y0 + py, d > 14.0 * 14.0 ? DARK : kind == 'x' ? RED : BLUE);
        }
    if (kind == '!')
        text_at(c, &f, x0 + (32 - text_w(&f, g, 1)) / 2, y0 + 8, g, 1, DARK);
    else
        text_at(c, &f, x0 + (32 - text_w(&f, g, 1)) / 2, y0 + (32 - f.height) / 2, g, 1, WHITE);
}

static void draw_static(Canvas *c, const Window *w, const Window *dlg, int x0, int y0, int x1, int y1)
{
    UiFont f = ui_font(dlg, 0);
    char label[1024];
    int kind = (int)(w->style & 0x1F), ul = -1, disabled = !w->enabled || (w->style & 0x08000000u), align;
    const uint8_t *fg = w->ctl_has_fg && !disabled ? w->ctl_fg : BLACK;
    const uint8_t *bg = w->ctl_has_bg ? w->ctl_bg : FACE;

    if (kind == 4) { fill(c, x0, y0, x1, y1, BLACK); return; }                      /* SS_BLACKRECT */
    if (kind == 5) { fill(c, x0, y0, x1, y1, SHADOW); return; }                     /* SS_GRAYRECT */
    if (kind == 6) { fill(c, x0, y0, x1, y1, HILIGHT); return; }                    /* SS_WHITERECT */
    if (kind == 7) { bevel(c, x0, y0, x1, y1, BLACK, BLACK); return; }
    if (kind == 8) { bevel(c, x0, y0, x1, y1, SHADOW, SHADOW); return; }
    if (kind == 9) { bevel(c, x0, y0, x1, y1, HILIGHT, HILIGHT); return; }
    if (kind == 0x10 || kind == 0x11 || kind == 0x12) {                             /* SS_ETCHEDHORZ / VERT / FRAME */
        if (kind == 0x10) { hline(c, x0, x1, (y0 + y1) / 2 - 1, SHADOW); hline(c, x0, x1, (y0 + y1) / 2, HILIGHT); }
        else if (kind == 0x11) { vline(c, (x0 + x1) / 2 - 1, y0, y1, SHADOW); vline(c, (x0 + x1) / 2, y0, y1, HILIGHT); }
        else { bevel(c, x0, y0, x1, y1, SHADOW, HILIGHT); bevel(c, x0 + 1, y0 + 1, x1 - 1, y1 - 1, HILIGHT, SHADOW); }
        return;
    }
    if (kind == 3 && w->title[0] == '\x01' && w->title[1]) {                         /* a message box's icon (msgbox.c): \x01 and one of ! ? i x */
        draw_msg_icon(c, x0, y0, w->title[1]);
        return;
    }
    if (kind == 3 || kind == 0xD || kind == 0xE)                                    /* icons, owner-drawn and bitmaps are not text */
        return;
    if (!w->ctl_transparent)
        fill(c, x0, y0, x1, y1, bg);
    if (w->style & 0x800000u)                                                       /* WS_BORDER */
        bevel(c, x0, y0, x1, y1, BLACK, BLACK);
    if (w->style & 0x80u) {                                                         /* SS_NOPREFIX */
        snprintf(label, sizeof(label), "%s", w->title);
    } else
        strip_amp(w->title, label, sizeof(label), &ul);
    align = kind == 1 ? 1 : kind == 2 ? 2 : 0;
    wrapped_text(c, &f, x0, y0, x1 - x0, label, align, kind != 0xC && kind != 0xB, fg, disabled, ul, NULL);
}

/* How much room a static text needs: its height when wrapped to `width` pixels in a dialog font, and the width of its longest line (what the message box sizes itself by). */
int ui_text_measure(const char *face, int pt, int bold, const char *s, int width, int *widest)
{
    UiFont f;
    int w = 0, h;

    f.face = face;
    f.pt = pt;
    f.bold = bold;
    ui_font_metrics(face, pt, bold, &f.height, &f.ascent, NULL);
    h = wrapped_text(NULL, &f, 0, 0, width, s, 0, 1, BLACK, 0, -1, &w);
    if (widest)
        *widest = w;
    return h;
}

/* ---- edit boxes ------------------------------------------------------------------------------------------------------------------------------
 * One layout serves the drawing, the mouse (which byte offset is under a point), the caret and the scrolling, so they cannot drift apart. A one-line box is one line of text, scrolled to the
 * left by `edit_xscroll` pixels when it is wider than the box; a multi-line box (ES_MULTILINE) wraps its text to its width into visual lines and shows `edit_top` onward, with a scroll bar when
 * the window has WS_VSCROLL. Offsets are bytes of the window's own text (edit.c). The text of a password box is drawn (and measured) as asterisks. */
typedef struct EditGeo {
    int x0, y0, x1, y1;                 /* the control, on the screen */
    int tx0, ty0, tx1, ty1;             /* the text's area: inside the frame, left of the scroll bar */
    int sb;                             /* the scroll bar's left edge, or 0 for none */
    int inset, ml;
    UiFont f;
} EditGeo;

typedef struct VLine { int start, end, next; } VLine;      /* a visual line: its text is [start, end); the next line starts at `next` (after a line break, if the line ended with one) */

static UiFont edit_font(const Window *w, const Window *dlg)
{
    const char *face = NULL, *old_face = ctl_face;
    int bold = 0, px = 0, old_px = ctl_px, old_bold = ctl_bold;
    UiFont f;

    if (!dlg && w->hfont && gdi_font_object(w->hfont, &face, &bold, &px)) {
        ctl_face = face;
        ctl_px = px;
        ctl_bold = bold;
        f = ui_font(dlg, 0);
        ctl_face = old_face;
        ctl_px = old_px;
        ctl_bold = old_bold;
        return f;
    }
    return ui_font(dlg, 0);
}

static void edit_geo(const Window *w, const Window *dlg, EditGeo *g)
{
    int three_d = (dlg && (dlg->style & 4u)) || (w->exstyle & 0x200u);

    wm_abs_rect(w, &g->x0, &g->y0, &g->x1, &g->y1);
    g->f = edit_font(w, dlg);
    g->inset = three_d ? 2 : 1;
    g->ml = (w->style & 4u) != 0;
    g->tx0 = g->x0 + g->inset + 1;
    g->tx1 = g->x1 - g->inset - 1;
    g->ty0 = g->y0 + g->inset;
    g->ty1 = g->y1 - g->inset;
    g->sb = 0;
    if (g->ml && (w->style & 0x200000u) && g->x1 - g->x0 > 40) {        /* WS_VSCROLL */
        g->sb = g->x1 - g->inset - 16;
        g->tx1 = g->sb;
    }
}

static char *edit_shown(const Window *w, const char **s)         /* the text as it is drawn; the returned pointer (or NULL) is to be freed */
{
    if ((w->style & 0x20u) && !(w->style & 4u)) {                /* ES_PASSWORD */
        size_t n = strlen(w->title);
        char *t = malloc(n + 1);

        if (t) {
            memset(t, '*', n);
            t[n] = 0;
            *s = t;
            return t;
        }
    }
    *s = w->title;
    return NULL;
}

/* The wrapped lines of a multi-line box, kept (a few boxes' worth) until the text, the width or the font changes. */
typedef struct LCache { uint32_t hwnd, hash; size_t len; int width, pt, bold; const char *face; VLine *v; int n, age; } LCache;
static LCache lcache[4];
static int lcache_age;

static uint32_t text_hash(const char *s, size_t n)
{
    uint32_t h = 2166136261u;
    size_t i;

    for (i = 0; i < n; i++)
        h = (h ^ (unsigned char)s[i]) * 16777619u;
    return h;
}

static int fit_end(const UiFont *f, const char *s, int pos, int le, int width)        /* the last offset in (pos, le] whose text [pos, offset) fits */
{
    int lo = pos + 1, hi = le;

    if (text_w(f, s + pos, (size_t)(le - pos)) <= width)
        return le;
    while (lo < hi) {
        int mid = (lo + hi + 1) / 2;

        if (text_w(f, s + pos, (size_t)(mid - pos)) <= width)
            lo = mid;
        else
            hi = mid - 1;
    }
    return lo;
}

static VLine *build_lines(const char *s, size_t len, const UiFont *f, int width, int *nout)
{
    int cap = 64, n = 0, pos = 0;
    VLine *v = malloc((size_t)cap * sizeof(*v));

    if (!v)
        return NULL;
    for (;;) {
        int le = pos, brk = 0, e;

        while ((size_t)le < len && s[le] != '\r' && s[le] != '\n')
            le++;
        if ((size_t)le < len)
            brk = (s[le] == '\r' && (size_t)le + 1 < len && s[le + 1] == '\n') ? 2 : 1;
        for (;;) {                                              /* the line from pos to le, wrapped */
            if (n == cap) {
                VLine *nv = realloc(v, (size_t)(cap *= 2) * sizeof(*v));

                if (!nv) {
                    free(v);
                    return NULL;
                }
                v = nv;
            }
            e = le;
            if (width > 0 && le > pos && text_w(f, s + pos, (size_t)(le - pos)) > width) {
                int k;

                e = fit_end(f, s, pos, le, width);
                if (e < le) {
                    if (s[e] == ' ') {
                        e++;                                    /* the space after the last word that fits hangs on the line */
                    } else {
                        for (k = e - 1; k > pos; k--)
                            if (s[k] == ' ') {
                                e = k + 1;
                                break;
                            }
                    }
                }
            }
            if (e >= le) {
                v[n++] = (VLine){pos, le, le + brk};
                break;
            }
            v[n++] = (VLine){pos, e, e};
            pos = e;
        }
        pos = le + brk;
        if (!brk)
            break;
    }
    *nout = n;
    return v;
}

static const VLine *edit_vlines(const Window *w, const EditGeo *g, const char *s, int *n)
{
    size_t len = strlen(s);
    uint32_t h = text_hash(s, len);
    int width = g->tx1 - g->tx0, i, oldest = 0;

    for (i = 0; i < 4; i++)
        if (lcache[i].v && lcache[i].hwnd == w->hwnd && lcache[i].hash == h && lcache[i].len == len && lcache[i].width == width && lcache[i].pt == g->f.pt &&
            lcache[i].bold == g->f.bold && lcache[i].face == g->f.face) {
            *n = lcache[i].n;
            return lcache[i].v;
        }
    for (i = 0; i < 4; i++) {
        if (lcache[i].hwnd == w->hwnd) {                         /* the box's own entry is replaced */
            oldest = i;
            break;
        }
        if (!lcache[i].v) {
            oldest = i;
            break;
        }
        if (lcache[i].age < lcache[oldest].age)
            oldest = i;
    }
    free(lcache[oldest].v);
    lcache[oldest] = (LCache){w->hwnd, h, len, width, g->f.pt, g->f.bold, g->f.face, build_lines(s, len, &g->f, width, n), 0, ++lcache_age};
    if (!lcache[oldest].v) {
        *n = 0;
        return NULL;
    }
    lcache[oldest].n = *n;
    return lcache[oldest].v;
}

static int line_at(const VLine *v, int n, int off)               /* the last line that starts at or before an offset */
{
    int i, at = 0;

    for (i = 0; i < n; i++)
        if (v[i].start <= off)
            at = i;
    return at;
}

static int page_of(const EditGeo *g)
{
    int p = (g->ty1 - g->ty0) / g->f.height;

    return p < 1 ? 1 : p;
}

static int single_x(const Window *w, const EditGeo *g, int tw)  /* where a one-line box's text starts */
{
    int vw = g->tx1 - g->tx0;

    if (tw <= vw)
        return (w->style & 3u) == 1 ? g->x0 + (g->x1 - g->x0 - tw) / 2 : (w->style & 3u) == 2 ? g->x1 - g->inset - 1 - tw : g->tx0;
    return g->tx0 - w->edit_xscroll;
}

static int nearest_boundary(const UiFont *f, const char *s, int a, int b, int lx)      /* the offset in [a, b] whose left edge is nearest to lx (pixels from the start of s + a) */
{
    int i, prev = 0;

    for (i = a; i < b; i++) {
        int next = text_w(f, s + a, (size_t)(i + 1 - a));

        if (lx < (prev + next) / 2)
            return i;
        prev = next;
    }
    return b;
}

int ui_edit_index_at(const Window *w, int x, int y)
{
    EditGeo g;
    const char *s;
    char *own;
    int r = 0, len;

    if (!w || !w->title)
        return 0;
    edit_geo(w, dialog_of(w), &g);
    own = edit_shown(w, &s);
    len = (int)strlen(s);
    if (!g.ml) {
        r = nearest_boundary(&g.f, s, 0, len, x - single_x(w, &g, text_w(&g.f, s, (size_t)len)));
    } else {
        int n, line;
        const VLine *v = edit_vlines(w, &g, s, &n);

        if (v) {
            line = w->edit_top + (y - g.ty0) / g.f.height;
            line = line < 0 ? 0 : line >= n ? n - 1 : line;
            r = nearest_boundary(&g.f, s, v[line].start, v[line].end, x - g.tx0);
        }
    }
    free(own);
    return r;
}

int ui_edit_line_count(const Window *w)
{
    EditGeo g;
    const char *s;
    char *own;
    int n = 1;

    if (!w || !w->title)
        return 1;
    edit_geo(w, dialog_of(w), &g);
    own = edit_shown(w, &s);
    if (g.ml)
        edit_vlines(w, &g, s, &n);
    free(own);
    return n;
}

int ui_edit_page_lines(const Window *w)
{
    EditGeo g;

    if (!w)
        return 1;
    edit_geo(w, dialog_of(w), &g);
    return page_of(&g);
}

int ui_edit_line_of(const Window *w, int offset)
{
    EditGeo g;
    const char *s;
    char *own;
    int n, at = 0;

    if (!w || !w->title)
        return 0;
    edit_geo(w, dialog_of(w), &g);
    if (g.ml) {
        const VLine *v;

        own = edit_shown(w, &s);
        v = edit_vlines(w, &g, s, &n);
        at = v ? line_at(v, n, offset) : 0;
        free(own);
    }
    return at;
}

int ui_edit_line_range(const Window *w, int line, int *start, int *end)
{
    EditGeo g;
    const char *s;
    char *own;
    int n, ok = 0;

    if (!w || !w->title)
        return 0;
    edit_geo(w, dialog_of(w), &g);
    own = edit_shown(w, &s);
    if (!g.ml) {
        if (line == 0) {
            *start = 0;
            *end = (int)strlen(s);
            ok = 1;
        }
    } else {
        const VLine *v = edit_vlines(w, &g, s, &n);

        if (v && line >= 0 && line < n) {
            *start = v[line].start;
            *end = v[line].end;
            ok = 1;
        }
    }
    free(own);
    return ok;
}

int ui_edit_x_in_line(const Window *w, int offset)                  /* the pixels from the start of the visual line an offset is on to the offset */
{
    EditGeo g;
    const char *s;
    char *own;
    int n, x = 0;

    if (!w || !w->title)
        return 0;
    edit_geo(w, dialog_of(w), &g);
    own = edit_shown(w, &s);
    if (g.ml) {
        const VLine *v = edit_vlines(w, &g, s, &n);

        if (v) {
            int l = line_at(v, n, offset);

            x = text_w(&g.f, s + v[l].start, (size_t)(offset - v[l].start));
        }
    } else
        x = text_w(&g.f, s, (size_t)offset);
    free(own);
    return x;
}

int ui_edit_offset_at(const Window *w, int line, int x)             /* the offset on a visual line nearest to x pixels from its start */
{
    EditGeo g;
    const char *s;
    char *own;
    int n, r = 0;

    if (!w || !w->title)
        return 0;
    edit_geo(w, dialog_of(w), &g);
    own = edit_shown(w, &s);
    if (g.ml) {
        const VLine *v = edit_vlines(w, &g, s, &n);

        if (v) {
            line = line < 0 ? 0 : line >= n ? n - 1 : line;
            r = nearest_boundary(&g.f, s, v[line].start, v[line].end, x);
        }
    }
    free(own);
    return r;
}

int ui_edit_scroll_to_caret(Window *w)
{
    EditGeo g;
    const char *s;
    char *own;
    int changed = 0;

    if (!w || !w->title)
        return 0;
    edit_geo(w, dialog_of(w), &g);
    own = edit_shown(w, &s);
    if (!g.ml) {
        int len = (int)strlen(s), caret = w->caret > len ? len : w->caret, tw = text_w(&g.f, s, (size_t)len), vw = g.tx1 - g.tx0, old = w->edit_xscroll, cx;

        if (tw <= vw) {
            w->edit_xscroll = 0;
        } else {
            cx = text_w(&g.f, s, (size_t)caret);
            if (cx - w->edit_xscroll >= vw)
                w->edit_xscroll = cx - vw + 1;
            else if (cx - w->edit_xscroll < 0)
                w->edit_xscroll = cx;
            if (w->edit_xscroll > tw - vw + 2)
                w->edit_xscroll = tw - vw + 2;
            if (w->edit_xscroll < 0)
                w->edit_xscroll = 0;
        }
        changed = old != w->edit_xscroll;
    } else {
        int n, page = page_of(&g), line, old = w->edit_top;
        const VLine *v = edit_vlines(w, &g, s, &n);

        if (v) {
            line = line_at(v, n, w->caret);
            if (line < w->edit_top)
                w->edit_top = line;
            else if (line >= w->edit_top + page)
                w->edit_top = line - page + 1;
            if (w->edit_top > n - page)
                w->edit_top = n - page;
            if (w->edit_top < 0)
                w->edit_top = 0;
            changed = old != w->edit_top;
        }
    }
    free(own);
    return changed;
}

/* The scroll bar of a multi-line box: the same arrows, track and thumb as vscrollbar draws. */
static void sb_geometry(const EditGeo *g, int nlines, int page, int top, int *thumb_y, int *thumb_h)
{
    int h = g->ty1 - g->ty0, bw = 16, th;
    int ty = g->ty0 + bw;

    th = nlines > page && nlines > 0 ? (h - 2 * bw) * page / nlines : h - 2 * bw;
    if (th < 8)
        th = 8;
    if (nlines > page && top > 0)
        ty += (h - 2 * bw - th) * (top > nlines - page ? nlines - page : top) / (nlines - page);
    if (ty + th > g->ty1 - bw)
        th = g->ty1 - bw - ty;
    *thumb_y = ty;
    *thumb_h = th;
}

int ui_edit_vscroll_hit(const Window *w, int x, int y, int *part)
{
    EditGeo g;
    int n, page, ty, th;

    if (!w || !w->title)
        return 0;
    edit_geo(w, dialog_of(w), &g);
    if (!g.sb || x < g.sb || x >= g.x1 - g.inset || y < g.ty0 || y >= g.ty1)
        return 0;
    n = ui_edit_line_count(w);
    page = page_of(&g);
    sb_geometry(&g, n, page, w->edit_top, &ty, &th);
    if (y < g.ty0 + 16)
        *part = 0;
    else if (y >= g.ty1 - 16)
        *part = 1;
    else if (y < ty)
        *part = 2;
    else if (y >= ty + th)
        *part = 3;
    else
        *part = 4;
    return 1;
}

int ui_edit_vscroll_pos(const Window *w, int y)                     /* the first line to show for a thumb dragged to a screen y (its middle) */
{
    EditGeo g;
    int n, page, h, th, span;

    if (!w || !w->title)
        return 0;
    edit_geo(w, dialog_of(w), &g);
    n = ui_edit_line_count(w);
    page = page_of(&g);
    if (n <= page)
        return 0;
    h = g.ty1 - g.ty0;
    th = (h - 32) * page / n;
    if (th < 8)
        th = 8;
    span = h - 32 - th;
    if (span <= 0)
        return 0;
    y -= g.ty0 + 16 + th / 2;
    y = y < 0 ? 0 : y > span ? span : y;
    return (n - page) * y / span;
}

static void edit_segment(Canvas *c, const UiFont *f, const char *s, int a, int b, int lo, int hi, int base_x, int y, const uint8_t col[3], const uint8_t *back, int line_h, int box_y0,
                         int box_y1, int disabled)
{
    int x;

    if (a < lo)
        a = lo;
    if (b > hi)
        b = hi;
    if (a >= b)
        return;
    x = base_x + text_w(f, s + lo, (size_t)(a - lo));
    if (back)
        fill(c, x, box_y0, x + text_w(f, s + a, (size_t)(b - a)), box_y1 < box_y0 + line_h ? box_y1 : box_y0 + line_h, back);
    label_line(c, f, x, y, s + a, (size_t)(b - a), -1, col, disabled);
}

static void draw_edit(Canvas *c, const Window *w, const Window *dlg, int x0, int y0, int x1, int y1)
{
    EditGeo g;
    const uint8_t *fg = w->ctl_has_fg ? w->ctl_fg : BLACK, *bg = w->ctl_has_bg ? w->ctl_bg : WINDOW;
    const char *s;
    char *own;
    int len, sa = 0, sb = 0, disabled = !w->enabled || (w->style & 0x08000000u), focused, show_caret, caret;

    (void)x0; (void)y0; (void)x1; (void)y1;
    edit_geo(w, dlg, &g);
    fill(c, g.x0, g.y0, g.x1, g.y1, bg);
    if (g.inset == 2)
        sunken(c, g.x0, g.y0, g.x1, g.y1);
    else if (w->style & 0x800000u)
        bevel(c, g.x0, g.y0, g.x1, g.y1, BLACK, BLACK);
    own = edit_shown(w, &s);
    len = (int)strlen(s);
    focused = wm_get_focus() == w->hwnd || w->has_caret || (w->style & 0x100u);          /* ES_NOHIDESEL: the selection stays shown without the focus */
    if (w->has_caret == 2) {                                                         /* the file dialog's: all of it selected */
        sa = 0;
        sb = len;
    } else if (!w->has_caret && focused && w->sel_anchor != w->caret) {                  /* (the file dialog's box keeps its own caret and never has a selection but all of it) */
        sa = w->sel_anchor < w->caret ? w->sel_anchor : w->caret;
        sb = w->sel_anchor < w->caret ? w->caret : w->sel_anchor;
        if (sa < 0)
            sa = 0;
        if (sb > len)
            sb = len;
    }
    caret = w->caret > len ? len : w->caret;
    show_caret = wm_edit_caret_visible(w) && w->enabled && !(w->style & 0x800u);
    if (!g.ml) {
        int tw = text_w(&g.f, s, (size_t)len), tx = single_x(w, &g, tw), ty = (g.ty0 + g.ty1 - g.f.height) / 2, first = 0, last = len;

        if (tw > g.tx1 - g.tx0) {                                                   /* scrolled: only what shows whole is drawn */
            while (first < len && tx + text_w(&g.f, s, (size_t)first) < g.tx0)
                first++;
            while (last > first && tx + text_w(&g.f, s, (size_t)last) > g.tx1)
                last--;
        }
        edit_segment(c, &g.f, s, 0, sa, first, last, tx, ty, fg, NULL, g.f.height, ty, g.ty1, disabled);
        edit_segment(c, &g.f, s, sa, sb, first, last, tx, ty, HILIGHT, NAVY, g.f.height, ty, g.ty1, 0);
        edit_segment(c, &g.f, s, sb, len, first, last, tx, ty, fg, NULL, g.f.height, ty, g.ty1, disabled);
        if (show_caret) {
            int cx = tx + text_w(&g.f, s, (size_t)caret);

            if (cx >= g.tx0 - 1 && cx <= g.tx1)
                vline(c, cx, ty, ty + g.f.height, fg);
        }
    } else {
        int n, page = page_of(&g), top = w->edit_top, i;
        const VLine *v = edit_vlines(w, &g, s, &n);

        if (v) {
            if (top > n - page)
                top = n - page;
            if (top < 0)
                top = 0;
            for (i = top; i < n && g.ty0 + (i - top + 1) * g.f.height <= g.ty1; i++) {
                int ty = g.ty0 + (i - top) * g.f.height, a = v[i].start, b = v[i].end;

                edit_segment(c, &g.f, s, a, sa < b ? sa : b, a, b, g.tx0, ty, fg, NULL, g.f.height, ty, g.ty1, disabled);
                edit_segment(c, &g.f, s, sa > a ? sa : a, sb < b ? sb : b, a, b, g.tx0, ty, HILIGHT, NAVY, g.f.height, ty, g.ty1, 0);
                edit_segment(c, &g.f, s, sb > a ? sb : a, b, a, b, g.tx0, ty, fg, NULL, g.f.height, ty, g.ty1, disabled);
                if (sa < sb && sa < v[i].next && sb > b && b < v[i].next && sb > v[i].start) {          /* the selection runs on over the line break: a little highlight after the last character */
                    int ex = g.tx0 + text_w(&g.f, s + a, (size_t)(b - a));

                    fill(c, ex, ty, ex + 6 < g.tx1 ? ex + 6 : g.tx1, ty + g.f.height, NAVY);
                }
                if (show_caret && caret >= a && caret <= b && (i == line_at(v, n, caret))) {
                    int cx = g.tx0 + text_w(&g.f, s + a, (size_t)(caret - a));

                    vline(c, cx, ty, ty + g.f.height, fg);
                }
            }
            if (g.sb)
                vscrollbar(c, g.sb, g.ty0, g.x1 - g.inset, g.ty1, n, page, top);
        }
    }
    free(own);
}

static void folder_icon(Canvas *c, int x, int y)       /* 14 x 12: a yellow folder */
{
    static const uint8_t YEL[3] = {255, 255, 0}, OLIVE[3] = {128, 128, 0};

    fill(c, x, y + 2, x + 6, y + 4, OLIVE);
    fill(c, x, y + 3, x + 14, y + 12, YEL);
    bevel(c, x, y + 3, x + 14, y + 12, OLIVE, OLIVE);
    hline(c, x + 1, x + 13, y + 4, HILIGHT);
}

static void file_icon(Canvas *c, int x, int y)         /* a white page */
{
    fill(c, x + 2, y + 1, x + 11, y + 13, HILIGHT);
    bevel(c, x + 2, y + 1, x + 11, y + 13, SHADOW, SHADOW);
    hline(c, x + 4, x + 9, y + 4, SHADOW);
    hline(c, x + 4, x + 9, y + 6, SHADOW);
    hline(c, x + 4, x + 9, y + 8, SHADOW);
}

static void draw_listbox(Canvas *c, const Window *w, const Window *dlg, int x0, int y0, int x1, int y1)
{
    UiFont f = ui_font(dlg, 0);
    int three_d = (dlg && (dlg->style & 4u)) || (w->exstyle & 0x200u) || (w->style & 0x800000u), inset = three_d ? 2 : 1, rows, i, right = x1 - inset;
    const uint8_t *bg = w->ctl_has_bg ? w->ctl_bg : WINDOW;
    int rowh = f.height + 1, top = w->top;

    if (w->lb_icons && rowh < 16)
        rowh = 16;
    fill(c, x0, y0, x1, y1, bg);
    if ((dlg && (dlg->style & 4u)) || (w->exstyle & 0x200u))
        sunken(c, x0, y0, x1, y1);
    else if (w->style & 0x800000u)
        bevel(c, x0, y0, x1, y1, BLACK, BLACK);
    rows = (y1 - y0 - 2 * inset) / rowh;
    if (rows < 1)
        rows = 1;
    if (top < 0 || top > w->nitems - rows)
        top = w->nitems > rows ? w->nitems - rows : 0;
    if (w->nitems > rows && (w->style & 0x200000u)) {
        vscrollbar(c, x1 - inset - 16, y0 + inset, x1 - inset, y1 - inset, w->nitems, rows, top);
        right = x1 - inset - 16;
    }
    for (i = top; i < w->nitems && i < top + rows; i++) {
        int ry = y0 + inset + (i - top) * rowh;
        int selected = i == w->sel, tx = x0 + inset + 2, ty = ry + (rowh - f.height) / 2;

        if (w->lb_icons) {
            if (w->items[i].data == 1)
                folder_icon(c, tx, ry + 1);
            else
                file_icon(c, tx, ry + 1);
            tx += 20;
        }
        if (selected) {
            int tw = text_w(&f, w->items[i].text, strlen(w->items[i].text)), sx1 = tx + tw + 2;

            fill(c, w->lb_icons ? tx - 1 : x0 + inset, ry, w->lb_icons ? (sx1 < right ? sx1 : right) : right, ry + rowh, NAVY);
        }
        label_line(c, &f, tx, ty, w->items[i].text, strlen(w->items[i].text), -1, selected ? HILIGHT : (w->ctl_has_fg ? w->ctl_fg : BLACK), 0);
    }
}

/* The row of a list box at a screen y (the rows start under the frame, `top` is the first one), or -1. */
int ui_listbox_row(const Window *w, int y)
{
    UiFont f = ui_font(dialog_of(w), 0);
    int x0, y0, x1, y1, inset = (((dialog_of(w) && (dialog_of(w)->style & 4u))) || (w->style & 0x800000u) || (w->exstyle & 0x200u)) ? 2 : 1, rowh = f.height + 1, k;

    wm_abs_rect(w, &x0, &y0, &x1, &y1);
    if (y < y0 + inset || y >= y1 - inset)
        return -1;
    k = w->top + (y - y0 - inset) / rowh;
    return k < w->nitems ? k : -1;
}

/* The rows draw_listbox draws, as pixels (the D-pad's targets, navwm.c): the first row's top, the row height, the number of rows that fit (at most the items there are), the first row's
 * index and the x range of a row (left of the scroll bar, if it has one). */
void ui_listbox_geometry(const Window *w, int *y_first, int *rowh, int *rows, int *top, int *x0, int *x1)
{
    const Window *dlg = dialog_of(w);
    UiFont f = ui_font(dlg, 0);
    int ax0, ay0, ax1, ay1, inset = ((dlg && (dlg->style & 4u)) || (w->style & 0x800000u) || (w->exstyle & 0x200u)) ? 2 : 1, h = f.height + 1, n, t = w->top;

    if (w->lb_icons && h < 16)
        h = 16;
    wm_abs_rect(w, &ax0, &ay0, &ax1, &ay1);
    n = (ay1 - ay0 - 2 * inset) / h;
    if (n < 1)
        n = 1;
    if (t < 0 || t > w->nitems - n)
        t = w->nitems > n ? w->nitems - n : 0;
    *y_first = ay0 + inset;
    *rowh = h;
    *rows = w->nitems - t < n ? w->nitems - t : n;
    *top = t;
    *x0 = ax0 + inset;
    *x1 = ax1 - inset - (w->nitems > n && (w->style & 0x200000u) ? 16 : 0);
}

static void draw_combobox(Canvas *c, const Window *w, const Window *dlg, int x0, int y0, int x1)
{
    UiFont f = ui_font(dlg, 0);
    int y1 = y0 + 21;

    int disabled = !w->enabled;

    fill(c, x0, y0, x1, y1, WINDOW);
    sunken(c, x0, y0, x1, y1);
    button_face(c, x1 - 18, y0 + 2, x1 - 2, y1 - 2, w->dropped, 0);
    arrow(c, x1 - 10 + (w->dropped ? 1 : 0), (y0 + y1) / 2 + (w->dropped ? 1 : 0), 1, disabled ? SHADOW : BLACK);
    if (w->sel >= 0 && w->sel < w->nitems)
        label_line(c, &f, x0 + 4, y0 + (21 - f.height) / 2, w->items[w->sel].text, strlen(w->items[w->sel].text), -1, disabled ? SHADOW : BLACK, disabled);
}

/* The list of a drop-down combo box: just under the closed box (above it when the screen has no room below), as many rows as fit the height the game asked
 * for and as there are items, a scroll bar on the right when there are more. */
void ui_combo_geometry(const Window *w, int *x0, int *y0, int *x1, int *y1, int *rowh, int *rows)
{
    UiFont f = ui_font(dialog_of(w), 0);
    int ax0, ay0, ax1, ay1, maxrows, n;

    wm_abs_rect(w, &ax0, &ay0, &ax1, &ay1);
    *rowh = f.height + 1;
    maxrows = (w->drop_h - COMBO_CLOSED_H - 2) / *rowh;
    if (maxrows < 1)
        maxrows = 1;
    n = w->nitems < maxrows ? w->nitems : maxrows;
    *rows = n < 1 ? 1 : n;
    *x0 = ax0;
    *x1 = ax1;
    *y0 = ay1 - 1;
    *y1 = *y0 + *rows * *rowh + 2;
    if (*y1 > screen_h && ay0 - (*y1 - *y0) + 1 >= 0) {
        *y1 = ay0 + 1;
        *y0 = *y1 - (*rows * *rowh + 2);
    }
}

void ui_combo_list(uint8_t *rgb, int sw, int sh, const Window *w)
{
    Canvas c = {rgb, sw, sh};
    UiFont f = ui_font(dialog_of(w), 0);
    int x0, y0, x1, y1, rowh, rows, i, right;

    ui_combo_geometry(w, &x0, &y0, &x1, &y1, &rowh, &rows);
    fill(&c, x0, y0, x1, y1, WINDOW);
    bevel(&c, x0, y0, x1, y1, BLACK, BLACK);
    right = x1 - 1;
    if (w->nitems > rows) {
        vscrollbar(&c, x1 - 1 - 16, y0 + 1, x1 - 1, y1 - 1, w->nitems, rows, w->top);
        right = x1 - 1 - 16;
    }
    for (i = 0; i < rows && w->top + i < w->nitems; i++) {
        int ry = y0 + 1 + i * rowh, k = w->top + i;

        if (k == w->hot)
            fill(&c, x0 + 1, ry, right, ry + rowh, NAVY);
        label_line(&c, &f, x0 + 3, ry, w->items[k].text, strlen(w->items[k].text), -1, k == w->hot ? HILIGHT : BLACK, 0);
    }
}

/* A scroll bar control: the two arrow buttons, the track and the thumb at the position (SetScrollRange / SetScrollPos on the control: bar 2). */
static void draw_scrollbar(Canvas *c, const Window *w, int x0, int y0, int x1, int y1)
{
    const int *sc = w->scroll[2];
    int vertical = (w->style & 1u) != 0, len = vertical ? y1 - y0 : x1 - x0, bw = vertical ? x1 - x0 : y1 - y0, track, thumb, pos, span = sc[1] - sc[0];

    fill(c, x0, y0, x1, y1, LIGHT);
    if (vertical) {
        button_face(c, x0, y0, x1, y0 + bw, 0, 0);
        arrow(c, (x0 + x1) / 2, y0 + bw / 2, 0, BLACK);
        button_face(c, x0, y1 - bw, x1, y1, 0, 0);
        arrow(c, (x0 + x1) / 2, y1 - bw / 2 - 1, 1, BLACK);
    } else {
        button_face(c, x0, y0, x0 + bw, y1, 0, 0);
        arrow(c, x0 + bw / 2, (y0 + y1) / 2, 2, BLACK);
        button_face(c, x1 - bw, y0, x1, y1, 0, 0);
        arrow(c, x1 - bw / 2 - 1, (y0 + y1) / 2, 3, BLACK);
    }
    track = len - 2 * bw;
    thumb = bw;                                                    /* a square thumb: the range is not a number of lines this control knows */
    if (track < thumb + 1 || span <= 0)
        return;
    pos = (track - thumb) * (sc[2] - sc[0]) / span;
    if (pos < 0)
        pos = 0;
    if (vertical)
        button_face(c, x0, y0 + bw + pos, x1, y0 + bw + pos + thumb, 0, 0);
    else
        button_face(c, x0 + bw + pos, y0, x0 + bw + pos + thumb, y1, 0, 0);
}

/* A standard control. `pressed` is the push button the mouse is holding down. */
static void draw_control(Canvas *c, const Window *w, const Window *dlg, uint32_t pressed)
{
    int x0, y0, x1, y1;
    const char *face = NULL;
    int bold = 0, px = 0;

    wm_abs_rect(w, &x0, &y0, &x1, &y1);
    if (!dlg && w->hfont && gdi_font_object(w->hfont, &face, &bold, &px)) {
        ctl_face = face;
        ctl_px = px;
        ctl_bold = bold;
    }
    if (!strcasecmp(w->cname, "SCROLLBAR"))
        draw_scrollbar(c, w, x0, y0, x1, y1);
    else if (!strcasecmp(w->cname, "BUTTON"))
        draw_button(c, w, dlg, x0, y0, x1, y1, pressed == w->hwnd);
    else if (!strcasecmp(w->cname, "STATIC"))
        draw_static(c, w, dlg, x0, y0, x1, y1);
    else if (!strcasecmp(w->cname, "EDIT"))
        draw_edit(c, w, dlg, x0, y0, x1, y1);
    else if (!strcasecmp(w->cname, "LISTBOX"))
        draw_listbox(c, w, dlg, x0, y0, x1, y1);
    else if (!strcasecmp(w->cname, "COMBOBOX"))
        draw_combobox(c, w, dlg, x0, y0, x1);
    else if (!strcasecmp(w->cname, "msctls_updown32")) {                            /* spin buttons: two small arrow buttons, one above the other */
        int mid = (y0 + y1) / 2;

        button_face(c, x0, y0, x1, mid, 0, 0);
        arrow(c, (x0 + x1) / 2, (y0 + mid) / 2, 0, BLACK);
        button_face(c, x0, mid, x1, y1, 0, 0);
        arrow(c, (x0 + x1) / 2, (mid + y1) / 2, 1, BLACK);
    }
    ctl_face = NULL;
}

static int is_standard(const Window *w)
{
    static const char *const names[] = {"BUTTON", "STATIC", "EDIT", "LISTBOX", "COMBOBOX", "SCROLLBAR", "msctls_updown32"};
    size_t i;

    if ((w->proc && !w->subclassed) || w->ownerdraw)
        return 0;
    for (i = 0; i < sizeof(names) / sizeof(names[0]); i++)
        if (!strcasecmp(w->cname, names[i]))
            return 1;
    return 0;
}

/* Draw one open dialog on the composed screen: its frame, the client area (the face colour, then what the dialog's own procedure drew), then the controls from the
 * back of the stacking order to the front: the standard ones here, the others (owner-drawn buttons, the game's own classes) through `paint_child`. */
void ui_dialog(uint8_t *rgb, int sw, int sh, Window *d, uint32_t pressed, void (*paint_child)(void *ctx, Window *child, int ox, int oy), void *ctx)
{
    Canvas c = {rgb, sw, sh};
    int x0, y0, x1, y1, cx0, cy0, n = wm_window_count(), i, j, k, nk = 0;
    Window **kids;

    wm_abs_rect(d, &x0, &y0, &x1, &y1);
    wm_client_origin(d, &cx0, &cy0);
    fill(&c, x0, y0, x1, y1, FACE);
    draw_frame(&c, d, x0, y0, x1, y1);
    if (d->surface) {                 /* what the dialog's own procedure drew */
        Surface *sf = d->surface;
        uint8_t *row = malloc((size_t)sf->w * 3 + 3);
        int yy, xx;

        for (yy = 0; row && yy < sf->h; yy++) {
            surface_rgb(sf, 0, yy, sf->w, yy + 1, row);
            for (xx = 0; xx < sf->w; xx++)
                if (sf->direct[(size_t)yy * (size_t)sf->w + (size_t)xx] || sf->idx[(size_t)yy * (size_t)sf->w + (size_t)xx])
                    put(&c, cx0 + xx, cy0 + yy, row + 3 * xx);
        }
        free(row);
    }
    kids = malloc((size_t)(n + 1) * sizeof(*kids));
    for (i = 0; i < n; i++) {
        Window *w = wm_window_at_index(i);

        if (w && w->parent == d->hwnd && w->hwnd != d->hwnd && w->visible && w->w > 0 && w->h > 0 && !w->is_dialog)   /* a dialog owned by this one is drawn on its own (it is on the dialog stack): as a child it would be drawn twice, offset */
            kids[nk++] = w;
    }
    for (j = 1; j < nk; j++) {                     /* by stacking order, bottom first */
        Window *t = kids[j];

        for (k = j - 1; k >= 0 && kids[k]->z > t->z; k--)
            kids[k + 1] = kids[k];
        kids[k + 1] = t;
    }
    for (j = 0; j < nk; j++) {
        if (is_standard(kids[j]))
            draw_control(&c, kids[j], d, pressed);
        else if (paint_child)
            paint_child(ctx, kids[j], cx0, cy0);
    }
    free(kids);
}

/* The frame and background of a window as Windows draws a pushed-in or raised box: used by the compositor's stand-ins elsewhere. */
void ui_button_face(uint8_t *rgb, int sw, int sh, int x0, int y0, int x1, int y1, int pressed, int is_default)
{
    Canvas c = {rgb, sw, sh};

    button_face(&c, x0, y0, x1, y1, pressed, is_default);
}

const Window *ui_dialog_of(const Window *w) { return dialog_of(w); }

/* Whether a window is a modal dialog or inside one: those are drawn from the dialog stack (ui_dialog). A modeless dialog (CreateDialog: the Magic Shell's pages) is an ordinary child window. */
int ui_in_modal_dialog(const Window *w)
{
    for (; w; w = w->parent ? wm_window(w->parent) : NULL)
        if (w->is_dialog)
            return 1;
    return 0;
}

/* The standard controls of an ordinary window (not of a dialog): Windows draws them, the game never does (the Magic Shell's pages are made of them). */
int ui_standard_control(const Window *w) { return w && w->cname && is_standard(w); }

void ui_draw_control(uint8_t *rgb, int sw, int sh, const Window *w, uint32_t pressed)
{
    Canvas c = {rgb, sw, sh};

    draw_control(&c, w, dialog_of(w), pressed);
}

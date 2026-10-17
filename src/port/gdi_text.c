/* gdi_text.c - fonts and text, DrawText, the rectangle fills of user32, and the window background. Port of winemu/gdi.py (text) and the
 * painting calls of winemu/user32.py. */
#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "gdi_int.h"

#define P(a) ((char *)(G + (a)))

/* ---- the game's fonts and the stand-ins ----------------------------------------------------------------------------------------------- */
typedef struct GameFont { char family[64]; char style[32]; TTFont *f; } GameFont;
static GameFont *game_fonts;
static int ngame_fonts;
static TTFont *fallback_regular, *fallback_bold;
static int fallback_tried;

/* Remember the game's own TrueType file under its family name: CreateFont asks for that family and gets it (not a stand-in). */
int fonts_add_file(const char *host_path)
{
    TTFont *f = ttf_load(host_path);
    int i;

    if (!f)
        return 0;
    game_fonts = realloc(game_fonts, (size_t)(ngame_fonts + 1) * sizeof(*game_fonts));
    snprintf(game_fonts[ngame_fonts].family, sizeof(game_fonts[0].family), "%s", ttf_family(f));
    snprintf(game_fonts[ngame_fonts].style, sizeof(game_fonts[0].style), "%s", ttf_style(f));
    for (i = 0; game_fonts[ngame_fonts].family[i]; i++)
        game_fonts[ngame_fonts].family[i] = (char)tolower((unsigned char)game_fonts[ngame_fonts].family[i]);
    for (i = 0; game_fonts[ngame_fonts].style[i]; i++)
        game_fonts[ngame_fonts].style[i] = (char)tolower((unsigned char)game_fonts[ngame_fonts].style[i]);
    game_fonts[ngame_fonts].f = f;
    ngame_fonts++;
    return 1;
}

static void key_of(const char *face, char *out, size_t cap)
{
    size_t n = 0;

    while (*face == ' ' || *face == '"')
        face++;
    for (; *face && n + 1 < cap; face++)
        out[n++] = (char)tolower((unsigned char)*face);
    while (n && (out[n - 1] == ' ' || out[n - 1] == '"'))
        n--;
    out[n] = 0;
}

static TTFont *game_font_for(const char *face, int weight, int italic)
{
    char key[64];
    const char *want = weight >= 600 && italic ? "bold italic" : weight >= 600 ? "bold" : italic ? "italic" : "regular";
    static const char *const order[] = {NULL, "regular", "bold", "italic"};
    int i, c, any = -1;

    key_of(face, key, sizeof(key));
    for (c = 0; c < 4; c++) {
        const char *s = c == 0 ? want : order[c];

        for (i = 0; i < ngame_fonts; i++)
            if (!strcmp(game_fonts[i].family, key)) {
                if (any < 0)
                    any = i;
                if (!strcmp(game_fonts[i].style, s))
                    return game_fonts[i].f;
            }
    }
    return any >= 0 ? game_fonts[any].f : NULL;
}

static void load_fallbacks(void)
{
    static const char *const regular[] = {"/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
                                          "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf",
                                          "C:/Windows/Fonts/arial.ttf", NULL};
    static const char *const bold[] = {"/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
                                       "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
                                       "C:/Windows/Fonts/arialbd.ttf", NULL};
    int i;

    fallback_tried = 1;
    for (i = 0; regular[i] && !fallback_regular; i++)
        fallback_regular = ttf_load(regular[i]);
    for (i = 0; bold[i] && !fallback_bold; i++)
        fallback_bold = ttf_load(bold[i]);
    if (!fallback_regular && ngame_fonts)
        fallback_regular = game_fonts[0].f;                  /* nothing on this machine: the game's own first font */
    if (!fallback_bold)
        fallback_bold = fallback_regular;
}

typedef struct Resolved { TTFont *f; double em; int own; } Resolved;

/* The ppem Windows gives one of the game's TrueType fonts asked for a cell `cell` pixels tall (a positive lfHeight, in device pixels): the largest whose hinted cell (the ascent and the
 * descent each rounded, ttf_cell) is not taller. MPZurich Cn BT, which the card text is set in: a cell of 10 is 8 ppem (cell 8 + 2), 11 is 9, 12 is 10. */
int font_ppem_for_cell(const TTFont *f, int cell)
{
    int p, best = 1;

    for (p = 1; p <= 400; p++) {
        int a, d;

        ttf_cell(f, p, &a, &d);
        if (a + d > cell)
            break;
        best = p;
    }
    return best;
}

/* The font a LOGFONT-like object means at a vertical scale: the game's own file when it has the family, else a stand-in at 3/4 of the size. The game's TrueType fonts are hinted at whole
 * pixel sizes, as Windows draws them: the height of the font in device pixels (lfHeight times the scale, to the nearest pixel) is the em itself for a negative height and the cell height
 * for a positive one (font_ppem_for_cell). The original's card text (lfHeight 14 at 0.7467) is 8 ppem; the port's 8.64 was the height scaled to fill the cell as a fraction. */
static Resolved resolve(const Font *font, double scale)
{
    Resolved r = {0, 0, 0};
    const char *face = font ? font->face : "Arial";
    int size = font ? font->size : 13, weight = font ? font->weight : 400, italic = font ? font->italic : 0, height = font ? font->height : size;
    double sz = size * scale;
    TTFont *own = game_font_for(face, weight, italic);

    if (own) {
        int dev = (int)floor(sz + 0.5);

        if (dev < 1)
            dev = 1;
        r.f = own;
        r.own = 1;
        r.em = height < 0 ? dev : font_ppem_for_cell(own, dev);
        if (r.em < 2)
            r.em = 2;
        return r;
    }
    if (!fallback_tried)
        load_fallbacks();
    r.f = weight >= 600 ? fallback_bold : fallback_regular;
    if (r.f && height >= 0) {                       /* a positive height is the cell: ascent plus descent, so the em is smaller (Windows takes the largest whole ppem that fits) */
        int asc, desc;

        ttf_metrics(r.f, 100, &asc, &desc);
        r.em = (int)(sz * 100.0 / (asc + desc ? asc + desc : 120));
    } else
        r.em = (int)sz;                             /* a negative one is the em itself */
    if (r.em < 6)
        r.em = 6;
    return r;
}

/* The advance of a string in device pixels (whole-pixel advances; with `kern` the font's kerning pairs too, as the user interface's own text had them). Windows' GDI does not kern what a
 * program draws with TextOut or measures with GetTextExtentPoint: the sum of the glyphs' hinted advances is the extent. */
static double string_length(const Resolved *r, const char *s, size_t n, int kern)
{
    double w = 0;
    size_t i;

    for (i = 0; i < n; i++) {
        w += ttf_advance(r->f, r->em, (unsigned char)s[i]);
        if (kern && i + 1 < n)
            w += ttf_kern(r->f, r->em, (unsigned char)s[i], (unsigned char)s[i + 1]);
    }
    return w;
}

/* The logical height of the cell of a resolved font on a DC with vertical scale `sy` (tmHeight, and the cy of an extent): the hinted cell in device pixels divided by the scale,
 * truncated (the original's MPZurich Cn BT at 8 ppem on a 0.7467 mapping: a cell of 10 is 13). */
static int cell_height_logical(const Resolved *r, double sy)
{
    int a, d;

    ttf_cell(r->f, r->em, &a, &d);
    return (int)((a + d) / sy);
}

/* The width and height of `s` in the DC's logical units. The font is realized at its height scaled by the mapping's vertical scale, and its
 * width follows from that: the logical width is the realized device width divided by the horizontal scale, to the nearest unit (the original's extents on a 0.7467 mapping: a space
 * of 2 pixels is 3, "Gain" of 15 is 20); the height is the logical tmHeight. */
int text_width(const DC *dc, const char *s, size_t n, int *height)
{
    Resolved r = resolve(dc->font, dc->sy);

    if (height)
        *height = r.own ? cell_height_logical(&r, dc->sy) : dc->font ? dc->font->size : 13;
    if (!n || !r.f)
        return 0;
    return (int)floor(string_length(&r, s, n, 0) / dc->sx + 0.5);
}

/* Windows 98 draws text without smoothing, through the font's own hinting: at the 8 to 10 pixel sizes a scaled-down card's rule text comes out as solid black
 * one-pixel stems (the original's screenshot of an ante card's text at 640x480). The rasterizer here has no hinting, and the exact-area coverage of a stem 0.8 pixels
 * wide is a grey of at most 80%, so small text looked pale and smeared. The coverage is therefore doubled (saturating) up to 10 pixels, tapering to unchanged at 14.
 * docs/notes/castle-text.md. */
uint8_t text_coverage(uint8_t a, double em)
{
    double gain = em <= 10 ? 2.0 : em >= 14 ? 1.0 : 2.0 - (em - 10) / 4;
    int v = (int)(a * gain + 0.5);

    return (uint8_t)(v > 255 ? 255 : v);
}

/* Draw `s` with its reference point at logical (x, y); `align`: honour the DC's text alignment (TextOut does, DrawText does not). */
void draw_text_at(DC *dc, int x, int y, const char *s, size_t n, int align)
{
    Resolved r;
    int tw, th, asc, desc, x0, y0, bx, by, W, H, rw, rh, rx, ry, i;
    uint8_t fg[3], bg[3], *px, *mask = NULL;
    double pen;

    if (!n)
        return;
    r = resolve(dc->font, dc->sy);                      /* the font height is in logical units: scaled like everything else */
    if (!r.f)
        return;
    tw = text_width(dc, s, n, &th);
    tw = (int)(tw * dc->sx);                              /* back to device pixels */
    th = (int)(th * dc->sy);
    colorref_rgb(dc, dc->textcolor, fg);
    x0 = lx(dc, x) + dc->org[0];
    y0 = ly(dc, y) + dc->org[1];
    if (align && (dc->textalign & 6) == 6)
        x0 -= tw / 2;
    else if (align && (dc->textalign & 6) == 2)
        x0 -= tw;
    if (align && (dc->textalign & 24) == 8)
        y0 -= th;
    bx = x0;
    by = y0;
    W = tw + 1;
    H = th + 1;
    px = get_region(dc, bx, by, bx + W, by + H, &rw, &rh, &rx, &ry);
    if (!px)
        return;
    if (dc->bkmode == 2) {                                 /* opaque: the background colour behind the text */
        int yy, xx;

        colorref_rgb(dc, dc->bkcolor, bg);
        for (yy = 0; yy < rh; yy++)
            for (xx = 0; xx < rw; xx++)
                memcpy(px + 3 * ((size_t)yy * (size_t)rw + (size_t)xx), bg, 3);
    }
    {   /* over a see-through window (see Window.see_through) only the glyphs' pixels are drawn: the rest of the rectangle is what is behind the window */
        Window *wn = dc->memory ? NULL : wm_window(dc->hwnd);

        if (wn && wn->see_through && dc->bkmode != 2)
            mask = calloc((size_t)rw * (size_t)rh, 1);
    }
    ttf_metrics(r.f, r.em, &asc, &desc);
    pen = 0;
    for (i = 0; i < (int)n; i++) {
        int gw, gh, gl, gt, gx, gy;
        uint8_t *g = ttf_glyph(r.f, r.em, (unsigned char)s[i], &gw, &gh, &gl, &gt);

        if (g) {
            for (gy = 0; gy < gh; gy++)
                for (gx = 0; gx < gw; gx++) {
                    int dx = (int)pen + gl + gx - (rx - bx), dy = asc - gt + gy - (ry - by);
                    uint8_t a = g[gy * gw + gx], *o;
                    int c;

                    if (!a || dx < 0 || dy < 0 || dx >= rw || dy >= rh)
                        continue;
                    a = text_coverage(a, r.em);
                    o = px + 3 * ((size_t)dy * (size_t)rw + (size_t)dx);
                    if (mask)
                        mask[(size_t)dy * (size_t)rw + (size_t)dx] = 1;
                    for (c = 0; c < 3; c++)
                        o[c] = (uint8_t)(o[c] + ((int)fg[c] - (int)o[c]) * a / 255);
                }
            free(g);
        }
        pen += ttf_advance(r.f, r.em, (unsigned char)s[i]);
    }
    put_region_masked(dc, rx, ry, px, rw, rh, mask);
    free(mask);
    free(px);
}

static uint32_t TextOutA(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);

    if (dc)
        draw_text_at(dc, (int32_t)a[1], (int32_t)a[2], P(a[3]), a[4], 1);
    return 1;
}

static uint32_t GetTextExtentPointA(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);
    int h = 0, w = 0;

    if (dc)
        w = text_width(dc, P(a[1]), a[2], &h);
    WR32(a[3], (uint32_t)w);
    WR32(a[3] + 4, (uint32_t)h);
    return 1;
}

static uint32_t GetTextMetricsA(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);
    double sx = dc && dc->sx > 0 ? dc->sx : 1.0, sy = dc && dc->sy > 0 ? dc->sy : 1.0;
    int h = dc && dc->font ? dc->font->size : 13, avg;
    Resolved r = resolve(dc ? dc->font : NULL, dc ? sy : 1.0);
    int32_t vals[11];
    int i;

    if (r.own) {
        /* the game's own TrueType font: the hinted cell at the whole ppem realized for this DC, in device pixels, then in logical units by truncation (the original's MPZurich Cn BT at 8 ppem
         * on a 0.7467 mapping reported 13, 10, 2, 2, 0, 4: a cell of 10 = 8 + 2, an internal leading of 2, an average width of 3 pixels). docs/notes/card-text-metrics.md */
        int asc, desc, c, mx = 0;

        ttf_cell(r.f, r.em, &asc, &desc);
        for (c = 32; c < 256; c++) {
            int w = (int)ttf_advance(r.f, r.em, (unsigned char)c);

            if (w > mx)
                mx = w;
        }
        avg = ttf_avg_width(r.f, r.em);
        if (avg < 1)
            avg = (int)ttf_advance(r.f, r.em, 'x');
        vals[0] = (int)((asc + desc) / sy); vals[1] = (int)(asc / sy); vals[2] = (int)(desc / sy);
        vals[3] = asc + desc > (int)r.em ? (int)((asc + desc - (int)r.em) / sy) : 0; vals[4] = 0;
        vals[5] = (int)(avg / sx); vals[6] = (int)(mx / sx);
    } else {
        avg = r.f ? (int)ttf_advance(r.f, r.em, 'x') : h / 2;
        vals[0] = h; vals[1] = h * 4 / 5; vals[2] = h - h * 4 / 5; vals[3] = 0; vals[4] = 0; vals[5] = avg; vals[6] = avg * 2;
    }
    vals[7] = 400; vals[8] = 0;
    vals[9] = 96; vals[10] = 96;
    for (i = 0; i < 11; i++)
        WR32(a[1] + 4 * (uint32_t)i, (uint32_t)vals[i]);
    G[a[1] + 44] = 32; G[a[1] + 45] = 255; G[a[1] + 46] = 63; G[a[1] + 47] = 32; G[a[1] + 48] = 0; G[a[1] + 49] = 0; G[a[1] + 50] = 0; G[a[1] + 51] = 0x22;
    G[a[1] + 52] = 0; G[a[1] + 53] = 0; G[a[1] + 54] = 0; G[a[1] + 55] = 0;
    return 1;
}

static uint32_t GetCharWidthA(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);
    uint32_t c, i = 0;

    for (c = a[1]; c <= a[2]; c++, i++) {
        char ch = (char)c;

        WR32(a[3] + 4 * i, dc ? (uint32_t)text_width(dc, &ch, 1, NULL) : 0);
    }
    return 1;
}

static uint32_t GetCharABCWidthsA(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);
    uint32_t c, i = 0;

    for (c = a[1]; c <= a[2]; c++, i++) {
        char ch = (char)c;

        WR32(a[3] + 12 * i, 0);
        WR32(a[3] + 12 * i + 4, dc ? (uint32_t)text_width(dc, &ch, 1, NULL) : 0);
        WR32(a[3] + 12 * i + 8, 0);
    }
    return 1;
}

/* ---- the compositor's own labels -------------------------------------------------------------------------------------------------------- */
static Resolved plain(int size)
{
    Font f = {"Arial", size, 400, 0, size};

    return resolve(&f, 1.0);
}

int text_extent(const char *s, int size)
{
    Resolved r = plain(size);

    return r.f ? (int)string_length(&r, s, strlen(s), 1) : (int)strlen(s) * size / 2;
}

void text_on_rgb(uint8_t *rgb, int w, int h, int x, int y, const char *s, int size, const uint8_t color[3])
{
    Resolved r = plain(size);
    int asc, desc, i;
    double pen = 0;

    if (!r.f)
        return;
    ttf_metrics(r.f, r.em, &asc, &desc);
    for (i = 0; s[i]; i++) {
        int gw, gh, gl, gt, gx, gy;
        uint8_t *g = ttf_glyph(r.f, r.em, (unsigned char)s[i], &gw, &gh, &gl, &gt);

        if (g) {
            for (gy = 0; gy < gh; gy++)
                for (gx = 0; gx < gw; gx++) {
                    int dx = x + (int)pen + gl + gx, dy = y + asc - gt + gy;
                    uint8_t a = g[gy * gw + gx], *o;
                    int c;

                    if (!a || dx < 0 || dy < 0 || dx >= w || dy >= h)
                        continue;
                    o = rgb + 3 * ((size_t)dy * (size_t)w + (size_t)dx);
                    for (c = 0; c < 3; c++)
                        o[c] = (uint8_t)(o[c] + ((int)color[c] - (int)o[c]) * a / 255);
                }
            free(g);
        }
        pen += ttf_advance(r.f, r.em, (unsigned char)s[i]);
        if (s[i + 1])
            pen += ttf_kern(r.f, r.em, (unsigned char)s[i], (unsigned char)s[i + 1]);
    }
}

/* ---- the user interface's own text: dialogs and their controls, at a face and a point size ------------------------------------------------------ */
/* The pixel height Windows gives a dialog font of `pt` points at 96 dpi: CreateFont(-MulDiv(pt, 96, 72)), rounded to a whole pixel (10 points is 13, not 13.33). */
int ui_pixel_size(int pt) { return (pt * 96 + 36) / 72; }

/* The game's own file for `face` at `pt` points when it has the family, else the host's sans serif standing in for MS Sans Serif. MS Sans Serif is a bitmap font, 13 pixels
 * high at 8 points, whose text runs as wide as Arial at 10 pixels (the Run dialog of Windows 98: its 56-character sentence is 272 pixels, Arial at 10 is 270, at 11 281). */
static Resolved ui_resolve(const char *face, int pt, int bold)
{
    Resolved r = {0, 0, 0};
    int px = ui_pixel_size(pt);
    TTFont *own = face && face[0] ? game_font_for(face, bold ? 700 : 400, 0) : NULL;

    if (own) {
        r.f = own;
        r.em = px;
        return r;
    }
    if (!fallback_tried)
        load_fallbacks();
    r.f = bold ? fallback_bold : fallback_regular;
    r.em = (int)(px * 0.9 + 0.5);
    return r;
}

/* Metrics at a face and size: cell height (tmHeight), ascent (for placing the text), and the width the dialog base unit comes from. The system font
 * MS Sans Serif is the 13 x 6 of Windows 98 at 8 points (16 x 7 at 10). */
void ui_font_metrics(const char *face, int pt, int bold, int *height, int *ascent, int *avg)
{
    Resolved r = ui_resolve(face, pt, bold);
    TTFont *own = face && face[0] ? game_font_for(face, bold ? 700 : 400, 0) : NULL;
    int asc = 10, h, a, px = ui_pixel_size(pt);

    if (r.f) {
        if (own) {
            ttf_text_metrics(own, r.em, &h, &a);
            asc = ttf_ascent(own, r.em);
        } else {
            h = (int)(px * 1.2 + 0.5);
            a = (int)(px * 0.55 + 0.5);
            asc = px;                                    /* MS Sans Serif's ascent: 11 of its 13 pixels at 8 points */
        }
    } else {
        h = 13;
        a = 6;
    }
    if (avg)
        *avg = a;
    if (height)
        *height = h;
    if (ascent)
        *ascent = asc;
}

/* A template's position or size in pixels: the unit conversion Windows 98 does, MulDiv rounding to the nearest pixel (the real setup dialog's combo boxes at y = 82 and
 * 139 units sit at 154 and 261 pixels from the top of the client area, not 153 and 260), the horizontal one with a quarter-unit base and the vertical one with an eighth. */
int ui_dlu_x(int v, int avg) { return (v * avg + (v < 0 ? -2 : 2)) / 4; }
int ui_dlu_y(int v, int height) { return (v * height + (v < 0 ? -4 : 4)) / 8; }

int ui_text_width(const char *face, int pt, int bold, const char *s, size_t n)
{
    Resolved r = ui_resolve(face, pt, bold);

    return r.f ? (int)string_length(&r, s, n, 1) : (int)n * pt / 2;
}

/* Draw `s` with its top-left corner at (x, y) on an RGB screen buffer. */
void ui_text_draw(uint8_t *rgb, int w, int h, int x, int y, const char *s, size_t n, const char *face, int pt, int bold, const uint8_t color[3])
{
    Resolved r = ui_resolve(face, pt, bold);
    int asc, i;
    double pen = 0;

    if (!r.f)
        return;
    ui_font_metrics(face, pt, bold, NULL, &asc, NULL);
    for (i = 0; (size_t)i < n; i++) {
        int gw, gh, gl, gt, gx, gy;
        uint8_t *g = ttf_glyph(r.f, r.em, (unsigned char)s[i], &gw, &gh, &gl, &gt);

        if (g) {
            for (gy = 0; gy < gh; gy++)
                for (gx = 0; gx < gw; gx++) {
                    int dx = x + (int)pen + gl + gx, dy = y + asc - gt + gy;
                    uint8_t a = g[gy * gw + gx], *o;
                    int c;

                    if (!a || dx < 0 || dy < 0 || dx >= w || dy >= h)
                        continue;
                    o = rgb + 3 * ((size_t)dy * (size_t)w + (size_t)dx);
                    for (c = 0; c < 3; c++)
                        o[c] = (uint8_t)(o[c] + ((int)color[c] - (int)o[c]) * a / 255);
                }
            free(g);
        }
        pen += ttf_advance(r.f, r.em, (unsigned char)s[i]);
        if ((size_t)i + 1 < n)
            pen += ttf_kern(r.f, r.em, (unsigned char)s[i], (unsigned char)s[i + 1]);
    }
}

/* ---- user32's painting calls ---------------------------------------------------------------------------------------------------------- */
static void system_color(uint32_t index, uint8_t out[3])
{
    static const uint8_t colors[16][3] = {{192, 192, 192}, {0, 0, 128}, {0, 128, 128}, {192, 192, 192}, {255, 255, 255}, {0, 0, 0}, {0, 0, 0},
                                          {0, 0, 0}, {255, 255, 255}, {192, 192, 192}, {192, 192, 192}, {128, 128, 128}, {0, 0, 128},
                                          {255, 255, 255}, {192, 192, 192}, {192, 192, 192}};

    if (index >= 1 && index <= 15) {
        memcpy(out, colors[index], 3);
        return;
    }
    out[0] = out[1] = out[2] = 255;
}

/* RGB of a w x h rectangle filled with a brush: a solid colour, or a bitmap tiled from `origin`. Returns NULL for a null brush. */
static uint8_t *brush_pixels(const Brush *b, int w, int h, int ox, int oy)
{
    uint8_t *out;
    size_t i;

    if (b->pattern) {
        Bitmap *bmp = obj_get(b->pattern, O_BITMAP);

        if (bmp && bmp->w && bmp->h) {
            DC tmp;
            int tw, th, rx, ry, x, y;
            uint8_t *tile;

            memset(&tmp, 0, sizeof(tmp));
            tmp.memory = 1;
            tmp.bitmap = bmp;
            tile = get_region(&tmp, 0, 0, bmp->w, bmp->h, &tw, &th, &rx, &ry);
            if (tile) {
                out = malloc((size_t)w * (size_t)h * 3);
                for (y = 0; y < h; y++)
                    for (x = 0; x < w; x++)
                        memcpy(out + 3 * ((size_t)y * (size_t)w + (size_t)x), tile + 3 * ((size_t)((y + oy) % th) * (size_t)tw + (size_t)((x + ox) % tw)), 3);
                free(tile);
                return out;
            }
        }
    }
    out = malloc((size_t)w * (size_t)h * 3);
    for (i = 0; i < (size_t)w * (size_t)h; i++) {
        if (b->solid)
            memcpy(out + 3 * i, b->rgb, 3);
        else
            memset(out + 3 * i, 0, 3);
    }
    return out;
}

/* Fill a window's client area with its class background brush (a solid, system colour or pattern). */
int gdi_erase_background(Window *win)
{
    uint32_t bg = wm_class_background(win);
    Brush *br;
    Brush tmp;
    int cw, ch;
    uint8_t *px;
    uint32_t h;

    if (!win->cls || !bg)
        return 0;
    br = obj_get(bg, O_BRUSH);
    if (!br) {
        if (bg > 32)
            return 0;                                       /* COLOR_xxx + 1 */
        memset(&tmp, 0, sizeof(tmp));
        tmp.solid = 1;
        system_color(bg - 1, tmp.rgb);
        br = &tmp;
    }
    wm_client_size(win, &cw, &ch);
    if (cw <= 0 || ch <= 0)
        return 0;
    h = gdi_window_dc(win->hwnd);
    px = brush_pixels(br, cw, ch, 0, 0);
    put_region(dc_of(h), 0, 0, px, cw, ch);
    free(px);
    return 1;
}

static uint32_t FillRect(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);
    int l = (int32_t)RD32(a[1]), t = (int32_t)RD32(a[1] + 4), r = (int32_t)RD32(a[1] + 8), b = (int32_t)RD32(a[1] + 12);
    Brush *br = obj_get(a[2], O_BRUSH);
    uint8_t color[3] = {192, 192, 192};
    int have = 0;

    if (a[2] < 32 && !br)
        have = 1;                                              /* COLOR_xxx + 1 system brush indices */
    else if (br && br->solid) {
        brush_color(dc, br, color);
        have = 1;
    }
    if (dc && have)
        fill_rect_logical(dc, l, t, r, b, color);
    return 1;
}

static uint32_t FrameRect(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);
    int l = (int32_t)RD32(a[1]), t = (int32_t)RD32(a[1] + 4), r = (int32_t)RD32(a[1] + 8), b = (int32_t)RD32(a[1] + 12);
    Brush *br = obj_get(a[2], O_BRUSH);
    uint8_t color[3] = {0, 0, 0};

    if (!dc)
        return 1;
    if (br && br->solid)
        brush_color(dc, br, color);
    fill_rect_logical(dc, l, t, r, t + 1, color);
    fill_rect_logical(dc, l, b - 1, r, b, color);
    fill_rect_logical(dc, l, t, l + 1, b, color);
    fill_rect_logical(dc, r - 1, t, r, b, color);
    return 1;
}

static uint32_t one(const uint32_t *a) { (void)a; return 1; }

#define DT_CENTER 1
#define DT_RIGHT 2
#define DT_VCENTER 4
#define DT_BOTTOM 8
#define DT_WORDBREAK 0x10
#define DT_SINGLELINE 0x20
#define DT_CALCRECT 0x400
#define DT_NOPREFIX 0x800

typedef struct Line { char *s; size_t n; } Line;

/* Lines of `text` for DrawText (widths in logical units): split at newlines unless single-line, and, with DT_WORDBREAK, at spaces so that no line is
 * wider than `width` (a word wider than the line gets its own line). */
static int wrap_lines(const DC *dc, char *text, int width, int wordbreak, int single, Line *lines, int max)
{
    int n = 0;
    char *para = text;

    while (para && n < max) {
        char *nl = single ? NULL : strchr(para, '\n'), *end = nl ? nl : para + strlen(para);
        size_t len = (size_t)(end - para);

        if (len && para[len - 1] == '\r')
            len--;
        if (!wordbreak || single) {
            lines[n++] = (Line){para, len};
        } else {
            char *cur = para;
            size_t curn = 0, pos = 0;

            while (pos <= len && n < max) {
                size_t wend = pos;

                while (wend < len && para[wend] != ' ')
                    wend++;
                {
                    size_t trial_n = wend - (cur - para);
                    int fits = curn == 0 || text_width(dc, cur, trial_n, NULL) <= width;

                    if (!fits) {
                        lines[n++] = (Line){cur, curn};
                        cur = para + pos;
                        curn = wend - pos;
                    } else
                        curn = trial_n;
                }
                pos = wend + 1;
            }
            lines[n++] = (Line){cur, curn};
        }
        para = nl ? nl + 1 : NULL;
    }
    return n;
}

static uint32_t DrawTextA(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);
    int l = (int32_t)RD32(a[3]), t = (int32_t)RD32(a[3] + 4), r = (int32_t)RD32(a[3] + 8), b = (int32_t)RD32(a[3] + 12);
    uint32_t fmt = a[4];
    size_t len = (int32_t)a[2] < 0 ? strlen(P(a[1])) : a[2], i, o = 0;
    char *text = malloc(len + 1);
    Line lines[64];
    int n, k, single = (fmt & DT_SINGLELINE) != 0, total_h, lh = 0, widest = 0, y;

    if (!dc) {
        free(text);
        return 0;
    }
    memcpy(text, P(a[1]), len);
    text[len] = 0;
    if (!(fmt & DT_NOPREFIX)) {                                     /* "&x" marks a mnemonic (underlined in a menu); "&&" is an ampersand */
        for (i = 0; i < len; i++) {
            if (text[i] == '&') {
                if (text[i + 1] == '&')
                    text[o++] = text[i++];
                continue;
            }
            text[o++] = text[i];
        }
        text[o] = 0;
    }
    n = wrap_lines(dc, text, r - l, (fmt & DT_WORDBREAK) != 0, single, lines, 64);
    {
        int h0;

        for (k = 0; k < n; k++) {
            int w = text_width(dc, lines[k].s, lines[k].n, &h0);

            if (w > widest)
                widest = w;
            lh = h0;
        }
    }
    total_h = lh * n;
    if (fmt & DT_CALCRECT) {
        int right = (fmt & DT_WORDBREAK) && !single ? r : l + widest;

        WR32(a[3], (uint32_t)l); WR32(a[3] + 4, (uint32_t)t); WR32(a[3] + 8, (uint32_t)right); WR32(a[3] + 12, (uint32_t)(t + total_h));
        free(text);
        return (uint32_t)total_h;
    }
    y = t;
    if (single && (fmt & DT_VCENTER))
        y = t + (b - t - total_h) / 2;
    else if (single && (fmt & DT_BOTTOM))
        y = b - total_h;
    for (k = 0; k < n; k++) {
        int tw = text_width(dc, lines[k].s, lines[k].n, NULL);
        int x = (fmt & DT_CENTER) ? l + (r - l - tw) / 2 : (fmt & DT_RIGHT) ? r - tw : l;

        draw_text_at(dc, x, y, lines[k].s, lines[k].n, 0);
        y += lh;
    }
    free(text);
    return (uint32_t)total_h;
}

const WinApi GDI32_TEXT_APIS[] = {
    {"gdi32.dll", "TextOutA", TextOutA}, {"gdi32.dll", "GetTextExtentPointA", GetTextExtentPointA},
    {"gdi32.dll", "GetTextExtentPoint32A", GetTextExtentPointA}, {"gdi32.dll", "GetTextMetricsA", GetTextMetricsA},
    {"gdi32.dll", "GetCharWidthA", GetCharWidthA}, {"gdi32.dll", "GetCharABCWidthsA", GetCharABCWidthsA},
    {"user32.dll", "FillRect", FillRect}, {"user32.dll", "FrameRect", FrameRect}, {"user32.dll", "DrawFocusRect", one},
    {"user32.dll", "DrawTextA", DrawTextA},
    {0, 0, 0},
};

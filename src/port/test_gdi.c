/* test_gdi.c - the graphics layer without the game: DIB sections, blits and raster operations, palettes, mapping modes, clipping, text.
 *   make -C src/port test */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gdi_int.h"
#include "sched.h"

static int failures, checks;
#define CHECK(c) do { checks++; if (!(c)) { failures++; printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

static uint32_t cursor = 0x2000000u;
static uint32_t scratch(uint32_t n) { uint32_t p = cursor; cursor += (n + 15) & ~15u; return p; }

static uint32_t api(const char *name, uint32_t *args)
{
    static const WinApi *const tables[] = {GDI32_STATE_APIS, GDI32_BLIT_APIS, GDI32_TEXT_APIS, USER32_APIS, NULL};
    int t;
    const WinApi *p;

    for (t = 0; tables[t]; t++)
        for (p = tables[t]; p->name; p++)
            if (!strcmp(p->name, name))
                return p->fn(args);
    printf("no API %s\n", name);
    failures++;
    return 0;
}
#define API(n, ...) api(n, (uint32_t[14]){__VA_ARGS__})

#define SRCCOPY 0xCC0020u
#define SRCAND 0x8800C6u
#define SRCPAINT 0xEE0086u
#define RGB(r, g, b) ((uint32_t)(r) | (uint32_t)(g) << 8 | (uint32_t)(b) << 16)

/* a BITMAPINFO for a w x h DIB of bpp bits (bottom-up) with `ncol` colour table entries following the header */
static uint32_t bitmapinfo(int w, int h, int bpp, int ncol)
{
    uint32_t p = scratch(40 + 4 * 256);

    WR32(p, 40); WR32(p + 4, (uint32_t)w); WR32(p + 8, (uint32_t)h); WR16(p + 12, 1); WR16(p + 14, (uint16_t)bpp); WR32(p + 32, (uint32_t)ncol);
    return p;
}

static void set_colour(uint32_t bmi, int i, int r, int g, int b)
{
    WR8(bmi + 40 + 4 * (uint32_t)i, (uint8_t)b); WR8(bmi + 41 + 4 * (uint32_t)i, (uint8_t)g); WR8(bmi + 42 + 4 * (uint32_t)i, (uint8_t)r); WR8(bmi + 43 + 4 * (uint32_t)i, 0);
}

static Window *window_with_surface(int w, int h)
{
    Window *win = wm_new_window("static_test", 0, 0, 0, 0, 0, w, h, "", 0, 0);

    win->visible = 1;
    return win;
}

static uint8_t surface_index(Window *w, int x, int y) { return ((Surface *)w->surface)->idx[y * ((Surface *)w->surface)->w + x]; }

static void test_dib_to_window(void)
{
    uint32_t bmi = bitmapinfo(4, 2, 8, 256), bits = scratch(4), hdc, hmem, dib, win_dc;
    Window *win = window_with_surface(16, 16);
    int i;

    for (i = 0; i < 256; i++)
        set_colour(bmi, i, i, i, i);                           /* an identity colour table */
    hmem = API("CreateCompatibleDC", 0);
    dib = API("CreateDIBSection", hmem, bmi, 0, bits, 0, 0);
    CHECK(dib != 0 && RD32(bits) != 0);
    API("SelectObject", hmem, dib);
    {
        uint32_t px = RD32(bits);                              /* bottom-up: row 0 of the file is the bottom row */

        WR8(px + 0, 10); WR8(px + 1, 11); WR8(px + 2, 12); WR8(px + 3, 13);        /* bottom row */
        WR8(px + 4, 20); WR8(px + 5, 21); WR8(px + 6, 22); WR8(px + 7, 23);        /* top row */
    }
    win_dc = API("GetDC", win->hwnd);
    hdc = win_dc;
    CHECK(API("BitBlt", hdc, 2, 3, 4, 2, hmem, 0, 0, SRCCOPY) == 1);
    CHECK(surface_index(win, 2, 3) == 20 && surface_index(win, 5, 3) == 23);         /* the top DIB row is the top row on screen */
    CHECK(surface_index(win, 2, 4) == 10 && surface_index(win, 5, 4) == 13);
    CHECK(((Surface *)win->surface)->direct[3 * 16 + 2] == 0);                       /* indices stay indices */
}

static void test_rops(void)
{
    uint32_t bmi = bitmapinfo(2, 1, 8, 256), bits = scratch(4), hmem = API("CreateCompatibleDC", 0), dib, hdc;
    Window *win = window_with_surface(8, 8);
    int i;
    Surface *s = win->surface;

    for (i = 0; i < 256; i++)
        set_colour(bmi, i, i, i, i);
    dib = API("CreateDIBSection", hmem, bmi, 0, bits, 0, 0);
    API("SelectObject", hmem, dib);
    WR8(RD32(bits), 0xF0); WR8(RD32(bits) + 1, 0x0F);
    hdc = API("GetDC", win->hwnd);
    s->idx[0] = 0x3C; s->idx[1] = 0x3C;
    API("BitBlt", hdc, 0, 0, 2, 1, hmem, 0, 0, SRCAND);
    CHECK(s->idx[0] == (0x3C & 0xF0) && s->idx[1] == (0x3C & 0x0F));
    s->idx[0] = 0x3C; s->idx[1] = 0x3C;
    API("BitBlt", hdc, 0, 0, 2, 1, hmem, 0, 0, SRCPAINT);
    CHECK(s->idx[0] == (0x3C | 0xF0) && s->idx[1] == (0x3C | 0x0F));
    API("BitBlt", hdc, 0, 0, 2, 1, 0, 0, 0, 0x000042);                                /* BLACKNESS */
    CHECK(s->direct[0] == 1 && s->rgb[0] == 0 && s->rgb[1] == 0);
}

static void test_pixels_and_fills(void)
{
    Window *win = window_with_surface(16, 16);
    uint32_t hdc = API("GetDC", win->hwnd), br = API("CreateSolidBrush", RGB(10, 20, 30)), rc = scratch(16);
    Surface *s = win->surface;

    API("SetPixel", hdc, 3, 4, RGB(200, 100, 50));
    CHECK(API("GetPixel", hdc, 3, 4) == RGB(200, 100, 50));
    CHECK(s->direct[4 * 16 + 3] == 1);
    API("SetPixel", hdc, 5, 6, 0x01000000u | 77);                  /* PALETTEINDEX: the index itself */
    CHECK(s->idx[6 * 16 + 5] == 77 && s->direct[6 * 16 + 5] == 0);
    WR32(rc, 2); WR32(rc + 4, 2); WR32(rc + 8, 6); WR32(rc + 12, 5);
    API("FillRect", hdc, rc, br);
    CHECK(API("GetPixel", hdc, 2, 2) == RGB(10, 20, 30) && API("GetPixel", hdc, 5, 4) == RGB(10, 20, 30));
    CHECK(API("GetPixel", hdc, 6, 2) != RGB(10, 20, 30) && API("GetPixel", hdc, 2, 5) != RGB(10, 20, 30));       /* the right and bottom edges are outside */
    CHECK(API("GetPixel", hdc, 100, 100) == 0xFFFFFFFFu);
    API("FrameRect", hdc, rc, API("GetStockObject", 4));                                               /* a black frame */
    CHECK(API("GetPixel", hdc, 2, 2) == 0 && API("GetPixel", hdc, 3, 3) == RGB(10, 20, 30) && API("GetPixel", hdc, 5, 4) == 0);
}

static void test_stretch(void)
{
    uint32_t bmi = bitmapinfo(4, 4, 24, 0), bits = scratch(4), hmem = API("CreateCompatibleDC", 0), dib, hdc;
    Window *win = window_with_surface(16, 16);
    uint32_t px;
    int x, y;

    dib = API("CreateDIBSection", hmem, bmi, 0, bits, 0, 0);
    API("SelectObject", hmem, dib);
    px = RD32(bits);
    for (y = 0; y < 4; y++)
        for (x = 0; x < 4; x++) {
            uint8_t v = (uint8_t)((x + y) % 2 ? 200 : 100);                  /* a checkerboard of two greys */

            WR8(px + (uint32_t)(y * 12 + x * 3), v); WR8(px + (uint32_t)(y * 12 + x * 3 + 1), v); WR8(px + (uint32_t)(y * 12 + x * 3 + 2), v);
        }
    hdc = API("GetDC", win->hwnd);
    API("StretchBlt", hdc, 0, 0, 2, 2, hmem, 0, 0, 4, 4, SRCCOPY);            /* shrinking averages: every output pixel is the mean */
    CHECK(API("GetPixel", hdc, 0, 0) == RGB(150, 150, 150) && API("GetPixel", hdc, 1, 1) == RGB(150, 150, 150));
    API("StretchBlt", hdc, 8, 0, 8, 8, hmem, 0, 0, 4, 4, SRCCOPY);            /* growing replicates */
    CHECK(API("GetPixel", hdc, 8, 0) == RGB(200, 200, 200) && API("GetPixel", hdc, 9, 0) == RGB(200, 200, 200) && API("GetPixel", hdc, 10, 0) == RGB(100, 100, 100));   /* (the top screen row is the DIB's last row) */
}

/* Shrinking one way and stretching the other (the card text boxes: 195x104 to 162x113) must not leave black rows or columns where a destination
 * pixel's centre falls exactly on a source pixel edge. */
static void test_box_resize_no_gaps(void)
{
    int w0 = 195, h0 = 104, w = 162, h = 113, x, y, bad = 0;
    uint8_t *src = malloc((size_t)w0 * h0 * 3), *out;

    memset(src, 200, (size_t)w0 * h0 * 3);
    out = gdi_box_resize(src, w0, h0, w, h);
    for (y = 0; y < h; y++)
        for (x = 0; x < w; x++)
            if (out[((size_t)y * w + x) * 3] != 200)
                bad++;
    CHECK(bad == 0);
    free(out);
    free(src);
}

static void test_state(void)
{
    Window *win = window_with_surface(16, 16);
    uint32_t hdc = API("GetDC", win->hwnd), pt = scratch(8);

    API("SetTextColor", hdc, RGB(1, 2, 3));
    API("SetViewportOrgEx", hdc, 5, 6, 0);
    CHECK(API("SaveDC", hdc) == 1);
    API("SetTextColor", hdc, RGB(9, 9, 9));
    API("SetViewportOrgEx", hdc, 50, 60, 0);
    CHECK(API("SaveDC", hdc) == 2);
    CHECK(API("RestoreDC", hdc, (uint32_t)-1) == 1);
    CHECK(dc_of(hdc)->org[0] == 50 && dc_of(hdc)->textcolor == RGB(9, 9, 9));
    CHECK(API("RestoreDC", hdc, 1) == 1);
    CHECK(dc_of(hdc)->org[0] == 5 && dc_of(hdc)->textcolor == RGB(1, 2, 3));
    CHECK(API("RestoreDC", hdc, 1) == 0);                                  /* nothing left to restore */
    /* an isotropic mapping: 100 logical units across 200 pixels scale by 2 */
    API("SetMapMode", hdc, 7);
    API("SetWindowExtEx", hdc, 100, 100, 0);
    API("SetViewportExtEx", hdc, 200, 200, 0);
    WR32(pt, 10); WR32(pt + 4, 20);
    API("LPtoDP", hdc, pt, 1);
    CHECK((int32_t)RD32(pt) == 25 && (int32_t)RD32(pt + 4) == 46);          /* x * 2 + the viewport origin (5, 6) */
    API("DPtoLP", hdc, pt, 1);
    CHECK((int32_t)RD32(pt) == 10 && (int32_t)RD32(pt + 4) == 20);
}

static void test_mono_bitmap_and_clip(void)
{
    Window *win = window_with_surface(16, 16);
    uint32_t hdc = API("GetDC", win->hwnd), bits = scratch(4), mono, hmem = API("CreateCompatibleDC", 0), region;

    WR8(bits, 0xA0);                                                       /* 1 0 1 0 ... */
    WR8(bits + 1, 0);
    mono = API("CreateBitmap", 4, 1, 1, 1, bits);
    API("SelectObject", hmem, mono);
    API("SetTextColor", hdc, RGB(0, 0, 0));
    API("SetBkColor", hdc, RGB(255, 255, 255));
    /* a monochrome bitmap blitted to a colour DC: 0 bits take the text colour, 1 bits the background colour */
    API("BitBlt", hdc, 0, 0, 4, 1, hmem, 0, 0, SRCCOPY);
    CHECK(API("GetPixel", hdc, 0, 0) == API("GetPixel", hdc, 2, 0) && API("GetPixel", hdc, 1, 0) == API("GetPixel", hdc, 3, 0));
    CHECK(API("GetPixel", hdc, 0, 0) != API("GetPixel", hdc, 1, 0));
    region = API("CreateRectRgn", 2, 0, 4, 1);
    API("SelectClipRgn", hdc, region);
    API("BitBlt", hdc, 0, 1, 4, 1, hmem, 0, 0, SRCCOPY);
    CHECK(API("GetPixel", hdc, 0, 1) != API("GetPixel", hdc, 0, 0) || API("GetPixel", hdc, 1, 1) != API("GetPixel", hdc, 1, 0) ||
          ((Surface *)win->surface)->idx[16 + 0] == 0);                         /* outside the clip: untouched */
    CHECK(((Surface *)win->surface)->idx[16 + 0] == 0 && ((Surface *)win->surface)->idx[16 + 1] == 0);
    CHECK(((Surface *)win->surface)->idx[16 + 2] != 0 || API("GetPixel", hdc, 2, 1) != 0xFFFFFFFFu);
}

static void test_palettes(void)
{
    uint32_t pal = scratch(4 + 4 * 4), hp, hdc, ent = scratch(16);
    Window *win = window_with_surface(8, 8);
    uint8_t out[3 * 4];

    WR16(pal, 0x300); WR16(pal + 2, 4);
    WR32(pal + 4, RGB(0, 0, 0)); WR32(pal + 8, RGB(255, 0, 0)); WR32(pal + 12, RGB(0, 255, 0)); WR32(pal + 16, RGB(0, 0, 255));
    hp = API("CreatePalette", pal);
    hdc = API("GetDC", win->hwnd);
    API("SelectPalette", hdc, hp, 0);
    CHECK(API("RealizePalette", hdc) == 4);
    ((Surface *)win->surface)->idx[0] = 1;
    ((Surface *)win->surface)->idx[1] = 3;
    surface_rgb(win->surface, 0, 0, 2, 1, out);
    CHECK(out[0] == 255 && out[1] == 0 && out[2] == 0 && out[3] == 0 && out[4] == 0 && out[5] == 255);
    WR32(ent, RGB(10, 20, 30));                                             /* palette animation: the picture changes without a redraw */
    API("AnimatePalette", hp, 1, 1, ent);
    surface_rgb(win->surface, 0, 0, 2, 1, out);
    CHECK(out[0] == 10 && out[1] == 20 && out[2] == 30);
    CHECK(nearest_index((uint8_t[]){0, 250, 5}) == 2);                      /* the nearest entry of the current system palette */
}

/* A brush or pen made from a PALETTEINDEX colour means the entry of the palette of the DC it is drawn with, not of whatever the system palette held when it was made (the deck builder's
 * footer: its bar was black, its text dark grey on it, because the brush made at start-up took index 134 from the game's palette; docs/notes/deck-footer-colours.md). */
static void test_palette_relative_tools(void)
{
    uint32_t pa = scratch(4 + 4 * 3), pb = scratch(4 + 4 * 3), ha, hb, hdc, br, pen, rc = scratch(16);
    Window *win = window_with_surface(16, 16);

    WR16(pa, 0x300); WR16(pa + 2, 3);
    WR32(pa + 4, RGB(0, 0, 0)); WR32(pa + 8, RGB(200, 100, 50)); WR32(pa + 12, RGB(1, 2, 3));
    WR16(pb, 0x300); WR16(pb + 2, 3);
    WR32(pb + 4, RGB(0, 0, 0)); WR32(pb + 8, RGB(11, 22, 33)); WR32(pb + 12, RGB(44, 55, 66));
    ha = API("CreatePalette", pa);
    hb = API("CreatePalette", pb);
    hdc = API("GetDC", win->hwnd);
    br = API("CreateSolidBrush", 0x01000001u);                       /* made before either palette is on the DC: entry 1 */
    pen = API("CreatePen", 0, 1, 0x01000002u);                       /* entry 2 */
    API("SelectPalette", hdc, hb, 0);
    WR32(rc, 2); WR32(rc + 4, 2); WR32(rc + 8, 6); WR32(rc + 12, 5);
    API("FillRect", hdc, rc, br);
    CHECK(API("GetPixel", hdc, 3, 3) == RGB(11, 22, 33));            /* FillRect names the brush: the DC's palette, entry 1 */
    API("SelectPalette", hdc, ha, 0);
    API("FillRect", hdc, rc, br);
    CHECK(API("GetPixel", hdc, 3, 3) == RGB(200, 100, 50));
    API("SelectObject", hdc, br);
    API("SelectObject", hdc, pen);
    API("Rectangle", hdc, 8, 8, 14, 14);
    CHECK(API("GetPixel", hdc, 8, 8) == RGB(1, 2, 3) && API("GetPixel", hdc, 10, 10) == RGB(200, 100, 50));   /* the pen's entry 2, the brush's entry 1 of palette a */
    API("SelectPalette", hdc, hb, 0);                                /* the palette changes after the tools are selected: they follow it */
    API("Rectangle", hdc, 8, 8, 14, 14);
    CHECK(API("GetPixel", hdc, 8, 8) == RGB(44, 55, 66) && API("GetPixel", hdc, 10, 10) == RGB(11, 22, 33));
}

/* The card text of the original, measured in the Windows 98 VM at 640x480 (MPZurich Cn BT, TT0298M_.TTF, a LOGFONT of height 14 on the card's mapping, three ante cards' words and spaces: MM_ISOTROPIC, window 200 x 300, viewport 160 x 224): what
 * GetTextExtentPoint32 returned for the words and spaces of an ante card ("Gain 1 life. Use this ability ... for each such spell."), and what GetTextMetrics returned for the font
 * (docs/notes/card-text-metrics.md). Skipped when the game's font is not there (it is not in the repository). */
static void test_card_text_metrics(void)
{
    static const struct { const char *s; int cx; } words[] = {
        {" ", 3}, {"+2/+2.", 35}, {"1", 5}, {":", 3}, {"Asp", 16}, {"Enchanted", 46}, {"Flying", 27}, {"Gain", 20}, {"Nafs", 19}, {"Use", 16}, {"Whenever", 44}, {"a", 5}, {"ability", 27},
        {"additional", 43}, {"an", 11}, {"and", 16}, {"before", 27}, {"cast", 17}, {"creature", 35}, {"damage", 35}, {"damages", 39}, {"deals", 23}, {"draw", 21}, {"during", 27},
        {"each", 21}, {"for", 11}, {"gets", 17}, {"he", 11}, {"her", 13}, {"his", 12}, {"is", 7}, {"it", 5}, {"life.", 16}, {"next", 19}, {"once", 21}, {"only", 19}, {"or", 8},
        {"pays", 20}, {"phase", 26}, {"phase.", 28}, {"player", 27}, {"player,", 30}, {"red", 13}, {"she", 15}, {"spell", 20}, {"spell.", 23}, {"successfully", 52}, {"such", 20},
        {"that", 16}, {"this", 15}, {"to", 8}, {"unless", 27}, {"when", 24},
    };
    extern int fonts_add_file(const char *host_path);
    const char *path = "../../sources/installed/Magic/Program/TT0298M_.TTF";
    Window *win = window_with_surface(200, 40);
    uint32_t hdc, face = scratch(32), str = scratch(32), sz = scratch(8), tm = scratch(64), font;
    size_t i;
    int bad = 0;
    TTFont *f = ttf_load(path);

    if (!f) {
        printf("(the game's card font is not here: the card text's metrics are not checked)\n");
        return;
    }
    /* the ppem Windows picks for a cell: the largest whose hinted cell (both rounded) fits */
    CHECK(font_ppem_for_cell(f, 10) == 8 && font_ppem_for_cell(f, 11) == 9 && font_ppem_for_cell(f, 12) == 10 && font_ppem_for_cell(f, 16) == 14 && font_ppem_for_cell(f, 1) == 1);
    CHECK(fonts_add_file(path) == 1);
    hdc = API("GetDC", win->hwnd);
    API("SetMapMode", hdc, 7);                                          /* MM_ISOTROPIC: window 200 x 300 on viewport 160 x 224 (the card's: 0.8 and 0.7467), so x is cut to 149 of 160: 0.745 */
    API("SetWindowExtEx", hdc, 200, 300, 0);
    API("SetViewportExtEx", hdc, 160, 224, 0);
    strcpy((char *)(G + face), "MPZurich Cn BT");
    font = API("CreateFontA", 14, 0, 0, 0, 400, 0, 0, 0, 0, 0, 0, 0, 0, face);
    API("SelectObject", hdc, font);
    for (i = 0; i < sizeof(words) / sizeof(words[0]); i++) {
        strcpy((char *)(G + str), words[i].s);
        API("GetTextExtentPoint32A", hdc, str, (uint32_t)strlen(words[i].s), sz);
        if ((int)RD32(sz) != words[i].cx || (int)RD32(sz + 4) != 13) {
            bad++;
            printf("  '%s': %d x %d, the original's %d x 13\n", words[i].s, (int)RD32(sz), (int)RD32(sz + 4), words[i].cx);
        }
    }
    CHECK(bad == 0);
    API("GetTextMetricsA", hdc, tm);
    CHECK((int)RD32(tm) == 13 && (int)RD32(tm + 4) == 10 && (int)RD32(tm + 8) == 2 && (int)RD32(tm + 12) == 2 && (int)RD32(tm + 16) == 0 && (int)RD32(tm + 20) == 4);   /* height, ascent, descent, internal leading, external leading, average width */
}

/* The game's text is in code page 1252: 0x93 and 0x94 are the curly quotes of the 2.15 card texts, and they are drawn from the font's Unicode glyphs, not as the missing-glyph box. */
static void test_cp1252(void)
{
    const char *path = "../../sources/installed/Magic/Program/TT0298M_.TTF";
    TTFont *f;

    CHECK(font_cp1252_to_unicode(0x93) == 0x201cu && font_cp1252_to_unicode(0x94) == 0x201du && font_cp1252_to_unicode(0x91) == 0x2018u && font_cp1252_to_unicode(0x92) == 0x2019u);
    CHECK(font_cp1252_to_unicode(0x96) == 0x2013u && font_cp1252_to_unicode(0x97) == 0x2014u && font_cp1252_to_unicode(0x85) == 0x2026u && font_cp1252_to_unicode(0x80) == 0x20acu);
    CHECK(font_cp1252_to_unicode('A') == 'A' && font_cp1252_to_unicode(0x7f) == 0x7fu && font_cp1252_to_unicode(0xa0) == 0xa0u && font_cp1252_to_unicode(0xfb) == 0xfbu);
    CHECK(font_cp1252_to_unicode(0x81) == 0x81u && font_cp1252_to_unicode(0x8d) == 0x8du && font_cp1252_to_unicode(0x8f) == 0x8fu && font_cp1252_to_unicode(0x90) == 0x90u && font_cp1252_to_unicode(0x9d) == 0x9du);
    f = ttf_load(path);
    if (!f) {
        printf("(the game's card font is not here: the curly quotes' glyphs are not checked)\n");
        return;
    }
    {
        int w, h, l, t, w2, h2;
        uint8_t *q = ttf_glyph(f, 14, 0x93, &w, &h, &l, &t), *missing = ttf_glyph(f, 14, 0x81, &w2, &h2, &l, &t);

        CHECK(q != NULL && w > 0 && h > 0);
        CHECK(missing == NULL || w != w2 || h != h2 || memcmp(q, missing, (size_t)w * (size_t)h) != 0);    /* not the box U+0081 has */
        free(q);
        free(missing);
    }
}

static void test_text(void)
{
    Window *win = window_with_surface(200, 40);
    uint32_t hdc = API("GetDC", win->hwnd), sz = scratch(8), rc = scratch(16), font, txt = scratch(32);
    int w1, w2;

    font = API("CreateFontA", (uint32_t)-14, 0, 0, 0, 400, 0, 0, 0, 0, 0, 0, 0, 0, 0);          /* (a null face name falls back to the stand-in) */
    (void)font;
    strcpy((char *)(G + txt), "Hello");
    API("GetTextExtentPointA", hdc, txt, 5, sz);
    w1 = (int)RD32(sz);
    API("GetTextExtentPointA", hdc, txt, 3, sz);
    w2 = (int)RD32(sz);
    if (w1 == 0) {
        printf("(no font on this machine: text checks skipped)\n");
        return;
    }
    CHECK(w1 > w2 && w2 > 0);
    API("SetTextColor", hdc, RGB(255, 255, 255));
    API("SetBkMode", hdc, 2);
    API("SetBkColor", hdc, RGB(0, 0, 0));
    API("TextOutA", hdc, 2, 2, txt, 5);
    {
        int x, y, lit = 0;

        for (y = 0; y < 30; y++)
            for (x = 0; x < 60; x++)
                if (API("GetPixel", hdc, (uint32_t)x, (uint32_t)y) != 0)
                    lit++;
        CHECK(lit > 10);
    }
    WR32(rc, 0); WR32(rc + 4, 0); WR32(rc + 8, 400); WR32(rc + 12, 0);
    CHECK(API("DrawTextA", hdc, txt, (uint32_t)-1, rc, 0x400 | 0x20) > 0);              /* DT_CALCRECT | DT_SINGLELINE: the size of the text */
    CHECK((int)RD32(rc + 8) == w1);
}

/* Small text is drawn the way Windows 98's hinted, unsmoothed text looks (solid strokes), not as a pale smear: text_coverage doubles the coverage up to 10 pixels and
 * fades the gain out by 14. (docs/notes/castle-text.md: the card text of the castle panels at 640x480.) */
static void test_small_text_coverage(void)
{
    CHECK(text_coverage(0, 8) == 0 && text_coverage(255, 8) == 255);
    CHECK(text_coverage(100, 8) == 200 && text_coverage(100, 10) == 200 && text_coverage(200, 9) == 255);
    CHECK(text_coverage(100, 14) == 100 && text_coverage(100, 30) == 100);
    CHECK(text_coverage(100, 12) == 150);                                    /* the taper between 10 and 14 */
}

int pe_find_resource(uint32_t hinst, uint32_t type, uint32_t name, uint32_t *addr, uint32_t *size) { (void)hinst; (void)type; (void)name; (void)addr; (void)size; return 0; }

/* What Spells of the Ancients asks of the graphics layer: whether a rectangle touches a region, text with a rectangle, the width of a character that arrives sign-extended, and the
 * desktop's device context given back (it opens one for every character it measures) */
static void test_sota_calls(void)
{
    Window *win = window_with_surface(32, 32);
    uint32_t rgn = API("CreateRectRgn", 10, 10, 20, 20), rc = scratch(16), abc = scratch(64 * 12), hdc = API("GetDC", win->hwnd), h1, h2, own;

    WR32(rc, 15); WR32(rc + 4, 15); WR32(rc + 8, 30); WR32(rc + 12, 30);
    CHECK(API("RectInRegion", rgn, rc) == 1);
    WR32(rc, 20); WR32(rc + 4, 20);
    CHECK(API("RectInRegion", rgn, rc) == 0);                                          /* both are half open: x = 20 is outside */
    WR32(rc, 0); WR32(rc + 4, 0); WR32(rc + 8, 10); WR32(rc + 12, 10);
    CHECK(API("RectInRegion", rgn, rc) == 0);
    WR32(rc + 8, 11); WR32(rc + 12, 11);
    CHECK(API("RectInRegion", rgn, rc) == 1);
    WR32(rc, 12); WR32(rc + 4, 12); WR32(rc + 8, 12); WR32(rc + 12, 12);
    CHECK(API("RectInRegion", rgn, rc) == 0);                                          /* an empty rectangle touches nothing */
    CHECK(API("RectInRegion", 0x1234, rc) == 0);

    /* ExtTextOutA with ETO_OPAQUE and no text fills the rectangle with the background colour; the rest is as it was */
    API("SetBkColor", hdc, RGB(10, 20, 30));
    WR32(rc, 2); WR32(rc + 4, 2); WR32(rc + 8, 6); WR32(rc + 12, 5);
    CHECK(API("ExtTextOutA", hdc, 0, 0, 2, rc, 0, 0, 0) == 1);
    CHECK(API("GetPixel", hdc, 2, 2) == RGB(10, 20, 30) && API("GetPixel", hdc, 5, 4) == RGB(10, 20, 30));
    CHECK(API("GetPixel", hdc, 6, 2) != RGB(10, 20, 30) && API("GetPixel", hdc, 2, 5) != RGB(10, 20, 30));
    {
        uint32_t txt = scratch(8), dx = scratch(16), outside = API("GetPixel", hdc, 20, 20);

        memcpy(G + txt, "ab", 3);
        WR32(dx, 5); WR32(dx + 4, 5);
        CHECK(API("ExtTextOutA", hdc, 0, 0, 4, rc, txt, 2, dx) == 1);                  /* ETO_CLIPPED with the characters' own advances: nothing outside the rectangle */
        CHECK(API("GetPixel", hdc, 20, 20) == outside);
        CHECK(API("ExtTextOutA", hdc, 8, 8, 0, 0, txt, 2, 0) == 1);                    /* plain, like TextOut */
    }

    /* a character with its sign extended is a range that ends at 0xFFFFFFFF: one character, not four billion */
    CHECK(API("GetCharABCWidthsA", hdc, 0xFFFFFFFFu, 0xFFFFFFFFu, abc) == 1);
    CHECK(API("GetCharABCWidthsA", hdc, 0xFFFFFFE9u, 0xFFFFFFE9u, abc) == 1);
    CHECK(API("GetCharWidthA", hdc, 0xFFFFFFFFu, 0xFFFFFFFFu, abc) == 1);
    CHECK(API("GetCharABCWidthsA", hdc, 5, 4, abc) == 0 && API("GetCharWidthA", hdc, 0, 0x10000, abc) == 0);     /* backwards, and more than a font has */
    CHECK(API("GetCharWidthA", hdc, 65, 66, abc) == 1 && API("GetCharABCWidthsA", hdc, 65, 66, abc) == 1);

    /* the desktop's context is given back by ReleaseDC and its handle is the next one's; a window's own is kept (a window class with CS_OWNDC has one for good) */
    h1 = API("GetDC", 0);
    API("ReleaseDC", 0, h1);
    h2 = API("GetDC", 0);
    CHECK(h2 == h1 && API("GetCharWidthA", h2, 65, 65, abc) == 1);
    API("ReleaseDC", 0, h2);
    own = API("GetDC", win->hwnd);
    API("ReleaseDC", win->hwnd, own);
    CHECK(API("GetPixel", own, 1, 1) != 0xFFFFFFFFu);                                    /* still a context for the window */
    API("ReleaseDC", 0, 0x12345678u);                                                    /* what is not a context is left alone */
}

int main(void)
{
    extern void kernel32_init(void);

    guest_init();
    sched_init();
    kernel32_init();
    test_dib_to_window();
    test_rops();
    test_pixels_and_fills();
    test_stretch();
    test_box_resize_no_gaps();
    test_state();
    test_mono_bitmap_and_clip();
    test_palettes();
    test_palette_relative_tools();
    test_card_text_metrics();
    test_cp1252();
    test_text();
    test_small_text_coverage();
    test_sota_calls();
    printf("%d checks, %d failed\n", checks, failures);
    return failures ? 1 : 0;
}

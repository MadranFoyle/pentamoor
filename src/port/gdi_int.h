/*
 * gdi_int.h - the graphics layer's own structures (gdi*.c, compose.c). Behaviour: winemu/gdi.py.
 *
 * The screen model: the display is 8-bit, so a window's surface holds palette *indices*, and colours come from the system palette when the
 * screen is composed (palette animation then changes the picture without a redraw). Direct-colour drawing (24- and 32-bit sources, fills
 * with an RGB colour) goes into an overlay: `rgb` where `direct` is set. A bitmap is either a device-dependent one (indices, plus a 1-bit plane
 * for monochrome bitmaps) or a DIB section, whose pixels live in the guest's memory where the game writes them itself.
 */
#ifndef PORT_GDI_INT_H
#define PORT_GDI_INT_H

#include <stdint.h>

#include "gdi.h"


typedef struct Surface {
    int w, h;
    uint8_t *idx;       /* w*h palette indices */
    uint8_t *rgb;       /* w*h*3 direct-colour pixels */
    uint8_t *direct;    /* w*h: where rgb overrides the palette lookup */
    uint8_t *touched;   /* w*h: 1 where drawing has written (a see-through window shows what is behind it everywhere else) */
} Surface;

typedef struct Palette {
    int n;
    uint8_t e[256][3];  /* entries beyond 256 are not kept (the game's palettes have 256) */
} Palette;

typedef struct Bitmap {
    int ddb;                 /* 1: device-dependent (idx / mono below), 0: DIB section (bits in guest memory) */
    int w, h, bpp;
    uint32_t bits;           /* DIB: guest address of the pixels */
    int topdown;
    uint8_t palette[256][3]; /* DIB colour table */
    int npalette;
    uint8_t *idxmap;         /* DIB_PAL_COLORS: pixel value -> logical (= system) palette index; NULL otherwise */
    uint8_t *idx;            /* DDB: indices in system-palette space */
    uint8_t *mono;           /* 1-bpp DDB: 0 / 1 per pixel */
} Bitmap;

/* A brush or pen made from a PALETTEINDEX colour (flag byte 1) keeps the index (cref, rel = 1) and means the entry of the palette of the DC it is drawn with: rgb is that entry as of the
 * last place it was resolved (creation: the system palette; SelectObject, SelectPalette and FillRect: the DC's). docs/notes/deck-footer-colours.md. */
typedef struct Brush { int solid; uint8_t rgb[3]; uint32_t pattern; /* a bitmap handle, or 0 */ uint32_t cref; int rel; } Brush;
typedef struct Pen { int solid; uint8_t rgb[3]; int width; uint32_t cref; int rel; } Pen;
typedef struct Font { char face[40]; int size, weight, italic, height; } Font;
typedef struct Region { int l, t, r, b; } Region;

typedef struct DC DC;
struct DC {
    int uses;                /* how often drawing code asked for this context (dc_of): a WM_ERASEBKGND that never did has drawn nothing */
    int memory;              /* 0: a window's client area, 1: a memory DC */
    uint32_t hwnd;
    Bitmap *bitmap;
    Palette *palette;
    uint32_t textcolor, bkcolor;
    int bkmode;
    Pen pen;
    Brush brush;
    Font *font;
    int org[2], wo[2], wext[2], vext[2];
    double sx, sy;
    int mm;
    int pos[2];
    int has_clip, clip[4];
    int textalign;
    DC *saved;               /* the SaveDC stack: a chain of copies */
};

enum { O_NONE = 0, O_PEN, O_BRUSH, O_FONT, O_PALETTE, O_BITMAP, O_REGION, O_DC, O_CURSOR, O_ICON, O_ACCEL };

/* the object table */
uint32_t obj_new(int kind, void *p);
void *obj_get(uint32_t h, int kind);
int obj_kind(uint32_t h);
void obj_free(uint32_t h);
void gdi_release_dc(uint32_t h);                                    /* ReleaseDC, DeleteDC */
DC *dc_of(uint32_t h);
uint32_t dc_new(int memory, uint32_t hwnd);
uint32_t stock_object(int which);

/* the system palette (shared: AnimatePalette on the realized palette shows at once) */
extern Palette *system_palette;
extern uint32_t palette_generation;
int nearest_index(const uint8_t rgb[3]);
void quantize(const uint8_t *rgb, int count, uint8_t *out);
uint32_t colorref_rgb(const DC *dc, uint32_t c, uint8_t out[3]);
int color_index(const DC *dc, uint32_t c);
void brush_color(const DC *dc, const Brush *b, uint8_t out[3]);     /* a solid brush's colour on this DC (a palette-relative one through the DC's palette) */
void pen_color(const DC *dc, const Pen *p, uint8_t out[3]);
void dc_resolve_tools(DC *dc);                                      /* the DC's selected pen and brush, again, after its palette changed */

/* surfaces */
Surface *surface_new(int w, int h);
void surface_free(Surface *s);
void surface_touched(const Surface *s, uint8_t *alpha);
void surface_rgb(const Surface *s, int x0, int y0, int x1, int y1, uint8_t *out);     /* the palette's colours with the direct overlay */

/* DC targets */
void target_size(const DC *dc, int *w, int *h);
uint8_t *get_region(DC *dc, int x0, int y0, int x1, int y1, int *rw, int *rh, int *rx, int *ry);   /* malloc'd RGB, clipped to the target */
void put_region(DC *dc, int x0, int y0, const uint8_t *rgb, int w, int h);
void put_region_masked(DC *dc, int x0, int y0, const uint8_t *rgb, int w, int h, const uint8_t *mask);
void put_indices(DC *dc, int x0, int y0, const uint8_t *idx, int w, int h);
uint8_t *dc_indices(DC *dc, int x0, int y0, int x1, int y1, DC *mono_dc, int *rx, int *ry, int *rw, int *rh);   /* NULL: needs colours */
void fill_rect_rgb(DC *dc, int x0, int y0, int w, int h, const uint8_t color[3]);          /* device units, relative to the viewport origin */
void fill_rect_logical(DC *dc, int x0, int y0, int x1, int y1, const uint8_t color[3]);

/* DIB sections */
void dib_stride(const Bitmap *b, int *stride);
uint8_t *read_dib_rgb(const Bitmap *b, int x0, int y0, int x1, int y1, int *rw, int *rh);
void write_dib_rgb(Bitmap *b, int x0, int y0, const uint8_t *rgb, int w, int h);
void write_dib_indices(Bitmap *b, int x0, int y0, const uint8_t *idx, int w, int h);
uint8_t *read_dib_indices(const Bitmap *b, int x0, int y0, int x1, int y1);
void dib_to_system_lut(const uint8_t pal[][3], int n, uint8_t out[256]);
void dib_to_dib_lut(const uint8_t src[][3], int ns, const uint8_t dst[][3], int nd, uint8_t out[256]);

/* mapping */
int lx(const DC *dc, int x);
int ly(const DC *dc, int y);
void dev_rect(const DC *dc, int x, int y, int w, int h, int out[4]);

/* blits and fills */
int gdi_blit(DC *dst, DC *src, int x, int y, int w, int h, int sx, int sy, int sw, int sh, uint32_t rop);
uint8_t *gdi_box_resize(const uint8_t *src, int w0, int h0, int w, int h);   /* RGB, 3 bytes a pixel; malloc'd */

/* text */
int text_width(const DC *dc, const char *s, size_t n, int *height);                 /* logical units */
void draw_text_at(DC *dc, int x, int y, const char *s, size_t n, int align);
uint8_t text_coverage(uint8_t a, double em);                                         /* a glyph pixel's coverage as GDI's hinted, unsmoothed text would look at this size */

/* the TrueType rasterizer (font.c) */
typedef struct TTFont TTFont;
TTFont *ttf_load(const char *path);
const char *ttf_family(const TTFont *f);
const char *ttf_style(const TTFont *f);
void ttf_text_metrics(const TTFont *f, double em, int *height, int *avg_width);           /* tmHeight and tmAveCharWidth (the dialog base units) */
int ttf_avg_width(const TTFont *f, double em);                                            /* tmAveCharWidth: the OS/2 table's xAvgCharWidth, rounded; 0 if none */
int ttf_ascent(const TTFont *f, double em);                                               /* tmAscent: the rounded ascent */
void ttf_metrics(const TTFont *f, double em, int *ascent, int *descent);              /* hinted-like integer metrics at an em size in pixels (the ascent and the descent rounded up: where glyphs are placed) */
void ttf_cell(const TTFont *f, double em, int *ascent, int *descent);                 /* the cell Windows reports at a whole ppem: both rounded to nearest (tmAscent, tmDescent) */
double ttf_advance(const TTFont *f, double em, unsigned char ch);                      /* integer-rounded advance of a Latin-1 character */
double ttf_kern(const TTFont *f, double em, unsigned char a, unsigned char b);
int font_ppem_for_cell(const TTFont *f, int cell);                                     /* the ppem Windows gives a TrueType font asked for a cell of this many pixels */
uint8_t *ttf_glyph(const TTFont *f, double em, unsigned char ch, int *w, int *h, int *left, int *top);   /* malloc'd coverage plane, or NULL (a space) */

/* text on a plain RGB buffer in the stand-in face (the compositor's own labels) */
void text_on_rgb(uint8_t *rgb, int w, int h, int x, int y, const char *s, int size, const uint8_t color[3]);
int text_extent(const char *s, int size);
void ui_font_metrics(const char *face, int pt, int bold, int *height, int *ascent, int *avg);
int ui_pixel_size(int pt);
uint32_t gdi_dialog_font(const char *face, int pt);
int ui_dlu_x(int v, int avg);                  /* dialog units to pixels, as Windows 98 rounds them */
int ui_dlu_y(int v, int height);
int ui_text_width(const char *face, int pt, int bold, const char *s, size_t n);
int ui_text_measure(const char *face, int pt, int bold, const char *s, int width, int *widest);   /* ui.c: the height of a text wrapped to a width, and its longest line */
void ui_text_draw(uint8_t *rgb, int w, int h, int x, int y, const char *s, size_t n, const char *face, int pt, int bold, const uint8_t color[3]);
int compose_write_ppm(const char *path);

/* composing the screen */
void compose_screen(uint8_t *rgb640x480);
extern int compose_popup_hook;

#endif

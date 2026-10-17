/* gdi.c - objects, device contexts, palettes, surfaces, DIB sections, and the state APIs of gdi32. Port of winemu/gdi.py (first half). */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gdi_int.h"
#include "sched.h"

#define P(a) ((char *)(G + (a)))
#define OBJ_BASE 0x2001u

/* ---- the object table ------------------------------------------------------------------------------------------------------------ */
typedef struct Obj { int kind; void *p; } Obj;
static Obj *objs;
static int nobjs, capobjs;

/* The slots of device contexts that were released (ReleaseDC, DeleteDC) are used again by the next one, as Windows hands a handle out again: a program that measures a character with
 * GetDC, SelectObject, GetCharABCWidths and ReleaseDC (Spells of the Ancients does it for every character it draws) would otherwise take a slot and a context for each. */
static uint32_t *free_dcs;
static int nfree_dcs, capfree_dcs;

uint32_t obj_new(int kind, void *p)
{
    if (kind == O_DC && nfree_dcs) {
        uint32_t i = free_dcs[--nfree_dcs];

        objs[i] = (Obj){kind, p};
        return OBJ_BASE + 4u * i;
    }
    if (nobjs == capobjs) {
        capobjs = capobjs ? capobjs * 2 : 512;
        objs = realloc(objs, (size_t)capobjs * sizeof(*objs));
    }
    objs[nobjs] = (Obj){kind, p};
    return OBJ_BASE + 4u * (uint32_t)nobjs++;
}

static Obj *slot(uint32_t h)
{
    uint32_t i;

    if (h < OBJ_BASE || (h - OBJ_BASE) % 4)
        return NULL;
    i = (h - OBJ_BASE) / 4;
    return i < (uint32_t)nobjs && objs[i].kind ? &objs[i] : NULL;
}

void *obj_get(uint32_t h, int kind)
{
    Obj *o = slot(h);

    return o && o->kind == kind ? o->p : NULL;
}

int obj_kind(uint32_t h)
{
    Obj *o = slot(h);

    return o ? o->kind : 0;
}

void obj_free(uint32_t h)
{
    Obj *o = slot(h);

    if (o)
        o->kind = 0;
}

/* ReleaseDC and DeleteDC: the context goes (with the copies SaveDC made) and its handle can be given out again. A handle that is not a context, or has been released, is left alone. */
void gdi_release_dc(uint32_t h)
{
    Obj *o = slot(h);
    DC *d, *next;

    if (!o || o->kind != O_DC)
        return;
    for (d = o->p; d; d = next) {
        next = d->saved;
        free(d);
    }
    o->kind = 0;
    o->p = NULL;
    if (nfree_dcs == capfree_dcs) {
        capfree_dcs = capfree_dcs ? capfree_dcs * 2 : 64;
        free_dcs = realloc(free_dcs, (size_t)capfree_dcs * sizeof(*free_dcs));
    }
    free_dcs[nfree_dcs++] = (h - OBJ_BASE) / 4;
}

/* The window manager's names for the same table (cursors, icons, accelerators: opaque handles). */
int screen_w = 640, screen_h = 480;

void screen_set(int w, int h)
{
    if (w >= 640 && w <= SCREEN_MAX_W && h >= 480 && h <= SCREEN_MAX_H) {
        screen_w = w;
        screen_h = h;
    }
}

uint32_t gdi_new_object(int kind, uint32_t a, uint32_t b)
{
    uint32_t *p = malloc(8);

    p[0] = a;
    p[1] = b;
    return obj_new(kind == GDI_CURSOR ? O_CURSOR : kind == GDI_ICON ? O_ICON : O_ACCEL, p);
}

DC *dc_of(uint32_t h)
{
    DC *d = obj_get(h, O_DC);

    if (d)
        d->uses++;
    return d;
}

/* ---- the system palette and colours -------------------------------------------------------------------------------------------- */
static Palette default_palette;
Palette *system_palette;
uint32_t palette_generation = 1;
static int system_palette_set;

static void init_gdi(void)
{
    int i;

    if (system_palette)
        return;
    default_palette.n = 256;
    for (i = 0; i < 256; i++)
        default_palette.e[i][0] = default_palette.e[i][1] = default_palette.e[i][2] = (uint8_t)i;
    system_palette = &default_palette;
}

/* The index of the system-palette entry nearest to a colour (the first of equals). */
int nearest_index(const uint8_t rgb[3])
{
    static struct { uint32_t key, gen; int idx; } cache[4096];
    uint32_t key = (uint32_t)rgb[0] << 16 | (uint32_t)rgb[1] << 8 | rgb[2], h = (key * 2654435761u) >> 20;
    int best = 0, i;
    long bd = 1L << 30;      /* more than any squared distance of two colours (3 * 255^2); a long is 32 bits on Windows */

    if (cache[h].gen == palette_generation && cache[h].key == key && cache[h].gen)
        return cache[h].idx;
    init_gdi();
    for (i = 0; i < 256; i++) {
        long dr = (long)system_palette->e[i][0] * (i < system_palette->n) - rgb[0], dg = (long)system_palette->e[i][1] * (i < system_palette->n) - rgb[1],
             db = (long)system_palette->e[i][2] * (i < system_palette->n) - rgb[2], d = dr * dr + dg * dg + db * db;

        if (d < bd) {
            bd = d;
            best = i;
        }
    }
    cache[h].key = key;
    cache[h].gen = palette_generation;
    cache[h].idx = best;
    return best;
}

void quantize(const uint8_t *rgb, int count, uint8_t *out)
{
    int i;

    for (i = 0; i < count; i++)
        out[i] = (uint8_t)nearest_index(rgb + 3 * i);
}

/* (r, g, b) from a COLORREF; the palette-index form uses the DC's palette (else the system palette). Returns the flag byte. */
uint32_t colorref_rgb(const DC *dc, uint32_t c, uint8_t out[3])
{
    uint32_t flag = (c >> 24) & 0xFF;

    init_gdi();
    if (flag == 0x01) {
        const Palette *pal = dc && dc->palette ? dc->palette : system_palette;
        int n = pal->n ? pal->n : 1;

        out[0] = pal->e[(c & 0xFFFF) % (uint32_t)n][0];
        out[1] = pal->e[(c & 0xFFFF) % (uint32_t)n][1];
        out[2] = pal->e[(c & 0xFFFF) % (uint32_t)n][2];
        return flag;
    }
    out[0] = (uint8_t)c;
    out[1] = (uint8_t)(c >> 8);
    out[2] = (uint8_t)(c >> 16);
    return flag;
}

/* The system-palette index a COLORREF stands for on this DC (a palette index as itself, an RGB value as its nearest entry). */
int color_index(const DC *dc, uint32_t c)
{
    uint8_t rgb[3];

    if ((c >> 24) & 0xFF) {
        if (((c >> 24) & 0xFF) == 1)
            return (int)(c & 0xFF);
    }
    colorref_rgb(dc, c, rgb);
    return nearest_index(rgb);
}

void brush_color(const DC *dc, const Brush *b, uint8_t out[3])
{
    if (b->rel && dc)
        colorref_rgb(dc, b->cref, out);
    else
        memcpy(out, b->rgb, 3);
}

void pen_color(const DC *dc, const Pen *p, uint8_t out[3])
{
    if (p->rel && dc)
        colorref_rgb(dc, p->cref, out);
    else
        memcpy(out, p->rgb, 3);
}

void dc_resolve_tools(DC *dc)
{
    if (dc->brush.rel)
        brush_color(dc, &dc->brush, dc->brush.rgb);
    if (dc->pen.rel)
        pen_color(dc, &dc->pen, dc->pen.rgb);
}

/* ---- surfaces -------------------------------------------------------------------------------------------------------------------- */
Surface *surface_new(int w, int h)
{
    Surface *s = calloc(1, sizeof(*s));

    s->w = w > 0 ? w : 1;
    s->h = h > 0 ? h : 1;
    s->idx = calloc((size_t)s->w * (size_t)s->h, 1);
    s->rgb = calloc((size_t)s->w * (size_t)s->h, 3);
    s->direct = calloc((size_t)s->w * (size_t)s->h, 1);
    s->touched = calloc((size_t)s->w * (size_t)s->h, 1);
    return s;
}

void surface_free(Surface *s)
{
    if (!s)
        return;
    free(s->idx);
    free(s->rgb);
    free(s->direct);
    free(s->touched);
    free(s);
}

/* The surface's colours for a rectangle: indices through the system palette, the direct overlay on top. */
void surface_rgb(const Surface *s, int x0, int y0, int x1, int y1, uint8_t *out)
{
    int x, y;

    init_gdi();
    for (y = y0; y < y1; y++)
        for (x = x0; x < x1; x++) {
            size_t i = (size_t)y * (size_t)s->w + (size_t)x;
            uint8_t *o = out + 3 * ((size_t)(y - y0) * (size_t)(x1 - x0) + (size_t)(x - x0));

            if (s->direct[i]) {
                o[0] = s->rgb[3 * i]; o[1] = s->rgb[3 * i + 1]; o[2] = s->rgb[3 * i + 2];
            } else {
                int k = s->idx[i];

                if (k < system_palette->n) {
                    o[0] = system_palette->e[k][0]; o[1] = system_palette->e[k][1]; o[2] = system_palette->e[k][2];
                } else
                    o[0] = o[1] = o[2] = 0;
            }
        }
}

void gdi_resize_surface(Window *w)
{
    int cw, ch;
    Surface *s = w->surface;

    wm_client_size(w, &cw, &ch);
    if (!s || s->w != (cw > 0 ? cw : 1) || s->h != (ch > 0 ? ch : 1)) {
        surface_free(s);
        w->surface = surface_new(cw, ch);
    }
}

void gdi_release_surface(Window *w)
{
    surface_free(w->surface);
    w->surface = NULL;
}

void gdi_clear_surface(Window *w)
{
    Surface *s = w->surface;

    if (s) {
        memset(s->idx, 0, (size_t)s->w * (size_t)s->h);
        memset(s->direct, 0, (size_t)s->w * (size_t)s->h);
        memset(s->touched, 0, (size_t)s->w * (size_t)s->h);
    }
}

void gdi_forget_texts(Window *w) { (void)w; }

/* alpha (w*h): 1 where something was drawn, 0 where the surface is still as it was made. */
void surface_touched(const Surface *s, uint8_t *alpha) { memcpy(alpha, s->touched, (size_t)s->w * (size_t)s->h); }

/* Sends WM_ERASEBKGND to a window with a fresh device context and returns the procedure's answer. An answer of "erased" from a procedure that never used
 * the device context is see-through (Window.see_through): it drew nothing, so what its own painting leaves untouched shows what is behind it. */
uint32_t gdi_send_erase(Window *w, uint32_t h)
{
    uint32_t r;
    DC *d;

    if (!h)
        h = gdi_window_dc(w->hwnd);
    d = obj_get(h, O_DC);
    if (d)
        d->uses = 0;
    r = wm_send(w->hwnd, WM_ERASEBKGND, h, 0);
    d = obj_get(h, O_DC);
    if (r && d && d->uses == 0 && !w->see_through) {
        w->see_through = 1;
        port_trace("window 0x%x (%s '%s') answered WM_ERASEBKGND without drawing: see-through", w->hwnd, w->cname, w->title);
    }
    return r;
}

/* ---- device contexts ------------------------------------------------------------------------------------------------------------- */
uint32_t dc_new(int memory, uint32_t hwnd)
{
    DC *d = calloc(1, sizeof(*d));

    init_gdi();
    d->memory = memory;
    d->hwnd = hwnd;
    d->textcolor = 0;
    d->bkcolor = 0xFFFFFF;
    d->bkmode = 2;
    d->pen = (Pen){1, {0, 0, 0}, 1, 0, 0};
    d->brush = (Brush){1, {255, 255, 255}, 0, 0, 0};
    d->font = NULL;
    d->wext[0] = d->wext[1] = d->vext[0] = d->vext[1] = 1;
    d->sx = d->sy = 1.0;
    d->mm = 1;
    return obj_new(O_DC, d);
}

uint32_t gdi_window_dc(uint32_t hwnd)
{
    uint32_t h = dc_new(0, hwnd);

    if (!hwnd || !wm_window(hwnd))
        dc_of(h)->hwnd = wm_desktop();
    return h;
}

void target_size(const DC *dc, int *w, int *h)
{
    if (dc->memory) {
        *w = dc->bitmap ? dc->bitmap->w : 1;
        *h = dc->bitmap ? dc->bitmap->h : 1;
        return;
    }
    {
        Window *win = wm_window(dc->hwnd);
        Surface *s = win ? win->surface : NULL;

        *w = s ? s->w : SCREEN_W;
        *h = s ? s->h : SCREEN_H;
    }
}

/* ---- DIB sections ----------------------------------------------------------------------------------------------------------------- */
void dib_stride(const Bitmap *b, int *stride) { *stride = ((b->w * b->bpp + 31) / 32) * 4; }

static uint8_t *dib_row(const Bitmap *b, int y)
{
    int stride;

    dib_stride(b, &stride);
    return G + b->bits + (size_t)(b->topdown ? y : b->h - 1 - y) * (size_t)stride;
}

/* RGB of a rectangle of a DIB section, converting through its colour table. */
uint8_t *read_dib_rgb(const Bitmap *b, int x0, int y0, int x1, int y1, int *rw, int *rh)
{
    uint8_t *out;
    int x, y, w, h;

    x0 = x0 < 0 ? 0 : x0;
    y0 = y0 < 0 ? 0 : y0;
    x1 = x1 > b->w ? b->w : x1;
    y1 = y1 > b->h ? b->h : y1;
    w = x1 - x0;
    h = y1 - y0;
    *rw = w > 0 ? w : 0;
    *rh = h > 0 ? h : 0;
    if (w <= 0 || h <= 0)
        return NULL;
    out = malloc((size_t)w * (size_t)h * 3);
    for (y = 0; y < h; y++) {
        const uint8_t *row = dib_row(b, y0 + y);
        uint8_t *o = out + (size_t)y * (size_t)w * 3;

        for (x = 0; x < w; x++) {
            int sx = x0 + x;

            if (b->bpp == 8) {
                const uint8_t *c = row[sx] < b->npalette ? b->palette[row[sx]] : (const uint8_t[3]){0, 0, 0};

                o[3 * x] = c[0]; o[3 * x + 1] = c[1]; o[3 * x + 2] = c[2];
            } else if (b->bpp == 24) {
                o[3 * x] = row[sx * 3 + 2]; o[3 * x + 1] = row[sx * 3 + 1]; o[3 * x + 2] = row[sx * 3];
            } else if (b->bpp == 32) {
                o[3 * x] = row[sx * 4 + 2]; o[3 * x + 1] = row[sx * 4 + 1]; o[3 * x + 2] = row[sx * 4];
            } else if (b->bpp == 16) {
                uint16_t v = (uint16_t)(row[sx * 2] | row[sx * 2 + 1] << 8);

                o[3 * x] = (uint8_t)(((v >> 10) & 31) << 3); o[3 * x + 1] = (uint8_t)(((v >> 5) & 31) << 3); o[3 * x + 2] = (uint8_t)((v & 31) << 3);
            } else
                o[3 * x] = o[3 * x + 1] = o[3 * x + 2] = 0;
        }
    }
    return out;
}

/* Store an RGB rectangle into a DIB section (8-bit: the nearest colour-table entry). */
void write_dib_rgb(Bitmap *b, int x0, int y0, const uint8_t *rgb, int w, int h)
{
    int x, y;

    if (b->bpp != 24 && b->bpp != 32 && b->bpp != 8)
        return;
    for (y = 0; y < h; y++) {
        uint8_t *row;

        if (y0 + y < 0 || y0 + y >= b->h)
            continue;
        row = dib_row(b, y0 + y);
        for (x = 0; x < w; x++) {
            int dx = x0 + x;
            const uint8_t *c = rgb + 3 * ((size_t)y * (size_t)w + (size_t)x);

            if (dx < 0 || dx >= b->w)
                continue;
            if (b->bpp == 24) {
                row[dx * 3] = c[2]; row[dx * 3 + 1] = c[1]; row[dx * 3 + 2] = c[0];
            } else if (b->bpp == 32) {
                row[dx * 4] = c[2]; row[dx * 4 + 1] = c[1]; row[dx * 4 + 2] = c[0]; row[dx * 4 + 3] = 0;
            } else {
                int best = 0, i;
                long bd = 1L << 30;

                for (i = 0; i < b->npalette; i++) {
                    long dr = (long)b->palette[i][0] - c[0], dg = (long)b->palette[i][1] - c[1], db = (long)b->palette[i][2] - c[2], d = dr * dr + dg * dg + db * db;

                    if (d < bd) {
                        bd = d;
                        best = i;
                    }
                }
                row[dx] = (uint8_t)best;
            }
        }
    }
}

void write_dib_indices(Bitmap *b, int x0, int y0, const uint8_t *idx, int w, int h)
{
    int y;

    for (y = 0; y < h; y++) {
        int xs, xe;

        if (y0 + y < 0 || y0 + y >= b->h)
            continue;
        xs = x0 < 0 ? 0 : x0;
        xe = x0 + w > b->w ? b->w : x0 + w;
        if (xe > xs)
            memcpy(dib_row(b, y0 + y) + xs, idx + (size_t)y * (size_t)w + (size_t)(xs - x0), (size_t)(xe - xs));
    }
}

/* The raw bytes of rows y0..y1 and columns x0..x1 of an 8-bit DIB, as a fresh array (top row first). */
uint8_t *read_dib_indices(const Bitmap *b, int x0, int y0, int x1, int y1)
{
    int y, w = x1 - x0, h = y1 - y0;
    uint8_t *out;

    if (w <= 0 || h <= 0)
        return NULL;
    out = malloc((size_t)w * (size_t)h);
    for (y = 0; y < h; y++)
        memcpy(out + (size_t)y * (size_t)w, dib_row(b, y0 + y) + x0, (size_t)w);
    return out;
}

/* A DIB colour table to system-palette indices: identity where the entries agree (as Windows does for an identity palette), otherwise the nearest. */
void dib_to_system_lut(const uint8_t pal[][3], int n, uint8_t out[256])
{
    int i, j;

    init_gdi();
    for (i = 0; i < 256; i++) {
        uint8_t t[3] = {0, 0, 0};
        long bd = 1L << 30;
        int best = 0;

        if (i < n) { t[0] = pal[i][0]; t[1] = pal[i][1]; t[2] = pal[i][2]; }
        if (i < system_palette->n && system_palette->e[i][0] == t[0] && system_palette->e[i][1] == t[1] && system_palette->e[i][2] == t[2]) {
            out[i] = (uint8_t)i;
            continue;
        }
        for (j = 0; j < 256; j++) {
            long dr = (j < system_palette->n ? system_palette->e[j][0] : 0) - (long)t[0], dg = (j < system_palette->n ? system_palette->e[j][1] : 0) - (long)t[1],
                 db = (j < system_palette->n ? system_palette->e[j][2] : 0) - (long)t[2], d = dr * dr + dg * dg + db * db;

            if (d < bd) {
                bd = d;
                best = j;
            }
        }
        out[i] = (uint8_t)best;
    }
}

void dib_to_dib_lut(const uint8_t src[][3], int ns, const uint8_t dst[][3], int nd, uint8_t out[256])
{
    int i, j;

    for (i = 0; i < 256; i++) {
        uint8_t t[3] = {0, 0, 0}, d0[3];
        long bd = 1L << 30;
        int best = 0, same;

        if (i < ns) { t[0] = src[i][0]; t[1] = src[i][1]; t[2] = src[i][2]; }
        d0[0] = d0[1] = d0[2] = 0;
        if (i < nd) { d0[0] = dst[i][0]; d0[1] = dst[i][1]; d0[2] = dst[i][2]; }
        same = d0[0] == t[0] && d0[1] == t[1] && d0[2] == t[2];
        if (same) {
            out[i] = (uint8_t)i;
            continue;
        }
        for (j = 0; j < 256; j++) {
            uint8_t e[3] = {0, 0, 0};
            long dr, dg, db, d;

            if (j < nd) { e[0] = dst[j][0]; e[1] = dst[j][1]; e[2] = dst[j][2]; }
            dr = (long)e[0] - t[0]; dg = (long)e[1] - t[1]; db = (long)e[2] - t[2];
            d = dr * dr + dg * dg + db * db;
            if (d < bd) {
                bd = d;
                best = j;
            }
        }
        out[i] = (uint8_t)best;
    }
}

/* ---- reading and writing a DC's target --------------------------------------------------------------------------------------------- */
/* The RGB pixels of a rectangle of the DC's target, clipped to the target; returns NULL (and size 0) when nothing is left. */
static uint8_t *get_region_raw(DC *dc, int x0, int y0, int x1, int y1, int *rw, int *rh, int *rx, int *ry)
{
    int w, h;
    uint8_t *out;

    target_size(dc, &w, &h);
    x0 = x0 < 0 ? 0 : x0;
    y0 = y0 < 0 ? 0 : y0;
    x1 = x1 > w ? w : x1;
    y1 = y1 > h ? h : y1;
    if (rx) *rx = x0;
    if (ry) *ry = y0;
    *rw = *rh = 0;
    if (x1 <= x0 || y1 <= y0)
        return NULL;
    *rw = x1 - x0;
    *rh = y1 - y0;
    if (dc->memory) {
        Bitmap *b = dc->bitmap;

        if (!b)
            return NULL;
        if (b->ddb) {
            int x, y;

            out = malloc((size_t)*rw * (size_t)*rh * 3);
            init_gdi();
            for (y = 0; y < *rh; y++)
                for (x = 0; x < *rw; x++) {
                    int k = b->idx[(size_t)(y0 + y) * (size_t)b->w + (size_t)(x0 + x)];
                    uint8_t *o = out + 3 * ((size_t)y * (size_t)*rw + (size_t)x);

                    if (k < system_palette->n) {
                        o[0] = system_palette->e[k][0]; o[1] = system_palette->e[k][1]; o[2] = system_palette->e[k][2];
                    } else
                        o[0] = o[1] = o[2] = 0;
                }
            return out;
        }
        return read_dib_rgb(b, x0, y0, x1, y1, rw, rh);
    }
    {
        Window *win = wm_window(dc->hwnd);

        if (!win || !win->surface)
            return NULL;
        out = malloc((size_t)*rw * (size_t)*rh * 3);
        surface_rgb(win->surface, x0, y0, x1, y1, out);
        return out;
    }
}

/* The pixels of a rectangle of the device context as RGB; a rectangle that holds none (or a device context with nothing selected) gives NULL and size 0. */
uint8_t *get_region(DC *dc, int x0, int y0, int x1, int y1, int *rw, int *rh, int *rx, int *ry)
{
    uint8_t *out = get_region_raw(dc, x0, y0, x1, y1, rw, rh, rx, ry);

    if (!out)
        *rw = *rh = 0;
    return out;
}

/* Clip a (x, y, w, h) rectangle of a source array to the DC's clip rectangle and its target; returns 0 if nothing remains. Gives the source offsets. */
static int clip_to_dc(const DC *dc, int *x0, int *y0, int w, int h, int *sx0, int *sy0, int *ex, int *ey)
{
    int tw, th, cx0 = *x0, cy0 = *y0;

    *sx0 = *sy0 = 0;
    *ex = w;
    *ey = h;
    if (dc->has_clip) {
        int nx0 = *x0 > dc->clip[0] ? *x0 : dc->clip[0], ny0 = *y0 > dc->clip[1] ? *y0 : dc->clip[1];
        int nx1 = *x0 + w < dc->clip[2] ? *x0 + w : dc->clip[2], ny1 = *y0 + h < dc->clip[3] ? *y0 + h : dc->clip[3];

        if (nx1 <= nx0 || ny1 <= ny0)
            return 0;
        *sx0 = nx0 - *x0;
        *sy0 = ny0 - *y0;
        *ex = nx1 - *x0;
        *ey = ny1 - *y0;
        cx0 = nx0;
        cy0 = ny0;
    }
    target_size(dc, &tw, &th);
    {
        int a = cx0 < 0 ? -cx0 : 0, b = cy0 < 0 ? -cy0 : 0, e1 = tw - *x0, e2 = th - *y0;

        if (*sx0 < a + (cx0 - *x0)) *sx0 = a + (cx0 - *x0);
        if (*sy0 < b + (cy0 - *y0)) *sy0 = b + (cy0 - *y0);
        if (*ex > e1) *ex = e1;
        if (*ey > e2) *ey = e2;
    }
    if (*ex <= *sx0 || *ey <= *sy0)
        return 0;
    return 1;
}

/* Write an RGB rectangle to the DC's target, honouring its clip rectangle. */
void put_region(DC *dc, int x0, int y0, const uint8_t *rgb, int w, int h) { put_region_masked(dc, x0, y0, rgb, w, h, NULL); }

/* As put_region, but with a mask (w*h, nonzero = draw this pixel) for a window surface; a memory DC takes the whole rectangle. */
void put_region_masked(DC *dc, int x0, int y0, const uint8_t *rgb, int w, int h, const uint8_t *mask)
{
    int sx0, sy0, ex, ey, y;

    if (!rgb || w <= 0 || h <= 0)
        return;
    if (!clip_to_dc(dc, &x0, &y0, w, h, &sx0, &sy0, &ex, &ey))
        return;
    {
        int cw = ex - sx0, ch = ey - sy0, ox = x0 + sx0, oy = y0 + sy0;

        if (dc->memory) {
            Bitmap *b = dc->bitmap;

            if (!b)
                return;
            if (b->ddb) {
                for (y = 0; y < ch; y++)
                    quantize(rgb + 3 * ((size_t)(sy0 + y) * (size_t)w + (size_t)sx0), cw, b->idx + (size_t)(oy + y) * (size_t)b->w + (size_t)ox);
            } else {
                uint8_t *tmp = malloc((size_t)cw * (size_t)ch * 3);

                for (y = 0; y < ch; y++)
                    memcpy(tmp + (size_t)y * (size_t)cw * 3, rgb + 3 * ((size_t)(sy0 + y) * (size_t)w + (size_t)sx0), (size_t)cw * 3);
                write_dib_rgb(b, ox, oy, tmp, cw, ch);
                free(tmp);
            }
        } else {
            Window *win = wm_window(dc->hwnd);
            Surface *s = win ? win->surface : NULL;

            if (!s)
                return;
            if (mask) {                  /* only the pixels the mask names are drawn (text over a see-through window: the rest must stay untouched) */
                for (y = 0; y < ch; y++) {
                    size_t di = (size_t)(oy + y) * (size_t)s->w + (size_t)ox, mi = (size_t)(sy0 + y) * (size_t)w + (size_t)sx0;
                    int x;

                    for (x = 0; x < cw; x++) {
                        if (!mask[mi + (size_t)x])
                            continue;
                        memcpy(s->rgb + 3 * (di + (size_t)x), rgb + 3 * (mi + (size_t)x), 3);
                        s->direct[di + (size_t)x] = 1;
                        s->touched[di + (size_t)x] = 1;
                    }
                }
                wm_dirty = 1;
                return;
            }
            for (y = 0; y < ch; y++) {
                size_t di = (size_t)(oy + y) * (size_t)s->w + (size_t)ox;

                memcpy(s->rgb + 3 * di, rgb + 3 * ((size_t)(sy0 + y) * (size_t)w + (size_t)sx0), (size_t)cw * 3);
                memset(s->direct + di, 1, (size_t)cw);
                memset(s->touched + di, 1, (size_t)cw);
            }
            wm_dirty = 1;
        }
    }
}

static uint8_t *system_to_dib_lut(const Bitmap *b)
{
    static uint8_t lut[256];
    int i;

    if (b->idxmap) {
        for (i = 0; i < 256; i++)
            lut[i] = (uint8_t)i;
        return lut;
    }
    {
        uint8_t sys[256][3];

        init_gdi();
        for (i = 0; i < 256; i++) {
            sys[i][0] = system_palette->e[i < system_palette->n ? i : 0][0] * (i < system_palette->n);
            sys[i][1] = system_palette->e[i < system_palette->n ? i : 0][1] * (i < system_palette->n);
            sys[i][2] = system_palette->e[i < system_palette->n ? i : 0][2] * (i < system_palette->n);
        }
        dib_to_dib_lut((const uint8_t (*)[3])sys, 256, b->palette, b->npalette, lut);
    }
    return lut;
}

/* Write palette indices (system-palette space) to a window surface, a device bitmap or an 8-bit DIB. */
void put_indices(DC *dc, int x0, int y0, const uint8_t *idx, int w, int h)
{
    int sx0, sy0, ex, ey, y;

    if (!idx || w <= 0 || h <= 0)
        return;
    if (!clip_to_dc(dc, &x0, &y0, w, h, &sx0, &sy0, &ex, &ey))
        return;
    {
        int cw = ex - sx0, ch = ey - sy0, ox = x0 + sx0, oy = y0 + sy0;

        if (dc->memory) {
            Bitmap *b = dc->bitmap;

            if (!b)
                return;
            if (b->ddb) {
                for (y = 0; y < ch; y++)
                    memcpy(b->idx + (size_t)(oy + y) * (size_t)b->w + (size_t)ox, idx + (size_t)(sy0 + y) * (size_t)w + (size_t)sx0, (size_t)cw);
            } else if (b->bpp == 8) {
                const uint8_t *lut = system_to_dib_lut(b);
                uint8_t *tmp = malloc((size_t)cw * (size_t)ch);
                int x;

                for (y = 0; y < ch; y++)
                    for (x = 0; x < cw; x++)
                        tmp[(size_t)y * (size_t)cw + (size_t)x] = lut[idx[(size_t)(sy0 + y) * (size_t)w + (size_t)(sx0 + x)]];
                write_dib_indices(b, ox, oy, tmp, cw, ch);
                free(tmp);
            }
            return;
        }
        {
            Window *win = wm_window(dc->hwnd);
            Surface *s = win ? win->surface : NULL;

            if (!s)
                return;
            for (y = 0; y < ch; y++) {
                size_t di = (size_t)(oy + y) * (size_t)s->w + (size_t)ox;

                memcpy(s->idx + di, idx + (size_t)(sy0 + y) * (size_t)w + (size_t)sx0, (size_t)cw);
                memset(s->direct + di, 0, (size_t)cw);
                memset(s->touched + di, 1, (size_t)cw);
            }
            wm_dirty = 1;
        }
    }
}

/* A 1-bpp bitmap's rectangle as indices, the way Windows converts one for a colour destination: 0 bits take the destination DC's text colour,
 * 1 bits its background colour. */
static uint8_t *mono_indices(const DC *dst, const Bitmap *b, int x0, int y0, int x1, int y1)
{
    int w = x1 - x0, h = y1 - y0, x, y;
    uint8_t one = (uint8_t)color_index(dst, dst->bkcolor), zero = (uint8_t)color_index(dst, dst->textcolor);
    uint8_t *out = malloc((size_t)w * (size_t)h);

    for (y = 0; y < h; y++)
        for (x = 0; x < w; x++)
            out[(size_t)y * (size_t)w + (size_t)x] = b->mono[(size_t)(y0 + y) * (size_t)b->w + (size_t)(x0 + x)] ? one : zero;
    return out;
}

/* Palette indices (system-palette space) of a rectangle of a DC's target; NULL when nothing is readable without a colour conversion
 * (24-bit DIBs, which go through RGB). */
uint8_t *dc_indices(DC *dc, int x0, int y0, int x1, int y1, DC *mono_dc, int *rx, int *ry, int *rw, int *rh)
{
    int w, h, y;
    uint8_t *out;

    target_size(dc, &w, &h);
    x0 = x0 < 0 ? 0 : x0;
    y0 = y0 < 0 ? 0 : y0;
    x1 = x1 > w ? w : x1;
    y1 = y1 > h ? h : y1;
    *rx = x0;
    *ry = y0;
    *rw = *rh = 0;
    if (x1 <= x0 || y1 <= y0) {
        return malloc(1);           /* empty but readable */
    }
    *rw = x1 - x0;
    *rh = y1 - y0;
    if (dc->memory) {
        Bitmap *b = dc->bitmap;

        if (!b)
            return NULL;
        if (b->ddb) {
            if (b->mono && mono_dc)
                return mono_indices(mono_dc, b, x0, y0, x1, y1);
            out = malloc((size_t)*rw * (size_t)*rh);
            for (y = 0; y < *rh; y++)
                memcpy(out + (size_t)y * (size_t)*rw, b->idx + (size_t)(y0 + y) * (size_t)b->w + (size_t)x0, (size_t)*rw);
            return out;
        }
        if (b->bpp == 8) {
            uint8_t lut[256], *raw = read_dib_indices(b, x0, y0, x1, y1);
            size_t i;

            if (b->idxmap)
                memcpy(lut, b->idxmap, 256);
            else
                dib_to_system_lut(b->palette, b->npalette, lut);
            for (i = 0; i < (size_t)*rw * (size_t)*rh; i++)
                raw[i] = lut[raw[i]];
            return raw;
        }
        return NULL;
    }
    {
        Window *win = wm_window(dc->hwnd);
        Surface *s = win ? win->surface : NULL;
        int x;

        if (!s)
            return NULL;
        for (y = y0; y < y1; y++)
            for (x = x0; x < x1; x++)
                if (s->direct[(size_t)y * (size_t)s->w + (size_t)x])
                    return NULL;
        out = malloc((size_t)*rw * (size_t)*rh);
        for (y = 0; y < *rh; y++)
            memcpy(out + (size_t)y * (size_t)*rw, s->idx + (size_t)(y0 + y) * (size_t)s->w + (size_t)x0, (size_t)*rw);
        return out;
    }
}

/* ---- logical to device -------------------------------------------------------------------------------------------------------------- */
static int round_half_even(double v) { return (int)nearbyint(v); }    /* the default rounding mode is ties-to-even, like Python's round */

int lx(const DC *dc, int x) { return round_half_even((x - dc->wo[0]) * dc->sx); }
int ly(const DC *dc, int y) { return round_half_even((y - dc->wo[1]) * dc->sy); }

void dev_rect(const DC *dc, int x, int y, int w, int h, int out[4])
{
    int x0 = lx(dc, x), y0 = ly(dc, y);

    out[0] = x0;
    out[1] = y0;
    out[2] = lx(dc, x + w) - x0;
    out[3] = ly(dc, y + h) - y0;
}

void fill_rect_rgb(DC *dc, int x0, int y0, int w, int h, const uint8_t color[3])
{
    uint8_t *buf;
    size_t i, n;

    if (w <= 0 || h <= 0)
        return;
    n = (size_t)w * (size_t)h;
    buf = malloc(n * 3);
    for (i = 0; i < n; i++) {
        buf[3 * i] = color[0]; buf[3 * i + 1] = color[1]; buf[3 * i + 2] = color[2];
    }
    put_region(dc, x0 + dc->org[0], y0 + dc->org[1], buf, w, h);
    free(buf);
}

void fill_rect_logical(DC *dc, int x0, int y0, int x1, int y1, const uint8_t color[3])
{
    int r[4];

    dev_rect(dc, x0, y0, x1 - x0, y1 - y0, r);
    fill_rect_rgb(dc, r[0], r[1], r[2], r[3], color);
}

/* ---- stock and created objects --------------------------------------------------------------------------------------------------- */
static uint32_t stock[21];

uint32_t stock_object(int which)
{
    static const uint8_t brush_rgb[5][3] = {{255, 255, 255}, {192, 192, 192}, {128, 128, 128}, {64, 64, 64}, {0, 0, 0}};

    init_gdi();
    if (which < 0 || which > 20)
        which = 0;
    if (!stock[which]) {
        if (which <= 5) {
            Brush *b = calloc(1, sizeof(*b));

            if (which < 5) {
                b->solid = 1;
                memcpy(b->rgb, brush_rgb[which], 3);
            }
            stock[which] = obj_new(O_BRUSH, b);
        } else if (which <= 8) {
            Pen *p = calloc(1, sizeof(*p));

            p->width = 1;
            if (which == 6) { p->solid = 1; p->rgb[0] = p->rgb[1] = p->rgb[2] = 255; }
            else if (which == 7) p->solid = 1;
            stock[which] = obj_new(O_PEN, p);
        } else if (which == 15) {
            Palette *pal = calloc(1, sizeof(*pal));
            int i;

            pal->n = 256;
            for (i = 0; i < 256; i++)
                pal->e[i][0] = pal->e[i][1] = pal->e[i][2] = (uint8_t)i;
            stock[which] = obj_new(O_PALETTE, pal);
        } else {
            Font *f = calloc(1, sizeof(*f));

            snprintf(f->face, sizeof(f->face), "Arial");
            f->size = (which == 10 || which == 11) ? 12 : 13;
            f->weight = 400;
            f->height = f->size;
            stock[which] = obj_new(O_FONT, f);
        }
    }
    return stock[which];
}

static uint32_t GetStockObject(const uint32_t *a) { return stock_object((int)a[0]); }

static uint32_t CreateSolidBrush(const uint32_t *a)
{
    Brush *b = calloc(1, sizeof(*b));

    b->solid = 1;
    colorref_rgb(NULL, a[0], b->rgb);
    b->cref = a[0];
    b->rel = ((a[0] >> 24) & 0xFF) == 1;
    return obj_new(O_BRUSH, b);
}

static uint32_t CreateBrushIndirect(const uint32_t *a)
{
    Brush *b = calloc(1, sizeof(*b));
    uint32_t style = RD32(a[0]), color = RD32(a[0] + 4), hatch = RD32(a[0] + 8);

    if (style == 3) {                       /* BS_PATTERN: `hatch` is a bitmap handle */
        b->pattern = hatch;
        return obj_new(O_BRUSH, b);
    }
    if (style != 1) {
        b->solid = 1;
        colorref_rgb(NULL, color, b->rgb);
        b->cref = color;
        b->rel = ((color >> 24) & 0xFF) == 1;
    }
    return obj_new(O_BRUSH, b);
}

static uint32_t CreatePatternBrush(const uint32_t *a)
{
    Brush *b = calloc(1, sizeof(*b));

    b->pattern = a[0];
    return obj_new(O_BRUSH, b);
}

static uint32_t CreateHatchBrush(const uint32_t *a)
{
    Brush *b = calloc(1, sizeof(*b));

    b->solid = 1;
    colorref_rgb(NULL, a[1], b->rgb);
    b->cref = a[1];
    b->rel = ((a[1] >> 24) & 0xFF) == 1;
    return obj_new(O_BRUSH, b);
}

static uint32_t CreatePen(const uint32_t *a)
{
    Pen *p = calloc(1, sizeof(*p));

    p->solid = a[0] != 5;
    colorref_rgb(NULL, a[2], p->rgb);
    p->cref = a[2];
    p->rel = ((a[2] >> 24) & 0xFF) == 1;
    p->width = (int32_t)a[1] > 1 ? (int)a[1] : 1;
    return obj_new(O_PEN, p);
}

static uint32_t CreatePenIndirect(const uint32_t *a)
{
    Pen *p = calloc(1, sizeof(*p));
    uint32_t style = RD32(a[0]);
    int32_t width = (int32_t)RD32(a[0] + 4);

    p->solid = style != 5;
    colorref_rgb(NULL, RD32(a[0] + 12), p->rgb);
    p->cref = RD32(a[0] + 12);
    p->rel = ((p->cref >> 24) & 0xFF) == 1;
    p->width = width > 1 ? width : 1;
    return obj_new(O_PEN, p);
}

static uint32_t make_font(const char *face, int32_t h, uint32_t weight, int italic)
{
    Font *f = calloc(1, sizeof(*f));

    snprintf(f->face, sizeof(f->face), "%s", face);
    f->size = h < 0 ? -h : h;
    if (!f->size)
        f->size = 13;
    f->weight = weight ? (int)weight : 400;
    f->italic = italic;
    f->height = h;
    return obj_new(O_FONT, f);
}

/* The font of a DS_SETFONT dialog: its face at -MulDiv(points, 96, 72) pixels, normal weight. */
uint32_t gdi_dialog_font(const char *face, int pt)
{
    return make_font(face, -ui_pixel_size(pt), 400, 0);
}

static uint32_t CreateFontIndirectA(const uint32_t *a)
{
    return make_font(P(a[0] + 28), (int32_t)RD32(a[0]), RD32(a[0] + 16), G[a[0] + 20] != 0);
}

static uint32_t CreateFontA(const uint32_t *a)
{
    return make_font(P(a[13]), (int32_t)a[0], a[4], (a[5] & 0xFF) != 0);
}

/* ---- palettes ------------------------------------------------------------------------------------------------------------------------- */
static uint32_t CreatePalette(const uint32_t *a)
{
    Palette *p = calloc(1, sizeof(*p));
    int n = RD16(a[0] + 2), i;

    p->n = n > 256 ? 256 : n;
    for (i = 0; i < p->n; i++) {
        p->e[i][0] = G[a[0] + 4 + 4 * (uint32_t)i];
        p->e[i][1] = G[a[0] + 5 + 4 * (uint32_t)i];
        p->e[i][2] = G[a[0] + 6 + 4 * (uint32_t)i];
    }
    return obj_new(O_PALETTE, p);
}

static uint32_t SetPaletteEntries(const uint32_t *a)
{
    Palette *p = obj_get(a[0], O_PALETTE);
    uint32_t i;

    if (!p || !p->n)
        return 0;
    for (i = 0; i < a[2]; i++) {
        uint32_t k = (a[1] + i) % (uint32_t)p->n;

        p->e[k][0] = G[a[3] + 4 * i]; p->e[k][1] = G[a[3] + 4 * i + 1]; p->e[k][2] = G[a[3] + 4 * i + 2];
    }
    palette_generation++;
    return a[2];
}

static uint32_t GetPaletteEntries(const uint32_t *a)
{
    Palette *p = obj_get(a[0], O_PALETTE);
    uint32_t i;

    if (!p || !p->n)
        return 0;
    for (i = 0; i < a[2]; i++) {
        uint32_t k = (a[1] + i) % (uint32_t)p->n;

        G[a[3] + 4 * i] = p->e[k][0]; G[a[3] + 4 * i + 1] = p->e[k][1]; G[a[3] + 4 * i + 2] = p->e[k][2]; G[a[3] + 4 * i + 3] = 0;
    }
    return a[2];
}

/* The palette index closest to a colour (squared distance in RGB); the first of equally close ones wins. */
static uint32_t GetNearestPaletteIndex(const uint32_t *a)
{
    Palette *p = obj_get(a[0], O_PALETTE);
    int r = a[1] & 255, g = (a[1] >> 8) & 255, b = (a[1] >> 16) & 255, i, best = 0, bestd = 1 << 30;

    if (!p || !p->n)
        return 0xFFFFFFFFu;
    for (i = 0; i < p->n; i++) {
        int dr = p->e[i][0] - r, dg = p->e[i][1] - g, db = p->e[i][2] - b, d = dr * dr + dg * dg + db * db;

        if (d < bestd) {
            bestd = d;
            best = i;
        }
    }
    return (uint32_t)best;
}

static uint32_t SelectPalette(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);
    Palette *p = obj_get(a[1], O_PALETTE);

    if (!dc || !p)
        return 0;
    dc->palette = p;
    dc_resolve_tools(dc);                       /* a pen or brush made from a palette index means that entry of this palette */
    return 1;
}

static int is_desktop_window(uint32_t hwnd) { return hwnd == wm_desktop_hwnd(); }

/* Only the application's own windows set the hardware palette. A memory DC, or the desktop's (GetDC(NULL), which the game uses to draw card
 * art with a palette of its own), realizes in the background: Windows maps it onto the colours already there. */
static uint32_t RealizePalette(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);

    if (dc && dc->palette) {
        if ((!dc->memory && !is_desktop_window(dc->hwnd)) || !system_palette_set) {
            system_palette = dc->palette;               /* shared: AnimatePalette on it shows at once */
            system_palette_set = 1;
            palette_generation++;
        }
        return (uint32_t)dc->palette->n;
    }
    return 0;
}

static uint32_t AnimatePalette(const uint32_t *a)
{
    Palette *p = obj_get(a[0], O_PALETTE);
    uint32_t i;

    if (!p || !p->n)
        return 0;
    for (i = 0; i < a[2]; i++) {
        uint32_t k = (a[1] + i) % (uint32_t)p->n;

        p->e[k][0] = G[a[3] + 4 * i]; p->e[k][1] = G[a[3] + 4 * i + 1]; p->e[k][2] = G[a[3] + 4 * i + 2];
    }
    palette_generation++;
    return 1;
}

/* ---- fonts: the game's own TrueType files ----------------------------------------------------------------------------------------------- */
extern int fonts_add_file(const char *host_path);

static uint32_t AddFontResourceA(const uint32_t *a)
{
    char host[1200];

    if (!paths_host(P(a[0]), 0, host, sizeof(host)))
        return 0;
    return fonts_add_file(host) ? 1 : 0;
}

/* ---- selecting, deleting ------------------------------------------------------------------------------------------------------------ */
static uint32_t default_bitmap_handle(void)
{
    static uint32_t h;

    if (!h) {
        Bitmap *b = calloc(1, sizeof(*b));

        b->ddb = 1; b->w = b->h = 1; b->bpp = 1;
        b->idx = calloc(1, 1);
        h = obj_new(O_BITMAP, b);
    }
    return h;
}

static uint32_t SelectObject(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);
    Obj *o = slot(a[1]);

    if (!dc || !o)
        return 0;
    switch (o->kind) {
    case O_BITMAP: {
        uint32_t old = dc->bitmap ? 0 : default_bitmap_handle();
        extern uint32_t bitmap_handle_of(const Bitmap *b);

        if (dc->bitmap)
            old = bitmap_handle_of(dc->bitmap);
        dc->bitmap = o->p;
        return old ? old : default_bitmap_handle();
    }
    case O_PEN: { Pen *old = &dc->pen; (void)old; dc->pen = *(Pen *)o->p; dc_resolve_tools(dc); return stock_object(7); }
    case O_BRUSH: dc->brush = *(Brush *)o->p; dc_resolve_tools(dc); return stock_object(0);
    case O_FONT: dc->font = o->p; return stock_object(13);
    default: return 0;
    }
}

static uint32_t DeleteObject(const uint32_t *a) { obj_free(a[0]); return 1; }
static uint32_t DeleteDC(const uint32_t *a) { gdi_release_dc(a[0]); return 1; }

/* A control asked its parent for its colours (WM_CTLCOLOR...): a fresh device context to hand over, and what the answer set on it and which brush it returned. */
uint32_t gdi_color_query_dc(void)
{
    uint32_t h = dc_new(0, 0);
    DC *d = dc_of(h);

    d->textcolor = 0;
    d->bkcolor = 0xC0C0C0;
    return h;
}

/* Reads the answer: the text colour, whether the background is transparent (SetBkMode(TRANSPARENT), or a null brush), the background colour (the returned brush's
 * when it is a solid one, else the DC's) and whether the parent changed anything at all (a brush returned or a colour set). */
void gdi_color_query_result(uint32_t hdc, uint32_t brush, uint8_t fg[3], uint8_t bg[3], int *transparent, int *has_bg)
{
    DC *d = dc_of(hdc);
    Brush *b = brush ? obj_get(brush, O_BRUSH) : NULL;

    colorref_rgb(d, d->textcolor, fg);
    *transparent = d->bkmode == 1;
    *has_bg = 0;
    colorref_rgb(d, d->bkcolor, bg);
    if (b) {
        if (b->solid) {
            brush_color(d, b, bg);
            *has_bg = 1;
        } else if (!b->pattern)
            *transparent = 1;                                 /* NULL_BRUSH: the control leaves what is behind it */
    }
    obj_free(hdc);
}

static uint32_t CreateCompatibleDC(const uint32_t *a)
{
    uint32_t h = dc_new(1, 0);

    (void)a;
    dc_of(h)->bitmap = obj_get(default_bitmap_handle(), O_BITMAP);
    return h;
}

static Bitmap *new_ddb(int w, int h, int bpp)
{
    Bitmap *b = calloc(1, sizeof(*b));

    b->ddb = 1;
    b->w = w;
    b->h = h;
    b->bpp = bpp;
    b->idx = calloc((size_t)w * (size_t)h, 1);
    return b;
}

static uint32_t CreateDCA(const uint32_t *a)
{
    uint32_t h = dc_new(1, 0);

    (void)a;
    dc_of(h)->bitmap = new_ddb(SCREEN_W, SCREEN_H, 8);
    return h;
}

static uint32_t CreateCompatibleBitmap(const uint32_t *a)
{
    return obj_new(O_BITMAP, new_ddb(a[1] ? (int)a[1] : 1, a[2] ? (int)a[2] : 1, 8));
}

static uint32_t CreateBitmap(const uint32_t *a)
{
    int w = (int32_t)a[0] > 0 ? (int)a[0] : 1, h = (int32_t)a[1] > 0 ? (int)a[1] : 1;
    Bitmap *b = new_ddb(w, h, a[3] ? (int)a[3] : 1);

    if ((a[2] ? a[2] : 1) * (a[3] ? a[3] : 1) == 1) {
        int y, x, stride = ((w + 15) / 16) * 2;

        b->mono = calloc((size_t)w * (size_t)h, 1);
        if (a[4])                                   /* scan lines are padded to 16 bits, most significant bit first */
            for (y = 0; y < h; y++)
                for (x = 0; x < w; x++)
                    b->mono[(size_t)y * (size_t)w + (size_t)x] = (G[a[4] + (uint32_t)(y * stride + x / 8)] >> (7 - x % 8)) & 1;
    }
    return obj_new(O_BITMAP, b);
}

uint32_t bitmap_handle_of(const Bitmap *b)
{
    int i;

    for (i = 0; i < nobjs; i++)
        if (objs[i].kind == O_BITMAP && objs[i].p == b)
            return OBJ_BASE + 4u * (uint32_t)i;
    return 0;
}

/* (width, height, topdown, bpp, palette entries, DIB_PAL_COLORS indices, header size) of a BITMAPINFO at guest address p. With usage == 1 the colour
 * table is 16-bit indices into the logical palette. */
typedef struct DibInfo { int w, h, topdown, bpp, ncol, pal_colors, hdr; uint8_t pal[256][3]; uint16_t words[256]; } DibInfo;

static void parse_bitmapinfo(uint32_t p, uint32_t usage, DibInfo *out)
{
    uint32_t size = RD32(p);
    int32_t w = (int32_t)RD32(p + 4), h = (int32_t)RD32(p + 8);
    int bpp = RD16(p + 14), i;
    uint32_t used = RD32(p + 32);
    int ncol = (int)(used ? used : (bpp <= 8 ? (1u << bpp) : 0));

    memset(out, 0, sizeof(*out));
    out->w = w;
    out->h = h < 0 ? -h : h;
    out->topdown = h < 0;
    out->bpp = bpp;
    if (ncol > 256)
        ncol = 256;
    out->ncol = ncol;
    if (usage == 1) {
        out->pal_colors = 1;
        for (i = 0; i < ncol; i++)
            out->words[i] = RD16(p + size + 2 * (uint32_t)i);
        out->hdr = (int)size + 2 * ncol;
        return;
    }
    for (i = 0; i < ncol; i++) {
        out->pal[i][0] = G[p + size + 4 * (uint32_t)i + 2];
        out->pal[i][1] = G[p + size + 4 * (uint32_t)i + 1];
        out->pal[i][2] = G[p + size + 4 * (uint32_t)i];
    }
    out->hdr = (int)size + 4 * ncol;
}

static uint32_t CreateDIBSection(const uint32_t *a)
{
    DibInfo di;
    Bitmap *b = calloc(1, sizeof(*b));
    int stride, i;

    parse_bitmapinfo(a[1], a[2], &di);
    b->w = di.w;
    b->h = di.h;
    b->bpp = di.bpp;
    b->topdown = di.topdown;
    for (i = 0; i < 256; i++)
        b->palette[i][0] = b->palette[i][1] = b->palette[i][2] = (uint8_t)i;
    b->npalette = 256;
    if (di.pal_colors) {                                   /* DIB_PAL_COLORS */
        DC *dc = dc_of(a[0]);

        b->idxmap = malloc(256);
        for (i = 0; i < 256; i++)
            b->idxmap[i] = (uint8_t)i;
        if (di.ncol)
            for (i = 0; i < di.ncol && i < 256; i++)
                b->idxmap[i] = (uint8_t)(di.words[i] & 0xFF);
        if (dc && dc->palette) {
            b->npalette = dc->palette->n;
            memcpy(b->palette, dc->palette->e, sizeof(b->palette));
        }
    } else if (di.ncol) {
        b->npalette = di.ncol;
        memcpy(b->palette, di.pal, sizeof(b->palette));
    }
    dib_stride(b, &stride);
    b->bits = a[4] ? k32_mapping_view(a[4], a[5]) : 0;       /* made from a file mapping (hSection): the pixels are the mapping's memory, shared with whoever has it */
    if (!b->bits) {
        b->bits = heap_alloc((uint32_t)(stride * b->h));
        guest_zero(b->bits, (uint32_t)(stride * b->h));
    }
    if (a[3])
        WR32(a[3], b->bits);
    return obj_new(O_BITMAP, b);
}

static uint32_t SetDIBColorTable(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);
    Bitmap *b = dc ? dc->bitmap : NULL;
    uint32_t i;

    if (!b || b->ddb)
        return 0;
    for (i = 0; i < a[2]; i++) {
        uint32_t k = (a[1] + i) % 256;

        b->palette[k][2] = G[a[3] + 4 * i]; b->palette[k][1] = G[a[3] + 4 * i + 1]; b->palette[k][0] = G[a[3] + 4 * i + 2];
        if ((int)k >= b->npalette)
            b->npalette = (int)k + 1;
    }
    return a[2];
}

/* A scan-line buffer at `bits` of `lines` rows of a DIB described by di, as RGB (top row first of the buffer's own order). */
static uint8_t *buffer_rgb(const DibInfo *di, uint32_t bits, int lines, int *ok)
{
    int stride = ((di->w * di->bpp + 31) / 32) * 4, y, x;
    uint8_t *out = malloc((size_t)lines * (size_t)di->w * 3);

    *ok = 1;
    for (y = 0; y < lines; y++)
        for (x = 0; x < di->w; x++) {
            const uint8_t *row = G + bits + (size_t)y * (size_t)stride;
            uint8_t *o = out + 3 * ((size_t)y * (size_t)di->w + (size_t)x);

            if (di->bpp == 8) {
                const uint8_t *c = row[x] < di->ncol ? di->pal[row[x]] : NULL;

                if (!di->ncol) {            /* no colour table: a grey ramp */
                    o[0] = o[1] = o[2] = row[x];
                } else if (c) {
                    o[0] = c[0]; o[1] = c[1]; o[2] = c[2];
                } else
                    o[0] = o[1] = o[2] = 0;
            } else if (di->bpp == 24) {
                o[0] = row[x * 3 + 2]; o[1] = row[x * 3 + 1]; o[2] = row[x * 3];
            } else {
                *ok = 0;
                free(out);
                return NULL;
            }
        }
    return out;
}

static uint32_t SetDIBits(const uint32_t *a)
{
    Bitmap *bmp = obj_get(a[1], O_BITMAP);
    DibInfo di;
    uint8_t *rgb, *flipped;
    int ok, y0, lines = (int)a[3], hh, y, w;

    if (!bmp)
        return 0;
    parse_bitmapinfo(a[6], 0, &di);
    rgb = buffer_rgb(&di, a[4], lines, &ok);
    if (!ok)
        return 0;
    w = di.w;
    flipped = malloc((size_t)lines * (size_t)w * 3);
    for (y = 0; y < lines; y++)                          /* bottom-up DIBs list their last line first */
        memcpy(flipped + (size_t)y * (size_t)w * 3, rgb + (size_t)(di.topdown ? y : lines - 1 - y) * (size_t)w * 3, (size_t)w * 3);
    free(rgb);
    y0 = di.topdown ? (int)a[2] : (di.h - (int)a[2] - lines > 0 ? di.h - (int)a[2] - lines : 0);
    if (bmp->ddb) {
        int cw = w < bmp->w ? w : bmp->w;

        hh = lines < bmp->h - y0 ? lines : bmp->h - y0;
        for (y = 0; y < hh; y++)
            quantize(flipped + (size_t)y * (size_t)w * 3, cw, bmp->idx + (size_t)(y0 + y) * (size_t)bmp->w);
    } else
        write_dib_rgb(bmp, 0, y0, flipped, w, lines);
    free(flipped);
    return a[3];
}

static uint32_t GetObjectA(const uint32_t *a)
{
    Bitmap *b = obj_get(a[0], O_BITMAP);

    if (b) {
        int stride;

        if (a[1] < 24 || !a[2])
            return 24;
        if (b->ddb)
            stride = ((b->w * 8 + 31) / 32) * 4;
        else
            dib_stride(b, &stride);
        WR32(a[2], 0); WR32(a[2] + 4, (uint32_t)b->w); WR32(a[2] + 8, (uint32_t)b->h); WR32(a[2] + 12, (uint32_t)stride);
        WR16(a[2] + 16, 1); WR16(a[2] + 18, (uint16_t)b->bpp); WR32(a[2] + 20, b->bits);
        return 24;
    }
    {
        Font *f = obj_get(a[0], O_FONT);

        if (f) {                                                   /* a LOGFONT: what CreateFontIndirectA would be given to make this one */
            if (a[1] < 60 || !a[2])
                return 60;
            guest_zero(a[2], 60);
            WR32(a[2], (uint32_t)f->height);
            WR32(a[2] + 16, (uint32_t)f->weight);
            G[a[2] + 20] = (uint8_t)f->italic;
            G[a[2] + 23] = 1;                                      /* DEFAULT_CHARSET */
            snprintf((char *)G + a[2] + 28, 32, "%s", f->face);
            return 60;
        }
    }
    /* Not an object (a control that has no font of its own gives a null handle): the structure is left as the caller had it on Windows, which is
     * whatever was on its stack; here it is zeroes, which makes the font the caller builds from it the default one. */
    if (a[2] && a[1] && a[1] < 4096)
        guest_zero(a[2], a[1]);
    return 0;
}

/* ---- DC state ---------------------------------------------------------------------------------------------------------------------- */
static uint32_t SetTextColor(const uint32_t *a) { DC *d = dc_of(a[0]); uint32_t o; if (!d) return 0; o = d->textcolor; d->textcolor = a[1]; return o; }
static uint32_t SetBkColor(const uint32_t *a) { DC *d = dc_of(a[0]); uint32_t o; if (!d) return 0; o = d->bkcolor; d->bkcolor = a[1]; return o; }
static uint32_t SetBkMode(const uint32_t *a) { DC *d = dc_of(a[0]); uint32_t o; if (!d) return 0; o = (uint32_t)d->bkmode; d->bkmode = (int)a[1]; return o; }
static uint32_t SetTextAlign(const uint32_t *a) { DC *d = dc_of(a[0]); uint32_t o; if (!d) return 0; o = (uint32_t)d->textalign; d->textalign = (int)a[1]; return o; }
static uint32_t GetTextAlign(const uint32_t *a) { DC *d = dc_of(a[0]); return d ? (uint32_t)d->textalign : 0; }
static uint32_t thirteen(const uint32_t *a) { (void)a; return 13; }
static uint32_t one(const uint32_t *a) { (void)a; return 1; }
/* MM_ISOTROPIC and MM_ANISOTROPIC scale logical units by viewport extent / window extent; every other mode is 1:1 here. */
static void rescale(DC *dc)
{
    if ((dc->mm == 7 || dc->mm == 8) && dc->wext[0] && dc->wext[1]) {
        dc->sx = (double)dc->vext[0] / dc->wext[0];
        dc->sy = (double)dc->vext[1] / dc->wext[1];
        if (dc->mm == 7) {
            /* MM_ISOTROPIC: the units must be equal, so Windows shrinks the viewport extent of the axis whose scale is the bigger, in whole units (the integer quotient). The card text's mapping:
             * window 200 x 300, viewport 160 x 224: x would be 0.8 and y 0.7467, so the viewport's x becomes 224 * 200 / 300 = 149 and the scales are 149 / 200 = 0.745 and 224 / 300. (The original's
             * extents of words, which the card text lays out by, agree with 0.745: docs/notes/card-text-metrics.md.) */
            long vx = dc->vext[0], vy = dc->vext[1], wx = dc->wext[0], wy = dc->wext[1];
            long ax = vx < 0 ? -vx : vx, ay = vy < 0 ? -vy : vy, bx = wx < 0 ? -wx : wx, by = wy < 0 ? -wy : wy;

            if (ax * by > ay * bx)            /* |vx / wx| > |vy / wy| */
                vx = (vx < 0 ? -1 : 1) * (ay * bx / by);
            else
                vy = (vy < 0 ? -1 : 1) * (ax * by / bx);
            dc->sx = (double)vx / (double)wx;
            dc->sy = (double)vy / (double)wy;
        }
    } else
        dc->sx = dc->sy = 1.0;
    if (dc->sx == 0 || dc->sy == 0) {   /* an extent not set yet (the game sets the two in separate calls) */
        dc->sx = dc->sx ? dc->sx : 1.0;
        dc->sy = dc->sy ? dc->sy : 1.0;
    }
}

static uint32_t SetMapMode(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);
    int old;

    if (!dc)
        return 0;
    old = dc->mm;
    dc->mm = (int)a[1];
    if (a[1] != 7 && a[1] != 8) {
        dc->wext[0] = dc->wext[1] = dc->vext[0] = dc->vext[1] = 1;
    }
    rescale(dc);
    return (uint32_t)old;
}

static uint32_t GetMapMode(const uint32_t *a) { DC *d = dc_of(a[0]); return d ? (uint32_t)d->mm : 0; }

static uint32_t ext_setter(const uint32_t *a, int viewport)
{
    DC *dc = dc_of(a[0]);
    int *e;

    if (!dc)
        return 0;
    e = viewport ? dc->vext : dc->wext;
    if (a[3]) {
        WR32(a[3], (uint32_t)e[0]);
        WR32(a[3] + 4, (uint32_t)e[1]);
    }
    if (dc->mm == 7 || dc->mm == 8) {
        e[0] = (int32_t)a[1];
        e[1] = (int32_t)a[2];
        rescale(dc);
    }
    return 1;
}
static uint32_t SetWindowExtEx(const uint32_t *a) { return ext_setter(a, 0); }
static uint32_t SetViewportExtEx(const uint32_t *a) { return ext_setter(a, 1); }

static uint32_t SetWindowOrgEx(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);

    if (!dc)
        return 0;
    if (a[3]) {
        WR32(a[3], (uint32_t)dc->wo[0]);
        WR32(a[3] + 4, (uint32_t)dc->wo[1]);
    }
    dc->wo[0] = (int32_t)a[1];
    dc->wo[1] = (int32_t)a[2];
    return 1;
}

static uint32_t points_converter(const uint32_t *a, int to_device)
{
    DC *dc = dc_of(a[0]);
    uint32_t i;

    if (!dc)
        return 0;
    for (i = 0; i < a[2]; i++) {
        int x = (int32_t)RD32(a[1] + 8 * i), y = (int32_t)RD32(a[1] + 8 * i + 4);

        if (to_device) {
            x = lx(dc, x) + dc->org[0];
            y = ly(dc, y) + dc->org[1];
        } else {
            x = round_half_even((x - dc->org[0]) / dc->sx) + dc->wo[0];
            y = round_half_even((y - dc->org[1]) / dc->sy) + dc->wo[1];
        }
        WR32(a[1] + 8 * i, (uint32_t)x);
        WR32(a[1] + 8 * i + 4, (uint32_t)y);
    }
    return 1;
}
static uint32_t LPtoDP(const uint32_t *a) { return points_converter(a, 1); }
static uint32_t DPtoLP(const uint32_t *a) { return points_converter(a, 0); }

/* SaveDC pushes the DC's attributes (selected objects, colours, origin, clip region); RestoreDC pops: level -1 is the last one saved, a positive
 * level is that one (and every later one is dropped). */
static uint32_t SaveDC(const uint32_t *a)
{
    DC *dc = dc_of(a[0]), *copy;
    int n = 0;

    if (!dc)
        return 0;
    copy = malloc(sizeof(*copy));
    *copy = *dc;
    copy->saved = dc->saved;
    dc->saved = copy;
    for (copy = dc->saved; copy; copy = copy->saved)
        n++;
    return (uint32_t)n;
}

static uint32_t RestoreDC(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);
    int depth = 0, level, n = (int32_t)a[1];
    DC *p;

    if (!dc)
        return 0;
    for (p = dc->saved; p; p = p->saved)
        depth++;
    level = n > 0 ? n : depth + n + 1;
    if (!depth || level < 1 || level > depth)
        return 0;
    {
        int drop = depth - level, i;
        DC *target = dc->saved;

        for (i = 0; i < drop; i++)
            target = target->saved;
        {
            DC *rest = target->saved;

            *dc = *target;
            dc->saved = rest;
        }
    }
    return 1;
}

static uint32_t SetViewportOrgEx(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);

    if (dc) {
        if (a[3]) {
            WR32(a[3], (uint32_t)dc->org[0]);
            WR32(a[3] + 4, (uint32_t)dc->org[1]);
        }
        dc->org[0] = (int32_t)a[1];
        dc->org[1] = (int32_t)a[2];
    }
    return 1;
}

static uint32_t OffsetViewportOrgEx(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);

    if (dc) {
        dc->org[0] += (int32_t)a[1];
        dc->org[1] += (int32_t)a[2];
    }
    return 1;
}

static uint32_t SelectClipRgn(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);
    Region *r = obj_get(a[1], O_REGION);

    if (dc) {
        dc->has_clip = r != NULL;
        if (r) {
            dc->clip[0] = r->l; dc->clip[1] = r->t; dc->clip[2] = r->r; dc->clip[3] = r->b;
        }
    }
    return 2;
}

static uint32_t IntersectClipRect(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);

    if (dc) {
        int x0 = lx(dc, (int32_t)a[1]) + dc->org[0], y0 = ly(dc, (int32_t)a[2]) + dc->org[1];
        int x1 = lx(dc, (int32_t)a[3]) + dc->org[0], y1 = ly(dc, (int32_t)a[4]) + dc->org[1];

        if (dc->has_clip) {
            if (x0 < dc->clip[0]) x0 = dc->clip[0];
            if (y0 < dc->clip[1]) y0 = dc->clip[1];
            if (x1 > dc->clip[2]) x1 = dc->clip[2];
            if (y1 > dc->clip[3]) y1 = dc->clip[3];
        }
        dc->has_clip = 1;
        dc->clip[0] = x0;
        dc->clip[1] = y0;
        dc->clip[2] = x1 > x0 ? x1 : x0;
        dc->clip[3] = y1 > y0 ? y1 : y0;
    }
    return 2;
}

static uint32_t CreateRectRgn(const uint32_t *a)
{
    Region *r = calloc(1, sizeof(*r));

    r->l = (int32_t)a[0]; r->t = (int32_t)a[1]; r->r = (int32_t)a[2]; r->b = (int32_t)a[3];
    return obj_new(O_REGION, r);
}

static uint32_t SetRectRgn(const uint32_t *a)
{
    Region *r = obj_get(a[0], O_REGION);

    if (!r)
        return 0;
    r->l = (int32_t)a[1]; r->t = (int32_t)a[2]; r->r = (int32_t)a[3]; r->b = (int32_t)a[4];
    return 1;
}

static uint32_t CreateRectRgnIndirect(const uint32_t *a)
{
    Region *r = calloc(1, sizeof(*r));

    r->l = (int32_t)RD32(a[0]); r->t = (int32_t)RD32(a[0] + 4); r->r = (int32_t)RD32(a[0] + 8); r->b = (int32_t)RD32(a[0] + 12);
    return obj_new(O_REGION, r);
}

/* RectInRegion(hrgn, &rect): does any part of the rectangle lie in the region? (The port's regions are their bounding rectangles; both are half open, as Windows' are.) */
static uint32_t RectInRegion(const uint32_t *a)
{
    Region *r = obj_get(a[0], O_REGION);
    int l = (int32_t)RD32(a[1]), t = (int32_t)RD32(a[1] + 4), rr = (int32_t)RD32(a[1] + 8), b = (int32_t)RD32(a[1] + 12);

    if (!r)
        return 0;
    return l < r->r && r->l < rr && t < r->b && r->t < b && l < rr && t < b;
}

static uint32_t CreatePolygonRgn(const uint32_t *a)
{
    Region *r = calloc(1, sizeof(*r));
    uint32_t i;

    r->l = r->t = 0x7FFFFFFF;
    r->r = r->b = -0x7FFFFFFF;
    for (i = 0; i < a[1]; i++) {
        int x = (int32_t)RD32(a[0] + 8 * i), y = (int32_t)RD32(a[0] + 8 * i + 4);

        if (x < r->l) r->l = x;
        if (y < r->t) r->t = y;
        if (x > r->r) r->r = x;
        if (y > r->b) r->b = y;
    }
    return obj_new(O_REGION, r);
}

static uint32_t GetDeviceCaps(const uint32_t *a)
{
    switch (a[1]) {
    case 8: return SCREEN_W; case 10: return SCREEN_H; case 12: return 8; case 14: return 1; case 24: return 20; case 26: return 0;
    case 38: return 0x7E99 | 0x100; case 88: return 96; case 90: return 96; case 104: return 256; case 106: return 20; case 4: return 0;
    case 6: return 0; case 2: return 1; case 0: return 0x0400;
    default: return 0;
    }
}

const WinApi GDI32_STATE_APIS[] = {
    {"gdi32.dll", "GetStockObject", GetStockObject}, {"gdi32.dll", "CreateSolidBrush", CreateSolidBrush},
    {"gdi32.dll", "CreateBrushIndirect", CreateBrushIndirect}, {"gdi32.dll", "CreatePatternBrush", CreatePatternBrush},
    {"gdi32.dll", "CreateHatchBrush", CreateHatchBrush}, {"gdi32.dll", "CreatePen", CreatePen}, {"gdi32.dll", "CreatePenIndirect", CreatePenIndirect},
    {"gdi32.dll", "CreateFontIndirectA", CreateFontIndirectA}, {"gdi32.dll", "CreateFontA", CreateFontA},
    {"gdi32.dll", "AddFontResourceA", AddFontResourceA}, {"gdi32.dll", "RemoveFontResourceA", one}, {"gdi32.dll", "CreatePalette", CreatePalette},
    {"gdi32.dll", "GetNearestPaletteIndex", GetNearestPaletteIndex}, {"gdi32.dll", "SetPaletteEntries", SetPaletteEntries}, {"gdi32.dll", "GetPaletteEntries", GetPaletteEntries},
    {"gdi32.dll", "SelectPalette", SelectPalette}, {"gdi32.dll", "RealizePalette", RealizePalette}, {"gdi32.dll", "AnimatePalette", AnimatePalette},
    {"gdi32.dll", "SetSystemPaletteUse", one}, {"gdi32.dll", "UnrealizeObject", one}, {"gdi32.dll", "SelectObject", SelectObject},
    {"gdi32.dll", "DeleteObject", DeleteObject}, {"gdi32.dll", "DeleteDC", DeleteDC}, {"gdi32.dll", "CreateCompatibleDC", CreateCompatibleDC},
    {"gdi32.dll", "CreateDCA", CreateDCA}, {"gdi32.dll", "CreateCompatibleBitmap", CreateCompatibleBitmap}, {"gdi32.dll", "CreateBitmap", CreateBitmap},
    {"gdi32.dll", "SetBitmapDimensionEx", one}, {"gdi32.dll", "CreateDIBSection", CreateDIBSection},
    {"gdi32.dll", "SetDIBColorTable", SetDIBColorTable}, {"gdi32.dll", "SetDIBits", SetDIBits}, {"gdi32.dll", "GetObjectA", GetObjectA},
    {"gdi32.dll", "SetTextColor", SetTextColor}, {"gdi32.dll", "SetBkColor", SetBkColor}, {"gdi32.dll", "SetBkMode", SetBkMode},
    {"gdi32.dll", "SetTextAlign", SetTextAlign}, {"gdi32.dll", "GetTextAlign", GetTextAlign}, {"gdi32.dll", "SetROP2", thirteen},
    {"gdi32.dll", "SetMapMode", SetMapMode}, {"gdi32.dll", "GetMapMode", GetMapMode}, {"gdi32.dll", "SetWindowExtEx", SetWindowExtEx},
    {"gdi32.dll", "SetViewportExtEx", SetViewportExtEx}, {"gdi32.dll", "SetWindowOrgEx", SetWindowOrgEx}, {"gdi32.dll", "LPtoDP", LPtoDP},
    {"gdi32.dll", "DPtoLP", DPtoLP}, {"gdi32.dll", "SetStretchBltMode", one}, {"gdi32.dll", "GdiFlush", one}, {"gdi32.dll", "GdiGetBatchLimit", one},
    {"gdi32.dll", "GdiSetBatchLimit", one}, {"gdi32.dll", "SaveDC", SaveDC}, {"gdi32.dll", "RestoreDC", RestoreDC},
    {"gdi32.dll", "SetViewportOrgEx", SetViewportOrgEx}, {"gdi32.dll", "OffsetViewportOrgEx", OffsetViewportOrgEx},
    {"gdi32.dll", "SelectClipRgn", SelectClipRgn}, {"gdi32.dll", "IntersectClipRect", IntersectClipRect}, {"gdi32.dll", "CreateRectRgn", CreateRectRgn},
    {"gdi32.dll", "SetRectRgn", SetRectRgn}, {"gdi32.dll", "CreateRectRgnIndirect", CreateRectRgnIndirect}, {"gdi32.dll", "RectInRegion", RectInRegion},
    {"gdi32.dll", "CreatePolygonRgn", CreatePolygonRgn}, {"gdi32.dll", "GetDeviceCaps", GetDeviceCaps},
    {0, 0, 0},
};


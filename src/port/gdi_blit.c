/* gdi_blit.c - BitBlt and StretchBlt with their raster operations, and the shapes. Port of winemu/gdi.py (the second half). */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gdi_int.h"

/* Raster operations that combine the source with what is already there (the game draws its bitmap-font glyphs as an AND with a mask and
 * then an OR with the glyph, so that the glyph's black background stays out of the picture). */
static int rop_known(uint32_t rop)
{
    return rop == 0x8800C6 || rop == 0xEE0086 || rop == 0x660046 || rop == 0x440328 || rop == 0x330008 || rop == 0x1100A6 || rop == 0xBB0226;
}

static uint8_t rop_apply(uint32_t rop, uint8_t s, uint8_t d)
{
    switch (rop) {
    case 0x8800C6: return s & d;              /* SRCAND */
    case 0xEE0086: return s | d;              /* SRCPAINT */
    case 0x660046: return s ^ d;              /* SRCINVERT */
    case 0x440328: return (uint8_t)(s & ~d);  /* SRCERASE */
    case 0x330008: return (uint8_t)~s;        /* NOTSRCCOPY */
    case 0x1100A6: return (uint8_t)~(s | d);  /* NOTSRCERASE */
    case 0xBB0226: return (uint8_t)(~s | d);  /* MERGEPAINT */
    }
    return s;
}

static int iabs(int v) { return v < 0 ? -v : v; }

/* An (h0 x w0) array of `bpp` bytes per pixel stretched to |h| x |w| by nearest neighbour; a negative height flips vertically. */
static uint8_t *nearest(const uint8_t *src, int w0, int h0, int bpp, int w, int h)
{
    int aw = iabs(w), ah = iabs(h), x, y;
    uint8_t *out = malloc((size_t)aw * (size_t)ah * (size_t)bpp);

    for (y = 0; y < ah; y++) {
        int sy = (int)((long long)y * h0 / (ah ? ah : 1));
        int oy = h < 0 ? ah - 1 - y : y;

        if (sy > h0 - 1)
            sy = h0 - 1;
        for (x = 0; x < aw; x++) {
            int sx = (int)((long long)x * w0 / (aw ? aw : 1));

            if (sx > w0 - 1)
                sx = w0 - 1;
            memcpy(out + ((size_t)oy * (size_t)aw + (size_t)x) * (size_t)bpp, src + ((size_t)sy * (size_t)w0 + (size_t)sx) * (size_t)bpp, (size_t)bpp);
        }
    }
    return out;
}

/* A box-filter resize (PIL's BOX): each output pixel averages the source pixels under it, edge pixels by their overlap. */
uint8_t *gdi_box_resize(const uint8_t *src, int w0, int h0, int w, int h)
{
    int aw = iabs(w), ah = iabs(h), x, y, c, k;
    double sx = (double)w0 / aw, sy = (double)h0 / ah;
    float *tmp = malloc((size_t)aw * (size_t)h0 * 3 * sizeof(float));
    uint8_t *out = malloc((size_t)aw * (size_t)ah * 3);

    for (y = 0; y < h0; y++)                              /* horizontal pass */
        for (x = 0; x < aw; x++) {
            double center = (x + 0.5) * sx, support = sx > 1.0 ? 0.5 * sx : 0.5, sum[3] = {0, 0, 0}, wsum = 0;
            int xmin = (int)(center - support + 0.5), xmax = (int)(center + support + 0.5);

            if (xmin < 0) xmin = 0;
            if (xmax > w0) xmax = w0;
            for (k = xmin; k < xmax; k++) {
                double t = (k - center + 0.5) / (sx > 1.0 ? sx : 1.0), wt = (t >= -0.5 && t < 0.5) ? 1.0 : 0.0;

                for (c = 0; c < 3; c++)
                    sum[c] += src[((size_t)y * (size_t)w0 + (size_t)k) * 3 + (size_t)c] * wt;
                wsum += wt;
            }
            if (wsum <= 0) {                                  /* stretching up with a centre exactly on a pixel edge: no pixel is inside the box, take the nearest */
                k = (int)center;
                if (k > w0 - 1) k = w0 - 1;
                for (c = 0; c < 3; c++)
                    sum[c] = src[((size_t)y * (size_t)w0 + (size_t)k) * 3 + (size_t)c];
                wsum = 1;
            }
            for (c = 0; c < 3; c++)
                tmp[((size_t)y * (size_t)aw + (size_t)x) * 3 + (size_t)c] = (float)(sum[c] / wsum);
        }
    for (y = 0; y < ah; y++) {                            /* vertical pass */
        double center = (y + 0.5) * sy, support = sy > 1.0 ? 0.5 * sy : 0.5;
        int ymin = (int)(center - support + 0.5), ymax = (int)(center + support + 0.5);
        int oy = h < 0 ? ah - 1 - y : y;

        if (ymin < 0) ymin = 0;
        if (ymax > h0) ymax = h0;
        for (x = 0; x < aw; x++) {
            double sum[3] = {0, 0, 0}, wsum = 0;

            for (k = ymin; k < ymax; k++) {
                double t = (k - center + 0.5) / (sy > 1.0 ? sy : 1.0), wt = (t >= -0.5 && t < 0.5) ? 1.0 : 0.0;

                for (c = 0; c < 3; c++)
                    sum[c] += tmp[((size_t)k * (size_t)aw + (size_t)x) * 3 + (size_t)c] * wt;
                wsum += wt;
            }
            if (wsum <= 0) {                                  /* as above, for rows */
                k = (int)center;
                if (k > h0 - 1) k = h0 - 1;
                for (c = 0; c < 3; c++)
                    sum[c] = tmp[((size_t)k * (size_t)aw + (size_t)x) * 3 + (size_t)c];
                wsum = 1;
            }
            for (c = 0; c < 3; c++) {
                double v = sum[c] / wsum;

                out[((size_t)oy * (size_t)aw + (size_t)x) * 3 + (size_t)c] = (uint8_t)(v + 0.5 > 255 ? 255 : v + 0.5);
            }
        }
    }
    if (w < 0) {                                          /* a negative width flips horizontally */
        for (y = 0; y < ah; y++)
            for (x = 0; x < aw / 2; x++)
                for (c = 0; c < 3; c++) {
                    uint8_t t = out[((size_t)y * (size_t)aw + (size_t)x) * 3 + (size_t)c];

                    out[((size_t)y * (size_t)aw + (size_t)x) * 3 + (size_t)c] = out[((size_t)y * (size_t)aw + (size_t)(aw - 1 - x)) * 3 + (size_t)c];
                    out[((size_t)y * (size_t)aw + (size_t)(aw - 1 - x)) * 3 + (size_t)c] = t;
                }
    }
    free(tmp);
    return out;
}

/* Index-preserving copy between windows, device bitmaps and 8-bit DIB sections, with optional nearest-neighbour stretch. Returns 0 when the source cannot
 * be read as indices (the caller falls back to colours). */
static int blit_indices(DC *dst, int x, int y, int w, int h, DC *src, int sx, int sy, int sw, int sh)
{
    int ax0, ay0, ax1, ay1, cx0, cy0, cw, ch, ox, oy, aw, ah;
    uint8_t *idx, *use;
    Bitmap *db = dst->memory ? dst->bitmap : NULL;

    if (w == 0 || h == 0 || sw == 0 || sh == 0)
        return 1;
    ax0 = sx + src->org[0];
    ay0 = sy + src->org[1];
    ax1 = ax0 + iabs(sw);
    ay1 = ay0 + iabs(sh);
    idx = dc_indices(src, ax0, ay0, ax1, ay1, dst, &cx0, &cy0, &cw, &ch);
    if (!idx)
        return 0;
    if (cw == 0 || ch == 0) {
        free(idx);
        return 1;
    }
    aw = iabs(w);
    ah = iabs(h);
    if (aw != iabs(sw) || ah != iabs(sh)) {                 /* stretch: sample the source nearest-neighbour */
        uint8_t *full = calloc((size_t)iabs(sw) * (size_t)iabs(sh), 1);
        int yy;

        for (yy = 0; yy < ch; yy++)
            memcpy(full + (size_t)(cy0 - ay0 + yy) * (size_t)iabs(sw) + (size_t)(cx0 - ax0), idx + (size_t)yy * (size_t)cw, (size_t)cw);
        use = nearest(full, iabs(sw), iabs(sh), 1, aw, ah);
        free(full);
        cw = aw;
        ch = ah;
        ox = x;
        oy = y;
    } else {
        use = idx;
        idx = NULL;
        ox = x + (cx0 - ax0);
        oy = y + (cy0 - ay0);
    }
    free(idx);
    if (db && !db->ddb && (db->bpp == 24 || db->bpp == 32)) {
        /* indices into a direct-colour bitmap: colours come from the source DC's logical palette (else the system palette), as Windows resolves
         * them when it copies to a device-independent bitmap */
        const Bitmap *sb = src->memory ? src->bitmap : NULL;
        const uint8_t (*table)[3];
        int n, i;
        uint8_t full[256][3];
        uint8_t *rgb;

        if (sb && !sb->ddb && sb->bpp == 8 && sb->idxmap) {
            table = sb->palette;
            n = sb->npalette;
        } else {
            const Palette *pal = src->palette ? src->palette : system_palette;

            table = pal->e;
            n = pal->n;
        }
        for (i = 0; i < 256; i++) {
            if (i < n) { full[i][0] = table[i][0]; full[i][1] = table[i][1]; full[i][2] = table[i][2]; }
            else full[i][0] = full[i][1] = full[i][2] = 0;
        }
        rgb = malloc((size_t)cw * (size_t)ch * 3);
        for (i = 0; i < cw * ch; i++)
            memcpy(rgb + 3 * (size_t)i, full[use[i]], 3);
        write_dib_rgb(dst->bitmap, ox + dst->org[0], oy + dst->org[1], rgb, cw, ch);
        free(rgb);
    } else
        put_indices(dst, ox + dst->org[0], oy + dst->org[1], use, cw, ch);
    free(use);
    return 1;
}

/* Blit with a combining raster operation (device units, relative to the viewport origins): on palette indices when both sides are readable as
 * indices (what an 8-bit display does) and on colours otherwise. The source is stretched to the destination. */
static int rop_blit(DC *dst, int x, int y, int w, int h, DC *src, int sx, int sy, int sw, int sh, uint32_t rop)
{
    int X = x + dst->org[0], Y = y + dst->org[1], aw = iabs(w), ah = iabs(h), i;
    int rx, ry, rw, rh, dx, dy, dw, dh;
    uint8_t *si, *di;

    if (w == 0 || h == 0 || sw == 0 || sh == 0)
        return 1;
    si = dc_indices(src, sx + src->org[0], sy + src->org[1], sx + src->org[0] + iabs(sw), sy + src->org[1] + iabs(sh), dst, &rx, &ry, &rw, &rh);
    di = dc_indices(dst, X, Y, X + aw, Y + ah, NULL, &dx, &dy, &dw, &dh);
    if (si && di && rw && rh && rw == iabs(sw) && rh == iabs(sh) && dw == aw && dh == ah) {
        uint8_t *stretched = si, *res;

        if (iabs(sw) != aw || iabs(sh) != ah)
            stretched = nearest(si, rw, rh, 1, w, h);
        res = malloc((size_t)aw * (size_t)ah);
        for (i = 0; i < aw * ah; i++)
            res[i] = rop_apply(rop, stretched[i], di[i]);
        put_indices(dst, X, Y, res, aw, ah);
        free(res);
        if (stretched != si)
            free(stretched);
        free(si);
        free(di);
        return 1;
    }
    free(si);
    free(di);
    {
        int sw2, sh2, dw2, dh2, rxx, ryy;
        uint8_t *sp = get_region(src, sx + src->org[0], sy + src->org[1], sx + src->org[0] + iabs(sw), sy + src->org[1] + iabs(sh), &sw2, &sh2, &rxx, &ryy);
        uint8_t *dp = get_region(dst, X, Y, X + aw, Y + ah, &dw2, &dh2, &rxx, &ryy), *res;

        if (!sp || !dp) {
            free(sp);
            free(dp);
            return 1;
        }
        if (sw2 != dw2 || sh2 != dh2) {
            uint8_t *st = nearest(sp, sw2, sh2, 3, w, h);

            free(sp);
            sp = st;
            sw2 = aw;
            sh2 = ah;
        }
        if (sw2 != dw2 || sh2 != dh2) {
            free(sp);
            free(dp);
            return 1;
        }
        res = malloc((size_t)dw2 * (size_t)dh2 * 3);
        for (i = 0; i < dw2 * dh2 * 3; i++)
            res[i] = rop_apply(rop, sp[i], dp[i]);
        put_region(dst, X, Y, res, dw2, dh2);
        free(res);
        free(sp);
        free(dp);
    }
    return 1;
}

static int pattern_fill(DC *dc, int x, int y, int w, int h)
{
    if (dc->brush.solid)
        fill_rect_rgb(dc, x, y, w, h, dc->brush.rgb);
    return 1;
}

/* BitBlt / StretchBlt in logical units: the destination rectangle is mapped by the destination DC, the source rectangle by the source DC (so a DC
 * with a scaled mapping stretches), then copied or combined with the raster operation. */
int gdi_blit(DC *dst, DC *src, int x, int y, int w, int h, int sx, int sy, int sw, int sh, uint32_t rop)
{
    int d[4], s[4], shrinking, rw, rh, rx, ry;
    uint8_t *px;

    dev_rect(dst, x, y, w, h, d);
    if (rop == 0x000042) {
        const uint8_t black[3] = {0, 0, 0};

        fill_rect_rgb(dst, d[0], d[1], d[2], d[3], black);
        return 1;
    }
    if (rop == 0xFF0062) {
        const uint8_t white[3] = {255, 255, 255};

        fill_rect_rgb(dst, d[0], d[1], d[2], d[3], white);
        return 1;
    }
    if (rop == 0xF00021)
        return pattern_fill(dst, d[0], d[1], d[2], d[3]);
    if (!src)
        return 0;
    dev_rect(src, sx, sy, sw, sh, s);
    if (rop_known(rop))
        return rop_blit(dst, d[0], d[1], d[2], d[3], src, s[0], s[1], s[2], s[3], rop);
    shrinking = iabs(d[2]) < iabs(s[2]) || iabs(d[3]) < iabs(s[3]);
    if (!shrinking && blit_indices(dst, d[0], d[1], d[2], d[3], src, s[0], s[1], s[2], s[3]))
        return 1;
    px = get_region(src, s[0] + src->org[0], s[1] + src->org[1], s[0] + src->org[0] + iabs(s[2]), s[1] + src->org[1] + iabs(s[3]), &rw, &rh, &rx, &ry);
    if (!px || d[2] == 0 || d[3] == 0) {
        free(px);
        return 1;
    }
    if (rw != iabs(d[2]) || rh != iabs(d[3])) {
        uint8_t *st;

        if (shrinking && rw && rh)
            st = gdi_box_resize(px, rw, rh, d[2], d[3]);       /* the game asks for HALFTONE stretching: shrinking averages the source pixels */
        else
            st = nearest(px, rw, rh, 3, d[2], d[3]);
        free(px);
        px = st;
        rw = iabs(d[2]);
        rh = iabs(d[3]);
    }
    put_region(dst, d[0] + dst->org[0], d[1] + dst->org[1], px, rw, rh);
    free(px);
    return 1;
}

static int blitlog = -1;

/* PORT_BLITLOG=1: every BitBlt and StretchBlt with its destination, source, raster operation and the guest address that called it. */
static void log_blit(const char *what, const uint32_t *a, int stretch)
{
    if (blitlog < 0)
        blitlog = getenv("PORT_BLITLOG") != NULL;
    if (blitlog)
        fprintf(stderr, "    [blit] %s dc 0x%x (%d,%d %dx%d) <- dc 0x%x (%d,%d %s%dx%d) rop 0x%x from 0x%08x\n", what, a[0], (int)a[1], (int)a[2], (int)a[3], (int)a[4], a[5],
                (int)a[6], (int)a[7], stretch ? "src " : "", stretch ? (int)a[8] : (int)a[3], stretch ? (int)a[9] : (int)a[4], stretch ? a[10] : a[8], RD32(port_sp));
}

static uint32_t BitBlt(const uint32_t *a)
{
    DC *dst = dc_of(a[0]), *src = dc_of(a[5]);

    log_blit("BitBlt", a, 0);
    if (!dst)
        return 0;
    return (uint32_t)gdi_blit(dst, src, (int32_t)a[1], (int32_t)a[2], (int32_t)a[3], (int32_t)a[4], (int32_t)a[6], (int32_t)a[7], (int32_t)a[3], (int32_t)a[4], a[8]);
}

static uint32_t StretchBlt(const uint32_t *a)
{
    DC *dst = dc_of(a[0]), *src = dc_of(a[5]);

    log_blit("StretchBlt", a, 1);
    if (!dst)
        return 0;
    return (uint32_t)gdi_blit(dst, src, (int32_t)a[1], (int32_t)a[2], (int32_t)a[3], (int32_t)a[4], (int32_t)a[6], (int32_t)a[7], (int32_t)a[8], (int32_t)a[9], a[10]);
}

/* ---- SetDIBitsToDevice -------------------------------------------------------------------------------------------------------------- */
static uint32_t SetDIBitsToDevice(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);
    int x = (int32_t)a[1], y = (int32_t)a[2], cx = (int32_t)a[3], cy = (int32_t)a[4], sx = (int32_t)a[5], sy = (int32_t)a[6];
    int start = (int)a[7], lines = (int)a[8], k, w, h, bpp, topdown, stride, ncol, pal_colors;
    uint32_t bits = a[9], bmi = a[10], usage = a[11], size;
    uint8_t pal[256][3], lut[256];
    uint16_t words[256];
    int i;

    if (!dc)
        return 0;
    size = RD32(bmi);
    w = (int32_t)RD32(bmi + 4);
    h = (int32_t)RD32(bmi + 8);
    bpp = RD16(bmi + 14);
    topdown = h < 0;
    h = h < 0 ? -h : h;
    {
        uint32_t used = RD32(bmi + 32);

        ncol = (int)(used ? used : (bpp <= 8 ? (1u << bpp) : 0));
        if (ncol > 256)
            ncol = 256;
    }
    pal_colors = usage == 1;
    memset(pal, 0, sizeof(pal));
    for (i = 0; i < ncol; i++) {
        if (pal_colors)
            words[i] = RD16(bmi + size + 2 * (uint32_t)i);
        else {
            pal[i][0] = G[bmi + size + 4 * (uint32_t)i + 2]; pal[i][1] = G[bmi + size + 4 * (uint32_t)i + 1]; pal[i][2] = G[bmi + size + 4 * (uint32_t)i];
        }
    }
    stride = ((w * bpp + 31) / 32) * 4;
    for (k = 0; k < lines; k++) {
        int r = start + k, dy;
        const uint8_t *raw = G + bits + (size_t)k * (size_t)stride;

        if (!(sy <= r && r < sy + cy))
            continue;
        dy = y + (topdown ? r - sy : sy + cy - 1 - r);
        if (bpp == 8 && pal_colors) {                          /* DIB_PAL_COLORS: indices, not colours */
            uint8_t *row = malloc((size_t)cx);

            for (i = 0; i < 256; i++)
                lut[i] = (uint8_t)i;
            for (i = 0; i < ncol; i++)
                lut[i] = (uint8_t)(words[i] & 0xFF);
            for (i = 0; i < cx; i++)
                row[i] = lut[raw[sx + i]];
            if (!dc->memory || !dc->bitmap || dc->bitmap->ddb || dc->bitmap->bpp != 8)
                put_indices(dc, x + dc->org[0], dy + dc->org[1], row, cx, 1);
            else
                write_dib_indices(dc->bitmap, x + dc->org[0], dy + dc->org[1], row, cx, 1);
            free(row);
        } else if (bpp == 8) {
            uint8_t *row = malloc((size_t)cx), tmp[256];
            const Bitmap *db = dc->memory ? dc->bitmap : NULL;

            if (!ncol)
                for (i = 0; i < 256; i++)
                    pal[i][0] = pal[i][1] = pal[i][2] = (uint8_t)i;
            if (!dc->memory)
                dib_to_system_lut(pal, ncol ? ncol : 256, lut);
            else if (db && !db->ddb && db->bpp == 8 && memcmp(db->palette, pal, sizeof(pal)) != 0)
                dib_to_dib_lut(pal, ncol ? ncol : 256, db->palette, db->npalette, lut);
            else
                for (i = 0; i < 256; i++)
                    lut[i] = (uint8_t)i;
            for (i = 0; i < cx; i++)
                row[i] = lut[raw[sx + i]];
            if (!dc->memory)
                put_indices(dc, x + dc->org[0], dy + dc->org[1], row, cx, 1);
            else if (db && !db->ddb && db->bpp == 8)
                write_dib_indices(dc->bitmap, x + dc->org[0], dy + dc->org[1], row, cx, 1);
            else {
                dib_to_system_lut(pal, ncol ? ncol : 256, tmp);
                for (i = 0; i < cx; i++)
                    row[i] = tmp[raw[sx + i]];
                put_indices(dc, x + dc->org[0], dy + dc->org[1], row, cx, 1);
            }
            free(row);
        } else if (bpp == 24) {
            uint8_t *rgb = malloc((size_t)cx * 3);

            for (i = 0; i < cx; i++) {
                rgb[3 * i] = raw[(sx + i) * 3 + 2]; rgb[3 * i + 1] = raw[(sx + i) * 3 + 1]; rgb[3 * i + 2] = raw[(sx + i) * 3];
            }
            put_region(dc, x + dc->org[0], dy + dc->org[1], rgb, cx, 1);
            free(rgb);
        } else
            return 0;
    }
    return (uint32_t)lines;
}

uint32_t gdi_set_dibits_to_device(const uint32_t *a) { return SetDIBitsToDevice(a); }

/* ---- shapes -------------------------------------------------------------------------------------------------------------------------- */
/* The device box of a shape call's logical arguments a[1..4]. */
static void dev_box(const DC *dc, const uint32_t *a, int *x0, int *y0, int *x1, int *y1)
{
    int l = (int32_t)a[1], t = (int32_t)a[2], r = (int32_t)a[3], b = (int32_t)a[4];
    int xa = lx(dc, l) + dc->org[0], xb = lx(dc, r) + dc->org[0], ya = ly(dc, t) + dc->org[1], yb = ly(dc, b) + dc->org[1];

    *x0 = xa < xb ? xa : xb;
    *x1 = xa < xb ? xb : xa;
    *y0 = ya < yb ? ya : yb;
    *y1 = ya < yb ? yb : ya;
}

typedef struct Canvas { uint8_t *px; int w, h, ox, oy; } Canvas;

static Canvas canvas_open(DC *dc, int x0, int y0, int x1, int y1)
{
    Canvas c = {0};
    int rx, ry, w, h;

    c.px = get_region(dc, x0, y0, x1, y1, &w, &h, &rx, &ry);
    c.w = w;
    c.h = h;
    c.ox = rx;
    c.oy = ry;
    return c;
}

static void canvas_close(DC *dc, Canvas *c)
{
    if (c->px)
        put_region(dc, c->ox, c->oy, c->px, c->w, c->h);
    free(c->px);
}

static void cpix(Canvas *c, int x, int y, const uint8_t rgb[3])
{
    x -= c->ox;
    y -= c->oy;
    if (x < 0 || y < 0 || x >= c->w || y >= c->h)
        return;
    memcpy(c->px + 3 * ((size_t)y * (size_t)c->w + (size_t)x), rgb, 3);
}

static void hline(Canvas *c, int x0, int x1, int y, const uint8_t rgb[3])
{
    int x;

    for (x = x0; x <= x1; x++)
        cpix(c, x, y, rgb);
}

static uint32_t Rectangle(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);
    int x0, y0, x1, y1, y;
    Canvas c;
    int xe, ye;

    if (!dc)
        return 0;
    dev_box(dc, a, &x0, &y0, &x1, &y1);
    c = canvas_open(dc, x0, y0, x1 + 1, y1 + 1);
    xe = x1 - 1 > x0 ? x1 - 1 : x0;
    ye = y1 - 1 > y0 ? y1 - 1 : y0;
    if (dc->brush.solid)
        for (y = y0; y <= ye; y++)
            hline(&c, x0, xe, y, dc->brush.rgb);
    if (dc->pen.solid) {
        hline(&c, x0, xe, y0, dc->pen.rgb);
        hline(&c, x0, xe, ye, dc->pen.rgb);
        for (y = y0; y <= ye; y++) {
            cpix(&c, x0, y, dc->pen.rgb);
            cpix(&c, xe, y, dc->pen.rgb);
        }
    }
    canvas_close(dc, &c);
    return 1;
}

/* Is (x, y) inside the ellipse whose bounding box is [x0, x1] x [y0, y1] (pixel centres)? */
static int in_ellipse(double cx, double cy, double rx, double ry, int x, int y)
{
    double dx = (x - cx) / rx, dy = (y - cy) / ry;

    return dx * dx + dy * dy <= 1.0;
}

static uint32_t Ellipse(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);
    int x0, y0, x1, y1, x, y, xe, ye;
    Canvas c;
    double cx, cy, rx, ry;

    if (!dc)
        return 0;
    dev_box(dc, a, &x0, &y0, &x1, &y1);
    c = canvas_open(dc, x0, y0, x1 + 1, y1 + 1);
    xe = x1 - 1 > x0 ? x1 - 1 : x0;
    ye = y1 - 1 > y0 ? y1 - 1 : y0;
    cx = (x0 + xe) / 2.0;
    cy = (y0 + ye) / 2.0;
    rx = (xe - x0 + 1) / 2.0;
    ry = (ye - y0 + 1) / 2.0;
    for (y = y0; y <= ye; y++)
        for (x = x0; x <= xe; x++) {
            int inside = in_ellipse(cx, cy, rx, ry, x, y);
            int outline = inside && (!in_ellipse(cx, cy, rx - 1, ry - 1, x, y));

            if (outline && dc->pen.solid)
                cpix(&c, x, y, dc->pen.rgb);
            else if (inside && dc->brush.solid)
                cpix(&c, x, y, dc->brush.rgb);
        }
    canvas_close(dc, &c);
    return 1;
}

static uint32_t RoundRect(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);
    int x0, y0, x1, y1, x, y, xe, ye, radius;
    Canvas c;

    if (!dc)
        return 0;
    dev_box(dc, a, &x0, &y0, &x1, &y1);
    c = canvas_open(dc, x0, y0, x1 + 1, y1 + 1);
    xe = x1 - 1 > x0 ? x1 - 1 : x0;
    ye = y1 - 1 > y0 ? y1 - 1 : y0;
    {
        int ew = (int32_t)a[5] < (int32_t)a[6] ? (int32_t)a[5] : (int32_t)a[6];

        radius = (int)(ew * dc->sx) / 2;
        if (radius < 1)
            radius = 1;
    }
    for (y = y0; y <= ye; y++)
        for (x = x0; x <= xe; x++) {
            int dx = x < x0 + radius ? x0 + radius - x : x > xe - radius ? x - (xe - radius) : 0;
            int dy = y < y0 + radius ? y0 + radius - y : y > ye - radius ? y - (ye - radius) : 0;
            int inside = dx * dx + dy * dy <= radius * radius;
            int inner = (dx - 1) * (dx - 1) + (dy - 1) * (dy - 1) <= (radius - 1) * (radius - 1) && x > x0 && x < xe && y > y0 && y < ye;

            if (!inside)
                continue;
            if (!inner && dc->pen.solid)
                cpix(&c, x, y, dc->pen.rgb);
            else if (dc->brush.solid)
                cpix(&c, x, y, dc->brush.rgb);
        }
    canvas_close(dc, &c);
    return 1;
}

static uint32_t MoveToEx(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);

    if (!dc)
        return 0;
    if (a[3]) {
        WR32(a[3], (uint32_t)dc->pos[0]);
        WR32(a[3] + 4, (uint32_t)dc->pos[1]);
    }
    dc->pos[0] = (int32_t)a[1];
    dc->pos[1] = (int32_t)a[2];
    return 1;
}

static uint32_t LineTo(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);
    int x0, y0, x1, y1, ox, oy, dx, dy, sx, sy, err, wd, i, j;
    Canvas c;

    if (!dc)
        return 0;
    x0 = dc->pos[0]; y0 = dc->pos[1]; x1 = (int32_t)a[1]; y1 = (int32_t)a[2];
    dc->pos[0] = x1;
    dc->pos[1] = y1;
    if (!dc->pen.solid)
        return 1;
    ox = dc->org[0];
    oy = dc->org[1];
    x0 = lx(dc, x0) + ox; y0 = ly(dc, y0) + oy; x1 = lx(dc, x1) + ox; y1 = ly(dc, y1) + oy;
    c = canvas_open(dc, (x0 < x1 ? x0 : x1) - dc->pen.width, (y0 < y1 ? y0 : y1) - dc->pen.width, (x0 > x1 ? x0 : x1) + dc->pen.width + 1,
                    (y0 > y1 ? y0 : y1) + dc->pen.width + 1);
    dx = iabs(x1 - x0);
    dy = -iabs(y1 - y0);
    sx = x0 < x1 ? 1 : -1;
    sy = y0 < y1 ? 1 : -1;
    err = dx + dy;
    wd = dc->pen.width;
    for (;;) {
        for (j = 0; j < wd; j++)
            for (i = 0; i < wd; i++)
                cpix(&c, x0 + i - wd / 2, y0 + j - wd / 2, dc->pen.rgb);
        if (x0 == x1 && y0 == y1)
            break;
        {
            int e2 = 2 * err;

            if (e2 >= dy) { err += dy; x0 += sx; }
            if (e2 <= dx) { err += dx; y0 += sy; }
        }
    }
    canvas_close(dc, &c);
    return 1;
}

static uint32_t SetPixel(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);
    int x, y;
    uint32_t c = a[3];
    uint8_t rgb[3];

    if (!dc)
        return 0;
    x = lx(dc, (int32_t)a[1]) + dc->org[0];
    y = ly(dc, (int32_t)a[2]) + dc->org[1];
    if (((c >> 24) & 0xFF) == 0x01) {                          /* PALETTEINDEX: the index itself */
        uint8_t i = (uint8_t)(c & 0xFF);

        if (!dc->memory) {
            put_indices(dc, x, y, &i, 1, 1);
            return c;
        }
        if (dc->bitmap && !dc->bitmap->ddb && dc->bitmap->bpp == 8) {
            write_dib_indices(dc->bitmap, x, y, &i, 1, 1);
            return c;
        }
    }
    colorref_rgb(dc, c, rgb);
    put_region(dc, x, y, rgb, 1, 1);
    return c;
}

static uint32_t SetPixelV(const uint32_t *a) { return SetPixel(a) ? 1 : 0; }

static uint32_t GetPixel(const uint32_t *a)
{
    DC *dc = dc_of(a[0]);
    int gx, gy, w, h, rx, ry;
    uint8_t *px;
    uint32_t r;

    if (!dc)
        return 0xFFFFFFFFu;
    gx = lx(dc, (int32_t)a[1]) + dc->org[0];
    gy = ly(dc, (int32_t)a[2]) + dc->org[1];
    px = get_region(dc, gx, gy, gx + 1, gy + 1, &w, &h, &rx, &ry);
    if (!px)
        return 0xFFFFFFFFu;
    r = px[0] | (uint32_t)px[1] << 8 | (uint32_t)px[2] << 16;
    free(px);
    return r;
}

const WinApi GDI32_BLIT_APIS[] = {
    {"gdi32.dll", "BitBlt", BitBlt}, {"gdi32.dll", "StretchBlt", StretchBlt}, {"gdi32.dll", "SetDIBitsToDevice", SetDIBitsToDevice},
    {"gdi32.dll", "Rectangle", Rectangle}, {"gdi32.dll", "RoundRect", RoundRect}, {"gdi32.dll", "Ellipse", Ellipse},
    {"gdi32.dll", "MoveToEx", MoveToEx}, {"gdi32.dll", "LineTo", LineTo}, {"gdi32.dll", "SetPixel", SetPixel}, {"gdi32.dll", "SetPixelV", SetPixelV},
    {"gdi32.dll", "GetPixel", GetPixel},
    {0, 0, 0},
};

/* font.c - a small TrueType rasterizer: the game's own fonts (MAGIM___.TTF and friends, which it installs with AddFontResource) drawn
 * without a font library. Outlines are read from the font file (glyf, loca, cmap format 4, hmtx, hhea, head, kern, name), flattened to
 * lines and filled by exact area coverage; advances are rounded to whole pixels as a hinted renderer does. There is no hinting. */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gdi_int.h"

struct TTFont {
    uint8_t *d;
    size_t len;
    uint32_t glyf, loca, hmtx, cmap, kern, name, head, hhea, maxp;
    int upem, loca_long, nglyphs, nhmetrics, ascender, descender;
    uint32_t cmap4;                 /* offset of the format 4 subtable, or 0 */
    char family[64], style[32];
    struct { unsigned char ch; double em; int glyph; } *cache;     /* a few lookups cached */
    uint8_t *bmp_cache_key;
};

static uint16_t u16(const TTFont *f, size_t o) { return o + 2 <= f->len ? (uint16_t)(f->d[o] << 8 | f->d[o + 1]) : 0; }
static int16_t s16(const TTFont *f, size_t o) { return (int16_t)u16(f, o); }
static uint32_t u32(const TTFont *f, size_t o) { return o + 4 <= f->len ? (uint32_t)f->d[o] << 24 | (uint32_t)f->d[o + 1] << 16 | (uint32_t)f->d[o + 2] << 8 | f->d[o + 3] : 0; }

static uint32_t find_table(const TTFont *f, const char *tag)
{
    int n = u16(f, 4), i;

    for (i = 0; i < n; i++) {
        size_t e = 12 + 16 * (size_t)i;

        if (e + 16 <= f->len && !memcmp(f->d + e, tag, 4))
            return u32(f, e + 8);
    }
    return 0;
}

static void read_name(TTFont *f)
{
    uint32_t t = f->name;
    int count, off, i;

    f->family[0] = f->style[0] = 0;
    if (!t)
        return;
    count = u16(f, t + 2);
    off = u16(f, t + 4);
    for (i = 0; i < count; i++) {
        size_t r = t + 6 + 12 * (size_t)i;
        int plat = u16(f, r), id = u16(f, r + 6), len = u16(f, r + 8), so = u16(f, r + 10), k;
        char *dst;
        size_t cap;

        if (id != 1 && id != 2)
            continue;
        if (plat != 3 && plat != 1)
            continue;
        dst = id == 1 ? f->family : f->style;
        cap = id == 1 ? sizeof(f->family) : sizeof(f->style);
        if (dst[0] && plat == 1)
            continue;
        if (plat == 3) {
            for (k = 0; k + 1 < len && (size_t)(k / 2) + 1 < cap; k += 2)
                dst[k / 2] = (char)f->d[t + (size_t)off + (size_t)so + (size_t)k + 1];
            dst[k / 2] = 0;
        } else {
            for (k = 0; k < len && (size_t)k + 1 < cap; k++)
                dst[k] = (char)f->d[t + (size_t)off + (size_t)so + (size_t)k];
            dst[k] = 0;
        }
    }
}

TTFont *ttf_load(const char *path)
{
    FILE *fp = fopen(path, "rb");
    TTFont *f;
    long len;
    int n, i;

    if (!fp)
        return NULL;
    fseek(fp, 0, SEEK_END);
    len = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    f = calloc(1, sizeof(*f));
    f->d = malloc((size_t)len + 8);
    f->len = fread(f->d, 1, (size_t)len, fp);
    fclose(fp);
    if (f->len < 12 || (u32(f, 0) != 0x00010000u && memcmp(f->d, "true", 4))) {
        free(f->d);
        free(f);
        return NULL;
    }
    f->glyf = find_table(f, "glyf");
    f->loca = find_table(f, "loca");
    f->hmtx = find_table(f, "hmtx");
    f->cmap = find_table(f, "cmap");
    f->kern = find_table(f, "kern");
    f->name = find_table(f, "name");
    f->head = find_table(f, "head");
    f->hhea = find_table(f, "hhea");
    f->maxp = find_table(f, "maxp");
    if (!f->glyf || !f->loca || !f->hmtx || !f->cmap || !f->head || !f->hhea || !f->maxp) {
        free(f->d);
        free(f);
        return NULL;
    }
    f->upem = u16(f, f->head + 18);
    f->loca_long = s16(f, f->head + 50);
    f->nglyphs = u16(f, f->maxp + 4);
    f->ascender = s16(f, f->hhea + 4);
    f->descender = s16(f, f->hhea + 6);
    f->nhmetrics = u16(f, f->hhea + 34);
    n = u16(f, f->cmap + 2);
    for (i = 0; i < n; i++) {
        size_t r = f->cmap + 4 + 8 * (size_t)i;
        int plat = u16(f, r), enc = u16(f, r + 2);
        uint32_t off = f->cmap + u32(f, r + 4);

        if (u16(f, off) == 4 && ((plat == 3 && (enc == 1 || enc == 0)) || plat == 0)) {
            f->cmap4 = off;
            if (plat == 3 && enc == 1)
                break;
        }
    }
    read_name(f);
    if (!f->upem)
        f->upem = 1000;
    return f;
}

const char *ttf_family(const TTFont *f) { return f->family; }
const char *ttf_style(const TTFont *f) { return f->style; }

void ttf_metrics(const TTFont *f, double em, int *ascent, int *descent)
{
    double s = em / f->upem;

    *ascent = (int)ceil(f->ascender * s - 1e-9);
    *descent = (int)ceil(-f->descender * s - 1e-9);
}

/* tmAscent: the ascent rounded to a whole pixel, the line the text sits on (12 for Benguiat Bk BT at 13 pixels, where a ceiling would say 13). */
int ttf_ascent(const TTFont *f, double em)
{
    return (int)(f->ascender * em / f->upem + 0.5);
}

/* The dialog base unit's font: tmHeight (the rounded ascent plus the rounded descent of the em) and the width the horizontal unit comes from. That width is not
 * tmAveCharWidth (the OS/2 table's xAvgCharWidth: 7 pixels for Benguiat Bk BT at 10 points) but the one of the 52 letters a-z and A-Z, (sum / 26 + 1) / 2 with
 * whole-pixel advances, which is 8; the real Windows 98 setup dialog of DUEL.EXE has 8 x 15 pixels per unit (docs/notes/dialogs.md). */
void ttf_text_metrics(const TTFont *f, double em, int *height, int *avg_width)
{
    double s = em / f->upem;
    int sum = 0;
    unsigned char c;

    *height = (int)(f->ascender * s + 0.5) + (int)(-f->descender * s + 0.5);
    for (c = 'a'; c <= 'z'; c++)
        sum += (int)ttf_advance(f, em, c) + (int)ttf_advance(f, em, (unsigned char)(c - 'a' + 'A'));
    *avg_width = (sum / 26 + 1) / 2;
    if (*avg_width < 1)
        *avg_width = 1;
}

static int glyph_index(const TTFont *f, unsigned int ch)
{
    int segx2, i;
    uint32_t t = f->cmap4;

    if (!t)
        return 0;
    segx2 = u16(f, t + 6);
    for (i = 0; i < segx2; i += 2) {
        uint32_t end = u16(f, t + 14 + (size_t)i), start = u16(f, t + 16 + (size_t)segx2 + (size_t)i);

        if (ch <= end) {
            int delta, range;
            size_t ro;

            if (ch < start)
                return 0;
            delta = u16(f, t + 16 + 2 * (size_t)segx2 + (size_t)i);
            ro = t + 16 + 3 * (size_t)segx2 + (size_t)i;
            range = u16(f, ro);
            if (!range)
                return (int)((ch + (uint32_t)delta) & 0xFFFF);
            {
                int g = u16(f, ro + (size_t)range + 2 * (ch - start));

                return g ? (int)(((unsigned)g + (unsigned)delta) & 0xFFFF) : 0;
            }
        }
    }
    return 0;
}

static int advance_units(const TTFont *f, int glyph)
{
    int k = glyph < f->nhmetrics ? glyph : f->nhmetrics - 1;

    return u16(f, f->hmtx + 4 * (size_t)k);
}

static int kern_units(const TTFont *f, int left, int right)
{
    int tables, t;
    size_t o;

    if (!f->kern)
        return 0;
    tables = u16(f, f->kern + 2);
    o = f->kern + 4;
    for (t = 0; t < tables; t++) {
        int len = u16(f, o + 2), cov = u16(f, o + 4);

        if ((cov >> 8) == 0 && (cov & 1)) {
            int n = u16(f, o + 6), lo = 0, hi = n - 1;
            uint32_t key = (uint32_t)left << 16 | (uint32_t)right;

            while (lo <= hi) {
                int mid = (lo + hi) / 2;
                size_t p = o + 14 + 6 * (size_t)mid;
                uint32_t k = u32(f, p);

                if (k == key)
                    return s16(f, p + 4);
                if (k < key)
                    lo = mid + 1;
                else
                    hi = mid - 1;
            }
        }
        o += (size_t)len;
    }
    return 0;
}

double ttf_advance(const TTFont *f, double em, unsigned char ch)
{
    int g = glyph_index(f, ch);

    return floor(advance_units(f, g) * em / f->upem + 0.5);       /* a hinted advance is a whole number of pixels */
}

double ttf_kern(const TTFont *f, double em, unsigned char a, unsigned char b)
{
    return floor(kern_units(f, glyph_index(f, a), glyph_index(f, b)) * em / f->upem + 0.5);
}

/* ---- outlines ------------------------------------------------------------------------------------------------------------------ */
typedef struct Pt { double x, y; int on; } Pt;
typedef struct Edges { double (*e)[4]; int n, cap; } Edges;

static void add_edge(Edges *E, double x0, double y0, double x1, double y1)
{
    if (y0 == y1)
        return;
    if (E->n == E->cap) {
        E->cap = E->cap ? E->cap * 2 : 256;
        E->e = realloc(E->e, (size_t)E->cap * sizeof(*E->e));
    }
    E->e[E->n][0] = x0; E->e[E->n][1] = y0; E->e[E->n][2] = x1; E->e[E->n][3] = y1;
    E->n++;
}

static void quad(Edges *E, double x0, double y0, double cx, double cy, double x1, double y1, int depth)
{
    double dx = x0 - 2 * cx + x1, dy = y0 - 2 * cy + y1;

    if (depth > 6 || dx * dx + dy * dy < 0.05) {
        add_edge(E, x0, y0, x1, y1);
        return;
    }
    {
        double ax = (x0 + cx) / 2, ay = (y0 + cy) / 2, bx = (cx + x1) / 2, by = (cy + y1) / 2, mx = (ax + bx) / 2, my = (ay + by) / 2;

        quad(E, x0, y0, ax, ay, mx, my, depth + 1);
        quad(E, mx, my, bx, by, x1, y1, depth + 1);
    }
}

/* The outline of a glyph, transformed (a b c d tx ty), into edges in font units. */
static int glyph_edges(const TTFont *f, int glyph, double m[6], Edges *E, int depth)
{
    uint32_t a, b;
    size_t g;
    int nc, i, npts, k;
    uint16_t *ends;
    Pt *pts;

    if (glyph < 0 || glyph >= f->nglyphs || depth > 4)
        return 0;
    a = f->loca_long ? u32(f, f->loca + 4 * (size_t)glyph) : 2u * u16(f, f->loca + 2 * (size_t)glyph);
    b = f->loca_long ? u32(f, f->loca + 4 * (size_t)glyph + 4) : 2u * u16(f, f->loca + 2 * (size_t)glyph + 2);
    if (b <= a)
        return 1;                           /* an empty glyph (a space) */
    g = f->glyf + a;
    nc = s16(f, g);
    if (nc < 0) {                           /* composite: components with their own offsets and scales */
        size_t o = g + 10;
        int flags;

        do {
            int cg, arg1, arg2;
            double sub[6], sa = 1, sb = 0, sc = 0, sd = 1;

            flags = u16(f, o);
            cg = u16(f, o + 2);
            o += 4;
            if (flags & 1) { arg1 = s16(f, o); arg2 = s16(f, o + 2); o += 4; }
            else { arg1 = (int8_t)f->d[o]; arg2 = (int8_t)f->d[o + 1]; o += 2; }
            if (flags & 8) { sa = sd = s16(f, o) / 16384.0; o += 2; }
            else if (flags & 0x40) { sa = s16(f, o) / 16384.0; sd = s16(f, o + 2) / 16384.0; o += 4; }
            else if (flags & 0x80) { sa = s16(f, o) / 16384.0; sb = s16(f, o + 2) / 16384.0; sc = s16(f, o + 4) / 16384.0; sd = s16(f, o + 6) / 16384.0; o += 8; }
            /* the component's matrix composed with the parent's; offsets are in the component's parent space */
            {
                double tx = (flags & 2) ? arg1 : 0, ty = (flags & 2) ? arg2 : 0;

                sub[0] = m[0] * sa + m[2] * sb; sub[1] = m[1] * sa + m[3] * sb;
                sub[2] = m[0] * sc + m[2] * sd; sub[3] = m[1] * sc + m[3] * sd;
                sub[4] = m[4] + m[0] * tx + m[2] * ty; sub[5] = m[5] + m[1] * tx + m[3] * ty;
            }
            glyph_edges(f, cg, sub, E, depth + 1);
        } while (flags & 0x20);
        return 1;
    }
    ends = malloc((size_t)(nc + 1) * sizeof(*ends));
    for (i = 0; i < nc; i++)
        ends[i] = u16(f, g + 10 + 2 * (size_t)i);
    npts = nc ? ends[nc - 1] + 1 : 0;
    {
        size_t o = g + 10 + 2 * (size_t)nc;
        int ilen = u16(f, o), p;
        uint8_t *flags = malloc((size_t)npts + 1);

        o += 2 + (size_t)ilen;
        for (p = 0; p < npts;) {
            uint8_t fl = f->d[o++];

            flags[p++] = fl;
            if (fl & 8) {
                int rep = f->d[o++];

                while (rep-- && p < npts)
                    flags[p++] = fl;
            }
        }
        pts = malloc(((size_t)npts + 1) * sizeof(*pts));
        {
            int v = 0;

            for (p = 0; p < npts; p++) {
                if (flags[p] & 2) { int dx = f->d[o++]; v += (flags[p] & 16) ? dx : -dx; }
                else if (!(flags[p] & 16)) { v += s16(f, o); o += 2; }
                pts[p].x = v;
            }
            v = 0;
            for (p = 0; p < npts; p++) {
                if (flags[p] & 4) { int dy = f->d[o++]; v += (flags[p] & 32) ? dy : -dy; }
                else if (!(flags[p] & 32)) { v += s16(f, o); o += 2; }
                pts[p].y = v;
                pts[p].on = flags[p] & 1;
            }
        }
        free(flags);
    }
    k = 0;
    for (i = 0; i < nc; i++) {
        int start = k, end = ends[i], n = end - start + 1, p;
        Pt *c = malloc((size_t)(2 * n + 2) * sizeof(*c));
        int nn = 0;

        /* expand implied on-curve points between consecutive off-curve ones, and start on an on-curve point */
        for (p = 0; p < n; p++) {
            Pt cur = pts[start + p], nxt = pts[start + (p + 1) % n];

            c[nn++] = cur;
            if (!cur.on && !nxt.on)
                c[nn++] = (Pt){(cur.x + nxt.x) / 2, (cur.y + nxt.y) / 2, 1};
        }
        {
            int first_on = -1, q;

            for (q = 0; q < nn; q++)
                if (c[q].on) { first_on = q; break; }
            if (first_on < 0) {          /* all off-curve: start at the middle of the first two */
                Pt mid = {(c[0].x + c[1 % nn].x) / 2, (c[0].y + c[1 % nn].y) / 2, 1};

                memmove(c + 1, c, (size_t)nn * sizeof(*c));
                c[0] = mid;
                nn++;
                first_on = 0;
            }
            for (q = 0; q < nn;) {
                Pt p0 = c[(first_on + q) % nn], p1 = c[(first_on + q + 1) % nn], p2 = c[(first_on + q + 2) % nn];
#define TX(P) (m[0] * (P).x + m[2] * (P).y + m[4])
#define TY(P) (m[1] * (P).x + m[3] * (P).y + m[5])
                if (p1.on) {
                    add_edge(E, TX(p0), TY(p0), TX(p1), TY(p1));
                    q += 1;
                } else {
                    quad(E, TX(p0), TY(p0), TX(p1), TY(p1), TX(p2), TY(p2), 0);
                    q += 2;
                }
#undef TX
#undef TY
            }
        }
        free(c);
        k = end + 1;
    }
    free(pts);
    free(ends);
    return 1;
}

/* A glyph's coverage: an 8-bit plane with the offsets of its top-left corner from the origin (x right, y up from the baseline). */
uint8_t *ttf_glyph(const TTFont *f, double em, unsigned char ch, int *w, int *h, int *left, int *top)
{
    Edges E = {0};
    double m[6], s = em / f->upem, minx = 1e30, maxx = -1e30, miny = 1e30, maxy = -1e30, *acc;
    int g = glyph_index(f, ch), i, x, y, W, H;
    uint8_t *out;

    m[0] = s; m[1] = 0; m[2] = 0; m[3] = -s; m[4] = 0; m[5] = 0;          /* y is flipped: pixels grow downward */
    *w = *h = *left = *top = 0;
    if (!glyph_edges(f, g, m, &E, 0) || !E.n) {
        free(E.e);
        return NULL;
    }
    for (i = 0; i < E.n; i++) {
        double xa = E.e[i][0], xb = E.e[i][2], ya = E.e[i][1], yb = E.e[i][3];

        if (xa < minx) minx = xa;
        if (xb < minx) minx = xb;
        if (xa > maxx) maxx = xa;
        if (xb > maxx) maxx = xb;
        if (ya < miny) miny = ya;
        if (yb < miny) miny = yb;
        if (ya > maxy) maxy = ya;
        if (yb > maxy) maxy = yb;
    }
    x = (int)floor(minx);
    y = (int)floor(miny);
    W = (int)ceil(maxx) - x + 1;
    H = (int)ceil(maxy) - y + 1;
    if (W <= 0 || H <= 0 || W > 2048 || H > 2048 || !(minx < maxx + 1) || !(miny < maxy + 1)) {       /* a glyph of no size, or a size no font has: nothing to draw */
        fprintf(stderr, "font: glyph %u at em %g would be %d x %d (bounds %g..%g, %g..%g): not drawn\n", ch, em, W, H, minx, maxx, miny, maxy);
        free(E.e);
        return NULL;
    }
    acc = calloc((size_t)W * (size_t)H + (size_t)W + 2, sizeof(double));
    for (i = 0; i < E.n; i++) {                  /* signed area accumulation: each edge adds its coverage to the cells it crosses */
        double x0 = E.e[i][0] - x, y0 = E.e[i][1] - y, x1 = E.e[i][2] - x, y1 = E.e[i][3] - y, dir = 1.0, dxdy;
        int row, row0, row1;

        if (y0 > y1) {
            double t;

            t = x0; x0 = x1; x1 = t;
            t = y0; y0 = y1; y1 = t;
            dir = -1.0;
        }
        dxdy = (x1 - x0) / (y1 - y0);
        row0 = (int)floor(y0);
        row1 = (int)ceil(y1);
        for (row = row0; row < row1 && row < H; row++) {
            double ya = y0 > row ? y0 : row, yb = y1 < row + 1 ? y1 : row + 1, dy, xa, xb, left_x, right_x;
            int c0, c1, c;

            if (row < 0 || yb <= ya)
                continue;
            dy = yb - ya;
            xa = x0 + (ya - y0) * dxdy;
            xb = x0 + (yb - y0) * dxdy;
            left_x = xa < xb ? xa : xb;
            right_x = xa < xb ? xb : xa;
            c0 = (int)floor(left_x);
            c1 = (int)floor(right_x);
            if (c0 == c1) {
                double xmf = 0.5 * (xa + xb) - c0;           /* the edge stays in one cell: split its area at the cell's mean x */

                acc[row * W + c0] += dir * dy * (1.0 - xmf);
                if (c0 + 1 < W)
                    acc[row * W + c0 + 1] += dir * dy * xmf;
            } else {
                double slope = dy / (right_x - left_x);

                for (c = c0; c <= c1 && c < W; c++) {
                    double cl = left_x > c ? left_x : c, cr = right_x < c + 1 ? right_x : c + 1, part = (cr - cl) * slope, xmf = 0.5 * (cl + cr) - c;

                    if (cr <= cl)
                        continue;
                    acc[row * W + c] += dir * part * (1.0 - xmf);
                    if (c + 1 < W)
                        acc[row * W + c + 1] += dir * part * xmf;
                }
            }
        }
    }
    out = malloc((size_t)W * (size_t)H);
    for (y = 0; y < H; y++) {
        double sum = 0;

        for (x = 0; x < W; x++) {
            double v;

            sum += acc[y * W + x];
            v = fabs(sum);
            if (v > 1)
                v = 1;
            out[y * W + x] = (uint8_t)(v * 255.0 + 0.5);
        }
    }
    free(acc);
    free(E.e);
    *w = W;
    *h = H;
    *left = (int)floor(minx);
    *top = -(int)floor(miny);                      /* rows above the baseline: the first row is `top` pixels above it */
    return out;
}

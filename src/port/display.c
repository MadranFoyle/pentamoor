/* display.c - see display.h. Pure: no SDL, no game (display_cfg.c has the file access). */
#include <ctype.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "display.h"

/* ---- the modes -------------------------------------------------------------------------------------------------------------------------------------- */
static const char *const scale_names[SCALE_COUNT] = {"fit", "integer", "stretch"};
static const char *const filter_names[FILTER_COUNT] = {"nearest", "linear", "sharp"};

const char *scale_name(ScaleMode m) { return m >= 0 && m < SCALE_COUNT ? scale_names[m] : scale_names[DEFAULT_SCALE]; }
const char *filter_name(FilterMode f) { return f >= 0 && f < FILTER_COUNT ? filter_names[f] : filter_names[DEFAULT_FILTER]; }

/* does `s` (blanks around it allowed) spell `name`, in any case? */
static int word_is(const char *s, const char *name)
{
    while (*s == ' ' || *s == '\t')
        s++;
    for (; *name; name++, s++)
        if (tolower((unsigned char)*s) != *name)
            return 0;
    while (*s == ' ' || *s == '\t' || *s == '\r' || *s == '\n')
        s++;
    return *s == 0;
}

int scale_parse(const char *s, ScaleMode *out)
{
    int i;

    for (i = 0; s && i < SCALE_COUNT; i++)
        if (word_is(s, scale_names[i])) {
            *out = (ScaleMode)i;
            return 1;
        }
    return 0;
}

int filter_parse(const char *s, FilterMode *out)
{
    int i;

    for (i = 0; s && i < FILTER_COUNT; i++)
        if (word_is(s, filter_names[i])) {
            *out = (FilterMode)i;
            return 1;
        }
    return 0;
}

ScaleMode scale_cycle(ScaleMode m) { return (ScaleMode)(((int)m + 1) % SCALE_COUNT); }
FilterMode filter_cycle(FilterMode f) { return (FilterMode)(((int)f + 1) % FILTER_COUNT); }

static int ifloor(double v)
{
    int i = (int)v;

    return (double)i > v ? i - 1 : i;
}

static int iceil(double v)
{
    int i = (int)v;

    return (double)i < v ? i + 1 : i;
}

/* ---- the layout ------------------------------------------------------------------------------------------------------------------------------------- */
double display_fit(int sw, int sh, int dw, int dh, int *integer, int *vw, int *vh)
{
    double f, s;
    int k, whole = 0;

    if (sw <= 0 || sh <= 0 || dw <= 0 || dh <= 0) {
        if (integer)
            *integer = 0;
        if (vw)
            *vw = sw;
        if (vh)
            *vh = sh;
        return 1.0;
    }
    f = (double)dw / sw < (double)dh / sh ? (double)dw / sw : (double)dh / sh;
    k = (int)(f + 1e-9);
    s = f;
    if (k >= 1 && k * 100.0 >= f * INT_SCALE_MIN) {
        whole = 1;
        s = k;
    }
    if (integer)
        *integer = whole;
    if (vw)
        *vw = (int)(sw * s + 0.5);
    if (vh)
        *vh = (int)(sh * s + 0.5);
    return s;
}

static void centre(DispView *v, int ow, int oh, int w, int h)
{
    if (w > ow)
        w = ow;
    if (h > oh)
        h = oh;
    v->dst.w = w;
    v->dst.h = h;
    v->dst.x = (ow - w) / 2;
    v->dst.y = (oh - h) / 2;
}

void display_layout(int sw, int sh, int ow, int oh, ScaleMode mode, DispView *v)
{
    int integer = 0, vw = sw, vh = sh;
    double s;

    memset(v, 0, sizeof(*v));
    v->sx = v->sy = 1.0;
    v->dst.w = sw;
    v->dst.h = sh;
    v->whole = 1;
    if (sw <= 0 || sh <= 0 || ow <= 0 || oh <= 0)
        return;
    if (mode == SCALE_STRETCH) {
        v->dst.x = v->dst.y = 0;
        v->dst.w = ow;
        v->dst.h = oh;
        v->sx = (double)ow / sw;
        v->sy = (double)oh / sh;
        v->whole = ow % sw == 0 && oh % sh == 0;
        return;
    }
    if (mode == SCALE_INTEGER) {
        double f = (double)ow / sw < (double)oh / sh ? (double)ow / sw : (double)oh / sh;
        int k = (int)(f + 1e-9);

        if (k >= 1) {
            s = k;
            integer = 1;
            vw = sw * k;
            vh = sh * k;
        } else {
            s = display_fit(sw, sh, ow, oh, &integer, &vw, &vh);       /* does not even fit once: the whole picture, smaller, rather than a cut one */
            integer = 0;
        }
    } else
        s = display_fit(sw, sh, ow, oh, &integer, &vw, &vh);
    centre(v, ow, oh, vw, vh);
    v->sx = v->sy = s;
    v->whole = integer;
}

int display_to_screen(const DispView *v, int sw, int sh, int ow, int oh, double ww, double wh, int wx, int wy, int *px, int *py)
{
    double ax, ay;
    int ix, iy;

    if (ww <= 0.0 || wh <= 0.0 || ow <= 0 || oh <= 0 || v->dst.w <= 0 || v->dst.h <= 0) {
        ix = wx;
        iy = wy;
    } else {
        ax = ((wx + 0.5) * ow / ww - v->dst.x) * sw / v->dst.w;
        ay = ((wy + 0.5) * oh / wh - v->dst.y) * sh / v->dst.h;
        ix = ifloor(ax);
        iy = ifloor(ay);
    }
    if (px)
        *px = ix;
    if (py)
        *py = iy;
    return ix >= 0 && iy >= 0 && ix < sw && iy < sh;
}

void display_to_window(const DispView *v, int sw, int sh, int ow, int oh, double ww, double wh, int px, int py, int *wx, int *wy)
{
    double ax, ay;

    if (ww <= 0.0 || wh <= 0.0 || ow <= 0 || oh <= 0 || sw <= 0 || sh <= 0) {
        *wx = px;
        *wy = py;
        return;
    }
    ax = (v->dst.x + (px + 0.5) * v->dst.w / sw) * ww / ow;
    ay = (v->dst.y + (py + 0.5) * v->dst.h / sh) * wh / oh;
    *wx = ifloor(ax);
    *wy = ifloor(ay);
}

int display_prescale(int src, int dst, int cap, int max_dim)
{
    int k;

    if (src <= 0 || dst <= src)
        return 1;
    k = (dst + src - 1) / src;
    if (cap > 0 && k > cap)
        k = cap;
    while (k > 1 && max_dim > 0 && (long)src * k > max_dim)
        k--;
    return k < 1 ? 1 : k;
}

/* ---- the card zoom ---------------------------------------------------------------------------------------------------------------------------- */
double display_zoom_layout(int cw, int ch, int ow, int oh, DispRect *dst)
{
    int aw, ah, vw = 0, vh = 0, integer = 0;
    double s;

    memset(dst, 0, sizeof(*dst));
    if (cw <= 0 || ch <= 0 || ow <= 0 || oh <= 0)
        return 1.0;
    aw = (int)((long)ow * ZOOM_FILL_PCT / 100);
    ah = (int)((long)oh * ZOOM_FILL_PCT / 100);
    if (aw < 1)
        aw = 1;
    if (ah < 1)
        ah = 1;
    s = display_fit(cw, ch, aw, ah, &integer, &vw, &vh);
    if (vw > ow)
        vw = ow;
    if (vh > oh)
        vh = oh;
    if (vw < 1)
        vw = 1;
    if (vh < 1)
        vh = 1;
    dst->w = vw;
    dst->h = vh;
    dst->x = (ow - vw) / 2;
    dst->y = (oh - vh) / 2;
    return s;
}

/* ---- the window ------------------------------------------------------------------------------------------------------------------------------------- */
void display_initial_window(int sw, int sh, int usable_w, int usable_h, double dpi, int *w, int *h)
{
    double ux, uy, fit, s;
    int k;

    if (dpi < 0.5)
        dpi = 1.0;
    *w = (int)(sw / dpi + 0.5);
    *h = (int)(sh / dpi + 0.5);
    if (usable_w <= 0 || usable_h <= 0 || sw <= 0 || sh <= 0)
        return;
    ux = usable_w * dpi * 0.9;                               /* pixels */
    uy = usable_h * dpi * 0.9;
    fit = ux / sw < uy / sh ? ux / sw : uy / sh;
    k = (int)(fit + 1e-9);
    if (k >= 1)
        s = k;
    else {
        s = fit < 0.25 ? 0.25 : fit;
    }
    *w = (int)(sw * s / dpi + 0.5);
    *h = (int)(sh * s / dpi + 0.5);
    if (*w > usable_w)
        *w = usable_w;
    if (*h > usable_h)
        *h = usable_h;
}

void display_min_window(int sw, int sh, double dpi, int start_w, int start_h, int *w, int *h)
{
    if (dpi < 0.5)
        dpi = 1.0;
    *w = iceil(sw / dpi - 1e-9);
    *h = iceil(sh / dpi - 1e-9);
    if (start_w > 0 && *w > start_w)
        *w = start_w;
    if (start_h > 0 && *h > start_h)
        *h = start_h;
    if (*w < 1)
        *w = 1;
    if (*h < 1)
        *h = 1;
}

int display_pos_ok(int x, int y, int w, int h, const DispRect *displays, int n, int need)
{
    int i;

    if (need > w)
        need = w;
    if (need > h)
        need = h;
    for (i = 0; i < n; i++) {
        int x0 = x > displays[i].x ? x : displays[i].x, y0 = y > displays[i].y ? y : displays[i].y;
        int x1 = x + w < displays[i].x + displays[i].w ? x + w : displays[i].x + displays[i].w;
        int y1 = y + h < displays[i].y + displays[i].h ? y + h : displays[i].y + displays[i].h;

        if (x1 - x0 >= need && y1 - y0 >= need)
            return 1;
    }
    return 0;
}

/* ---- display.cfg ------------------------------------------------------------------------------------------------------------------------------------ */
void dcfg_init(DisplayCfg *c)
{
    memset(c, 0, sizeof(*c));
    c->scale = DEFAULT_SCALE;
    c->filter = DEFAULT_FILTER;
}

/* "123" or "-45" (blanks around): 1 and the value if the whole string is a number in range */
static int parse_int(const char *s, long lo, long hi, long *out)
{
    char *end;
    long v;

    while (*s == ' ' || *s == '\t')
        s++;
    if (!*s)
        return 0;
    v = strtol(s, &end, 10);
    if (end == s)
        return 0;
    while (*end == ' ' || *end == '\t')
        end++;
    if (*end || v < lo || v > hi)
        return 0;
    *out = v;
    return 1;
}

/* "1280x800", "1280 x 800" or "1280,800" */
static int parse_pair(const char *s, int sep_x, long lo, long hi, long *a, long *b)
{
    char tmp[64], *sep;
    size_t n = strlen(s);

    if (n >= sizeof(tmp))
        return 0;
    memcpy(tmp, s, n + 1);
    if (sep_x)
        sep = strpbrk(tmp, "xX");
    else
        sep = strchr(tmp, ',');
    if (!sep)
        return 0;
    *sep = 0;
    return parse_int(tmp, lo, hi, a) && parse_int(sep + 1, lo, hi, b);
}

static int flag_value(const char *v, int *out)
{
    if (word_is(v, "1") || word_is(v, "yes") || word_is(v, "on") || word_is(v, "true")) {
        *out = 1;
        return 1;
    }
    if (word_is(v, "0") || word_is(v, "no") || word_is(v, "off") || word_is(v, "false")) {
        *out = 0;
        return 1;
    }
    return 0;
}

int dcfg_parse(const char *text, DisplayCfg *c)
{
    int taken = 0;
    const char *p = text;

    while (p && *p) {
        const char *nl = strchr(p, '\n'), *start = p;
        size_t n = nl ? (size_t)(nl - p) : strlen(p);
        char line[160], *eq, *key, *val;
        size_t i;

        p = nl ? nl + 1 : p + n;
        if (n >= sizeof(line))
            continue;                                         /* nothing the file holds is that long */
        memcpy(line, start, n);
        line[n] = 0;
        for (i = 0; i < n; i++)
            if (line[i] == '\r')
                line[i] = 0;
        key = line;
        while (*key == ' ' || *key == '\t')
            key++;
        if (*key == '#' || *key == ';' || !*key)
            continue;
        eq = strchr(key, '=');
        if (!eq)
            continue;
        *eq = 0;
        val = eq + 1;
        for (i = strlen(key); i > 0 && (key[i - 1] == ' ' || key[i - 1] == '\t'); i--)
            key[i - 1] = 0;
        for (i = 0; key[i]; i++)
            key[i] = (char)tolower((unsigned char)key[i]);
        if (!strcmp(key, "fullscreen")) {
            int f;

            if (flag_value(val, &f)) {
                c->has_fullscreen = 1;
                c->fullscreen = f;
                taken++;
            }
        } else if (!strcmp(key, "scale")) {
            if (scale_parse(val, &c->scale)) {
                c->has_scale = 1;
                taken++;
            }
        } else if (!strcmp(key, "filter")) {
            if (filter_parse(val, &c->filter)) {
                c->has_filter = 1;
                taken++;
            }
        } else if (!strcmp(key, "window")) {
            long a, b;

            if (parse_pair(val, 1, DISPLAY_WIN_MIN, DISPLAY_WIN_MAX, &a, &b)) {
                c->has_window = 1;
                c->win_w = (int)a;
                c->win_h = (int)b;
                taken++;
            }
        } else if (!strcmp(key, "position")) {
            long a, b;

            if (parse_pair(val, 0, -32768, 32767, &a, &b)) {
                c->has_pos = 1;
                c->win_x = (int)a;
                c->win_y = (int)b;
                taken++;
            }
        }
    }
    return taken;
}

int dcfg_format(const DisplayCfg *c, char *buf, size_t cap)
{
    int n = snprintf(buf, cap,
                     "# Pentamoor display settings. The game writes this file when you change them; edit it while the game is not running.\n"
                     "# fullscreen: 0 or 1.  scale: fit, integer or stretch.  filter: nearest, linear or sharp.\n"
                     "# window: the size of the window in points, position: its top-left corner. Delete a line to get its default.\n"
                     "# PORT_FULLSCREEN, PORT_SCALE, PORT_FILTER and PORT_WINDOW in the environment win over this file.\n");
    int m;

    if (n < 0 || (size_t)n >= cap)
        return -1;
#define LINE(...) do { m = snprintf(buf + n, cap - (size_t)n, __VA_ARGS__); if (m < 0 || (size_t)m >= cap - (size_t)n) return -1; n += m; } while (0)
    if (c->has_fullscreen)
        LINE("fullscreen=%d\n", c->fullscreen ? 1 : 0);
    if (c->has_scale)
        LINE("scale=%s\n", scale_name(c->scale));
    if (c->has_filter)
        LINE("filter=%s\n", filter_name(c->filter));
    if (c->has_window)
        LINE("window=%dx%d\n", c->win_w, c->win_h);
    if (c->has_pos)
        LINE("position=%d,%d\n", c->win_x, c->win_y);
#undef LINE
    return n;
}

/* ---- what the run uses ------------------------------------------------------------------------------------------------------------------------------ */
static void warn_add(char *warn, size_t cap, const char *what, const char *value)
{
    size_t n;

    if (!warn || !cap)
        return;
    n = strlen(warn);
    snprintf(warn + n, cap - n, "%s: \"%.40s\" is not understood, ignored\n", what, value);
}

void display_resolve(const DisplayCfg *file, const char *env_fullscreen, const char *env_scale, const char *env_filter, const char *env_window, int deck,
                     DisplaySettings *out, char *warn, size_t warncap)
{
    memset(out, 0, sizeof(*out));
    if (warn && warncap)
        warn[0] = 0;
    out->fullscreen = file && file->has_fullscreen ? file->fullscreen != 0 : deck != 0;
    out->scale = file && file->has_scale ? file->scale : DEFAULT_SCALE;
    out->filter = file && file->has_filter ? file->filter : DEFAULT_FILTER;
    if (file && file->has_window) {
        out->has_window = 1;
        out->win_w = file->win_w;
        out->win_h = file->win_h;
    }
    if (file && file->has_pos) {
        out->has_pos = 1;
        out->win_x = file->win_x;
        out->win_y = file->win_y;
    }
    if (env_fullscreen) {                                     /* as PORT_FULLSCREEN always was: empty, 0, no, off and false mean no, anything else yes */
        out->fullscreen = !(!*env_fullscreen || word_is(env_fullscreen, "0") || word_is(env_fullscreen, "no") || word_is(env_fullscreen, "off") || word_is(env_fullscreen, "false"));
    }
    if (env_scale && *env_scale && !scale_parse(env_scale, &out->scale))
        warn_add(warn, warncap, "PORT_SCALE", env_scale);
    if (env_filter && *env_filter && !filter_parse(env_filter, &out->filter))
        warn_add(warn, warncap, "PORT_FILTER", env_filter);
    if (env_window && *env_window) {
        long a, b;

        if (parse_pair(env_window, 1, DISPLAY_WIN_MIN, DISPLAY_WIN_MAX, &a, &b)) {
            out->has_window = 1;
            out->win_w = (int)a;
            out->win_h = (int)b;
            out->win_env = 1;
        } else
            warn_add(warn, warncap, "PORT_WINDOW", env_window);
    }
}

void display_cfg_update(DisplayCfg *file, const DisplaySettings *start, const DisplaySettings *now)
{
    if (now->fullscreen != start->fullscreen) {
        file->has_fullscreen = 1;
        file->fullscreen = now->fullscreen;
    }
    if (now->scale != start->scale) {
        file->has_scale = 1;
        file->scale = now->scale;
    }
    if (now->filter != start->filter) {
        file->has_filter = 1;
        file->filter = now->filter;
    }
    if (now->has_window && !(start->win_env && start->has_window && now->win_w == start->win_w && now->win_h == start->win_h)) {
        file->has_window = 1;
        file->win_w = now->win_w;
        file->win_h = now->win_h;
    }
    if (now->has_pos) {
        file->has_pos = 1;
        file->win_x = now->win_x;
        file->win_y = now->win_y;
    }
}

/* ---- the keys and the pad ---------------------------------------------------------------------------------------------------------------------------- */
DispAction display_key_action(DispKey key, int alt, int ctrl, int shift)
{
    if (key == DK_RETURN)
        return alt && !ctrl && !shift ? DA_FULLSCREEN : DA_NONE;
    if (key == DK_F11) {
        if (alt)
            return DA_NONE;
        if (ctrl && shift)
            return DA_NONE;
        if (ctrl)
            return DA_SCALE;
        if (shift)
            return DA_FILTER;
        return DA_FULLSCREEN;
    }
    return DA_NONE;
}

int display_combo_step(DispCombo *c, int a_down, int b_down, uint32_t now_ms)
{
    if (!(a_down && b_down)) {
        c->held = c->fired = 0;
        return 0;
    }
    if (!c->held) {
        c->held = 1;
        c->fired = 0;
        c->since = now_ms;
        return 0;
    }
    if (!c->fired && now_ms - c->since >= DISPLAY_COMBO_MS) {
        c->fired = 1;                                         /* once per hold */
        return 1;
    }
    return 0;
}

/* ---- the message ------------------------------------------------------------------------------------------------------------------------------------ */
static pthread_mutex_t notice_lock = PTHREAD_MUTEX_INITIALIZER;
static char notice_text[96];
static uint32_t notice_t0;

void display_notice(const char *text, uint32_t now_ms)
{
    pthread_mutex_lock(&notice_lock);
    snprintf(notice_text, sizeof(notice_text), "%s", text);
    notice_t0 = now_ms ? now_ms : 1;
    pthread_mutex_unlock(&notice_lock);
}

int display_notice_get(uint32_t now_ms, char *out, size_t cap)
{
    int got = 0;

    pthread_mutex_lock(&notice_lock);
    if (notice_t0 && notice_text[0] && now_ms - notice_t0 < DISPLAY_NOTICE_MS) {
        snprintf(out, cap, "%s", notice_text);
        got = 1;
    }
    pthread_mutex_unlock(&notice_lock);
    return got;
}

void display_notice_text(ScaleMode s, FilterMode f, char *out, size_t cap)
{
    snprintf(out, cap, "Scaling: %s, filter: %s", scale_name(s), filter_name(f));
}

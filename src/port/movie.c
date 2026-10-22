/* movie.c - the game's AVI movies, played on the host. Port of winemu/movie.py.
 *
 * MAGIC.EXE shows the coin toss with MCIWndCreateA (msvfw32): a child window that the game then sends MCI_PLAY (0x806), MCI_STOP (0x808) and WM_CLOSE. There is
 * no Video for Windows here, so the window is a built-in class whose surface is painted from the movie on the clock: the screen composer calls movie_tick and
 * the frame for the time since MCI_PLAY is decoded and drawn. MAGVID.DLL, the video engine the statistics window (STATWIN.DLL) plays the ending movie with, is
 * replaced the same way (video.c): a video there is a window like the MCI one.
 *
 * The coin toss movies are Microsoft Video 1 ("CRAM", 16 bit, 4x4 blocks) with 8 bit PCM sound, which is small enough to decode here. The ending movie is Indeo 4
 * ("IV41"), which is not: when ffmpeg is installed it decodes those frames (a pipe, in order); without it such a movie is skipped, as a movie that cannot load.
 * The sound is plain PCM in the AVI and goes through the mixer (sound.c) whichever way the picture is decoded. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <unistd.h>

#include "plat.h"
#include "gdi.h"
#include "gdi_int.h"
#include "movie.h"
#include "port.h"
#include "sched.h"
#include "wm.h"

enum { MCI_PLAY = 0x806, MCI_STOP = 0x808 };
enum { MCIWNDM_NOTIFYMODE = 0x4C8, MCI_MODE_STOP = 524, MCI_MODE_PLAY = 525 };

typedef struct Chunk { uint32_t off, size; } Chunk;

struct Movie {
    uint8_t *data;
    size_t len;
    int w, h, nframes, naudio;
    double fps;
    char fourcc[5];
    Chunk *frames, *audio;
    uint32_t audio_rate, audio_bits, audio_channels;
    uint16_t *pix;               /* Video 1: the decoded state, bottom row first (DIB order) */
    int at;                      /* the frame the decoded state holds (-1: none) */
    FILE *pipe;                  /* ffmpeg: the frames as RGB, in order */
    uint8_t *last;               /* ffmpeg: the latest one, w*h*3 */
    char path[1100];
};

static uint32_t le32(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static uint32_t le16(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8; }

static void add_chunk(Chunk **list, int *n, uint32_t off, uint32_t size)
{
    *list = realloc(*list, (size_t)(*n + 1) * sizeof(**list));
    (*list)[(*n)++] = (Chunk){off, size};
}

/* The RIFF container: the stream formats, the frame and the sound chunks. */
static void walk(Movie *m, size_t pos, size_t end, uint8_t *kind)
{
    const uint8_t *d = m->data;

    while (pos + 8 <= end) {
        uint32_t size = le32(d + pos + 4);
        size_t body = pos + 8;
        const uint8_t *tag = d + pos;

        if (body + size > m->len)
            size = (uint32_t)(m->len - body);                  /* a file cut short: what is there */
        if (!memcmp(tag, "LIST", 4)) {
            walk(m, body + 4, body + size < end ? body + size : end, kind);
        } else if (!memcmp(tag, "strh", 4) && size >= 28) {
            memcpy(kind, d + body, 4);
            if (!memcmp(kind, "vids", 4)) {
                uint32_t scale = le32(d + body + 20), rate = le32(d + body + 24);

                memcpy(m->fourcc, d + body + 4, 4);
                m->fps = scale ? (double)rate / (double)scale : 15.0;
            }
        } else if (!memcmp(tag, "strf", 4)) {
            if (!memcmp(kind, "vids", 4) && size >= 12) {
                m->w = (int)le32(d + body + 4);
                m->h = (int)le32(d + body + 8);
            } else if (!memcmp(kind, "auds", 4) && size >= 16) {
                m->audio_channels = le16(d + body + 2);
                m->audio_rate = le32(d + body + 4);
                m->audio_bits = le16(d + body + 14);
                if (le16(d + body) != 1)
                    m->audio_bits = 0;                            /* not PCM: no sound */
            }
        } else if (tag[2] == 'w' && tag[3] == 'b') {
            add_chunk(&m->audio, &m->naudio, (uint32_t)body, size);
        } else if (tag[0] == '0' && tag[1] == '0' && tag[2] != 'w') {      /* stream 0 is the picture: "00dc" or "00db", and whatever else a tool wrote (G_AMGX.AVI has "0041") */
            add_chunk(&m->frames, &m->nframes, (uint32_t)body, size);
        }
        pos = body + size + (size & 1);
    }
}

/* One Microsoft Video 1 (16 bit) frame applied to `pix` (w*h, DIB order: the bottom row first). Blocks are 4x4, coded left to right from the bottom block row up:
 * a skip run, one colour, two colours (a bit per pixel) or eight (two per quadrant). */
void movie_decode_msvc16(const uint8_t *buf, size_t n, int w, int h, uint16_t *pix)
{
    int bw = w / 4, total = bw * (h / 4), idx = 0;
    size_t pos = 0;

    while (idx < total && pos + 2 <= n) {
        unsigned a = buf[pos], b = buf[pos + 1];
        int x, y, r, c;

        pos += 2;
        if ((b & 0xFC) == 0x84) {                                  /* skip: this block and the rest of the run are unchanged */
            idx += (int)(((b - 0x84) << 8) + a);
            continue;
        }
        x = (idx % bw) * 4;
        y = (idx / bw) * 4;
        if (b < 0x80) {                                            /* two or eight colours; (b, a) are the bit flags */
            unsigned flags = (b << 8) | a, c0, c1;
            unsigned cols[8];

            if (pos + 4 > n)
                break;
            c0 = le16(buf + pos);
            c1 = le16(buf + pos + 2);
            pos += 4;
            if (c0 & 0x8000) {                                     /* eight colours: a pair for each 2x2 quadrant */
                int i;

                if (pos + 12 > n)
                    break;
                cols[0] = c0 & 0x7FFF;
                cols[1] = c1 & 0x7FFF;
                for (i = 0; i < 6; i++)
                    cols[2 + i] = le16(buf + pos + 2 * (size_t)i) & 0x7FFF;
                pos += 12;
                for (r = 0; r < 4; r++)
                    for (c = 0; c < 4; c++) {
                        int base = (r / 2) * 4 + (c / 2) * 2;

                        pix[(size_t)(y + r) * (size_t)w + (size_t)(x + c)] = (uint16_t)((flags >> (r * 4 + c)) & 1 ? cols[base] : cols[base + 1]);
                    }
            } else {
                for (r = 0; r < 4; r++)
                    for (c = 0; c < 4; c++)
                        pix[(size_t)(y + r) * (size_t)w + (size_t)(x + c)] = (uint16_t)((flags >> (r * 4 + c)) & 1 ? (c0 & 0x7FFF) : (c1 & 0x7FFF));
            }
        } else {                                                   /* one colour */
            uint16_t col = (uint16_t)(((b << 8) | a) & 0x7FFF);

            for (r = 0; r < 4; r++)
                for (c = 0; c < 4; c++)
                    pix[(size_t)(y + r) * (size_t)w + (size_t)(x + c)] = col;
        }
        idx++;
    }
}

#ifdef _WIN32
/* cmd.exe: double quotes (a file name cannot hold one there) */
static void shell_quote(const char *s, char *out, size_t cap)
{
    size_t o = 0;

    out[o++] = '"';
    for (; *s && o + 3 < cap; s++)
        out[o++] = *s == '"' ? '\'' : *s;
    out[o++] = '"';
    out[o] = 0;
}
#else
static void shell_quote(const char *s, char *out, size_t cap)
{
    size_t o = 0;

    out[o++] = '\'';
    for (; *s && o + 6 < cap; s++) {
        if (*s == '\'') {
            memcpy(out + o, "'\\''", 4);
            o += 4;
        } else {
            out[o++] = *s;
        }
    }
    out[o++] = '\'';
    out[o] = 0;
}
#endif

/* Where ffmpeg is: on the PATH, or in the places a program started from a desktop launcher (with a short PATH) would miss. NULL if nowhere. */
static const char *ffmpeg_path(void)
{
    static const char *known;
    static int done;
    static char found[1100];
#ifdef _WIN32
    static const char *const extra[] = {"C:/ffmpeg/bin", "C:/Program Files/ffmpeg/bin", NULL};
    static const char *const name = "ffmpeg.exe";
#else
    static const char *const extra[] = {"/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/snap/bin", NULL};
    static const char *const name = "ffmpeg";
#endif
    const char *path;
    char dirs[4096];
    char *dir, *save;
    int i;

    if (done)
        return known;
    done = 1;
#ifdef PLAT_IOS
    return NULL;                    /* an iOS app cannot run ffmpeg (nor any program): the clips that need it are skipped, as with PORT_FFMPEG=none */
#endif
    if ((path = getenv("PORT_FFMPEG")) != NULL) {            /* PORT_FFMPEG=/path/to/ffmpeg names it; PORT_FFMPEG=none plays as if there were none (for testing) */
        if (!strcmp(path, "none") || !path[0])
            return NULL;
        snprintf(found, sizeof(found), "%s", path);
        return plat_is_executable(found) ? (known = found) : NULL;
    }
    path = getenv("PATH");
    snprintf(dirs, sizeof(dirs), "%s", path ? path : "");
    {
        const char sep[2] = {PLAT_PATH_LIST, 0};

        for (dir = strtok_r(dirs, sep, &save); dir; dir = strtok_r(NULL, sep, &save)) {
            snprintf(found, sizeof(found), "%s/%s", dir, name);
            if (plat_is_executable(found))
                return known = found;
        }
    }
    for (i = 0; extra[i]; i++) {
        snprintf(found, sizeof(found), "%s/%s", extra[i], name);
        if (plat_is_executable(found))
            return known = found;
    }
    return NULL;
}

static int have_ffmpeg(void) { return ffmpeg_path() != NULL; }

/* "-fps_mode passthrough" (every picture once, none repeated to fill a gap) is ffmpeg 5.1 and later; before that it was "-vsync passthrough". */
static const char *passthrough_option(void)
{
    static const char *opt;

    if (!opt) {
        char f[1200], cmd[2600];

        shell_quote(ffmpeg_path(), f, sizeof(f));
        snprintf(cmd, sizeof(cmd), "%s -nostdin -v quiet -f lavfi -i nullsrc=s=16x16:d=0.05 -fps_mode passthrough -f null - >" PLAT_NULL_DEVICE " 2>&1", f);
        opt = plat_system(cmd) == 0 ? "-fps_mode passthrough" : "-vsync passthrough";
    }
    return opt;
}

Movie *movie_open_mem(uint8_t *data, size_t len, const char *path)
{
    Movie *m = calloc(1, sizeof(*m));
    uint8_t kind[4] = {0};

    m->data = data;
    m->len = len;
    m->fps = 15.0;
    m->at = -1;
    snprintf(m->path, sizeof(m->path), "%s", path ? path : "");
    if (len < 12 || memcmp(data, "RIFF", 4) || memcmp(data + 8, "AVI ", 4)) {
        movie_close(m);
        return NULL;
    }
    walk(m, 12, len, kind);
    if (!m->nframes || m->w <= 0 || m->h <= 0 || m->w > 4096 || m->h > 4096) {
        movie_close(m);
        return NULL;
    }
    if (!strcasecmp(m->fourcc, "CRAM") || !strcasecmp(m->fourcc, "MSVC")) {
        m->pix = calloc((size_t)m->w * (size_t)m->h, sizeof(uint16_t));
        return m;
    }
    if (m->path[0] && have_ffmpeg()) {                             /* another codec (Indeo 4): ffmpeg, if it is there */
        m->last = calloc((size_t)m->w * (size_t)m->h * 3, 1);
        return m;
    }
    movie_close(m);
    return NULL;
}

Movie *movie_open(const char *host_path)
{
    FILE *f = fopen(host_path, "rb");
    uint8_t *d;
    long n;

    if (!f)
        return NULL;
    fseek(f, 0, SEEK_END);
    n = ftell(f);
    fseek(f, 0, SEEK_SET);
    d = malloc((size_t)n + 1);
    if (!d || fread(d, 1, (size_t)n, f) != (size_t)n) {
        free(d);
        fclose(f);
        return NULL;
    }
    fclose(f);
    return movie_open_mem(d, (size_t)n, host_path);          /* takes d, and frees it if it is not a movie */
}

void movie_close(Movie *m)
{
    if (!m)
        return;
    if (m->pipe)
        plat_pclose(m->pipe);
    free(m->data);
    free(m->frames);
    free(m->audio);
    free(m->pix);
    free(m->last);
    free(m);
}

int movie_width(const Movie *m) { return m->w; }
int movie_height(const Movie *m) { return m->h; }
int movie_frames(const Movie *m) { return m->nframes; }
double movie_fps(const Movie *m) { return m->fps; }

/* ffmpeg decodes the next picture into m->last; at the end of the stream (or with a failed pipe) the last picture stays. */
static void next_ffmpeg(Movie *m)
{
    size_t size = (size_t)m->w * (size_t)m->h * 3;

    if (!m->pipe) {
        char q[1200], f[1200], cmd[2500];

        shell_quote(m->path, q, sizeof(q));
        shell_quote(ffmpeg_path() ? ffmpeg_path() : "ffmpeg", f, sizeof(f));
        snprintf(cmd, sizeof(cmd), "%s -nostdin -v error -i %s -an -f rawvideo -pix_fmt rgb24 %s - 2>" PLAT_NULL_DEVICE, f, q, passthrough_option());
        m->pipe = plat_popen_read(cmd);
        if (!m->pipe) {
            m->at = m->nframes;
            return;
        }
    }
    if (fread(m->last, 1, size, m->pipe) < size) {
        m->at = m->nframes;
        return;
    }
    m->at++;
}

void movie_frame(Movie *m, int index, uint8_t *rgb)
{
    size_t px = (size_t)m->w * (size_t)m->h;

    if (index < 0)
        index = 0;
    if (index >= m->nframes)
        index = m->nframes - 1;
    if (m->pix) {
        size_t i;
        int y;

        if (index < m->at) {                                       /* back to the start: the frames are changes to the one before */
            memset(m->pix, 0, px * sizeof(uint16_t));
            m->at = -1;
        }
        while (m->at < index) {
            Chunk c;

            m->at++;
            c = m->frames[m->at];
            if (c.size)
                movie_decode_msvc16(m->data + c.off, c.size, m->w, m->h, m->pix);
        }
        for (y = 0; y < m->h; y++) {                               /* top row first */
            const uint16_t *src = m->pix + (size_t)(m->h - 1 - y) * (size_t)m->w;
            uint8_t *dst = rgb + (size_t)y * (size_t)m->w * 3;

            for (i = 0; i < (size_t)m->w; i++) {
                unsigned p = src[i], r = (p >> 10) & 31, g = (p >> 5) & 31, b = p & 31;

                dst[3 * i] = (uint8_t)((r << 3) | (r >> 2));
                dst[3 * i + 1] = (uint8_t)((g << 3) | (g >> 2));
                dst[3 * i + 2] = (uint8_t)((b << 3) | (b >> 2));
            }
        }
        return;
    }
    if (index < m->at && m->pipe) {                                /* ffmpeg cannot go back: start the stream again */
        plat_pclose(m->pipe);
        m->pipe = NULL;
        m->at = -1;
    }
    while (m->at < index && m->at < m->nframes)
        next_ffmpeg(m);
    memcpy(rgb, m->last, px * 3);
}

/* The sound as 16 bit PCM (interleaved if stereo), or NULL; *frames and *rate are filled in. The caller owns the memory. */
int16_t *movie_audio(const Movie *m, uint32_t *frames, uint32_t *rate, int *channels)
{
    size_t total = 0, n, i;
    int16_t *pcm;
    uint32_t bytes;
    int k;
    size_t at = 0;

    if (!m->naudio || (m->audio_bits != 8 && m->audio_bits != 16) || (m->audio_channels != 1 && m->audio_channels != 2) || !m->audio_rate)
        return NULL;
    for (k = 0; k < m->naudio; k++)
        total += m->audio[k].size;
    bytes = m->audio_bits / 8;
    n = total / bytes;
    pcm = malloc(n * sizeof(int16_t) + 2);
    if (!pcm)
        return NULL;
    for (k = 0; k < m->naudio; k++) {
        const uint8_t *src = m->data + m->audio[k].off;
        size_t cnt = m->audio[k].size / bytes;

        for (i = 0; i < cnt && at < n; i++, at++)
            pcm[at] = m->audio_bits == 16 ? (int16_t)le16(src + 2 * i) : (int16_t)(((int)src[i] - 128) << 8);
    }
    *frames = (uint32_t)(at / m->audio_channels);
    *rate = m->audio_rate;
    *channels = (int)m->audio_channels;
    return pcm;
}

/* ---- a movie in a window ------------------------------------------------------------------------------------------------------------ */
typedef struct MovieWin {
    Movie *movie;
    double t0;
    int playing, shown, voice;
    int transparent;             /* SetVidTransparency: black is see-through (the spell and wizard clips are figures on black) */
    int held;                    /* DrawVidBackground after the clip ended: nothing is drawn, but the window is still there and still takes input */
    uint8_t *alpha;              /* w*h of the picture shown: 0 where it is see-through; NULL when not transparent */
} MovieWin;

static MovieWin *mw_of(Window *w) { return (MovieWin *)w->movie; }

/* The clips that overlay a picture are drawn on black. The game's own player (MAGVID.DLL) made the video 8 bit, where that black is palette entry 0; here
 * the pictures are RGB from the decoder, whose compression leaves a faint noise on the black, so "black" is every pixel up to MOVIE_KEY in all three. */
#define MOVIE_KEY 8

void movie_key_alpha(const uint8_t *rgb, size_t pixels, uint8_t *alpha)
{
    size_t i;

    for (i = 0; i < pixels; i++)
        alpha[i] = (uint8_t)(rgb[3 * i] > MOVIE_KEY || rgb[3 * i + 1] > MOVIE_KEY || rgb[3 * i + 2] > MOVIE_KEY);
}

/* The mask of the picture the window shows (from its surface), when the window is transparent. */
static void rebuild_alpha(Window *w)
{
    MovieWin *mw = mw_of(w);
    Surface *sf = w->surface;

    if (!mw->transparent || !sf) {
        free(mw->alpha);
        mw->alpha = NULL;
        return;
    }
    mw->alpha = realloc(mw->alpha, (size_t)sf->w * (size_t)sf->h);
    movie_key_alpha(sf->rgb, (size_t)sf->w * (size_t)sf->h, mw->alpha);
}

static void show_frame(Window *w, int index)
{
    MovieWin *mw = mw_of(w);
    Surface *sf = w->surface;
    uint8_t *rgb;
    int y, cw, ch;

    if (!sf || (mw->shown == index && sf->w == movie_width(mw->movie) && sf->h == movie_height(mw->movie)))
        return;
    rgb = malloc((size_t)movie_width(mw->movie) * (size_t)movie_height(mw->movie) * 3);
    if (!rgb)
        return;
    movie_frame(mw->movie, index, rgb);
    cw = sf->w < movie_width(mw->movie) ? sf->w : movie_width(mw->movie);
    ch = sf->h < movie_height(mw->movie) ? sf->h : movie_height(mw->movie);
    for (y = 0; y < ch; y++) {
        memcpy(sf->rgb + 3 * (size_t)y * (size_t)sf->w, rgb + 3 * (size_t)y * (size_t)movie_width(mw->movie), (size_t)cw * 3);
        memset(sf->direct + (size_t)y * (size_t)sf->w, 1, (size_t)cw);
        memset(sf->touched + (size_t)y * (size_t)sf->w, 1, (size_t)cw);
    }
    free(rgb);
    mw->shown = index;
    rebuild_alpha(w);
    wm_dirty = 1;
}

static void stop(Window *w, int notify)
{
    MovieWin *mw = mw_of(w);

    if (mw->voice >= 0) {
        sound_stream_stop(mw->voice);
        mw->voice = -1;
    }
    if (mw->playing) {
        mw->playing = 0;
        if (notify && w->parent)
            wm_post(w->parent, MCIWNDM_NOTIFYMODE, w->hwnd, MCI_MODE_STOP);
    }
}

static void play(Window *w)
{
    MovieWin *mw = mw_of(w);
    uint32_t frames = 0, rate = 0;
    int channels = 0;
    int16_t *pcm;

    if (mw->playing)
        return;
    mw->playing = 1;
    mw->t0 = port_now();
    pcm = movie_audio(mw->movie, &frames, &rate, &channels);
    if (pcm)
        mw->voice = sound_stream_start(pcm, frames, rate, channels);
    if (w->parent)
        wm_post(w->parent, MCIWNDM_NOTIFYMODE, w->hwnd, MCI_MODE_PLAY);
    wm_dirty = 1;
}

/* Bring a playing movie to the frame for the clock; at its end it stops. 1 while it is still playing. */
static int advance(Window *w)
{
    MovieWin *mw = mw_of(w);
    int index, n = movie_frames(mw->movie);

    if (!mw->playing)
        return 0;
    index = (int)((port_now() - mw->t0) * movie_fps(mw->movie));
    if (index >= n) {
        show_frame(w, n - 1);
        stop(w, 1);
        return 0;
    }
    show_frame(w, index);
    wm_dirty = 1;                                                  /* keep composing while it plays */
    return 1;
}

/* A window that shows `movie` (the class name tells the game's two kinds apart). The window owns the movie from here on. */
Window *movie_window(const char *cname, uint32_t parent, uint32_t style, int x, int y, Movie *movie)
{
    Window *w = wm_new_window(cname, parent, style, 0, x, y, movie_width(movie), movie_height(movie), "", 0, 0);
    MovieWin *mw = calloc(1, sizeof(*mw));

    mw->movie = movie;
    mw->shown = -1;
    mw->voice = -1;
    w->movie = mw;
    w->visible = (style & WS_VISIBLE) != 0;
    show_frame(w, 0);
    return w;
}

void movie_window_set_transparent(Window *w, int on)
{
    if (!w || !w->movie)
        return;
    mw_of(w)->transparent = on != 0;
    rebuild_alpha(w);
    wm_dirty = 1;
}

const uint8_t *movie_window_alpha(const Window *w) { return w && w->movie ? ((MovieWin *)w->movie)->alpha : NULL; }

void movie_window_move(Window *w, int x, int y)
{
    if (!w || !w->movie)
        return;
    w->x = x;
    w->y = y;
    wm_dirty = 1;
}

int movie_window_playing(Window *w) { return w && w->movie && advance(w); }
void movie_window_play(Window *w) { if (w && w->movie) { mw_of(w)->held = 0; play(w); } }
void movie_window_set_held(Window *w, int on) { if (w && w->movie) { mw_of(w)->held = on != 0; wm_dirty = 1; } }
int movie_window_held(const Window *w) { return w && w->movie && ((MovieWin *)w->movie)->held; }
void movie_window_stop(Window *w) { if (w && w->movie) stop(w, 0); }
int movie_window_frames(const Window *w) { return w && w->movie ? movie_frames(((MovieWin *)w->movie)->movie) : 0; }

/* The composer's call: every playing movie moves on. */
void movie_tick(void)
{
    int i;

    for (i = 0; i < wm_window_count(); i++) {
        Window *w = wm_window_at_index(i);

        if (w && w->movie)
            advance(w);
    }
}

/* what the window manager asks of this layer: the messages the game sends the MCI window, and its destruction */
uint32_t wm_movie_message(Window *w, uint32_t msg, uint32_t wp, uint32_t lp)
{
    (void)wp; (void)lp;
    if (!w->movie)
        return 0;
    if (msg == MCI_PLAY) {
        play(w);
    } else if (msg == MCI_STOP) {
        stop(w, 1);
    } else if (msg == WM_CLOSE) {
        wm_destroy(w->hwnd);
    }
    return 0;
}

void wm_movie_release(Window *w)
{
    MovieWin *mw = mw_of(w);

    if (!mw)
        return;
    stop(w, 0);
    movie_close(mw->movie);
    free(mw->alpha);
    free(mw);
    w->movie = NULL;
}

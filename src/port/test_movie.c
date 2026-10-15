/* test_movie.c - the AVI movies (movie.c): the container, the Video 1 decoder (one colour, two colours, eight colours, skip runs), the sound, and a movie
 * in a window (MCI_PLAY, the clock, the end, WM_CLOSE). The movie is built here: no game files are needed.
 *   make -C src/port test */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <dirent.h>
#include <sys/stat.h>

#include "gdi_int.h"
#include "port.h"
#include "movie.h"
#include "plat.h"
#include "sched.h"
#include "test_util.h"
#include "wm.h"

void kernel32_init(void);
void port_index_functions(void);

static int failures, checks;
#define CHECK(c) do { checks++; if (!(c)) { failures++; printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

typedef struct Buf { uint8_t *p; size_t n, cap; } Buf;
static void put(Buf *b, const void *d, size_t n)
{
    if (b->n + n > b->cap) { b->cap = (b->n + n) * 2; b->p = realloc(b->p, b->cap); }
    memcpy(b->p + b->n, d, n);
    b->n += n;
}
static void p32(Buf *b, uint32_t v) { put(b, &v, 4); }
static void p16(Buf *b, uint32_t v) { put(b, &v, 2); }
static void chunk(Buf *b, const char *tag, const uint8_t *d, uint32_t n)
{
    static const uint8_t pad = 0;

    put(b, tag, 4); p32(b, n); put(b, d, n);
    if (n & 1) put(b, &pad, 1);
}

/* A 16x8 Video 1 movie at 15 fps with 3 frames and 2205 samples of 8 bit mono sound at level 200 (the picture decodes below). */
static uint8_t *make_avi(size_t *len)
{
    Buf b = {0}, hdr = {0};
    static const uint8_t f0[] = {0x00, 0xFC, 0xE0, 0x83, 0x1F, 0x80, 0xFF, 0xFF, 0x04, 0x84};                      /* red, green, blue, white, skip 4 */
    static const uint8_t f1[] = {0x03, 0x84, 0xFF, 0x00, 0x00, 0x7C, 0x1F, 0x00, 0x04, 0x84};                      /* skip 3, red over blue (rows 0 and 1 red), skip 4 */
    static const uint8_t f2[] = {0x01, 0x00, 0x00, 0xFC, 0xE0, 0x03, 0x1F, 0x00, 0x1F, 0x00, 0x1F, 0x00, 0x1F, 0x00, 0x1F, 0x00, 0x07, 0x84};   /* eight colours at block 0 */
    uint8_t snd[2205];
    size_t fix;

    memset(snd, 200, sizeof(snd));
    /* strl video */
    {
        Buf v = {0};

        put(&v, "strl", 4);
        put(&v, "strh", 4); p32(&v, 56); put(&v, "vidsCRAM", 8); { int i; for (i = 0; i < 3; i++) p32(&v, 0); }   /* flags, priority/language, initial frames */
        p32(&v, 1); p32(&v, 15); p32(&v, 0); p32(&v, 3); p32(&v, 0); p32(&v, 0); p32(&v, 0); p32(&v, 0); p32(&v, 0);
        put(&v, "strf", 4); p32(&v, 40); p32(&v, 40); p32(&v, 16); p32(&v, 8); p16(&v, 1); p16(&v, 16); put(&v, "CRAM", 4); { int i; for (i = 0; i < 5; i++) p32(&v, 0); }
        put(&hdr, "LIST", 4); p32(&hdr, (uint32_t)v.n); put(&hdr, v.p, v.n);
        free(v.p);
    }
    /* strl audio */
    {
        Buf a = {0};

        put(&a, "strl", 4);
        put(&a, "strh", 4); p32(&a, 56); put(&a, "audsPCM ", 8); { int i; for (i = 0; i < 3; i++) p32(&a, 0); }
        p32(&a, 1); p32(&a, 22050); p32(&a, 0); p32(&a, 2205); p32(&a, 0); p32(&a, 0); p32(&a, 0); p32(&a, 0); p32(&a, 0);
        put(&a, "strf", 4); p32(&a, 16); p16(&a, 1); p16(&a, 1); p32(&a, 22050); p32(&a, 22050); p16(&a, 1); p16(&a, 8);
        put(&hdr, "LIST", 4); p32(&hdr, (uint32_t)a.n); put(&hdr, a.p, a.n);
        free(a.p);
    }
    put(&b, "RIFF", 4); fix = b.n; p32(&b, 0); put(&b, "AVI ", 4);
    put(&b, "LIST", 4); p32(&b, (uint32_t)hdr.n + 4); put(&b, "hdrl", 4); put(&b, hdr.p, hdr.n);
    {
        Buf mv = {0};

        put(&mv, "movi", 4);
        chunk(&mv, "00dc", f0, sizeof(f0));
        chunk(&mv, "01wb", snd, sizeof(snd));
        chunk(&mv, "00dc", f1, sizeof(f1));
        chunk(&mv, "00dc", f2, sizeof(f2));
        put(&b, "LIST", 4); p32(&b, (uint32_t)mv.n); put(&b, mv.p, mv.n);
        free(mv.p);
    }
    *(uint32_t *)(b.p + fix) = (uint32_t)(b.n - 8);
    free(hdr.p);
    *len = b.n;
    return b.p;
}

static int is(const uint8_t *rgb, int w, int x, int y, int r, int g, int b)
{
    const uint8_t *p = rgb + 3 * ((size_t)y * (size_t)w + (size_t)x);

    return p[0] == r && p[1] == g && p[2] == b;
}

/* The key: black (and the faint noise a decoder leaves on it) is see-through, any colour is not. */
static void test_transparency(void)
{
    static const uint8_t px[] = {0, 0, 0, 8, 8, 8, 9, 0, 0, 0, 200, 0, 0, 0, 12};
    uint8_t alpha[5];
    size_t len;
    uint8_t *avi = make_avi(&len);                           /* (not as arguments of one call: the order they are evaluated in is the compiler's) */
    Movie *m = movie_open_mem(avi, len, "");
    Window *w = movie_window("VIDWINCLASS", 0, WS_POPUP | WS_VISIBLE, 5, 6, m);
    const uint8_t *a;

    movie_key_alpha(px, 5, alpha);
    CHECK(alpha[0] == 0 && alpha[1] == 0 && alpha[2] == 1 && alpha[3] == 1 && alpha[4] == 1);
    CHECK(movie_window_alpha(w) == NULL);                                          /* opaque by default */
    movie_window_set_transparent(w, 1);
    a = movie_window_alpha(w);
    CHECK(a != NULL && a[7 * 16 + 12] == 1 && a[0] == 0);                         /* frame 0: the white block shows, the empty top row does not */
    movie_window_move(w, 30, 40);
    CHECK(w->x == 30 && w->y == 40);
    movie_window_set_transparent(w, 0);
    CHECK(movie_window_alpha(w) == NULL);
    wm_destroy(w->hwnd);
}

static Window *find_video_window(void)
{
    int i;

    for (i = 0; i < wm_window_count(); i++) {
        Window *w = wm_window_at_index(i);

        if (w && w->cname && !strcmp(w->cname, "VIDWINCLASS"))
            return w;
    }
    return NULL;
}

/* MAGVID.DLL's exports the statistics window drives the clips with: load (a missing file is 5), position, transparency, play, status, the background, unload. */
static void test_magvid(void)
{
    char dir[300], path[300];
    uint32_t args[4], slot_at = 0x500100, pos_at = 0x500200, name_at = 0x500000;
    size_t len;
    uint8_t *avi = make_avi(&len);
    FILE *f;
    Window *w;
    int16_t pos[2];
    HostGuestFn load = video_host_fn("LoadAVI"), play = video_host_fn("PlayAVI"), set_pos = video_host_fn("SetVidPos");
    HostGuestFn trans = video_host_fn("SetVidTransparency"), status = video_host_fn("VidStatus"), draw_bg = video_host_fn("DrawVidBackground");
    HostGuestFn unload = video_host_fn("UnloadAVI");
    const char *guest = "C:\\Magic\\Program\\t.avi", *missing = "C:\\Magic\\Program\\none.avi";

    test_tmpdir(dir, sizeof(dir), "test_movie_");
    CHECK(dir[0] != 0);
    snprintf(path, sizeof(path), "%s/Program", dir); plat_mkdir(path);                  /* C:\\Magic\\X is the game folder's X */
    snprintf(path, sizeof(path), "%s/Program/t.avi", dir);
    f = fopen(path, "wb");
    CHECK(f != NULL && fwrite(avi, 1, len, f) == len);
    fclose(f);
    free(avi);
    paths_init(dir, dir);
    CHECK(load && play && set_pos && trans && status && draw_bg && unload);

    memcpy(G + name_at, guest, strlen(guest) + 1);
    pos[0] = 7; pos[1] = 9;
    memcpy(G + pos_at, pos, 4);
    args[0] = name_at; args[1] = slot_at; args[2] = pos_at; args[3] = 1;
    CHECK(load(args) == 0);                                                        /* flags 1: at the position given */
    w = find_video_window();
    CHECK(w != NULL && w->x == 7 && w->y == 9 && !w->visible);                    /* and nothing shows before PlayAVI */
    if (w) {
        uint32_t slot;

        memcpy(&slot, G + slot_at, 4);
        pos[0] = 100; pos[1] = 50;
        memcpy(G + pos_at, pos, 4);
        args[0] = slot; args[1] = pos_at;
        set_pos(args);
        CHECK(w->x == 100 && w->y == 50);                                          /* SetVidPos moves it (the screen position, 16 bit each) */
        args[0] = slot; args[1] = 1;
        trans(args);
        CHECK(movie_window_alpha(w) != NULL);
        args[0] = slot;
        play(args);
        CHECK(w->visible && status(args) == 1);
        draw_bg(args);
        CHECK(w->visible);                                                         /* a clip that is playing is not painted over */
        usleep(300000);                                                            /* 0.2 s of movie */
        CHECK(status(args) == 0);
        draw_bg(args);
        CHECK(w->visible && movie_window_held(w));                                 /* a see-through clip that is over is not drawn any more, but its window stays: STATWIN waits for a click or key on that thread */
        CHECK(wm_key_target() == w->hwnd);                                         /* and keys go to it, as nothing else of that thread can take them */
        {   /* the screen is black while it waits: a click anywhere reaches the clip's thread, press and release alike (it was only a click on the clip's own, undrawn place) */
            char buf[2048];
            FILE *q = tmpfile();
            char want[64];

            CHECK(q != NULL);
            if (q) {
                wm_inject_mouse(IN_DOWN, 900, 700);
                wm_inject_mouse(IN_UP, 900, 700);
                wm_dump_queue(q);
                rewind(q);
                buf[fread(buf, 1, sizeof(buf) - 1, q)] = 0;
                fclose(q);
                snprintf(want, sizeof(want), "[0x%x msg 0x%x ", w->hwnd, 0x201);
                CHECK(strstr(buf, want) != NULL);
                snprintf(want, sizeof(want), "[0x%x msg 0x%x ", w->hwnd, 0x202);
                CHECK(strstr(buf, want) != NULL);
            }
        }
        play(args);
        CHECK(!movie_window_held(w));                                              /* playing it again draws it */
        usleep(300000);
        draw_bg(args);
        CHECK(movie_window_held(w));
        args[0] = 5;
        CHECK(status(args) == 2);                                                  /* a bad handle */
        args[0] = slot;
        unload(args);
        CHECK(find_video_window() == NULL);
    }
    /* centred (flag 2) and a missing file */
    args[0] = name_at; args[1] = slot_at; args[2] = 0; args[3] = 2;
    CHECK(load(args) == 0);
    w = find_video_window();
    CHECK(w != NULL && w->x == (screen_w - 16) / 2 && w->y == (screen_h - 8) / 2);
    {
        uint32_t slot;

        memcpy(&slot, G + slot_at, 4);
        args[0] = slot;
        unload(args);
    }
    memcpy(G + name_at, missing, strlen(missing) + 1);
    args[0] = name_at; args[1] = slot_at; args[2] = 0; args[3] = 1;
    CHECK(load(args) == 5);                                                        /* the game carries on without the clip */
    unlink(path);
    snprintf(path, sizeof(path), "%s/Program", dir); rmdir(path);
    rmdir(dir);
}

/* MOVIE_TEST_GAME=1: every clip on the disc (sources/installed/Magic/Program/Statwin, the installer copies them) opens, with the size and the number of pictures the
 * container says, and its first and a middle picture decode (Indeo 4 needs ffmpeg: without it the clips are skipped here, as the game skips them). */
static void test_game_clips(void)
{
    const char *dir = "../../sources/installed/Magic/Program/Statwin";
    DIR *d;
    struct dirent *e;
    int n = 0, skipped = 0;

    if (!getenv("MOVIE_TEST_GAME") || !(d = opendir(dir)))
        return;
    while ((e = readdir(d))) {
        size_t l = strlen(e->d_name);
        char path[600];
        Movie *m;
        uint8_t *rgb;

        if (l < 5 || strcasecmp(e->d_name + l - 4, ".avi"))
            continue;
        snprintf(path, sizeof(path), "%s/%s", dir, e->d_name);
        m = movie_open(path);
        if (!m) {
            skipped++;
            continue;
        }
        n++;
        CHECK(movie_width(m) > 0 && movie_height(m) > 0 && movie_frames(m) >= 50 && movie_fps(m) > 14.9 && movie_fps(m) < 15.1);
        rgb = malloc((size_t)movie_width(m) * (size_t)movie_height(m) * 3);
        movie_frame(m, 0, rgb);
        movie_frame(m, movie_frames(m) / 2, rgb);
        {
            size_t i, lit = 0;

            for (i = 0; i < (size_t)movie_width(m) * (size_t)movie_height(m); i++)
                lit += rgb[3 * i] > 8 || rgb[3 * i + 1] > 8 || rgb[3 * i + 2] > 8;
            CHECK(lit > 100);                                                      /* something is in the middle of every clip */
        }
        free(rgb);
        movie_close(m);
    }
    closedir(d);
    printf("game clips: %d decoded, %d skipped (no ffmpeg)\n", n, skipped);
}

int main(void)
{
    size_t len;
    uint8_t *avi = make_avi(&len), rgb[16 * 8 * 3];
    Movie *m;
    int16_t out[2 * 64];
    uint32_t frames, rate;
    int channels, i;
    Window *w, *parent;
    Surface *sf;

    guest_init();
    sched_init();
    kernel32_init();
    port_index_functions();

    {
        uint8_t *junk = malloc(8);

        memset(junk, 0, 8);
        CHECK(movie_open_mem(junk, 8, "") == NULL);              /* not an AVI (the buffer is freed) */
    }
    m = movie_open_mem(avi, len, "");
    CHECK(m != NULL);
    CHECK(movie_width(m) == 16 && movie_height(m) == 8 && movie_frames(m) == 3 && movie_fps(m) == 15.0);

    /* frame 0: the bottom block row (the first four blocks) in four colours, the top row not drawn yet */
    movie_frame(m, 0, rgb);
    CHECK(is(rgb, 16, 0, 7, 255, 0, 0) && is(rgb, 16, 3, 4, 255, 0, 0));          /* red: the left block, its rows 4..7 from the top */
    CHECK(is(rgb, 16, 4, 7, 0, 255, 0) && is(rgb, 16, 8, 7, 0, 0, 255) && is(rgb, 16, 12, 7, 255, 255, 255));
    CHECK(is(rgb, 16, 0, 0, 0, 0, 0) && is(rgb, 16, 15, 3, 0, 0, 0));
    /* frame 1: only the last block of the bottom row changes (two colours: its first two rows red, the other two blue) */
    movie_frame(m, 1, rgb);
    CHECK(is(rgb, 16, 12, 7, 255, 0, 0) && is(rgb, 16, 15, 6, 255, 0, 0));
    CHECK(is(rgb, 16, 12, 5, 0, 0, 255) && is(rgb, 16, 12, 4, 0, 0, 255));
    CHECK(is(rgb, 16, 0, 7, 255, 0, 0) && is(rgb, 16, 8, 7, 0, 0, 255));          /* the rest stays */
    /* frame 2: the first block in eight colours (quadrant 0: red where the bit is set, green elsewhere; quadrant 1: blue) */
    movie_frame(m, 2, rgb);
    CHECK(is(rgb, 16, 0, 7, 255, 0, 0));
    CHECK(is(rgb, 16, 1, 7, 0, 255, 0) && is(rgb, 16, 0, 6, 0, 255, 0));
    CHECK(is(rgb, 16, 2, 7, 0, 0, 255));
    /* going back starts again from nothing: frame 0 is what it was */
    movie_frame(m, 0, rgb);
    CHECK(is(rgb, 16, 12, 7, 255, 255, 255) && is(rgb, 16, 1, 7, 255, 0, 0));

    {
        int16_t *pcm = movie_audio(m, &frames, &rate, &channels);

        CHECK(pcm != NULL && frames == 2205 && rate == 22050 && channels == 1 && pcm[0] == (200 - 128) * 256 && pcm[2204] == (200 - 128) * 256);
        free(pcm);
    }

    /* in a window: the first picture is there before the movie plays */
    parent = wm_new_window("TESTPARENT", 0, WS_POPUP | WS_VISIBLE, 0, 0, 0, 100, 100, "p", 0, 0);
    w = movie_window("MCIWndClass", parent->hwnd, WS_CHILD | WS_VISIBLE, 0, 0, m);
    sf = w->surface;
    CHECK(w->movie != NULL && sf && sf->w == 16 && sf->h == 8);
    CHECK(sf->direct[7 * 16 + 12] == 1 && sf->rgb[3 * (7 * 16 + 12)] == 255 && sf->rgb[3 * (7 * 16 + 12) + 1] == 255);       /* frame 0: white */
    CHECK(!movie_window_playing(w));
    sound_set_device(1);
    wm_send(w->hwnd, 0x806, 0, 0);                                                 /* MCI_PLAY */
    CHECK(movie_window_playing(w));
    sound_mix(out, 64);
    CHECK(out[0] == (200 - 128) * 256 && out[1] == (200 - 128) * 256);             /* its sound plays, mono into both sides */
    port_clock_skew += 0.15;                                                                /* 2.25 frames: frame 2 is up (the clock is moved, not slept: a loaded machine would oversleep past the end) */
    CHECK(movie_window_playing(w));
    movie_tick();
    CHECK(sf->rgb[3 * (7 * 16 + 2) + 2] == 255 && sf->rgb[3 * (7 * 16 + 2)] == 0);   /* frame 2's blue at (2, 7) */
    port_clock_skew += 0.15;                                                                /* past the end: it stops by itself, on the last picture */
    movie_tick();
    CHECK(!movie_window_playing(w));
    CHECK(sf->rgb[3 * (7 * 16 + 2) + 2] == 255);
    /* play again, and stop it */
    wm_send(w->hwnd, 0x806, 0, 0);
    CHECK(movie_window_playing(w));
    wm_send(w->hwnd, 0x808, 0, 0);                                                 /* MCI_STOP */
    CHECK(!movie_window_playing(w));
    sound_mix(out, 64);
    for (i = 0; i < 4; i++)
        CHECK(out[i] == 0);                                                        /* silence again */
    /* WM_CLOSE destroys the window and the movie with it */
    {
        uint32_t h = w->hwnd;

        wm_send(h, WM_CLOSE, 0, 0);
        CHECK(wm_window(h) == NULL);
    }
    test_transparency();
    test_magvid();
    test_game_clips();
    printf("%d checks, %d failed\n", checks, failures);
    return failures ? 1 : 0;
}

int pe_find_resource(uint32_t hinst, uint32_t type, uint32_t name, uint32_t *addr, uint32_t *size) { (void)hinst; (void)type; (void)name; (void)addr; (void)size; return 0; }

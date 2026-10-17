/* test_display.c - how the picture is put on a window (display.c, display_cfg.c): the scaling modes and filters, the layout on many displays (with a display scaling factor of 2
 * too), the mouse mapping, the window it starts in, display.cfg, the keys, the controller combination and the on-screen message. Pure: no SDL, no game.
 *   make -C src/port test */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "display.h"
#include "test_util.h"

static int failures, checks;
#define CHECK(c) do { checks++; if (!(c)) { failures++; printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

static int view_is(const DispView *v, int x, int y, int w, int h) { return v->dst.x == x && v->dst.y == y && v->dst.w == w && v->dst.h == h; }

static void test_names(void)
{
    ScaleMode s = SCALE_STRETCH;
    FilterMode f = FILTER_LINEAR;
    int i;

    CHECK(scale_parse("fit", &s) && s == SCALE_FIT);
    CHECK(scale_parse("INTEGER", &s) && s == SCALE_INTEGER);
    CHECK(scale_parse("  Stretch\n", &s) && s == SCALE_STRETCH);
    s = SCALE_INTEGER;
    CHECK(!scale_parse("fill", &s) && s == SCALE_INTEGER);                 /* untouched on failure */
    CHECK(!scale_parse("", &s) && !scale_parse(NULL, &s) && !scale_parse("fitx", &s) && !scale_parse("fi", &s));
    CHECK(filter_parse("nearest", &f) && f == FILTER_NEAREST);
    CHECK(filter_parse("Linear", &f) && f == FILTER_LINEAR);
    CHECK(filter_parse("SHARP ", &f) && f == FILTER_SHARP);
    CHECK(!filter_parse("smooth", &f) && f == FILTER_SHARP);
    CHECK(!filter_parse("", &f) && !filter_parse(NULL, &f));
    for (i = 0; i < SCALE_COUNT; i++) {
        ScaleMode back = SCALE_FIT;

        CHECK(scale_parse(scale_name((ScaleMode)i), &back) && back == (ScaleMode)i);
    }
    for (i = 0; i < FILTER_COUNT; i++) {
        FilterMode back = FILTER_NEAREST;

        CHECK(filter_parse(filter_name((FilterMode)i), &back) && back == (FilterMode)i);
    }
    CHECK(scale_cycle(SCALE_FIT) == SCALE_INTEGER && scale_cycle(SCALE_INTEGER) == SCALE_STRETCH && scale_cycle(SCALE_STRETCH) == SCALE_FIT);
    CHECK(filter_cycle(FILTER_NEAREST) == FILTER_LINEAR && filter_cycle(FILTER_LINEAR) == FILTER_SHARP && filter_cycle(FILTER_SHARP) == FILTER_NEAREST);
    CHECK(DEFAULT_SCALE == SCALE_FIT && DEFAULT_FILTER == FILTER_SHARP);
    CHECK(!strcmp(scale_name((ScaleMode)99), "fit") && !strcmp(filter_name((FilterMode)-1), "sharp"));
}

/* fit is the Steam Deck's rule, unchanged (test_steamdeck.c checks view_scale with the same numbers) */
static void test_fit(void)
{
    int integer, vw, vh;
    double s;

    s = display_fit(1024, 768, 1280, 800, &integer, &vw, &vh);              /* the Deck: 1.04x fractional, 1x whole */
    CHECK(s == 1.0 && integer == 1 && vw == 1024 && vh == 768);
    s = display_fit(1024, 768, 1920, 1080, &integer, &vw, &vh);             /* a television: 1.406x */
    CHECK(s > 1.40 && s < 1.41 && integer == 0 && vw == 1440 && vh == 1080);
    s = display_fit(1024, 768, 3840, 2160, &integer, &vw, &vh);             /* 4K: 2.81x, 2x would use 71% of it */
    CHECK(s > 2.81 && s < 2.82 && integer == 0 && vw == 2880 && vh == 2160);
    s = display_fit(1024, 768, 2048, 1536, &integer, &vw, &vh);
    CHECK(s == 2.0 && integer == 1 && vw == 2048 && vh == 1536);
    s = display_fit(1024, 768, 2100, 1600, &integer, &vw, &vh);             /* 2.05x fractional: 2x uses 97% */
    CHECK(s == 2.0 && integer == 1 && vw == 2048 && vh == 1536);
    s = display_fit(1024, 768, 640, 480, &integer, &vw, &vh);               /* smaller than the picture: fractional, never cut */
    CHECK(s < 0.63 && integer == 0 && vw == 640 && vh == 480);
    s = display_fit(1024, 768, 0, 0, &integer, &vw, &vh);
    CHECK(s == 1.0 && integer == 0 && vw == 1024 && vh == 768);
    CHECK(display_fit(1024, 768, 1280, 800, NULL, NULL, NULL) == 1.0);
}

static void layout(int ow, int oh, ScaleMode m, DispView *v) { display_layout(1024, 768, ow, oh, m, v); }

static void test_layout(void)
{
    DispView v;

    /* fit */
    layout(1280, 800, SCALE_FIT, &v);
    CHECK(view_is(&v, 128, 16, 1024, 768) && v.whole && v.sx == 1.0 && v.sy == 1.0);
    layout(1366, 768, SCALE_FIT, &v);
    CHECK(view_is(&v, 171, 0, 1024, 768) && v.whole);
    layout(1920, 1080, SCALE_FIT, &v);
    CHECK(view_is(&v, 240, 0, 1440, 1080) && !v.whole && v.sx > 1.40 && v.sx < 1.41);
    layout(2560, 1440, SCALE_FIT, &v);
    CHECK(view_is(&v, 320, 0, 1920, 1440) && !v.whole);
    layout(3840, 2160, SCALE_FIT, &v);
    CHECK(view_is(&v, 480, 0, 2880, 2160) && !v.whole);
    layout(2048, 1536, SCALE_FIT, &v);                                       /* a Retina window of 1024x768 points */
    CHECK(view_is(&v, 0, 0, 2048, 1536) && v.whole && v.sx == 2.0);
    layout(1000, 700, SCALE_FIT, &v);                                        /* odd sizes: the shape is kept, never cut */
    CHECK(v.dst.h == 700 && v.dst.w == 933 && v.dst.x == 33 && v.dst.y == 0 && !v.whole);
    layout(1025, 769, SCALE_FIT, &v);
    CHECK(view_is(&v, 0, 0, 1024, 768) && v.whole);
    layout(333, 777, SCALE_FIT, &v);
    CHECK(v.dst.w == 333 && v.dst.h == 250 && v.dst.x == 0 && v.dst.y == 263);
    /* integer: always the largest whole number */
    layout(1280, 800, SCALE_INTEGER, &v);
    CHECK(view_is(&v, 128, 16, 1024, 768) && v.whole);
    layout(1920, 1080, SCALE_INTEGER, &v);
    CHECK(view_is(&v, 448, 156, 1024, 768) && v.whole && v.sx == 1.0);
    layout(2560, 1440, SCALE_INTEGER, &v);
    CHECK(view_is(&v, 768, 336, 1024, 768) && v.whole);
    layout(3840, 2160, SCALE_INTEGER, &v);
    CHECK(view_is(&v, 896, 312, 2048, 1536) && v.whole && v.sx == 2.0);
    layout(5120, 2880, SCALE_INTEGER, &v);                                   /* 3.75x best, 3x whole */
    CHECK(view_is(&v, 1024, 288, 3072, 2304) && v.whole && v.sx == 3.0);
    layout(2047, 1535, SCALE_INTEGER, &v);                                   /* one pixel short of 2x: 1x */
    CHECK(view_is(&v, 511, 383, 1024, 768) && v.whole);
    layout(800, 600, SCALE_INTEGER, &v);                                     /* not even 1x: the whole picture, smaller, rather than a cut one */
    CHECK(v.dst.w <= 800 && v.dst.h <= 600 && v.dst.w * 3 - v.dst.h * 4 < 4 && v.dst.h * 4 - v.dst.w * 3 < 4 && !v.whole);
    /* stretch */
    layout(1920, 1080, SCALE_STRETCH, &v);
    CHECK(view_is(&v, 0, 0, 1920, 1080) && !v.whole && v.sx > 1.87 && v.sx < 1.88 && v.sy > 1.40 && v.sy < 1.41);
    layout(2048, 1536, SCALE_STRETCH, &v);
    CHECK(view_is(&v, 0, 0, 2048, 1536) && v.whole);
    layout(3000, 768, SCALE_STRETCH, &v);
    CHECK(view_is(&v, 0, 0, 3000, 768) && !v.whole);
    /* nothing to lay out in */
    layout(0, 0, SCALE_FIT, &v);
    CHECK(view_is(&v, 0, 0, 1024, 768));
    /* other picture sizes (the game also runs at 800x600 and 640x480) */
    display_layout(640, 480, 1920, 1080, SCALE_FIT, &v);                     /* 2.25x fractional; 2x uses 89%: fractional */
    CHECK(view_is(&v, 240, 0, 1440, 1080) && !v.whole);
    display_layout(640, 480, 1280, 960, SCALE_FIT, &v);
    CHECK(view_is(&v, 0, 0, 1280, 960) && v.whole && v.sx == 2.0);
    display_layout(800, 600, 1920, 1080, SCALE_INTEGER, &v);
    CHECK(view_is(&v, 560, 240, 800, 600) && v.whole);
    /* the picture always lies inside the output, for every mode and a spread of sizes */
    {
        static const int sizes[][2] = {{1280, 800}, {1366, 768}, {1920, 1080}, {2560, 1440}, {3840, 2160}, {5120, 2880}, {2048, 1536}, {1000, 700}, {333, 777}, {1, 1}, {4096, 4096}, {1281, 801}, {7680, 4320}};
        int i, m;

        for (i = 0; i < (int)(sizeof(sizes) / sizeof(sizes[0])); i++)
            for (m = 0; m < SCALE_COUNT; m++) {
                layout(sizes[i][0], sizes[i][1], (ScaleMode)m, &v);
                CHECK(v.dst.x >= 0 && v.dst.y >= 0 && v.dst.w >= 1 && v.dst.h >= 1 && v.dst.x + v.dst.w <= sizes[i][0] && v.dst.y + v.dst.h <= sizes[i][1]);
                CHECK(v.dst.x == (sizes[i][0] - v.dst.w) / 2 && v.dst.y == (sizes[i][1] - v.dst.h) / 2);        /* centred */
            }
    }
}

static void test_prescale(void)
{
    CHECK(display_prescale(1024, 1024, 8, 0) == 1);
    CHECK(display_prescale(1024, 800, 8, 0) == 1);                           /* shown smaller: no enlargement */
    CHECK(display_prescale(1024, 1440, 8, 0) == 2);                          /* 1.41x: enlarged by 2 first */
    CHECK(display_prescale(1024, 2048, 8, 0) == 2);
    CHECK(display_prescale(1024, 2049, 8, 0) == 3);
    CHECK(display_prescale(1024, 2880, 8, 0) == 3);                          /* 4K: 2.81x */
    CHECK(display_prescale(1024, 5000, 4, 0) == 4);                          /* the cap */
    CHECK(display_prescale(1024, 3000, 8, 2048) == 2);                       /* a texture size limit: 1024 * 3 would not fit */
    CHECK(display_prescale(1024, 3000, 8, 1000) == 1);
    CHECK(display_prescale(0, 100, 8, 0) == 1);
}

/* the mouse: a window point to a picture pixel */
static void test_mapping(void)
{
    static const struct { int ow, oh, ww, wh; ScaleMode m; } cfgs[] = {
        {1024, 768, 1024, 768, SCALE_FIT}, {1280, 800, 1280, 800, SCALE_FIT}, {1366, 768, 1366, 768, SCALE_FIT}, {1920, 1080, 1920, 1080, SCALE_FIT},
        {2560, 1440, 2560, 1440, SCALE_FIT}, {3840, 2160, 3840, 2160, SCALE_FIT}, {1920, 1080, 1920, 1080, SCALE_INTEGER}, {3840, 2160, 3840, 2160, SCALE_INTEGER},
        {1920, 1080, 1920, 1080, SCALE_STRETCH}, {3000, 768, 3000, 768, SCALE_STRETCH},
        {2048, 1536, 1024, 768, SCALE_FIT},                                 /* Retina: a 1024x768-point window is 2048x1536 pixels */
        {2880, 1800, 1440, 900, SCALE_FIT}, {2880, 1800, 1440, 900, SCALE_INTEGER}, {2880, 1800, 1440, 900, SCALE_STRETCH},
        {3840, 2160, 1920, 1080, SCALE_FIT}, {3840, 2160, 1920, 1080, SCALE_INTEGER},   /* a 1920x1080-point window on a 200% display */
        {2560, 1600, 1280, 800, SCALE_FIT}, {1500, 1000, 1200, 800, SCALE_FIT},          /* 125% */
        {1501, 999, 1201, 799, SCALE_FIT},                                              /* odd sizes */
    };
    DispView v;
    size_t i;
    int px, py, wx, wy, x, y;

    for (i = 0; i < sizeof(cfgs) / sizeof(cfgs[0]); i++) {
        int ow = cfgs[i].ow, oh = cfgs[i].oh, ww = cfgs[i].ww, wh = cfgs[i].wh;
        double per_point_x, per_point_y;
        int bad = 0, tested = 0;

        display_layout(1024, 768, ow, oh, cfgs[i].m, &v);
        per_point_x = v.sx * ow / ww;                                         /* picture pixels per window point, the other way round: */
        per_point_y = v.sy * oh / wh;
        /* the middle of the picture is the middle of the window (+- a point), the corners of the picture are inside it */
        CHECK(display_to_screen(&v, 1024, 768, ow, oh, ww, wh, ww / 2, wh / 2, &px, &py) && px >= 510 && px <= 513 && py >= 382 && py <= 385);
        /* a round trip: every picture pixel that a point is at least as big as comes back as itself */
        if (per_point_x >= 1.0 && per_point_y >= 1.0)
            for (y = 0; y < 768; y += 7)
                for (x = 0; x < 1024; x += 5) {
                    display_to_window(&v, 1024, 768, ow, oh, ww, wh, x, y, &wx, &wy);
                    tested++;
                    if (!display_to_screen(&v, 1024, 768, ow, oh, ww, wh, wx, wy, &px, &py) || px != x || py != y)
                        bad++;
                }
        CHECK(bad == 0);
        CHECK(tested > 0 || per_point_x < 1.0 || per_point_y < 1.0);
        /* the button the game draws at (528, 493) is hit at the point it is drawn at */
        display_to_window(&v, 1024, 768, ow, oh, ww, wh, 528, 493, &wx, &wy);
        CHECK(display_to_screen(&v, 1024, 768, ow, oh, ww, wh, wx, wy, &px, &py));
        CHECK(abs(px - 528) <= 1 && abs(py - 493) <= 1);
    }
    /* the bars: outside the picture, with the numbers an unclamped mapping gives */
    display_layout(1024, 768, 1280, 800, SCALE_FIT, &v);
    CHECK(display_to_screen(&v, 1024, 768, 1280, 800, 1280, 800, 0, 0, &px, &py) == 0 && px == -128 && py == -16);
    CHECK(display_to_screen(&v, 1024, 768, 1280, 800, 1280, 800, 127, 400, &px, &py) == 0 && px == -1);
    CHECK(display_to_screen(&v, 1024, 768, 1280, 800, 1280, 800, 128, 16, &px, &py) == 1 && px == 0 && py == 0);
    CHECK(display_to_screen(&v, 1024, 768, 1280, 800, 1280, 800, 1151, 783, &px, &py) == 1 && px == 1023 && py == 767);
    CHECK(display_to_screen(&v, 1024, 768, 1280, 800, 1280, 800, 1152, 400, &px, &py) == 0 && px == 1024);
    /* stretch maps the whole window onto the whole picture, each axis on its own */
    display_layout(1024, 768, 1920, 1080, SCALE_STRETCH, &v);
    CHECK(display_to_screen(&v, 1024, 768, 1920, 1080, 1920, 1080, 0, 0, &px, &py) && px == 0 && py == 0);
    CHECK(display_to_screen(&v, 1024, 768, 1920, 1080, 1920, 1080, 1919, 1079, &px, &py) && px == 1023 && py == 767);
    CHECK(display_to_screen(&v, 1024, 768, 1920, 1080, 1920, 1080, 960, 540, &px, &py) && px == 512 && py == 384);
    /* Retina, integer scale: points count double. A window of 1440x900 points (2880x1800 pixels), 2x whole: the picture is 2048x1536 pixels = 1024x768 points, at 416,132 points */
    display_layout(1024, 768, 2880, 1800, SCALE_INTEGER, &v);
    CHECK(view_is(&v, 416, 132, 2048, 1536));
    CHECK(display_to_screen(&v, 1024, 768, 2880, 1800, 1440, 900, 208, 66, &px, &py) && px == 0 && py == 0);
    CHECK(display_to_screen(&v, 1024, 768, 2880, 1800, 1440, 900, 207, 66, &px, &py) == 0);
    CHECK(display_to_screen(&v, 1024, 768, 2880, 1800, 1440, 900, 208 + 1023, 66 + 767, &px, &py) && px == 1023 && py == 767);
    /* SDL's renderer may already have turned the events' positions into render pixels (front_sdl.c, "mouse units"): the window's size in that unit is the drawable's, and the same point on the screen maps to the same
     * picture pixel as when the events are in points */
    display_layout(1024, 768, 2880, 1800, SCALE_FIT, &v);
    {
        static const int pts[][2] = {{0, 0}, {700, 450}, {1439, 899}, {208, 66}, {515, 340}};
        size_t k;

        for (k = 0; k < sizeof(pts) / sizeof(pts[0]); k++) {
            int ax, ay, bx, by;

            display_to_screen(&v, 1024, 768, 2880, 1800, 1440.0, 900.0, pts[k][0], pts[k][1], &ax, &ay);                          /* in points */
            display_to_screen(&v, 1024, 768, 2880, 1800, 2880.0, 1800.0, pts[k][0] * 2, pts[k][1] * 2, &bx, &by);                /* the same place, in pixels (the upper left pixel of the point) */
            CHECK(abs(ax - bx) <= 1 && abs(ay - by) <= 1);
        }
        display_layout(1024, 768, 2048, 1536, SCALE_FIT, &v);
        CHECK(display_to_screen(&v, 1024, 768, 2048, 1536, 2048.0, 1536.0, 1056, 986, &px, &py) && px == 528 && py == 493);       /* events in pixels on a Retina window: the Start New Game button */
        CHECK(display_to_screen(&v, 1024, 768, 2048, 1536, 1024.0, 768.0, 528, 493, &px, &py) && px == 528 && py == 493);        /* events in points */
        display_to_window(&v, 1024, 768, 2048, 1536, 2048.0, 1536.0, 528, 493, &wx, &wy);
        CHECK(wx == 1057 && wy == 987);
        display_to_window(&v, 1024, 768, 2048, 1536, 1024.0, 768.0, 528, 493, &wx, &wy);
        CHECK(wx == 528 && wy == 493);
        CHECK(display_to_screen(&v, 1024, 768, 2048, 1536, 1536.0, 1152.0, 528, 493, &px, &py) && px == 352 && py == 329);        /* 1.5 pixels per point, events in points of such a window */
    }
    /* unknown sizes: the point is the pixel */
    CHECK(display_to_screen(&v, 1024, 768, 0, 0, 0, 0, 5, 6, &px, &py) && px == 5 && py == 6);
}

static void test_window(void)
{
    int w, h;

    /* the usual displays: the largest whole multiple that fits 90% of what is free (usable area in points, dpi = pixels per point) */
    display_initial_window(1024, 768, 1366, 728, 1.0, &w, &h);                /* a 1366x768 laptop less a taskbar: not even 1x fits, 90% of the area, shape kept */
    CHECK(w == 874 && h == 655);
    display_initial_window(1024, 768, 1280, 760, 1.0, &w, &h);                /* a Deck in desktop mode */
    CHECK(w == 912 && h == 684);
    display_initial_window(1024, 768, 1440, 875, 2.0, &w, &h);                /* a 13" MacBook: 2x in pixels = 1024x768 points */
    CHECK(w == 1024 && h == 768);
    display_initial_window(1024, 768, 1920, 1040, 1.0, &w, &h);               /* 1080p */
    CHECK(w == 1024 && h == 768);
    display_initial_window(1024, 768, 2560, 1400, 1.0, &w, &h);               /* 1440p: 2x needs 1536 of 1260 */
    CHECK(w == 1024 && h == 768);
    display_initial_window(1024, 768, 3840, 2120, 1.0, &w, &h);               /* 4K at 100% */
    CHECK(w == 2048 && h == 1536);
    display_initial_window(1024, 768, 1920, 1060, 2.0, &w, &h);               /* 4K at 200%: 3840x2120 pixels, 2x = 1024x768 points */
    CHECK(w == 1024 && h == 768);
    display_initial_window(1024, 768, 2560, 1400, 2.0, &w, &h);               /* 5K at 200%: 5120x2800 pixels, 3x */
    CHECK(w == 1536 && h == 1152);
    display_initial_window(1024, 768, 1536, 824, 1.25, &w, &h);               /* 1920x1080 at 125%: 1x pixels = 819x614 points */
    CHECK(w == 819 && h == 614);
    display_initial_window(1024, 768, 7680, 4320, 1.0, &w, &h);               /* 8K: 5x */
    CHECK(w == 5120 && h == 3840);
    display_initial_window(640, 480, 1366, 728, 1.0, &w, &h);                 /* the original's size on a laptop: 1x */
    CHECK(w == 640 && h == 480);
    display_initial_window(1024, 768, 500, 300, 1.0, &w, &h);                 /* a tiny display */
    CHECK(w <= 500 && h <= 300 && w >= 256 && h >= 192);
    display_initial_window(1024, 768, 10, 10, 1.0, &w, &h);                   /* absurd: not below a quarter, not larger than the display */
    CHECK(w <= 10 && h <= 10);
    display_initial_window(1024, 768, 0, 0, 1.0, &w, &h);                     /* unknown: the picture's own size */
    CHECK(w == 1024 && h == 768);
    display_initial_window(1024, 768, 0, 0, 2.0, &w, &h);
    CHECK(w == 512 && h == 384);
    display_initial_window(1024, 768, 1920, 1040, 0.0, &w, &h);              /* unknown dpi counts as 1 */
    CHECK(w == 1024 && h == 768);
    /* never larger than the display, whole-number scales are whole in pixels */
    {
        static const int usable[][2] = {{1280, 760}, {1366, 728}, {1440, 875}, {1920, 1040}, {2560, 1400}, {3840, 2120}, {800, 560}, {1024, 740}, {1025, 693}};
        static const double dpis[] = {1.0, 1.25, 1.5, 2.0, 3.0};
        size_t i, j;

        for (i = 0; i < sizeof(usable) / sizeof(usable[0]); i++)
            for (j = 0; j < sizeof(dpis) / sizeof(dpis[0]); j++) {
                display_initial_window(1024, 768, usable[i][0], usable[i][1], dpis[j], &w, &h);
                CHECK(w <= usable[i][0] && h <= usable[i][1] && w * 3 - h * 4 < 8 && h * 4 - w * 3 < 8);
                CHECK(w <= usable[i][0] * 0.9 + 1 && h <= usable[i][1] * 0.9 + 1);
            }
    }
    /* the smallest window */
    display_min_window(1024, 768, 1.0, 1024, 768, &w, &h);
    CHECK(w == 1024 && h == 768);
    display_min_window(1024, 768, 2.0, 1024, 768, &w, &h);                    /* Retina: 1x pixels = 512x384 points */
    CHECK(w == 512 && h == 384);
    display_min_window(1024, 768, 1.5, 1024, 768, &w, &h);
    CHECK(w == 683 && h == 512);
    display_min_window(1024, 768, 1.0, 874, 655, &w, &h);                     /* the display could not hold 1x: no larger than the start */
    CHECK(w == 874 && h == 655);
    display_min_window(1024, 768, 1.0, 700, 525, &w, &h);                     /* PORT_WINDOW=700x525 */
    CHECK(w == 700 && h == 525);
    display_min_window(1024, 768, 1.0, 0, 0, &w, &h);
    CHECK(w == 1024 && h == 768);
    /* a saved place that is on no display is not restored */
    {
        static const DispRect one[] = {{0, 0, 1920, 1080}};
        static const DispRect two[] = {{0, 0, 1920, 1080}, {1920, 0, 1280, 1024}};

        CHECK(display_pos_ok(100, 50, 1024, 768, one, 1, 64));
        CHECK(display_pos_ok(-900, 50, 1024, 768, one, 1, 64) == 1);          /* 124 points of it are on the display */
        CHECK(!display_pos_ok(-1000, 50, 1024, 768, one, 1, 64));
        CHECK(!display_pos_ok(2000, 50, 1024, 768, one, 1, 64));              /* the second display is gone */
        CHECK(display_pos_ok(2000, 50, 1024, 768, two, 2, 64));
        CHECK(!display_pos_ok(100, 1060, 1024, 768, one, 1, 64));             /* hanging off the bottom */
        CHECK(display_pos_ok(100, 1000, 1024, 768, one, 1, 64));
        CHECK(!display_pos_ok(0, 0, 100, 100, NULL, 0, 64));
        CHECK(display_pos_ok(0, 0, 50, 50, one, 1, 64));                      /* a window smaller than `need` is judged by its own size */
    }
}

static void test_cfg_text(void)
{
    DisplayCfg c, d;
    char buf[2048];
    int n;

    dcfg_init(&c);
    CHECK(!c.has_fullscreen && !c.has_scale && !c.has_filter && !c.has_window && !c.has_pos && c.scale == SCALE_FIT && c.filter == FILTER_SHARP);
    CHECK(dcfg_parse("", &c) == 0 && dcfg_parse("\n\n\n", &c) == 0 && dcfg_parse(NULL, &c) == 0);
    CHECK(dcfg_parse("fullscreen=1\nscale=integer\nfilter=nearest\nwindow=1280x800\nposition=-20,35\n", &c) == 5);
    CHECK(c.has_fullscreen && c.fullscreen == 1 && c.has_scale && c.scale == SCALE_INTEGER && c.has_filter && c.filter == FILTER_NEAREST);
    CHECK(c.has_window && c.win_w == 1280 && c.win_h == 800 && c.has_pos && c.win_x == -20 && c.win_y == 35);
    /* formatting and reading it back */
    n = dcfg_format(&c, buf, sizeof(buf));
    CHECK(n > 0 && (size_t)n == strlen(buf));
    CHECK(strstr(buf, "fullscreen=1\n") && strstr(buf, "scale=integer\n") && strstr(buf, "filter=nearest\n") && strstr(buf, "window=1280x800\n") && strstr(buf, "position=-20,35\n"));
    dcfg_init(&d);
    CHECK(dcfg_parse(buf, &d) == 5);
    CHECK(d.fullscreen == 1 && d.scale == SCALE_INTEGER && d.filter == FILTER_NEAREST && d.win_w == 1280 && d.win_h == 800 && d.win_x == -20 && d.win_y == 35);
    CHECK(dcfg_format(&c, buf, 40) == -1 && dcfg_format(&c, buf, 0) == -1);                 /* too small: refused, not cut */
    /* only what is set is written */
    dcfg_init(&c);
    c.has_scale = 1;
    c.scale = SCALE_STRETCH;
    n = dcfg_format(&c, buf, sizeof(buf));
    CHECK(strstr(buf, "scale=stretch\n") && !strstr(buf, "fullscreen=") && !strstr(buf, "window=") && !strstr(buf, "filter=") && !strstr(buf, "position="));
    /* tolerance */
    dcfg_init(&c);
    CHECK(dcfg_parse("  FullScreen = Yes \r\n# a comment\n; another\nScale=FIT\r\nfilter =  Sharp\r\n", &c) == 3);        /* case, blanks, CRLF, comments */
    CHECK(c.fullscreen == 1 && c.scale == SCALE_FIT && c.filter == FILTER_SHARP && c.has_filter);
    dcfg_init(&c);
    CHECK(dcfg_parse("fullscreen=maybe\nscale=big\nfilter=\nwindow=axb\nposition=1;2\nfoo=bar\njust a line\n=\n===\n", &c) == 0);        /* bad values, unknown keys, junk */
    CHECK(!c.has_fullscreen && !c.has_scale && !c.has_filter && !c.has_window && !c.has_pos);
    dcfg_init(&c);
    CHECK(dcfg_parse("window=100x100\n", &c) == 0 && !c.has_window);                            /* below the least window */
    CHECK(dcfg_parse("window=99999x99999\n", &c) == 0 && !c.has_window);
    CHECK(dcfg_parse("window=1024x\n", &c) == 0 && dcfg_parse("window=x768\n", &c) == 0 && dcfg_parse("window=1024\n", &c) == 0);
    CHECK(dcfg_parse("window=1024 x 768\n", &c) == 1 && c.win_w == 1024 && c.win_h == 768);
    CHECK(dcfg_parse("position=100000,5\n", &c) == 0 && c.win_x == 0);
    dcfg_init(&c);
    CHECK(dcfg_parse("scale=integer\nscale=stretch\nscale=bogus\n", &c) == 2 && c.scale == SCALE_STRETCH);        /* the last good one wins */
    dcfg_init(&c);
    CHECK(dcfg_parse("version=7\nsomething=new\nfilter=linear\nfuture_setting=1\n", &c) == 1 && c.filter == FILTER_LINEAR);   /* a file of another version: what is understood still counts */
    dcfg_init(&c);
    CHECK(dcfg_parse("fullscreen=1\nfilter=linea", &c) == 1 && c.fullscreen == 1 && !c.has_filter);               /* cut short, no newline at the end */
    dcfg_init(&c);
    {
        char junk[300];
        int i;

        for (i = 0; i < (int)sizeof(junk) - 1; i++)
            junk[i] = (char)(i % 7 == 0 ? '\n' : 1 + (i * 37) % 250);
        junk[sizeof(junk) - 1] = 0;
        dcfg_parse(junk, &c);                                                                    /* must not crash; what it takes is not our business */
        memset(junk, 'a', sizeof(junk) - 1);
        CHECK(dcfg_parse(junk, &c) == 0);                                                         /* one very long line */
    }
    dcfg_init(&c);
    CHECK(dcfg_parse("fullscreen=0\n", &c) == 1 && c.has_fullscreen && c.fullscreen == 0);
    CHECK(dcfg_parse("fullscreen=true\n", &c) == 1 && c.fullscreen == 1);
    CHECK(dcfg_parse("fullscreen=off\n", &c) == 1 && c.fullscreen == 0);
}

static void test_cfg_files(void)
{
    char dir[600], sub[700], path[800], buf[200];
    DisplayCfg c, d;
    FILE *f;

    test_tmpdir(dir, sizeof(dir), "pentamoor_disp");
    CHECK(dir[0]);
    if (!dir[0])
        return;
    /* no file: the defaults, nothing created */
    CHECK(dcfg_load(dir, &c) == 0 && !c.has_fullscreen && !c.has_scale && !c.has_window);
    snprintf(path, sizeof(path), "%s/%s", dir, DISPLAY_CFG_NAME);
    CHECK((f = fopen(path, "rb")) == NULL);
    /* write, read */
    dcfg_init(&c);
    c.has_fullscreen = 1; c.fullscreen = 1; c.has_scale = 1; c.scale = SCALE_INTEGER; c.has_window = 1; c.win_w = 1111; c.win_h = 833; c.has_pos = 1; c.win_x = 12; c.win_y = -3;
    CHECK(dcfg_save(dir, &c) == 1);
    CHECK(dcfg_load(dir, &d) == 4 && d.fullscreen == 1 && d.scale == SCALE_INTEGER && d.win_w == 1111 && d.win_h == 833 && d.win_x == 12 && d.win_y == -3 && !d.has_filter);
    snprintf(path, sizeof(path), "%s/%s.tmp", dir, DISPLAY_CFG_NAME);
    CHECK((f = fopen(path, "rb")) == NULL);                                  /* no temporary file left */
    /* saving again replaces */
    c.scale = SCALE_STRETCH;
    CHECK(dcfg_save(dir, &c) == 1 && dcfg_load(dir, &d) == 4 && d.scale == SCALE_STRETCH);
    /* the folder does not exist yet (a first run): it and its parents are made, and only the one file is in it */
    snprintf(sub, sizeof(sub), "%s/a/b", dir);
    CHECK(dcfg_save(sub, &c) == 1 && dcfg_load(sub, &d) == 4);
    snprintf(path, sizeof(path), "%s/a/b/%s", dir, DISPLAY_CFG_NAME);
    CHECK((f = fopen(path, "rb")) != NULL);
    if (f) {
        size_t n = fread(buf, 1, sizeof(buf), f);

        fclose(f);
        CHECK(n > 0);
    }
    /* a corrupt file: binary, empty, truncated, outdated */
    snprintf(path, sizeof(path), "%s/%s", dir, DISPLAY_CFG_NAME);
    f = fopen(path, "wb");
    if (f) {
        fwrite("\x00\x01\x02\xff\xfe scale=integer\n", 1, 20, f);
        fclose(f);
    }
    CHECK(dcfg_load(dir, &d) == 0 && !d.has_scale && d.scale == SCALE_FIT);
    f = fopen(path, "wb");
    if (f)
        fclose(f);
    CHECK(dcfg_load(dir, &d) == 0 && !d.has_scale);
    f = fopen(path, "wb");
    if (f) {
        fputs("scale=integer\nfilter=sha", f);
        fclose(f);
    }
    CHECK(dcfg_load(dir, &d) == 1 && d.scale == SCALE_INTEGER && !d.has_filter);
    f = fopen(path, "wb");
    if (f) {
        fputs("# written by an older Pentamoor\nzoom=2\nscale=fit\nfullscreen=1\nmonitor=2\n", f);
        fclose(f);
    }
    CHECK(dcfg_load(dir, &d) == 2 && d.scale == SCALE_FIT && d.fullscreen == 1);
    /* a very long file: what fits is read, nothing overflows */
    f = fopen(path, "wb");
    if (f) {
        int i;

        fputs("scale=stretch\n", f);
        for (i = 0; i < 2000; i++)
            fputs("# padding padding padding padding padding padding\n", f);
        fputs("filter=linear\n", f);
        fclose(f);
    }
    CHECK(dcfg_load(dir, &d) == 1 && d.scale == SCALE_STRETCH && !d.has_filter);
    /* a folder that cannot be made (a file is in the way): refused, no crash */
    snprintf(sub, sizeof(sub), "%s/%s/x", dir, DISPLAY_CFG_NAME);
    CHECK(dcfg_save(sub, &c) == 0);
    test_rmtree(dir);
}

static void test_resolve(void)
{
    DisplayCfg file;
    DisplaySettings s;
    char warn[256];

    dcfg_init(&file);
    /* no file, no environment */
    display_resolve(&file, NULL, NULL, NULL, NULL, 0, &s, warn, sizeof(warn));
    CHECK(s.fullscreen == 0 && s.scale == SCALE_FIT && s.filter == FILTER_SHARP && !s.has_window && !s.has_pos && !warn[0]);
    display_resolve(NULL, NULL, NULL, NULL, NULL, 0, &s, NULL, 0);                              /* no file at all, no warning buffer */
    CHECK(s.fullscreen == 0 && s.scale == SCALE_FIT);
    /* the Steam Deck is full screen by itself */
    display_resolve(&file, NULL, NULL, NULL, NULL, 1, &s, warn, sizeof(warn));
    CHECK(s.fullscreen == 1);
    /* the file */
    CHECK(dcfg_parse("fullscreen=0\nscale=stretch\nfilter=linear\nwindow=1200x900\nposition=40,50\n", &file) == 5);
    display_resolve(&file, NULL, NULL, NULL, NULL, 1, &s, warn, sizeof(warn));                  /* ... wins over the Deck's default */
    CHECK(s.fullscreen == 0 && s.scale == SCALE_STRETCH && s.filter == FILTER_LINEAR && s.has_window && s.win_w == 1200 && s.win_h == 900 && !s.win_env && s.has_pos && s.win_x == 40 && s.win_y == 50);
    /* the environment wins over the file */
    display_resolve(&file, "1", "integer", "NEAREST", "800x600", 0, &s, warn, sizeof(warn));
    CHECK(s.fullscreen == 1 && s.scale == SCALE_INTEGER && s.filter == FILTER_NEAREST && s.win_w == 800 && s.win_h == 600 && s.win_env && !warn[0]);
    CHECK(s.has_pos && s.win_x == 40);
    display_resolve(&file, "0", NULL, NULL, NULL, 1, &s, warn, sizeof(warn));                   /* PORT_FULLSCREEN=0 wins on a Deck */
    CHECK(s.fullscreen == 0);
    dcfg_init(&file);
    dcfg_parse("fullscreen=1\n", &file);
    display_resolve(&file, "0", NULL, NULL, NULL, 0, &s, warn, sizeof(warn));
    CHECK(s.fullscreen == 0);
    display_resolve(&file, "", NULL, NULL, NULL, 0, &s, warn, sizeof(warn));                    /* empty means no, as PORT_FULLSCREEN always did */
    CHECK(s.fullscreen == 0);
    display_resolve(&file, "off", NULL, NULL, NULL, 0, &s, warn, sizeof(warn));
    CHECK(s.fullscreen == 0);
    display_resolve(&file, "false", NULL, NULL, NULL, 0, &s, warn, sizeof(warn));
    CHECK(s.fullscreen == 0);
    display_resolve(&file, "yes", NULL, NULL, NULL, 0, &s, warn, sizeof(warn));
    CHECK(s.fullscreen == 1);
    dcfg_init(&file);
    display_resolve(&file, "2", NULL, NULL, NULL, 0, &s, warn, sizeof(warn));
    CHECK(s.fullscreen == 1);
    /* bad values in the environment are ignored (and said so), the rest still counts */
    dcfg_parse("scale=integer\nfilter=nearest\n", &file);
    display_resolve(&file, NULL, "huge", "smooth", "1024", 0, &s, warn, sizeof(warn));
    CHECK(s.scale == SCALE_INTEGER && s.filter == FILTER_NEAREST && !s.has_window);
    CHECK(strstr(warn, "PORT_SCALE") && strstr(warn, "PORT_FILTER") && strstr(warn, "PORT_WINDOW"));
    display_resolve(&file, NULL, "", "", "", 0, &s, warn, sizeof(warn));                        /* empty is "not set" for these */
    CHECK(s.scale == SCALE_INTEGER && !warn[0]);
    display_resolve(&file, NULL, "stretch", NULL, "50x50", 0, &s, warn, sizeof(warn));          /* a window below the least one is refused */
    CHECK(s.scale == SCALE_STRETCH && !s.has_window && strstr(warn, "PORT_WINDOW"));
}

static void test_update(void)
{
    DisplayCfg file;
    DisplaySettings start, now;

    dcfg_init(&file);
    dcfg_parse("scale=stretch\nfilter=nearest\nfullscreen=0\n", &file);
    display_resolve(&file, NULL, NULL, NULL, NULL, 0, &start, NULL, 0);
    now = start;
    /* nothing changed: the file keeps what it had (no window geometry known) */
    display_cfg_update(&file, &start, &now);
    CHECK(file.has_scale && file.scale == SCALE_STRETCH && file.has_filter && file.filter == FILTER_NEAREST && file.has_fullscreen && file.fullscreen == 0 && !file.has_window && !file.has_pos);
    /* the player changed things */
    now.scale = SCALE_FIT;
    now.fullscreen = 1;
    now.has_window = 1; now.win_w = 1300; now.win_h = 900; now.has_pos = 1; now.win_x = 7; now.win_y = 8;
    display_cfg_update(&file, &start, &now);
    CHECK(file.scale == SCALE_FIT && file.filter == FILTER_NEAREST && file.fullscreen == 1 && file.has_window && file.win_w == 1300 && file.win_h == 900 && file.has_pos && file.win_x == 7);
    /* a setting that came from the environment and was not touched stays out of the file */
    dcfg_init(&file);
    display_resolve(&file, "1", "integer", "linear", "700x500", 0, &start, NULL, 0);
    now = start;
    now.has_pos = 1; now.win_x = 3; now.win_y = 4;
    display_cfg_update(&file, &start, &now);
    CHECK(!file.has_fullscreen && !file.has_scale && !file.has_filter && !file.has_window && file.has_pos && file.win_x == 3);
    now.win_w = 900;                                                          /* ... until the player resizes the window */
    now.win_h = 700;
    display_cfg_update(&file, &start, &now);
    CHECK(file.has_window && file.win_w == 900);
    now.filter = FILTER_SHARP;                                                /* a changed setting is kept even if the environment set it */
    display_cfg_update(&file, &start, &now);
    CHECK(file.has_filter && file.filter == FILTER_SHARP);
}

static void test_keys(void)
{
    /* Alt+Enter and F11: full screen; Ctrl+F11: scaling; Shift+F11: filter */
    CHECK(display_key_action(DK_RETURN, 1, 0, 0) == DA_FULLSCREEN);
    CHECK(display_key_action(DK_F11, 0, 0, 0) == DA_FULLSCREEN);
    CHECK(display_key_action(DK_F11, 0, 1, 0) == DA_SCALE);
    CHECK(display_key_action(DK_F11, 0, 0, 1) == DA_FILTER);
    /* everything else is the game's: Enter alone is the default button of a dialog */
    CHECK(display_key_action(DK_RETURN, 0, 0, 0) == DA_NONE);
    CHECK(display_key_action(DK_RETURN, 0, 1, 0) == DA_NONE);
    CHECK(display_key_action(DK_RETURN, 0, 0, 1) == DA_NONE);
    CHECK(display_key_action(DK_RETURN, 1, 1, 0) == DA_NONE);
    CHECK(display_key_action(DK_RETURN, 1, 0, 1) == DA_NONE);
    CHECK(display_key_action(DK_F11, 1, 0, 0) == DA_NONE);
    CHECK(display_key_action(DK_F11, 0, 1, 1) == DA_NONE);
    CHECK(display_key_action(DK_F11, 1, 1, 1) == DA_NONE);
    CHECK(display_key_action(DK_OTHER, 0, 0, 0) == DA_NONE && display_key_action(DK_OTHER, 1, 1, 1) == DA_NONE);
}

static void test_combo(void)
{
    DispCombo c = {0, 0, 0};

    CHECK(display_combo_step(&c, 0, 0, 100) == 0);
    CHECK(display_combo_step(&c, 1, 0, 200) == 0 && display_combo_step(&c, 1, 0, 5000) == 0);          /* one stick alone never */
    CHECK(display_combo_step(&c, 0, 1, 6000) == 0 && display_combo_step(&c, 0, 1, 9000) == 0);
    CHECK(display_combo_step(&c, 1, 1, 10000) == 0);                                                    /* both just pressed */
    CHECK(display_combo_step(&c, 1, 1, 10500) == 0);
    CHECK(display_combo_step(&c, 1, 1, 10999) == 0);
    CHECK(display_combo_step(&c, 1, 1, 11000) == 1);                                                    /* held a second */
    CHECK(display_combo_step(&c, 1, 1, 11008) == 0 && display_combo_step(&c, 1, 1, 14000) == 0);        /* once per hold */
    CHECK(display_combo_step(&c, 1, 0, 14010) == 0);                                                    /* let go ... */
    CHECK(display_combo_step(&c, 1, 1, 14020) == 0);                                                    /* ... and again */
    CHECK(display_combo_step(&c, 1, 1, 15019) == 0 && display_combo_step(&c, 1, 1, 15020) == 1);
    CHECK(display_combo_step(&c, 0, 0, 15030) == 0);
    CHECK(display_combo_step(&c, 1, 1, 15040) == 0 && display_combo_step(&c, 0, 1, 15500) == 0 && display_combo_step(&c, 1, 1, 16200) == 0);   /* released in between: starts again */
    CHECK(display_combo_step(&c, 0, 0, 1) == 0);
    CHECK(display_combo_step(&c, 1, 1, 0) == 0 && display_combo_step(&c, 1, 1, DISPLAY_COMBO_MS) == 1);   /* a clock that reads 0 */
    {
        DispCombo w = {0, 0, 0};

        CHECK(display_combo_step(&w, 1, 1, 0xFFFFFF00u) == 0);                                          /* the clock wraps */
        CHECK(display_combo_step(&w, 1, 1, 0xFFFFFF00u + DISPLAY_COMBO_MS) == 1);
    }
}

static void test_notice(void)
{
    char buf[100];

    CHECK(!display_notice_get(1000, buf, sizeof(buf)));
    display_notice("Scaling: integer, filter: sharp", 5000);
    CHECK(display_notice_get(5000, buf, sizeof(buf)) && !strcmp(buf, "Scaling: integer, filter: sharp"));
    CHECK(display_notice_get(6000, buf, sizeof(buf)));
    CHECK(display_notice_get(5000 + DISPLAY_NOTICE_MS - 1, buf, sizeof(buf)));
    CHECK(!display_notice_get(5000 + DISPLAY_NOTICE_MS, buf, sizeof(buf)));                              /* about 1.5 s */
    display_notice("again", 20000);
    CHECK(display_notice_get(20100, buf, sizeof(buf)) && !strcmp(buf, "again"));
    display_notice("a message that is far too long to fit the buffer of the message line, which is ninety-six bytes, so it is cut short and still ends", 30000);
    CHECK(display_notice_get(30001, buf, sizeof(buf)) && strlen(buf) == 95);
    CHECK(display_notice_get(30001, buf, 8) && strlen(buf) == 7);
    display_notice_text(SCALE_INTEGER, FILTER_SHARP, buf, sizeof(buf));
    CHECK(!strcmp(buf, "Scaling: integer, filter: sharp"));
    display_notice_text(SCALE_STRETCH, FILTER_NEAREST, buf, sizeof(buf));
    CHECK(!strcmp(buf, "Scaling: stretch, filter: nearest"));
}

int main(void)
{
    test_names();
    test_fit();
    test_layout();
    test_prescale();
    test_mapping();
    test_window();
    test_cfg_text();
    test_cfg_files();
    test_resolve();
    test_update();
    test_keys();
    test_combo();
    test_notice();
    printf("test_display: %d checks, %d failed\n", checks, failures);
    return failures ? 1 : 0;
}

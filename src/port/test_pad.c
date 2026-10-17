/* test_pad.c - the controller logic (pad.c): the dead zone and the response curve, the cursor's speed and its independence of the frame rate and the screen's size, clamping, what each
 * button does, walking, keys that repeat, the mouse taking the cursor back, and the arrow that is drawn. No SDL and no game: the logic is pure.
 *   make -C src/port test */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "pad.h"

static int failures, checks;
#define CHECK(c) do { checks++; if (!(c)) { failures++; printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

static int near_int(int a, int b, int tol) { return abs(a - b) <= tol; }

/* run `ms` of time in steps of `step` ms */
static void run(Pad *p, int ms, int step, PadOut *out)
{
    int t;

    for (t = 0; t < ms; t += step)
        pad_step(p, step < ms - t ? step : ms - t, out);
}

static int count(const PadOut *o, int type)
{
    int i, n = 0;

    for (i = 0; i < o->n; i++)
        n += o->act[i].type == type;
    return n;
}

static const PadAct *first(const PadOut *o, int type)
{
    int i;

    for (i = 0; i < o->n; i++)
        if (o->act[i].type == type)
            return &o->act[i];
    return NULL;
}

static void axis(Pad *p, int a, double v, PadOut *out) { pad_axis(p, a, (int)(v * 32767), out); }

static void test_stick(void)
{
    float ox, oy, len, last = 0, v;
    int i;

    CHECK(pad_stick(0, 0, &ox, &oy) == 0 && ox == 0 && oy == 0);
    CHECK(pad_stick(0.2f, 0, &ox, &oy) == 0 && ox == 0);              /* inside the dead zone */
    CHECK(pad_stick(0.15f, 0.15f, &ox, &oy) == 0);                    /* the dead zone is round: (0.15, 0.15) has length 0.212 */
    len = pad_stick(0.23f, 0, &ox, &oy);
    CHECK(len > 0 && len < 0.01f && ox > 0);                           /* just outside: nearly nothing (no jump at the edge) */
    len = pad_stick(1, 0, &ox, &oy);
    CHECK(fabsf(len - 1) < 1e-4f && fabsf(ox - 1) < 1e-4f && fabsf(oy) < 1e-4f);
    len = pad_stick(1, 1, &ox, &oy);                                   /* a square gate's corner is no faster than full */
    CHECK(fabsf(len - 1) < 1e-4f && fabsf(ox - 0.7071f) < 1e-3f && fabsf(oy - 0.7071f) < 1e-3f);
    len = pad_stick(-0.6f, 0.8f, &ox, &oy);                            /* the direction is the stick's */
    CHECK(len > 0 && ox < 0 && oy > 0 && fabsf(oy / ox + 4.0f / 3) < 1e-3f);
    for (i = 0, v = 0.23f; v <= 1.0f; v += 0.01f, i++) {               /* grows with the push, never down */
        len = pad_stick(v, 0, &ox, &oy);
        CHECK(len >= last);
        last = len;
    }
    CHECK(pad_stick(0.6f, 0, &ox, &oy) < 0.6f * 0.5f);                  /* the curve: small pushes are small (a push of 0.6 is well under half the speed) */
    /* speed: in screen widths per second */
    CHECK(near_int((int)pad_speed(1, 1024, 0, 0), 1024, 1));
    CHECK(near_int((int)pad_speed(1, 640, 0, 0), 640, 1));
    CHECK(pad_speed(1, 1024, 1, 0) < pad_speed(1, 1024, 0, 0) && pad_speed(1, 1024, 0, 1) > pad_speed(1, 1024, 0, 0));
}

static void test_dir8(void)
{
    CHECK(pad_dir8(0, 0, -1) == -1 && pad_dir8(0.4f, 0, -1) == -1);    /* below the threshold to start */
    CHECK(pad_dir8(0.4f, 0, 2) == 2);                                  /* but enough to stay */
    CHECK(pad_dir8(0, -1, -1) == 0 && pad_dir8(1, -1, -1) == 1 && pad_dir8(1, 0, -1) == 2 && pad_dir8(1, 1, -1) == 3);
    CHECK(pad_dir8(0, 1, -1) == 4 && pad_dir8(-1, 1, -1) == 5 && pad_dir8(-1, 0, -1) == 6 && pad_dir8(-1, -1, -1) == 7);
    CHECK(pad_dir8(0.1f, -1, -1) == 0 && pad_dir8(-0.1f, -1, -1) == 0);   /* a little off an axis is still that axis */
    CHECK(pad_clamp(-3, 0, 9) == 0 && pad_clamp(12, 0, 9) == 9 && pad_clamp(4, 0, 9) == 4);
}

static void test_table(void)
{
    int n, i, j;
    const PadBind *b = pad_bindings(&n);

    CHECK(n >= 10);
    for (i = 0; i < n; i++) {
        CHECK(b[i].btn >= 0 && b[i].btn < PAD_NBUTTONS);
        CHECK(b[i].act != PB_KEY || (b[i].vk && b[i].sc));
        for (j = i + 1; j < n; j++)
            CHECK(b[i].btn != b[j].btn);                                /* a control does one thing */
    }
}

static void test_cursor(void)
{
    Pad p, q, r;
    PadOut out;
    int x1, x8, x33, i;

    pad_init(&p, 1024, 768);
    CHECK(p.ix == 512 && p.iy == 384 && !p.active);
    out.n = 0;
    pad_step(&p, 100, &out);                                           /* nothing is moved before the pad is used */
    CHECK(out.n == 0);
    axis(&p, PAD_AX_LX, 0.1, &out);                                    /* drift: not use */
    CHECK(!p.active);
    pad_step(&p, 100, &out);
    CHECK(out.n == 0);

    /* the same distance whatever the frame rate: 300 ms of half a push, in steps of 1, 8 and 33 ms */
    for (i = 0; i < 3; i++) {
        Pad *c = i == 0 ? &p : i == 1 ? &q : &r;

        pad_init(c, 1024, 768);
        out.n = 0;
        axis(c, PAD_AX_LX, 0.6, &out);
        CHECK(c->active);
        run(c, 300, i == 0 ? 1 : i == 1 ? 8 : 33, &out);
    }
    x1 = p.ix; x8 = q.ix; x33 = r.ix;
    CHECK(x1 > 520 && near_int(x1, x8, 2) && near_int(x1, x33, 2));
    {   /* the number: speed(len) * 0.3 s */
        float ox, oy, len = pad_stick(0.6f, 0, &ox, &oy);

        CHECK(near_int(x8, 512 + (int)(pad_speed(len, 1024, 0, 0) * 0.3f), 2));
    }
    CHECK(near_int(p.iy, 384, 0));

    /* the same trip across a screen of another size (speed is in screen widths) */
    pad_init(&p, 640, 480);
    pad_init(&q, 1024, 768);
    out.n = 0;
    axis(&p, PAD_AX_LX, -0.8, &out);
    axis(&q, PAD_AX_LX, -0.8, &out);
    run(&p, 200, 8, &out);
    run(&q, 200, 8, &out);
    CHECK(near_int((320 - p.ix) * 1024, (512 - q.ix) * 640, 3 * 1024));

    /* diagonals: both axes move, and never past the edges */
    pad_init(&p, 1024, 768);
    out.n = 0;
    axis(&p, PAD_AX_LX, 1.0, &out);
    axis(&p, PAD_AX_LY, 1.0, &out);
    run(&p, 5000, 8, &out);
    CHECK(p.ix == 1023 && p.iy == 767);
    axis(&p, PAD_AX_LX, -1.0, &out);
    axis(&p, PAD_AX_LY, -1.0, &out);
    run(&p, 5000, 8, &out);
    CHECK(p.ix == 0 && p.iy == 0);
    CHECK(count(&out, PA_MOVE) > 10);
    for (i = 0; i < out.n; i++)
        if (out.act[i].type == PA_MOVE)
            CHECK(out.act[i].x >= 0 && out.act[i].x < 1024 && out.act[i].y >= 0 && out.act[i].y < 768);
    axis(&p, PAD_AX_LX, 0, &out);
    axis(&p, PAD_AX_LY, 0, &out);
    out.n = 0;
    run(&p, 100, 8, &out);
    CHECK(out.n == 0);                                                 /* a stick at rest moves nothing */

    /* the slow modifier (left trigger) and the fast one (right stick pressed) */
    pad_init(&p, 1024, 768);
    pad_init(&q, 1024, 768);
    pad_init(&r, 1024, 768);
    out.n = 0;
    axis(&p, PAD_AX_LX, 1.0, &out);
    axis(&q, PAD_AX_LX, 1.0, &out);
    axis(&q, PAD_AX_LT, 1.0, &out);
    axis(&r, PAD_AX_LX, 1.0, &out);
    pad_button(&r, PAD_RSTICK, 1, &out);
    run(&p, 100, 8, &out);
    run(&q, 100, 8, &out);
    run(&r, 100, 8, &out);
    CHECK(near_int((q.ix - 512) * 4, p.ix - 512, 6) && near_int((r.ix - 512), (p.ix - 512) * 2, 6));
    axis(&q, PAD_AX_LT, 0, &out);                                      /* let go of the trigger: full speed again */
    {
        int before = q.ix;

        run(&q, 100, 8, &out);
        CHECK(near_int(q.ix - before, p.ix - 512, 3));
    }
}

static void test_buttons(void)
{
    Pad p;
    PadOut out;
    const PadAct *a;

    pad_init(&p, 1024, 768);
    out.n = 0;
    pad_button(&p, PAD_A, 1, &out);                                    /* A: the left button, at the cursor */
    CHECK(p.active && out.n == 1 && out.act[0].type == PA_LDOWN && out.act[0].x == 512 && out.act[0].y == 384);
    pad_button(&p, PAD_A, 1, &out);                                    /* the same state again: nothing */
    CHECK(out.n == 1);
    axis(&p, PAD_AX_LX, 1.0, &out);                                    /* held: a drag, the cursor moves with it down */
    run(&p, 100, 8, &out);
    CHECK(count(&out, PA_MOVE) > 3 && p.left_src);
    pad_button(&p, PAD_A, 0, &out);
    a = first(&out, PA_LUP);
    CHECK(a && a->x == p.ix && a->y == p.iy && p.left_src == 0);
    pad_button(&p, PAD_A, 0, &out);
    CHECK(count(&out, PA_LUP) == 1);

    out.n = 0;
    pad_button(&p, PAD_B, 1, &out);                                    /* B: the right button */
    pad_button(&p, PAD_B, 0, &out);
    CHECK(out.n == 2 && out.act[0].type == PA_RDOWN && out.act[1].type == PA_RUP && out.act[0].x == p.ix);

    out.n = 0;
    pad_button(&p, PAD_X, 1, &out);                                    /* X, Start, Back: Enter and Escape as the game takes them (Y is a double click) */
    pad_button(&p, PAD_X, 0, &out);
    CHECK(out.n == 2 && out.act[0].type == PA_KEYDOWN && out.act[0].vk == 13 && out.act[0].sc == 0x1C && out.act[0].ch == 13 && out.act[0].repeat == 0);
    CHECK(out.act[1].type == PA_KEYUP && out.act[1].vk == 13 && out.act[1].sc == 0x1C);
    pad_init(&p, 1024, 768);                                           /* a pad at rest, so that the steps move nothing */
    out.n = 0;
    pad_button(&p, PAD_Y, 1, &out);                                    /* Y: a double click, never Escape: the press goes down at once, up after 90 ms, down again after 70, up after 90 */
    CHECK(out.n == 1 && out.act[0].type == PA_LDOWN);
    pad_button(&p, PAD_Y, 0, &out);                                    /* letting go of Y changes nothing; the sequence runs by itself */
    CHECK(out.n == 1);
    pad_step(&p, 80, &out);
    CHECK(out.n == 1);
    pad_step(&p, 20, &out);
    CHECK(out.n == 2 && out.act[1].type == PA_LUP);
    pad_step(&p, 50, &out);
    CHECK(out.n == 2);
    pad_step(&p, 20, &out);
    CHECK(out.n == 3 && out.act[2].type == PA_LDOWN);
    pad_step(&p, 100, &out);
    CHECK(out.n == 4 && out.act[3].type == PA_LUP && p.left_src == 0 && p.dbl.phase == 0);
    CHECK(out.act[0].x == out.act[2].x && out.act[0].y == out.act[2].y);   /* both presses at the same place */
    out.n = 0;
    pad_button(&p, PAD_Y, 1, &out);                                    /* a big time step runs the whole thing: two presses and two releases */
    pad_button(&p, PAD_Y, 0, &out);
    pad_step(&p, 1000, &out);
    CHECK(count(&out, PA_LDOWN) == 2 && count(&out, PA_LUP) == 2 && p.dbl.phase == 0);
    out.n = 0;
    pad_button(&p, PAD_Y, 1, &out);                                    /* pressed again while it runs: ignored; unplugging in the middle lets the button go */
    pad_button(&p, PAD_Y, 0, &out);
    pad_button(&p, PAD_Y, 1, &out);
    CHECK(count(&out, PA_LDOWN) == 1);
    pad_release_all(&p, &out);
    CHECK(count(&out, PA_LUP) == 1 && p.left_src == 0 && p.dbl.phase == 0);
    pad_step(&p, 500, &out);
    CHECK(count(&out, PA_LDOWN) == 1);                                 /* nothing more after the release */
    out.n = 0;
    pad_button(&p, PAD_START, 1, &out);
    pad_button(&p, PAD_START, 0, &out);
    pad_button(&p, PAD_BACK, 1, &out);
    pad_button(&p, PAD_BACK, 0, &out);
    CHECK(out.n == 4 && out.act[0].vk == 13 && out.act[2].vk == 27);
    out.n = 0;
    pad_button(&p, PAD_GUIDE, 1, &out);                                /* the guide button is ignored */
    pad_button(&p, PAD_GUIDE, 0, &out);
    CHECK(out.n == 0);
    pad_button(&p, PAD_LSTICK, 1, &out);                               /* the left stick pressed in: Space */
    pad_button(&p, PAD_LSTICK, 0, &out);
    CHECK(out.n == 2 && out.act[0].vk == 32 && out.act[0].sc == 0x39 && out.act[0].ch == 32);

    /* the bumpers: Page Up and Page Down, repeating while held */
    axis(&p, PAD_AX_LX, 0, &out);
    out.n = 0;
    pad_button(&p, PAD_LB, 1, &out);
    CHECK(out.n == 1 && out.act[0].vk == 0x21 && out.act[0].sc == 0x49 && out.act[0].ch == -1);
    run(&p, 300, 10, &out);
    CHECK(out.n == 1);                                                 /* not before the delay */
    run(&p, 800, 10, &out);                                            /* 1100 ms in all: repeats at 400, 470, ... */
    CHECK(count(&out, PA_KEYDOWN) >= 9 && count(&out, PA_KEYDOWN) <= 12 && out.act[1].repeat == 1);
    pad_button(&p, PAD_LB, 0, &out);
    CHECK(out.act[out.n - 1].type == PA_KEYUP && out.act[out.n - 1].vk == 0x21);
    out.n = 0;
    pad_button(&p, PAD_RB, 1, &out);
    pad_button(&p, PAD_RB, 0, &out);
    CHECK(out.n == 2 && out.act[0].vk == 0x22 && out.act[0].sc == 0x51);
    out.n = 0;                                                         /* Enter is not repeated */
    pad_button(&p, PAD_X, 1, &out);
    run(&p, 1000, 10, &out);
    CHECK(out.n == 1);
    pad_button(&p, PAD_X, 0, &out);

    /* the D-pad is the arrow keys: a key down, repeating after the delay as a keyboard's do, and up on release; the cursor stays where it is */
    pad_init(&p, 1024, 768);
    out.n = 0;
    pad_button(&p, PAD_DRIGHT, 1, &out);
    CHECK(out.n == 1 && out.act[0].type == PA_KEYDOWN && out.act[0].vk == 39 && out.act[0].sc == 0x4D && out.act[0].repeat == 0);
    pad_button(&p, PAD_DUP, 1, &out);
    CHECK(out.n == 2 && out.act[1].type == PA_KEYDOWN && out.act[1].vk == 38 && out.act[1].sc == 0x48);
    pad_button(&p, PAD_DUP, 0, &out);
    CHECK(out.act[out.n - 1].type == PA_KEYUP && out.act[out.n - 1].vk == 38);
    out.n = 0;
    run(&p, 300, 10, &out);
    CHECK(out.n == 0);                                                 /* not before the delay (400 ms) */
    run(&p, 400, 10, &out);
    CHECK(count(&out, PA_KEYDOWN) >= 3 && out.act[0].repeat == 1 && out.act[0].vk == 39);
    pad_button(&p, PAD_DRIGHT, 0, &out);
    CHECK(out.act[out.n - 1].type == PA_KEYUP && out.act[out.n - 1].vk == 39);
    out.n = 0;
    run(&p, 500, 10, &out);
    CHECK(out.n == 0 && p.ix == 512 && p.iy == 384);
    out.n = 0;
    pad_button(&p, PAD_DDOWN, 1, &out);
    pad_button(&p, PAD_DLEFT, 1, &out);
    CHECK(out.n == 2 && out.act[0].vk == 40 && out.act[0].sc == 0x50 && out.act[1].vk == 37 && out.act[1].sc == 0x4B);
    pad_button(&p, PAD_DDOWN, 0, &out);
    pad_button(&p, PAD_DLEFT, 0, &out);
}

/* the D-pad in a duel or a dialog: a press asks for the next target in that direction (PA_NAV, from where the pointer is), repeating while held, with no key; elsewhere it is the arrow key */
/* Back is Escape; where a tap of Escape leaves the game with no question (the title menu) it has to be held PAD_BACK_HOLD_MS */
static int guard_on;
static int guard(void) { return guard_on; }

static void test_back_guard(void)
{
    Pad p;
    PadOut out;

    pad_init(&p, 1024, 768);
    out.n = 0;
    pad_set_back_guard(guard);
    guard_on = 0;                                                      /* anywhere else: a plain tap, as before */
    pad_button(&p, PAD_BACK, 1, &out);
    pad_button(&p, PAD_BACK, 0, &out);
    CHECK(out.n == 2 && out.act[0].type == PA_KEYDOWN && out.act[0].vk == 27 && out.act[1].type == PA_KEYUP);
    guard_on = 1;                                                      /* the title menu: a tap does nothing, not even later */
    out.n = 0;
    pad_button(&p, PAD_BACK, 1, &out);
    run(&p, PAD_BACK_HOLD_MS - 100, 10, &out);
    pad_button(&p, PAD_BACK, 0, &out);
    run(&p, 1000, 10, &out);
    CHECK(out.n == 0);
    pad_button(&p, PAD_BACK, 1, &out);                                 /* held long enough: the key goes down once, and comes up with the button */
    run(&p, PAD_BACK_HOLD_MS - 20, 10, &out);
    CHECK(out.n == 0);
    run(&p, 60, 10, &out);
    CHECK(out.n == 1 && out.act[0].type == PA_KEYDOWN && out.act[0].vk == 27 && out.act[0].sc == 0x01 && out.act[0].repeat == 0);
    run(&p, 2000, 10, &out);
    CHECK(out.n == 1);                                                 /* no repeats */
    pad_button(&p, PAD_BACK, 0, &out);
    CHECK(out.n == 2 && out.act[1].type == PA_KEYUP && out.act[1].vk == 27);
    out.n = 0;                                                         /* the pad let go of (unplugged) while Back is being held: nothing comes later */
    pad_button(&p, PAD_BACK, 1, &out);
    pad_release_all(&p, &out);
    run(&p, 1000, 10, &out);
    CHECK(out.n == 0);
    guard_on = 0;                                                      /* the guard is asked when Back is pressed: a screen change while it is held changes nothing */
    out.n = 0;
    pad_button(&p, PAD_BACK, 1, &out);
    CHECK(out.n == 1 && out.act[0].type == PA_KEYDOWN);
    pad_button(&p, PAD_BACK, 0, &out);
    pad_set_back_guard(NULL);                                          /* no guard installed: always a tap */
    guard_on = 1;
    out.n = 0;
    pad_button(&p, PAD_BACK, 1, &out);
    pad_button(&p, PAD_BACK, 0, &out);
    CHECK(out.n == 2);
}

static void test_nav(void)
{
    Pad p;
    PadOut out;
    int i;

    pad_init(&p, 1024, 768);
    pad_set_nav(&p, 1);
    out.n = 0;
    pad_button(&p, PAD_DDOWN, 1, &out);
    CHECK(out.n == 1 && out.act[0].type == PA_NAV && out.act[0].dir == 1 && out.act[0].x == 512 && out.act[0].y == 384 && out.act[0].repeat == 0);
    CHECK(p.active);
    pad_button(&p, PAD_DDOWN, 0, &out);
    CHECK(out.n == 1);                                                 /* letting go sends nothing: there was no key */
    out.n = 0;
    pad_button(&p, PAD_DUP, 1, &out);
    pad_button(&p, PAD_DLEFT, 1, &out);
    pad_button(&p, PAD_DRIGHT, 1, &out);
    CHECK(out.n == 3 && out.act[0].dir == 0 && out.act[1].dir == 2 && out.act[2].dir == 3);       /* up, left, right: the numbers of nav.h's NAV_UP, NAV_LEFT, NAV_RIGHT */
    pad_button(&p, PAD_DUP, 0, &out);
    pad_button(&p, PAD_DLEFT, 0, &out);
    pad_button(&p, PAD_DRIGHT, 0, &out);
    CHECK(out.n == 3 && count(&out, PA_KEYDOWN) == 0 && count(&out, PA_KEYUP) == 0);

    /* held: after 400 ms, a request every 150 ms, marked as a repeat; the pointer in each is where it is by then */
    out.n = 0;
    pad_button(&p, PAD_DRIGHT, 1, &out);
    run(&p, 390, 10, &out);
    CHECK(out.n == 1);
    run(&p, 20, 10, &out);
    CHECK(out.n == 2 && out.act[1].type == PA_NAV && out.act[1].repeat == 1 && out.act[1].dir == 3);
    pad_put(&p, 700, 300, &out);
    run(&p, 150, 10, &out);
    CHECK(out.act[out.n - 1].type == PA_NAV && out.act[out.n - 1].x == 700 && out.act[out.n - 1].y == 300);
    run(&p, 450, 10, &out);
    CHECK(count(&out, PA_NAV) >= 5 && count(&out, PA_NAV) <= 7);
    pad_button(&p, PAD_DRIGHT, 0, &out);
    i = out.n;
    run(&p, 600, 10, &out);
    CHECK(out.n == i);                                                 /* nothing after the release */

    /* the answer: the pointer is put somewhere, and the game is told as for any move */
    pad_init(&p, 1024, 768);
    out.n = 0;
    pad_put(&p, 300, 200, &out);
    CHECK(out.n == 1 && out.act[0].type == PA_MOVE && out.act[0].x == 300 && out.act[0].y == 200 && p.ix == 300 && p.iy == 200);
    out.n = 0;
    pad_put(&p, 300, 200, &out);
    CHECK(out.n == 0);                                                 /* not twice for the same place */
    pad_put(&p, 5000, -5, &out);
    CHECK(p.ix == 1023 && p.iy == 0);                                  /* kept on the screen */

    /* the mode of the press is the mode of its whole hold: the arrow key goes down and comes up as a key even if the game has targets by then, and the other way */
    pad_init(&p, 1024, 768);
    out.n = 0;
    pad_button(&p, PAD_DDOWN, 1, &out);                                /* no targets: the key */
    CHECK(out.n == 1 && out.act[0].type == PA_KEYDOWN && out.act[0].vk == 40);
    pad_set_nav(&p, 1);
    run(&p, 500, 10, &out);
    CHECK(count(&out, PA_NAV) == 0 && count(&out, PA_KEYDOWN) >= 2);   /* its repeats are keys */
    pad_button(&p, PAD_DDOWN, 0, &out);
    CHECK(out.act[out.n - 1].type == PA_KEYUP && out.act[out.n - 1].vk == 40);
    out.n = 0;
    pad_button(&p, PAD_DDOWN, 1, &out);                                /* targets: a request */
    pad_set_nav(&p, 0);
    run(&p, 600, 10, &out);
    pad_button(&p, PAD_DDOWN, 0, &out);
    CHECK(count(&out, PA_NAV) >= 2 && count(&out, PA_KEYDOWN) == 0 && count(&out, PA_KEYUP) == 0);

    /* "scroll": the arrow key of the direction, tapped */
    {
        static const struct { int dir; uint32_t vk, sc; } keys[4] = {{0, 38, 0x48}, {1, 40, 0x50}, {2, 37, 0x4B}, {3, 39, 0x4D}};

        for (i = 0; i < 4; i++) {
            out.n = 0;
            pad_tap_dir(&p, keys[i].dir, &out);
            CHECK(out.n == 2 && out.act[0].type == PA_KEYDOWN && out.act[0].vk == keys[i].vk && out.act[0].sc == keys[i].sc && out.act[1].type == PA_KEYUP && out.act[1].vk == keys[i].vk);
        }
    }

    /* the pointer taken by the mouse, or the pad unplugged, ends the hold */
    pad_init(&p, 1024, 768);
    pad_set_nav(&p, 1);
    out.n = 0;
    pad_button(&p, PAD_DUP, 1, &out);
    pad_release_all(&p, &out);
    i = out.n;
    run(&p, 800, 10, &out);
    CHECK(out.n == i);
}

static void test_triggers_and_arrows(void)
{
    Pad p;
    PadOut out;

    pad_init(&p, 1024, 768);
    out.n = 0;
    CHECK(pad_axis(&p, PAD_AX_LT, 4000, &out) == 0 && !(p.down & (1u << PAD_LT)));         /* a light touch is not a press */
    CHECK(pad_axis(&p, PAD_AX_LT, 30000, &out) == 1 && (p.down & (1u << PAD_LT)));
    CHECK(pad_axis(&p, PAD_AX_LT, 12000, &out) == 0 && (p.down & (1u << PAD_LT)));         /* it stays down until well released (a hysteresis) */
    pad_axis(&p, PAD_AX_LT, 2000, &out);
    CHECK(!(p.down & (1u << PAD_LT)));

    /* the right stick is the arrow keys, and the keypad diagonals the castles read */
    pad_init(&p, 1024, 768);
    out.n = 0;
    CHECK(pad_axis(&p, PAD_AX_RX, 3000, &out) == 0 && out.n == 0 && !p.active);
    CHECK(pad_axis(&p, PAD_AX_RX, 32000, &out) == 1 && out.n == 1 && out.act[0].type == PA_KEYDOWN && out.act[0].vk == 39 && out.act[0].sc == 0x4D);
    CHECK(pad_axis(&p, PAD_AX_RX, 32000, &out) == 0 && out.n == 1);                        /* the same direction: no new key */
    pad_axis(&p, PAD_AX_RY, -32000, &out);                                                 /* up-right: Page Up */
    CHECK(out.n == 3 && out.act[1].type == PA_KEYUP && out.act[1].vk == 39 && out.act[2].type == PA_KEYDOWN && out.act[2].vk == 0x21 && out.act[2].sc == 0x49);
    run(&p, 500, 10, &out);
    CHECK(out.n > 3 && out.act[3].type == PA_KEYDOWN && out.act[3].repeat == 1 && out.act[3].vk == 0x21);
    axis(&p, PAD_AX_RX, 0, &out);
    axis(&p, PAD_AX_RY, 0, &out);
    CHECK(out.act[out.n - 1].type == PA_KEYUP && out.act[out.n - 1].vk == 38 && p.dir8 == -1);        /* up-right to up (the stick came back along one axis) to nothing */
    {
        static const uint32_t want[8] = {38, 0x21, 39, 0x22, 40, 0x23, 37, 0x24};
        static const double dx[8] = {0, 1, 1, 1, 0, -1, -1, -1}, dy[8] = {-1, -1, 0, 1, 1, 1, 0, -1};
        int d;

        for (d = 0; d < 8; d++) {
            pad_init(&p, 1024, 768);
            out.n = 0;
            axis(&p, PAD_AX_RX, dx[d], &out);
            axis(&p, PAD_AX_RY, dy[d], &out);
            CHECK(out.act[out.n - 1].type == PA_KEYDOWN && out.act[out.n - 1].vk == want[d]);
        }
    }
}

static void test_walk(void)
{
    Pad p;
    PadOut out;
    const PadAct *m, *d;

    pad_init(&p, 1024, 768);
    out.n = 0;
    axis(&p, PAD_AX_LX, 1.0, &out);
    axis(&p, PAD_AX_RT, 1.0, &out);                                    /* the walk button held, the stick pushed: walking */
    CHECK(p.active && (p.down & (1u << PAD_RT)));
    pad_step(&p, 8, &out);
    m = first(&out, PA_MOVE);
    d = first(&out, PA_LDOWN);
    CHECK(m && d && m < d && p.walking);                                                    /* the pointer goes ahead of the avatar first, then the button goes down */
    CHECK(p.ox == 512 && p.oy == 300);                                                     /* the game's own place for the party on the map */
    CHECK(near_int(p.ix, 512 + 154, 1) && p.iy == 300 && d->x == p.ix && d->y == p.iy);     /* 0.15 of the screen's width from the avatar */
    CHECK(p.left_src == 2);
    run(&p, 200, 8, &out);
    CHECK(count(&out, PA_LDOWN) == 1 && count(&out, PA_LUP) == 0 && near_int(p.ix, 666, 1));   /* held, one press */
    axis(&p, PAD_AX_LX, 0, &out);                                      /* the stick back: the button comes up */
    CHECK(count(&out, PA_LUP) == 1 && !p.walking && p.left_src == 0);

    /* any direction, aimed from where the avatar is */
    pad_init(&p, 1024, 768);
    pad_set_origin(&p, 400, 300);
    out.n = 0;
    axis(&p, PAD_AX_RT, 1.0, &out);
    axis(&p, PAD_AX_LX, -0.7, &out);
    axis(&p, PAD_AX_LY, -0.7, &out);
    pad_step(&p, 8, &out);
    CHECK(near_int(p.ix, 400 - 109, 2) && near_int(p.iy, 300 - 109, 2));                    /* up-left, the same distance whatever the push (it is a direction) */
    axis(&p, PAD_AX_LX, 0.3, &out);
    axis(&p, PAD_AX_LY, 0.0, &out);
    pad_step(&p, 8, &out);
    CHECK(near_int(p.ix, 400 + 154, 1) && p.iy == 300 && count(&out, PA_LDOWN) == 1);        /* turned: still one press, the pointer moved */
    axis(&p, PAD_AX_RT, 0, &out);                                      /* the walk button let go while walking: up */
    CHECK(count(&out, PA_LUP) == 1 && p.left_src == 0);
    pad_step(&p, 8, &out);
    CHECK(p.left_src == 0 && count(&out, PA_LDOWN) == 1);              /* and the stick is a cursor again */

    /* the target stays on the screen: an avatar at the edge */
    pad_init(&p, 1024, 768);
    pad_set_origin(&p, 1010, 10);
    out.n = 0;
    axis(&p, PAD_AX_RT, 1.0, &out);
    axis(&p, PAD_AX_LX, 1.0, &out);
    axis(&p, PAD_AX_LY, -1.0, &out);
    pad_step(&p, 8, &out);
    CHECK(p.ix == 1023 && p.iy == 0);

    /* no walk button, no walking: the stick is a cursor and the left button stays up */
    pad_init(&p, 1024, 768);
    out.n = 0;
    axis(&p, PAD_AX_LX, 1.0, &out);
    run(&p, 200, 8, &out);
    CHECK(count(&out, PA_LDOWN) == 0 && !p.walking);
    /* the walk button without the stick: nothing */
    pad_init(&p, 1024, 768);
    out.n = 0;
    axis(&p, PAD_AX_RT, 1.0, &out);
    run(&p, 100, 8, &out);
    CHECK(out.n == 0);
    /* A held while walking keeps the button down when the stick lets go */
    axis(&p, PAD_AX_LX, 1.0, &out);
    pad_step(&p, 8, &out);
    pad_button(&p, PAD_A, 1, &out);
    CHECK(count(&out, PA_LDOWN) == 1);                                 /* already down by walking: no second press */
    axis(&p, PAD_AX_LX, 0, &out);
    CHECK(count(&out, PA_LUP) == 0 && p.left_src == 1);
    pad_button(&p, PAD_A, 0, &out);
    CHECK(count(&out, PA_LUP) == 1);
}

static void test_takeover(void)
{
    Pad p;
    PadOut out;

    pad_init(&p, 1024, 768);
    out.n = 0;
    pad_button(&p, PAD_A, 1, &out);                                    /* the pad holds the button, a key and a stick ... */
    pad_button(&p, PAD_LB, 1, &out);
    axis(&p, PAD_AX_LX, 1.0, &out);
    run(&p, 50, 10, &out);
    out.n = 0;
    pad_mouse_used(&p, 100, 200, &out);                                /* ... and the mouse moves: it has the cursor, and what the pad held comes up */
    CHECK(!p.active && p.ix == 100 && p.iy == 200);
    CHECK(count(&out, PA_LUP) == 1 && count(&out, PA_KEYUP) == 1 && p.left_src == 0 && p.down == 0);
    out.n = 0;
    run(&p, 200, 10, &out);
    CHECK(out.n == 0 && p.ix == 100);                                  /* the stick, still held, does not fight the mouse */
    pad_button(&p, PAD_A, 0, &out);                                    /* the late release of what was let go: nothing */
    CHECK(out.n == 0);
    axis(&p, PAD_AX_LX, 0.9, &out);                                    /* a move of the stick takes the cursor back, from where the mouse left it */
    CHECK(p.active);
    run(&p, 50, 10, &out);
    CHECK(p.ix > 100 && p.iy == 200);
    out.n = 0;
    pad_mouse_used(&p, 5000, -9, &out);                                /* outside the screen: kept inside */
    CHECK(p.ix == 1023 && p.iy == 0 && out.n == 0);

    /* unplugged, or the window lost the focus: everything up, sticks at rest */
    pad_init(&p, 1024, 768);
    out.n = 0;
    pad_button(&p, PAD_B, 1, &out);
    pad_button(&p, PAD_RB, 1, &out);
    pad_button(&p, PAD_DLEFT, 1, &out);
    axis(&p, PAD_AX_LY, 1.0, &out);
    axis(&p, PAD_AX_RX, 1.0, &out);
    out.n = 0;
    pad_release_all(&p, &out);
    CHECK(count(&out, PA_RUP) == 1 && count(&out, PA_KEYUP) == 3 && p.down == 0 && p.ax[PAD_AX_LY] == 0);
    {
        int x = p.ix, y = p.iy;

        out.n = 0;
        run(&p, 300, 10, &out);
        CHECK(out.n == 0 && p.ix == x && p.iy == y);                    /* the held keys' repeat is off too */
    }
    out.n = 0;
    pad_release_all(&p, &out);
    CHECK(out.n == 0);
}

static void test_screen(void)
{
    Pad p;
    PadOut out;

    pad_init(&p, 1024, 768);
    out.n = 0;
    pad_mouse_used(&p, 1000, 700, &out);
    pad_set_screen(&p, 640, 480);                                      /* the cursor is kept on a smaller screen */
    CHECK(p.ix == 639 && p.iy == 479 && p.ox == 320 && p.oy == 188);
    pad_set_screen(&p, 800, 600);                                     /* the party stands at 320 x 188 of 640, scaled by width */
    CHECK(p.ox == 400 && p.oy == 235);
}

static void test_draw(void)
{
    enum { W = 64, H = 48 };
    uint8_t *buf = malloc(W * H * 3 + 64);
    int i, bad = 0;

    memset(buf, 0x55, W * H * 3 + 64);
    memset(buf, 0x20, W * H * 3);
    pad_draw_cursor(buf, W, H, 10, 10);
    CHECK(buf[(10 * W + 10) * 3] == 0 && buf[(10 * W + 10) * 3 + 2] == 0);                    /* the tip is black */
    CHECK(buf[((12 * W) + 11) * 3] == 255 && buf[((12 * W) + 11) * 3 + 1] == 255);             /* inside the arrow is white */
    CHECK(buf[(10 * W + 20) * 3] == 0x20);                                                    /* outside it the frame is as it was */
    CHECK(buf[(11 * W + 11) * 3] == 0 && buf[(11 * W + 10) * 3] == 0);                         /* the outline */
    pad_draw_cursor(buf, W, H, -5, -5);                                                       /* clipped at every edge, nothing written past the frame */
    pad_draw_cursor(buf, W, H, W - 3, H - 3);
    pad_draw_cursor(buf, W, H, W + 40, 2);
    pad_draw_cursor(buf, W, H, 2, H + 40);
    for (i = W * H * 3; i < W * H * 3 + 64; i++)
        bad += buf[i] != 0x55;
    CHECK(bad == 0);
    CHECK(buf[(0 * W + 0) * 3] == 0x20 || buf[(0 * W + 0) * 3] == 0 || buf[(0 * W + 0) * 3] == 255);
    CHECK(pad_cursor_scale(640) == 1 && pad_cursor_scale(800) == 1 && pad_cursor_scale(1024) == 2);
    free(buf);
}

int main(void)
{
    test_stick();
    test_dir8();
    test_table();
    test_cursor();
    test_buttons();
    test_back_guard();
    test_nav();
    test_triggers_and_arrows();
    test_walk();
    test_takeover();
    test_screen();
    test_draw();
    printf("test_pad: %d checks, %d failed\n", checks, failures);
    return failures != 0;
}

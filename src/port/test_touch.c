/* test_touch.c - fingers as a mouse (touch.c) and the iOS app's start-up decisions (iosboot.c): pure, no SDL, no game.
 *   make -C src/port test */
#include <stdio.h>
#include <string.h>

#include "iosboot.h"
#include "nav.h"
#include "touch.h"

static int failures, checks;
#define CHECK(c) do { checks++; if (!(c)) { failures++; printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

/* everything the machine has queued, as "M12,34 D U r R" text, so a whole gesture is one comparison */
static const char *drain(Touch *t)
{
    static char buf[256];
    TouchAction a;
    size_t n = 0;

    buf[0] = 0;
    while (touch_next(t, &a)) {
        const char c = a.kind == TA_MOVE ? 'M' : a.kind == TA_LDOWN ? 'D' : a.kind == TA_LUP ? 'U' : a.kind == TA_RDOWN ? 'r' : 'R';

        n += (size_t)snprintf(buf + n, sizeof(buf) - n, "%s%c%d,%d", n ? " " : "", c, a.x, a.y);
    }
    return buf;
}
#define IS(t, s) (!strcmp(drain(t), s))

static void test_tap(void)
{
    Touch t;

    touch_init(&t);
    touch_down(&t, 1, 100, 200, 1000);
    CHECK(IS(&t, "M100,200"));                      /* the pointer is there at once (the card under it is shown), nothing is pressed */
    CHECK(touch_active(&t));
    touch_tick(&t, 1100);
    CHECK(IS(&t, ""));
    touch_up(&t, 1, 101, 201, 1150);
    CHECK(IS(&t, "M101,201 D101,201 U101,201"));   /* a tap is a click, at the lift */
    CHECK(!touch_active(&t) && t.state == TS_IDLE);

    /* a tap that wanders a little (under the slop) is still a tap */
    touch_down(&t, 1, 100, 200, 5000);
    drain(&t);
    touch_move(&t, 1, 105, 204, 5050);
    CHECK(IS(&t, ""));
    touch_up(&t, 1, 105, 204, 5100);
    CHECK(IS(&t, "M105,204 D105,204 U105,204"));
}

static void test_long_press(void)
{
    Touch t;

    touch_init(&t);
    touch_down(&t, 7, 300, 400, 0);
    drain(&t);
    touch_tick(&t, TOUCH_LONG_MS - 1);
    CHECK(IS(&t, ""));
    touch_tick(&t, TOUCH_LONG_MS);
    CHECK(IS(&t, "r300,400 R300,400"));             /* one right click, where the finger went down */
    touch_tick(&t, TOUCH_LONG_MS + 300);
    CHECK(IS(&t, ""));                              /* once */
    touch_move(&t, 7, 330, 400, TOUCH_LONG_MS + 400);
    CHECK(IS(&t, ""));                              /* the finger after a long press does nothing */
    touch_up(&t, 7, 330, 400, TOUCH_LONG_MS + 500);
    CHECK(IS(&t, "") && !touch_active(&t));

    /* a finger that has moved past the slop is a drag, never a long press */
    touch_down(&t, 7, 300, 400, 10000);
    drain(&t);
    touch_move(&t, 7, 330, 400, 10100);
    drain(&t);
    touch_tick(&t, 10000 + TOUCH_LONG_MS + 200);
    CHECK(IS(&t, ""));
}

static void test_drag(void)
{
    Touch t;

    touch_init(&t);
    touch_down(&t, 3, 50, 60, 0);
    drain(&t);
    touch_move(&t, 3, 55, 60, 10);
    CHECK(IS(&t, ""));
    touch_move(&t, 3, 80, 90, 20);
    CHECK(IS(&t, "D50,60 M80,90"));                 /* the button goes down where the finger began, then follows it */
    touch_move(&t, 3, 120, 90, 30);
    CHECK(IS(&t, "M120,90"));
    touch_tick(&t, 2000);
    CHECK(IS(&t, ""));
    touch_up(&t, 3, 130, 95, 2100);
    CHECK(IS(&t, "M130,95 U130,95"));
    CHECK(!touch_active(&t));
    /* a move of some other finger is not this one's */
    touch_down(&t, 4, 10, 10, 3000);
    drain(&t);
    touch_move(&t, 9, 500, 500, 3010);
    CHECK(IS(&t, ""));
}

static void test_two_finger_tap(void)
{
    Touch t;

    touch_init(&t);
    touch_down(&t, 1, 100, 100, 0);
    drain(&t);
    touch_down(&t, 2, 160, 100, 40);
    CHECK(IS(&t, ""));
    touch_up(&t, 2, 160, 100, 120);
    CHECK(IS(&t, "M100,100 r100,100 R100,100"));    /* a right click where the first finger was; no left click at all */
    touch_up(&t, 1, 100, 100, 140);
    CHECK(IS(&t, "") && !touch_active(&t) && t.state == TS_IDLE);

    /* the first finger lifting first is the same */
    touch_down(&t, 1, 100, 100, 1000);
    drain(&t);
    touch_down(&t, 2, 160, 100, 1040);
    touch_up(&t, 1, 100, 100, 1100);
    CHECK(IS(&t, "M100,100 r100,100 R100,100"));
    touch_up(&t, 2, 160, 100, 1120);
    CHECK(IS(&t, "") && t.state == TS_IDLE);

    /* too slow, or a finger that wandered: nothing */
    touch_down(&t, 1, 100, 100, 5000);
    drain(&t);
    touch_down(&t, 2, 160, 100, 5040);
    touch_up(&t, 2, 160, 100, 5000 + TOUCH_TWO_MS + 50);
    CHECK(IS(&t, ""));
    touch_up(&t, 1, 100, 100, 5000 + TOUCH_TWO_MS + 80);
    CHECK(IS(&t, "") && t.state == TS_IDLE);
    touch_down(&t, 1, 100, 100, 8000);
    drain(&t);
    touch_down(&t, 2, 160, 100, 8030);
    touch_move(&t, 1, 160, 160, 8050);
    touch_up(&t, 2, 160, 100, 8100);
    CHECK(IS(&t, ""));
    touch_up(&t, 1, 160, 160, 8120);
    CHECK(IS(&t, "") && t.state == TS_IDLE);

    /* a second finger that comes after the first has been long-pressed or is dragging is ignored, and does not disturb the drag */
    touch_down(&t, 1, 100, 100, 20000);
    drain(&t);
    touch_move(&t, 1, 140, 100, 20020);
    drain(&t);
    touch_down(&t, 2, 300, 300, 20030);
    touch_move(&t, 1, 150, 100, 20040);
    CHECK(IS(&t, "M150,100"));
    touch_up(&t, 2, 300, 300, 20050);
    CHECK(IS(&t, ""));
    touch_up(&t, 1, 150, 100, 20060);
    CHECK(IS(&t, "M150,100 U150,100"));
    CHECK(t.state == TS_IDLE && !touch_active(&t));
}

static void test_hold_press(void)
{
    Touch t;

    /* the map: a finger held still for TOUCH_HOLD_MS presses the button where it went down and keeps it down (the party walks), and lets go with the finger; no long press */
    touch_init(&t);
    touch_set_hold_press(&t, 1);
    touch_down(&t, 1, 500, 300, 0);
    CHECK(IS(&t, "M500,300"));
    touch_tick(&t, TOUCH_HOLD_MS - 1);
    CHECK(IS(&t, ""));
    touch_tick(&t, TOUCH_HOLD_MS);
    CHECK(IS(&t, "D500,300"));
    touch_tick(&t, 2000);
    CHECK(IS(&t, ""));
    touch_move(&t, 1, 520, 300, 2100);
    CHECK(IS(&t, "M520,300"));
    touch_up(&t, 1, 520, 300, 2200);
    CHECK(IS(&t, "M520,300 U520,300"));
    CHECK(t.state == TS_IDLE);

    /* a tap there is still a click, made when the finger lifts */
    touch_down(&t, 1, 500, 300, 3000);
    drain(&t);
    touch_tick(&t, 3050);
    touch_up(&t, 1, 500, 300, 3100);
    CHECK(IS(&t, "M500,300 D500,300 U500,300"));

    /* a drag is a drag, as anywhere */
    touch_down(&t, 1, 500, 300, 4000);
    drain(&t);
    touch_move(&t, 1, 560, 300, 4050);
    CHECK(IS(&t, "D500,300 M560,300"));
    touch_up(&t, 1, 560, 300, 4100);
    drain(&t);

    /* the answer is asked again at every tick: a map that was not running when the finger went down and is by the time it has been held a moment still gets the button */
    touch_set_hold_press(&t, 0);
    touch_down(&t, 1, 500, 300, 6000);
    drain(&t);
    touch_tick(&t, 6200);
    CHECK(IS(&t, ""));
    touch_set_hold_press(&t, 1);
    touch_tick(&t, 6220);
    CHECK(IS(&t, "D500,300"));
    touch_up(&t, 1, 500, 300, 7000);
    drain(&t);

    /* a second finger soon after the button went down lets it go, and is a two-finger tap */
    touch_down(&t, 1, 500, 300, 9000);
    drain(&t);
    touch_tick(&t, 9160);
    CHECK(IS(&t, "D500,300"));
    touch_down(&t, 2, 560, 300, 9200);
    CHECK(IS(&t, "U500,300"));
    touch_up(&t, 2, 560, 300, 9250);
    CHECK(IS(&t, "M500,300 r500,300 R500,300"));
    touch_up(&t, 1, 500, 300, 9270);
    CHECK(IS(&t, "") && t.state == TS_IDLE);

    /* without the flag a held finger is a long press, and the flag turned off again stops it pressing */
    touch_set_hold_press(&t, 0);
    touch_down(&t, 1, 10, 10, 20000);
    drain(&t);
    touch_tick(&t, 20000 + TOUCH_HOLD_MS + 10);
    CHECK(IS(&t, ""));
    touch_tick(&t, 20000 + TOUCH_LONG_MS);
    CHECK(IS(&t, "r10,10 R10,10"));
    touch_up(&t, 1, 10, 10, 21000);
    drain(&t);
}

static void test_odd_orders(void)
{
    Touch t;
    TouchAction a;
    int i;

    touch_init(&t);
    touch_up(&t, 1, 0, 0, 0);                       /* an up with nothing down */
    touch_move(&t, 1, 0, 0, 0);
    touch_tick(&t, 99999);
    CHECK(IS(&t, "") && t.state == TS_IDLE);
    touch_down(&t, 1, 5, 5, 0);
    touch_down(&t, 1, 6, 6, 1);                     /* the same finger twice */
    touch_down(&t, 2, 90, 90, 2);
    touch_down(&t, 3, 95, 95, 3);                   /* a third */
    drain(&t);
    touch_up(&t, 3, 95, 95, 10);
    CHECK(IS(&t, ""));
    touch_up(&t, 2, 90, 90, 20);
    touch_up(&t, 1, 5, 5, 30);
    drain(&t);
    CHECK(t.state == TS_IDLE && !touch_active(&t));
    /* many gestures with the queue never drained in between do not overrun it (it drops, it does not corrupt) */
    for (i = 0; i < 40; i++) {
        touch_down(&t, 1, i, i, (uint32_t)i * 1000);
        touch_up(&t, 1, i, i, (uint32_t)i * 1000 + 10);
    }
    i = 0;
    while (touch_next(&t, &a))
        i++;
    CHECK(i > 0 && i <= 16);
}

static void test_boot(void)
{
    IosBoot b;
    char text[600], docs[100];

    CHECK(!strcmp(ios_program(NULL, NULL), "magic"));
    CHECK(!strcmp(ios_program("", ""), "magic"));
    CHECK(!strcmp(ios_program("duel", NULL), "duel"));
    CHECK(!strcmp(ios_program("DECK.EXE", "duel"), "deck"));                        /* the environment wins */
    CHECK(!strcmp(ios_program(NULL, "  Duel\n"), "duel"));
    CHECK(!strcmp(ios_program("nonsense", "deck"), "deck"));                        /* an environment that names nothing is passed over */
    CHECK(!strcmp(ios_program(NULL, "duelling"), "magic"));
    CHECK(!strcmp(ios_program(NULL, "magic.exe extra"), "magic"));
    CHECK(!strcmp(ios_program(NULL, "# comment"), "magic"));

    ios_documents("/var/mobile/Containers/Data/Application/ABC", docs, sizeof(docs));
    CHECK(!strcmp(docs, "/var/mobile/Containers/Data/Application/ABC/Documents"));
    ios_documents(NULL, docs, sizeof(docs));
    CHECK(!strcmp(docs, "."));

    ios_boot_paths("/d/Documents/", "duel", &b);
    CHECK(!strcmp(b.program, "duel") && !strcmp(b.exe_name, "DUEL.EXE"));
    CHECK(!strcmp(b.root, "/d/Documents/Magic"));
    CHECK(!strcmp(b.exe, "/d/Documents/Magic/Program/DUEL.EXE"));
    CHECK(!strcmp(b.overlay, "/d/Documents/port_overlay"));
    ios_boot_paths("/d", "garbage", &b);
    CHECK(!strcmp(b.program, "magic") && !strcmp(b.exe, "/d/Magic/Program/MAGIC.EXE"));
    ios_missing_text(&b, text, sizeof(text));
    CHECK(strstr(text, "Magic/Program/MAGIC.EXE") && strstr(text, "/d/Magic/Program/MAGIC.EXE"));
    CHECK(strlen(text) < sizeof(text) - 1);
}

/* Fingers on the small controls of a page (the Magic Shell's spin buttons are 12 x 14 pixels): what touch.c makes of a gesture goes through nav_snap_track as front.c does it, so a tap near an
 * arrow lands on the arrow with the press and the release in one place, and a long press (right click) is moved the same way. The "page" has the arrows of one spin button, an edit box beside them
 * and a check box; the reach is 14 pixels. */
static const char *snapped(Touch *t, NavSnap *s, const NavTarget *tg, int ntg)
{
    static char buf[256];
    TouchAction a;
    size_t n = 0;

    buf[0] = 0;
    while (touch_next(t, &a)) {
        int ev = a.kind == TA_LDOWN || a.kind == TA_RDOWN ? 1 : a.kind == TA_LUP || a.kind == TA_RUP ? -1 : 0, sx = 0, sy = 0, sn = 0, x, y;
        const char c = a.kind == TA_MOVE ? 'M' : a.kind == TA_LDOWN ? 'D' : a.kind == TA_LUP ? 'U' : a.kind == TA_RDOWN ? 'r' : 'R';

        if (ev == 1 || (ev == 0 && !s->active))
            sn = nav_snap(tg, ntg, a.x, a.y, 14, &sx, &sy);
        nav_snap_track(s, ev, a.x, a.y, sn, sx, sy, &x, &y);
        n += (size_t)snprintf(buf + n, sizeof(buf) - n, "%s%c%d,%d", n ? " " : "", c, x, y);
    }
    return buf;
}

static void test_snap_on_controls(void)
{
    NavTarget tg[4];
    Touch t;
    NavSnap s;

    memset(tg, 0, sizeof(tg));
    tg[0].x0 = 299; tg[0].y0 = 461; tg[0].x1 = 333; tg[0].y1 = 489;      /* the edit box */
    tg[1].x0 = 333; tg[1].y0 = 461; tg[1].x1 = 345; tg[1].y1 = 475;      /* the spin's up arrow */
    tg[2].x0 = 333; tg[2].y0 = 475; tg[2].x1 = 345; tg[2].y1 = 489;      /* its down arrow */
    tg[3].x0 = 237; tg[3].y0 = 430; tg[3].x1 = 293; tg[3].y1 = 444;      /* the check box */
    memset(&s, 0, sizeof(s));
    touch_init(&t);
    touch_down(&t, 1, 353, 468, 1000);                                   /* a finger 8 pixels right of the up arrow */
    CHECK(!strcmp(snapped(&t, &s, tg, 4), "M338,467"));                  /* the hover is on the arrow */
    touch_up(&t, 1, 354, 469, 1100);
    CHECK(!strcmp(snapped(&t, &s, tg, 4), "M338,467 D338,467 U338,467"));   /* a tap: the click is on the arrow, and the lift (a pixel away) is the press's place */
    touch_down(&t, 1, 340, 492, 5000);                                   /* under the down arrow */
    snapped(&t, &s, tg, 4);
    touch_tick(&t, 5000 + TOUCH_LONG_MS);
    CHECK(!strcmp(snapped(&t, &s, tg, 4), "r338,481 R338,481"));        /* a long press is a right click on the arrow's middle */
    touch_up(&t, 1, 340, 492, 5700);
    CHECK(!strcmp(snapped(&t, &s, tg, 4), ""));
    touch_down(&t, 1, 500, 300, 8000);                                   /* nowhere near anything: as it is */
    snapped(&t, &s, tg, 4);
    touch_up(&t, 1, 500, 300, 8050);
    CHECK(!strcmp(snapped(&t, &s, tg, 4), "M500,300 D500,300 U500,300"));
    touch_down(&t, 1, 340, 492, 9000);                                   /* a drag starting near an arrow: the press is on the arrow, the moves keep the offset */
    snapped(&t, &s, tg, 4);
    touch_move(&t, 1, 340, 520, 9050);
    CHECK(!strcmp(snapped(&t, &s, tg, 4), "D338,481 M338,509"));
    touch_up(&t, 1, 340, 520, 9100);
    CHECK(!strcmp(snapped(&t, &s, tg, 4), "M338,509 U338,509"));
}

int main(void)
{
    test_tap();
    test_long_press();
    test_drag();
    test_two_finger_tap();
    test_hold_press();
    test_odd_orders();
    test_snap_on_controls();
    test_boot();
    printf("test_touch: %d checks, %d failed\n", checks, failures);
    return failures != 0;
}

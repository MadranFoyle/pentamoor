/* test_nav.c - the spatial navigation (nav.c): grids, a hand beside the creature rows, staggered rows, empty zones, ties, scrolling lists and a pointer that is on nothing. Pure: no SDL, no
 * game. The layouts are those of a duel at 1024x768 (docs/notes/controller-nav.md).
 *   make -C src/port test */
#include <stdio.h>
#include <string.h>

#include "nav.h"

static int failures, checks;
#define CHECK(c) do { checks++; if (!(c)) { failures++; printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

typedef struct { NavTarget t[NAV_MAXTARGETS]; int n; } List;

static int add(List *l, int x0, int y0, int w, int h, int zone, const char *label)
{
    NavTarget *t = &l->t[l->n];

    memset(t, 0, sizeof(*t));
    t->x0 = x0; t->y0 = y0; t->x1 = x0 + w; t->y1 = y0 + h; t->zone = zone; t->kind = NAVK_CARD;
    strncpy(t->label, label, sizeof(t->label) - 1);
    return l->n++;
}

/* a move from target `from` (the pointer in its middle) */
static int go(const List *l, int from, int dir)
{
    int x, y, hx = -1, hy = -1;

    nav_point(&l->t[from], &x, &y);
    return nav_pick(l->t, l->n, -1, x, y, dir, &hx, &hy);
}

static int go_name(const List *l, const char *from, int dir, char *out)
{
    int i, r;

    for (i = 0; i < l->n; i++)
        if (!strcmp(l->t[i].label, from))
            break;
    if (i == l->n)
        return -99;
    r = go(l, i, dir);
    strcpy(out, r >= 0 ? l->t[r].label : "");
    return r;
}

#define GOTO(from, dir, want) do { char got[40]; int r_ = go_name(&l, from, dir, got); CHECK(r_ >= 0 && !strcmp(got, want)); if (r_ < 0 || strcmp(got, want)) printf("  %s -> dir %d: got '%s' (%d), wanted %s\n", from, dir, got, r_, want); } while (0)
#define GOTO_NONE(from, dir) do { char got[40]; int r_ = go_name(&l, from, dir, got); CHECK(r_ == NAV_NONE); if (r_ != NAV_NONE) printf("  %s -> dir %d: got '%s' (%d), wanted none\n", from, dir, got, r_); } while (0)

static void test_grid(void)
{
    List l = {{{0}}, 0};
    int r, c;
    char name[8];

    for (r = 0; r < 3; r++)
        for (c = 0; c < 3; c++) {
            snprintf(name, sizeof(name), "%d%d", r, c);
            add(&l, 100 + c * 130, 100 + r * 130, 128, 128, 1, name);
        }
    GOTO("00", NAV_RIGHT, "01");
    GOTO("01", NAV_RIGHT, "02");
    GOTO_NONE("02", NAV_RIGHT);                                  /* no wrapping to the next row */
    GOTO_NONE("00", NAV_LEFT);
    GOTO_NONE("00", NAV_UP);
    GOTO("00", NAV_DOWN, "10");
    GOTO("11", NAV_UP, "01");
    GOTO("11", NAV_DOWN, "21");
    GOTO("11", NAV_LEFT, "10");
    GOTO("11", NAV_RIGHT, "12");
    GOTO_NONE("22", NAV_DOWN);
    GOTO_NONE("22", NAV_RIGHT);
    GOTO("22", NAV_LEFT, "21");
    GOTO("22", NAV_UP, "12");
    /* left then right comes back; down then up too */
    {
        char a[40], b[40];

        CHECK(go_name(&l, "11", NAV_LEFT, a) >= 0 && go_name(&l, a, NAV_RIGHT, b) >= 0 && !strcmp(b, "11"));
        CHECK(go_name(&l, "11", NAV_DOWN, a) >= 0 && go_name(&l, a, NAV_UP, b) >= 0 && !strcmp(b, "11"));
    }
}

/* the duel at 1024x768: your hand is a column of strips (the visible 15 pixels of each card but the last), your territory is on the left of it, the opponent's above */
static void build_duel(List *l)
{
    int i;
    char name[24];

    /* zone 1: your hand, seven cards: strips of 15 pixels, the last one whole */
    for (i = 0; i < 7; i++) {
        snprintf(name, sizeof(name), "hand%d", i);
        add(l, 828, 499 + 15 * i, 128, i == 6 ? 128 : 15, 1, name);
    }
    /* zone 2: your territory: creatures in a row at y 560, lands in a row below (every card 128 x 128, 5 pixels apart) */
    for (i = 0; i < 3; i++) {
        snprintf(name, sizeof(name), "mine-c%d", i);
        add(l, 320 + i * 133, 400, 128, 128, 2, name);
    }
    for (i = 0; i < 4; i++) {
        snprintf(name, sizeof(name), "mine-l%d", i);
        add(l, 320 + i * 133, 580, 128, 128, 2, name);
    }
    /* zone 3: the opponent's territory */
    for (i = 0; i < 3; i++) {
        snprintf(name, sizeof(name), "opp-c%d", i);
        add(l, 320 + i * 133, 20, 128, 128, 3, name);
    }
    add(l, 320, 200, 128, 128, 3, "opp-l0");
    /* zone 4: the Done button between the territories, zone 5: the phase icons (the left column), zone 6: the life totals */
    {
        NavTarget *t;
        int k = add(l, 310, 371, 69, 26, 4, "done");

        t = &l->t[k];
        t->kind = NAVK_BUTTON;
        for (i = 0; i < 8; i++) {                                 /* the player's eight phase icons, 41 pixels apart */
            snprintf(name, sizeof(name), "phase%d", i);
            add(l, 258, 436 + 41 * i, 42, 40, 5, name);
        }
        for (i = 0; i < 8; i++) {                                 /* the opponent's eight, above */
            snprintf(name, sizeof(name), "ophase%d", i);
            add(l, 258, 2 + 41 * i, 42, 40, 7, name);
        }
        add(l, 1, 672, 128, 96, 6, "life-mine");
        add(l, 1, 0, 128, 96, 6, "life-opp");
    }
}

static void test_duel(void)
{
    List l = {{{0}}, 0};

    build_duel(&l);
    /* the user's examples: the bottom card of the hand, up: up the hand */
    GOTO("hand6", NAV_UP, "hand5");
    GOTO("hand5", NAV_UP, "hand4");
    GOTO("hand1", NAV_UP, "hand0");
    GOTO("hand0", NAV_DOWN, "hand1");
    GOTO("hand5", NAV_DOWN, "hand6");
    GOTO_NONE("hand6", NAV_DOWN);                                /* nothing below: no wrapping to the top */
    GOTO_NONE("hand6", NAV_RIGHT);
    /* the first card of the hand, up: out of the hand to the zone above, nothing of the hand left that way. The nearest in the beam is the opponent's side or the Done
       button; in the beam above x 828..956 there are no cards, so the best of the half-plane above (a card of the opponent's row of lands) is chosen */
    {
        char got[40];
        int r = go_name(&l, "hand0", NAV_UP, got);

        CHECK(r >= 0 && l.t[r].zone != 1);
    }
    /* left from the hand goes to the territory, to the row nearest in height: the bottom card is level with the lands, the top ones with the creatures */
    GOTO("hand6", NAV_LEFT, "mine-l3");
    GOTO("hand0", NAV_LEFT, "mine-c2");
    /* and scrolls along the row: left, left, left... then the edge */
    GOTO("mine-l3", NAV_LEFT, "mine-l2");
    GOTO("mine-l2", NAV_LEFT, "mine-l1");
    GOTO("mine-l1", NAV_LEFT, "mine-l0");
    /* the left end of the lands: the phase icons, level with it (a jump to the neighbouring zone) */
    {
        char got[40];
        int r = go_name(&l, "mine-l0", NAV_LEFT, got);

        CHECK(r >= 0 && l.t[r].zone == 5);
    }
    /* the right end of the creatures goes to the hand */
    GOTO("mine-c2", NAV_RIGHT, "hand0");
    /* up from the creatures: the Done button is no neighbour as long as there are cards in the beam; up again from the opponent's row there is nothing */
    GOTO("mine-l1", NAV_UP, "mine-c1");
    GOTO("mine-c1", NAV_DOWN, "mine-l1");
    GOTO_NONE("opp-c0", NAV_UP);
    GOTO("opp-c0", NAV_RIGHT, "opp-c1");
    GOTO("opp-c0", NAV_DOWN, "opp-l0");                          /* the land under the first creature: the same column */
    GOTO("opp-c1", NAV_DOWN, "mine-c1");                         /* nothing under the second: the next zone down, in its column (past the Done button, which is not in the beam) */
    /* up from my creatures reaches the Done button (between the territories), and from it up the opponent's cards */
    GOTO("mine-c0", NAV_UP, "done");
    GOTO("done", NAV_DOWN, "mine-c0");
    GOTO("done", NAV_UP, "opp-l0");
}

static void test_zone_preference(void)
{
    List l = {{{0}}, 0};

    /* a card of another zone is nearer than the next one of the same zone, but the same zone wins while it is in the beam */
    add(&l, 100, 100, 100, 100, 1, "a");
    add(&l, 210, 100, 100, 100, 2, "other-near");
    add(&l, 400, 100, 100, 100, 1, "same-far");
    GOTO("a", NAV_RIGHT, "same-far");
    /* when the same zone's card is not in the beam (a long way down), the near one of the other zone wins */
    {
        List m = {{{0}}, 0};
        char got[40];

        add(&m, 100, 100, 100, 100, 1, "a");
        add(&m, 210, 100, 100, 100, 2, "other-near");
        add(&m, 300, 700, 100, 100, 1, "same-low");
        CHECK(go_name(&m, "a", NAV_RIGHT, got) >= 0 && !strcmp(got, "other-near"));
    }
}

static void test_staggered(void)
{
    List l = {{{0}}, 0};
    int i;
    char name[8];

    /* two rows of cards, the second shifted right by 40 pixels: down goes to the one below whose middle is nearer, up to the one above */
    for (i = 0; i < 4; i++) {
        snprintf(name, sizeof(name), "t%d", i);
        add(&l, 100 + i * 130, 100, 128, 128, 1, name);
    }
    for (i = 0; i < 4; i++) {
        snprintf(name, sizeof(name), "b%d", i);
        add(&l, 140 + i * 130, 240, 128, 128, 1, name);
    }
    GOTO("t0", NAV_DOWN, "b0");
    GOTO("t1", NAV_DOWN, "b1");
    GOTO("t3", NAV_DOWN, "b3");
    GOTO("b0", NAV_UP, "t0");
    GOTO("b3", NAV_UP, "t3");
    GOTO("b1", NAV_LEFT, "b0");
    GOTO_NONE("b3", NAV_RIGHT);
    GOTO_NONE("t0", NAV_LEFT);
    /* a stagger of exactly half a card is a tie between two cards equally near: the earlier in the list (the left one) wins, every time */
    {
        List m = {{{0}}, 0};

        for (i = 0; i < 3; i++) {
            snprintf(name, sizeof(name), "t%d", i);
            add(&m, 100 + i * 130, 100, 128, 128, 1, name);
        }
        for (i = 0; i < 3; i++) {
            snprintf(name, sizeof(name), "b%d", i);
            add(&m, 165 + i * 130, 240, 128, 128, 1, name);
        }
        for (i = 0; i < 3; i++) {
            char got[40];

            CHECK(go_name(&m, "t1", NAV_DOWN, got) >= 0 && !strcmp(got, "b0"));
        }
    }
}

static void test_empty_and_single(void)
{
    List l = {{{0}}, 0};
    int hx, hy;

    CHECK(nav_pick(l.t, 0, -1, 10, 10, NAV_UP, &hx, &hy) == NAV_NONE);        /* nothing at all */
    add(&l, 10, 10, 50, 50, 1, "only");
    GOTO_NONE("only", NAV_UP);
    GOTO_NONE("only", NAV_LEFT);
    GOTO_NONE("only", NAV_RIGHT);
    GOTO_NONE("only", NAV_DOWN);
}

static void test_tie(void)
{
    List l = {{{0}}, 0};

    /* two cards equally far to the right of c, one above and one below: the tie goes to the earlier in the list (the caller sorts top to bottom), always the same */
    add(&l, 100, 190, 100, 100, 1, "c");
    add(&l, 300, 90, 100, 100, 1, "up");
    add(&l, 300, 290, 100, 100, 1, "down");
    {
        int i;

        for (i = 0; i < 5; i++)
            GOTO("c", NAV_RIGHT, "up");
    }
}

static void test_pointer_on_nothing(void)
{
    List l = {{{0}}, 0};
    int hx = 0, hy = 0, r;

    build_duel(&l);
    /* the pointer in an empty place of the territory, between the rows: up goes to the card above it, down to the card below it */
    r = nav_pick(l.t, l.n, -1, 400, 545, NAV_UP, &hx, &hy);
    CHECK(r >= 0 && l.t[r].y1 <= 545);
    r = nav_pick(l.t, l.n, -1, 400, 545, NAV_DOWN, &hx, &hy);
    CHECK(r >= 0 && l.t[r].y0 >= 545);
    /* the pointer left of everything: right finds a target, left (none that way) goes to the nearest anyway */
    r = nav_pick(l.t, l.n, -1, 0, 380, NAV_LEFT, &hx, &hy);
    CHECK(r >= 0);
    /* hover point in the middle of the box */
    r = nav_pick(l.t, l.n, -1, 400, 545, NAV_DOWN, &hx, &hy);
    CHECK(r >= 0 && hx == (l.t[r].x0 + l.t[r].x1 - 1) / 2 && hy == (l.t[r].y0 + l.t[r].y1 - 1) / 2);
    /* an explicit current target wins over where the pointer is */
    r = nav_pick(l.t, l.n, 0, 400, 545, NAV_UP, &hx, &hy);
    CHECK(r != 0);                                               /* from the first target (the hand's top strip) up: not itself */
}

static void test_scroll(void)
{
    List l = {{{0}}, 0};
    int i, hx, hy;
    char name[8];

    /* a list of five rows shown (more below), and a button under it */
    for (i = 0; i < 5; i++) {
        snprintf(name, sizeof(name), "row%d", i);
        add(&l, 100, 100 + i * 14, 200, 14, 7, name);
        l.t[i].kind = NAVK_ROW;
        l.t[i].scroll = NAVS_DOWN;
    }
    add(&l, 100, 200, 60, 24, 8, "ok");
    GOTO("row0", NAV_DOWN, "row1");
    GOTO("row3", NAV_DOWN, "row4");
    CHECK(go(&l, 4, NAV_DOWN) == NAV_SCROLL);                    /* the last shown row: the list scrolls before the pointer leaves it */
    CHECK(go(&l, 0, NAV_UP) == NAV_NONE);                        /* no more rows above: nothing */
    l.t[0].scroll |= NAVS_UP;
    CHECK(go(&l, 0, NAV_UP) == NAV_SCROLL);
    for (i = 0; i < 5; i++)
        l.t[i].scroll = 0;
    GOTO("row4", NAV_DOWN, "ok");                                /* a list that does not scroll: the button below */
    CHECK(nav_pick(l.t, l.n, 4, 0, 0, NAV_DOWN, &hx, &hy) == 5);
}

static void test_find(void)
{
    List l = {{{0}}, 0};

    add(&l, 0, 0, 100, 100, 1, "a");
    add(&l, 100, 0, 100, 100, 1, "b");
    CHECK(nav_find(l.t, l.n, 50, 50) == 0);
    CHECK(nav_find(l.t, l.n, 100, 50) == 1);
    CHECK(nav_find(l.t, l.n, 99, 99) == 0);
    CHECK(nav_find(l.t, l.n, 100, 100) == -1);
    CHECK(nav_find(l.t, l.n, -1, 0) == -1);
}

static void test_wide_boxes(void)
{
    List l = {{{0}}, 0};

    /* a wide bar (the mana pool, a dialog's list) above two buttons: down from the bar reaches the button its middle is nearer to; a button overlapping the bar sideways is in its beam */
    add(&l, 100, 100, 400, 30, 1, "bar");
    add(&l, 100, 200, 100, 30, 2, "left");
    add(&l, 400, 200, 100, 30, 2, "right");
    GOTO("left", NAV_UP, "bar");
    GOTO("right", NAV_UP, "bar");
    GOTO("bar", NAV_DOWN, "left");                               /* centre of the bar is 300: both 100 px off, the first in the list */
    GOTO("left", NAV_RIGHT, "right");
}

static void test_nearest(void)
{
    List l = {{{0}}, 0};
    int hx = -1, hy = -1;

    CHECK(nav_nearest(l.t, 0, 5, 5, &hx, &hy) == NAV_NONE);
    add(&l, 0, 0, 100, 100, 1, "a");
    add(&l, 300, 0, 100, 100, 1, "b");
    add(&l, 0, 300, 100, 100, 1, "c");
    CHECK(nav_nearest(l.t, l.n, 50, 50, &hx, &hy) == 0 && hx == 49 && hy == 49);        /* on a target: that one */
    CHECK(nav_nearest(l.t, l.n, 250, 40, &hx, &hy) == 1 && hx == 349);                  /* off to the side: the nearest edge, in any direction */
    CHECK(nav_nearest(l.t, l.n, 40, 250, &hx, &hy) == 2 && hy == 349);
    CHECK(nav_nearest(l.t, l.n, 199, 50, &hx, &hy) == 0 && nav_nearest(l.t, l.n, 200, 50, &hx, &hy) == 1);   /* the middle between a's edge (99) and b's (300) */
    l.t[1].x0 = 301; l.t[1].x1 = 401;
    CHECK(nav_nearest(l.t, l.n, 200, 50, &hx, &hy) == 0);                               /* a tie goes to the earlier */
    CHECK(nav_nearest(l.t, l.n, 100, 50, &hx, &hy) == 0);                               /* the edge is out (x1 is exclusive): 1 pixel from a */
}

int main(void)
{
    test_nearest();
    test_grid();
    test_duel();
    test_zone_preference();
    test_staggered();
    test_empty_and_single();
    test_tie();
    test_pointer_on_nothing();
    test_scroll();
    test_find();
    test_wide_boxes();
    printf("%d checks, %d failed\n", checks, failures);
    return failures ? 1 : 0;
}

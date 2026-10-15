/* screens.c - the D-pad's targets on the screens MAGIC.EXE draws itself (see screens.h). Nothing of the game's code is changed or copied: pre-call hooks note which loop is running, and what a click
 * would hit is read from where the game keeps it, in guest memory, at the addresses of MAGIC.EXE 1.0 (as pace.c and textfocus.c do for theirs). docs/notes/controller-screens.md. */
#include <stdio.h>
#include <string.h>

#include "navwm.h"
#include "port.h"
#include "sched.h"
#include "screens.h"

/* ---- the game's button table (the library at 0x41f12b..0x41fe62) ----------------------------------------------------------------------------------------- */
/* Every screen with buttons keeps its records in one place: a context (0x41f354 pushes a new one when a screen starts, 0x41f391 pops it) holds a count and a list of pointers to records of 84
 * bytes: +0x10 x, +0x14 y, +0x18 width, +0x1c height (screen pixels: the game scaled them from its 640x480 layout, which is kept in +0x00..+0x0c, to the screen it runs at), +0x24 the handler
 * (called with the record and 0 to ask "is the mouse on you", 1 to draw it picked, 2 for a click), +0x40 the type (3: shown greyed, never hit). A record with no place (x = y = -1) is a key
 * with no button. The loop of the screen calls 0x41f3ea once a pass, which asks each handler, and the handlers test the mouse like this: x <= mx <= x + w and y <= my <= y + h. */
#define UI_CTX 0x519c24u                /* the current context */
#define UI_COUNT 0x67f780u              /* dword per context: how many records */
#define UI_PTRS 0x67f7d0u               /* 50 pointers (200 bytes) per context */
#define UI_MAXCTX 20
#define UI_MAXREC 50
#define REC_X 0x10
#define REC_Y 0x14
#define REC_W 0x18
#define REC_H 0x1c
#define REC_HANDLER 0x24
#define REC_TYPE 0x40
#define TYPE_GREY 3

/* ---- the text menu (0x489748: the loop of "Will you...\n Duel a Sorceress.\n Pay 40 gold.\n") ------------------------------------------------------------------------ */
/* The box's place and the lines are in globals the loop and its drawing routine (0x489c9c) share: the left edge, the top, the right edge (both ends in), the line height of the font, the number of
 * lines of text above the choices (the first choice is line `first`), the number of choices, and a mask of the ones that are shut. The loop turns the mouse into a choice with
 * (my - top - 4) / height - first, when mx is between the edges, and takes it when the button is let go. */
#define TM_LEFT 0x539decu
#define TM_TOP 0x539df0u
#define TM_RIGHT 0x676d44u
#define TM_LINEH 0x527b30u
#define TM_FIRST 0x676d50u
#define TM_COUNT 0x676d40u
#define TM_MASK 0x676d58u

/* ---- the loops --------------------------------------------------------------------------------------------------------------------------------------- */
/* The functions that run a screen, by the range of their code. A pass of the button table (SRC_TABLE) from a loop that is not in this list is a screen with buttons and nothing else; the
 * mouse snapshot (SRC_SNAPSHOT) is taken by every loop, and counts only for the ones listed here, which have something besides buttons. */
typedef struct { uint32_t lo, hi; int kind; } Loop;
static const Loop loops[] = {
    {0x4e73a0, 0x4e7936, SCREEN_NONE},          /* the overworld: walking is the arrow keys (the D-pad stays that), its buttons are for the stick */
    {0x489748, 0x489c9c, SCREEN_TEXTMENU},      /* the text menu */
    {0x509517, 0x509fd4, SCREEN_BUYCARDS},      /* "Cards for Sale": the Done button is in the table, the cards are boxes in the function's locals */
    {0x48f523, 0x49094c, SCREEN_CLUES},         /* Dungeon & Castle Clues: the arrows and Done are in the table, the twelve rows are tested by the loop itself */
};

/* The locals of 0x509517 (the frame is the one lift_out.ebp holds when the loop calls out): the number of cards, and for each a box at ebp - 0xa0 + 16 * i: x0, y0, x1, y1 (both ends in).
 * The ids are a global array, -1 for a card that is sold. */
#define BUY_COUNT (-0xa8)
#define BUY_BOXES (-0xa0)
#define BUY_IDS 0x61e060u
#define BUY_MAX 8
/* The locals of 0x48f523: how many rows have a dungeon in them. */
#define CLUE_COUNT (-0x12d8)

static int cur_kind;                    /* what the latest pass was */
static double cur_t = -1e9;
static uint32_t cur_ebp;

#define LIVE_S 0.4                      /* a loop that has not passed for this long is not the screen that is on */

/* ---- the pieces ---------------------------------------------------------------------------------------------------------------------------------------- */
static int clamp_box(NavTarget *t, int x0, int y0, int x1, int y1, int sw, int sh)
{
    if (x0 < 0) x0 = 0;
    if (y0 < 0) y0 = 0;
    if (x1 > sw) x1 = sw;
    if (y1 > sh) y1 = sh;
    if (x1 <= x0 || y1 <= y0)
        return 0;
    memset(t, 0, sizeof(*t));
    t->x0 = x0; t->y0 = y0; t->x1 = x1; t->y1 = y1;
    return 1;
}

int screens_record_target(int x, int y, int w, int h, int type, int sw, int sh, NavTarget *t)
{
    if (type == TYPE_GREY || w <= 0 || h <= 0 || x < 0 || y < 0)
        return 0;
    if (!clamp_box(t, x, y, x + w + 1, y + h + 1, sw, sh))      /* the game's test has both ends in */
        return 0;
    t->kind = NAVK_BUTTON;
    return 1;
}

int screens_textmenu_targets(int x0, int x1, int top, int lh, int first, int count, uint32_t mask, int sw, int sh, NavTarget *t, int max)
{
    int i, n = 0;

    if (lh <= 0 || count <= 0 || count > 32 || first < 0 || first > 64 || x1 <= x0)
        return 0;
    for (i = 0; i < count && n < max; i++) {
        int y0 = top + 4 + (first + i) * lh;

        if ((mask & (1u << i)) || !clamp_box(&t[n], x0, y0, x1 + 1, y0 + lh, sw, sh))
            continue;
        t[n].kind = NAVK_MENU;
        t[n].zone = 1;
        snprintf(t[n].label, sizeof(t[n].label), "line %d", i);
        n++;
    }
    return n;
}

int screens_card_targets(const int32_t *boxes, const int32_t *ids, int n, int sw, int sh, NavTarget *t, int max)
{
    int i, k = 0;

    for (i = 0; i < n && i < BUY_MAX && k < max; i++) {
        const int32_t *b = boxes + 4 * i;

        if (ids[i] == -1 || b[2] < b[0] || b[3] < b[1] || !clamp_box(&t[k], b[0], b[1], b[2] + 1, b[3] + 1, sw, sh))
            continue;
        t[k].kind = NAVK_CARD;
        t[k].zone = 2;
        snprintf(t[k].label, sizeof(t[k].label), "card %d", i);
        k++;
    }
    return k;
}

/* x, y in the game's 640x480 units are floor(mx * 640 / sw): the smallest screen coordinate whose unit is at least u */
static int unit_to_screen(int u, int range, int screen) { return (u * screen + range - 1) / range; }

int screens_clue_targets(int count, int sw, int sh, NavTarget *t, int max)
{
    /* two columns, x in (0x54, 0x54 + 0xfb) and (0x15b, 0x15b + 0xfd), six rows from y 0x49, each 0x3e tall (the edges of the game's test are out on the left and the top) */
    static const int left[2] = {0x54 + 1, 0x15b + 1}, right[2] = {0x54 + 0xfb, 0x15b + 0xfd};
    int row, col, k = 0;

    for (row = 0; row < 6; row++)
        for (col = 0; col < 2; col++) {
            int idx = row * 2 + col, y0u = 0x49 + 0x3e * row, y1u = y0u + 0x3e;

            if (idx >= count || k >= max)
                continue;
            if (y0u < 0x49 + 1)
                y0u = 0x49 + 1;
            if (!clamp_box(&t[k], unit_to_screen(left[col], 640, sw), unit_to_screen(y0u, 480, sh), unit_to_screen(right[col], 640, sw), unit_to_screen(y1u, 480, sh), sw, sh))
                continue;
            t[k].kind = NAVK_ROW;
            t[k].zone = 3;
            snprintf(t[k].label, sizeof(t[k].label), "clue %d", idx);
            k++;
        }
    return k;
}

/* ---- noting the loops ---------------------------------------------------------------------------------------------------------------------------------- */
static const Loop *loop_of(uint32_t ret)
{
    size_t i;

    for (i = 0; i < sizeof(loops) / sizeof(loops[0]); i++)
        if (ret >= loops[i].lo && ret < loops[i].hi)
            return &loops[i];
    return NULL;
}

void screens_note(uint32_t ret, uint32_t ebp, int src, double now)
{
    const Loop *l = loop_of(ret);
    int kind;

    if (l)
        kind = l->kind;
    else if (src == SRC_TABLE)
        kind = SCREEN_TABLE;
    else
        return;                         /* a loop with nothing to read (or one the table's own pass will note) */
    cur_kind = kind;
    cur_ebp = ebp;
    cur_t = now;
}

int screens_kind(double now)
{
    return now - cur_t <= LIVE_S ? cur_kind : SCREEN_NONE;
}

/* ---- reading the game ---------------------------------------------------------------------------------------------------------------------------------- */
static uint32_t rd32(uint32_t a) { return RD32(a); }
static int32_t rds32(uint32_t a) { return (int32_t)RD32(a); }

static int collect_table(NavTarget *out, int max)
{
    uint32_t ctx = rd32(UI_CTX);
    int n, i, k = 0;

    if (ctx >= UI_MAXCTX)
        return 0;
    n = rds32(UI_COUNT + 4 * ctx);
    if (n < 0 || n > UI_MAXREC)
        return 0;
    for (i = 0; i < n && k < max; i++) {
        uint32_t p = rd32(UI_PTRS + 200 * ctx + 4 * (uint32_t)i);
        NavTarget t;

        if (p < 0x400000u || p > 0x7fff0000u)
            continue;
        if (!screens_record_target(rds32(p + REC_X), rds32(p + REC_Y), rds32(p + REC_W), rds32(p + REC_H), rds32(p + REC_TYPE), screen_w, screen_h, &t))
            continue;
        t.zone = (int)rd32(p + REC_HANDLER);
        t.id = p;
        snprintf(t.label, sizeof(t.label), "button %d", i);
        out[k++] = t;
    }
    return k;
}

static int collect_textmenu(NavTarget *out, int max)
{
    return screens_textmenu_targets(rds32(TM_LEFT), rds32(TM_RIGHT), rds32(TM_TOP), rds32(TM_LINEH), rds32(TM_FIRST), rds32(TM_COUNT), rd32(TM_MASK), screen_w, screen_h, out, max);
}

/* the frame must look like one: a guest stack address (the loop's own function made the call), and the local the screen reads next is a small number */
static int frame_ok(uint32_t ebp)
{
    return ebp > 0x10000u && ebp < 0xf0000000u && (ebp & 3) == 0;
}

static int collect_buycards(NavTarget *out, int max)
{
    int32_t boxes[4 * BUY_MAX], ids[BUY_MAX];
    int n, i, k;

    k = collect_table(out, max);
    if (!frame_ok(cur_ebp))
        return k;
    n = rds32(cur_ebp + BUY_COUNT);
    if (n < 1 || n > BUY_MAX)
        return k;
    for (i = 0; i < 4 * n; i++)
        boxes[i] = rds32(cur_ebp + BUY_BOXES + 4 * (uint32_t)i);
    for (i = 0; i < n; i++)
        ids[i] = rds32(BUY_IDS + 4 * (uint32_t)i);
    return k + screens_card_targets(boxes, ids, n, screen_w, screen_h, out + k, max - k);
}

static int collect_clues(NavTarget *out, int max)
{
    int n, k = collect_table(out, max);

    if (!frame_ok(cur_ebp))
        return k;
    n = rds32(cur_ebp + CLUE_COUNT);
    if (n < 1 || n > 12)
        return k;
    return k + screens_clue_targets(n, screen_w, screen_h, out + k, max - k);
}

int screens_collect(NavTarget *out, int max, double now)
{
    switch (screens_kind(now)) {
    case SCREEN_TABLE: return collect_table(out, max);
    case SCREEN_TEXTMENU: return collect_textmenu(out, max);
    case SCREEN_BUYCARDS: return collect_buycards(out, max);
    case SCREEN_CLUES: return collect_clues(out, max);
    default: return 0;
    }
}

/* ---- the hooks ----------------------------------------------------------------------------------------------------------------------------------------- */
static uint32_t hook_table(const uint32_t *a)
{
    (void)a;
    screens_note(RD32(port_sp), lift_out.ebp, SRC_TABLE, port_now());
    return 0;
}

static uint32_t hook_snapshot(const uint32_t *a)
{
    (void)a;
    screens_note(RD32(port_sp), lift_out.ebp, SRC_SNAPSHOT, port_now());
    return 0;
}

void screens_install(void)
{
    if (strcmp(lift_game->program, "MAGIC"))
        return;
    port_prehook(0x41f3eau, hook_table);       /* the button table's pass: pace.c has a hook there too, both run */
    port_prehook(0x44b84bu, hook_snapshot);    /* the mouse snapshot, taken by every loop that reads the mouse */
}

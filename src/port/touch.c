/* touch.c - fingers as a mouse (touch.h). Pure. */
#include <stdlib.h>

#include "touch.h"

static void push(Touch *t, TouchKind k, int x, int y)
{
    const int cap = (int)(sizeof(t->q) / sizeof(t->q[0]));

    if (t->qn == cap) {                                                   /* full (the caller drains it after every event, and an event adds at most four): make room, or drop this */
        int i;

        if (t->qhead == 0)
            return;
        for (i = t->qhead; i < t->qn; i++)
            t->q[i - t->qhead] = t->q[i];
        t->qn -= t->qhead;
        t->qhead = 0;
    }
    t->q[t->qn].kind = k;
    t->q[t->qn].x = x;
    t->q[t->qn].y = y;
    t->qn++;
}

int touch_next(Touch *t, TouchAction *a)
{
    if (t->qhead >= t->qn) {
        t->qhead = t->qn = 0;
        return 0;
    }
    *a = t->q[t->qhead++];
    return 1;
}

void touch_init(Touch *t)
{
    t->state = TS_IDLE;
    t->hold_press = 0;
    t->id1 = t->id2 = -1;
    t->x0 = t->y0 = t->x1 = t->y1 = 0;
    t->moved = t->left_down = t->fingers = 0;
    t->t0 = 0;
    t->qn = t->qhead = 0;
}

void touch_set_hold_press(Touch *t, int on) { t->hold_press = on != 0; }
int touch_active(const Touch *t) { return t->fingers > 0; }

static int far_from(int x, int y, int x0, int y0)
{
    int dx = x - x0, dy = y - y0;

    return dx * dx + dy * dy > TOUCH_SLOP * TOUCH_SLOP;
}

void touch_down(Touch *t, int id, int x, int y, uint32_t ms)
{
    if (t->state == TS_IDLE) {
        t->id1 = id;
        t->id2 = -1;
        t->x0 = t->x1 = x;
        t->y0 = t->y1 = y;
        t->moved = 0;
        t->t0 = ms;
        t->fingers = 1;
        push(t, TA_MOVE, x, y);
        t->left_down = 0;
        t->state = TS_PENDING;
        return;
    }
    if (id == t->id1 || id == t->id2)
        return;                                                     /* the same finger again: nothing */
    t->fingers++;
    if (t->id2 >= 0)
        return;                                                     /* a third finger: counted, ignored */
    /* a second finger: a two-finger tap if the touch is still undecided and recent */
    if ((t->state == TS_PENDING || t->state == TS_PRESSED) && ms - t->t0 <= TOUCH_TWO_MS && !t->moved) {
        if (t->left_down) {
            push(t, TA_LUP, t->x1, t->y1);
            t->left_down = 0;
        }
        t->id2 = id;
        t->state = TS_TWO;
    }
}

void touch_move(Touch *t, int id, int x, int y, uint32_t ms)
{
    (void)ms;
    if (id != t->id1)
        return;
    t->x1 = x;
    t->y1 = y;
    switch (t->state) {
    case TS_PENDING:
        if (far_from(x, y, t->x0, t->y0)) {                         /* a drag: the button goes down where the finger started, then follows it */
            t->moved = 1;
            push(t, TA_LDOWN, t->x0, t->y0);
            t->left_down = 1;
            t->state = TS_PRESSED;
            push(t, TA_MOVE, x, y);
        }
        break;
    case TS_PRESSED:
        if (far_from(x, y, t->x0, t->y0))
            t->moved = 1;
        push(t, TA_MOVE, x, y);
        break;
    case TS_TWO:
        if (far_from(x, y, t->x0, t->y0))
            t->state = TS_TWO_DONE;                                 /* the first finger wandered: not a tap (and nothing else either: the touch is spent) */
        break;
    default:
        break;                                                      /* after a long press, or a two-finger tap: the finger is ignored */
    }
}

static void all_up(Touch *t)
{
    if (t->fingers <= 0) {
        t->fingers = 0;
        t->state = TS_IDLE;
        t->id1 = t->id2 = -1;
        t->left_down = 0;
    }
}

void touch_up(Touch *t, int id, int x, int y, uint32_t ms)
{
    if (t->state == TS_IDLE)
        return;
    if (t->fingers > 0)
        t->fingers--;
    if (id != t->id1 && id != t->id2) {                             /* a finger that was ignored */
        all_up(t);
        return;
    }
    switch (t->state) {
    case TS_PENDING:                                                /* a tap */
        push(t, TA_MOVE, x, y);
        push(t, TA_LDOWN, x, y);
        push(t, TA_LUP, x, y);
        t->state = TS_IDLE;
        t->fingers = 0;
        break;
    case TS_PRESSED:
        push(t, TA_MOVE, x, y);
        push(t, TA_LUP, x, y);
        t->left_down = 0;
        t->state = TS_IDLE;
        t->fingers = 0;
        break;
    case TS_TWO:
        if (ms - t->t0 <= TOUCH_TWO_MS) {                           /* a two-finger tap: a right click where the first finger went down */
            push(t, TA_MOVE, t->x0, t->y0);
            push(t, TA_RDOWN, t->x0, t->y0);
            push(t, TA_RUP, t->x0, t->y0);
        }
        t->state = TS_TWO_DONE;
        break;
    case TS_LONG:
    case TS_TWO_DONE:
    default:
        break;
    }
    all_up(t);
}

void touch_tick(Touch *t, uint32_t ms)
{
    if (t->state == TS_PENDING && !t->moved && t->hold_press && ms - t->t0 >= TOUCH_HOLD_MS) {      /* held where a held button matters: the button goes down, where the finger began */
        push(t, TA_LDOWN, t->x0, t->y0);
        t->left_down = 1;
        t->state = TS_PRESSED;
        return;
    }
    if (t->state == TS_PENDING && !t->moved && ms - t->t0 >= TOUCH_LONG_MS) {
        push(t, TA_RDOWN, t->x0, t->y0);
        push(t, TA_RUP, t->x0, t->y0);
        t->state = TS_LONG;
    }
}

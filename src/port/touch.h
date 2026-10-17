/*
 * touch.h - fingers as a mouse, for a touch screen (the iPad), as a pure state machine: no SDL and no game, so it is unit tested (test_touch.c). docs/notes/ios.md.
 *
 * The game wants a mouse: a left button (a click, a hold that walks the party on the map, a drag) and a right button (the card menus of a duel). SDL's own conversion
 * (a finger is the left button, at once) has no right button, so it is switched off (front_sdl.c) and this does it:
 *
 *   - a finger down moves the pointer there (the game shows the card under it) and waits to see what the touch is:
 *       - lifted soon, without moving: a tap, a left click where it was;
 *       - moved more than TOUCH_SLOP: a drag, the left button goes down where the finger started and follows it, up when the finger lifts;
 *       - held still for TOUCH_LONG_MS: a long press, one right click there (the finger lifting afterwards does nothing);
 *   - a second finger down while the first is still undecided (and within TOUCH_TWO_MS of it) and a lift of either within TOUCH_TWO_MS of the first touch, without either having
 *     moved far: a two-finger tap, one right click where the first finger was;
 *   - where a held button means something (the world map: the party walks while it is held) the front end says so (touch_set_hold_press): a finger held still for TOUCH_HOLD_MS then
 *     presses the left button where it went down, and there is no long press. (A second finger within TOUCH_TWO_MS lets the button go again and is a two-finger tap as above.)
 *
 * Positions are the game's screen pixels. The caller turns what comes out into mouse events; time is in milliseconds (any origin).
 */
#ifndef PORT_TOUCH_H
#define PORT_TOUCH_H

#include <stdint.h>

#define TOUCH_LONG_MS 500           /* held still this long: a long press (right click) */
#define TOUCH_TWO_MS 350            /* a two-finger tap: both fingers down and one lifted within this long of the first touch */
#define TOUCH_HOLD_MS 150           /* where a held button is wanted (touch_set_hold_press): a finger held still this long presses the left button */
#define TOUCH_SLOP 12               /* game pixels a finger may wander and still be a tap or a long press (a drag past it) */

typedef enum { TA_MOVE, TA_LDOWN, TA_LUP, TA_RDOWN, TA_RUP } TouchKind;
typedef struct { TouchKind kind; int x, y; } TouchAction;

typedef enum { TS_IDLE, TS_PENDING, TS_PRESSED, TS_LONG, TS_TWO, TS_TWO_DONE } TouchState;

typedef struct {
    TouchState state;
    int hold_press;             /* a finger held still for TOUCH_HOLD_MS presses the left button (and is no long press): set by the caller while a held button matters */
    int id1, id2;               /* the fingers (id2 < 0: none) */
    int x0, y0;                 /* where the first finger went down */
    int x1, y1;                 /* where it is now */
    int moved;                  /* the first finger has gone past the slop */
    int left_down;
    int fingers;                /* how many are down */
    uint32_t t0;                /* when the first finger went down */
    TouchAction q[16];
    int qn, qhead;
} Touch;

void touch_init(Touch *t);
void touch_set_hold_press(Touch *t, int on);                          /* whether a held finger is a held button right now (call before every touch_tick: the answer can change) */
void touch_down(Touch *t, int id, int x, int y, uint32_t ms);
void touch_move(Touch *t, int id, int x, int y, uint32_t ms);
void touch_up(Touch *t, int id, int x, int y, uint32_t ms);
void touch_tick(Touch *t, uint32_t ms);                               /* call often (every few ms while a finger is down): the long press is decided by the clock */
int touch_next(Touch *t, TouchAction *a);                             /* the next thing to do as a mouse, in order; 0 when there is none */
int touch_active(const Touch *t);                                     /* a finger is down (the caller keeps ticking) */

#endif

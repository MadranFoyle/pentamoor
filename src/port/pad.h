/*
 * pad.h - a game controller as a mouse and a keyboard. The game only ever sees a pointer position, two buttons and keys, so a pad is emulation in the front end:
 * this file is the logic of it, with no SDL and no game in it (the window half, front_sdl.c, feeds it controller events and the clock and sends the actions it
 * returns through front_push_mouse and front_push_key). Everything that can be tuned is at the top of pad.c; docs/notes/controller.md says what each control does.
 *
 * Positions are screen pixels (the game's own, whatever PORT_RES and the window's size are). Axes come as SDL gives them: sticks -32768..32767 (y down is
 * positive), triggers 0..32767.
 */
#ifndef PORT_PAD_H
#define PORT_PAD_H

#include <stdint.h>

/* the controls, in SDL_GameController's own names (the window half translates); the triggers are buttons here, made from their axes */
enum {
    PAD_A, PAD_B, PAD_X, PAD_Y, PAD_BACK, PAD_GUIDE, PAD_START, PAD_LSTICK, PAD_RSTICK, PAD_LB, PAD_RB,
    PAD_DUP, PAD_DDOWN, PAD_DLEFT, PAD_DRIGHT, PAD_LT, PAD_RT, PAD_NBUTTONS
};
enum { PAD_AX_LX, PAD_AX_LY, PAD_AX_RX, PAD_AX_RY, PAD_AX_LT, PAD_AX_RT };

/* what the pad asks the game to see */
enum { PA_MOVE, PA_LDOWN, PA_LUP, PA_RDOWN, PA_RUP, PA_KEYDOWN, PA_KEYUP, PA_NAV };
typedef struct { int type, x, y; uint32_t vk, sc; int ch, repeat; int dir; } PadAct;      /* x, y: where the pointer is (all mouse actions, and PA_NAV: where it is now); vk, sc, ch, repeat: keys; dir: PA_NAV, the D-pad's direction (0 up, 1 down, 2 left, 3 right: nav.h's NAV_UP...) */
#define PAD_MAXACT 64
typedef struct { PadAct act[PAD_MAXACT]; int n; } PadOut;

/* what a control is bound to (the table is at the top of pad.c) */
enum { PB_NONE, PB_LCLICK, PB_RCLICK, PB_KEY, PB_SLOW, PB_FAST, PB_WALK, PB_STEP, PB_NAV };
typedef struct {
    int btn, act;
    uint32_t vk, sc;              /* PB_KEY */
    int ch;                       /* the character it types, or -1 */
    int rep;                      /* PB_KEY: repeats while held, as a keyboard does */
    int dx, dy;                   /* PB_STEP: the direction of one step */
} PadBind;

typedef struct {
    int sw, sh;                   /* the screen */
    int active;                   /* the pad was the last device used: its cursor is drawn and its sticks move it */
    float ax[6];                  /* lx ly rx ry (-1..1, y down positive), lt rt (0..1) */
    uint32_t down;                /* PAD_ buttons held (bit per button) */
    float fx, fy;                 /* the cursor, in pixels, with a fraction */
    int ix, iy;                   /* where the game was last told the pointer is */
    int left_src;                 /* what holds the left button down: bit 0 the A button, bit 1 walking */
    int right_down;
    int walking;
    int ox, oy;                   /* where the avatar is on the screen (walking aims from it) */
    int dir8;                     /* the right stick as a key: -1 none, else 0..7 (see pad_dir8) */
    struct { int on, rep, ch; uint32_t vk, sc; int held, next; } key[PAD_NBUTTONS + 1];      /* keys the pad holds down: one per control, one for the right stick */
    int step_held[4], step_next[4];                                                           /* the D-pad's auto-repeat */
    int nav;                      /* the game has things to move between now (a duel, a dialog, a menu): the D-pad moves the pointer between them (PB_NAV) instead of pressing its arrow key */
    struct { int on, nav, next; } dp[4];                                                      /* PB_NAV controls held: whether the press was a move (else its key is down), and the next repeat */
} Pad;

void pad_init(Pad *p, int sw, int sh);
void pad_set_screen(Pad *p, int sw, int sh);
const PadBind *pad_bindings(int *n);

/* a stick's deflection (-1..1 each) as the cursor sees it: the dead zone taken out and the curve applied; returns the length 0..1 (0 inside the dead zone) */
float pad_stick(float x, float y, float *ox, float *oy);
/* the pixels per second of a cursor driven at a stick's (deflected, 0..1) length, on a screen sw wide, with the slow / fast modifiers */
float pad_speed(float len, int sw, int slow, int fast);
/* the right stick as eight directions: 0 up, 1 up-right, 2 right, 3 down-right, 4 down, 5 down-left, 6 left, 7 up-left; -1 inside the threshold. `was` is the
 * direction held now (-1 none): it needs less to stay than to start. */
int pad_dir8(float x, float y, int was);
int pad_clamp(int v, int lo, int hi);

/* A controller event. pad_axis returns whether it is real use (not a stick's drift: past the dead zone, or a trigger pressed, or a stick coming back to rest). */
int pad_axis(Pad *p, int axis, int value, PadOut *out);
void pad_button(Pad *p, int btn, int down, PadOut *out);
/* Time passes (ms): the cursor moves, walking aims, held keys repeat. */
void pad_step(Pad *p, int ms, PadOut *out);
/* The mouse (or a touch) was used at x, y: the pad is not the active device now, its cursor follows the mouse and what it holds is let go. */
void pad_mouse_used(Pad *p, int x, int y, PadOut *out);
/* Every control let go and the sticks at rest (a controller was unplugged, the window lost the focus): what was held comes up. */
void pad_release_all(Pad *p, PadOut *out);
void pad_set_origin(Pad *p, int x, int y);
/* Whether the game has things the D-pad can move the pointer between (front.c knows). A press uses the answer of the moment it is made. */
void pad_set_nav(Pad *p, int on);
/* The pointer is put at x, y (the answer to a PA_NAV): the game is told as it is for a stick's move. */
void pad_put(Pad *p, int x, int y, PadOut *out);
/* One tap of the arrow key of a direction (the answer 'scroll' to a PA_NAV: a list that goes on in that direction): key down, key up. */
void pad_tap_dir(Pad *p, int dir, PadOut *out);

/* The pointer's arrow, drawn into a frame (rgb, w x h x 3) with its tip at x, y; clipped to the frame. pad_cursor_scale: how many pixels each cell of it is. */
int pad_cursor_scale(int w);
void pad_draw_cursor(uint8_t *rgb, int w, int h, int x, int y);

#endif

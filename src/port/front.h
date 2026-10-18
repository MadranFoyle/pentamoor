/*
 * front.h - the host's window: where the screen is shown and the mouse and keyboard come from.
 *
 * The front end has two halves. The window half (front_sdl.c, SDL2) runs on the program's main thread, as SDL requires on some systems, and
 * only queues what it sees; the guest half (front.c) runs on whichever guest thread holds the baton (sched.h), at the points where the baton
 * passes and wherever the game waits for a message. So the guest's state (windows, message queues) is touched by one thread at a time, and
 * the window half never touches it: input goes in through a queue, the screen comes out as the latest composed frame.
 */
#ifndef PORT_FRONT_H
#define PORT_FRONT_H

#include <stddef.h>
#include <stdint.h>

/* ---- called from the window thread (any thread) ---- */
void front_push_mouse(int kind, int x, int y);                            /* kind: IN_MOVE, IN_DOWN, ... (wm.h); screen pixels */
void front_push_key(uint32_t vk, uint32_t scancode, int down, int ch, int repeat);   /* ch: the character the key types, or -1 */
void front_push_char(int ch);                                             /* a character with no key (WM_CHAR alone: Latin-1 text from an input method) */
void front_push_call(uint32_t addr, const uint32_t *args, int n);          /* start a guest function on a new thread (a test and debugging aid) */
void front_push_quit(void);                                               /* the window was closed */
/* The D-pad's navigation (navwm.c, docs/notes/controller-nav.md): a press with the pointer at x, y; dir is a NAV_ direction (nav.h), or -1 to print the targets on stderr. It is answered
 * on the guest side, where the window tree may be read, and the answer comes back through front_nav_result. front_nav_ready: whether there is anything to navigate now (a duel, a dialog, a
 * popup menu), as of the last frame; the pad presses the arrow keys instead when there is not. */
void front_push_nav(int dir, int x, int y);
int front_nav_ready(void);
enum { NAVR_MOVE = 1, NAVR_SCROLL };
int front_nav_result(unsigned *seen, int *kind, int *x, int *y, int *dir);       /* 1 if there is an answer newer than *seen */
/* View card (docs/notes/controller.md): the game's own Full-size card window shows the card under (x, y) at once, instead of after the pointer has rested on it. Done on the guest side (navwm.c).
 * front_view_ready: there is a card under the pointer in a duel (as of the last frame): the pad's view button is that, and Page Up when there is none. */
void front_push_view(int x, int y);
int front_view_ready(void);
/* The enlarged card (the second press of the view button on the same card, docs/notes/controller.md): the picture of the game's Full-size card window as it was at that press, a copy the window half
 * shows over the frame. front_zoom_take copies it when it is newer than *seen (cap bytes of room: w * h * 3), returns 1 and its size. */
int front_zoom_take(uint8_t *rgb, size_t cap, unsigned *seen, int *w, int *h);
/* Copy the latest frame (640x480 RGB) if it is newer than *seen; returns 1 if it was. */
int front_take_frame(uint8_t *rgb, unsigned *seen);
/* The game has ended: the window half stops. */
int front_finished(void);

int front_text_wanted(void);                                              /* a text field has the focus: the on-screen keyboard may show (steamdeck.h) */

/* ---- the guest side ---- */
void front_note_name_entry(void);                                         /* the game's name box asked for a key just now (textfocus.c) */
void front_install(void);                                                 /* the hooks that serve the queue and publish frames */
void front_serve(double max_wait);                                        /* deliver queued input, publish a frame if one is due */

/* The hold on a pressed button or key (front.c): whether the event after a press must wait yet. held_ms: how long the press has been down; mouse: it is a
 * mouse button; seen: a screen's loop has seen the button down; ui_active: such a loop has passed lately. */
int front_hold_rule(uint32_t held_ms, int mouse, int seen, int ui_active);
/* From the pre-call hook of a screen's loop pass (pace.c): note that a pass is starting; *id is the number of the latest mouse press (0: none yet), *held_ms how long it has lasted
 * (0 if it is up); returns whether it is down. front_ui_saw: the pass has the button down, so the press has been seen and may end. */
int front_ui_pass(uint32_t *id, uint32_t *held_ms);
void front_ui_saw(void);

/* Run `game(arg)` (the whole program) and the window. SDL: the game on a new thread and the window here; without SDL: the game here.
 * Returns the game's exit code. */
int front_run(int (*game)(void *), void *arg);
int front_has_window(void);

#endif

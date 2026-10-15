/* yesno.h - the game's own "(Y/N)" questions (yesno.c): who is asking, and what answers them besides the keyboard. */
#ifndef PORT_YESNO_H
#define PORT_YESNO_H

#include <stdint.h>

/* How long after its last poll for a key the game still counts as asking (it polls on every pass of its wait loop). */
#define YESNO_HOLD_MS 200

/* Is `ret` a place the game asks a yes/no question from: the address a call of its wait-for-key function (0x48ac2f) returns to? Three are known: buying a card (the village's
 * "Cards for Sale": "Buy for 20 gold?   (Y/N)"), selling one in the deck editor ("Sell X for N gold? (Y/N)") and taking one ("Take X   (Y/N)"). */
int yesno_site(uint32_t ret);

/* The state of the question at time `now_ms`: the game polled for the key at `poll_ms` (0: never). */
int yesno_asking(uint32_t now_ms, uint32_t poll_ms);

/* What a mouse press at `now_ms` means while the game asks (`kind` is an IN_ event of wm.h; the game last polled at `poll_ms`): 'y' for the left button, 'n' for the right one; 0 when
 * nothing is asked or it is another event (it goes on to the game as it was). */
int yesno_press_answer(int kind, uint32_t now_ms, uint32_t poll_ms);

/* The runtime's side (front.c asks these on the guest side). */
void yesno_note_poll(void);                      /* the game's wait loop for a key polled just now (the hook; the tests call it too) */
int yesno_waiting(void);                         /* the game is asking a yes/no question now: the hint is shown, a click answers */
int yesno_mouse(int kind);                       /* a mouse event about to be delivered: 'y' or 'n' = it answers (send that key instead), -1 = drop it (the release of an answering press), 0 = deliver it */
void yesno_install(void);                        /* the hooks that tell when the game asks (MAGIC.EXE only) */

#endif

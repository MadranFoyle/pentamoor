/* yesno.c - the game's own "(Y/N)" questions.
 *
 * "Buy for 20 gold?   (Y/N)" (a card in a village's "Cards for Sale"), "Sell <card> for N gold? (Y/N)" (the deck editor's sell) and "Take <card>   (Y/N)" are not dialogs and not
 * message boxes: the game draws the question over its own picture and then waits in 0x48ac2f ("wait for a key", a loop of polls of its key queue, 0x4080b2) for a key. 'y' (and
 * for two of the three 'Y') answers yes, any other key no. Nothing else can answer: a click does nothing, and a controller, which has no Y key, is left with a screen that does not
 * go away.
 *
 * So, while one of these three is asking, the mouse answers it too: the left button (a controller's A) is Y, the right button (B) is N, and the screen says so (compose.c). It is
 * known to be asking by the same two hooks that textfocus.c uses for the name box: the wait-for-key function is entered from a place (its return address) that is one of the three,
 * and while it is polling, each poll notes the time. A click is turned into the key press in front.c (deliver), and nothing else about the click reaches the game.
 *
 * The addresses are those of the game's code (MAGIC.EXE, version 1.0); each site is the instruction after the call of 0x48ac2f. */
#include <string.h>

#include "front.h"
#include "port.h"
#include "sched.h"
#include "wm.h"
#include "yesno.h"

#define WAIT_KEY 0x48ac2fu
#define POLL_KEY 0x4080b2u
#define WAIT_LOOP_RET 0x48ac3du                  /* where the poll inside the wait loop returns to */

static const uint32_t sites[] = {0x509e4au, 0x4f156eu, 0x45119du};

int yesno_site(uint32_t ret)
{
    size_t i;

    for (i = 0; i < sizeof(sites) / sizeof(sites[0]); i++)
        if (sites[i] == ret)
            return 1;
    return 0;
}

int yesno_asking(uint32_t now_ms, uint32_t poll_ms)
{
    return poll_ms != 0 && now_ms - poll_ms < YESNO_HOLD_MS;
}

int yesno_press_answer(int kind, uint32_t now_ms, uint32_t poll_ms)
{
    if (!yesno_asking(now_ms, poll_ms))
        return 0;
    return kind == IN_DOWN ? 'y' : kind == IN_RDOWN ? 'n' : 0;
}

static volatile uint32_t poll_ms;                /* when the wait loop of a yes/no question last polled; 0: not asking */
static int in_question;                          /* the wait-for-key function now running was entered from one of the sites */
static int swallow_up;                           /* the release of a press that answered is still to come: the game does not get it */

static uint32_t wait_enter(const uint32_t *a)
{
    (void)a;
    in_question = yesno_site(RD32(port_sp));     /* the hook runs with the return address on top of the stack, as in pace.c */
    return 0;
}

void yesno_note_poll(void)
{
    uint32_t t = port_now_ms();

    poll_ms = t ? t : 1;
}

static uint32_t wait_poll(const uint32_t *a)
{
    (void)a;
    if (in_question && RD32(port_sp) == WAIT_LOOP_RET)
        yesno_note_poll();
    return 0;
}

int yesno_waiting(void)
{
    return yesno_asking(port_now_ms(), poll_ms);
}

int yesno_mouse(int kind)
{
    int ans = yesno_press_answer(kind, port_now_ms(), poll_ms);

    if (ans) {
        poll_ms = 0;                             /* one answer per question: the second click of a double click is not another */
        swallow_up = 1;
        return ans;
    }
    if ((kind == IN_UP || kind == IN_RUP) && swallow_up) {
        swallow_up = 0;
        return -1;
    }
    return 0;
}

void yesno_install(void)
{
    if (strcmp(lift_game->program, "MAGIC"))
        return;
    port_prehook(WAIT_KEY, wait_enter);
    port_prehook(POLL_KEY, wait_poll);
}

/* pace.c - the overworld's frame rate.
 *
 * The overworld loop of MAGIC.EXE (0x4e7867..0x4e7911) means to wait 60 ms for every frame: `while (clock() - last < 60);`. But `last` is a local that the loop
 * head sets to 0 (`mov [ebp-0x1c], 0` at 0x4e7867, inside the loop), so after the first 60 ms of the process the wait never waits, and the game runs a frame as soon
 * as the last one is drawn: its speed was whatever the 1997 machine could draw (a few frames a second), where a native CPU draws hundreds. A held mouse button
 * moves the party a step each frame, so the tiniest press went a long way. The frame is paced here, where the loop starts it: the call of 0x5016f9 (the tick
 * counter's read-and-clear) at 0x4e786e returns to 0x4e7873. The period is the game's own 60 ms unless PORT_FRAME_MS says otherwise. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "front.h"
#include "port.h"
#include "sched.h"

#define FRAME_RET 0x4e7873u                     /* where the overworld loop's call of 0x5016f9 returns to */
#define TICKS 0x530da0u                         /* the 33 ms timer's tick counter, which 0x5016f9 returns and clears */

static double period = 0.060, last;
static int log_slow;                            /* PORT_FRAME_LOG=1: report every frame that took more than the period and 15 ms */

/* 0x5016f9: return the ticks counted and start counting again. From the overworld loop it also waits out the rest of the frame. */
static uint32_t read_and_clear_ticks(const uint32_t *a)
{
    uint32_t t;

    (void)a;
    if (RD32(port_sp) == FRAME_RET && period > 0) {
        double now = port_now(), wait = last + period - now;

        if (log_slow && last > 0 && now - last > period + 0.015)
            port_log("overworld frame took %.0f ms (the period is %.0f)", (now - last) * 1000, period * 1000);
        if (last > 0 && wait > 0)
            sched_sleep(wait);
        last = port_now();
    }
    t = RD32(TICKS);
    WR32(TICKS, 0);
    return t;
}


/* The loops of the game's other screens (the title menu, the village, the castle, the shops) call 0x41f3ea once a pass, with the mouse's place and button, and the button's
 * handler runs on every pass while the button is down. A click is meant to be one pass. What made it two or three:
 *  - a pass is a redraw (2.6 ms), and a press lasts 70 ms or longer (front.c), so a click was tens of passes (a village's "Buy 10 food" 27 times); the pass was paced to 60 ms
 *    while the button is down, which left two or three;
 *  - the button's state is an argument of the call, pushed before this hook runs: a hook that waits (the pacing) hands the call a state that is older than the wait, so ending the
 *    press early did not help: the pass after the wait still had the button down;
 *  - a click that ends a screen starts the next screen's loop while the button is still down, and that loop's first pass saw the same press.
 * Now the first pass of a press that sees the button down is the click: it runs as it is, and front.c ends the press at once (front_ui_saw). A later pass of the same press sees the
 * button up (the argument and the game's variable are cleared), until the press has lasted REPEAT_MS: then it repeats, a pass per frame period, as a held button did. The map's loop
 * (Adventure_EnterTownLocation, 0x4e73a0..0x4e7936: it walks the party while the button is held, and reads the button elsewhere than here) is left to the frame pacing alone. */
#define UI_PASS 0x41f3eau
#define BUTTON_VAR 0x7039c4u                    /* the game's mouse button state: 1 left, 2 right, 0 up (the window procedure sets it) */
#define MAP_LOOP_LO 0x4e73a0u
#define MAP_LOOP_HI 0x4e7936u
#define REPEAT_MS 400u                          /* a button held this long repeats */

static double ui_last;
static uint32_t cur_press, press_val;           /* the press the loops have acted on (front.c's number), and the button state it had */
static int suppressed, carried, ui_log;

static uint32_t pace_ui_pass(const uint32_t *a)
{
    uint32_t ret = RD32(port_sp), arg = port_sp + 12, id, held;      /* a[2] is at port_sp + 12 */
    int down;
    double now = port_now(), wait = ui_last + period - now;

    if (ret >= MAP_LOOP_LO && ret < MAP_LOOP_HI) {      /* the map: nothing but the frame period between passes with the button down */
        if (a[2] == 0)
            return 0;
        if (period > 0 && ui_last > 0 && wait > 0)
            sched_sleep(wait);
        ui_last = port_now();
        return 0;
    }
    down = front_ui_pass(&id, &held);
    if (id != 0 && id != cur_press && a[2] != 0) {     /* the first pass that sees this press down: the click */
        cur_press = id;
        press_val = a[2];
        suppressed = 0;
        carried = held >= REPEAT_MS;                    /* a press that began on the map and walked the party onto this screen is not a click on it */
        if (ui_log)
            port_log("ui pass from 0x%x: %s (press %u, state %u, down for %u ms)", ret, carried ? "carried over" : "click", id, a[2], held);
        if (!carried) {
            front_ui_saw();
            ui_last = now;
            return 0;
        }
    }
    if (id != cur_press)                                /* no press has been acted on */
        return 0;
    /* the press has been acted on */
    if (!down || held < REPEAT_MS || carried) {                    /* it is over (the release is on its way to the game) or too young to repeat: the game sees the button up */
        if (a[2] != 0 || RD32(BUTTON_VAR) != 0) {
            WR32(arg, 0);
            WR32(BUTTON_VAR, 0);
            suppressed = down;
            if (ui_log)
                port_log("ui pass from 0x%x: press %u %s, held %u ms, shown as up", ret, id, down ? "down" : "over", held);
        }
        return 0;
    }
    if (suppressed) {                                   /* held long enough: the game sees the button down again */
        WR32(BUTTON_VAR, press_val);
        suppressed = 0;
    }
    if (period > 0 && wait > 0)
        sched_sleep(wait);
    ui_last = port_now();
    WR32(arg, RD32(BUTTON_VAR));                        /* the state as it is after the wait */
    if (ui_log)
        port_log("ui pass from 0x%x: press %u held, repeat (state %u)", ret, id, RD32(BUTTON_VAR));
    return 0;
}

void pace_install(void)
{
    const char *ms = getenv("PORT_FRAME_MS");

    if (strcmp(lift_game->program, "MAGIC"))
        return;
    if (ms)
        period = atof(ms) / 1000.0;
    log_slow = getenv("PORT_FRAME_LOG") != NULL;
    ui_log = getenv("PORT_UI_LOG") != NULL;
    port_override(0x5016f9, read_and_clear_ticks, 0, 0);
    port_prehook(UI_PASS, pace_ui_pass);
}

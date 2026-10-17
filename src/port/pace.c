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
#include "profile.h"
#include "sched.h"

/* The addresses are those of the build's profile (profile.c; the numbers in the comments are MAGIC.EXE 1.0's): pace.tick_fn 0x5016f9, pace.frame_ret 0x4e7873 (where the overworld
 * loop's call of it returns to), pace.ticks 0x530da0 (the 33 ms timer's tick counter, which it returns and clears), buttons.pass 0x41f3ea, buttons.mouse_var 0x7039c4,
 * pace.map_loop 0x4e73a0..0x4e7936. */

static double period = 0.060, last;
static int log_slow;                            /* PORT_FRAME_LOG=1: report every frame that took more than the period and 15 ms */

/* 0x5016f9: return the ticks counted and start counting again. From the overworld loop it also waits out the rest of the frame. */
static uint32_t read_and_clear_ticks(const uint32_t *a)
{
    uint32_t t;

    (void)a;
    if (RD32(port_sp) == profile->pace.frame_ret && period > 0) {
        double now = port_now(), wait = last + period - now;

        if (log_slow && last > 0 && now - last > period + 0.015)
            port_log("overworld frame took %.0f ms (the period is %.0f)", (now - last) * 1000, period * 1000);
        if (last > 0 && wait > 0)
            sched_sleep(wait);
        last = port_now();
    }
    t = RD32(profile->pace.ticks);
    WR32(profile->pace.ticks, 0);
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
#define PASS_BUDGET 20000                       /* back-edges a pass of the table may need (a few hundred in fact: the records' loops and their drawing); a budget below this is renewed at its start */
#define REPEAT_MS 400u                          /* a button held this long repeats */

static double ui_last;
static uint32_t cur_press, press_val;           /* the press the loops have acted on (front.c's number), and the button state it had */
static int suppressed, carried, ui_log;

static uint32_t pace_ui_pass(const uint32_t *a)
{
    uint32_t ret = RD32(port_sp), arg = port_sp + 12, id, held, btn = a[2];      /* a[2], the button state pushed for the call, is at port_sp + 12 (a is a copy: the state is kept in btn) */
    int down;
    double now = port_now(), wait = ui_last + period - now;

    if (ret >= profile->pace.map_loop.lo && ret < profile->pace.map_loop.hi) {      /* the map: nothing but the frame period between passes with the button down */
        if (btn == 0)
            return 0;
        if (period > 0 && ui_last > 0 && wait > 0)
            sched_sleep(wait);
        ui_last = port_now();
        return 0;
    }
    /* A pass is not to be preempted in the middle: the window's thread runs only when this one offers the baton (a loop back-edge whose budget ran out), and a press that is dispatched
     * after the argument was pushed, while the pass is running, is a press the pass does not see but the loop's own read of the variable after the call does (the Journal's and the
     * castle pager's loop at 0x40b4e8: it turns it into "next page" and waits for the button to come up, so Done never got the click). The baton is offered here, where the argument
     * can still be made right, and the pass starts with a full budget. */
    if (sched_yield_if_low(PASS_BUDGET) && btn == 0 && RD32(profile->buttons.mouse_var) != 0) {
        btn = RD32(profile->buttons.mouse_var);
        WR32(arg, btn);
        if (ui_log)
            port_log("ui pass from 0x%x: the press came in while the baton was offered: state %u", ret, btn);
    }
    down = front_ui_pass(&id, &held);
    if (id != 0 && id != cur_press && btn != 0) {     /* the first pass that sees this press down: the click */
        cur_press = id;
        press_val = btn;
        suppressed = 0;
        carried = held >= REPEAT_MS;                    /* a press that began on the map and walked the party onto this screen is not a click on it */
        if (ui_log)
            port_log("ui pass from 0x%x: %s (press %u, state %u, down for %u ms)", ret, carried ? "carried over" : "click", id, btn, held);
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
        if (btn != 0 || RD32(profile->buttons.mouse_var) != 0) {
            WR32(arg, 0);
            WR32(profile->buttons.mouse_var, 0);
            suppressed = down;
            if (ui_log)
                port_log("ui pass from 0x%x: press %u %s, held %u ms, shown as up", ret, id, down ? "down" : "over", held);
        }
        return 0;
    }
    if (suppressed) {                                   /* held long enough: the game sees the button down again */
        WR32(profile->buttons.mouse_var, press_val);
        suppressed = 0;
    }
    if (period > 0 && wait > 0)
        sched_sleep(wait);
    ui_last = port_now();
    WR32(arg, RD32(profile->buttons.mouse_var));                        /* the state as it is after the wait */
    if (ui_log)
        port_log("ui pass from 0x%x: press %u held, repeat (state %u)", ret, id, RD32(profile->buttons.mouse_var));
    return 0;
}

void pace_install(void)
{
    const char *ms = getenv("PORT_FRAME_MS");

    if (!profile->pace.tick_fn)             /* a file with no pacing in its profile (another program, or an unknown build): nothing is hooked */
        return;
    if (ms)
        period = atof(ms) / 1000.0;
    log_slow = getenv("PORT_FRAME_LOG") != NULL;
    ui_log = getenv("PORT_UI_LOG") != NULL;
    port_override(profile->pace.tick_fn, read_and_clear_ticks, 0, 0);
    port_prehook(profile->buttons.pass, pace_ui_pass);
}

/* Is the overworld's loop running (it has made a frame in the last third of a second)? The touch screen holds the left button with a finger there (the party walks while it is held) and
 * waits to tell a tap from a long press everywhere else (front_sdl.c, touch.h). Called from the window's thread; `last` is a double the game's thread writes once a frame: a stale read only
 * gives the answer of the frame before. */
int pace_map_active(void)
{
    double l = last;

    return l > 0 && port_now() - l < 0.35;
}

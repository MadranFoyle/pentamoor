# One click, one pass (0x41f3ea)

The loops of the game's screens (the title menus, the village, the castle pager at 0x40b4e8, the shops) call `0x41f3ea` once a pass with the mouse's x, y and button state (`DAT_007039c4`, set by the
main window's procedure: 1 on `WM_LBUTTONDOWN`, 2 on `WM_RBUTTONDOWN`, 0 on either button-up), and the handler of the button under the mouse runs on every pass that has the button down.
`overworld-walk2.md` had a click on "Buy 10 food for 15 gold" still costing 3 purchases; an attempt to end the press after the first pass that saw it still showed 2 passes at the title screen.

## Why it was two or three (found by tracing pass times against the dispatch of `WM_LBUTTONDOWN`/`UP`)

1. **The button state is an argument, read before the hook.** A pass is `push DAT_007039c4; call 0x41f3ea`. The pre-call hook of `pace.c` slept 60 ms for a pass with the button down, so even when the
   press was released during the sleep, the call went on with the value it had been pushed with. Ending the press early could not help while the hook slept.
2. **The next screen's loop sees the same press.** At the title screen: pass 1 (`ret 0x47a8f9`, t=16.361) sees the click and the loop ends; the next screen's loop (`0x47af79`) starts at once, its first
   pass has `DAT_007039c4` still 1 (the release was queued for 70 ms), and that second pass was the "2 passes per click". It is a different loop, so counting passes per loop never showed it.
3. `App_ProcessPendingMessages` (0x40a3e1) is the key queue's drain, not a message pump (it spins `while (DAT_0067bda0 != 0)` for the button to come up). The window's messages
   reach the guest through the host's pump (`wm_pump_hook`, called from `PeekMessage`); a delivered press is dispatched by the next pump, so a pass sees it at once.
4. The castle pager (loop at 0x40b4e8) also reads `DAT_007039c4` itself after the call (`& 1`: next page, `& 2`: previous), so masking only the argument is not enough there.

## What it does now

`front.c` knows the press (`press_id`, `press_t0`, whether a screen's loop has seen it) and `pace.c`'s hook on `0x41f3ea` (not for the map's loop, whose call returns inside
`Adventure_EnterTownLocation`, 0x4e73a0..0x4e7936: the map walks the party while the button is held, and reads the button elsewhere; it keeps the old frame pacing only):

- The **first pass that has the button down** is the click: it runs untouched and `front_ui_saw()` lets `front.c` end the press at once (the queued release is delivered at the next
  `front_serve`) instead of after 70 ms. A press that no screen's loop has seen ends after 70 ms as before (the map, keys); while a screen's loop is running (it passed within 300 ms) a press waits up to
  250 ms for a pass, so a screen that is busy loading does not lose the click (`front_hold_rule`, tested in `test_wm.c`).
- **Later passes of the same press** see the button up: the hook writes 0 into the call's argument and into `DAT_007039c4` (the castle's direct read), whether the release has been delivered yet or not
  (a real user's release arrives ~100 ms later), until the press has lasted `REPEAT_MS` (400 ms). A press that began on the map and was held until the village opened (age >= 400 ms at its first pass) is
  "carried over": not a click on the screen, ignored until released.
- A press held **past 400 ms** repeats like a held button: the game's variable is restored, passes are a frame period (60 ms) apart, the argument is re-read after the wait (it was stale).
- Old 60 ms pacing of the map loop's passes is unchanged. `PORT_UI_LOG=1` prints each decision.

## Measured (640x480, trace of the dispatch and the passes)

- Title menu chain (New Game, difficulty, colour, visage): one pass per click, one screen advanced per click; the next screen's first pass has the button shown as up ("held 10 ms, shown as up").
- Village "Buy 10 food": one `click`: 15 gold, +10 food (940/48 -> 925/58, 5000/50 -> 4985/60). A 120 ms `down`/`up`: one purchase. Two `click`s 200 ms apart: two. `down` held 1.2 s: one click,
  then 14 repeats (about 13 expected: (1.2 - 0.4) / 0.06).
- Walking on the map with a held button: the party and the scroll behave as before (no `ui pass` lines come from the map's loop).
- The processes of the runs were killed more than once from outside (exit status 0 = the SIGTERM path of the front end): other sessions' `pkill` on the shared machine; not related.

## Not verified

- The "carried over" rule (walk onto a village with the button held): the village opened only after the press ended in the tries (monsters and quest chases kept interrupting the walk).
- The castle pager (0x40b4e8): not reached.
- Right-button presses (`DAT_007039c4 = 2`) go through the same code but were not clicked in a screen of this loop.

## A release that lands on the window the press opened: the black screen after the deck builder

Report: leaving the deck builder (Exit, or Exit and "Remove Extra Cards" when the deck holds more than four of a card) from the village's "Edit deck/Sell cards" left the main window black. A click anywhere
brought the village back (checked below: both variables 0 and the deck at 45 of 47 after the removal). From the map (F1) it did not happen (no press opens the builder there); a plain `click` of the control pipe hit it too.

**Cause.** "Edit deck" acts on the *press*: the game opens the deck builder (its own top-level window, a popup the main window owns) while the button is still down. The release then goes to the window under the pointer,
which is the builder's, so the main window never gets `WM_LBUTTONUP` and its window procedure leaves `DAT_007039c4` at 1 (and `DAT_0067bda0`, the snapshot of it, at 1). When the builder returns, the village's loop
runs `App_ProcessPendingMessages` (0x40a3e1), which spins on `DAT_0067bda0 != 0` *before it redraws anything* (the first part of this note: it waits for the button to come up). It waits for a release that has already
happened; the screen is the black the builder's exit left, until the next click, whose press and release both reach the main window. `game.log` shows nothing, the CPU is the spin, `windows` shows the main window alone.
The original on a 1997 machine took a good part of a second to put the builder on the screen (it reads the card lists first), so a click was over before the window existed and the release found the main window.
Here the window is up in a few milliseconds.

**Reproduced headless** (1024x768, a village, `Edit deck` as `down`, 150 ms, `up`; the deck builder's `Exit`; for the extra cards `poke 0x321cded4 6` on the stock list's first entry before Exit, then the dialog's
"Remove Extra Cards" button): before the change a black screen with `DAT_007039c4 = 1` and `DAT_0067bda0 = 1`; the same through F1 on the map: the map is back at once with the deck at 45 of 47, both variables 0.

**Fix** (`input.c`, `wm_inject_mouse`): the window that took a left press is remembered, with the handle the next window would get at that moment. The release goes to that window when a top-level window
has come into being since (its handle is not below the remembered one) and is not the press window's own top-level; in every other case it goes where the pointer is, as before (a card dragged inside the builder,
a button that is pressed and released on itself). `test_wm` +6 checks (`test_release_follows_press`: it fails without the change).
Checked: the sequence above before and after (the village comes back at once after Exit and after "Remove Extra Cards", both variables 0), F1 as before.
Not checked: with a controller (A is a press and a release like the mouse's, so the same), a very long press (the same path), the standalone `DECK.EXE` (it opens no window on a press).

## A press that comes in while a pass is running

The pre-call hook offers the baton before it looks at the press, so the pass cannot be preempted in the middle and the window's thread has dispatched the latest press before the pass reads it: the Journal's Done lost
its click without that (`journal-done.md`).

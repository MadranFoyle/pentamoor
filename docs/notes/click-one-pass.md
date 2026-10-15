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

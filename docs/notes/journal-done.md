# The Journal's Done button that did not always work

`resolution.md` recorded it: from Wiz Stats, the Journal's Done answered a scripted click the first time and then, in the next try, left the Journal on the screen (the same with `click`, `move` + `click` and `down`/`up`,
and at 640x480 before the resolution change, so not a matter of size). "The loop sat in its redraw pass and the pass that tests the button never took the press." It was found, reproduced at will and fixed.

## Reproduced

640x480, a game resumed from `sources/emu_overlay`, monsters poked out, gold poked, then: click the wizard button (32,262), the Journal button (523,18), Done (545,19) (a small script of `PORT_CONTROL`
commands; the same sequence as `castle-dungeon-stats.md`). With `PORT_UI_LOG=1` and `PORT_PAD_LOG=stderr`: Journal, Done, Journal, Done ... **from a third to nine tenths of the Done clicks did nothing** (3 taken of 8 in one run, 1 of 10 in another); the rest went through. The D-pad
and A path (`screen_nav_play.py`, step `stats`) failed at the first round of 8: the same code, since A is a press and a release like the mouse's.

## The cause

The Journal is the loop at 0x40b4e8 (the same function the notes called the castle pager; it is the pager of the journal's pages). A pass of it is:

    push [0x7039c4]  ; call 0x41f3ea         the button table's pass: hover, and a click on the button under the mouse
    cmp  [0x5384d0], -1 ; jne  end           the Done button's click function (0x40b00c) left a result: leave
    cmp  [0x7039c4], 0  ; jne  page          **the loop reads the button again itself**: a press is "next page"
    ...
    page: call 0x40b7fa(page + 1); call 0x40a3e1     (clamped at the last page, so nothing is seen) and 0x40a3e1 waits for the button to come up

The button state is read twice, once as the argument of the table's pass and once after it. The window procedure that sets `[0x7039c4]` on `WM_LBUTTONDOWN` runs on another guest thread, and the scheduler
(`sched.c`) hands the baton over only where a thread's budget of loop back-edges runs out (every 200,000 of them) or where it blocks. The back-edges of a pass of the loop are mostly inside the table's pass (the loops over its
records, the handlers' drawing), so about half the time the baton was passed there: the press arrived after the argument was pushed with 0 and before the second read. The table's pass saw no click, the loop's own read
saw the button, took it for "next page", and `0x40a3e1` then spun until the release (the press had been held 250 ms by the front end, which waits that long for a screen's pass to see it). The click was spent on a page
turn that does nothing. (The first pass logged nothing in `PORT_UI_LOG` because no pass had seen the button down.)

The same race is in the original, between a user's click and the loop's two reads, but with real threads the window is a few instructions wide and a click that does not take is one a person repeats; here the preemption
point sat inside the pass.

## The fix (`pace.c`, `sched.c`)

The pre-call hook of 0x41f3ea (which already decides whether a pass sees a press) now offers the baton first, when the thread's budget is low (`sched_yield_if_low(PASS_BUDGET)`, 20,000 back-edges; a pass is some hundreds):
the window's thread dispatches what has come in, the pass then starts with a full budget and cannot be preempted in the middle, and the argument (pushed before the hook ran) is made right if a press was dispatched
meanwhile (`WR32(arg, [0x7039c4])`). Either the pass sees the press, and the click function's result ends the loop before its second read, or the press comes after the pass and the next pass sees it. The hook keeps the
button state in a local (`btn`): the hook's argument array is a copy, so a write to the guest's argument is not visible in it (a first version that read `a[2]` after writing it made one click advance two screens).

## Tested

- `test_module` (+3): `sched_yield_if_low` offers the baton only when fewer back-edges are left than asked for, and leaves a full budget.
- `tools/soak/screen_nav_play.py`, step `stats` (`journal_rounds`): the Journal is opened and left with the D-pad and A eight times; every Done must come back to Wiz Stats. Before the change it failed in the first round,
  after it passes (640x480). Also by hand, 20 rounds of `click` on Journal and Done 2 s apart: the Done's pass saw the press every time (before the change: 3 of 8, and 1 of 10 in another run).
- The rest of `screen_nav_play.py` (title, new game, village buying food once, shops, clues, deck builder) as before; the click-one-pass checks of `click-one-pass.md` hold (one purchase per click).

## Not checked

- The original: the race is read from its code, not seen in the Windows 98 VM. Whether a click there is lost as often as it was here (it should be much less: real threads, a pass that is a small part of the loop) was not measured.
- 800x600 and 1024x768 (not size dependent by the reading above; the e2e step was run at 640x480).
- The other loops that read the button themselves after the pass (none was found besides this one; a search of the calls of 0x41f3ea would say).

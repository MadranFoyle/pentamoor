# Load-then-walk, in-duel Save, SIGTERM (investigation notes)

Short investigation, macOS arm64 build, dummy SDL drivers, 640x480. Nothing in `src/port` was changed.

## 1. Avatar walks towards the mouse after Load Saved Game: not reproduced

The game keeps the mouse in globals `0x7039cc` (x) / `0x7039c8` (y) and the button in `0x7039c4`. Its main-window procedure
(lifted at 0x5013d2..) sets `0x7039c4` to 1 on WM_LBUTTONDOWN, 2 on WM_RBUTTONDOWN and 0 on the two WM_xBUTTONUPs; x/y are set by
WM_MOUSEMOVE and both button-downs. The overworld reads `0x7039c4` once a frame (0x40b6f9, 0x40b742, 0x40b770).

Experiment (`PORT_CONTROL`, `peek 0x7039c4 3`): title screen, click "Load Saved Game", press on slot 2 ("b", an overworld save) at
(200,128), release after 0.02 / 0.3 / 2.5 s, then poll for 5 s and compare screenshots.

* `0x7039c4` is 0 from the moment the map is up in every case; `0x7039cc/c8` hold the slot click (200,128), i.e. a stale position
  inside the map viewport, never a stale button.
* The map did not scroll and the avatar did not move in any of the three runs (screenshots identical).
* Slot 1 ("test") loads straight into the Sorcerer ante screen, not the map.

So the port does not leave a pending button: the DOWN on the list reaches the game, the UP follows (hold logic in `front.c` is
fine, `wm_keys[1]` also returns to 0). What can still make the avatar walk is the stale *position* plus a real button state
that a human mouse produces (e.g. the user presses on the map again), or something that only the real macOS pointer does
(SDL motion events without a button). That was not reproducible headlessly. If it is seen again, `peek 0x7039c4 3` right after
Load tells which of the two it is.

## 2. In-duel Save: there is none in the Shandalar duel

Right-click menu of a duel from the saved game's Sorcerer ante (640x480): Done, Go to: Cleanup phase, Arrange opponent's cards,
Duel Options..., Show ID tags, Show invisible effects, Show all cards' summoning sickness, About..., Help..., Concede. No Save, and
the Duel Options dialog (Layout, cue cards, territory background) has none either. MAGIC.EXE does contain "Save game..." /
"MTG Gauntlet Save Game" / `*.SVG`, which belong to the stand-alone Gauntlet duel, not to a Shandalar encounter. After the
duel start `SaveGame/AUTOSAVE.SVG` kept its old time stamp, so nothing is written there either in this flow. Nothing to
round-trip in Shandalar mode; a Gauntlet-mode check is open.

## 3. SIGTERM takes a few seconds

`front.c` has no signal handler; SDL turns SIGTERM into SDL_QUIT, which posts WM_CLOSE to the main window once, and the process
only ends because of the fallback in `front_serve`: `quits == 1 && port_now() - first_quit > 5.0` calls `exit(0)`. Measured here:
5.06 s from the title screen and 5.04 s on the map, exit status 0. So the game's own window procedure does not end the program on
WM_CLOSE (the default handling destroys the window but the game's loop does not quit). A second SIGTERM/close ends it at once.
Options: end at once on the first SDL_QUIT that came from a signal, or shorten the 5 s grace.

## 4. Linux soak (3 minutes, 3 sizes at once, x86-64 box)

`tools/soak/run_all.sh 3`: 640x480 1 game / 1 duel / 4 turns, 800x600 1 game / 2 duels / 4 turns, 1024x768 1 game / 1 duel / 5 turns.
No CRASH, HANG, STUCK or SETUP events; only NOTEs ("duel ended: over/restart"). Too short to say more than "no crash in 3 minutes".
(`run_all.sh` calls `python3`; the box's system python has no PIL, so it was pointed at the venv for this run, not committed.)
The SIGTERM delay (section 3) is the same 5 s fallback there.

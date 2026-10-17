# The standalone duel program: setup dialog, Gauntlet, Save game

Looked at `DUEL.EXE` (`make -C src/port GEN=../../sources/generated/lift_duel BUILD=build_duel`, run with `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`, 640x480,
`PORT_CONTROL` fifo, own `PORT_OVERLAY`) past the one path that had been seen (Single Duel, default choices). macOS arm64.

## What was wrong, and is fixed (all in `src/port`, tests in `test_wm.c`: `test_auto_controls`)

1. **Automatic radio buttons and check boxes did not check themselves.** Every radio button of the setup and options dialogs is `BS_AUTORADIOBUTTON`
   (style 9, `WS_GROUP` on the first of a group); the game only calls `CheckRadioButton` for the side effects it wants (Gauntlet: opponent "Random deck"), and leaves the
   clicked button's own tick to the system. The port only posted `BN_CLICKED`, so "Gauntlet" never showed as chosen, nor "Best of Three", the Enemy Level, the Duel Options
   layout/background radios, or the check boxes. `wm_button_auto_check` (controls.c) does what Windows does before it tells the parent: a click on an automatic radio
   button checks it and unchecks the others of its `WS_GROUP` group, an automatic check box flips.
2. **`EnableWindow` was a stub.** Choosing Gauntlet disables the opponent's "Pick a deck" and its combo box (the game calls `EnableWindow(.., 0)`); nothing was disabled, so
   a gauntlet could be started with the dead controls looking alive. `EnableWindow` now sets the state (result: previous "was disabled"), sends `WM_ENABLE`, the drawing
   greys the control, and a disabled button or combo box takes no click.
3. **Combo boxes could not be used with the mouse or keyboard at all.** No drop-down: "picking different decks in the combo boxes" was impossible. A drop-down combo box
   is now just its closed box (21 px; the height in the template is its list's height, `drop_h`; before, its window covered the controls under the list and the hit test
   went to the group box), a click drops the list (drawn over everything, flipped above the box when the screen has no room below, scroll bar, `CBN_DROPDOWN`), the list takes
   the mouse and keys while down: pointer highlights, click chooses (`CBN_SELCHANGE`, `CBN_SELENDOK`, `CBN_CLOSEUP`), click elsewhere / right click / Esc cancels (back to the old
   choice), Up/Down/PageUp/PageDown/Home/End/letters move the choice, Enter accepts, the wheel scrolls (`SDL_MOUSEWHEEL` -> `IN_WHEEL`), the scroll bar's arrows and thumb work.
4. **List boxes took no mouse** (and drew from row 0 always). A built-in list box now chooses the row under a press (`LBN_SELCHANGE`, a second press within 0.5 s is `LBN_DBLCLK`) and
   draws from its first visible row (`top`).
5. **`GetSaveFileNameA` was a stub, `GetOpenFileNameA` was missing**, so "Save game..." and the setup dialog's "Load saved game..." did nothing. Main has since got the
   full file dialog (`filedlg.c`), which is what both now use; this branch's smaller one was dropped. The file dialog does its own clicks on its list and drop-downs
   (`Window.own_mouse`, set by its procedure), so the standard list box / combo box mouse handling (3, 4) leaves the controls of that dialog alone.
6. **A dialog owned by another dialog or window was drawn twice** (a ghost copy of the Gauntlet Options / Duel Options OK and Cancel buttons, offset by the owner's
   origin, at the bottom of the screen): owned dialogs are on the dialog stack and are drawn from it; they are no longer also painted as children (`compose.c` `paint`,
   `ui.c` `ui_dialog`).
7. **Create Deck... opened the deck builder under the setup dialog.** Dialogs are drawn over everything; the "Deck Maker" top-level window is made after the dialog and was
   hidden behind it. Top-level windows made after the first open dialog are now drawn in creation order with the dialogs (`compose.c`), so the builder is on top and
   works (Exit returns to the setup dialog).
8. `PORT_CONTROL windows` also prints `id=`, ` checked`, ` disabled`.

## Recipe (what a person does, through the control pipe; coordinates at 640x480)

Setup dialog: Gauntlet radio (85,87), Single Duel (85,106), Gauntlet Options (492,78), Duel Options (492,116), Create Deck (156,347), OK (173,409), Load saved game (325,409), Exit (471,409).
Gauntlet Options: Best of Three (255,221), Best of One (255,240), Ante (185,276), Apprentice/Magician/Sorcerer/Wizard (368,221/240/259/277), OK (248,340), Cancel (388,340).
Combo boxes: opponent's (350,204), yours (350,311); click, then a row, or Up/Down + Enter.

1. start; click Gauntlet (opponent deck becomes Random, "Pick a deck" greys out); OK.
2. The coin toss is a movie dialog; if you win it a dialog offers "Play first" / "Draw first" (else it goes straight on). Then the ante screen ("Start the duel" at (497,371)).
3. In the duel: right click opens the menu (Done, Go to, Arrange, Duel Options, ID tags, ..., Minimize, **Save game... Ctrl+S**, About, Help, Concede > "Yes, I'm sure").
4. Concede: result screen "Too bad / You lost the game / That was round 1 / Your record is 0/1/0" with "OK" (Best of One: back to the setup dialog) or, Best of Three, "The match
   continues..." with **Next Round** (237,413) and **Quit Gauntlet** (237,453). Next Round runs the coin toss and ante screen again with the same opponent.
5. Save game...: type a name, Enter; `SaveGame/<NAME>.SVG` (89,224 bytes) appears in the overlay. The game also writes `SaveGame/AUTOSAVE.SVG` at the start of each duel.
6. Quit (SIGTERM, about 5 s as in `load-mouse-duel-save-sigterm.md`), restart **with the same overlay**, Load saved game..., click the name, Open.

## Results

* Round trip: with the setup dialog on Gauntlet and Best of Three, a game saved in game 2 of a match (record 0/1/0) loaded into the same duel (the same hand of seven, the same opponent), and
  after a concede the result screen said "round 1, record 0/2/0": round, decks, record and the duel itself come back. With the dialog left on **Single Duel** the same file loaded into the same duel
  but the result screen began a new record (0/1/0 after one concede, no "match continues"): the match type is taken from the setup dialog, not the file. Not checked against the original.
* Best of One, conceded: result screen with OK, back to the setup dialog. Best of Three: Next Round, Quit Gauntlet both present; Next Round starts game 2 (coin toss, ante screen, duel).
  Quit Gauntlet goes back to the setup dialog.
* Duel Options: layout Standard/Advanced, "Show cue cards", "abilities on small cards", "power/toughness", territory background radios all work with the clicks now; OK then a duel with the Advanced
  layout started and ran without a crash (the layout itself was not looked at).
* Create Deck opens the same deck builder as `DECK.EXE` ("Deck Maker", "New Deck"); Exit comes back to the setup dialog.
* "Help..." in the duel menu: nothing happens (no window, no crash; WinHelp is not implemented). "About..." not tried. *Correction (documentation audit, 2026-10): `Help...` now shows a box saying the help file cannot be shown, and `About...` was run: [help-about.md](help-about.md).*
* The result screen's window is 492 px high (screen 480): the bottom is clipped, the buttons are still in view.
* Not done: a Gauntlet won (so "round 2" as the next *match*), Wizard/Apprentice levels, a deck picked with Create Deck and used in a duel, the file dialog's list scrolling with more
  than ~9 files (the list has no scroll bar of its own; Up/Down and the wheel are not wired into it), a unit test of `file_dialog` (it needs a guest thread; checked by hand as above).

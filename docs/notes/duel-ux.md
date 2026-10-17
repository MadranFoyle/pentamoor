# Duel prompts and a soak test

Notes from looking at "the opponent just stopped playing" (a duel at 1024x768 whose engine thread sat in the game's choose-target code with
nothing on screen to say so), and from a soak test written afterwards (`tools/soak/`).

## What the original does with a prompt

The prompt bar is the window class `MAGIC_TellUserClass` (0x4770xx: its window procedure is `UI_Register_WINBK_TellUser_004771fa`, registered by
`Prompts_Load_00476e60`). Names in the decompiled tree are unreliable, so the path as the code shows it:

- The engine thread wants a choice. `Duel_ChooseTarget` (0x405802) builds a prompt text (`Action_PromptTarget_00405370` makes
  "CASTING: ... Pick target creature", "ACTIVATING: ..." and "PROCESSING: ..." out of the stack's top; callers with a fixed text pass one read from
  PROMPTS.TXT) and calls `Ai_Subsystem_004af765`, which sends `0x403` to the duel window (`MAGICGAME_MainClass`) and waits.
  `0x46fa40` is not an ability: it is the discard step ("Select card to discard.", PROMPTS.TXT `@DISCARD`), called when a hand is over seven
  cards at the end of the turn or a spell makes a player discard.
- The duel window's `0x403` handler (in `Pic_Clip_00443b63`'s window procedure, around magic_all.c:29971) shows the text on the bar through
  `FUN_00477d73` and runs its **own message loop** on the duel thread until a `0x464` message arrives carrying the answer (16 bytes). That loop
  is where all input of a prompt goes: mouse clicks are dispatched as usual (a click on a card is the choice), and keys are looked at by
  `Palette_Subsystem_00495cde` (0x495cde):
  - only `WM_CHAR` (0x102) of Space, Enter, Esc, only while the bar is visible and has a button;
  - bar with both buttons: Enter = Done (button 2), Esc = Cancel (button 1), Space does nothing;
  - bar with one button: Enter and Space = that button, Esc = Cancel if Cancel is the one shown.
  The key is turned into `SendMessage(bar, 0x401, id)`, which is also what a click on a button sends (as `WM_COMMAND` 1 or 2).
- The bar has two owner-drawn buttons, id 1 = **Cancel** and id 2 = **Done** (their labels are the two lines of PROMPTS.TXT `@BUTTONLABELS`).
  Which are shown is decided by the caller (`arg_19` of `Duel_ChooseTarget`: bit 0 Cancel, bit 1 Done). A targeted spell or ability has Cancel;
  the phase prompts have Done; forced choices (discard, the mana-source picks) have **no button at all** and cannot be cancelled: the only
  ways out of them are making the choice or Concede in the right-click menu (a right click is dispatched during a prompt too).
- Cancel returns `(-2, -1, -1)` to the engine thread, Done `(-2, -1, -2)`; `Duel_ChooseTarget` turns either into "no target" (return 0) and the
  caller backs the spell out.

## What was wrong in the port

1. **PROMPTS.TXT came back one line late** (`src/port/stdio.c`, `fscanf`). The game reads a section with `fscanf("%d")` for the line count and then
   `fgets` for the rest of that line (0x424500); the port's `fscanf` moved the file to the *next line* after every call. So every prompt read through
   that function lost its first line and returned the blank line after it: the bar's two labels were "Done" and "" (the Done button was drawn
   empty; Cancel read "Done"), and a one-line prompt such as `@DISCARD` ("Select card to discard.") was an empty string. The bar hides itself
   when its text is empty (`FUN_00477d73`), so the player saw nothing, with the engine thread waiting in `Duel_ChooseTarget` for a click on a card: this is
   the user's "the opponent just stopped playing" (it is the player's own end-of-turn discard, or a discard spell of the opponent's). `fscanf` now
   moves the file position by what it converted, like the C runtime's.
2. **Esc, Enter and Space never reached the prompt's message loop** (`src/port/input.c`). Keys were posted to the first top-level window
   (`ShandalarMainClass`, the first thread's); the loop that reads them is the duel thread's, and the queues are per thread. A prompt could be
   cancelled with the mouse only. Keys now go to the window with the keyboard focus (`wm_key_target`; the duel window takes the focus when it is
   shown), falling back to the first top-level window as before.
3. `PORT_CONTROL windows` now lists an open popup menu (rows with their pixel boxes), so a script can click "Concede" without knowing where the
   screen edge pushed the menu.

Checked after the fixes, with the bar read from the window tree and screenshots, at 640x480, 800x600 and 1024x768: the bar sits between the two
territories at the same relative place at all three sizes (x 188, y 230 at 640; 235, 287 at 800; 300, 367 at 1024), is drawn with its text and
labels, its buttons hit-test where they are drawn (a click at the centre of the rectangle `windows` gives presses it), Enter presses Done, Esc and the
bar's Cancel button cancel a "CASTING" prompt, and the discard prompt cannot be cancelled by Esc or a right click (the right click opens the
menu, Esc closes it, the prompt stays) but is answered by clicking a card name in the hand list.

## The soak test

`tools/soak/soak.py` (library `pentamoor_ctl.py`, launcher `run_all.sh`): see the header of `soak.py`. It needs the installed game and the
saved game's Sorcerer encounter (as the recipe in `docs/PHASE_C.md`) and plays at 640x480, 800x600 or 1024x768 with random choices.

### Run (20 minutes at each size, the three at once, a MacBook with other things running)

| size | games | duels | turns | actions (dialog / main / prompt / done / attack / popup) | crashes | hangs | stuck | stderr |
|---|---|---|---|---|---|---|---|---|
| 640x480 | 5 | 5 | 17 | 216 / 133 / 149 / 66 / 32 / 6 | 0 | 0 | 0 | 0 |
| 800x600 | 4 | 8 | 40 | 239 / 133 / 44 / 102 / 36 / 3 | 0 | 0 | 0 | 0 |
| 1024x768 | 4 | 6 | 20 | 247 / 151 / 113 / 73 / 52 / 10 | 0 | 0 | 0 | 0 |

(19 duels. A "turn" is a pass through the discard phase, both players', so it is a rough count.) Nothing died, nothing hung, no state sat still for
60 s, and the program printed nothing on stderr in any of the 13 game processes. The prompts it met included "CASTING: ... tap" (a spell waiting for
mana), which it paid by clicking permanents, or cancelled by the bar's Cancel button, by Esc, or by Esc after a right click (the menu), at random;
no cancel failed to clear its prompt (the script logs a NOTE when one does not).

What the soak does not cover, and what it taught:
- **Duels were conceded or lost, never won**, and it does not choose targets with any sense, so the paths of a win (the reward screens, the
  Gauntlet's next round) are still unseen. Attacks are "click every permanent of mine, then Done": the attack window opened and closed, but
  whether creatures really attacked was not checked. *Correction (documentation audit, 2026-10): a duel was won later, by setting the opponent's life, and the screens after it were recorded: [duel-won.md](duel-won.md).*
- **After a duel the saved game moves on**: the first duel is the Sorcerer's, a second one follows on the ante screen, a third time the game is
  in a village. So a game process plays at most two duels from one save; the script restarts it (the saved game is in a fresh copy of the overlay each time).
- The coin toss is not always a movie: when the player wins it, it is a dialog with "Play first" / "Draw first" (800x600 and 1024x768 showed it).
  The script reads dialogs from the window tree, so it does not care.
- "Sorcerer casts..." (the dialog that shows an AI spell) needs about a dozen Return presses before it goes (there is no button; it ends by a timer or the
  key, a few seconds), and its picture shows a black panel at 640x480. Not looked into. *Correction (documentation audit, 2026-10): fixed, the panel was a child window that draws nothing of its own: [sorcerer-casts-dialog.md](sorcerer-casts-dialog.md).*
- Window titles can contain newlines ("Your next draw:\n..." in the result dialog), which spread over several lines of `windows`; the script's parser
  skips them (the first test run reported them as stray stderr).
- Under load three games and a build were all slow (the first duel took 5 minutes to start at 640x480 while the others were starting); the stall limit of
  60 s was not reached.

Run it: `tools/soak/run_all.sh 20 /tmp/soak` (the three sizes at once), or `python3 tools/soak/soak.py --res 800x600 --minutes 20 --verbose`.


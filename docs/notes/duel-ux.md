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

## Long runs, 2026-10-17 (macOS arm64 and Linux x86_64), the standalone programs, memory

Run after the dungeon-5 crash was explained ([castle-dungeon-stats.md](castle-dungeon-stats.md)), with the runtime of that day. Every process was started by the scripts (SDL dummy drivers, own control pipe, own overlay copy); nothing ran on a real display.

| where | what | time | games | duels | turns | crashes | hangs | stuck | stderr |
|---|---|---|---|---|---|---|---|---|---|
| Mac | 640x480, 800x600 and 1024x768 at once, duels conceded after 3 to 9 turns | 3 x 35 min | 22 | 40 | 173 | 0 | 0 | 0 | 0 |
| Linux | 640x480 and 1024x768 at once, the same | 2 x 35 min | 16 | 29 | 128 | 0 | 0 | 0 | 0 |
| Mac | 1024x768, duels of 12 to 40 turns (conceded after 420 s at the latest) | 20 + 2 x 45 min | 21 | 43 | 208 | 0 | 0 | 0 | 0 |
| Linux | 1024x768, the same, 6 to 14 processes at once | about 1,700 min | 315 | 573 | 2,578 | 0 | 0 | 13 | 2 message boxes (one cause) |
| Mac | `monkey.py`: random clicks and keys on the places of the map (villages, towers, castles, dungeons, teleported to): 57 places at each of 640x480 and 1024x768, and 107 in one process | 12 + 12 + 20 min | 5 | 221 places | | 0 | 0 | 0 | 0 |
| Linux | `monkey.py`: 107 places in one process at 1024x768; `DECK.EXE` and `DUEL.EXE` at two sizes (27 runs of up to 90 s) | 20 + 24 min | 28 | 107 places, 27 runs | | 0 | 0 | 0 | 0 |
| Mac | `DUEL.EXE` played by the soak (concede, OK in the setup dialog, the next duel, all in one process) | 8 + 20 min | 2 | 2 (and the rounds in them) | 36 | 0 | 0 | 0 | 0 |

No process died or stopped answering, and no line of "is not implemented" or of a stub call was printed. (The stderr column counts what the soak does not know: the monkey's first run on the Mac printed `GetProcAddress(0x400000, szDeckName) -> not found` when the random clicks opened the deck builder, which asks `MAGIC.EXE` for an export that 1.0's does not have, ManaLink's does, and Windows answers NULL too; the soak lists it now, and, for `DECK.EXE`, which has no exports at all, the deck builder's other nine lookups and its message boxes.) Two kinds of event are not nothing, both on Linux, both in long duels that the player never wins:

- **13 times the duel sat on `Fast Effects?...Draw Phase`** with Done doing nothing: [draw-phase-stuck.md](draw-phase-stuck.md) (the loop is in the program's own prompt code; the note says where, what feeds it, and what is not known).
- **Twice a message box from the game, `Assertion Error: File-> G:\NewMagic\sources\sid\Minit.c, Line-> 1598 / AddCard error / Please call MPS Customer Support`** (answered OK by the port, as Windows would have to), once per click for the rest of the duel. `AddCard` (0x451291) looks for a free entry in the player's table of 80 cards (first field -1) and asserts when there is none. Both duels had gone on for 12 and 14 minutes before it (the soak's concede did not take, and did not end either duel until the run's time was up), with the Asp hitting the player again and again; the used-up Asp Legacy cards that were looked at in the stuck processes keep their entry (first field 418, second field -1), so the table probably fills with them. The table was not looked at in the two processes that asserted. It is the program's own limit; a concede that failed (a prompt or a menu in the way) used to be tried once and is now tried every 20 s, so the soak ends such a duel.

The scripts that are not soaks (1024x768 unless said): `pad_play.py`, `screen_nav_play.py` (also 640x480), `nav_play.py` (seeds 3, 4, 5, 6 and 7 on the Mac, 3, 5 and 6 on Linux; also 800x600 and 640x480; and `--game duel`, which was in the usage line but not in the code and is now) and `pad_realtime.py` (seeds 3 and 6 on the Mac, 3 on Linux) all passed on both machines, apart from two checks of `nav_play.py` seed 6 on the Mac (the big card's picture after a D-pad move: a hover that came late on a loaded machine; the rerun passed) and one of `screen_nav_play.py` at 640x480 on Linux (the map's menu had two targets instead of eight on a machine running 14 games; the rerun passed). Seeds 5 and 6 of `nav_play.py` had stalled in their own set-up: the hand overflowed and the script answered "Select card to discard" by clicking permanents ("Illegal target"); it clicks a card of the hand now. `./pentamoor deck` and `./pentamoor duel` start and keep running until stopped.

**Resident memory** (`ps -o rss=` of the exact process, every minute, in `rss.csv`): a game process starts at 100 to 130 MiB and takes 30 to 70 MiB more in its first five minutes (the pictures). It then stays where it is on the map and in `DUEL.EXE`, and grows slowly in a long duel. One process for 107 places of the map, 20 min: Mac 104 MiB, 170 at 268 s, 166 at the end; Linux 120, 193 at 270 s, 194 at the end (+0.04 MiB/min). `DUEL.EXE`, 20 min of duels in one process: 71 MiB, 99 after four minutes, +0.25 MiB/min after that. `MAGIC.EXE` in one duel of 26 minutes (Linux): 121 MiB, 155 after four minutes, 175 after 26, a steady +1 MiB/min. Over the 30 Linux processes of 8 minutes and more the growth after the first five minutes had a median of 2.6 MiB/min (largest 8.6); the largest process seen was 189 MiB (the map). Whether the growth in a duel is the guest's own heap (the game allocates per turn) or the runtime's was not looked at; a duel of a normal length is nowhere near a limit.

How: `tools/soak/soak.py` (also `--program .../DUEL.EXE`), `tools/soak/monkey.py` (also `--program .../DECK.EXE`; [CONTRIBUTING.md](../../CONTRIBUTING.md)), and for the long duels `--min-turns 12 --max-turns 40 --max-duel-s 420 --stall-s 45 --duels-per-game 3`.

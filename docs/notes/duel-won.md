# A duel won in the native port, and the screens after it

First duel won in the port (800x600 and 1024x768). It was won by a poke of the opponent's life, not by combat; the screens after the win were
recorded. One bug found and fixed (the win hung on a black screen).

## The real life totals

`docs/notes/duel-win-attempt.md` poked 0x6ff194 and nothing changed on screen. The reason is in `Ai_Subsystem_004b42dc` (magic_all.c ~77370), the
function that copies the engine's state into the "last drawn" copies to see whether the board must be redrawn:

    if (g_PlayerCreatureCount != DAT_006a3f7c || DAT_006a4a04 != DAT_006ff194) changed = 1;
    DAT_006a3f7c = g_PlayerCreatureCount;   DAT_006ff194 = DAT_006a4a04;

So 0x6a3f7c and 0x6ff194 are the drawn copies, rewritten from the real values on every redraw; the real ones are

| address | what | name in the decompilation (wrong) |
|---|---|---|
| 0x6a4a00 | **your life** | `g_PlayerCreatureCount` |
| 0x6a4a04 | **the opponent's life** | `DAT_006a4a04` |

Both are 10 at the start of the Sorcerer duel (set to 20 by `y == -1` in the duel start code at 0x34830 for the full game; here 10).
`FUN_005062b1` (magic_all.c ~114448) is the end-of-game test: `g_PlayerCreatureCount < 1 || DAT_006a4a04 < 1`. `Ai_Subsystem_004b6fa6(0|1)` reads the
mirrors (player, opponent). The engine reads the real values at the next state check, so a poke shows on screen after the next action (a land played, Done).

## Recipe (script it with `tools/soak/pentamoor_ctl.py`; coordinates at 800x600, the other sizes in `soak.py`)

1. start MAGIC.EXE (own `PORT_CONTROL`, own overlay copy, `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`), 9 s, click "Resume Game" (412,487), 9 s: the ante screen.
2. click "Duel a Sorcerer" (360,388); within ~25 s the coin toss dialog ("Play first" / "Draw first": a dialog, not the movie, when the player wins the toss;
   the movie otherwise, then click on it), then the "Start the duel" dialog (button read from `windows`).
3. wait for the prompt bar "Main phase (before combat)" with its Done button (`windows`: `MAGIC_TellUserClass`).
4. `poke 0x6a4a04 0`, then click Done (any action that makes the engine look again works). The "You won!" dialog opens (class #32770, two static
   texts "You won!" and "Your next draw:", **no buttons**).
5. click in the dialog (`key escape` works too; Return does not close it any more, as in the original: `dialogs.md`). What follows:
   - a moment of black, then the wizards' statistics picture (the original has it too; it was black here until the third report of duel-won-black-screen.md), a crystal ball clip (STATWIN R_MWZ.avi, 6.7 s, with STATSCRN.WAV) at (304,340) and then the wizard's hit clip (RED-HIT.AVI) at
     (420,108) at 800x600: the same spell-hit animation STATWIN plays for a spell cast at a wizard. About 12 s in all.
   - then the game waits for a click or a key (the clips' windows are the only windows of that thread). `key return` once more (or a click on the hit clip's place).
   - the reward screen on the dungeon backdrop: four cards (Winds of Change, Mountain, Swamp, Stone Giant in this run, with rarity banners), the text
     "You have defeated the slimy Sorcerer. Will you... Take the cards. / Take the dungeon clue." and a plaque with the next clue ("The Paths of Chronus:
     Mox Emerald, Mox Pearl, Mox Ruby (first clue)"). Click "Take the cards." (215,424) or the clue line.
   - the map again (800x600: the party beside the town, gold 80, food 45, deck 46/47 as before; a Sorcerer win pays no gold).

Windows seen in the first state: `MAGIC_TellUserClass` bar, `MAGICGAME_*` duel windows; after the dialog the duel windows are gone and only
`ShandalarMainClass` and two `VIDWINCLASS` windows (STATWIN's clips) remain.

## The bug: the win hung on a black screen

After the two clips STATWIN (0x3000268a, loop at 0x30002b55) calls its poll function 0x3000105a over and over until it returns 1; that function does
`PeekMessage(msg, NULL, 0, 0, PM_REMOVE)` and returns 1 for WM_LBUTTONUP / WM_KEYDOWN (and opens a help dialog for WM_RBUTTONUP). `PeekMessage(NULL)` reads the
calling thread's queue, and the thread (the duel's) owns no window but the two video windows. The port made a see-through clip invisible when the game
called `DrawVidBackground` after it ended, and an invisible window gets no input; the keys went to the first thread's main window. So nothing could ever
reach the thread: black screen, process idle, `windows` answering, no crash. (The opaque death animation of the notes in movies.md stays visible, which is why that
path worked.)

Fix (`src/port`): `DrawVidBackground` now *holds* the clip (`movie_window_set_held`): the window stays visible for hit-testing but `compose.c` does not draw it,
and `PlayAVI` clears the hold. `wm_key_target` (user32.c) sends keys to a held clip's window first. Clicks reach it where it lies (a click elsewhere
goes to the main window and does nothing; the original probably worked the same, the cursor being over a visible video window). `test_movie` 51 -> 54 checks.

## Checked / not checked

- Won at 800x600 (Return, Return, "Take the cards") and 1024x768 (the toss was lost that time, "Sorcerer will start first"; the poke worked from the first
  prompt of the turn, "Fast Effects?...Main Phase"). 640x480 not run.
- Dismissals at 1024x768: in the "You won!" dialog Return worked (800x600; it no longer does, as in the original: `dialogs.md`) and a click inside the dialog works, **Space did not** (the dialog stayed); in the
  held-clip wait Esc worked (1024x768) and Return worked (800x600). The reward screen drew three cards this time (Lightning Bolt, Inferno, Will-O'-The-Wisp)
  and its card text boxes run over the art, the known 1024x768 text-box issue of `overworld.md`.
- "Take the dungeon clue." (1024x768, click (280,552)) opens a cave screen: "Soulchant Monastery, Creatures: Contains large Green creatures", the three
  quest cards (Sol Ring, Timetwister, Time Walk) and a "Done" button (click (100,692)); Done goes back to the map. Gold/food/deck unchanged (80, 45, 46/47).
- The only stderr line of the whole run is the known `stub user32.dll!IntersectRect (called from 0x30007ceb)` (STATWIN), not implemented, harmless here.
- After the reward screen the map comes back and the process keeps running; no crash, no stderr output, no hang.
- NOT verified: that "Take the cards" really adds the four cards to the collection (the status bar shows the deck 46/47 before and after, as it should for cards
  that go to the collection; the deck builder was not opened); what "Take the dungeon clue" does; the ante card (Ali Baba on the ante screen) was not among
  the four cards shown. Gold is unchanged by this win.
- NOT done: a win by combat. The hand of this run was Mountain x2, Brothers of Fire, Pradesh Gypsies, Giant Strength, Uthden Troll, Goblin Rock Sled; the
  opponent's life at 3 and a Goblin Rock Sled (3/1) on turn 2 would be the line (play Mountain, Mountain, cast the Sled by clicking its row and paying with the
  lands), but it was not played out: the poke is the reliable path, and shows the same result screens.

## Rechecked at 640x480 after the file dialogs, click-one-pass, gauntlet dialogs and IntersectRect merges (#110 to #114)

Main game (`MAGIC.EXE`, `PORT_RES` unset, saved game from `sources/emu_overlay`, build of `main` at 8e72475): Resume Game (330,390), "Duel a Sorcerer" (290,325), the coin toss movie
(a click on it), "Start the duel" (496,371), the prompt bar "Main phase (before combat)"; `poke 0x6a4a04 0`, Done (214,241). Then: "You won!" dialog (155,0)-(485,492) -> `key return`
-> the two clips (STATWIN crystal ball at (224,280), the hit clip at (340,48), a held clip waiting) -> `key return` -> the reward screen (four cards, "Take the cards. / Take the
dungeon clue.", the clue plaque) -> a click at (190,321) (the text "slimy Sorcerer.", I had meant "Take the cards." at y~352; not investigated whether a click beside the two choices counts as the clue) -> "The Paths of Chronus" clue screen -> Done (60,433) -> the **ante screen of the next duel** (the saved game's next encounter,
as in the soak). No hang, no crash, process alive; the log has nothing but the three start-up lines: **no "is not implemented" line**, the `IntersectRect` stub message that the first run
above still had is gone.

`./pentamoor duel` (`DUEL.EXE`, own build in `src/port/build_duel`): OK on the setup dialog (173,409), coin toss movie click, "Start the duel" (497,371), the opponent's life
dropped to 0 by `poke 0x681eac 0` and a click on Done: the dialog "Congratulations! You've won the duel! That was round 1 Your record is 1/0/0" with an OK button (237,453)
-> the setup dialog again (control returned). Nothing on stderr. In DUEL.EXE the opponent's real life is at **0x681eac** (the player's at 0x681ea8), not at the MAGIC.EXE
addresses; `0x68ee70` is another pair of 20s that does nothing when poked. Found by scanning for two consecutive dwords of 20 with `peek`.

Not checked: a win by combat, the Gauntlet's win path, 800x600 and 1024x768 again (they were fine before; the merges since touched generic code, so they are worth a rerun).

# The D-pad on the screens the game draws itself

`controller-nav.md` is the D-pad in a duel, a dialog or a menu, where the targets are windows. Most of what is left is drawn by `MAGIC.EXE` itself into one window and the game decides what a click hit with
its own code: the title menus, the new game, the village, the shops, the clues, the wizard's stats, the encounter boxes. This note is what those screens are, how the program finds what is clickable on them
(and the other ways that were weighed), what is supported, and what is not.

Code: `src/port/screens.c` (reads the game; `screens.h`), `navwm.c` (the mode `screen` and `deck`), `nav.c` (`nav_nearest`). Tests: `test_wm.c` (`test_screens`, `test_navwm_deck`), `test_nav.c`;
end to end `tools/soak/screen_nav_play.py`. All addresses are those of `MAGIC.EXE` 1.0, as in `pace.c` and `textfocus.c`; names are mine and say what the code does.

## How the clickable things are found

### What was weighed

| | way | verdict |
|---|---|---|
| a | the game keeps a table of its hotspots in memory, per screen | **there is one, shared by every screen with buttons** (below): exact, no layout copied |
| b | hook the game's own tests and record what they compare | the tests are inline in each loop (no shared "point in rect" routine except the table's handlers and `0x48edeb`), so the same information is read where the loops keep it (locals and globals); not an instrumented build |
| c | move the pointer over a grid and look for a hover reaction in the picture | slow and only finds what highlights; used here to check the tables (`hover_check` in the end-to-end tool puts the real mouse on every target and asks the game which button it hovers), not to find them |
| d | record the blits of the button sprites | what is painted is not what is clickable (the village's button is 272 x 148 over a picture 100 wide) |

### The button table (the library at 0x41f12b..0x41fe62)

Every screen with buttons uses the same small library, and it keeps its state in guest memory:

- `0x41f354` pushes a **context** when a screen starts (`[0x519c24]` is the current one), `0x41f391` pops it; `0x41f12b` empties one.
- A context has a count (`[0x67f780 + 4 * ctx]`) and up to 50 pointers (`[0x67f7d0 + 200 * ctx + 4 * i]`) to **records of 84 bytes**, which the screens add with `0x41f17e(array, count, ctx)`.
  The arrays are static data of the program (`0x525dd8`, `0x531890`, ...): the records are there from the start, only filled in (scaled) when the screen opens.
- A record: `+0x00..0x0c` x, y, w, h at 640x480; **`+0x10 x, +0x14 y, +0x18 w, +0x1c h` at the screen the game runs at** (scaled by `g_DisplayScreenWidth / 640`, so the table follows `PORT_RES`
  by itself: 294,462,443,64 at 1024x768 is 184,289,277,40 at 640x480); `+0x24` the handler; `+0x28` the click function; `+0x40` the type, **3 = greyed (shown, never hit)**; a record with x = y = -1 is a key
  with no button (the colour screen's last one has the letters it answers to).
- The screen's loop calls `0x41f3ea(mouse x, mouse y, button)` once a pass. It asks every handler "is the mouse on you" (handler called with mode 0), keeps the hover (`[0x519ff4]`, the previous one
  `[0x519ff8]`), and a button state of 1 calls the hovered record's click function (mode 2). **The test, in every handler read** (`0x47a94c`, `0x47afa2`, `0x507b44`, `0x48eadc`, `0x50935e`, ...): `x <= mx <= x + w` and
  `y <= my <= y + h`, both ends in, type 3 refused. The same function reads the arrow keys and Tab on screens that set `[0x538750 + 4 * ctx]`, picks the next record by *index* and calls `SetCursorPos` at its
  middle; that is what the D-pad's arrow keys did until now (the pointer, which is ours, never moved with it, and the order is the order of the array, not of the picture).

So the targets of a table screen are the records of the current context, minus greyed ones and keys with no place, as the boxes `[x, x + w] x [y, y + h]`. `screens.c: collect_table`. 15 loops call it:
the title, difficulty, colour, visage (`0x47a2e6`, `0x47abf1`, `0x47b208`, `0x47b899`), the village (`0x507c86`), the shop (`0x509517`), the world map (`0x4c24b3`), the city info (`0x490d7b`), the clue list and its
page (`0x48f523`, `0x492ddf`), the stats and journal (`0x421b32`), the save and load screen (`0x4207a8`), the amulet trade (`0x49716e`), the castle's page (`0x40b4e8`), and the map (`0x4e73a0`).

### Which screen is on

The tables of screens that have ended stay in memory (the map's under a village's, a village's under the shop's, the map's still there when an encounter box covers it), so memory alone does not say what
is on. The **loops say it**: each passes by `0x41f3ea` (the table) and takes the mouse snapshot `0x44b84b` once a pass, and `screens.c` has two pre-call hooks (like `pace.c`'s) that note, with the call's return
address (the loop it came from), the time. A loop that passed in the last 0.4 s is the screen that is on. Loops that are known (`loops[]`): the map (not a screen for the D-pad, below), the text menu, the shop,
the clue list; any other pass of the table is a plain screen of buttons. The hook also takes the caller's `ebp` from `lift_out` (the registers a lifted call leaves), which is how a loop's **locals** are read.

### The text menu (0x489748)

"Will you...\n Duel a Sorceress.\n Pay 40 gold.\n" (the encounters, a castle's gate, "Will you take this card...", the map's Escape menu, a forced "you must... Duel a Troll Shaman") is one function,
`0x489748(text)`, with its state in globals: left `[0x539dec]`, top `[0x539df0]`, right `[0x676d44]`, the font's line height `[0x527b30]`, the number of lines of text above the choices `[0x676d50]` (4
in an encounter), the number of choices `[0x676d40]` and a mask of shut ones `[0x676d58]`. The loop turns the mouse into a choice with `(my - top - 4) / height - first` when `left <= mx <= right`, hovers
it, and takes it when the button is let go. `collect_textmenu` makes a box of every open choice. Seen at 1024x768: 396, 409, 630, 16, 4, 2 (boxes 396..630 x 477..493 and 493..509, which are the lines on the picture).

### The shop's cards, the clue rows (locals of the loop)

- **Cards for Sale** (`0x509517`): Done is in the table; the four cards are boxes in the loop's own frame, `[ebp - 0xa0 + 16 * i]` = x0, y0, x1, y1 (both ends in), the count at `[ebp - 0xa8]`, and a sold card has id -1
  in `[0x61e060 + 4 * i]`. Read through the `ebp` of the pass.
- **Clue list** (`0x48f523`): the arrows and Done are in the table; the twelve rows are tested by the loop itself in 640x480 units (`x * 640 / width`, `y * 480 / height`): two columns, x in (84, 335) and (347, 600), six
  rows from y 73, 62 tall, the edges on the left and the top out, row `(y - 73) / 62 * 2 (+ 1)`, valid below the count `[ebp - 0x12d8]`. These constants are the game's (like the phase column's in `navwm.c`) and are in
  `screens_clue_targets`; a test compares them with the game's test for every pixel of the screen at 640x480, 800x600 and 1024x768.

### Questions with a Y/N

"Buy for 20 gold? (Y/N)" is not a window or a text menu: the game waits in `0x48ac2f` for the key. `yesno.c` (another change) makes A the key y and B the key n while it waits, so the shop works with
the D-pad: D-pad to a card, A (the question), A (yes).

## The screens

Seen = reached in the running game at 1024x768 with the D-pad (`screen_nav_play.py`: 640x480 and 800x600 too). "Table": the button table above.

| Screen | Function | Clickable parts | D-pad |
|---|---|---|---|
| Title menu | 0x47a2e6 | table: Start New Game, Load Saved Game, Resume Game, Exit | **yes** (seen) |
| Difficulty | 0x47abf1 | table: 4 rows | **yes** (seen) |
| Colour | 0x47b208 | table: 5 rows (+ a key record) | **yes** (seen) |
| Visage | 0x47b899 | table: 14 faces | **yes** (seen) |
| Name entry | 0x47be64 | none: the game reads keys (text box) | X is Enter; no targets (`textfocus.c`) |
| Encounter, castle gate, "Will you..." boxes | 0x489748 | text menu lines | **yes** (seen: a castle's gate, the encounter) |
| Overworld | 0x4e73a0 | table: the four buttons of the left column (deck, world map, clues, wizard) and the five amulets | **no, deliberately**: the D-pad is the arrow keys that walk. **B** (the right click) opens the game's own menu of the map (a text menu: Save, Quit, See/Edit Deck F1, See Map F2, City List F3, Dungeon Clues F4, Stats F5, Wiz Stats F6), which the D-pad walks: that is how the map's buttons are reached (seen) |
| Village | 0x507c86 | table: Buy Cards, Edit deck/Sell cards, Begin a Quest, Buy 10 food, Leave (272 x 148 boxes), and the map's left column | **yes** (seen) |
| Cards for Sale | 0x509517 | table: Done; the four cards (locals). Before the cards the "card seller suggests ..." hint waits for a click (no targets: A is the click) | **yes** (seen; buying: A on a card, A) |
| Edit deck / See deck | DECKDLL.DLL | **windows**: a window for every card (strips), push buttons; the filter bar and the picture row are one window each | **cards and buttons** (seen): `deck` mode. Not the filter icons and the pictures row (below) |
| World map | 0x4c24b3 | table: Plain Map, Info Map, City Info, Done; the map itself is a click on a place | **buttons yes** (seen). City Info is the city list below (result 3 of the loop calls `0x490d7b(1)`); the map's own "click on a place" exists only with the cheat flag `[0x67b9a4]` |
| Clues | 0x48f523 | table: Done, two arrows (greyed when there is nothing to scroll); 12 rows | **yes** (seen) |
| A clue's page | 0x492ddf | table: Done | **yes** (seen) |
| Wiz Stats, Journal | 0x421b32 | table: Wiz Stats, Journal, Done, a scroll bar, the castle emblems, the world magics owned (the others greyed) | **yes** (seen) |
| City list (F3, and the world map's City Info) | 0x490d7b | table: Done and four scroll arrows (greyed while there is nothing to scroll to: all four when the list is empty, the two up ones at the top of a longer one). **The rows are not clickable**: the loop has no test for them, only the table's result and the keys PageUp, Up, Down, PageDown, and nine rows to a page | **yes** (seen with 38 places: Done and the two down arrows, A on an arrow scrolls and the up arrows come on; `screen_nav_play.py`, step `worldmap`) |
| Save and load | 0x4207a8 | table: 10 slots, the whole width of the list; the three buttons on top | **yes** (seen: the ten slots) |
| "Which card do you seek?" (the card trade screen, `tradscrn.pic`; the old name "amulet trade" was a guess) | 0x49716e | table: Done (when the caller passes the flag that uses the table: `[ebp + 0x18]`). The two lists of kinds (six rows each) and the list of card names are tested by the loop itself, in 640-unit formulas (below) | **Done only**; reached with `call 0x40eeb4 0 -1` from the control pipe (the card trade's own callers are the village's flows at 0x509fd4, 0x40e220 and 0x40e731, not played): `pad nav` listed Done (272,5)-(370,33) at 640x480 |
| Castles, dungeons: the maze | 0x40b4e8 / 0x4a2ef0 | the party walks by the arrow keys or the pointer's direction | **arrow keys, deliberately**; the rule card panel is Escape |
| Castles, dungeons: events | 0x4a2ef0 and text menus | "Will you take this card", quiz answers: text menus | text menu: yes (not reached) |
| Victory: take three cards | 0x49239e | text menu "Will you take this card...\n Yes\n No" and the cards | menu yes; the cards not |
| Duel, its dialogs and menus | windows | | already (`controller-nav.md`) |
| Standalone `DUEL.EXE` setup, Gauntlet, results; `DECK.EXE` | dialogs and windows | | already (dialog mode), as before |

## What is not done

- **The deck builder's filter bar and picture row.** Each is one window that draws its icons and pictures itself; the icons' places come from a function of the game's (`DECKDLL.DLL` 0x10001294, which depends on
  mode flags in the DLL's data), the pictures from the list's scroll state. There is no table, and calling the game's function from the front end's thread is not safe (it runs between guest instructions).
  The stick points there; the cards and buttons are D-pad targets.
- **The map's own buttons** (left column, amulets): the map's loop is excluded from `screen` mode on purpose, since the D-pad walks. The game's menu on B reaches the same things (deck, map, cities, clues, stats,
  wizard's stats) by the D-pad; the amulets (their spell menus) are for the stick. They are table records and could be given a modifier (say the left trigger held); that is a question of feel, so it is left.
- **The card trade screen's lists** (`0x49716e`): after the table's pass the loop tests a click itself with `W * n / 320` and `W * n / 640` (`0x4c3ba3`, `0x4c3bc4`, W the screen's width): a click outside the box
  (x 246..396, y 102..326 in 640 units, both scaled by W / 640) closes it, one in the upper part picks a kind in the left or the right list (six rows each, `[0x52b730]` and `[0x52b734]`), one lower down picks a name from the list
  (`[0x52b738]`, the row from `(y - [ebp - 8]) / [ebp - 4]` plus the page). The rows' places are locals of the loop that were not read, so only Done is a D-pad target; the lists are for the stick.
  The screen itself was reached only with `call`, not through a game flow.
- **The city list's rows** are not a thing to reach (nothing in the game reacts to a click on them).
- Previously "not reached": the world map's City Info mode is the city list (above): reached and done.
- The maze of a castle or dungeon, and the world map's click on a place (a free pointer).

## Not verified, needs a real controller

- The feel: `nav_nearest` (the first press on a screen takes the nearest target in any direction, since after a click the pointer is wherever the last screen left it), the order in which the D-pad crosses the
  village's five buttons (left from "Edit deck" goes to "Buy Cards", skipping the middle one, since it is in the same row), the repeat on a held direction.
- That nothing here was run with a real controller (the `pad` steps of `PORT_CONTROL`, as in `controller.md`).

## Spells of the Ancients 2.15 (`shandalar.exe`)

The same library and the same way of reading the screens, with 2.15's addresses in the build's profile (`src/port/profile.c`; every group but the card list's is marked verified in `hooks_verified`, which means it was run and seen, not matched by code shape: [sota-comparison.md](sota-comparison.md), "Milestone 4", has the table of each address and what was seen). What is the same: the button table (a context, a count and 50 record pointers per context, the **same 84-byte record** with the screen-size x, y, w, h at +0x10..0x1c, the handler at +0x24 and the type at +0x40 (3: greyed); read from `0x577cec`, `0x7270e0` and `0x727130`), the text menu and its seven globals, the locals of the shop and of the clue list, the title menu told apart by its loop. What is new in 2.15's screens:

- **The card list** (`0x4f041d`, "Pick a card": the function every picker of 2.15 goes through, with its `prompts.txt` key and its player, its ids, a count and a flag that asks "Take this card?  (Y/N)" after a click). Its cards are not in the button table and not windows: the game lays them out in a 320 x 240 space (each 0x30 square, in columns that start at x 0x64 and step 0x38, a card over the one above it), keeps the places in two arrays of dwords in its frame (`ebp - 0xfb0` x, `ebp - 0x1780` y, the count at `ebp - 0x7d8`) and turns the mouse into that space with `x * 320 / width`, `y * 240 / height`. `screens.c` reads them (`SCREEN_CARDLIST`, `screens_cardlist_targets`: what a click reaches of a card is its square less the squares of the cards drawn later; a test compares it with the game's own test for every pixel at 640x480, 800x600 and 1024x768). **Not seen in a game flow, so no row holds the group** (`HK_CARDLIST`): see "What was not seen" in the Milestone 4 section; the function was run from the control pipe (the list drawn, the question asked, A and B answered it), not reached by playing, and the D-pad on its list was not seen.
- **A duel's "Select target card." dialogs** (Demonic Tutor and the like) are a dialog (`#32770`) whose cards are windows of the class `ShowListCard` (title "List Card"): `navwm.c`'s dialog mode lists each as a target (kind OTHER), 24 of them for a 36-card library, and A on one picks it.
- **The title menu with no saved game** has two targets, not four: the greyed `Load Saved Game` and `Resume Game` are records of type 3, so they are not targets until a game has been saved (the same as 1.0's with an empty overlay).
- **The new game's visage screen is FaceMaker**, a second program with its own window and no button table: the D-pad has nothing there (mode `none`); the left stick puts the cursor on the portrait or on Leave and A clicks.
- **The map's right-click menu has nine lines** (Save, Load, Quit, See/Edit Deck, See Map, City List, Dungeon Clues, Stats, Wiz Stats: B opens it, the D-pad walks it, A takes a line, Back closes it), one more than 1.0's.
- **The save and load screen** has ten slots, all table records; on load, only slots that hold a save are targets.

Run end to end by `tools/soak/sota_pad_play.py` (below); `PORT_SCREENS_TRACE=1` prints each loop's return address and kind the first time it passes, which is how the addresses were found.

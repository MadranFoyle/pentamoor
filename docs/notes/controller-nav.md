# The D-pad moves between cards

The vision: in a duel the D-pad is enough. From the card under the cursor, a direction goes to the nearest card that way (up the hand, left to your cards, up again to the opponent's), crosses from
one zone to the next at an edge, and reaches the other things a click can act on (the Done button, the life totals, the piles, the phase icons). The stick stays for free pointing. The same goes
for a dialog's buttons and fields and for a popup menu's rows. The screens the game draws itself (title, new game, village, shops, world map, clues, encounter boxes) have their targets read from the game's
own button table instead (`controller-screens.md`), and the deck builder's cards and buttons are windows like these. On the map and in castles and dungeons the D-pad is still the arrow keys (`controller.md`).

This note is the research (where the game keeps its cards, and how the program gets at them), the rules, and what was tested.

## Where the game keeps its cards

**As windows.** The duel is not drawn by one big routine with a table of card rectangles: every card is a child window of its own, and the game lets the window system find the card under the
pointer. That is the same for `MAGIC.EXE`'s duels and for `DUEL.EXE` (the two share the duel code: the class names below are in both). `PORT_CONTROL`'s `windows` shows them (this is 1024x768, the
first main phase; positions are screen pixels):

| Window class (title) | What | Where, at 1024x768 |
|---|---|---|
| `MAGICGAME_MainClass` ('Magic') | the duel's window, a child of `ShandalarMainClass`; there while a duel is on screen | 1,0 to 1025,768 |
| `MAGICGAME_TerritoryClass` ('Player Territory', 'Oppon Territory') | one for each side; its children are the permanents | 299,384 to 1025,768 and 299,0 to 1025,384 |
| `MAGICGAME_CardClass` ('In-play Card') | a permanent: one child window of its territory, 128 x 128 | wherever the game laid it |
| `MAGICGAME_HandClass` ('Your hand (7)', 'Opponent (7)') | the hand, a window you can drag by its title; its children are the cards | 819,460 and 819,307 |
| `MAGICGAME_CardClass` ('Hand Card') | a card of the hand: 128 x 128, each 15 pixels lower than the one before, so a strip of 15 pixels of each shows, and the whole of the last | 828,499 (the first), +15 each |
| `MAGICGAME_LifeClass`, `...GraveyardClass`, `...LibraryClass` | the life totals, the graveyards, the libraries (both sides) | 1,0 / 1,672; 65,96 / 65,576; 1,96 / 1,576 |
| `MAGICGAME_ManaSummaryClass` | a side's mana pool: six rows (the five colours and colourless) | 129,0 and 129,576, 128 x 192 |
| `MAGICGAME_PhaseDisplayClass` ('Phase Display') | the column of phase icons, both sides in one window | 257,0 to 299,768 |
| `MAGICGAME_FaceClass` | a wizard's face (it appears when a spell wants a player as its target) | |
| `MAGIC_TellUserClass` (the prompt) and two owner-drawn `BUTTON`s | the prompt bar, Cancel (id 1) and Done (id 2) | 299,367, 528 x 34 |
| `MAGICGAME_FullCardClass` ('Full-size card') | the big card on the left that shows the card under the pointer | 1,192 to 257,576 |
| `MAGICGAME_AttackClass`, `...SpellChainClass`, `...ScrollbarClass` | the attack and spell-chain panels, with their own `CardClass` children ('Card in attack', 'Spell Card', 'Spell Target Card') | only while there is combat or a stack |

What the code says (names in the decompiled tree are unreliable; these were read in `magic/magic_unified.c`):

- The territory's window procedure (`Duel_MainArena_WndProc`, 0x4ecfe5, registered for `MAGICGAME_TerritoryClass`) answers message `0x40a` by creating a `CardClass` child
  ("In-play Card", `DAT_006a28b0` x `DAT_006b2e30` big: 128 x 128 at 1024x768) and placing it with `SetWindowPos` at the place `Duel_LayoutCardSlots` (0x4ef15b) gives. That function is a bump layout
  over global counters (`DAT_006a49d8`, `DAT_006b2e80`, `DAT_006ff378` ...: the next free place of each kind of card, by the type flags of `Ai_Subsystem_004b613b`, the step `DAT_006ff67c`
  = 15 at 1024x768, wrapping back in three phases when it reaches the edge); `Duel_HitTestCardSlot` is only used to find which card a *new* card would land on. There is **no table of card
  rectangles and no hit list in memory** to read: the positions exist only as the windows' own rectangles. The stacks of lands that cascade at the corner of a territory (a strip of each card
  shows) are this layout too.
- A click is not looked up by the game: the window system (ours: `wm_hit_test`, `input.c`) finds the topmost window under the pointer and sends `WM_LBUTTONDOWN` to its procedure; the hover is
  `WM_MOUSEMOVE` (the big card on the left follows it). The one-window things have inner parts the procedure finds itself: the phase column (`Pic_Subsystem_00425ee3`, 0x425ee3, with the rectangles of
  `Pic_Subsystem_004262cf`, 0x4262cf: eight icons of 40/760 of the window's height, their tops at 2, 43, 84, 125, 166, 207, 248, 289 of 760, your side 430/760 lower; a click runs to that
  phase) and the mana pool (six rows of `height / 6`; `Ai_CalcManaRequirement`, 0x4b9284's window procedure, takes a row's colour when it pays).
- The hand's header (`Pic_Subsystem_0044bad4`) is a window you drag by its title; a click in its left or right fifth shows the previous or next card, which hovering does anyway, so it is not a target.

**Layouts.** All of it follows from the screen size the game was started with (`g_DisplayScreenWidth`, 0x522458, in `MAGIC.EXE`; the duel code asks `GetSystemMetrics`), so the numbers change
with `PORT_RES`; the program never hard-codes any (a table of what was measured is at the end).

## How the program gets at them (and why)

Three ways were weighed:

1. **Read the game's memory.** There is nothing to read: no table, and the layout counters above are not the positions (they are where the *next* card goes). Computing the layout again would
   copy the game's procedural code and break with it.
2. **Record the card blits.** The Win32 layer sees every draw (`BitBlt`, `StretchBlt` and the picture routines the cards are drawn with), so rectangles could be collected per frame. It would see
   what was painted, not what is clickable: a stack of cards repaints only what changed, a card hidden behind another is still blitted whole, the hand's strips are drawn whole and overpainted, and
   the prompt bar and the popup draw over cards. Matching a blit to "the card under this point" needs the stacking order again, which is the window tree.
3. **Read the window tree.** The cards, the buttons and the counters are windows; the window manager (`wm.h`) knows each one's class, rectangle, visibility and stacking, and `wm_hit_test` is the
   very function that decides where a click goes. Targets read this way are, by construction, where a click lands, and the same code gives dialogs' buttons and list rows.

The third is the one used: `navwm.c`. It runs on the guest side only (the window thread never touches the window tree; `front.c` delivers the D-pad's press at the point where input is
delivered, in order with the clicks and keys, the answer goes back through `front_nav_result`) and reads nothing of the game's memory or code.

**Which windows are targets.** Windows of the duel's classes in the table (cards, life, graveyards, libraries, faces, the prompt bar's two buttons, the attack and phase displays), that are
shown (they and all ancestors visible) and not empty; their rectangle is cut to their parents' client areas and the screen. *What of a card is visible* is found with the hit test itself: the
edges of every window that overlaps the card cut its rectangle into cells, inside each of which the hit test gives one answer; the cells where the answer is the card (or a child of it) are
joined into the biggest rectangle. So a hand card is a strip of 15 pixels (the last whole), a stacked land is the strip of it that shows, a card under the prompt bar starts below the bar,
and a card covered completely is no target. The pointer goes to the middle of that rectangle, which is a pixel a click there would give to the card. The mana pool is six targets, the phase
column sixteen (the formulas above), which is the only place the program uses a number of the game's: both are *inside one window*, so there is no other way.

**Dialogs** (`wm_top_dialog`): the dialog's enabled push buttons, check boxes and radio buttons (not group boxes), edit boxes, combo boxes (the closed box), the visible rows of its list boxes
(`ui_listbox_geometry`, the same rows the drawing code draws), and windows of the game's own classes inside it that have no such child (the card choice). **Popup menus** (the right-click menus): the
rows that are not separators or grey, of every open level. **A combo box's list that is down**: its rows. A dialog has the pointer's whole attention (it is modal, the duel behind it is not
navigated), a menu or a list down has it over a dialog.

**How the front end knows.** `front.c` asks `navwm_mode()` once a frame (30 per second): a popup menu open, a combo list down, a dialog open, or a duel on screen (a shown
`MAGICGAME_MainClass`, which exists only while there is a duel and is the cheap check: one pass over the windows comparing class names), in that order; `front_nav_ready()` is that answer. The pad
reads it when a D-pad direction goes down: with targets the press is a `PA_NAV` (a request), without it is the arrow key as before. The mode at the moment of the press holds for that press and
its repeats, so a key is never left down.

## The rules

`nav.c` (pure, `test_nav.c`); the same text is at the top of `nav.h`.

1. The current target is the one the pointer is on (the window under it; with several pieces, the nearest middle). With none, the direction is taken from the pointer itself.
2. A candidate lies beyond the current one: its centre strictly past the current centre along the axis, and either overlaps the current box sideways (up and down: in x; left and right: in y) or
   is within 45 degrees (no further sideways than along). No wrapping.
3. Tiers, the first with a candidate wins: in the beam, same zone; in the beam, another zone; in the cone only, same zone; in the cone only, another zone. A zone is a hand, a territory, a list, a
   dialog's buttons, the life totals, the piles, a mana pool, a phase column side. So inside a row of cards left and right walk the row, and at its end the move jumps to what is next to it.
4. In a tier the nearest wins: distance along the axis plus twice the sideways offset of the centres. A tie goes to the smaller sideways offset, then to the earlier in the list (sorted top to
   bottom, left to right), so it is the same every time.
5. A list that scrolls (a list box with rows above or below what is shown) says "scroll" instead of leaving it: the D-pad taps its arrow key, and the list moves. Nothing else scrolls: the hand
   grows (the game stacks more strips) and the territories lay their cards out in the window.
6. Nothing in the direction: the pointer stays. With the pointer on no target and none in the direction, the nearest target is taken, so the pointer can always get back.

Holding repeats (after 400 ms, every 150 ms). `A` is the click and `B` the right click, wherever the pointer is: *selecting is hovering* (the game shows the card), `A` acts, `B` opens the card's
menu; in a menu the D-pad walks the rows (the pointer is on each, so `A` takes it and `Y` closes).

Moving the pointer is a plain mouse move through `front_push_mouse` (the same queue, the same hold rules), no click: one click is still one pass (`click-one-pass.md`).

## Layouts

Measured in a duel at each size (`windows`, and `peek` of the game's card size `0x6a28b0` / `0x6b2e30` and hand step `0x6ff67c`). All of it scales with the screen (x0.625 and x0.78125 of 1024x768, the game's own
art sizes); the program reads the rectangles, it does not know these numbers.

| | 640x480 | 800x600 | 1024x768 |
|---|---|---|---|
| card | 80 x 80 | 100 x 100 | 128 x 128 |
| hand step (the strip of a card that shows) | 9 | 11 | 15 |
| your hand window (default place) | 512,288 | 632,360 | 819,460 |
| territories (yours; the opponent's above) | 187,240 to 641,480 | 234,300 to 801,600 | 299,384 to 1025,768 |
| phase column | 161..187 | 201..234 | 257..299 |
| the big card (hover) | 1,120 to 161,360 | 1,150 to 201,450 | 1,192 to 257,576 |
| prompt bar | 187,230 | 234,287 | 299,367 |
| a life total, a pool | 80 x 60, 80 x 120 | 100 x 75, 100 x 150 | 128 x 96, 128 x 192 |

Where a card goes in a territory is the game's own business and looks like this at 1024x768: the opponent's creatures in a row along the bottom of its territory (cascading onto each other when there are many),
lands of both sides in a stack in the right-hand corner (a strip of each shows), yours and the opponent's mirrored.

## Tested

Headless (SDL's dummy drivers, `PORT_CONTROL`), with controller commands only, `tools/soak/nav_play.py`, at 640x480, 800x600 and 1024x768, in a duel against the Sorcerer started from the saved game (the mouse
plays the duel to a board with lands and creatures on both sides; the life totals were set to 60 with `poke` so the duel lasts), and by hand in `DUEL.EXE`.

- **The coin toss and the mulligan/ante dialogs** were answered with the D-pad and A: `Play first` to `Draw first` is one press of down and back one of up; the wanted button was reached and pressed.
- **The list** (`pad nav`): 50 to 55 targets at each size: every card of the hand, every permanent in play that is not covered (13 of 13 windows at 1024x768; the stacked lands are strips), both life totals, both
  libraries and graveyards, the pools' 12 rows, the phase icons (16, or the combat column's 7), the Done button. `hit` at the middle of every target gave that target's window (0 wrong), and every target was on the screen.
- **The examples**: on the last card of the hand, up six times went up the hand strip by strip (each landing the middle of the strip above); up from the first card left the hand (to the stack of lands above it);
  down from the last card stayed where it was (no wrapping). In the layout above, left from the hand reaches the phase icons level with it (there were no cards of mine to the left), and from the opponent's row up
  from the Done button reaches the creature above it, not the phase icon beside it.
- **Every target in every direction**: the pointer was put on each target with the mouse and each of the four directions pressed (about 50 x 4 presses, 180 moves in 160 s). Every move landed on the middle of
  another target of a fresh list and went the way it was pressed; about three in four were undone by the opposite direction (the rest go between things of different sizes and places, where the way back starts from another middle); from the hand's last card **every** target could be reached by D-pad moves alone.
- **The hover**: after D-pad moves onto a hand card and onto two permanents, the big card on the left was the same picture as after the real mouse was put on the same pixel (the game shows it a second or so after the pointer
  arrives, a permanent's later than a hand card's; the check waits for the picture to settle), and the pictures differed from card to card.
- **A and B**: A on Done passed the phase (`Main phase (before combat)` to `... (after combat)`); A on a hand card acted as a click (`CASTING: ..., tap ...`, or a land played); B opened the card's menu (5 rows),
  down walked its rows with the pointer on each (the first press from the card goes to the first row), down at the last row stayed, up went back, Y closed it.
- **The map**: `pad nav` says `none` and the D-pad, held, walks the party as the arrow key (`pad_play.py --only newgame`).
- **`DUEL.EXE`**: the same duel code; the hand, A on a card (a Swamp played from the hand: the land became a target at once), and its setup dialog: 14 targets (radio buttons, two combo boxes, five push buttons), a combo
  box dropped with A (its rows are targets: `mode combo`), down twice and A chose the third deck.
- Unit tests: `test_nav` (91 checks: grids, the user's examples in a layout of a hand, territories, phase icons and life totals, staggered rows, ties, an empty list, a pointer on nothing, scrolling lists, the wide bar),
  `test_wm` (the targets read off windows of a duel's classes laid out as at 1024x768: strips, the prompt bar over a card, the combat column, a dialog, a menu, a combo list), `test_pad` (a D-pad press is a request
  in a duel and a key elsewhere, for the whole hold; repeats; the answers).

## Not verified, and what a person has to judge

- **A real controller.** Everything above is SDL's controller events pushed by the `pad` steps (as `controller.md` says). The rhythm of a held direction (first repeat at 400 ms, then every 150 ms, `PAD_NAV_REPEAT_MS`)
  and whether a D-pad (or a Steam Deck's) needs the stick's help are matters of feel.
- **Whether the choices are the natural ones.** The rules are TV-style focus rules; they were checked for consistency (every move goes the way it was pressed, everything is reachable) but whether "up from Done" or "left
  from the hand" lands where a player expects, in the many layouts a duel can have (a territory full of creatures that cascade, a hand dragged elsewhere), is for a player to say. There is no memory of the column
  you came from: up then down from a card in a different column may come back to its neighbour, not to the card you left (about a quarter of the moves are not undone by the opposite direction).
- **What was not on the board**: the attack and spell-chain panels' cards (they are targets of their own, `Card in attack` and the combat column were seen listed; A on them was not tried), the graveyard and library
  pile windows when clicked (the lists they open are windows of other classes that are not targets yet), a wizard's face while a spell asks for a player, the card choice windows of a dialog (the Sorcerer's "casts..."
  dialog has one target and no button: the D-pad does nothing there, as the arrow keys did), a menu with a sub-menu (the Concede item), a list box that scrolls (a dialog's list, the file dialogs: the rows are targets and
  the arrow key is tapped at the edge, by unit test and by the combo list only), and a duel at a window size other than the screen's.
- **The deck builder** has windows (its cards and buttons are targets now: mode `deck`, `controller-screens.md`); **the village, the title menus, the shops** have no windows, and are read from the game's button
  table (`controller-screens.md`). The castles' mazes stay on the arrow keys.

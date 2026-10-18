# Game controllers

The game sees a mouse position, two mouse buttons and keys, nothing else, so a pad is emulation in the front end: the left stick moves a cursor, the buttons click and press keys. The game's code is not
touched. Everything goes through `front_push_mouse` and `front_push_key` (`front.c`), the queue the real mouse and keyboard use, so the hold on a press (`HOLD_MS`, 70 ms) and the one-click-is-one-pass rule
(`click-one-pass.md`) apply to a pad as they do to a mouse: A pressed and let go quickly is a down and an up that `front_hold_rule` spaces out, a click on a village's "Buy 10 food" bought once (250 gold ->
235, food 49 -> 59) and a held A past 400 ms repeats like a held mouse button.

Files: `pad.c` / `pad.h` (the logic: no SDL, no game, unit tested: `test_pad.c`, about 450 checks), and the glue in `front_sdl.c` (controller events in, the cursor drawn, the `pad` steps of `PORT_CONTROL`). The D-pad's
navigation is `nav.c` (which target next: pure, `test_nav.c`) and `navwm.c` (the targets, read off the window tree), described in `controller-nav.md`; on the game's own screens the targets are read from the game's button table by `screens.c`, described in `controller-screens.md`.
`PORT_NOPAD=1` turns it all off. With no controller nothing changes: the pad is "active" only after it has been used, and the real mouse takes over again the moment it moves.

## The controls

All of this is one table at the top of `pad.c` (`binds[]`, with the numbers beside it: dead zone, curve, speeds, step, repeat times, walking reach).

| Control | Does | Why |
|---|---|---|
| Left stick | the cursor, in screen pixels | |
| Left trigger (held) | slow cursor, a quarter of the speed | precision |
| Right stick pressed in (held) | fast cursor, twice the speed | |
| D-pad | **in a duel, a dialog or a menu, on the screens the game draws itself (title, new game, village, shops, world map, clues, stats, the encounter boxes) and in the deck builder: the cursor jumps to the next card, button or row in that direction** (after 400 ms it repeats, every 150 ms); on the map, in castles and dungeons the arrow keys, repeating as a keyboard's do (after 400 ms, every 70) | `controller-nav.md`: how the targets are found and the rules; `controller-screens.md`: the game's own screens |
| A | left click; held while A is held (drags: deck builder cards; the map walks toward the cursor) | |
| B | right click (the game's menus on a card, the castle pager's previous page) | |
| X, Start | Enter | the default button of a dialog, the Done of a prompt bar, the name entry |
| Y | a double click at the cursor | on a card in a duel the game pays its mana for you; two presses 70 ms apart, well inside the game's double-click time |
| Back | Escape | cancel; "Ready to Quit?" on the map. **At the title menu it has to be held half a second** (below). Y is not Escape on purpose: Escape closes the game on some screens, and Y is easy to hit |
| LB | **in a duel, with the cursor on a card: view that card** (below): the game's own Full-size card window shows it at once, and a second press shows it enlarged over the whole window. With no card under the cursor, and everywhere else, **Page Up** (repeating) | the list boxes, the file dialog and the deck builder's card row |
| RB | Page Down, repeating | the same lists (RB scrolled the deck builder's stock row a page at 1024x768) |
| Left stick pressed in | Space | the map reads Space as "stop" (`Adventure_PlayLocationMusic`, key 0x20); not tried |
| Right trigger (held) + left stick | **walk** on the map (below) | |
| Right stick | the arrow keys, in eight directions (the diagonals are Home, Page Up, End, Page Down, which the map and the castles read as the keypad) | walking on the map and in castles and dungeons by key, rows of a list |
| Guide, the extra buttons, rumble | nothing | |

Names are the position-based ones SDL uses (A is the bottom button of the diamond on every pad; on a Nintendo pad SDL's button labels setting decides, its default is the label).

## Viewing a card

**What the spot is.** In a duel the game keeps a window of its own for the card you are looking at: `MAGICGAME_FullCardClass`, title "Full-size card", the big card on the left (256 x 384 at 1024x768; the deck
builder has its own, `MagicFullCardClass`, 288 x 432). It is drawn by the game from the card it was last given. It is given one by a message of its own (`WM_USER + 1`: the card's two numbers; the window keeps
them and repaints), and the game sends that in two ways, found by reading the window procedures (`MAGIC.EXE` 0x4997e6 is the Full-size card's, 0x467a68 the card windows'):

- **Hover.** The card under the pointer is shown after the pointer has rested on it for about three seconds (the windows that hold cards set 3000 ms timers). Measured at 1024x768 by moving the pointer onto a card of the
  hand and taking the picture every 0.7 s: unchanged at 3.5 s, changed at 4.3 s. That is what the D-pad's moves wait for. (The deck builder shows its card at once: changed in under 0.5 s.)
- **The card's own menu.** A right click on a card (B) opens a menu whose first line is "View in full card" (command 0x6e; "Show full card" when the game runs at the small size, where the same window pops up for
  twelve seconds), and choosing it sends the window the card at once. The card's window procedure does it on `WM_COMMAND` 0x6e, from the card's own two numbers.

On the Full-size card window itself (tried at 1024x768 with the real game): a left click and a double click do nothing; a right click opens its own menu, "Expand text box" (the card's rules text
box grows over the picture, for a long text: a game option, the first line is checked while it is on), "Help for this card..." and "Help...". A, Y (double click) and B on a card in the duel are what they always were:
play or tap it, pay its mana, open its menu. So there is no bigger view in the game than this window (and its expanded text box).

**What the port does.** The view button posts that same command, `WM_COMMAND` 0x6e, to the card window under the pointer (`navwm_view_card`; `profile->viewcard.cmd`, a per-build number: 1.0's `MAGIC.EXE` and `DUEL.EXE` have it,
Spells of the Ancients 2.15 draws its card menu from a resource and has no such command, so LB stays Page Up there). The game then does what it does for its own menu: the card is in the Full-size card window within a
frame, and stays there until the pointer has rested on another card for three seconds. Nothing is written to the game's memory and no key or mouse message is invented. Three ways to ask:

| | |
|---|---|
| LB | with the pointer (the pad's cursor) on a card of a duel: view it. Elsewhere Page Up, as above. The decision is the one of the moment the button goes down (`front_view_ready`, a flag the guest side refreshes 30 times a second: the pointer is on a `MAGICGAME_CardClass` window, in a duel with no dialog or menu on top), so a held LB is a view or a Page Up for its whole length |
| V | the same, for the keyboard's pointer. With no card under it V is the game's (a V typed in a name); Ctrl, Alt and Shift with V are not ours |
| the middle mouse button | the same, at the pointer |

**The second press.** The same button again, on the same card, with nothing sent to the game since (`front.c`: the pointer has not moved, no click or key went in), takes a copy of the Full-size card window's picture
(its own surface, on the guest side, at that moment: it stays as it was whatever the pointer does) and the window half shows it over the whole frame, dimmed behind (`ZOOM_DIM_ALPHA`), centred, with its shape kept
(`display_zoom_layout`: as large as fits in 96% of each side, a whole-number scale when that loses under 10%), drawn into the window's own pixels with the filter the player chose (nearest, linear, or sharp: a
whole-number enlargement with nearest neighbour and then the final step linear). So it uses all of the window's resolution, not the game's. While it is up **the game is sent nothing**: the pointer's moves, the
wheel, clicks, keys, text and touches are taken here and so are the pad's buttons, triggers and sticks (`pad_freeze`: what the pad held is let go once, then it is silent, so the cursor stays where it was). **Any
mouse button, key (except Shift, Ctrl, Alt and the display's own F11 and Alt+Enter), pad button or trigger, or a finger on the screen ends it**, and that press is not the game's either (its release is dropped too); the
sticks and moving the mouse do not. Press LB, V or the middle button once more on the card and it is back; move the pointer and the next press is a first one again.

Touch (iOS) has no binding of its own: a long press is a right click, whose menu has "View in full card".

**How legible it is** (looked at, 1024x768 and 640x480): the source is the game's drawing at its own size, with 8 ppem text. At 1024x768 (the card 256 x 384, shown 1.92x at 491 x 737) the name, cost and type line,
the rules text and the artist line are easy to read; at 640x480 (160 x 240, also 1.92x at 307 x 460) the rules text of a short card is readable and a long one is small and soft but legible. It is a bigger picture of the
same pixels, not a redraw: the hinted letter shapes of the 8 ppem font and the card's dither get bigger with it. A crisper card would need the game's own card drawing (`MagicFullCardClass`'s and the card windows'
routine, which draws into the window's device context with `MM_ISOTROPIC` and a LOGFONT of height 14, `card-text-metrics.md`) to be called with a larger window and font, which means a window (or a device
context) of the larger size for the game to paint into: not tried.

Tested: `test_pad` (the binding; LB is a view only with a card under the pointer and Page Up otherwise, for the whole press; RB unchanged; `pad_freeze`), `test_wm` (`navwm_card_at` in a duel laid out as at 1024x768,
the command posted to the card's window, none in a build without it or with a dialog on top), `test_display` (`display_zoom_layout`: centred, shape kept, inside the margin, never cut, at 13 output sizes and 5 card
sizes), `test_profile`, and `python3 tools/soak/card_view.py [--res 640x480|800x600|1024x768] [--deck] [--game duel]`: a duel at the pad's pace, LB, V and the middle button on a card of the hand and permanents of both
sides (the big card changes within 0.6 s, as the game's own hover does only after its wait, to the same picture), LB with no card is Page Up, the second press (the window dimmed, the card centred), and every kind of
press ending it with the input log showing the game was sent nothing, the window then identical to before, A on Done passing the phase; `--deck` checks the deck builder (its card follows at once, LB and RB are as they were).
Not verified: with a real controller, in Spells of the Ancients, at the small size where the game pops the card window up (`0x6fe444` is 2 there: read in the code, not seen), and on a real display.

## The cursor

- **Coordinates.** The cursor lives in the game's screen pixels (`SCREEN_W` x `SCREEN_H`, so any `PORT_RES`) as a float, is moved by the stick at a fixed integration step (`pad_step(ms)`: the main loop passes the
  real time since the last turn of its loop, at most 100 ms, so a window drag does not fling it), and is announced to the game as an integer position when it changes. The speed is in screen widths per second
  (`PAD_FULL_SPEED` 1.0: a full push crosses the screen in one second at 640 and at 1024 alike), after a round dead zone (0.22) and a response curve (the push past the dead zone, squared). The window's
  size does not matter: the pointer the game sees is a screen pixel, and `SDL_RenderSetLogicalSize` scales the picture, not what we send. The cursor stays inside the screen.
- **It is drawn by us.** The game draws no cursor (`SetCursor` and `ShowCursor` are stubs, the pointer is the host's). The pad's arrow (a 12x19 pixel one, twice that from 1024 wide up) is drawn into the
  frame that is shown (`frame_view`, `front_sdl.c`), in a window and in a full screen alike, and the host's pointer is hidden (`SDL_ShowCursor`) while the pad is the device in use. `shot` in `PORT_CONTROL`
  includes the arrow while the pad is active, so a screenshot shows where it is. No `SDL_WarpMouseInWindow`: a warp is a mouse event, it would hand the cursor back to the mouse.
- **Last device wins.** A mouse motion or click (a touch is a mouse to SDL, `SDL_HINT_TOUCH_MOUSE_EVENTS` stays at its default) makes the mouse the active device, puts the pad's cursor where the mouse is (so
  the next stick push starts from there), lets go of whatever the pad held (a button, a key) and stops the stick from moving anything until it is moved again (a stick held while the mouse is used does not fight it).
  A controller unplugged, or the window losing focus, lets go of everything too.
- **Full screen.** `PORT_FULLSCREEN=1` starts in a borderless full-screen window (SDL's "desktop" full screen: the picture is scaled with the shape kept, bars at the sides), F11 and Alt+Enter toggle it on a keyboard, and
  **both sticks pressed in (L3 + R3) held for a second** toggle it on a pad (`display.md`). Back + Start was not used for that on purpose: Back is Escape and Start is Enter, sent when each goes down, so pressing them in turn would cancel and then confirm
  whatever the game asks ("Ready to Quit?" on the map). L3 is Space (stop, on the map) and R3 the fast-cursor modifier, so the combination sends one harmless Space. On a Steam Deck (or inside Gamescope) full screen is the default
  (`PORT_FULLSCREEN=0` for a window), and the scale is a whole number where that loses little: `steamdeck.md`.
- **Steam Input.** Steam hands a non-Steam game the Desktop layout (a keyboard and mouse, no game controller), so a Deck needs the Gamepad template for this file's pad to work: `steamdeck.md` has the steps,
  the layout file that ships, and `SDL_GAMECONTROLLERCONFIG` / `SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS` (set on a Deck).
- **Hot plug.** `SDL_INIT_GAMECONTROLLER`; SDL queues `SDL_CONTROLLERDEVICEADDED` for each controller present at start and for each plugged in later, each is opened, and `SDL_CONTROLLERDEVICEREMOVED`
  closes it. Every controller drives the same cursor. `SDL_GAMECONTROLLERCONFIG` works as for any SDL program.

## Walking

On the map the game walks the party toward the pointer while the left button is held, in eight directions: `Adventure_HandleLocationMenuChoice` (0x4e7a6f) takes the pointer's place relative to the party,
which never moves on the screen (the map scrolls under it), at (320, 188) in 640x480 pixels scaled by width/640 (512, 300 at 1024x768; the sprite stands a little below and right of that), and ignores the pointer
outside the map (x 64..576, y 48..328, same units). A click in the box around the party (304..344 by 168..221) stops it. It also reads the arrow keys and the keypad diagonals for the same eight directions
(`Adventure_PlayLocationMusic`, 0x4e7f51, on the key codes 0x4800, 0x5000, ...).

- **Right trigger + left stick** (walk mode): the pointer goes to the party's place plus `PAD_WALK_REACH` (0.15 of the width: 154 px at 1024, always inside the map) in the stick's direction, and the left button is
  held; the direction follows the stick; the stick back to rest, or the trigger let go, lets the button go. The game turns the direction into the nearest of its eight. Seen at 1024x768: east walked the party
  from (368, 752) to (380, 764) in 2.5 s (the map is isometric, east is +x +y; rough ground and the 60 ms frame make it slow), into a village (Amanaxis Village, the Buy 10 food button then worked with A).
- **Right stick**: arrow keys. The party walked (down: (-20, +20) in 1.5 s). The party stopped when the stick came back to rest. This is the way to walk in castles and dungeons too, where the party is not at the same place on the screen
  (walk mode aims from the map's place, so it is for the map only).
- A with the stick (a drag) also walks, as with a mouse.

## Text entry

The new game's name box is drawn and read by the game itself from key events (a dialog of the game's own, not an edit control of the window layer: nothing in the window tree says that a text field has the focus). The real keyboard
works as before (the name box has "Melody Whisp" in it to accept with X / Enter), and so does Steam's on-screen keyboard (Steam + X) when it sends key events. `steamdeck.md`, "Text", has what was added for the Deck: text
that arrives with no key before it (`SDL_TEXTINPUT` from an input method or a keyboard that sends text) is typed as the key presses that produce it (the name box reads keys and ignores `WM_CHAR`), once per character, and on a
Deck `SDL_StartTextInput` is called only while a text field has the focus: an edit control in the open dialog (the file dialogs' name box), or the new game's name box, which the game says by asking for keys in its
name loop (a hook before `FUN_004080b2`, `textfocus.c`). The pad has no key for typing; A on the on-screen keyboard is Steam's.

## Testing without a controller

`PORT_CONTROL` and `PORT_SCRIPT` take `pad` steps. They push the SDL controller events a real device would (`SDL_CONTROLLERAXISMOTION`, `SDL_CONTROLLERBUTTONDOWN`/`UP`, with an instance id no device has: the handler
does not look at it), so the code from the event on is the real one:

    pad axis lx|ly|rx|ry|lt|rt VALUE      -1..1 (triggers 0..1)
    pad stick l|r X Y                     both axes of a stick
    pad button NAME down|up               a b x y back guide start l3 r3 lb rb up down left right
    pad press NAME                        down, then up
    pad remove                            a controller was unplugged
    pad pos                               where the cursor is, on stderr: "pad: X Y active=0|1 left=0|1"
    pad nav                               what the D-pad would move between now: "nav: mode duel|deck|dialog|menu|combo|screen|none, N targets, pointer (X,Y) on I", then a line for each target
    hit X Y                               (not a pad step) the window a click at X, Y reaches

(Steps are handled in the order of the pipe, but the controller events they push are seen by the next turn of the window loop: ask `pad pos` a few milliseconds after the last one.)

- `make -C src/port test` runs `test_nav` (the choice of the next target) and `test_wm` (the targets read off windows of a duel's classes, a dialog, a menu, a combo list), and `test_pad` (the dead zone, the curve, the speed at 640 and 1024 and at 1, 8 and 33 ms steps, clamping at the four edges, every button, repeats, walking, the mouse taking over, unplugging, drawing and clipping the arrow).
- `python3 tools/soak/pad_play.py [--shots DIR]` plays with pad commands only, headless, 1024x768: the title screen, difficulty, colour, visage and name of a new game, walking on the map (trigger and stick,
  right stick), then, from the saved game, the encounter's Duel, the coin toss dialogs, a land played from the hand with A, B's menu closed with Back, Done. It reads the game's memory and the window tree to check
  each step and keeps screenshots; it passed here. `Game.pad_goto` (`tools/soak/pentamoor_ctl.py`) moves the cursor with the stick the way a person does (closed loop on `pad pos`).
- `python3 tools/soak/screen_nav_play.py [--res 1024x768] [--shots DIR]` plays a new game, a castle's gate, a village (food, a card bought), the world map, the clues, the wizard's stats and the deck builder with the D-pad and A, and checks each screen's targets against the game's own hover (`controller-screens.md`).
- `python3 tools/soak/pad_realtime.py [--res 1024x768] [--env "K=V ..."]` plays a duel with the pad at a person's speed (a button down 120 to 150 ms, the next 450 ms later, a direction held 1.3 s, the stick to bring the pointer near) with `PORT_PAD_LOG` on and checks the input log: every D-pad press lands on a target, no arrow key goes to the duel, A on Done passes the phase, B's menu opens and closes, the D-pad's mode stays `duel`, the game's (Y/N) question is never reported, no message box.
- `python3 tools/soak/nav_play.py [--res 1024x768]` plays a duel (mouse, until both sides have permanents) and then checks the D-pad in it: `controller-nav.md`, "Tested".
- By hand with the same driver: the deck builder (`DECK.EXE`): a card dragged from the stock row into the deck with A held and the stick (Stats 0 -> 1 cards), RB paging the stock row, and the title screen, a village's food button
  (one A press, one purchase), the duel's hand list, a card's right-click menu (B) and a menu row chosen with A, the encounter dialogs' buttons.

## Not verified

- **A real controller.** Nothing here was run with one: the events were SDL's own type pushed by the `pad` steps, on SDL's dummy video driver. Open: whether the Steam Deck, an Xbox, a PlayStation and a Switch pad
  are seen as game controllers with these button names (SDL decides), the hot plug, the real stick's drift against the 0.22 dead zone.
- **Feel.** Speed, curve, dead zone, the slow and fast factors, the key repeat, the walk reach and the trigger thresholds are all numbers at the top of `pad.c`; they were picked, not tuned. Full push crosses
  the screen in a second; the slow trigger makes that four seconds; whether the arrow is big enough at a couch's distance is a matter of taste (`pad_cursor_scale`).
- **A real display.** The drawn cursor and the hidden host pointer were looked at in screenshots and, for the pointer, by the code path only (the dummy video driver has no pointer to see). Full screen likewise.
- **Touch** was not touched: SDL's default turns it into the mouse, and the pad then gives the cursor back to it. (The Deck's touch screen goes through the same logical size as the mouse; not tried.)
- **Steam Input's layouts** (`steamdeck.md`): the Gamepad template and the layout that ships were not loaded in a Steam client.
- **The game's own keyboard navigation of buttons** (Tab and Shift+Tab, and the up and down arrows on some screens, step through a screen's button table by index and call `SetCursorPos` to put the pointer on the
  button: `FUN_0041f3ea`, 0x41f3ea) is not followed: `SetCursorPos` only changes the number `GetCursorPos` answers, so neither the real pointer nor the pad's cursor moves with it. The D-pad does not use it: on the
  game's own screens it reads the same table (`controller-screens.md`) and moves by the picture, and in the map it is the arrow keys.

## Back where Escape leaves the game with no question

Back is Escape, and Escape ends the game on some screens. Which, found by pressing it on each screen reached headless (the saved game, 640x480, the keyboard's `key escape`; `tools/soak` has the recipes, the table is what was seen):

| screen | Escape does |
|---|---|
| **title menu** (Start New Game, Load, Resume, Exit) | **leaves the game at once**, no question (exit status 1; the title menu takes Escape as its Exit) |
| new game: difficulty, colour, visage | back one screen |
| the map | the text menu "Ready to Quit?" (two lines); Escape again closes it. Its Quit line, in the menu B opens, quits without asking: it is a line the player picks |
| village, the Clues, the deck builder (F1) | leaves to the map |
| castle gate, the maze of a castle or a dungeon | leaves (the first one closes the rule card, the second leaves the maze) |
| world map, Plain/Info/City Info | nothing |
| the encounter's menu ("Will you... Duel / Pay") | not tried (a text menu: Escape answers "cancel" there, 0x489b4d) |
| dialogs and menus of the port | cancel |

So the title menu is the one place where a tap of Back closes the game with no confirmation (a controller user who presses Back to leave a screen they are not on lands there after a few of them). `pad.c` now holds Back for `PAD_BACK_HOLD_MS`
(500 ms) when `pad_set_back_guard`'s function says the title menu is on: the key goes down at 500 ms if the button is still held and up when it is let go; a shorter press sends nothing. The function is `main.c`'s `title_guard`:
`screens_kind() == SCREEN_TITLE`, which `screens.c` knows from the title's loop (`title.loop` in the build profile, 0x47a2e6 to 0x47a94c: the pass of the button table that returns into it). It is asked when Back is
pressed. Everything else keeps Back as a tap (dialogs, menus, duels, "Ready to Quit?"), and the keyboard's Escape is as it was (the original's behaviour).

Tested: `test_pad` (+9: the tap, a short hold, a hold with no repeat, a release in the middle, the guard asked at the press, no guard installed), `test_profile` (the range), `test_wm` (the title loop is `SCREEN_TITLE`, a table screen for the D-pad), and
`tools/soak/back_guard.py` (640x480, headless, controller commands: at the title menu a tap and a 0.3 s hold do nothing and a 0.9 s hold ends the game; a tap on the difficulty screen goes back; on the map a tap opens
"Ready to Quit?" and a second closes it).
Not checked: with a real controller (the hold's feel: 0.5 s is a guess; nothing on the screen says "hold"), the dungeon of the saved game's entry 5 (the crash seen on a teleport onto it was the script's, not the dungeon's: see
`castle-dungeon-stats.md`, "Teleporting by poke"), the encounter menu's Escape, the Load Saved Game dialog's.

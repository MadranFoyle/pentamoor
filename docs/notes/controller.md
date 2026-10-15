# Game controllers

The game sees a mouse position, two mouse buttons and keys, nothing else, so a pad is emulation in the front end: the left stick moves a cursor, the buttons click and press keys. The game's code is not
touched. Everything goes through `front_push_mouse` and `front_push_key` (`front.c`), the queue the real mouse and keyboard use, so the hold on a press (`HOLD_MS`, 70 ms) and the one-click-is-one-pass rule
(`click-one-pass.md`) apply to a pad as they do to a mouse: A pressed and let go quickly is a down and an up that `front_hold_rule` spaces out, a click on a village's "Buy 10 food" bought once (250 gold ->
235, food 49 -> 59) and a held A past 400 ms repeats like a held mouse button.

Files: `pad.c` / `pad.h` (the logic: no SDL, no game, unit tested: `test_pad.c`, about 430 checks), and the glue in `front_sdl.c` (controller events in, the cursor drawn, the `pad` steps of `PORT_CONTROL`). The D-pad's
navigation is `nav.c` (which target next: pure, `test_nav.c`) and `navwm.c` (the targets, read off the window tree), described in `controller-nav.md`.
`PORT_NOPAD=1` turns it all off. With no controller nothing changes: the pad is "active" only after it has been used, and the real mouse takes over again the moment it moves.

## The controls

All of this is one table at the top of `pad.c` (`binds[]`, with the numbers beside it: dead zone, curve, speeds, step, repeat times, walking reach).

| Control | Does | Why |
|---|---|---|
| Left stick | the cursor, in screen pixels | |
| Left trigger (held) | slow cursor, a quarter of the speed | precision |
| Right stick pressed in (held) | fast cursor, twice the speed | |
| D-pad | **in a duel, a dialog or a menu: the cursor jumps to the next card, button or row in that direction** (after 400 ms it repeats, every 150 ms); anywhere else the arrow keys, repeating as a keyboard's do (after 400 ms, every 70) | `controller-nav.md`: how the targets are found and the rules |
| A | left click; held while A is held (drags: deck builder cards; the map walks toward the cursor) | |
| B | right click (the game's menus on a card, the castle pager's previous page) | |
| X, Start | Enter | the default button of a dialog, the Done of a prompt bar, the name entry |
| Y | a double click at the cursor | on a card in a duel the game pays its mana for you; two presses 70 ms apart, well inside the game's double-click time |
| Back | Escape | cancel; "Ready to Quit?" on the map. Y is not Escape on purpose: Escape closes the game on some screens, and Y is easy to hit |
| LB, RB | Page Up, Page Down, repeating | the list boxes, the file dialog and the deck builder's card row (RB scrolled the stock row a page at 1024x768) |
| Left stick pressed in | Space | the map reads Space as "stop" (`Adventure_PlayLocationMusic`, key 0x20); not tried |
| Right trigger (held) + left stick | **walk** on the map (below) | |
| Right stick | the arrow keys, in eight directions (the diagonals are Home, Page Up, End, Page Down, which the map and the castles read as the keypad) | walking on the map and in castles and dungeons by key, rows of a list |
| Guide, the extra buttons, rumble | nothing | |

Names are the position-based ones SDL uses (A is the bottom button of the diamond on every pad; on a Nintendo pad SDL's button labels setting decides, its default is the label).

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
- **Full screen.** `PORT_FULLSCREEN=1` starts in a borderless full-screen window (SDL's "desktop" full screen: the picture is scaled with the shape kept, bars at the sides). There is no key for it. On a
  Steam Deck (or inside Gamescope) it is the default (`PORT_FULLSCREEN=0` for a window), and the scale is a whole number where that loses little: `steamdeck.md`.
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
    pad nav                               what the D-pad would move between now: "nav: mode duel|dialog|menu|combo|none, N targets, pointer (X,Y) on I", then a line for each target
    hit X Y                               (not a pad step) the window a click at X, Y reaches

(Steps are handled in the order of the pipe, but the controller events they push are seen by the next turn of the window loop: ask `pad pos` a few milliseconds after the last one.)

- `make -C src/port test` runs `test_nav` (the choice of the next target) and `test_wm` (the targets read off windows of a duel's classes, a dialog, a menu, a combo list), and `test_pad` (the dead zone, the curve, the speed at 640 and 1024 and at 1, 8 and 33 ms steps, clamping at the four edges, every button, repeats, walking, the mouse taking over, unplugging, drawing and clipping the arrow).
- `python3 tools/soak/pad_play.py [--shots DIR]` plays with pad commands only, headless, 1024x768: the title screen, difficulty, colour, visage and name of a new game, walking on the map (trigger and stick,
  right stick), then, from the saved game, the encounter's Duel, the coin toss dialogs, a land played from the hand with A, B's menu closed with Back, Done. It reads the game's memory and the window tree to check
  each step and keeps screenshots; it passed here. `Game.pad_goto` (`tools/soak/pentamoor_ctl.py`) moves the cursor with the stick the way a person does (closed loop on `pad pos`).
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
- **The game's own keyboard navigation of buttons** (Tab and Shift+Tab, and the up and down arrows on some screens, step through a screen's hotspots and call `SetCursorPos` to put the pointer on the
  button: `FUN_0041f3ea`, 0x41f3ea) is not followed: `SetCursorPos` only changes the number `GetCursorPos` answers, so neither the real pointer nor the pad's cursor moves with it. The D-pad's own navigation
  (`controller-nav.md`) works from the window tree instead, and only in duels, dialogs and menus; the screens drawn by the game itself (the title menus, the village, the castle pager, the map, the deck
  builder) have no windows to read, so there the D-pad is still the arrow keys.

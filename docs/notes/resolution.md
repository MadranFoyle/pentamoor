# Resolution: 1024x768 is the default

The program starts at 1024x768 now. `PORT_RES=640x480` gives the original's size, `PORT_RES=800x600` the middle one. This note says what was looked at to decide it, what was
found, and what is the game's own doing at the larger sizes. Method as in `overworld.md` and `castle-dungeon-stats.md`: SDL's dummy drivers, a `PORT_CONTROL` fifo and
screenshots (`shot`), each size in its own process with its own overlay, monsters poked out of the overworld's table, teleporting onto towns and castles by writing the party's position.

## How a size is chosen

`main.c` sets the screen to 1024x768 and then lets `PORT_RES` override it (`screen_set` accepts 640x480 up to the largest buffer, 1600x1200; the game only has layouts for 640x480, 800x600 and
1024x768, so those are the three that mean something). For `MAGIC.EXE` the two numbers are also written into the game's memory (`g_DisplayScreenWidth/Height`, 0x522458/0x52245c), which is
what switches the game to its larger art and layouts. `DECK.EXE` and `DUEL.EXE` do not read that variable (the deck builder DLL and the duel code ask `GetSystemMetrics`), so the screen
size alone changes them. All three programs run at the default.

## The window

Since the display work ([display.md](display.md)) the window starts as the largest whole-number multiple of the screen that fits 90% of the display's usable area (`display_initial_window`: 1024x768 on a 1366x768 laptop's
874x655 free area does not fit even once, so it is 874x655 with the shape kept; 1440x900 and 1920x1080 displays get 1024x768, 4K 2048x1536), or the size `display.cfg` remembers, and is resizable down to the picture's own size. The picture is scaled
into it by `display_layout` (not `SDL_RenderSetLogicalSize` any more) and the mouse is mapped back by `display_to_screen`, so a click lands where it is drawn at any window size, on a Retina display too (`PORT_WINDOW=700x525` on the 1024x768
screen was how it was first checked, with scripted clicks given in screen pixels). `PORT_WINDOW=WxH` asks for a window size by hand. A run on SDL's dummy driver keeps the screen's size; scripted mouse positions are screen pixels whatever the window is.

**Full screen** (F11, Alt+Enter, `PORT_FULLSCREEN=1`, and by default on a Steam Deck or in Gamescope: `steamdeck.md`) is SDL's desktop full screen: the display's own size, the picture scaled with its 4:3 shape kept and bars on the
free sides. `display_fit` (`display.c`, formerly `view_scale` in `steamdeck.c`) picks the scale for `fit`: a whole number (1x, 2x) when it uses at least 90% of the best fractional scale, so that every pixel stays square (the
Deck's 1280x800 shows 1024x768 at 1x with bars of 128 px at the sides and 16 above and below; 1.04x would double an uneven one pixel in 24), else the fractional one (a 1080p television: 1.41x, 1440x1080). Looked at with the real X11 driver on a virtual 1280x800 and 1920x1080 display
and a real (XTest) pointer: the picture where the layout says, a click on the drawn "Start New Game" arrives at 528,493 in both (the same check, for many more setups, is `tools/display/xe2e.py`).

Two things that were wrong at a window size other than the screen's, and are fixed (`front_sdl.c`):

- **Scripted mouse positions were off.** SDL's logical-size mapping turned every mouse event, a pushed one too, from window pixels to screen pixels, so `click 450 500` in a window of 700x525 arrived as some other
  point. A scripted position is marked and given to the game as it is now (the display work), so it is the screen pixel the script gave, whatever the window.
- **`shot` wrote garbage in a window of another size.** It read the renderer back, which gives window pixels, into a buffer sized for the screen: the picture came out as a small copy of the
  screen drawn over a second, broken one. It writes the latest frame itself now (the screen's size whatever the window).

## What was looked at

At 1024x768 (every screen below), 800x600 (title, new game, the map walked, a village, "Cards for Sale", Wiz Stats and Journal, the duel at its start, ante and coin toss) and 640x480 for comparison:

| Screen | Seen | Result |
|---|---|---|
| Title, new game (difficulty, colour, visage, name) | 640, 800, 1024 | the game's art for each size; every click lands on the button drawn |
| Overworld | 640, 800, 1024 | map, the stained-glass frame, the right-hand column, the stamina/food/gold bar and the amulet row; walking by holding the button moves and scrolls the map (about 116, 120 and 153 pixels in 2 s); no slow frames with `PORT_FRAME_LOG=1` (the 60 ms frame still holds at 1024x768) |
| Encounter / ante screens | 640, 800, 1024 | drawn with the game's larger layout; "Pay N gold" and "Duel" lines hit where drawn |
| Village | 640, 800, 1024 | the five buttons, the wise man's quest, "Buy Cards" and its "Cards for Sale" page (800), food, "Leave the village" |
| Edit deck / Sell cards (the deck builder inside the game) | 640, 1024 | drawn, a card dragged from the deck to the stock |
| World map, Dungeon & Castle Clues (list, detail page), spell book | 640, 800, 1024 | drawn, hit regions right, the list's hover highlight under the mouse |
| Wiz Stats, Journal | 640, 800, 1024 | drawn at the DLL's own layout for the size; its own Done leaves to the map; the Journal's Done is flaky (see below) |
| Castle gate, castle interior (a maze), a free dungeon, "Ready to Quit?" on Escape | 1024 (the first two also 640, 800 in `castle-dungeon-stats.md`) | drawn, keys and clicks move the party, Escape leaves |
| `DECK.EXE` standalone | 640, 800, 1024 | the deck builder with its larger layout at each size, a card dragged from the stock row to the deck, Stats window |
| `DUEL.EXE` standalone | 1024 | setup dialog, Gauntlet Options, Duel Options, the Load saved game file dialog, coin toss, ante screen |
| A duel from `MAGIC.EXE` | 640, 800, 1024 | coin toss dialog, ante, the board, the phase bar, the hand list (a land played by clicking its row), the right-click menu (positions itself inside the screen) |
| Dialogs | 1024 | Duel Options, Gauntlet Options, the file dialog: the units come out the same as at 640x480 (the dialogs are drawn from templates, not from the art) |

Nothing printed "is not implemented" on stderr at any size, and nothing crashed. An 8-minute soak at 1024x768 (`tools/soak/soak.py --res 1024x768`) is in the PR text.

## The game's own behaviour at the larger sizes (not changed)

- **Card text boxes.** The ante screen's cards at 800x600 and 1024x768 print a long rules text past the bottom of the text box (the Giant Spider's: the last lines run over the artist line and
  out of the card). The text wraps by our substitute font's widths; the original used its own bitmap font. It belongs with the card-text work (`font.c`, `gdi_text.c`), which was in other hands
  at the time. `overworld.md` found the same at 1024x768.
- **The Journal's map is small and centred** at 800x600 and 1024x768 (it is drawn at the size the game draws it for 640x480), and the labels overlap each other ("Windlass Forge" under the
  entry line). The code picks the positions; not compared with the original.
- **The deck builder's labels ("Stats (36 cards)", "* Deck1 *", "Exit")** inside the game are dark grey on black at all three sizes, 640x480 too; in the standalone `DECK.EXE` they are
  readable on grey bars. Not looked into.
- **The Journal's Done button did not always answer a scripted click** (the screen's loop at 0x40b4e8; it showed in the first try and then stayed on the Journal in the next, with
  `click`, with `move` + `click` and with `down`/`up` alike). It is the same at 640x480 with the build from before this change, so it is not the size; `castle-dungeon-stats.md` had
  it working at 640x480 and 800x600 with a plain `click`. The loop sat in its redraw pass (tens of thousands of `FillRect` calls a second) and the pass that tests the button never took the press.
  Not found why; Wiz Stats' own Done (leaving to the map) worked each time. Not investigated further.
- **The coin toss movie** stays 320x240 in the middle of the screen (`video.c`); it was not played again at these sizes.

## Choosing the default

1024x768 works as well as 800x600 everywhere that was reached, costs no visible slowdown (no frame over the 60 ms period plus 15 ms while walking), and the window fits a laptop screen as
described above. It gives the larger art and the larger board; 800x600 stays available (`PORT_RES=800x600`) and 640x480 is what the original ran at.

## Not verified

- A real display, a real mouse and a resized window by hand: all of the above is the dummy video driver, with `PORT_WINDOW` standing in for a resized window.
- 800x600: the castle interior, the dungeons, `DECK.EXE` with the mouse past the first screen, and `DUEL.EXE` (`castle-dungeon-stats.md` has the castle at 800x600).
- 1024x768: winning a duel and the screens after it, the Gauntlet's next round, buying a card, the coin toss movie, a saved game loaded from the file dialog.
- The original at 800x600 and 1024x768 (no real screenshots): "right" here means no overlap, no wrong hit region and no black hole, not pixel for pixel.

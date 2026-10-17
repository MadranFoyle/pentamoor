# The deck builder's footer: dark grey on black

`resolution.md` recorded it: inside the game, the deck builder's "Stats (46 cards)", "* Deck1 *" and "Exit" were dark grey on black at all three sizes (640x480 too), while in the standalone `DECK.EXE` the same
labels read well on grey bars. It was **ours**, a rule of GDI that the port did not follow, and is fixed.

## Found

The footer buttons are owner-drawn (`BUTTON*`, style 0x5600000b) and `DECKDLL.DLL` paints them in the main window's `WM_DRAWITEM` (the function at 0x10032bd7, called from 0x100262dd). Everything it uses is a palette index,
set once at start-up (0x100254a2..0x10025502):

    brush  CreateSolidBrush(PALETTEINDEX(134))      the bar's face
    pens   CreatePen(PALETTEINDEX(193)), CreatePen(PALETTEINDEX(22))      the light and dark edges
    text   SetTextColor(PALETTEINDEX(1))            (PALETTEINDEX(191) for the button that has the focus)

and the paint does `SelectPalette(hdc, DLL's palette)`, `RealizePalette`, then fills and draws. The DLL's logical palette (loaded from `DUEL.plogpal`) has entry 1 = (28,24,26), entry 134 = (142,143,144), entry 193 = (203,203,203),
entry 22 = (78,78,79), entry 191 = (254,254,254) (read from the port with a temporary print): near-black text on a grey bar with light and dark edges.

A palette-index colour means the entry of the palette **of the device context it is drawn with**, at the time it is drawn. `gdi.c` resolved it when the brush or pen was made (`colorref_rgb(NULL, ...)`, against the system
palette of that moment) and kept the RGB. In the game the brush and the pens are made before the DLL's palette is realized, and entries 134, 193 and 22 of the palette then in the system came out (0,0,0): a black bar,
no edges, and the text (resolved when it is drawn, correctly) near-black on it, so "dark grey on black". The standalone `DECK.EXE` makes the same objects, but with the DLL's own palette already in the system, so it looked right.

## The change (`gdi.c`, `gdi_text.c`, `gdi_int.h`)

A brush or pen made from a palette index keeps the COLORREF and a flag (`Brush.cref/rel`, `Pen.cref/rel`). Its RGB is worked out again from the DC's palette when the object is selected into the DC (`SelectObject`), when the
DC's palette changes (`SelectPalette`: `dc_resolve_tools`), and when a brush is named by a call that draws with it (`FillRect`, `FrameRect`, the answer to a `WM_CTLCOLOR...`). RGB and `PALETTERGB` colours are
untouched. `test_gdi` +4 checks (`test_palette_relative_tools`: a brush made before any palette is on the DC draws entry 1 of whichever palette the DC has, also after the palette is changed with the tools selected).

## Checked

The deck builder in the game from the map (F1) at 640x480 and 1024x768, and the standalone `DECK.EXE` at 640x480: the bars are grey with their edges and the labels are legible. Screens elsewhere that use palette-index
brushes or pens were not compared one by one (the duel board, the shops and the map use RGB or the game's own drawing); the checks of `screen_nav_play.py` pass as before.
Not checked against the original (the Windows 98 VM): the colours follow from the DLL's palette file and the rule above, not from a screenshot of the original.

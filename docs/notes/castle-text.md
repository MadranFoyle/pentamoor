# Card text in the castle panels at 640x480: partly the original, partly our renderer

`castle-dungeon-stats.md` noted that the card in a castle's panel (the wizard's rule card, "Crystal Rod in effect.") has mushy text at 640x480 and asked whether
that is the original. Checked by reading what the lifted code asks of GDI and by comparing with a screenshot of the original (the Windows 98 oracle VM was not
running and was not booted; the comparison is `sources/oracle/probe_duel_start.png`, a 640x480 shot of the original's "Start of duel" dialog, which draws a card
with the same code at nearly the same size).

## How the text gets there

The game draws a card face into a memory DC and stretches it where it is wanted. The rule text is not drawn as lines: every **word and every space is its own
`TextOut`**, placed at a logical x that the game advances by the width `GetTextExtentPoint` returned. Logged with a temporary print in `draw_text_at` (not kept):

    face "MPZurich Cn BT" (TT0298M_.TTF), logical height 14, mapping scale 0.747 (castle panel: the card is 146 pixels wide, 195 logical)
    -> device cell 10.46 pixels, em 8.64, whole-pixel advances
    'when' at 28, ' ' at 52, 'a' at 54, ' ' at 59, 'white' at 61, ' ' at 85, 'spell' at 87 ...

So a space is 2 logical units (the extent of one space, 2 device pixels, divided by 0.747 and truncated to a whole logical unit), which is 1.5 device pixels. The
words run together ("abilityonly", "castand") because the text is that small and its spaces that narrow, whatever the renderer does. At 800x600 the card is drawn
bigger (the earlier note saw it clean there; its mapping scale was not logged), so the same extents make wider spaces.

## What the original looks like

In the original's screenshot of an ante card at 640x480 the text is **the same compressed**: "hassummoning sickness", "turn" reads as "tum", and "Raiders" begins with a letter that looks like an A.
The words are not better separated there. What differs is the rendering: Windows 98 draws this text with the font's own hinting and **no smoothing**, so every stroke
is a solid black one-pixel line. Our rasterizer (`font.c`) is exact-area coverage of the unhinted outline at a fractional em: a stem 0.8 pixels wide comes out as a
grey of at most 80%, spread over two pixels when it straddles a boundary, and the card text looked pale and smeared.

## The change

`text_coverage` (`gdi_text.c`) doubles the coverage of glyph pixels for text drawn at an em of 10 pixels or less (saturating at 255), fading the gain out to nothing at
14 pixels, so bigger text is unchanged. It is used for the game's own `TextOut`/`DrawText` text (`draw_text_at`); the dialog and control text (`ui_text_draw`) has its
own path and was not touched. `test_gdi` checks the gain at both ends and in the taper (44 checks).

Before: the castle card's text ("Gain 1 life. Use this ability only when a blue spell is successfully cast and only once for each such spell.") was dark grey on
a pale parchment, letters blurred into the next. After: black strokes of one to two pixels, the glyphs separate, the words still touch where the game's spacing puts
them 1.5 pixels apart. Screenshots were taken with the `PORT_CONTROL` recipe of `castle-dungeon-stats.md` (castle at 640x480, "Yes, enter the castle").

## Not done, not known

- **Hinting.** The original's letters are cleaner than anything an unhinted outline gives (a threshold instead of a gain was tried on the same words: stems
  merged and counters filled, worse). A TrueType bytecode interpreter would be the real answer; not attempted.
- **The em.** The original's line "At the end of your turn, Erg" is about 85 pixels wide in its screenshot, ours about 80 at em 8.64 (the card there is 141 pixels
  wide, so the scale is about 0.72; that scale and the widths are read off a zoomed screenshot, not logged). A whole ppem of 9 would match the width. `resolve`
  (`gdi_text.c`) keeps the em fractional for the game's own fonts and floors it for the stand-ins; what Windows picks for a cell height of 10 pixels was not measured.
- **The width of a space.** Whether Windows' `GetTextExtentPoint` result is converted to logical units by truncation (as here) or rounding is not known; rounding would
  make the space 3 logical units, 2.2 pixels, and the words a little farther apart.
- **Fire Elemental's long text on the 640x480 ante screen** runs past the bottom of its text box (seven lines; the box holds six). The wrapping is the game's, from the
  same extents, so it may be the original's too; not compared.
- The Windows 98 VM was not running; the comparison is one screenshot of another card. A same-card check (a castle's rule card on the original at 640x480) would settle
  the em and the spaces.

## Settled since (`card-text-metrics.md`)

The questions above were answered by measuring the original in the Windows 98 VM: the card font is **8 ppem** (a whole number, not 8.64), a space is **3** logical units (the extents round to the nearest unit; the port
truncated), GDI applies **no kerning**, the card's MM_ISOTROPIC mapping is cut to **149 x 224** (x scale 0.745), the line pitch is `tmHeight` **13** (the port said 14). With those the words wrap where the original
wraps them and Fire Elemental's seven lines fit the box at 640x480. What stays: the original's hinted glyph shapes (a TrueType bytecode interpreter), and the sizes other than 640x480, which have no reference.


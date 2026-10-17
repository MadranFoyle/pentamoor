# Card text: measuring and wrapping like the original

`castle-text.md` and `resolution.md` left two things open: long rules text ran past the text box of a card (the ante screens at 800x600 and 1024x768, the castle's panel, Fire Elemental even at 640x480), and
the port's em for the card font (8.64) and the width of a space (2 logical units) were guesses. The game wraps card text itself, by the widths `GetTextExtentPoint32` returns for each word, so the fix is to
make those numbers, and the metrics the game reads, the original's. They were measured in the original.

## Measured (the Windows 98 VM of `docs/ORACLE_VM.md`, 640x480, the saved game: three ante cards)

`tools/verification_harness/probe_card_text.py` puts breakpoints on the card text routine of `MAGIC.EXE` (the word layout's three `GetTextExtentPoint32A` calls, its `GetTextMetricsA` calls, the font creation)
and logs, for each word and each space the layout measures, the arguments and the `SIZE` it got back; the guest ran meanwhile (walk on the map until a monster comes, the ante screen draws the two cards).
Three cards gave 53 distinct strings ("Gain", "successfully", "player,", " " ...), every one measured at 640x480. What the game does around them (from the code): the card is drawn into a memory DC with
`SetMapMode(MM_ISOTROPIC)`, window 200 x 300, viewport 160 x 224 (`SetWindowExtEx` at 0x49c839, `SetViewportExtEx` at 0x49c85e), with a `LOGFONT` of height 14 and the face "MPZurich Cn BT"
(`TT0298M_.TTF`); every word and every space is its own `TextOut`, placed at a logical x that the game advances by the extent it measured, and a word that would pass the box's right edge starts a line; the
line pitch is the font's `tmHeight`.

`tools/research/cardtextfit.py` tries the guesses against the 53 strings (the font's `hmtx` advances, its `kern` table, the card's scale). **Exactly one fits all 53**:

| | the original | the port was |
|---|---|---|
| size | **8 ppem**, a whole number: a cell of 10 device pixels (14 x 0.7467 = 10.46) is the largest hinted cell of the font that fits | 8.64, a fraction (the height scaled to fill the cell) |
| a glyph's advance | `round(advance * ppem / 2048)`, each glyph to a whole pixel | the same |
| kerning | **none**: GDI does not apply the font's `kern` table to what a program measures or draws (with it one of the 53 is wrong) | applied |
| device width to logical units | **to the nearest unit**: a space of 2 pixels is 3, "Gain" of 15 is 20 | truncated: a space 2 |
| the card's scale | MM_ISOTROPIC cuts the viewport's x so that both axes have one scale: 224 * 200 / 300 = 149, so x is 149 / 200 = **0.745** (y stays 224 / 300) | 0.7467 both (the smaller of 0.8 and 0.7467, not cut to whole units) |
| the extent's height `cy` | **13** (= `tmHeight`, below) | 14 (the `LOGFONT`'s height) |
| `GetTextMetrics` | height 13, ascent 10, descent 2, internal leading 2, external leading 0, average width 4 (logical) | 14, 11, 3, 0, 0, 5 |

The metrics are the hinted cell, ascent and descent each rounded to a whole pixel (8 and 2 at 8 ppem: `ttf_cell`), the internal leading the cell less the em (2), the average width the OS/2 table's
`xAvgCharWidth` (778 of 2048: 3 pixels), each divided by the scale and **truncated** (13.4, 10.7 and 2.7 became 13, 10 and 2: the extents round and the metrics truncate). With the old numbers a space was 2
and a word of 20 pixels measured 17: lines held more words than the original's and each line took 14 units of the box, not 13; both made a text box too full, whichever way the box was drawn.

## The change

- `gdi.c`, `rescale`: MM_ISOTROPIC fits the extents as Windows does, in whole units (the viewport extent of the axis with the larger scale is cut to the other's proportion, integer quotient).
- `gdi_text.c`: `resolve` makes the game's own TrueType fonts whole-pixel sizes: the height in device pixels (lfHeight times the vertical scale, to the nearest pixel) is the em for a negative height, the cell for a
  positive one, and the em is then the largest ppem whose hinted cell is not taller (`font_ppem_for_cell`); `text_width` sums the glyphs' advances with no kerning and divides by the scale to the nearest unit, and
  returns the logical `tmHeight` as the height; `GetTextMetricsA` answers as above for the game's own fonts (stand-in fonts and the dialogs' text, `ui_*`, are as they were); `draw_text_at` lays glyphs out with
  no kerning, the way the width was measured.
- `font.c`: `ttf_cell` (the cell Windows reports) and `ttf_avg_width`.

`test_gdi` (`test_card_text_metrics`, 3 checks and the table) runs when the game's font is there (`sources/installed/Magic/Program/TT0298M_.TTF`): the 53 strings of the original on the card's mapping, the
extent's height, the `TEXTMETRIC`, and the ppem for a few cell heights. Without the font it prints that it skipped them. The ppem rule is checked there too (cells of 10, 11, 12, 16 and 1).

## Seen

640x480, the ante screen of the port with Giant Strength, and the original's with the same card: the same six lines, broken at the same words ("Enchanted creature gets +2/+2." / "'O! it is excellent / To have a" /
"giant's strength, but it is tyrannous" / "/ To use it like a giant.' ---William" / "Shakespeare, Measure for" / "Measure"), at the same height in the box. Fire Elemental, the card that ran past the box at 640x480
(seven lines in the old widths) is seven lines inside the box now; at 800x600 (Diabolic Machine, Manabarbs) and 1024x768 (Giant Strength, Winds of Change with its nine lines) every line of every card is inside its box, and the castle's panel at 640x480 reads "All swamps are 1/1 creatures. (These creatures still count as lands.)" with the words apart.

## What is not known, not done

- **800x600 and 1024x768 have no reference**: the VM runs at 640x480, so the ppem rule was checked at one point (a cell of 10 is 8 ppem). The rule is the largest ppem whose hinted cell fits, with the ascent and descent
  rounded (the evidence for rounding is `tmAscent` of the dialog font in `dialogs.md`); if Windows rounds them up instead, the sizes differ at 1024x768 (14 ppem against 13 for lfHeight 14) and the widths there by about 7%.
  Setting the VM's display to 800x600 (the Cirrus card does it) and running `probe_card_text.py` again would settle it.
- **Hinting.** The original's glyphs at 8 ppem are hinted bitmaps (solid, clunky: its "a" and "e" are not the outline's); ours are the unhinted outline at the same size, with the coverage gain of `castle-text.md`. The
  letters differ, the line breaks, widths and heights do not.
- The old report that the Giant Spider's last lines ran over the artist line at 800x600 and 1024x768 was not reproduced with that card (it did not come up); the cause above is what the numbers say, and every other long
  card looked at fits.
- `GetCharWidthA` and `GetCharABCWidthsA` (the mana symbols' widths) still answer per character with `text_width`: the rounding is now to the nearest unit as for extents; the original's values were not measured.
- The dialogs' own text (`ui_text_width`, `ui_font_metrics`) keeps its kerning and its metrics: it was calibrated against the real dialogs (`dialogs.md`) and is a different path.
- The deck builder's full-size card (`MagicFullCardClass`, the DLL's own drawing through the same GDI calls) still ends Cave People's rules text at the bottom of the box after "(If defending player controls any"; it did
  before the change and was not compared with the original.


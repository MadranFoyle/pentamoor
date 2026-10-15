# Black lines in the ante cards' text boxes (1024x768)

Seen at 1024x768 on the encounter ("ante") screen: one or two horizontal black lines through the text box of a card (depends on the card; several
of six random draws showed it). 640x480 and 800x600 did not.

Cause: `StretchBlt` of the text box, `(16,196) 195x104` of the card art to `162x113` (PORT_BLITLOG shows it). Narrower but taller, so
`gdi_blit` takes the "shrinking" path, `box_resize`. In the vertical direction (scale 104/113 < 1, an upscale) the box has a support of one source
row; when the destination row's centre lands exactly on a source row's edge (row 56 here) the half-open interval `[-0.5, 0.5)` holds no source
row, the weight sum is 0 and the output row was written as 0, black. Same in the horizontal pass.

Fix: `box_resize` (now `gdi_box_resize`) takes the nearest source pixel when no pixel is inside the box. Unit test `test_box_resize_no_gaps`
in `src/port/test_gdi.c`. Checked with six runs at 1024x768 after the fix: no black rows in either card.

`PORT_BLITLOG=1` now also prints the source size of a StretchBlt.

# "Sorcerer casts..." black panel at 640x480

Not found in the time given. A script that resumed the saved game, started the Sorcerer duel and pressed Return reached the duel board but did not
get to the dialog within 80 s; the dialog needs the AI to cast a spell. Next step: play to the Sorcerer's first spell, dump the dialog's child
windows (`windows`) and look for a static control with a bitmap or an owner-draw control that `controls.c` paints as black.

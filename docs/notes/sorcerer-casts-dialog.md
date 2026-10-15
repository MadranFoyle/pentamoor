# "Sorcerer casts..." showed a black panel

When the opponent AI casts a spell, the duel shows a modal dialog with the spell's card on the left and the caster's name ("Sorcerer casts...") on the
right. The right half was a plain black rectangle (640x480, and the same at 800x600 and 1024x768).

## What the dialog is

- `DialogBoxParam` **template 223** (the coin-toss template: one control), dialog procedure `0x00401000`. In the window tree (`PORT_CONTROL windows`) it is
  a top-level-looking `#32770` (44,38)-(596,441 at 640x480) with one child, class `MAGICGAME_BigCardChoiceClass`, title `Sorcerer casts...`, at
  (323,56)-(578,289). The card on the left is painted by the dialog itself (`WM_ERASEBKGND`: the `WINBK_BigCard.pic` parchment and the card picture).
- The child's window procedure is `0x00401f70` (`RegisterClassA(magicgame_bigcardchoiceclass)`, 20 bytes per window). Its `WM_ERASEBKGND` handler
  (`0x4020e6`) is `mov eax, 1; jmp end`: it **says "erased" and draws nothing**. Its `WM_PAINT` handler (`0x4026a8`) does `BeginPaint`, `SetBkMode(TRANSPARENT)`,
  and draws the window text with `DrawText`: a shadow pass (offset by one pixel, colour `0x10000c9`) and a text pass (`0x1000097`), then the card's rules
  text under it. The window has no background of its own; it relies on the parent's picture showing through, as a child window does on a real screen
  (a child shares its parent's pixels: whatever it does not draw is the parent's).

## What was wrong in the port

Every window with a procedure has its own surface in `compose.c`, drawn opaque over its parent, and a new surface is black. A window that answers
`WM_ERASEBKGND` with 1 and then draws only text therefore became a black rectangle with text on it. (The text itself was drawn through `get_region` /
`put_region`, which wrote the whole text rectangle back, so even a window known to be transparent would have shown a black box round each line.)

## Fix

- `gdi_send_erase` (gdi.c) sends `WM_ERASEBKGND` and counts how often the procedure used the device context (`DC.uses`, bumped by `dc_of`). An answer of
  "erased" from a procedure that never touched its DC marks the window `see_through` (wm.h). A procedure that erases by drawing, even with black, is
  opaque as before. All three places that send `WM_ERASEBKGND` (the message pump, `BeginPaint`, `DefWindowProc`) use it.
- `compose.c` composes a `see_through` window with a mask: only pixels that were drawn (`Surface.touched`, set by the two write paths of a window surface,
  `put_region` and the index writer) cover the parent. (Palette index 0 cannot mean "not drawn": the game fills with black.)
- `draw_text_at` (gdi_text.c) writes only the glyph pixels to a `see_through` window (`put_region_masked`), not the whole rectangle.
- Unit test `test_see_through_child` in `src/port/test_wm.c`: a ghost child (erase answers 1 without a DC call) shows the parent's colour where it drew
  nothing and its own pixel where it drew; a child that erases by drawing black stays opaque.

Anti-aliased glyph edges are blended with the surface's black (there is no coverage channel), so the text has a thin dark fringe; with the game's
shadow pass it reads as the intended shadow.

## Recipe: getting the dialog on screen

No saved-game surgery is needed; the AI casts a spell within the first few turns of the Sorcerer duel.

1. `ln -s <main checkout>/sources sources`, build, then start the game as `tools/soak/pentamoor_ctl.py` does (dummy video and audio drivers, own fifo,
   own copy of `sources/emu_overlay`).
2. Title screen: click "Resume Game" (640: 330,390; 800: 412,487; 1024: 528,624), wait about 9 s; ante screen: click "Duel a Sorcerer" (640: 290,325;
   800: 360,388; 1024: 470,486). Click through the coin toss / mulligan dialogs (the soak's `start_duel_from_ante`).
3. Play with the soak policy (`Soak.tick`: lands, Done at every phase, pay prompts, discard prompts). The first Sorcerer spell shows up after 15 to 40
   seconds (about the 4th to 8th turn pass).
4. Poll `windows` every second. The dialog is there when a visible `MAGICGAME_BigCardChoiceClass` titled `... casts...` exists (the dialog is not the one
   whose own title says it: its title is empty, the title is on the child). **Stop sending Return before looking**: the soak policy presses Return on
   every dialog, and the dialog is gone after a few seconds anyway (there is no button; Return or a timer ends it). Send `shot <file.ppm>` the moment it
   is seen. Trace with `PORT_TRACE=1` (the `DialogBoxParam` line names template 223 and proc 0x401000).

`python3 tools/soak/casts_dialog.py 800x600 /tmp/casts-800` does all of this (about 25 lines on top of `tools/soak/soak.py`): it stops at the dialog,
writes `<workdir>/casts.png`, prints the game's pid and leaves the game running (kill that pid). It took 40 to 100 seconds at each resolution (the
spell the AI casts differs from run to run; the soak policy's random choices do not change what the Sorcerer does first).

## Checked

Screenshots of the dialog at 640x480, 800x600 and 1024x768 after the fix: the parchment shows on the right half with "Sorcerer casts..." in the
shadowed gold text, and where the spell has a target its card (Ali Baba at 1024x768) is drawn on the parchment, which the black panel had hidden
too. The same window class shows "Sorcerer activates..." for an ability (seen in a 1024x768 run); it is the same code path. `make -C src/port test` passes
(123 checks in test_wm).

The rule is general, so it also marks other windows: the `PORT_TRACE` line "answered WM_ERASEBKGND without drawing: see-through" names them. In a duel up to
the dialog: `ShandalarMainClass`, `MAGICGAME_MainClass`, the full-size card, both life, graveyard and library windows, both hands, both scroll bars and the
BigCardChoice window. To make sure that changes nothing for them, a temporary build composed each frame twice, with and without the rule: on the
duel board (640x480, a frame with no dialog) 0 pixels differed; in the frames with the dialog the only differing pixels were inside the dialog's
child window (about 58,800 of its 255 x 233).

Not verified: no reference screenshot of the real dialog exists, so the text's thin dark fringe (above) and the exact text placement are as the
game's own code draws them through our text renderer, not compared with Windows 98.

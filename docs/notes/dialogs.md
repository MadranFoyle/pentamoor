# Dialog metrics: what the real Windows 98 does

Notes from checking `ui.c`, `controls.c`, `gdi_text.c` and `font.c` against the original running in the Windows 98 oracle VM
([ORACLE_VM.md](../ORACLE_VM.md)). The reference is a real screenshot of the setup dialog of `DUEL.EXE` (template 231) and of the deck
builder's Stats window, taken by running `C:\Magic\Program\DUEL.EXE` and `DECK.EXE` from the Start menu's Run box (`base_duel.raw` starts
`DUEL.EXE` with arguments that skip the setup dialog, so kill that one with Ctrl+Alt+Del / End Task first; a second `DUEL.EXE` exits at once).
The screenshots are not in the repository (they show the game's art).

## The templates

All 29 templates (`DialogBoxParam` ids; 22 in `MAGIC.EXE` and again in `DUEL.EXE`, 7 in `DECKDLL.DLL`, 1 in `STATWIN.DLL`) have position 0, 0 and
`DS_SETFONT`. Fonts: Benguiat Bk BT at 10 points (most), 12 points (coin toss 223, 235, 246; Deck Info 197 and Stats 198), 16 points (243, 249); MS Sans
Serif 8 for 224 (Browse), 226, 233 (ShowList) and `STATWIN.DLL` 101. Benguiat Bk BT is `TT0127M_.TTF` (a bold face, one style only). Template 226 and the
ones from 230 to 232 and 239 are written as extended templates (`DLGTEMPLATEEX`, signature `0001 FFFF`); the old parser in `controls.c` already reads both.
The setup dialog the task called "Pick a deck:" has no colon: it is the radio button "Pick a deck" (51 x 10 units) next to the combo box at x = 73.

## What was wrong, and the real rules

Measured on the real setup dialog (template 231, 281 x 213 units, border style, no caption): the outer window is 564 x 401 pixels, so the client area is
562 x 399 inside a one-pixel border. That is **8 x 15 pixels per unit** (281 * 8 / 4 = 562, 213 * 15 / 8 = 399.4). We had 7 x 16 before, which is why
the radio button was 89 pixels wide and its Benguiat text ran under the combo box.

- **Horizontal unit: not xAvgCharWidth.** The OS/2 table says 1071 / 2048 em = 6.97 pixels at 13 pixels, so 7. Windows gets 8: it measures the 52 letters
  a-z, A-Z and takes `(sum / 26 + 1) / 2` (whole-pixel advances: 428 pixels, 428 / 26 = 16, (16 + 1) / 2 = 8). This is the documented rule for proportional
  fonts, and it is why MS Sans Serif 8 (tmAveCharWidth 5) has the familiar 6 pixels per unit and the 75 x 23 button of 50 x 14 units.
  `ttf_text_metrics` (font.c) does it now.
- **The font's size is whole pixels: `-MulDiv(points, 96, 72)`.** 10 points is 13 pixels, not 13.33; 12 is 16, 16 is 21, 8 is 11 (`ui_pixel_size`). At 13.33
  the cell height would round to 16; real is 15: `round(ascent) + round(descent)` = 12 + 3 at 13 pixels (hhea 1964 and 516 of 2048).
- **Vertical unit** is that height (15). Unchanged rule, new em.
- **Units round, they do not truncate** (`MulDiv`): the real combo boxes at y = 82 and 139 units are 154 and 261 pixels down (153.75 and 260.6); truncating
  put them a pixel high. `ui_dlu_x` / `ui_dlu_y`.
- **Where the dialog goes.** A template at 0, 0 is centred, and a dialog bigger than the screen is moved so its top left corner stays visible
  (the real Stats window is at 0, 0 and runs off the right edge). It is also a popup, so its position is the screen's: `wm_abs_rect` used to add the
  owner's position and border (the game's window is at 1, 0), which put every dialog a pixel to the right.
  Not copied: Windows centres in the work area (the screen less the taskbar, 452 pixels high here, so the real dialog is 14 pixels higher than ours).
- **Baseline.** The text sits on `tmAscent` = the rounded ascent (12 at 13 pixels); a ceiling (13) put every label a pixel low. A check box or radio
  button's text is centred one pixel above the middle of its rectangle (`(h - cell - 2) / 2`: the real radio buttons of 19 and 23 pixels have it at 1 and 3).
- **WM_SETFONT / WM_GETFONT.** Windows creates the dialog's font and sets it on every control; the game's own button painting asks the control for it with
  `WM_GETFONT` (0x31) and draws "Create Deck...", "OK" and the rest in it. We answered 0, so the owner-drawn buttons were Arial; they are Benguiat now.
- **The stand-in for MS Sans Serif.** The real one is a bitmap font, 13 pixels high at 8 points, as wide as Arial at 10 pixels (the Run dialog's
  56-character sentence is 272 pixels; Arial at 10 gives 270, at 11 gives 281). We used 0.88 of 10.67 (9.4) which ran about 8% narrow.
- **A positive `lfHeight` is the cell, not the em.** A font made with `CreateFont(30, ...)` for a face we do not have (the Stats table's labels ask for
  "Cheltenham ITC BT" at a height of 30 among others) is the largest whole ppem whose ascent plus descent fits, about 0.89 of it for Arial; we took 0.75, 17% too small.
  A negative height is the em itself. With the dialog 270 units wide at 12 points (10 x 19 pixels per unit: 675 x 425) the Stats columns are 72 pixels apart
  as in the real window (real: 128, 199, 271, 343, 416, 488, 560; ours: 137, 208, 279, 350, 421, 492, 563) and "Colorless" / "Total" no longer touch.

Group boxes keep the face-coloured strip behind their label even over artwork (real: "Game" in the setup dialog sits on a grey patch).

## Not done, not verified

- The real display is 8-bit: a colour such as the face grey 192,192,192 comes out as the nearest palette entry (176,168,144 in the setup dialog's
  group-box label). We draw true colours.
- The Stats table's face. Windows 98 had no "Cheltenham ITC BT" either; what it picked is not known (the labels measured 62, 53, 82 and 85 pixels for
  "Card Type", "Colorless", "Non-Creature", "Mana Sources": Arial at 13 gives 60, 54, 76, 84). Our stand-in is Arial a little too large.
- The other dialogs (Select Active Artist, Load deck, Casting Cost, Deck Info, the coin toss, ...) were not compared with real screenshots, only checked
  for text that no longer clips with the new units. Deck Info (267 units at 12 points = 667 pixels) is wider than the screen, as the Stats window is.
- The `1` after "DIFFICULTY:" has a grey patch behind it in the real dialog; ours is transparent.
- Owner-drawn button labels are two or three pixels lower than the real ones (the game computes that position itself from `GetTextMetrics`).
- No real screenshots of Windows 98 at 800x600 or 1024x768, where the same rules apply with different layouts.

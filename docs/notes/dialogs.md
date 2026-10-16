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

## Message boxes (`MessageBoxA`) and the "(Y/N)" questions

Findings of the session that fixed "can't say Y or N to the buy cards dialog" (macOS arm64, dummy SDL drivers, 1024x768, a new game, the village poked to, `PORT_CONTROL`).
Code: `src/port/msgbox.c`, `yesno.c`; tests `test_msgbox` and `test_yesno` in `test_wm.c`.

### What the Buy Cards question is

Not a dialog, not a message box. In a village, `Buy Cards` opens "Cards for Sale" (four cards with prices, drawn by the game); a click on a card draws the card large with **"Buy for 20 gold?   (Y/N)"**
over it (text at 0x5322d0 in `MAGIC.EXE`). No window exists then (the `windows` dump shows only the desktop and the main window), and `MessageBox:` is not logged. The game sits in its wait-for-key
function 0x48ac2f (a loop of polls of its own key queue, 0x4080b2) and takes `y` or `Y` as yes and **any other key as no** (the caller, 0x509e45 to 0x509f4c). So:

- the keyboard works (`key y` from the control pipe: gold 5000 -> 4980, the card gone, the deck 36 -> 37 cards; real keys arrive the same way as typed names do);
- a mouse click does nothing, and a controller has no Y key (its Y button is a double click, X is Enter, which is "no"): the screen could not be left, which is the bug.

There are three such questions in `MAGIC.EXE` (the other two are "Sell <card> for N gold? (Y/N)" at 0x4f1569, `y` only, and "Take <card>     (Y/N)" at 0x451198, `y` or `Y`); the other two were not reached
(the deck editor's sell is a popup menu "Sell Card for 10" that sells at once, and the "Take" one is in a function called from about 25 places of the duel and shop code).

### The fix

`yesno.c` hooks the wait-for-key function (entry: is the caller one of the three return addresses 0x509e4a, 0x4f156e, 0x45119d) and its poll (each poll inside the loop notes the time). While the game
has polled in the last 200 ms for one of those three, `front.c` turns a left press into the key `y` and a right press into `n` (the release is dropped, and the press that answered ends the question, so
the second click of a double click is the game's again), and `compose.c` draws "Y or left click (A): yes   N or right click (B): no" at the bottom. The controller needs nothing of its own: A and B
are the left and right buttons. Checked: left press -> bought (5000 -> 4990), right press -> declined, the hint on screen only while the question is up, `key y` still buys.

### MessageBoxA

Every call used to log `MessageBox: caption: text -> IDOK` and return 1 without showing anything, which is neither `IDYES` (6) nor `IDNO` (7). Who calls it (`MessageBoxA` import, found in the machine code;
types are `uType`):

| program | where | box |
| --- | --- | --- |
| `DECKDLL.DLL` | 0x10024ffd, 0x100278a5 | **YESNOCANCEL, question icon**, "Deck Builder"/"Deck Maker": "Do you wish to save C:\MAGIC\PROGRAM\PlayDeck\new.dck?" (leaving the standalone deck builder after a change; nothing asked it before: the answer was IDOK) |
| `DECKDLL.DLL` | 0x10024ee0, 0x10024f12, 0x10024f4f, 0x10025073, 0x100250a4 | OK + info: "You must name your deck before saving.", "Your deck must have at least 40 cards to be used in the duel.", "Your deck has too many cards. ...", errors |
| `DECKDLL.DLL` | 0x10024d9b, 0x10024db6, 0x10024e65, 0x1002549c, 0x100171d3..0x10017aea, 0x1003cda4 | OK: "Checking deck for legal cards", "All cards are in 4th edition", "Card Error", "Could not create CARDID.TXT", "Stats Error" |
| `DECKDLL.DLL` | five "Couldn't bring up the ... dialog box", the memory warning, two "Assertion Error" (system modal), 0x100129b7 | OK: error paths |
| `MAGIC.EXE` | 0x4437a8 | OK + exclamation: "Not enough system memory to run at this screen resolution. ..." |
| `MAGIC.EXE` | 0x495943, 0x4f2ebc, 0x500ff5, 0x443319 | OK: "Duel couldn't run", "Couldn't bring up the Load Decks dialog", "Couldn't register the classes", "These big arts are in:" |
| `MAGIC.EXE` | 0x501987, 0x501ab7 | OK, system modal: "Assertion Error" (+ "Please call MPS Customer Support") |
| `MAGIC.EXE` | 0x4424ed | **YESNO**, "End of duel": "Congratulations!" / "Too bad" / "Oh well..." (by the duel's result 1, 0, -1) + "Want to play again?"; in the window procedure that waits on a child duel process (WaitForSingleObject, 0x4423e9) and on IDYES sends itself a message to start again. Not met in play (duels run inside the process here); IDOK was never "yes" |
| `DUEL.EXE` | 0x49bf21..0x49c192 | OK + error: "Duel Error": "Your selected deck is not a legal deck. Please select a new deck." and six more, "Couldn't bring up the dialog box", "Load saved game: Couldn't load the save game; corrupt file or from a different version" |
| `DUEL.EXE` | 0x4b383d | YESNO "End of duel", the same code as in `MAGIC.EXE`; the others as in `MAGIC.EXE` |
| `STATWIN.DLL`, `MAGVID.DLL` | 0x1000a407, 0x10008d97, 0x10002cbb | "KPlay error: Not a Windows DIB.", "GetLastError" |

Only the deck builder's save question and the "must name your deck" / "40 cards" notices are met in play; the rest are error paths.

`msgbox.c` builds the box as a modal dialog in code (as `filedlg.c` and `winhelp.c`): MS Sans Serif 8, centred on the screen, caption in the title bar, an icon of 32 x 32 drawn by `ui.c`
(a `?` in a blue disc, a `!` in a yellow triangle, a white cross in a red disc, an `i` in a blue disc; no icon when the style has none), the text word-wrapped to at most 55% of the screen width (240 to 520
pixels; the box is as wide as the longest line, the buttons or the caption need), 75 x 23 pixel buttons 9 apart, centred. `MB_OK`, `OKCANCEL`, `ABORTRETRYIGNORE`, `YESNOCANCEL`, `YESNO`, `RETRYCANCEL`
with `MB_DEFBUTTON1` to 3 (a default that is not there is the first button; `MB_SYSTEMMODAL`, `MB_TOPMOST` and the rest are ignored) return `IDOK`, `IDCANCEL`, `IDABORT`, `IDRETRY`, `IDIGNORE`, `IDYES`, `IDNO`.
Keys (Windows's rules): Enter and Space press the focused button (the default one at first; Tab, Right and Down move it on, Left and Up back; the focused one is drawn as the default button), a letter
underlined on a button presses it (`&Yes`, `&No`, `&Abort`, `&Retry`, `&Ignore`; case does not matter; a key with no character counts as its letter), **Esc is IDCANCEL if there is a Cancel button, IDOK for
a lone OK, and nothing for Yes/No and Abort/Retry/Ignore** (the close box the same). The box's dialog procedure reads Enter and Esc itself (`own_keys` in `Window`), because the dialog manager's
"Enter is IDOK" would press OK on `MB_DEFBUTTON2`. A close box that does nothing must still answer `WM_CLOSE` as handled: the default turns it into `DestroyWindow` under the loop that waits.
Mouse: the buttons are ordinary push buttons. Controller: the D-pad's dialog mode finds the push buttons (checked in `DECK.EXE`: `pad nav` lists `&Yes`, `&No`, `Cancel`; left, then A, answered IDNO),
X and Start are Enter, Back is Esc.

**Unattended runs.** A run that nobody can answer would hang in the box. `PORT_MSGBOX=auto` (the default when `PORT_CONTROL`, `PORT_SCRIPT` or `PORT_HEADLESS` is set or `SDL_VIDEODRIVER=dummy`) shows nothing
and returns the default button's id (IDOK for `MB_OK`, IDYES for `MB_YESNO`, IDCANCEL for `MB_YESNOCANCEL | MB_DEFBUTTON3`, ...), logging `MessageBox: caption: text -> IDYES`; `ask` shows the box (a `PORT_CONTROL`
session that wants to see one sets `PORT_MSGBOX=ask`, and the log line ends in `(answered)`).

Checked in the real programs (`DECK.EXE`, standalone, `PORT_MSGBOX=ask`): the YESNOCANCEL box looked right (icon, wrapped text, three buttons, `Yes` default with the heavier border); Esc -> IDCANCEL and
the program stayed; Tab then Enter -> IDNO (the program left); `pad press left`, `pad press a` -> IDNO; `y` -> IDYES, which saved and showed the "You must name your deck before saving." info box; with no
`PORT_MSGBOX` under `PORT_CONTROL` the same call logged `-> IDYES` and showed nothing. **Not checked:** the box at 640x480 and 800x600, in `MAGIC.EXE` and `DUEL.EXE` (no path to one of their errors was
found without breaking the game), with a real mouse, keyboard or controller (all input here was the control pipe), on Windows, the Sell and Take "(Y/N)" questions, and against a real Windows 98 box
(sizes and spacing follow its look, not measured). A message box is modal and the game waits behind it, which it also did on Windows.

## Enter in a dialog with nothing to press: the "You won!" screen

In the original **a click closes the "You won!" dialog and Return does not** (`duel-won-black-screen.md`: 70 s unchanged, twice); in the port Return closed it too. The reading of its procedure
(MAGIC.EXE 0x4ae995, template 246, opened by `DialogBoxParamA` at 0x4ae895) explains both. The template has five statics and two owner-drawn buttons ("&Next round" 0x493, "&Quit Gauntlet" 0x494); for a duel
that is not a Gauntlet's the initialisation hides both buttons and returns 0 (it sets no focus). The procedure closes the dialog (`EndDialog`) on:

- `WM_LBUTTONDOWN` (it starts a move of the window by `WM_SYSCOMMAND` 0xF012 and ends the dialog if the window did not move more than 5 pixels: a click),
- `WM_CHAR` for 13, 32 and 27,
- `WM_COMMAND` 0x493, 0x494 and 2 (IDCANCEL),

and answers `WM_COMMAND` with IDOK (1) with a plain "handled". Windows runs every key of a modal dialog through the dialog manager (`IsDialogMessage`): Enter with no default push button (no `DM_SETDEFID`
here) and no control to press is sent to the procedure as `WM_COMMAND` with IDOK, and **no `WM_CHAR` 13 is delivered**; Esc is `WM_COMMAND` with IDCANCEL (which closes it); Space is an ordinary character (closes it).
So the `WM_CHAR` cases for 13 and 27 are dead code in the original, and Enter does nothing.

`input.c` (`wm_inject_key`) used to deliver Enter to a dialog without an IDOK control as `WM_KEYDOWN` and `WM_CHAR` (the change that let the "You won!" screen be left at all, `PHASE_C.md`: it ate the key before). Now,
for a dialog with no IDOK control and **no visible, enabled push button** (plain, default or owner-drawn: nothing the dialog manager could press), Enter is sent as `WM_COMMAND` with IDOK and no control, as Windows
does, and no character follows. A dialog that has such a button, or an IDOK control, or a message box (`own_keys`) is as before; so is Esc (the character, which closes the dialog with 1 where the original's IDCANCEL
closes it with 0: nothing reads it for this dialog) and Space. A Gauntlet's result screen (both buttons shown) is not changed either; there the original would press the focused button on Enter, which the port does
not do (the mouse, A on a controller, does). Other dialogs of `MAGIC.EXE` and `DUEL.EXE` without an IDOK control (templates 223, 229, 233, 235, 240, 243, 244, 247, 249 by the resource tables) were not played with Enter; the
ones with buttons keep their behaviour by the rule, and the list ("ShowList from Sid") never took Enter.

Tested: `test_wm` (`test_dialog`: a dialog with a text and a push button still gets `WM_CHAR` 13; a dialog with only a text gets `WM_COMMAND` 1 and no 13, and Space as a character closes it; the old expectation that the
text-only dialog got the 13 is gone) and `tools/soak/won_dialog.py` (a duel won by poking the opponent's life: Return leaves the dialog, a click closes it; 640x480). Esc (the pipe's `key escape`) closes it in the running game too, so on a controller **Back or A with the cursor on the dialog closes it** (X and Start are Enter, which does nothing here, as in the original). Space was
not tried end to end: the control pipe's `key space` sends no character (SDL makes the character from a text event), and `text` cannot send a blank (the parser skips it), so only the unit test covers it.
Not checked in the Windows 98 VM again: the reading above is of the code and agrees with what was seen there.

# Help and About

Findings of one session (macOS arm64, dummy SDL drivers, 640x480). Code: `src/port/winhelp.c` (+ `winhelp.h`); `WinHelpA` moved there out of `user32.c`. Tests: `test_winhelp` in `src/port/test_wm.c`.

## What the game does

**There is no menu bar.** `MAGIC.EXE` and `DUEL.EXE` have no menu resources (the resources are 22 dialog templates, a string table of one entry, one accelerator table, icons and version info); `DECK.EXE`,
`DECKDLL.DLL` and `STATWIN.DLL` have no Help or About at all (no `WinHelp`, no help or about strings, no About template). Everything the player can pick is in the **right-click popup menus**,
which the program builds with `AppendMenuA` and serves from `WM_COMMAND`:

| where | items | what the command does |
| --- | --- | --- |
| the duel window's menu (`MAGIC.EXE` duels, `DUEL.EXE`) | `About...` (id 0x70), `Help...` (0x6e) | 0x70: `DialogBoxParamA(template 247)`; 0x6e: `WinHelpA(hwnd, "<install>\duel.hlp", HELP_CONTEXT, 0x7e2)` |
| card, phase, ante, deck and other windows' menus (about seventeen call sites in each program) | `Help...`, `Help for this card...`, `Help for this phase...` | `WinHelpA(.., HELP_CONTEXT, n)` with n one of 0x7dd, 0x7df, 0x7e2, 0x7e3, 0x7e5 to 0x7ea, 0xbbc, 0xbd2, 0xbdf, 0xc1b |
| the palette window's `WM_DESTROY` | | `WinHelpA(.., HELP_QUIT, 0)` |

The help file name is `g_GameInstallDirectory + "\duel.hlp"`; the guest sees `C:\MAGIC\PROGRAM\duel.hlp`. `DUEL.HLP` and `DUEL.CNT` are in the install, and `DUEL.HLP` is a genuine WinHelp 3.x
file (`|SYSTEM`, `|TOPIC`, `|CONTEXT`, `|CTXOMAP`, `|KWBTREE`, 56 `|bmN` bitmaps...): LZ-compressed topics with a phrase table, not text. `DUEL.CNT` is the contents tree ("About Cards", "Types of Cards",
...) with topic names and numbers; the numbers the program passes are presumably the file's context ids (not decoded).

**F1.** The accelerator table of both programs (resource 111) maps F1 (virtual key 0x70) to command 600 (0x258), and no window procedure of `MAGIC.EXE` or `DUEL.EXE` handles command 600 (the same table has
F12 = 599, which toggles the debug flag, and F4 to F11 and a number of letters, all debug commands guarded by that flag). So the game itself does nothing on F1 in a duel. (On the map the notes on
saves say F1 opens the deck builder; that is a key handler, not help.) `TranslateAcceleratorA` is a stub that returns 0 in this port (`user32.c`), so no accelerator of the table works here, including the
visible ones (Ctrl+T, Ctrl+I, Ctrl+U and Ctrl+S next to "Show ID tags", "Show invisible effects", "Show all cards' summoning sickness" and "Save game..." in the menu): they are reachable by the menu only.
Not changed; it would be a separate piece of work (and the letter accelerators, which are debug commands, need a decision on what to enable).

## About

Template 247 is a 200 x 100 unit popup with no caption and three left-aligned statics (the copyright, trademark and "Computer code" lines); the window procedure (`Duel_PaintBattlefieldBackground` in the
decompiled tree: the names are wrong, it is a dialog procedure) paints the background black on `WM_ERASEBKGND`, answers `WM_CTLCOLORSTATIC` with white text over a transparent brush, and calls `EndDialog` on
`WM_LBUTTONDOWN`, `WM_CHAR` and `WM_COMMAND`. **It has no OK button**: a click on it, or any key, closes it.

It already worked through the port's dialog layer and needed no change: seen in `DUEL.EXE` (standalone) and in a `MAGIC.EXE` duel (Resume Game, Duel a Sorcerer, Start the duel), right-click on the board,
`About...` shows the black box centred on the board with the three paragraphs in the game's own font; a click on it closes it, the duel goes on. `test_winhelp` checks the part of this the port is
responsible for with a template of the same shape (three statics, no buttons): a click on the text reaches the dialog procedure as `WM_LBUTTONDOWN` and a key arrives as `WM_CHAR`, and either ends the dialog.

## Help

`WinHelpA` returned 1 and did nothing, so `Help...` looked dead. A WinHelp engine (decompressing `|TOPIC`, the phrase tables, the bitmaps, the keyword index and drawing the result) is not worth building
for one help file, and showing the file as text is not possible: it is not text. So `winhelp.c`:

* returns TRUE for every call, as WinHelp does when it launches (the game does not look at the result);
* for a command that asks for help to be shown (`HELP_CONTEXT`, `HELP_INDEX`, `HELP_FINDER`, `HELP_KEY`, `HELP_CONTEXTPOPUP`, ...) shows a modal dialog, "Help", with "In-game help is not available in this port."
  and "The help file (duel.hlp) is in the Windows Help format, which Pentamoor cannot show." over an OK button (`winhelp_text` makes the text; the file name is the path's last component, as the game gave it);
* for `HELP_QUIT`, `HELP_SETINDEX`, `HELP_FORCEFILE`, `HELP_SETPOPUP_POS` and `HELP_SETWINPOS` does nothing (there is no help window to close or place);
* writes `WinHelp: window, file, command, data` with `PORT_TRACE=1`, so the topic number the game asked for is visible.

The dialog (`port_message_dialog`) is built in code like the file dialog's and run by `wm_dialog_box`: MS Sans Serif 8, centred on the screen, the OK button the default (Enter), Esc and the close box also
close it. It is modal as a real help window is not (WinHelp opens a separate window and the game goes on); the game is paused behind the dialog until OK, which is no different for the player than closing
the help window, and avoids needing a second top-level window.

`port_message_dialog` is now a message box with only an OK button (`msgbox.c`, see `dialogs.md`: `MessageBoxA` is real since, with `PORT_MSGBOX=auto` for unattended runs); the dialog text above is
the same, the size now comes from measuring the wrapped text instead of the 50-characters-a-line estimate.

## Checked

Run natively with SDL's dummy drivers, the dialogs read from screenshots and the window dump (`PORT_CONTROL` `windows`):

* `DUEL.EXE`: setup dialog, OK, coin toss, start of duel; right-click on the board, `About...` (black box, three paragraphs; a click closes it), `Help...` (the Help dialog; closed by a click on OK, by Return, by Esc).
* `MAGIC.EXE`: Resume Game, Duel a Sorcerer, start of duel; `About...` (same, closed by a click) and `Help...` (the Help dialog), and the right-click menu of a card in the hand, `Help...`
  (`WinHelp: ... command 0x1, data 0xa4` in the trace; the same dialog).
* `make -C src/port test`: `test_wm` runs a block of new checks (`winhelp_shows`, `winhelp_text`, the file name, a small buffer, `HELP_QUIT` with and without a file name opens nothing, WinHelpA closed four ways: OK, Enter,
  Esc and WM_CLOSE, with and without a file name; the About-shaped dialog closed by a click and by a key).

## Not checked

* The other Help items (`Help for this phase...`, the ante and deck windows' menus, `Help for this card...` on the battlefield) were not clicked one by one; they all reach the same `WinHelpA`
  (the phase and card menus are `AppendMenuA` calls at the sites in the table above, all `HELP_CONTEXT`). Only the duel window's and a hand card's menu were run.
* The standalone `DECK.EXE` and the overworld (towns, castles, dungeons): nothing there asks for help or has an About.
* The real Windows 98 About dialog and the real WinHelp window against screenshots: not compared (no Windows 98 run of the duel's About was made); the look is the game's own template through `ui.c`.
* The dialog's height is estimated from the text length at about 50 characters a line; a very long help file name could make the text wrap to more lines than room was left for.

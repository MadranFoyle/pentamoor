# File dialogs, prompts.txt.txt, SIGTERM

Findings of one session (macOS arm64, dummy SDL drivers, 640x480). Code: `src/port/filedlg.c` (+ `filedlg.h`), small changes in `controls.c`, `ui.c`, `wm.h`, `front_sdl.c`.

## 1. GetOpenFileNameA / GetSaveFileNameA

### Who calls them

Not the deck builder. Checked from the PE import tables and the machine code:

| program | import | called from | what |
| --- | --- | --- | --- |
| `DUEL.EXE` | `GetOpenFileNameA` (thunk 0x4d95f0) | 0x49c701 | the setup dialog's "Load saved game..." button |
| `DUEL.EXE` | `GetSaveFileNameA` (thunk 0x4d95f6) | 0x4b4193 | the duel's right-click menu, "Save game..." (Ctrl+S) |
| `MAGIC.EXE` | `GetSaveFileNameA` (thunk 0x50ce18) | 0x442dfb | a save from the Gauntlet duel inside MAGIC.EXE (not exercised) |
| `DECK.EXE`, `DECKDLL.DLL`, `STATWIN.DLL` | none | | the earlier notes listing them were wrong |

DUEL.EXE fills one static OPENFILENAME (0x615300, the old 76-byte form) once (0x49ac8a) and reuses it. Seen with `PORT_TRACE`:
`lpstrInitialDir` `C:\MAGIC\PROGRAM\SaveGame`, `lpstrFile` offered as `*.SVG` (open) or `AUTOSAVE.SVG` (save), `nMaxFile` 260, one filter
"MTG Gauntlet Save Game" / `*.SVG`, `lpstrDefExt` is the string `*.SVG` (the game uses it as `buf + 1` = ".SVG" itself), flags 0x2a100c for Open (LONGNAMES, EXPLORER,
NONETWORKBUTTON, FILEMUSTEXIST, NOCHANGEDIR, HIDEREADONLY) and 0x2a000c for Save (no OVERWRITEPROMPT, no PATHMUSTEXIST). The title is "Load Saved Game" / "Save Game".
No hook, no template. The game then passes `lpstrFile` to its own loader / `fopen`.

### What was built

A modal Explorer-style dialog, made of the standard controls through the same code as the game's own dialogs (`wm_dialog_box`, split out of `DialogBoxParamA`:
it takes a template in host memory, so `filedlg.c` builds a DLGTEMPLATE in code and the window procedure is a host function), drawn by `ui.c`:

* title from `lpstrTitle` (else "Open" / "Save As"), "Look in:" combo (a drop-down lists the folders from `C:\` down to the current one; a pick opens it), "Up one level" button,
  list of the folder's sub-folders (first) and the files matching the selected filter (sorted without regard to case; `.`-names hidden), a scroll bar (arrows and track clicks),
  "File name:" edit box with a blinking cursor, "Files of type:" combo (a drop-down of the filter descriptions), Open/Save and Cancel, a status line.
* Mouse: click selects (a file's name goes into the box), a second click on the same row within 500 ms opens (folder: goes in; file: chooses it), combo boxes and their lists.
* Keyboard: typing, Backspace, Delete, Left/Right/Home/End; Up/Down/PgUp/PgDn move the list selection; Return is IDOK and Esc is IDCANCEL (the dialog manager in `input.c`;
  Esc first closes an open drop-down, or answers "No" to a replace question). The offered file name starts selected (typing replaces it).
* What Return does: empty box + a folder selected enters it; a name with `*` or `?` becomes the pattern shown (a folder in front of it is entered first); a name that is a folder enters it;
  else the name is made absolute (relative to the dialog's folder; `..`, `.`, `D:x`, quotes and a trailing backslash handled by `fd_resolve`), the default extension added when it has
  none (Open: only when that file exists and the plain name does not), `OFN_FILEMUSTEXIST` refuses a name that is not there, a folder that does not exist is refused (message in the
  status line, the dialog stays), `OFN_OVERWRITEPROMPT` asks "x already exists. Do you want to replace it?" with Yes/No (Return = Yes, Esc = No).
* Result: the full guest path (`C:\MAGIC\PROGRAM\SaveGame\AUTOSAVE.SVG`, the folder spelled as the host has it where the user picked it from the list, as typed otherwise) into `lpstrFile`
  (refused if it does not fit `nMaxFile`), `nFileOffset`, `nFileExtension` (0: none; a trailing period points at the terminator), `lpstrFileTitle`, `nFilterIndex`; return 1. Cancel, Esc and the
  close box return 0, `lpstrFile` untouched.
* `lpstrDefExt` as DUEL.EXE hands it over (`*.SVG`) is read as `SVG`: leading `*` and `.` dropped, a pattern with wildcards inside is no extension.
* Not done: hooks and templates (`OFN_ENABLEHOOK` / `OFN_ENABLETEMPLATE` are traced and ignored), multi-select, the places bar, the read-only box, `lpstrCustomFilter`, a mouse drag of the
  scroll thumb, and the working directory is not changed after OK (the flag NOCHANGEDIR is set by the game anyway). The "Look in" list stops at `C:\`, which the path mapper shows as the
  same files as `C:\Magic`.

Checked running: `./pentamoor duel`: Load saved game... shows `AUTOSAVE.SVG` in `SaveGame` (Look in drop-down, Up one level to PROGRAM with its folders and files, scrolling), typing
`AUTOSAVE` + Return loads it (".SVG" added, the duel starts); in the duel Save game... (right-click menu), `mysave` + Return wrote `SaveGame/mysave.SVG` in the overlay.
`test_wm` runs 17 scripted sessions of the real dialog (keys, clicks, double clicks, the drop-downs, Up, patterns, fallback folder, the overwrite question, cancel); `test_paths` checks the
filter parser, wildcard matcher, path splitting/joining/resolving, default extension and the offsets (44 checks).

## 2. `prompts.txt.txt`: not the port's doing

The deck builder DLL (`DECKDLL.DLL`, function at 0x10034b40, called at 0x100197fb and 0x10019919 with section "COLORWORDS" / "LANDWORDS" and the name `prompts.txt`) builds the file
name itself: `<install folder>\` + the name + a suffix chosen by a language variable at 0x10175ee8: 0 gives ".txt", 1 ".ger", 2 ".fre". The variable is only ever written once, to 0
(0x10010a62). So the DLL opens `prompts.txt.txt`, with a suffix on a name that already has one, and the disc has only `PROMPTS.TXT`. `fopen` is asked for exactly what the code built
and the port maps names faithfully, so the original on Windows asks for the same file and does not find it either (not run on the Windows 98 VM; read from the code). The DLL goes on
without it (the return is -1). Left as is: making the port answer with `PROMPTS.TXT` would change what the deck builder shows compared with the original.

## 3. SIGTERM / SIGINT

`front_sdl.c` now switches SDL's own signal handling off (`SDL_HINT_NO_SIGNAL_HANDLERS`) and installs its own SIGINT / SIGTERM handler that sets a flag; the window loop sees the flag
within 8 ms, flushes and calls `exit(0)`. The window's close button (SDL_QUIT) keeps the polite path (WM_CLOSE, the 5 s fallback, a second request ends it at once). Measured with
`DUEL.EXE`: SIGTERM gone after 0.02 s; the PORT_CONTROL `quit` command (the close button's event) still takes 5.00 s. Without a window (`PORT_HEADLESS`, or SDL failing to start) no
handler is installed, so the default action ends the process at once as before.

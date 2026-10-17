# Saved games and the file layer

What was checked, what was found, what changed (src/port/paths.c, stdio.c, kernel32.c, controls.c, test_paths.c).

## Where files go

The game sees `C:\Magic\...`; `paths_host` maps it to two trees: the installed folder (read-only to the port) and the overlay (`PORT_OVERLAY`,
default `./port_overlay`). A read looks in the overlay first, then the installed folder. A write always goes to the overlay, folders made as needed.
Drive letters mean nothing (`D:MAGIC0.SVE`, `C:sound\x.wav` are the working folder's), either slash works, `..` and `.` are resolved, and a leading
`Magic` folder is the installed root.

The game's own files in the overlay (all under `Program/`):

| file | written by | meaning |
| --- | --- | --- |
| `MAGIC3.SVE .map .fce` | every autosave (seen after an encounter, a step and Quit) | what "Resume Game" loads |
| `MAGIC4..MAGICD.*` | Save (right-click on the map, or Shift+S) | the ten slots of "Load Saved Game" (slot n of the list is MAGIC(n+3)) |
| `saveDescs` | Save | ten lines, the slot names; opened `r+t`, rewound, ten `fprintf`s, so the file is not shortened (the original does the same: the tail of the old text stays, and is never read) |
| `SaveGame/` | made at start, `AUTOSAVE.SVG` and the duel slots go here | |
| `Statwin/*.tmp` | the status window DLL | masks it builds at start |

`.map` is read at start to see which slots exist (`magic3.map` ... `magicd.map`; the ones that do not exist are logged `(missing)` by PORT_TRACE and
that is right: an empty slot).

## Round trips tested

macOS, a new game (Red, a name), then: pay a wizard (gold 150 to 70), Save to slot 1 with a name, walk, Quit (autosaves), restart:

* Resume Game: gold, food, position and the map are as at Quit.
* Load Saved Game: the list shows the name typed; slot 1 loads (gold 70).
* The same overlay on Linux (case-sensitive; the overlay has a `PROGRAM` folder made by the macOS run): Resume Game gives the same screen
  (gold 30, food 45, same place) as Resume did on macOS. Save, walk, Quit, restart, Load works on Linux with the list showing the name.

Observation, not a file bug and not fixed: right after Load the avatar walks about three steps towards the mouse cursor (where the slot was clicked),
food goes down by that much, and a wizard tower nearby may open its encounter. The same happens on both hosts. The map's click-to-move reads the
mouse; whether the original does this after a load was not checked (that needs the oracle VM).

## Found and fixed

1. **Case-variant folders** (Linux). Names are matched without regard to case, but the old resolver took the first match `readdir` gave. With
   `PROGRAM` and `Program` both in the overlay (the game spells `C:\MAGIC\PROGRAM\...` one place and `Program` another, and a case-sensitive
   host makes two folders of that), which one a file was looked in depended on directory order. Now every spelling is searched, the one spelled as
   asked first, the rest in name order, and a file in any of them is found.
2. **What the overlay calls things.** A folder or file the game creates now takes the installed folder's spelling for a name the installed folder
   has (`Statwin`, `Program`, `SaveGame`...), else the game's spelling. Before, whichever case the game used first made the folder (macOS runs
   produced `PROGRAM`, the shipped saves have `Program`), so a Linux overlay could end with both.
3. **Writing into a file that only the installed folder has** (`r+`, `a`, `CreateFile` open-existing with write access, `_open` with `O_RDWR`):
   the file is copied up to the overlay first (`paths_host(..., 2, ...)`). Before, only `fopen("r+")` did that; `CreateFileA` and `_open` would
   fail (or, with `OPEN_ALWAYS`, create an empty file and lose the contents). Writing from scratch (`w`, `CREATE_ALWAYS`, `O_TRUNC`) stays
   `paths_host(..., 1, ...)` and copies nothing.
4. **"Dir" list requests** (`LB_DIR`/`CB_DIR`, used with `\*.DCK` for the deck lists) listed only one folder: the overlay's once it had any
   file in that folder, hiding every installed deck. They now list the installed and the overlay folders together; an overlay file shadows an
   installed one of the same name (compared without regard to case). `paths_list` does it.
5. **A crash on Linux in the deck builder.** `LB_GETITEMDATA`/`SETITEMDATA`/`GETLBTEXT`/`DELETESTRING` with index -1 (`LB_ERR`) passed the
   `index < count` test as a signed number and then indexed with an unsigned 4 billion. macOS got away with it (a mapped page), Linux segfaulted as
   soon as the deck builder (F1 or the book icon) opened. All five now test `0 <= index < count`.
6. **`CopyFileA`**: it ignored `bFailIfExists`, and a copy of a file onto itself truncated it before reading. It now fails the first with
   `ERROR_FILE_EXISTS` (existing in the overlay) and refuses the second.
7. **`ftell`/`fseek` on files written with `w`/`a`** did not look at the file being written (position stayed 0); they now use the host file. For
   `r+` files the write position follows `fseek` (text mode counts the line ends), and `_filelength` flushes first.
8. PORT_TRACE now says where every open, write, copy-up, copy and delete went (`paths: ... (write, new|exists)`, `copied up`, `CopyFileA`, `DeleteFileA`).

## Linux path audit (PORT_TRACE=1, title, new game, deck builder, a duel start)

Every `(missing)`/`not found` line in a run that did new game, Save, Quit, Resume, Load, the deck builder and the start of a duel:

* `magic4.map` ... `magicd.map` (and `magic3.map` before the first autosave): empty save slots, right.
* `C:\MAGIC\PROGRAM\prompts.txt.txt`: asked twice by the deck builder DLL on opening, not there on the installed disc either (probably the DLL adds
  `.txt` to a name that has it; not looked into); not a case problem, the game goes on, not changed.

Nothing else was missing: `sound\locmus1.wav`, `C:\MAGIC\PROGRAM\DuelArt\Damage.pic`, `\MAGIC\PROGRAM\CardArt\SmallArt.cat`, `C:sound\...`, `Decks\0076.dck`,
`statwin\water.avi` and the rest map to the installed spelling on a case-sensitive file system.

## Not covered

* In-duel Save (the `SaveGame/*.SVG` slots, `D:MAGIC0.SVE`..) was not exercised end to end; only that the folder is made and the autosave files are
  written. DUEL.EXE's `GetOpenFileNameA`/`GetSaveFileNameA` are stubs that return 0 (the standalone duel program's own file dialogs). *Correction (documentation audit, 2026-10): no longer true, they are real dialogs now: [file-dialogs.md](file-dialogs.md).*
* The game never calls `DeleteFileA`, `remove`, `rename` or `FindFirstFile` (checked in MAGIC.EXE, DUEL.EXE, DECK.EXE, DECKDLL.DLL imports), so no
  "whiteout" for a deleted installed file exists: a delete only removes the overlay's copy.
* Several guest threads calling `paths_host` at once while creating the same new folder in two spellings can still race on a case-sensitive host;
  this was not seen and not looked into.

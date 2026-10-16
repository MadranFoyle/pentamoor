# Spells of the Ancients (2.0 and 2.15) against the 1.0 the port is built from

What it would take to run *Magic: The Gathering "Spells of the Ancients"* (SotA, the 1997 expansion that replaced most of the programs) in Pentamoor, measured on the real files. Everything here is from the machine code and
the files of the two discs and the patch; nothing was decompiled, and no game file, generated C or screenshot is in the repository. The numbers come from `tools/research/` (the last section), which anyone with the files can rerun.
**2.15 is the target** (it is the last version, `sotav215.exe` applies to 2.0 directly and holds whole files); 2.0 is kept as a second row where it matters.

## Summary

- **The programs changed enough that nothing keyed to a 1.0 address survives**, but the lifter did not care: shandalar.exe (the successor of MAGIC.EXE) and magic.exe (a new "Magic Shell" that also carries the duel) lift to C with the lifter as it is,
  after a wrapper that replaces the 1.0 constants (2,050 of 2,058 and 1,747 of 1,756 functions; the rest are the picture decompressor, one or two compiler helpers and two functions with a `rol` instruction), and their five libraries lift completely.
  With a 290-line patch of experimental changes to a copy of the runtime (kept in `tools/research`, not applied) **shandalar.exe 2.15 runs to the title screen and into a new game's colour choice, headless, pixel-checked by eye only**; magic.exe creates its window and then stays black (not solved).
- **Every address the port hard-codes is different**: 0 of 54 hooked 1.0 addresses are where they were, 11 are the same code at a new address, 19 are the same function with changed code (a human has to look), 2 were not found. 2.0 and 2.15 differ from
  each other at 50 of the same 54, so a per-version table of addresses is needed, and only one SotA version should be supported.
- The 1.0 start of the program for a plain run (`LIFT_PROGRAM` = `MAGIC`) stops at the first picture: the picture decompressor lives at another address, which `lzw.c` does not know.
- Real changes in the engine, not only moved code: the master card record grew from 0x34 to 0x48 bytes (463 to 622 cards), the duel's card slot from 288 to 300 bytes and 81 to 101 slots a player (so `src/native/engine.h`'s strides are wrong for SotA), shandalar.exe 2.15 reads two values of
  Windows' own registry key at start and quits without them, the game starts two programs that find each other by window class (a process model the port does not have), and the installer is an InstallShield 5 cabinet that needs the original CD.
- Rough size of the work: 40 to 60 hours of agent work for shandalar.exe alone with no hook features, 90 to 140 for the whole thing (shell, controller and screen hooks, installer, CI). Details and risks at the end.

## What there is

| | |
|---|---|
| `MTG v2.00.iso` | the disc label "MTG v2", `Setup/DATA.TAG`: *Spells of the Ancients*, version 2.0, "September 8, 1997: UK Release Build". An **expansion**: its installer (`setup.ins`, compiled InstallShield script) asks for the original CD (`CheckOriginalCD`, `MSG_INSERTORIGINALCD`; `CdTools.dll` is the check), copies the old decks to `Old Decks` and `Old Playdeck`, reads the registry key `SOFTWARE\MicroProse\Magic: The Gathering` (value `1.0` under it), and installs into `C:\Magic` over the existing game |
| `sotav215.exe` (2.15 patch) | a WinZip self-extractor with five entries; **the copy in `sources/` is cut short**: 1,048,331 bytes, and the last entry (`deckdll.dll`, 265,216 bytes expanded, 89,728 packed) has only 19,716 bytes of its data (60,661 bytes inflate, then it ends). The other four are whole: `shandalar.exe` (1,740,288 B, 1997-10-31), `magic.exe` (1,530,368 B, 1997-10-20), `FaceData.txt`, `Readme.txt` (37,224 B). `tools/research/sotapatch.py` reads it (the stub contains false `PK` signatures, so `zipfile` cannot) and checks every entry's CRC. A complete copy is needed for 2.15's `deckdll.dll`; the experiments below used 2.0's, which is why the deck builder was not tried |
| 2.15 install | 2.0's Program folder with the four files replaced: `sources/installed_sota_215` (git-ignored) |

The 2.15 readme's change list ("Changes from version 2.0"), in short: cards of the expansion are now sold in Shandalar's towns; and a dozen card fixes in the duel engine (Black Vise and The Rack no longer deal double damage; Zombie Master-like cards stop working while they
are only in the spell chain; Kismet lets you target either player; Howling Mine, Soul Net and other artifacts with a continuous effect switch off when tapped; Black Lotus can no longer be answered with fast effects; City of Brass does not lose its point of damage;
Contract from Below lets you order the discards; Fastbond works with several in play and with lands that arrive another way than from the hand; Nevinyral's Disk does not tap when the activation is cancelled; Argothian Pixies and Treefolk are not immune to some
direct damage; Disenchanting an Animate Artifact keeps the creature state of an artifact creature; Farmstead sees Gloom's extra cost; Serendib Djinn flies). Nothing in the list is about the installer, the screens or the Windows side.
**2.15 is not a binary patch of 2.0**: 2.0 to 2.15 leaves 1,405 of magic.exe's 1,756 functions and 1,595 of shandalar.exe's 2,058 byte-identical (relocations masked), but the rest are mostly re-compiled code (the same operation with its operands swapped,
instructions in another order), so a function's being "changed" says little about the change.

## The installer's format

`Setup/data1.cab`, `_sys1.cab` and `_user1.cab` are InstallShield 5 cabinets (signature `ISc(`, version word 0x01005100). `tools/research/iscab.py` lists and extracts them (also straight out of the `.iso`, with `tools/install/iso9660.py`):

- header: the descriptor's offset (0x200) and size; the descriptor holds the file table's offset, size, and the numbers of directories and files; the table is one `u32` offset per directory then per file, relative to the table; a directory is a NUL-terminated
  name (`Program\CardArt`); a file descriptor is 0x2a bytes: name, directory, flags (4 compressed, 2 "obfuscated", 1 split, 8 unused slot), expanded and packed sizes, DOS attributes, date and time, and the offset of the data.
- data: a run of chunks, each a `u16` length and that many bytes of raw deflate, inflated one at a time. (The "obfuscated" flag is set on every file of `data1.cab` but the bytes are plain deflate.) There is no separate `data1.hdr`.
- `data1.cab`: 17 directories (`Program` and its art, deck, sound, video and tutorial subfolders), **335 entries, 70,587,570 bytes expanded, 55,435,910 packed**; they extract to 332 files in `Program` plus three at the top (`Readme.txt` and two `.url`s). `_sys1.cab`: 4 files (two DLLs, an
  ini, an exe, 495,478 bytes). `_user1.cab`: 23 files (20 bitmaps, a text, a `.jbf`, a `.shl`; 3,993,895 bytes). The installer itself (`SETUP.EXE`, `_INST32I.EX_`, `setup.ins` 67,768 bytes) is a compiled script: not read further.
- The disc also carries what the game reads from the CD, as 1.0's does: `Sound` (31 WAV), `StatWin` (68 AVI), `DuelSounds` (the shell's voice clips), and `Tutorial` (the Director projector `TUTORIAL.EXE`, 1.4 MB, with 13 chapter files, which 1.0's install has too, and 13 wizard videos of 1 to 35 MB), the autoplay program and
  its intro movies, and a copy of DirectX.

**What an installer for it has to do**: take two discs (the 1.0 disc first, then this one; Pentamoor's installer today takes one), install 1.0 as it does now, then extract the cabinet over it (`Program` of the new folder replaces files of the old: 93 files exist in both and differ, 11 are the same, 228 are new, and 976
of 1.0's stay, among them every sprite and most pictures: SotA **needs the 1.0 art**), apply the patch (four files here; five when the patch is whole), take the CD files from the 2.0 disc as well (22 WAV), and fingerprint the programs. The registry values the original installer wrote
have to be made up (see "What breaks").

## The folder

| folder | identical | different | only 1.0 | only 2.0 |
|---|---|---|---|---|
| Program (the folder itself) | 11 | 27 | 135 | 24 |
| `CardArt`, `DBArt`, `DuelArt` | 0 | 6 | 161 | 4 |
| `Decks` | 0 | 55 | 0 | 0 |
| `PlayDeck` | 0 | 5 | 55 | 31 |
| `Exp1Art` (the expansion's cards), `FaceArt`, `PlayFace`, `FaceMaker`, `ShellArt` | 0 | 0 | 0 | 147 |
| `DuelSounds` | 0 | 0 | 50 | 22 |
| `Sound`, `StatWin`, `Faces`, `SPR*` (sprites, three sizes) | 0 | 0 | 575 | 0 |

(2.0's `Program` holds 332 files, 1.0's install 1,080.) The program files: `shandalar.exe` 1,739,264 B (linked 1997-09-02; 2.15: 1,740,288), `magic.exe` 1,529,856 B (1997-09-03), `DECK.EXE` 16 KB (1.0: 86 KB with its own copy of the C runtime; it is a stub that
starts the deck builder in `deckdll.dll`), `deckdll.dll` 264 KB, `STATWIN.DLL`, `MAGSND.DLL`, `MAGVID.DLL` (all smaller; the ones checked now import the C runtime's DLL, `MSVCRT.DLL`, instead of the debug one, `MSVCRTD.DLL`),
and three new libraries: `cardartlib.dll` (card art: Load/Draw/Destroy of big and small art), `drawcardlib.dll` (draws a whole card, its mana text, the back) and `CdTools.dll` (`CheckOriginalCD`, `CheckSotaCD`, `IsCDDrive`, autoplay hooks). New program: `FaceMaker.exe`
(a portrait editor, with `FaceArt` and `PlayFace`); `Tutorial.exe` is 1.0's (its folder is in 1.0's install too). No `DUEL.EXE`. `CARDS.DAT` is 330,587 bytes (1.0: 325,187): the card rules did not move into data; **the master card table is in the program** (below).

### Which program is which

| 2.0 | role | 1.0 counterpart |
|---|---|---|
| `shandalar.exe` | the adventure (overworld, towns, castles, dungeons), the duel, the deck editor. Started with `/MTGshell`; refuses to start twice (`FindWindow` for its class `ShandalarMainClass` and for "Magic Shell", which it restores and quits) | `MAGIC.EXE` (1,956 functions found, 1,565 of them have a counterpart in it: 80%) |
| `magic.exe` | **the shell** (`MAGICGAME_MagicShellClass`, "Magic Shell"): the first thing a player starts. Pages `SHELLPAGE_GAUNTLET`, `SINGLEDUEL`, `SEALEDDECK` and screens for the duel, the hall of records, tools and help; runs its own duels (it carries the duel and AI code) and starts the other programs | `DUEL.EXE`, which it replaces (69% of DUEL.EXE's functions are in it; 61% of MAGIC.EXE's are in it too) |
| `DECK.EXE` | stub for the deck builder | `DECK.EXE` |

The programs start each other: magic.exe runs `WinExec("<dir>\Shandalar.exe /MTGshell")` for "Shandalar", and `CreateProcessA` (four sites; the strings name `Tutorial.exe`, `WinHelp.exe`, `Write.exe` and `FaceMaker.exe`); shandalar.exe runs `WinExec("<dir>\Magic.exe /start3,1")` to go back to the
shell, `_spawnl` (one site; it names `FaceMaker.exe` too), and `WinExec("Write c:/...")` to open Write on a debugging dump. Both look for the other's window. **The port runs one program per process** (`pentamoor-run -m MODULE PROGRAM.EXE`).

## Function-level comparison

Method (`tools/research/sotacmp.py`): the functions of each program are found with `tools/lift/fnscan.py`; each is reduced to its bytes with every base relocation zeroed and every call or jump to outside the function zeroed ("identical": the same code at another place), and to a stream of
instruction tokens (mnemonic, registers, small constants, field offsets; addresses are one token). Old and new are matched in stages: identical bytes (functions with identical twins are told apart by who calls them); the same token stream; then the Dice score of the
three-token groups plus the C strings the function uses (best pairs first, one to one); then through the call lists and the gaps between matched neighbours. "0.9-1.0" and so on are that score. The matching is the tool's reading, not a proof: of the pairs that have a string in the old
function, the new one has the same string in 97% of the "identical" pairs, 94% of the 0.9 band, 82%, 68%, and 75% of the "below 0.5" ones; so below about 0.7 a pair needs a person.
"Functions" are what the scan finds, dead code included (a function nothing found reaches, found by its prologue): 1,624 of 1.0's 1,956 in MAGIC.EXE are reachable; the second table counts those.

| comparison | functions old | functions new | identical | same shape | 0.9-1.0 | 0.7-0.9 | 0.5-0.7 | below 0.5 | old only | new only |
|---|---|---|---|---|---|---|---|---|---|---|
| MAGIC.EXE 1.0 -> shandalar.exe 2.15 | 1956 | 2058 | 579 | 9 | 131 | 261 | 246 | 339 | 391 | 493 |
| MAGIC.EXE 1.0 -> shandalar.exe 2.0 | 1956 | 2058 | 588 | 8 | 140 | 252 | 240 | 339 | 389 | 491 |
| DUEL.EXE 1.0 -> magic.exe 2.15 | 1837 | 1756 | 423 | 7 | 92 | 196 | 207 | 333 | 579 | 498 |
| DUEL.EXE 1.0 -> magic.exe 2.0 | 1837 | 1756 | 431 | 7 | 88 | 192 | 209 | 331 | 579 | 498 |
| shandalar.exe 2.0 -> 2.15 | 2058 | 2058 | 1595 | 0 | 343 | 90 | 23 | 5 | 2 | 2 |
| magic.exe 2.0 -> 2.15 | 1756 | 1756 | 1405 | 0 | 281 | 63 | 6 | 1 | 0 | 0 |
| MAGIC.EXE 1.0 -> magic.exe 2.0 (cross) | 1956 | 1756 | 348 | 13 | 84 | 184 | 216 | 348 | 763 | 563 |
| DUEL.EXE 1.0 -> shandalar.exe 2.0 (cross) | 1837 | 2058 | 351 | 13 | 87 | 186 | 228 | 335 | 637 | 858 |
| DECKDLL.DLL 1.0 -> deckdll.dll 2.0 | 684 | 370 | 183 | 2 | 44 | 55 | 27 | 17 | 356 | 42 |
| STATWIN.DLL 1.0 -> 2.0 | 238 | 149 | 118 | 1 | 8 | 11 | 0 | 1 | 99 | 10 |
| MAGVID.DLL 1.0 -> 2.0 | 367 | 237 | 197 | 3 | 15 | 8 | 0 | 0 | 144 | 14 |
| MAGSND.DLL 1.0 -> 2.0 | 131 | 71 | 47 | 5 | 5 | 4 | 0 | 0 | 70 | 10 |
| DECK.EXE 1.0 -> 2.0 | 182 | 16 | 4 | 0 | 1 | 0 | 0 | 0 | 177 | 11 |


| comparison | old reachable | new reachable | old only (reachable) | new only (reachable) | bytes of old functions: identical | all | share identical |
|---|---|---|---|---|---|---|---|
| MAGIC.EXE 1.0 -> shandalar.exe 2.15 | 1624 | 1868 | 202 | 434 | 109533 | 1123655 | 10% |
| MAGIC.EXE 1.0 -> shandalar.exe 2.0 | 1624 | 1860 | 200 | 433 | 109219 | 1123655 | 10% |
| DUEL.EXE 1.0 -> magic.exe 2.15 | 1473 | 1555 | 387 | 472 | 67392 | 971687 | 7% |
| DUEL.EXE 1.0 -> magic.exe 2.0 | 1473 | 1551 | 391 | 472 | 69391 | 971687 | 7% |
| shandalar.exe 2.0 -> 2.15 | 1860 | 1868 | 2 | 2 | 734549 | 1441626 | 51% |
| magic.exe 2.0 -> 2.15 | 1551 | 1555 | 0 | 0 | 727791 | 1276195 | 57% |
| MAGIC.EXE 1.0 -> magic.exe 2.0 (cross) | 1624 | 1551 | 544 | 492 | 57828 | 1123655 | 5% |
| DUEL.EXE 1.0 -> shandalar.exe 2.0 (cross) | 1473 | 1860 | 421 | 775 | 58201 | 971687 | 6% |
| DECKDLL.DLL 1.0 -> deckdll.dll 2.0 | 556 | 284 | 327 | 27 | 39867 | 197496 | 20% |
| STATWIN.DLL 1.0 -> 2.0 | 197 | 117 | 94 | 9 | 21331 | 34998 | 61% |
| MAGVID.DLL 1.0 -> 2.0 | 306 | 186 | 142 | 13 | 25418 | 38303 | 66% |
| MAGSND.DLL 1.0 -> 2.0 | 125 | 70 | 66 | 10 | 13509 | 20341 | 66% |
| DECK.EXE 1.0 -> 2.0 | 125 | 11 | 122 | 8 | 23 | 42745 | 0% |

What the tables say:

- **shandalar.exe is MAGIC.EXE's successor**: 1,567 of 1,956 old functions have a counterpart (80%), against 61% for magic.exe, but only 579 (30%) are byte-identical; those are small (10% of the old bytes). The rest differ by the compiler (the 2.0 programs were built
  with other settings and a release C runtime) and by real changes: new features, and **structure sizes**: in the pairs at 0.5 to 0.7, the common difference is one multiplication. The duel's slot table is indexed as `player * 23328 + slot * 288` in 1.0 (`SLOT_PLAYER_STRIDE 0x5b20`,
  `SLOT_STRIDE 0x120` in `src/native/engine.h`) and the compiler's replacement for the multiplication is `x*9*9*9<<5` and `x*9<<5`; in 2.0 and 2.15 it is `x*63*8+x<<2 *3 *5` and `x<<2 *5 *3 *5`: **30300 and 300**, i.e. 101 slots of 300 bytes. The hand-written engine
  (`src/native`, `layout.c`) is therefore unusable for SotA without new constants and new field offsets.
- **magic.exe is not a DUEL.EXE**: it is a program of its own that carries a copy of the duel code: 1,258 of DUEL.EXE's 1,837 functions (69%) have a counterpart in it, 1,200 in shandalar.exe, and the same duel code is in both (1.0's MAGIC.EXE also carried it).
- **The DLLs**: STATWIN, MAGVID and MAGSND are mostly the same code (60 to 66% of the bytes identical; the exports are the same 3, 20 and 27 names, so the host-made MAGSND and MAGVID of the port still fit by name). DECKDLL changed more (20% of the bytes), and DECK.EXE is a different, tiny program.
- **2.0 to 2.15** moved nothing big: one program per row, 2 functions of shandalar.exe appear and 2 go.

## The 54 addresses the port hard-codes

`tools/research/sotahooks.py` finds each address of `src/port` (pace.c, screens.c, yesno.c, textfocus.c, main.c, lzw.c and the ones the comments name) in the new programs: a function entry through the matching, an address inside a function by aligning the two instruction streams of the pair (checked
below by hand where it mattered), a global by the votes of every instruction that uses it ("strong": at least 3 agreeing uses, at least half of all uses, at least three quarters of the aligned ones).

**Summary, 2.15 (2.0 is the same except where the table shows a different address):**

| | count |
|---|---|
| same address and same code ("carried over unchanged") | **0** |
| code at a new address, identical bytes ("moved") | 11 functions (and three in the picture decompressor at the same offsets in its section, one found by hand) |
| a counterpart with changed code ("changed": look again) | 19 (the three ends of loops count here too), of which 2 under 0.5 and not to be trusted |
| not found | 2 (the "Sell" yes/no site, and a second entry of the decompressor, which is there at the same offset) |
| globals found strongly | 18 (one weak: the text menu's choice count) |
| frame offsets of the loops' locals | 3: two the same, one moved by 4 (the clue rows' count: `ebp-0x12d8` became `ebp-0x12d4`) |

2.0 and 2.15 put 50 of the 54 at different addresses (the four that agree are the decompressor's, and entries that were not found).
Checked by hand in 2.15: the return site of the overworld's tick call (`0x438f85`), the "Buy" and "Take" yes/no sites (`0x4a3296`, `0x4f0b96`) and the wait-loop's poll (`0x4b84e5`) are each the instruction after a call of the mapped function. The wait-for-key function has
10 call sites in 2.15 (12 in 1.0: the "Sell" site's function has no clear counterpart: two candidates are in `0x468533`), the mouse snapshot 19 (19), the button table's pass 18 (19), the key poll 9 (9), the tick function 9 (9).

| v1.0 | what the port does there | 2.15 | status 2.15 | 2.0 |
|---|---|---|---|---|
| `0x5016f9` | pace.c: overridden. Reads and clears the 33 ms tick counter | `0x48a3a5` | moved | `0x4daeb1` |
| `0x4e7873` | pace.c: return site of the tick call in the overworld loop (frame pacing) | `0x438f85` | changed (0.88) | `0x4ae0d5` |
| `0x4e73a0` | pace.c, screens.c: the overworld loop (start of the range the map loop is recognised by) | `0x438a70` | changed (0.88) | `0x4adbc0` |
| `0x4e7936` | pace.c, screens.c: the overworld loop (end of the range) | `0x439059` | end of the counterpart of the loop above | `0x4ae1a9` |
| `0x41f3ea` | pace.c, screens.c: pre-call hook, the button table's pass (once per loop of every screen with buttons) | `0x4ba087` | changed (0.97) | `0x4d3eba` |
| `0x530da0` | pace.c: the tick counter | `0x566f3c` | moved (strong) | `0x56d764` |
| `0x7039c4` | pace.c: the mouse button state | `0x9199b0` | moved (strong) | `0x916ef0` |
| `0x41f354` | screens.c: push a button-table context | `0x4b9ff1` | moved | `0x4d3e24` |
| `0x41f391` | screens.c: pop a button-table context | `0x4ba02e` | moved | `0x4d3e61` |
| `0x44b84b` | screens.c: pre-call hook, the mouse snapshot | `0x4eab14` | moved | `0x5426b4` |
| `0x489748` | screens.c: the text menu loop (start) | `0x4b6fe7` | changed (0.96) | `0x4010b8` |
| `0x489c9c` | screens.c: the text menu loop (end) | `0x4b753c` | end of the counterpart of the loop above | `0x40160c` |
| `0x509517` | screens.c: 'Cards for Sale' loop (start) | `0x4a28c7` | changed (0.76) | `0x4d7c97` |
| `0x509fd4` | screens.c: 'Cards for Sale' loop (end) | `0x4a347c` | end of the counterpart of the loop above | `0x4d884e` |
| `0x48f523` | screens.c: clues loop (start) | `0x4aa415` | changed (0.83) | `0x44ce24` |
| `0x49094c` | screens.c: clues loop (end) | `0x4ab73e` | end of the counterpart of the loop above | `0x44e14d` |
| `0x519c24` | screens.c: the current button-table context | `0x577cec` | moved (strong) | `0x56cb4c` |
| `0x67f780` | screens.c: records per context | `0x7270e0` | moved (strong) | `0x8b19a0` |
| `0x67f7d0` | screens.c: record pointers per context | `0x727130` | moved (strong) | `0x8b19f0` |
| `0x539dec` | screens.c: text menu left edge | `0x6a0f54` | moved (strong) | `0x586604` |
| `0x539df0` | screens.c: text menu top | `0x6a0f58` | moved (strong) | `0x586608` |
| `0x676d44` | screens.c: text menu right edge | `0x728114` | moved (strong) | `0x912934` |
| `0x527b30` | screens.c: text menu line height | `0x577c4c` | moved (strong) | `0x56302c` |
| `0x676d50` | screens.c: text menu first choice line | `0x728120` | moved (strong) | `0x913110` |
| `0x676d40` | screens.c: text menu choice count | `0x728110` | moved (weak) | `0x912930` |
| `0x676d58` | screens.c: text menu mask of shut choices | `0x728128` | moved (strong) | `0x913118` |
| `0x61e060` | screens.c: the cards for sale (ids) | `0x69eb70` | moved (strong) | `0x6a9590` |
| `ebp-0xa8@0x509517` | screens.c: number of cards for sale (a local of the loop) | `ebp-0xa8@0x4a28c7` | same | `ebp-0xa8@0x4d7c97` |
| `ebp-0xa0@0x509517` | screens.c: the card boxes (locals of the loop) | `ebp-0xa0@0x4a28c7` | same | `ebp-0xa0@0x4d7c97` |
| `ebp-0x12d8@0x48f523` | screens.c: number of rows with a dungeon (a local of the clues loop) | `ebp-0x12d4@0x4aa415` | moved | `ebp-0x12d4@0x44ce24` |
| `0x48ac2f` | yesno.c: pre-call hook, wait for a key | `0x4b84d7` | moved | `0x4025a5` |
| `0x4080b2` | yesno.c, textfocus.c: pre-call hook, pop a key from the game's key queue | `0x4a8ea2` | moved | `0x4fc722` |
| `0x48ac3d` | yesno.c: where the poll in the wait loop returns to | `0x4b84e5` | moved | `0x4025b3` |
| `0x509e4a` | yesno.c: yes/no site, 'Buy for N gold? (Y/N)' (return of the wait-for-key call) | `0x4a3296` | changed (0.76) | `0x4d8667` |
| `0x4f156e` | yesno.c: yes/no site, 'Sell ... (Y/N)' | - | none | - |
| `0x45119d` | yesno.c: yes/no site, 'Take ... (Y/N)' | `0x4f0b96` | changed (0.95) | `0x46bf46` |
| `0x47be64` | textfocus.c: the new game's name box loop (start) | `0x53aecd` | changed (0.72) | `0x53c6cd` |
| `0x47c080` | textfocus.c: the name box loop (end) | `0x53b129` | end of the counterpart of the loop above | `0x53c929` |
| `0x522458` | main.c: screen width the game's layouts read (written at start for 800x600 and 1024x768) | `0x57a7d0` | moved (strong) | `0x581440` |
| `0x52245c` | main.c: screen height | `0x57a7d4` | moved (strong) | `0x581444` |
| `0x70d000` | lzw.c: overridden. Picture decompressor, header reader (MPS_CODE) | `0x91e000` | moved | `0x91e000` |
| `0x70d484` | lzw.c: overridden. Decoder to a destination | `0x91e484` | moved | `0x91e484` |
| `0x70d1fc` | lzw.c: overridden. Decoder, second entry | `0x91e1fc` | moved (same offset in MPS_CODE, found by hand) | - |
| `0x50e8b0` | lzw.c: the callback it calls with the dictionary block | `0x55d9e0` | changed (0.95) | `0x55c6e0` |
| `0x706500` | lzw.c: input pointer | `0x915cd0` | moved (strong) | `0x915ce0` |
| `0x5327b0` | lzw.c: input end | `0x581fc0` | moved (strong) | `0x581fe8` |
| `0x67f43c` | lzw.c: refill callback | `0x726b1c` | moved (strong) | `0x72153c` |
| `0x532860` | lzw.c: dictionary block (the state block lies behind it, at fixed offsets) | `0x582070` | moved (strong) | `0x582098` |
| `0x40a3e1` | input.c: (comment) waits for the button release after the deck builder returns | `0x55ac0b` | moved | `0x4b3acb` |
| `0x4e7a6f` | pad.c: (comment) the map's walking code | `0x43923e` | changed (0.96) | `0x4ae38e` |
| `0x4262cf` | navwm.c: (comment) the phase column's icon test | `0x4d9509` | changed (0.98) | `0x51c949` |
| `0x427a0a` | navwm.c: (comment) the combat column's icons | `0x4dac44` | moved | `0x51e084` |
| `0x4b9284` | navwm.c: (comment) the mana pool's window procedure | `0x41c8a0` | changed (0.42), unreliable | `0x4713b0` |
| `0x424500` | stdio.c: (comment) reads PROMPTS.TXT | `0x4b33b0` | changed (0.3), unreliable | `0x5542b0` |

**What a plain run does with 1.0's addresses** (`LIFT_PROGRAM` = `MAGIC`, tried by making the module report that name): none of the five hooked or overridden function addresses is the start of a function in 2.0 or 2.15 (each lies inside another function), so those hooks and overrides would never fire (silently: no click handling,
no frame pacing, no yes/no on a pad, no name-box detection); `main.c` would write the screen size into `0x522458` and `0x52245c`, which are inside code in both versions (not in the data), and the program would leave the layouts at 640x480; and the run **stops at the first picture**: "a call to 0x0091e000, which is neither a lifted function nor an import" (exit status 2), because the decompressor
is only overridden at 1.0's address. So **a fingerprint check is needed before any of it is installed**: today the hooks look at `lift_game->program` and nothing else. (Done since: the addresses are in a per-build profile found by the file's SHA-256, and a build with no profile is refused with exit status 3: [PHASE_C.md](../PHASE_C.md), "Build profiles". The 54 addresses above are what a SotA profile would hold. `tools/research/sota-runtime-experiment.patch` was made against the tree before the profiles and no longer applies to `lzw.c`, `modules.c` and `port.h`; its decompressor part is now a row of the table, its other hunks apply as they were.)

### The duel engine's table (`src/native/layout.c`)

Mapped the same way (`sotalayout.py`): of its 39 functions in MAGIC's layout, 13 are found as identical code at new addresses, 22 as changed, 4 not at all (among them `query_card_attribute`, the engine's central query, and `get_color_and_type_flags`); of its 60 globals, 27 are found strongly and 32 weakly (the weak ones are the votes
of a few instructions in functions whose slot arithmetic changed; the master table's address, which is known to be `0x568bcc` for 2.15 shandalar.exe from its records, was *not* the vote's answer, so weak means wrong more often than not). DUEL's layout against magic.exe: 41 functions, 13 identical, 22 changed, 6 not found; 28 globals strongly, 30 weakly. In short:
nothing in `src/native` carries over without being redone, and the engine's record sizes changed under it.

## Lifting and running

`tools/research/liftsota.py` runs `tools/lift/gen_handlers.py` and `gen_dll.py` as they are, after replacing what is 1.0's: `PROGRAMS` (the master table's address and the code range), the record size read by `handler_addresses`, `native_entries`, `VARIADIC`, and the signatures the lifter lacks.

**Findings that the wrapper had to work around** (each is a few lines in the lifter or in a profile):

- the master card table: 622 records of **0x48** bytes (1.0: 463 of 0x34); the code pointer is where the first run of code pointers starts: `0x568bdc` in shandalar.exe 2.15 (master `0x568bcc` with the handler at +0x10), `0x54800c` in magic.exe (`0x547ffc`). It is found by looking for the run, not read from a known address;
  the dispatch is `call [eax+eax*8+X]` (four sites in shandalar.exe), not 1.0's `call [eax*4+X]`, and `gen_handlers.py` refuses a function that makes an indirect call in another form (none was refused here: `--no-handlers`, which is what the port uses, does not need the table, only the scan does);
- 47 Windows and C runtime calls the lifter has no signature for (all of them new: `sotaimports.py` lists them), and every export of the three new libraries, which are `cdecl` (found from their `ret`): `signature()` only knows the C calling convention for the C runtime; with those added, no function is refused for a missing signature;
- one unsupported instruction (`rol`: 2 functions of each program, one of them in the deck library, in no hot path as far as the scan can tell) and the picture decompressor (5 functions, handled by hand as in 1.0, see below);
- `chkstk` and `allshl` helpers are recognised as before. Register-argument functions: none new.

**Result (2.15; 2.0 is the same to the function):**

| program | functions found | lifted | not lifted |
|---|---|---|---|
| shandalar.exe | 2,058 | 2,050 | 8: the decompressor (5), `chkstk` (inline), 2 with `rol` (one dead code) |
| magic.exe | 1,756 | 1,747 | 9: the decompressor (5), `chkstk` and `allshl` (inline), 2 with `rol` |
| STATWIN, deckdll, cardartlib, drawcardlib, CdTools | 125, 203, 295, 280, 150 | all but one (`rol` in deckdll) | |

(`docs/PHASE_C.md` gives 97% for 1.0's MAGIC.EXE, counted at an earlier state of the scan; here it is 99.6%.) The generated C is 52 MB for shandalar.exe and 45 MB for magic.exe, as large as 1.0's, and each module builds with the port's own flags in under a minute.

**Imports.** shandalar.exe imports 339 functions and magic.exe 315; 23 and 29 of them are not imported by any 1.0 program. The port's tables lack **21 (shandalar.exe) and 27 (magic.exe)** of those (42 over both programs and the three new libraries; EqualRect and SetRectEmpty, new, are there already), and the lifter has no signature for 47:

- both programs: `RegOpenKeyA`, `RegCreateKeyA`, `GetFileTitleA`, `ExtTextOutA`, `RectInRegion`, `GetThreadTimes`, `GetVersionExA`, `GetWindowsDirectoryA`, `ResumeThread`, `SuspendThread`, `WinExec`, `GetUpdateRect`, `GetUpdateRgn`, and `_beginthreadex` from the C runtime;
- shandalar.exe only: `ChangeDisplaySettingsA`, `GetDiskFreeSpaceA`, `_spawnl`, `_setjmp3`, `longjmp`, `qsort`, `strcoll`;
- magic.exe only: `CreateProcessA`, `FindFirstFileA`, `FindClose`, `CreateDialogParamA`, `IsDialogMessageA`, `GetWindowTextLengthA`, `IsCharAlphaNumericA`, `ShowScrollBar`, `GetCursor`, `CharLowerA`, `CharUpperA`, `mciSendCommandA`, `mciGetErrorStringA`;
- the new libraries: `TlsAlloc`, `TlsFree`, `TlsGetValue`, `TlsSetValue` (their C runtime starts per-thread data), `GetLocaleInfoA` and `W`, `GetVolumeInformationA` (the CD check), `GetDiskFreeSpaceA`, `GetVersionExA`, `RegisterWindowMessageA`.
- **The C runtime's name**: the port finds an import by the library's name as written, and its tables say `msvcrtd.dll`; SotA's programs import `msvcrt.dll`, so 77 more calls of shandalar.exe (the C runtime's: 101 are not found as written, 24 after the alias) are "not implemented" until the name is treated as an alias (a one-line change in `pe.c`; it is in the experimental patch).
- The libraries MAGSND.DLL and MAGVID.DLL have the same exports as 1.0's, so the host-made ones still fit.

**Running it** (a scratch copy of `src/port` with `tools/research/sota-runtime-experiment.patch` applied: it adds the calls above as small implementations, the msvcrt alias, the decompressor's state for each copy of it, and an environment switch to rename the module's program; the modules were built with the port's Makefile from the generated C. `SDL_VIDEODRIVER=dummy`, 640x480, no hooks because the module's name is not `MAGIC`):

- **shandalar.exe, 2.0 and 2.15: the title screen draws** (the 640x480 title as in 1.0, by eye), and a click on "Start New Game" brings up "Select Your Color" correctly. Choosing a colour goes to the new-game name screen, which **draws garbage**: noise instead of the picture in the middle, and a garbage name; the middle is where the new portrait
  (`FaceArt`, `PlayFace`, `FaceMaker`: all new in 2.0) goes, probably drawn by the new libraries: not investigated.
- 2.0 asks `GetDiskFreeSpaceA` for the swap file's room and shows the game's own "Low Memory/Swap File Space Warning" until it returns believable numbers.
- **2.15 quits at once without a registry answer**: its start-up (the function that `WinMain` calls first, at `0x4e68b9`) opens `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion` and reads two values of it that Windows itself keeps (the system's first-install time and its product id), builds a short machine string from them, and returns "failure" if either is missing, on which the program ends
  with status 0. 2.0 has no such code. With two made-up values the program goes on. (What the string is used for was not followed: it may stamp saves or serve as a licence check.)
- **magic.exe, the shell, stays black**: it loads all its text tables, registers its window class, creates the window and about forty buttons and labels, loads a picture into an off-screen bitmap, and then sits in its message loop (1,780 passes in 15 s) without ever calling `ShowWindow` or `UpdateWindow`; its layout is for 800x600 (rectangles to x = 800) and 800x600 and 640x480 give the same black. Not solved. It makes no CD
  call, and its three registry reads fail as in 1.0 (defaults); the next step is to find what it waits for in the message loop (a timer or a posted message are the candidates).
- Not tried: a duel, the deck builder (needs 2.15's complete `deckdll.dll`), the overworld, a save, sound, and everything that needs a second program.

**The process model.** The port has no `CreateProcess`: `WinExec`, `CreateProcessA` and `_spawnl` are not implemented, and the runtime is one program per process with one module. The shell start-up (magic.exe first, then Shandalar, back and forth) needs: a launcher that picks the module by the program's file name; the three calls
implemented as "start another `pentamoor-run` for that program with the same overlay, folder and display settings, and either wait (a `_P_WAIT` mode) or hand over"; `FindWindowA` across processes, or better a rule in the launcher that makes the second start a restore of the first; the display and the audio device handed over (the original
runs two windows of two processes on one screen; here one SDL window cannot be shared, so the second program has to take over the first's window or the first has to exit). The simplest working model: the first program exits after starting the second and the second's exit starts the shell again.
Saves are shared through the overlay already. Both programs write the same registry-like settings (`DuelOptions`, `GauntletOptions`, `SealedDeckOptions`, `ScreenNames`, under `Software\MicroProse\Magic: The Gathering`), which the port ignores today (writes go nowhere, reads fail and the defaults are used): the shell's page settings would not persist.

## What a build profile would have to hold

One record per supported version, chosen by the SHA-256 of the programs (as `tools/install/install.py` already fingerprints 1.0's), which tells `liftrun`, the module build and the runtime what they cannot guess:

- **Lifter**: the programs and libraries of the version, the base each library is lifted at, the master card table (address of the first code pointer, record size, field offset), the code range, the variadic functions of any statically linked runtime (none in SotA), the native entries (or none), the extra import signatures
  (the 47 calls and the libraries' cdecl exports, ideally read from the executables), the unsupported-instruction list (`rol`), and the register-argument functions.
- **Runtime**: a name that is the profile's, not `MAGIC`; the picture decompressor's state per copy (program, deckdll.dll, drawcardlib.dll: `sotalzw.py` finds it) and the offsets of its three entry points; the addresses `pace.c`, `screens.c`, `yesno.c`, `textfocus.c` and `main.c` use (the 54 above: 11 functions, 22 globals and
  locals for the screens, the yes/no sites, the screen-size globals), each marked as verified or not; the window class names `navwm.c` looks for (all present in magic.exe and shandalar.exe, the deck builder's `MAGICDECK_*` live in the library); what the overworld and screen hooks should do in the shell (none of the overworld's loops, button table or
  snapshot exist in magic.exe).
- **Process model**: the list of programs, which is the first, how each starts the others (command lines, window classes), and which libraries each loads.
- **Installer**: the discs (1.0 and 2.0 or just the cabinet), the cabinet's directories, the patch and its files with sizes and hashes, which 1.0 files survive, what to copy from the CD (music, videos, the tutorial if ever), the registry values to invent.
- **Data**: nothing else: CARDS.DAT and the text tables are read by the game as they are.

The cheapest design is a Python file per version beside `tools/install/manifest.py`, read by the installer, the lifter wrappers and a generated C header (`profile_gen.h`, git-ignored) that the runtime includes in place of its hard-coded numbers; the hooks stay in the port and look their addresses up in the profile, and are not installed when
the profile says `verified: false`.

## Other differences

- **Features** (from the readme and the strings): a sealed-deck tournament (`SHELLPAGE_SEALEDDECK`, deck editing in Shandalar and sealed share the deck builder, with the new "Move By Color" and shift-double-click for several copies), a gauntlet that saves the duel in progress with its progress,
  a single-duel page, the tutorial is 1.0's (a Director projector: **not a candidate**, a different project), movable floating windows in the duel (the ante, the mulligan, both hands, the situation bar: a new window kind, `navwm.c`'s targets would need to follow them), minimisable spell chain and combat windows, the new
  portraits, `Exp1Art` (89 files: the expansion's card art in towns), 159 more cards (622 against 463), old decks backed up on install.
- **Data**: the card art is in `cardartlib` and `drawcardlib` now, which draw from `CardArt` and `Exp1Art` themselves (1.0 drew its cards in the program); `.pic` files changed (14 differ, 102 new) in ways the picture reader handled (the decompressor is the same code); `.spr` sprites are 1.0's.
- **The resolution switch**: the shell lays itself out for 800x600; shandalar.exe has 1.0's three layouts (the three screen-size globals at `0x57a7d0` and `0x57a7d4` for 2.15), so `PORT_RES` keeps working for it; magic.exe's screen size is not found (its uses of the 1.0 address did not align).
- **CD checks**: the CdTools library (`CheckOriginalCD`, `CheckSotaCD`, `IsCDDrive`, called by the installer's script and by the programs) asks the drive type and the volume label; the port answers "fixed disk" to `GetDriveTypeA` and has no `GetVolumeInformationA`, so a check that wants the disc would fail. Whether the programs refuse to run without it was not reached.

## Effort (hours of agent work, rough)

| item | hours |
|---|---|
| Profile mechanism: fingerprint, a profile per version, the runtime reads it instead of constants (`pe.c`, `lzw.c` for three copies, `main.c`), hooks installed only for a verified profile, lifter wrappers folded into `gen_handlers.py` and `liftrun.py` | 8 to 12 |
| Lifter: the 47 signatures (best read from the executables), `rol`, reading the master table by its pattern, the libraries' cdecl exports, the second program and five libraries in `liftrun`, `manifest.py`, module build and release layout for two programs | 6 to 10 |
| Win32 and C runtime additions for shandalar.exe (the 21 calls it lacks, 27 for magic.exe; TLS; the update-region calls; registry values for 2.15's start-up; `qsort`, `strcoll`, `_beginthreadex`, `setjmp`/`longjmp` (the lifter has to model `setjmp`: not trivial)) | 8 to 14 |
| Installer: second disc, cabinet and patch (the readers exist), merge over 1.0, fingerprints, music and video copy, the invented registry values; tests | 6 to 10 |
| Process model: the three spawn calls, launcher by program, hand-over of the window, saves and settings shared | 8 to 14 |
| The shell page (magic.exe black screen), the portrait/name screen noise, the CD checks | 8 to 20 (unknown: both are things the port has not met) |
| Porting the hooks (pace, screens, yes/no, name box, controller navigation) to 2.15: read the 19 changed sites against 1.0's, re-verify all 54, find the sell site, adapt `navwm.c` to the movable windows and the shell's pages | 10 to 16 |
| Tests, a soak on both programs, CI (a SotA job cannot use the discs: only the profile logic, the cabinet reader on a made-up cabinet, and the patch reader on a made-up archive) | 8 to 12 |
| **Shandalar alone, without the screen hooks (title, new game, overworld, duels with the mouse)** | **about 40 to 60** |
| **Everything above** | **about 90 to 140** |
| Not counted: the tutorial; the hand-written engine for SotA (new strides and offsets, and the functions with no counterpart); a clean-C pass over the changed parts | 40 and more |

## Risks

- **One build only.** The patch copy is truncated, so 2.15's `deckdll.dll` is missing; everything above that touched it used 2.0's, which is a file the real 2.15 programs would not be run with (the deck builder, which both programs open, is untested). Get a whole `sotav215.exe` before relying on 2.15, and check the three programs' hashes against the community's known-good ones.
- **Two versions never meet**: 2.0 and 2.15 are two profiles (50 of 54 addresses differ). Support one.
- **The matching is not proof**: 19 of the 54 sites are "changed" and two of them are below 0.5. Each needs to be read in both versions and, ideally, checked by running (the oracle VM, `docs/ORACLE_VM.md`: a Windows 98 image with the SotA install would be the way to check 2.15's behaviour, and the VM's disc needs the 2.0 media).
- **Legal and installer**: SotA needs the 1.0 install under it (so two discs are needed from the user), and the installer's checks of the original CD must be reproduced as "the first disc was given", not as a disc check in the game. The registry check in 2.15 reads Windows' own values; inventing them must not look like a bypass of anything else.
  Nothing in this work distributes game files or generated code.
- **Process model and display**: two programs that find each other by window class, on one SDL window, is the least certain part; an unexpected exit path (a program that expects the other to be running) can end the session.
- **The shell never painted**: until it does, nothing is known about the sealed deck page, the gauntlet page, the records, or whether any of it needs more of the port (modeless dialogs through `CreateDialogParamA` are there and unimplemented).
- **The engine**: the hand-written native engine and its differential tests (`tools/difftest`) have 1.0's strides and offsets; the new ones are known for two arrays only. The lifted program runs without them, so this is only a risk for the long-term plan (docs/ROADMAP.md).
- **The lifter's output is large** and each version is two more 50 MB sources to compile locally (a minute each here, more on a slow machine), and an installer that builds both 1.0 and SotA modules takes twice as long.

## The research tools

All in `tools/research/`, each documented at the top, none holding game data (they print counts and addresses); they need `pefile` and `capstone` and use `tools/lift`.

| script | what |
|---|---|
| `iscab.py` | lists and extracts an InstallShield 5 cabinet, from a file or from a disc image |
| `sotapatch.py` | lists and extracts the files of a WinZip self-extractor (the 2.15 patch), checking each entry's CRC |
| `sotatree.py` | compares two installed folders (counts by folder and extension; `--list-new` lists names) |
| `sotacmp.py` | matches the functions of two builds of a program and reports the counts; `--json`, `--map` |
| `sotahooks.py` | finds the addresses `src/port` is keyed to in another build, with the old and new call sites of the hooked functions |
| `sotalayout.py` | the same for `src/native/layout.c` |
| `sotaimports.py` | imports of a build against the port's tables and the lifter's signatures |
| `sotalzw.py` | the picture decompressor's state in another build |
| `liftsota.py` | runs the lifter on another build, with its constants replaced (`liftsota.py dll ...` for the libraries) |
| `sota-runtime-experiment.patch` | the scratch changes to `src/port` that got the title screen up (not applied; it changes 1.0's behaviour only by adding the msvcrt alias and new calls); apply it to a copy to reproduce the runs |

Reproduce, with `sources/installed_sota_215` made by copying `sources/installed_sota` and running `sotapatch.py` on the patch into its `Program` folder:

```bash
python3 tools/research/sotacmp.py sources/installed/Magic/Program/MAGIC.EXE sources/installed_sota_215/Program/shandalar.exe --json /tmp/m.json
python3 tools/research/sotahooks.py sources/installed/Magic/Program/MAGIC.EXE sources/installed_sota_215/Program/shandalar.exe
python3 tools/research/liftsota.py --name sota215_shandalar --exe sources/installed_sota_215/Program/shandalar.exe --master 0x568bcc --stride 0x48 --code-hi 0x562000 \
    --libs <the four libraries, comma-separated> --out sources/generated_sota/lift215_shandalar
```

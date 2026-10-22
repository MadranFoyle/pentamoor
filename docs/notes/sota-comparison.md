# Spells of the Ancients (2.0, 2.15) and ManaLink 3.0 against the 1.0 the port is built from

What it would take to run *Magic: The Gathering "Spells of the Ancients"* (SotA, the 1997 expansion that replaced most of the programs) in Pentamoor, measured on the real files, and what the last official build, the *ManaLink 3.0* add-on (January 1998:
the programs of *Duels of the Planeswalkers*), adds to it. Everything here is from the machine code and
the files of the two discs, the 2.15 patch and the ManaLink installer; nothing was decompiled, and no game file, generated C or screenshot is in the repository. The numbers come from `tools/research/` (the last section), which anyone with the files can rerun.
**2.15 is the target** (it is the last version that has `shandalar.exe`; `sotav215.exe` applies to 2.0 directly and holds six whole files); 2.0 is kept as a second row where it matters; ManaLink 3.0 is a section of its own near the end ("ManaLink 3.0").

*Revision.* The first version of this note was written with a copy of the 2.15 patch that was cut short (its `deckdll.dll` was incomplete and `cards.dat` was missing, and nobody noticed: the reader listed the four whole entries and said nothing of the rest). A complete patch has been
found; this version corrects what that got wrong: the patch has **six** entries, not five (the sixth is `cards.dat`), so **2.15 does change the data** (the readme's change list says nothing of it), the deck library 2.15 runs with is a recompile of 2.0's and not 2.0's own file, and the reader now says when an archive is not whole.

## Summary

- **The programs changed enough that nothing keyed to a 1.0 address survives**, but the lifter did not care: shandalar.exe (the successor of MAGIC.EXE) and magic.exe (a new "Magic Shell" that also carries the duel) lift to C with the lifter as it is,
  after a wrapper that replaces the 1.0 constants (2,050 of 2,058 and 1,747 of 1,756 functions; the rest are the picture decompressor, one or two compiler helpers and two functions with a `rol` instruction), and their libraries, the **complete 2.15 ones**, lift too (with `rol` support, which the
  lifter lacks, all of them lift: the one `rol` function of the deck library *is* on the deck builder's start-up path). With a scratch copy of the runtime with a few hundred lines of experimental changes (the old patch, re-made for the build profiles: a row per file, and the same Win32 additions)
  **shandalar.exe 2.15 runs to the title screen and into a new game's colour choice, and the 2.15 deck builder (the real 2.15 `deckdll.dll`) comes up and draws cards**, headless, checked by eye only; after the colour the game starts a *third program*, `FaceMaker.exe`, and waits for it (a process model the
  port does not have); magic.exe (the shell) still created its window and stayed black at that point (**Milestone 5, below, paints it, runs its pages and its duels, and starts Shandalar from it**). The 2.15 registry check is as it was.
- **Every address the port hard-codes is different**: 0 of 54 hooked 1.0 addresses are where they were, 11 are the same code at a new address, 19 are the same function with changed code (a human has to look), 2 were not found. 2.0 and 2.15 differ from
  each other at 50 of the same 54, so a per-version table of addresses is needed, and only one SotA version should be supported.
- A SotA build is refused today, as it should be: the runtime has build profiles now (`src/port/profile.c`), and a file whose SHA-256 is in no row stops with exit status 3 (`PORT_UNKNOWN_BUILD=1` runs on with every hook off: here it ends within a moment, as the programs import the C runtime as `msvcrt.dll`, a name the unmodified runtime does not know). Tried on the complete 2.15 shandalar.exe and on ManaLink's magic.exe: both exit with status 3.
- Real changes in the engine, not only moved code: the master card record grew from 0x34 to 0x48 bytes (463 to 622 cards), the duel's card slot from 288 to 300 bytes and 81 to 101 slots a player (so `src/native/engine.h`'s strides are wrong for SotA), shandalar.exe 2.15 (and its magic.exe) read two values of
  Windows' own registry key at start and quit without them, the game starts other programs that find each other by window class (a process model the port does not have), and the installer is an InstallShield 5 cabinet that needs the original CD.
- **2.15 changes the data too**: the patch carries a new `cards.dat` (339,984 bytes against 2.0's 330,587): the rules text of 109 cards and the flavour text of 8 changed, two cards were renamed, and 2.15 puts back a per-card sound-file reference in 909 records that 2.0 had emptied. The readme does not list any of it.
- **ManaLink 3.0 is the Duels of the Planeswalkers build of the programs**, not a networking add-on only: its `magic.exe` is linked on 1998-01-14 (the day the game came out), its own version resource says "Duels of the Planeswalker", 6.3b, and its readme says version 3.0 is the Duels of the Planeswalkers standalone version. It brings a larger `magic.exe` (1,948 functions
  against 1,756, a master card table of **722 cards against 622**, and a *different duel layout*: 151 slots a player, 45,300 bytes, against 101 and 30,300), a recompiled deck library, a new online client (`Manalink.exe`, `gcconn.dll`: Winsock and DirectPlay, for a service that is gone) and `ManalinkInterface.dll`, which `magic.exe` calls
  (16 exports, 13 used). **It has no `shandalar.exe`**: it is installed over a SotA install and the Shandalar program stays 2.15's. Details in "ManaLink 3.0".
- **Recommended target: 2.15** (shandalar.exe, magic.exe, DECK.EXE and the 2.15 libraries: one coherent, complete, checked set). ManaLink 3.0's `magic.exe` and libraries are a second layer worth doing later, as one more profile, not as the first target.
- **Where it stands (Milestone 2):** `shandalar.exe` 2.15 plays from the title screen through a new game, the map, the village, a duel against the AI (to a win or a concession, with the reward screens), a save and a load, at 640x480, 800x600 and 1024x768, with its pacing, key-wait and name-box hooks run and verified and every other hook left off; soaked for hours without a crash or a hang. The note's "Milestone 2" section has what ran, what did not, and the table of every site.
- **Where it stands (Milestone 3):** one command installs it: `pentamoor-install "MTG v1.0.iso" --sota "MTG v2.00.iso" --patch SOTAV215.EXE` makes the 2.15 folder from the two discs and the patch, checks every file of it by size and SHA-256, and lifts and builds its modules with the first game's; `./pentamoor sota` then runs it with no setting, in a folder and with saves of its own. The note's "Milestone 3" section has what ran, what did not, the timings and the hours.
- **Where it stands (Milestone 4):** the controller and touch work in 2.15 as in 1.0 on every screen that was played (new game, map, a save and a load, villages and their shop and deck editor, the stats, clues and world map, a castle's gate, duels, the reward screens): the D-pad, A and B, the (Y/N) questions, the view-card button. Every group of hook addresses but one (the card list) is verified, and the screens' addresses are in the profile. The note's "Milestone 4" section has the table of what was run and what was not, the per-hook table, the two questions that were not what the task thought (the sell question is in a function nothing calls; "Take this card?" is a duel-time card picker, not the reward screen) and the hours.
- **Is it the same adventure?** Nearly: the world, its generator, the towns, shops, quests, creature table and World Magics are the same bytes or constants as 1.0's, and the adventure's text is the same sentences; what changed is the **55 opponent deck files** (all rewritten, 20 % of their cards the expansion's) and a few small things (the event log, the collection warning, the duel deck's 100 distinct cards). Evidence, table and limits in [sota-adventure-diff.md](sota-adventure-diff.md).
- Rough size of the work: 36 to 55 hours of agent work for shandalar.exe alone with no hook features, 85 to 130 for the whole 2.15 thing (shell, controller and screen hooks, installer, CI), 15 to 25 more for ManaLink 3.0's programs. Details and risks at the end.

## What there is

| | |
|---|---|
| `MTG v2.00.iso` | the disc label "MTG v2", `Setup/DATA.TAG`: *Spells of the Ancients*, version 2.0, "September 8, 1997: UK Release Build". An **expansion**: its installer (`setup.ins`, compiled InstallShield script) asks for the original CD (`CheckOriginalCD`, `MSG_INSERTORIGINALCD`; `CdTools.dll` is the check), copies the old decks to `Old Decks` and `Old Playdeck`, reads the registry key `SOFTWARE\MicroProse\Magic: The Gathering` (value `1.0` under it), and installs into `C:\Magic` over the existing game |
| `SOTAV215.EXE` (2.15 patch) | a WinZip self-extractor, 1,207,571 bytes, **six entries, all whole, every CRC-32 right**: `shandalar.exe` (1,740,288 B, 1997-10-31), `readme.txt` (37,224 B, 1997-11-07), `magic.exe` (1,530,368 B, 1997-10-20), `FaceData.txt` (208 B), `deckdll.dll` (265,216 B, 1997-10-20) and `cards.dat` (339,984 B, 1997-10-14). The programs are whole files, not deltas. `tools/install/sotapatch.py` reads it (the stub contains false `PK` signatures, so `zipfile` cannot), checks every entry's CRC-32 and the archive's own end record, and extracts to a folder (hashes under "Hashes"); the installer uses its `load`. A second copy, `sotav215.exe` (1,048,331 B), **is cut short**: its last entry (`deckdll.dll`, 89,728 packed bytes) has only 19,716 of them and `cards.dat` is not there at all; the reader reports that copy as `TRUNCATED` with no end record and extracts nothing from it (the first version of this note used it, and so missed `cards.dat` and 2.15's deck library) |
| 2.15 install | 2.0's Program folder with the six files replaced (`Readme.txt` is the patch's `readme.txt`, `CARDS.DAT` the patch's `cards.dat`, by file name ignoring case): `sources/installed_sota_215` (git-ignored). 332 files |
| `ml_sota_us.zip` | the **ManaLink 3.0** installer for the US Spells of the Ancients (see its section): `data1.cab`, `_user1.cab`, `_sys1.cab` and the InstallShield files; extracted to `sources/installed_manalink` (Program files as the cabinet names them) and, over the 2.15 install, `sources/installed_manalink_over215` |

The 2.15 readme's change list ("Changes from version 2.0"), in short: cards of the expansion are now sold in Shandalar's towns; and a dozen card fixes in the duel engine (Black Vise and The Rack no longer deal double damage; Zombie Master-like cards stop working while they
are only in the spell chain; Kismet lets you target either player; Howling Mine, Soul Net and other artifacts with a continuous effect switch off when tapped; Black Lotus can no longer be answered with fast effects; City of Brass does not lose its point of damage;
Contract from Below lets you order the discards; Fastbond works with several in play and with lands that arrive another way than from the hand; Nevinyral's Disk does not tap when the activation is cancelled; Argothian Pixies and Treefolk are not immune to some
direct damage; Disenchanting an Animate Artifact keeps the creature state of an artifact creature; Farmstead sees Gloom's extra cost; Serendib Djinn flies). Nothing in the list is about the installer, the screens, the Windows side or the data files (but `cards.dat` and `deckdll.dll` are in the patch: "2.15 against 2.0", below).
**2.15 is not a binary patch of 2.0**: 2.0 to 2.15 leaves 1,405 of magic.exe's 1,756 functions and 1,595 of shandalar.exe's 2,058 byte-identical (relocations masked), but the rest are mostly re-compiled code (the same operation with its operands swapped,
instructions in another order), so a function's being "changed" says little about the change.

## The installer's format

`Setup/data1.cab`, `_sys1.cab` and `_user1.cab` are InstallShield 5 cabinets (signature `ISc(`, version word 0x01005100; ManaLink 3.0's have 0x01000004 and a different layout of the compressed data, below). `tools/install/iscab.py` lists and extracts them (also straight out of the `.iso`, with `tools/install/iso9660.py`; it was `tools/research/iscab.py` until Milestone 3, which still runs the same command):

- header: the descriptor's offset (0x200) and size; the descriptor holds the file table's offset, size, and the numbers of directories and files; the table is one `u32` offset per directory then per file, relative to the table; a directory is a NUL-terminated
  name (`Program\CardArt`); a file descriptor is 0x2a bytes: name, directory, flags (4 compressed, 2 "obfuscated", 1 split, 8 unused slot), expanded and packed sizes, DOS attributes, date and time, and the offset of the data.
- data, version 0x01005100: a run of chunks, each a `u16` length and that many bytes of raw deflate, inflated one at a time. (The "obfuscated" flag is set on every file of `data1.cab` but the bytes are plain deflate.) There is no separate `data1.hdr`.
- data, version 0x01000004 (ManaLink 3.0's cabinets, made with the earlier InstallShield 5): the same header and file table, but a compressed file is **one raw deflate stream**: no chunk lengths, and no "obfuscated" flag (reading it with the chunk reader fails on the first chunk's "length", which is the stream's first two bytes). `iscab.py` picks the layout from the version and falls back on the other when the size does not come out; read against the 2.0 disc it still gives 335 entries and 70,587,570 bytes.
- `data1.cab`: 17 directories (`Program` and its art, deck, sound, video and tutorial subfolders), **335 entries, 70,587,570 bytes expanded, 55,435,910 packed**; they extract to 332 files in `Program` plus three at the top (`Readme.txt` and two `.url`s). `_sys1.cab`: 4 files (two DLLs, an
  ini, an exe, 495,478 bytes). `_user1.cab`: 23 files (20 bitmaps, a text, a `.jbf`, a `.shl`; 3,993,895 bytes). The installer itself (`SETUP.EXE`, `_INST32I.EX_`, `setup.ins` 67,768 bytes) is a compiled script: not read further.
- The disc also carries what the game reads from the CD, as 1.0's does: `Sound` (31 WAV), `StatWin` (68 AVI), `DuelSounds` (the shell's voice clips), and `Tutorial` (the Director projector `TUTORIAL.EXE`, 1.4 MB, with 13 chapter files, which 1.0's install has too, and 13 wizard videos of 1 to 35 MB), the autoplay program and
  its intro movies, and a copy of DirectX.

**What an installer for it has to do** (done in Milestone 3: `tools/install/sotainstall.py`, see its section): take two discs (the 1.0 disc first, then this one; Pentamoor's installer today takes one), install 1.0 as it does now, then extract the cabinet over it (`Program` of the new folder replaces files of the old: 93 files exist in both and differ, 11 are the same, 228 are new, and 976
of 1.0's stay, among them every sprite and most pictures: SotA **needs the 1.0 art**), apply the patch (six files: `sotapatch.py` extracts them over the Program folder, which the case-insensitive file system turns into replacements of `CARDS.DAT` and `Readme.txt`), take the CD files from the 2.0 disc as well (22 WAV), and fingerprint the programs. (The original installer also wrote registry values; Pentamoor's installer writes none: Milestone 3.)

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

## 2.15 against 2.0: the six files of the patch

| file | 2.0 | 2.15 | what changed |
|---|---|---|---|
| `shandalar.exe` | 1,739,264 B, linked 1997-09-02 | 1,740,288 B, 1997-10-31 | 1,595 of 2,058 functions byte-identical, 343 at 0.9 to 1.0, 90 at 0.7 to 0.9 (the card fixes; and the start-up's registry check, which the first version of this note found in 2.15 and not in 2.0) |
| `magic.exe` | 1,529,856 B, 1997-09-03; version 6.2 | 1,530,368 B, 1997-10-20; 6.2.1 | 1,405 of 1,756 identical, 281 at 0.9 to 1.0; 2.15's also makes the registry calls |
| `deckdll.dll` | 264,192 B, 1997-09-03; version 6.0 | 265,216 B, 1997-10-20; **6.3** | the real 2.15 file, compared for the first time: 370 functions each, 327 byte-identical, 29 at 0.9 to 1.0, 12 at 0.7 to 0.9, 1 at 0.5 to 0.7, 1 below; none added or removed |
| `cards.dat` | 330,587 B | 339,984 B | below |
| `FaceData.txt`, `readme.txt` | | 208 B; 37,224 B | the portrait list; the readme of "2.15, 7 November 1997" |

**`CARDS.DAT`** (`tools/research/sotacards.py`; no card text is printed, only counts and at most three names). The file is, little-endian: a `u32` count (999), a `u32` size of the string pool, 999 records of 152 bytes (38 `u32`: the card's id, four references into the pool for the full name, the short name, the rules text and the flavour text, and numbers: type
and colour flags, cost, power and toughness, ...; up to four more (columns 19 to 22) are names of per-card sound files such as `NNNN.wvl` (the first in 909 records of 2.15's file, the others in a handful)), then the pool; **the file's size is exactly 8 + 999 x 152 + the pool in all four builds**. It is **not the master card table**: that is an array in the program (0x34 bytes a record in 1.0, 0x48 in SotA, with the code pointer of the card's rules at +0x10, and a name inline),
463, 622 and 722 records long. `cards.dat` supplies the texts and descriptive numbers of all the cards the file names (928 or 929), implemented or not.

| build | bytes | pool | slots | names |
|---|---|---|---|---|
| 1.0 | 325,187 | 173,331 | 999 | 928 different card names, and 71 slots named "Blank" |
| 2.0 | 330,587 | 178,731 | 999 | 929 card names, 70 slots named "None" |
| 2.15 | 339,984 | 188,128 | 999 | the same 929, 70 "None" |
| ManaLink 3.0 | 340,009 | 188,153 | 999 | the same 929, 70 "None" |

| from -> to | names added / removed | cards with another rules text | flavour text | short name | numeric fields | sound-file references |
|---|---|---|---|---|---|---|
| 1.0 -> 2.0 | 4 / 4 (spelling fixes: "Abu Jafar" to "Abu Ja'far", "Argivian Archaeoligist" to "Archaeologist"; "Blank" to "Data Card") | 277 | 145 | 2 | 28 | 1.0 has one in 889 records, 2.0 **in none** |
| 2.0 -> 2.15 | 2 / 2 ("The Drowned" to "Drowned"; "Ring of Maruf" to "Ring of Ma'rûf") | 109 | 8 | 6 | 5 | **909 records again have one** (the 2.0 file had emptied them) |
| 2.15 -> ManaLink 3.0 | 0 / 0 | 13 | 29 | 2 | 2 | 0 |

(No card moved to another id: a renamed card stays in its slot.) So **2.15's data change is mostly text** (109 cards' rules text: far more than the dozen card fixes the readme lists, so most are typographic) **and the return of the per-card sound references**; what the game does with the `.wvl` names was not followed (no `.wvl` file is in any of the installs, so they come from a disc folder or are unused).
**ManaLink's `cards.dat` is 2.15's with 40 cards' text touched**, and **the 80 (really 100) new cards are not in it as news**: the 929 names are the same in 2.0, 2.15 and ManaLink (1.0's differ in a handful of spellings), and the cards ManaLink's table adds (checked by name on a few, e.g. "Crimson Kobolds", "Mountain Yeti", "Goblin Hero") already have their text in **1.0's** file. The data for Legends and The Dark was there from the start;
what is new in 3.0 is the code in the program's master table (722 records, 103 with a name 2.15's table lacks) and the deck builder's two set buttons.

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
| deckdll.dll 2.0 -> 2.15 (the real 2.15 file) | 370 | 370 | 327 | 0 | 29 | 12 | 1 | 1 | 0 | 0 |
| magic.exe 2.15 -> ManaLink 3.0 | 1756 | 1948 | 791 | 6 | 119 | 257 | 322 | 216 | 45 | 237 |
| magic.exe 2.0 -> ManaLink 3.0 | 1756 | 1948 | 783 | 6 | 115 | 264 | 316 | 229 | 43 | 235 |
| DUEL.EXE 1.0 -> magic.exe ManaLink 3.0 | 1837 | 1948 | 433 | 6 | 101 | 186 | 199 | 332 | 580 | 691 |
| MAGIC.EXE 1.0 -> magic.exe ManaLink 3.0 (cross) | 1956 | 1948 | 333 | 12 | 86 | 170 | 197 | 339 | 819 | 811 |
| shandalar.exe 2.15 -> magic.exe ManaLink 3.0 (cross) | 2058 | 1948 | 577 | 27 | 145 | 263 | 326 | 246 | 474 | 364 |
| deckdll.dll 2.15 -> ManaLink 3.0 | 370 | 672 | 322 | 5 | 29 | 13 | 1 | 0 | 0 | 302 |
| deckdll.dll 2.0 -> ManaLink 3.0 | 370 | 672 | 308 | 5 | 39 | 15 | 2 | 1 | 0 | 302 |
| DECKDLL.DLL 1.0 -> deckdll.dll ManaLink 3.0 | 684 | 672 | 463 | 0 | 46 | 63 | 34 | 20 | 58 | 46 |
| cardartlib.dll 2.15 (= 2.0) -> ManaLink 3.0 | 326 | 326 | 316 | 0 | 4 | 6 | 0 | 0 | 0 | 0 |
| drawcardlib.dll 2.15 (= 2.0) -> ManaLink 3.0 | 359 | 359 | 345 | 0 | 8 | 6 | 0 | 0 | 0 | 0 |
| CdTools.dll 2.15 (= 2.0) -> ManaLink 3.0 | 171 | 172 | 171 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |


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
| deckdll.dll 2.0 -> 2.15 (the real 2.15 file) | 284 | 282 | 0 | 0 | 122892 | 185756 | 66% |
| magic.exe 2.15 -> ManaLink 3.0 | 1555 | 1727 | 39 | 220 | 211527 | 1277033 | 17% |
| magic.exe 2.0 -> ManaLink 3.0 | 1551 | 1727 | 34 | 219 | 210875 | 1276195 | 17% |
| DUEL.EXE 1.0 -> magic.exe ManaLink 3.0 | 1473 | 1727 | 396 | 660 | 61633 | 971687 | 6% |
| MAGIC.EXE 1.0 -> magic.exe ManaLink 3.0 (cross) | 1624 | 1727 | 599 | 721 | 45093 | 1123655 | 4% |
| shandalar.exe 2.15 -> magic.exe ManaLink 3.0 (cross) | 1868 | 1727 | 435 | 305 | 121809 | 1442629 | 8% |
| deckdll.dll 2.15 -> ManaLink 3.0 | 282 | 543 | 0 | 281 | 120674 | 186431 | 65% |
| deckdll.dll 2.0 -> ManaLink 3.0 | 284 | 543 | 0 | 281 | 102840 | 185756 | 55% |
| DECKDLL.DLL 1.0 -> deckdll.dll ManaLink 3.0 | 556 | 543 | 49 | 30 | 39555 | 197496 | 20% |
| cardartlib.dll 2.15 -> ManaLink 3.0 | 301 | 301 | 0 | 0 | 99302 | 104854 | 95% |
| drawcardlib.dll 2.15 -> ManaLink 3.0 | 327 | 321 | 0 | 0 | 109225 | 121414 | 90% |
| CdTools.dll 2.15 -> ManaLink 3.0 | 162 | 163 | 0 | 1 | 51213 | 51213 | 100% |

What the tables say:

- **shandalar.exe is MAGIC.EXE's successor**: 1,567 of 1,956 old functions have a counterpart (80%), against 61% for magic.exe, but only 579 (30%) are byte-identical; those are small (10% of the old bytes). The rest differ by the compiler (the 2.0 programs were built
  with other settings and a release C runtime) and by real changes: new features, and **structure sizes**: in the pairs at 0.5 to 0.7, the common difference is one multiplication. The duel's slot table is indexed as `player * 23328 + slot * 288` in 1.0 (`SLOT_PLAYER_STRIDE 0x5b20`,
  `SLOT_STRIDE 0x120` in `src/native/engine.h`) and the compiler's replacement for the multiplication is `x*9*9*9<<5` and `x*9<<5`; in 2.0 and 2.15 it is `x*63*8+x<<2 *3 *5` and `x<<2 *5 *3 *5`: **30300 and 300**, i.e. 101 slots of 300 bytes. The hand-written engine
  (`src/native`, `layout.c`) is therefore unusable for SotA without new constants and new field offsets.
- **magic.exe is not a DUEL.EXE**: it is a program of its own that carries a copy of the duel code: 1,258 of DUEL.EXE's 1,837 functions (69%) have a counterpart in it, 1,200 in shandalar.exe, and the same duel code is in both (1.0's MAGIC.EXE also carried it).
- **The DLLs**: STATWIN, MAGVID and MAGSND are mostly the same code (60 to 66% of the bytes identical; the exports are the same 3, 20 and 27 names, so the host-made MAGSND and MAGVID of the port still fit by name). DECKDLL changed more (20% of the bytes), and DECK.EXE is a different, tiny program (linked 1997-03-21 and the same file in 2.0 and 2.15: it starts the deck builder that `deckdll.dll` holds).
- **2.0 to 2.15** moved nothing big: one program per row, 2 functions of shandalar.exe appear and 2 go. **The deck library is the same**: with the real 2.15 `deckdll.dll`, 370 functions against 370, 327 byte-identical, 29 at 0.9 to 1.0, 12 at 0.7 to 0.9, none added or removed (a recompile with small changes: its version resource says 6.3 where 2.0's says 6.0).
- **ManaLink 3.0's `magic.exe` is a bigger step than 2.0 to 2.15**: of 2.15's 1,756 functions 791 are byte-identical (45%; 80% from 2.0 to 2.15), 45 have no counterpart, and 237 of its 1,948 are new (the multiplayer module); only 17% of the old bytes are identical against 57% for 2.0 to 2.15. The reason is probably the layout of the duel (below: the table of strides) rather than the new code,
  since every function that indexes a player's slots has another constant. Its libraries are close to 2.15's: `cardartlib.dll` 316 of 326 functions identical (95% of the bytes), `drawcardlib.dll` 345 of 359 (90%), `CdTools.dll` identical but for one new function and export (`CheckDoPCD`); the deck library is not (next bullet).
- **ManaLink's `deckdll.dll` is a different build of the library**: 355,840 bytes, 672 functions against 370, **a debug-configuration link** (its debug directory names `D:\NEWMAGIC\DeckBuilder\Debug\deckdll.pdb`; no other build here has one), unoptimised and with no dead code removed: 626 of its 672 functions have a counterpart in 1.0's `DECKDLL.DLL` (463 byte-identical to 1.0's) and 370 have one in 2.15's (322 identical);
  298 functions exist in it and in 1.0's and not in 2.15's (small ones: 13,869 bytes). The exports are 2.15's six, and the host interface (the ten names it asks its program for: `CardIDFromType`, `CardTypeFromID`, `CardInDeck`, `SetCardInDeck`, `SellPrice`, `deck`, `Gold`, `Scards`, `szDeckName`, `_currentDeck`) is the same ten as 2.15's library asks.

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

- the master card table: 622 records of **0x48** bytes (1.0: 463 of 0x34); the code pointer is where the first run of code pointers starts: `0x568bdc` in shandalar.exe 2.15 (master `0x568bcc` with the handler at +0x10), `0x54800c` in magic.exe (`0x547ffc`). It is found by looking for the run, not read from a known address (`tools/research/sotamaster.py` does it: the longest run of records `stride` bytes apart whose +0x10 field points into the code; 622 records and 528 distinct handlers in both 2.15 programs);
  the dispatch is `call [eax+eax*8+X]` (four sites in shandalar.exe), not 1.0's `call [eax*4+X]`, and `gen_handlers.py` refuses a function that makes an indirect call in another form (none was refused here: `--no-handlers`, which is what the port uses, does not need the table, only the scan does);
- 47 Windows and C runtime calls the lifter has no signature for (all of them new: `sotaimports.py` lists them), and every export of the three new libraries, which are `cdecl` (found from their `ret`): `signature()` only knows the C calling convention for the C runtime; with those added, no function is refused for a missing signature;
- one unsupported instruction (`rol`: 2 functions of each program and one in the deck library, which the first version of this note said was in no hot path: **it is on the deck builder's start-up path**, found only once the real 2.15 library could be run) and the picture decompressor (5 functions, handled by hand as in 1.0, see below);
- `chkstk` and `allshl` helpers are recognised as before. Register-argument functions: none new.

**Result (the complete 2.15, with its own six files; 2.0 is the same to the function; ManaLink 3.0 in its section):**

| program | functions found | lifted | not lifted |
|---|---|---|---|
| shandalar.exe | 2,058 | 2,050 | 8: the decompressor (5), `chkstk` (inline), 2 with `rol` (one dead code, one reached from nothing the scan finds) |
| magic.exe | 1,756 | 1,747 | 9: the decompressor (5), `chkstk` and `allshl` (inline), 2 with `rol` |
| DECK.EXE (the stub) | 27 | 27 | 0 |
| deckdll.dll (the real 2.15 file) | 203 | 202 | 1: `rol` (**it is called when the deck builder starts**: the run stops there with "a call to 0x3200e1aa, which is neither a lifted function nor an import") |
| cardartlib, drawcardlib, CdTools | 295, 280, 150 | all | 0 |

With `rol` and `ror` added to the lifter (a dozen lines for 8, 16 and 32 bits, a scratch change not in this PR) the deck library lifts completely (204 functions) and the deck builder runs. (`docs/PHASE_C.md` gives 97% for 1.0's MAGIC.EXE, counted at an earlier state of the scan; here it is 99.6%.) The generated C is 55 MB for shandalar.exe and 49 MB for magic.exe, as large as 1.0's, and each module builds with the port's own flags in
under a minute. A new lift of a build needs: `liftsota.py --name NAME --exe PROGRAM --master ADDR --stride 0x48 --code-hi ADDR --libs <the libraries> --out DIR` (the master table's address is what `sotamaster.py` prints) and then `liftsota.py dll <the libraries> --dll LIB --base 0x32000000 ...` for each library (bases 0x32000000 deckdll, 0x34000000 cardartlib, 0x36000000
drawcardlib, 0x38000000 CdTools) and `--finish`; for the DECK.EXE stub `liftsota.py dll <libraries> --main --dll DECK.EXE`.

**Imports.** shandalar.exe imports 339 functions and magic.exe 315; 23 and 29 of them are not imported by any 1.0 program. The port's tables lack **21 (shandalar.exe) and 27 (magic.exe)** of those (42 over both programs and the three new libraries; EqualRect and SetRectEmpty, new, are there already), and the lifter has no signature for 47:

- both programs: `RegOpenKeyA`, `RegCreateKeyA`, `GetFileTitleA`, `ExtTextOutA`, `RectInRegion`, `GetThreadTimes`, `GetVersionExA`, `GetWindowsDirectoryA`, `ResumeThread`, `SuspendThread`, `WinExec`, `GetUpdateRect`, `GetUpdateRgn`, and `_beginthreadex` from the C runtime;
- shandalar.exe only: `ChangeDisplaySettingsA`, `GetDiskFreeSpaceA`, `_spawnl`, `_setjmp3`, `longjmp`, `qsort`, `strcoll`;
- magic.exe only: `CreateProcessA`, `FindFirstFileA`, `FindClose`, `CreateDialogParamA`, `IsDialogMessageA`, `GetWindowTextLengthA`, `IsCharAlphaNumericA`, `ShowScrollBar`, `GetCursor`, `CharLowerA`, `CharUpperA`, `mciSendCommandA`, `mciGetErrorStringA`;
- the new libraries: `TlsAlloc`, `TlsFree`, `TlsGetValue`, `TlsSetValue` (their C runtime starts per-thread data), `GetLocaleInfoA` and `W`, `GetVolumeInformationA` (the CD check), `GetDiskFreeSpaceA`, `GetVersionExA`, `RegisterWindowMessageA`.
- **The C runtime's name**: the port finds an import by the library's name as written, and its tables say `msvcrtd.dll`; SotA's programs import `msvcrt.dll`, so 77 more calls of shandalar.exe (the C runtime's: 101 are not found as written, 24 after the alias) are "not implemented" until the name is treated as an alias (a one-line change in `pe.c`; it is in the experimental patch).
- The libraries MAGSND.DLL and MAGVID.DLL have the same exports as 1.0's, so the host-made ones still fit.

**Running it** (a scratch copy of the repository, not committed: `src/port` with the old `tools/research/sota-runtime-experiment.patch` re-made for the build profiles. The patch no longer applies to `lzw.c`, `modules.c` and `port.h`, which the profile refactor rewrote, but its other five files do (`crt.c`, `gdi_text.c`,
`kernel32.c`, `pe.c`, `user32.c`); what the profiles replace is now **a row in `profile.c` for each file** (its SHA-256, `.program` = the module's name, `.base` for a library, and `.lzw` = the picture decompressor's state that `sotalzw.py` prints: `block` = 1.0's block + the printed delta), and `lzw.c` gets a second library slot
(drawcardlib.dll has a copy of the decompressor, deckdll.dll another). No hooks: the rows hold nothing else. The folder run is **1.0's install with the 2.15 files over it** (`sotaoverlay.py`: SotA needs 1.0's art; without it the first run stops at "File fonts.cv could not be opened"); the modules were made with the port's Makefile from the lifted C; `SDL_VIDEODRIVER=dummy`;
the pictures were looked at by eye and are not kept):

- **shandalar.exe 2.15: the title screen draws** (640x480, as 1.0's), a click on "Start New Game" brings up "Select Your Color" correctly. **Choosing a colour calls `_spawnl(_P_WAIT, FaceMaker.exe, ...)`** (from `0x53a88e`: the new portrait editor of 2.0 runs here, and the game waits for it); with the call stubbed the window goes black.
  The earlier note's "name screen that draws garbage" was not seen again: it was probably what the game drew while its helper program had not run. So starting a new game needs a **third program**, `FaceMaker.exe` (76,288 bytes, linked 1997-09-02, the same file in 2.0 and 2.15), run and waited for: the process model below, and one more thing to lift.
- **The 2.15 registry check is as it was**: the start-up of shandalar.exe opens `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion` (two `RegOpenKeyA` calls) and, with no answer, the program ends with status 0 (the same with the real 2.15 files and the real 2.15 `deckdll.dll`; 2.0 has no such code); magic.exe 2.15 makes the same two calls. The experiment answers with two made-up values to go on. What the machine string
  is used for is still not followed.
- **The deck builder works with the real 2.15 library**: `DECK.EXE` (the stub) with the 2.15 libraries lifted shows "Deck Maker" (800x600): the card art, the card in full, the filters and the first row of the card list. Needs the `rol` support above. The host interface the library asks its program for by name (ten names) is the same as before.
- **(Solved in Milestone 5, below: the update region was cleared before the paint routine asked for it.)** **magic.exe 2.15, the shell, stays black** (800x600, with the 2.15 libraries): the window class is registered, the window (about forty buttons and labels) is created and **is** shown now (`WM_SHOWWINDOW`, `WM_ACTIVATE`, `WM_SIZE` arrive; the first note said `ShowWindow` was never called), the window is visible and invalid with a client area, and its message loop runs about 25 passes a second on timer messages; no CD
  call, and the same two registry calls. Changing the port's message order so that a pending `WM_PAINT` comes before `WM_TIMER` (as in Windows) changed nothing. The picture it waits for is not found: not solved.
- Not tried: a duel, the overworld, a save, sound, `FaceMaker.exe`, the sealed deck and gauntlet pages, and everything that needs a second program.
- **Unknown builds are refused**: the unmodified runtime (built from this tree) run on the 2.15 module and on ManaLink's gets "shandalar.exe is build e4e46718c451..., which this version does not support (supported: v1.0 ...)", and exits with status 3; `PORT_UNKNOWN_BUILD=1` goes on with every hook off (and ends within a moment: the `msvcrt.dll` imports are not found without the alias).

**The process model.** (Built in Milestones 1 and 5; the end of Milestone 5 says what the runtime does now and where it stops. The text that follows is the plan the first note made.) The port has no `CreateProcess`: `WinExec`, `CreateProcessA` and `_spawnl` are not implemented, and the runtime is one program per process with one module. The shell start-up (magic.exe first, then Shandalar, back and forth) needs: a launcher that picks the module by the program's file name; the three calls
implemented as "start another `pentamoor-run` for that program with the same overlay, folder and display settings, and either wait (a `_P_WAIT` mode) or hand over"; `FindWindowA` across processes, or better a rule in the launcher that makes the second start a restore of the first; the display and the audio device handed over (the original
runs two windows of two processes on one screen; here one SDL window cannot be shared, so the second program has to take over the first's window or the first has to exit). The simplest working model: the first program exits after starting the second and the second's exit starts the shell again.
Saves are shared through the overlay already. Both programs write the same registry-like settings (`DuelOptions`, `GauntletOptions`, `SealedDeckOptions`, `ScreenNames`, under `Software\MicroProse\Magic: The Gathering`), which the port ignores today (writes go nowhere, reads fail and the defaults are used): the shell's page settings would not persist.

## ManaLink 3.0 (Duels of the Planeswalkers)

**What it is.** `ml_sota_us.zip` is the installer of the official MicroProse add-on *Magic: The Gathering "Manalink"*, version 3.0 for the US *Spells of the Ancients* (`DATA.TAG`: Company MicroProse Software, Application `Magic: The Gathering"Manalink"`, Version 3.0, "Misc=JAN 6, 1997" [sic]; the files are dated January 1998). It is an InstallShield 5 installer
(`SETUP.EXE` 59,904 B, the compiled script `setup.ins` 56,294 B, `data1.cab` 4,591,805 B with **69 files, 9,162,642 bytes expanded**, `_user1.cab` with one file (`value.shl`, 958 B), `_sys1.cab` with the four InstallShield helper files (492,170 B)). The cabinets are `ISc(` version 0x01000004, which `iscab.py` could not read until it learned the
single-stream layout (see "The installer's format").

**Where the files go** (strings of `setup.ins`; the script is compiled and was not read further): like 2.0's installer it reads `HKLM\SOFTWARE\MicroProse\Magic: The Gathering\1.0`, value `Path2` (where the game is), then requires `Program\menusx1.txt` there (a file that exists from SotA 2.0 on and not in 1.0's install: the add-on **refuses a plain 1.0**, with an error text that says the game must be installed first), and copies the cabinet's `Program\` tree over that folder. No CD check and no backup of old decks (none of 2.0's script strings for those, `CheckOriginalCD`, `CheckSotaCD`, `Old Decks`, is in this one); a program-folder entry "ManaLink" for `Program\Manalink.exe` (the string ` RUNFROMSHELL` is next to it)
and an uninstaller. On a 2.15 install: of the 69 files **14 replace a file** (`magic.exe`, `deckdll.dll`, `cardartlib.dll`, `drawcardlib.dll`, `CdTools.dll`, `CARDS.DAT`, `Legacy.csv`, `MENUS.TXT`, `UIStrings.txt`, `Readme.txt`, four of `ShellArt`), 1 is identical (`CardArt\ManaStripes.pic`) and **54 are new**; `sources/installed_manalink_over215` is that result
(`sotaoverlay.py`, which replaces ignoring case as Windows does). The 2.15 `shandalar.exe`, `DECK.EXE`, `STATWIN.DLL`, `FaceMaker.exe`, the card art catalogues, the decks and the sprites are not touched.

**What is in it** (`sources/installed_manalink`):

| group | files |
|---|---|
| programs | `magic.exe` 1,700,864 B (2.15's: 1,530,368); `deckdll.dll` 355,840 (265,216); `cardartlib.dll` 139,264 and `drawcardlib.dll` 178,176 (same sizes as 2.15's, different bytes); `CdTools.dll` 75,264 (74,752; a sixth export, `CheckDoPCD`, next to `CheckOriginalCD` and `CheckSotaCD`); **`Manalink.exe`** 304,640 (the online client), **`ManalinkInterface.dll`** 46,080, **`gcconn.dll`** 188,416 |
| data | `cards.dat` 340,009 (2.15's: 339,984), `Legacy.csv`, `Names.dat` (16,726 B of nearly nothing: it packs to 211), `menus.txt`, `UIStrings.txt`, `MP_UIStrings.txt` (the multiplayer strings), `PromptsX2.txt`, `tengame.ini` (the TEN service's installer path), `TT0127M_.TTF`, `manalink.txt` (the client's messages), `Credits.txt`, `readme.txt` (71,983 B) |
| art and sound | `ManaLink\Default` (20 bitmaps and 9 badge bitmaps: the client's windows), `ManaLink\Sounds` (9 WAV), `DBArt\legends.pic` and `dark.pic` (the deck builder's set buttons for **Legends** and **The Dark**; 2.15 has `antiquit.pic` and `arabnite.pic`), `shellart` (6: credits and shell screens, 16-bit bitmaps and `.pic`), `ScreenNames` (two files), `CardArt\ManaStripes.pic` |
| not in it | `shandalar.exe`, `DECK.EXE`, `STATWIN.DLL`, `MAGSND.DLL`, `MAGVID.DLL`, `FaceMaker.exe`, any card-art catalogue (`MedArt.cat`, `SmallArt.cat`), any deck (its readme says the Duels of the Planeswalkers installer adds new decks to the playdeck folder: this add-on does not) |

**Is its `magic.exe` the Duels of the Planeswalkers build?** The file says so itself, so it can be answered without the DotP disc (which was not looked at): 

1. its version resource: product name "Magic: The Gathering  Duels of the Planeswalker", file version **6.3b**, internal name `exp2` (2.0's magic.exe says `exp1`, 6.2; 2.15's 6.2.1); the source paths of its objects are `D:\Newmagic\multiplayer\...` (SotA's are `D:\Newmagic\sources\...`);
2. its link time is **1998-01-14 14:28:44 UTC**; the libraries were linked between 14:21 and 14:23 the same day, `Manalink.exe` at 14:30 and `ManalinkInterface.dll` at 14:29 (the cabinet's own file times are 09:21 to 09:30 on 1998-01-14: the same moments in US Eastern time). *Duels of the Planeswalkers* was released on 1998-01-14 (Wikipedia, as given);
3. its `readme.txt` is dated 14 January 1998 and its FAQ says that version 3.0 is the latest version, that it is the Duels of the Planeswalkers standalone version with the original game's features, a multiplayer module and 80 new cards; it also speaks of the Duels of the Planeswalkers CD and the `Ten` folder on it;
4. the features: a master card table of **722 cards against 622** (below), the deck builder's `legends.pic` and `dark.pic` (the two sets the 80 new cards come from), `CheckDoPCD` in the CD library, the multiplayer pages and `MultiOptions` in the shell.

What this does **not** show is that the retail DotP disc's `magic.exe` is byte-for-byte this file: the add-on is how SotA owners got the same version, so the two should be the same build, but only the disc (or the DotP patch executable, which is out of scope here) could say. The hash is below.

**What changed in `magic.exe`** (strings and imports against 2.15's): new shell pages `SHELLPAGE_MULTIDUEL`, `SHELLPAGE_ENTERSCREENNAME` and `SHELLPAGE_BLANK`, a window class `fam_WindowClass`, the registry key `Software\MicroProse\Magic: The Gathering\MultiOptions`, screen-name files (`ScreenNames\%s.scn`, `ActiveName.dat`), opponent pictures
(`Manalink\Opponent.pic`, `me.pic`), a credits page (`Credits.txt`, `WINBK_Credits.pic`), a version check of the opponent's program through `version.dll` (`GetFileVersionInfoA`, `VerQueryValueA`: `FamInterface_SetDuelVersion`), and it **starts `manalink.exe RUNFROMSHELL`**. It imports 13 of `ManalinkInterface.dll`'s 16 exports (`FamInterface_IsHost`, `HasOpponent`,
`SendPacket`, `ReceivePacket`, `SendFile`, `PostDuelResult`, `SetDuelState`, `Taunt`, `Flush`, `EndSession`, `IsNetworkTEN`, `SetDuelVersion`, `UpdateScreenName`), so the multiplayer is a small, clean interface that a host-made library could answer with "no network, no opponent". `Manalink.exe` is the online client: **Winsock and DirectPlay** (`wsock32.dll`: 20 calls;
`dplayx.dll` by ordinal; 221 imports, 44 of them in no 2.15 program), `gcconn.dll` (46 exports, `Gc*_new/_del`: the connection to the TEN service, linker 5.00) and the shared window class `MAGICGAME_MagicShellClass` to find the shell. The TEN service the client names (`TEN\setup.exe`) is gone, so none of this can be tested online and none of it is needed for a single-player port.

**The duel layout changed** (found with `sotastride.py`, which follows the compiler's multiplication sequences; a "site" is one sequence):

| program | master record | duel slot | slots a player | cards in the master table |
|---|---|---|---|---|
| 1.0 `MAGIC.EXE`, `DUEL.EXE` | 0x34 | 288 (DUEL.EXE: 6,520 sites in 647 functions) | 81 = 23,328 (6,503 in 644) | 463 (383 distinct handlers) |
| 2.0 and 2.15 `shandalar.exe` | 0x48 | 300 (8,242 in 748) | 101 = 30,300 (8,176 in 739) | 622 (528) |
| 2.0 and 2.15 `magic.exe` | 0x48 | 300 (8,199 in 744) | 101 = 30,300 (8,138 in 735) | 622 (528) |
| **ManaLink 3.0 `magic.exe`** | 0x48 | 300 (8,786 in 839) | **151 = 45,300** (8,713 in 825; 45,600, 152 slots, in 56 sites in 31 functions) | **722 (608)** |

The master record size and the slot size are the same as 2.15's, so the per-card code and the slot's fields are likely the same; the **number of slots a player has grew by half and the table by 100 cards** (103 of the 722 records have a name 2.15's table lacks, from record 548 on; the first 548 are the same names in the same order). Every function that indexes a player's slots is therefore
a different function, which is most of why only 45% of 2.15's functions are byte-identical. For a lifted program this does not matter (the lifter works on the machine code); for the hand-written engine (`src/native`) it would be a third set of strides.

**Does ManaLink's `magic.exe` still work with 2.15's `shandalar.exe`?** It was designed to, and what could be checked agrees; nothing could be *run* together (the port has no process model yet, and the Windows 98 oracle VM was not used for this):
- the installer ships no `shandalar.exe` and requires a SotA install, so the supported combination is exactly "ManaLink's magic.exe and libraries with SotA's shandalar.exe";
- the way each starts the other is unchanged: the function in `magic.exe` that builds `<dir>\Shandalar.exe /MTGshell` is **byte-identical** (score 1.00) to 2.15's, and `shandalar.exe` still builds `\Magic.exe /start3,1` (it is 2.15's own file); both still find the shell by the class `MAGICGAME_MagicShellClass` and the title "Magic Shell"; the shell's start-up function, which handles `/start`, changed
  (0.51: it grew the `manalink.exe RUNFROMSHELL` start);
- the registry root and the keys they share (`DuelOptions`, `GauntletOptions`, `GauntletEx1Options`, `SealedDeckOptions`, `SoloOptions`, `ScreenNames`) are the same strings; `MultiOptions` is new and only ManaLink's programs read it;
- the interface between a program and the deck library (the ten names the library asks the program for) is unchanged, and the library's six exports are the same, so 2.15's `shandalar.exe` can load ManaLink's `deckdll.dll`, which is what the installer arranges; the master record size (0x48) and the duel slot (300) are unchanged.
What differs and could break a mixed install: the **slot count** (a duel state saved by one program is not the other's: the gauntlet saves a duel in progress; whether a saved duel crosses is unknown) and the **card count** (a deck made with the 100 new cards, which `shandalar.exe`'s table of 622 does not have, may not load there: unknown).
What was run: `DECK.EXE` (2.15's stub) with ManaLink's libraries, lifted and run in the port, shows the same deck builder, with a longer card list (its seventh card is "Ali from Cairo" where 2.15's is "Amrou Kithkin"), so the library's start-up and drawing work with the 2.15 stub.

**Lifting and running ManaLink's programs** (`liftsota.py` as for 2.15, with 23 more signatures it lacked (`liftsota.py` has them): `CreateMutexA`, `CreateEventA`, `FindNextFileA`, `GetFileVersionInfoA`, `ExcludeClipRect`, `_beginthread`, `strftime`, `localtime` and the like):

| program | functions found | lifted | not lifted |
|---|---|---|---|
| magic.exe | 1,948 | 1,939 | 9: the decompressor (5), `chkstk` and `allshl` (inline), 2 with `rol` |
| deckdll.dll | 672 (found by the scan; the lift reaches 1,010) | 1,008, 1,010 with `rol` support | 2 with `rol` |
| cardartlib, drawcardlib, CdTools | 295, 280, 151 | all | 0 |
| ManalinkInterface.dll | 108 | 106 | 2: a jump table with no bound check in front of it (`0x3a001f70`) and a one-operand `imul` (`0x3a006620`) |

Imports: `magic.exe` imports 331 functions (25 from the game's own libraries); **43** are not in the port's tables even with the msvcrt alias (29 for 2.15's magic.exe); the 15 new against every 2.15 program are `CreateMutexA`, `ReleaseMutex`, `FindNextFileA`, `SetFileAttributesA`, `ExcludeClipRect`, `GetFileVersionInfoSizeA`, `GetFileVersionInfoA`, `VerQueryValueA`, and the C runtime's `_beginthread`, `_endthread`,
`_tzset`, `localtime`, `strftime`, `fputc`, `_ftol`. With a scratch runtime (rows in `profile.c`, the 2.15 experiment's calls, and mutexes and events answered with a handle) the module loads, maps `ManalinkInterface.dll` at 0x3a000000 and its four sibling libraries, and **stops inside `ManalinkInterface.dll`** at the unlifted jump-table function (before that its start-up asks `CreateMutexA`
and `DisableThreadLibraryCalls`). The shell was therefore not reached; with `ManalinkInterface.dll` provided by the host (16 functions that answer "no network"), or the two instructions supported, the next obstacle would be the black shell window that 2.15's magic.exe also shows.

**Which build line is the best single target for a SotA port?**

| | 2.0 | 2.15 | 2.15 + ManaLink 3.0 |
|---|---|---|---|
| programs | shandalar.exe 6.1 (1997-09-02), magic.exe 6.2 | shandalar.exe 6.1 (1997-10-31), magic.exe 6.2.1 | 2.15's shandalar.exe; magic.exe 6.3b (1998-01-14) |
| is every file at hand and whole | yes (the disc) | yes (disc + the complete patch) | yes (+ the add-on) |
| card fixes of the readme | no | yes | yes |
| cards in the programs' master tables | 622 | 622 | 622 in Shandalar's program, **722 in the shell's** |
| duel layout | 101 slots | 101 | 101 in shandalar.exe, **151 in magic.exe** |
| libraries | 2.0's | 2.15's (the deck library recompiled) | ManaLink's (a debug build of the deck library, `CheckDoPCD`) |
| unusual to support | -- | the registry check, FaceMaker | the same, plus `ManalinkInterface.dll`, 14 more Win32 calls, Legends and The Dark art that is not in the add-on |
| what a port needs for a first result | | profile rows, 21+27 Win32 calls, the process model, `rol` | all of 2.15's, then 15 to 25 hours more |

**Recommendation: target 2.15.** It is the last build with `shandalar.exe` in any file at hand, it is complete and consistent (programs and libraries from one patch level: every function counted above is from one coherent set), it fixes 2.0's card bugs, and everything measured so far was measured on it. ManaLink 3.0 changes what the *shell* and the *libraries* are; it
adds 100 cards (to the shell's duels, gauntlet and deck builder, not to Shandalar, whose program, unless the DotP disc's own `shandalar.exe` is a newer one, still has 622), a new duel layout, and a network client the port cannot use. A port that wants the "last official version" can add ManaLink's `magic.exe` and libraries as a **second set of profile rows** on top of the 2.15 install, exactly as the
installer layers them, at a cost listed in the effort table; but doing it first would mean two different duel layouts in one install and a host-made `ManalinkInterface.dll` before the first screen is up. Two things would change this recommendation: a *Duels of the Planeswalkers* `shandalar.exe` with 722 cards and 151 slots (then a "3.0" line would be coherent and the better target), and a failure of 2.15's shell page that the ManaLink shell does not share (not known: neither paints).

## What a build profile would have to hold

One record per supported version, chosen by the SHA-256 of the programs (as `tools/install/install.py` already fingerprints 1.0's), which tells `liftrun`, the module build and the runtime what they cannot guess:

(**The mechanism now exists**: `src/port/profile.c` and `tools/lift/builds.py` hold a row per file found by its SHA-256, the lifter writes the id into the module and the runtime refuses an unknown build; what is missing for SotA is the content of the rows. The experiment above filled in only the `.lzw` part for twelve files and nothing else; what a complete row needs is the list below.)

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

- **The adventure itself** (world, towns, shops, quests, castles, dungeons, opponents): compared file by file, constant by constant and by play in [sota-adventure-diff.md](sota-adventure-diff.md): the same game apart from the opponents' decks and a few limits.
- **Features** (from the readme and the strings): a sealed-deck tournament (`SHELLPAGE_SEALEDDECK`, deck editing in Shandalar and sealed share the deck builder, with the new "Move By Color" and shift-double-click for several copies), a gauntlet that saves the duel in progress with its progress,
  a single-duel page, the tutorial is 1.0's (a Director projector: **not a candidate**, a different project), movable floating windows in the duel (the ante, the mulligan, both hands, the situation bar: a new window kind, `navwm.c`'s targets would need to follow them), minimisable spell chain and combat windows, the new
  portraits, `Exp1Art` (89 files: the expansion's card art in towns), 159 more cards (622 against 463), old decks backed up on install.
- **Data in 2.15 and ManaLink**: see "2.15 against 2.0" (`cards.dat`: texts and the sound-file references; the same 929 names in 2.0, 2.15 and ManaLink) and the ManaLink section (`cards.dat` the same but for 40 cards; 100 more cards only in the program's table; `Legends` and `The Dark` buttons in the deck builder).
- **Data**: the card art is in `cardartlib` and `drawcardlib` now, which draw from `CardArt` and `Exp1Art` themselves (1.0 drew its cards in the program); `.pic` files changed (14 differ, 102 new) in ways the picture reader handled (the decompressor is the same code); `.spr` sprites are 1.0's.
- **The resolution switch**: the shell lays itself out for 800x600; shandalar.exe has 1.0's three layouts (the three screen-size globals at `0x57a7d0` and `0x57a7d4` for 2.15), so `PORT_RES` keeps working for it; magic.exe's screen size is not found (its uses of the 1.0 address did not align).
- **CD checks**: the CdTools library (`CheckOriginalCD`, `CheckSotaCD`, `IsCDDrive`, and in ManaLink 3.0's copy `CheckDoPCD`, called by the installer's script and by the programs) asks the drive type and the volume label; the port answers "fixed disk" to `GetDriveTypeA` and has no `GetVolumeInformationA`, so a check that wants the disc would fail. Whether the programs refuse to run without it was not reached.

## Milestone 1: shandalar.exe 2.15 from the title screen to the overworld

Milestone 1 of the port of 2.15 was: `shandalar.exe` 2.15 plays from the title screen through Start New Game (colour, name and face) to the overworld and walking, on the runtime as it is, with a profile row per file and nothing that changes 1.0. What follows is what ran and what did not, as it was seen on this machine (macOS, SDL dummy drivers, 640x480, the pictures looked at by eye and not kept). The Windows and Linux hosts were not run with a 2.15 module; the new platform code (`plat_win.c`) is compiled by CI only.

**What runs** (the real 2.15 files, all lifted from the machine code: `shandalar.exe` and the real `FaceMaker.exe`; the libraries `STATWIN.DLL`, `deckdll.dll`, `cardartlib.dll`, `drawcardlib.dll`, `CdTools.dll` as modules at their bases):

1. the title screen draws, and Start New Game brings up "Select Your Color";
2. choosing a colour makes the game call `_spawnl(_P_WAIT, FaceMaker.exe, "/S")`: the runtime starts a second copy of itself with the module of that program (the profile's `programs` list), the **real lifted FaceMaker** runs, draws the portrait, ends, and the game goes on;
3. the name screen shows the true portrait (the earlier note's noisy or garbage name screen was the portrait memory not shared between the two programs: the game's "graphic pages" are named file mappings, which the programs now hand over to each other, see below) with the name box;
4. typing a name and Return brings up the overworld; the player can walk about, and meeting a Sorceress on the map brings up her encounter dialog.

**What does not, or was not tried:**

- **(Done in Milestone 2, below.)** **Duels** inside `shandalar.exe` were not tried (stretch goal). The deck builder (`DECK.EXE` stub with the 2.15 libraries) lifts and builds with the installer's steps and the library part runs as in the earlier experiment, but it was not run again in this milestone. `magic.exe` (the Magic Shell) and ManaLink 3.0 are out of scope and unchanged: not lifted by the installer, not run (the shell is Milestone 5).
- **(Changed in Milestone 2, below: `hooks_verified` is a mask now and shandalar.exe has three groups.)** **Hooks are off for every 2.15 row** (`hooks_verified = 0`): no pacing hook, no controller navigation, no text-menu or yes/no hooks, no title hook. The game runs at whatever speed its own busy loops give (it spins a CPU core; the 1.0 hooks are what calm that); the 54 addresses are not re-verified.
- **(Done in Milestone 2.)** The display globals of 2.15 are not wired (no `.display` row), so 800x600 or 1024x768 scaling is not shown to work with 2.15: only 640x480 was used.
- **(Done in Milestone 2.)** No soak or random play on 2.15. A save, load and the rest of the overworld (shops, towns, the dungeons) were not visited beyond the one dialog.
- Saved settings: the registry writes go nowhere, as in 1.0.

**What was built** (all with tests; none of it changes what 1.0 runs: the lifter's output for 1.0 is byte-identical before and after, and 1.0 still starts a new game on the new runtime):

- Lifter: `rol` and `ror` (all widths, flags as the CPU sets them); `_setjmp3` and `longjmp` modelled (a guest `jmp_buf` that keeps the registers, with a host `jmp_buf` behind it; found also through a thunk), because the overworld uses them; the 47 import signatures, now **read from the executables** where they are the game's own libraries (`libsigs.py`: `ret imm16` is stdcall, plain `ret` is cdecl) and from a table for the system's, checked against the call sites (`tools/research/sotaimports.py --sigs` compares each signature with the pushes before it and the `add esp` after it); the master table found by its pattern (`mastertable.py`, no address in a table); a `builds.py` row per 2.15 file with bases `0x30000000` STATWIN, `0x32000000` deckdll, `0x34000000` cardartlib, `0x36000000` drawcardlib, `0x38000000` CdTools.
- Runtime: a profile row per file (ids, program names, bases, `.lzw`), more library slots in `lzw.c`, the `msvcrt.dll` name as an alias of the table's `msvcrtd.dll`, and the 21 missing Win32 and C runtime calls as implementations with tests (`winsys.c`, `crt.c`, `test_win32.c`), among them the registry, TLS, locale, volume and disk calls, `qsort` with the game's own comparison, and `_findfirst`. Two bugs of the runtime's own calls were found and fixed on the way: the character-width calls looped forever on a large range, and device contexts taken with `GetDC` and not given back were leaked until memory ran out.
- **The registry check.** At start-up the game (and `deckdll.dll`) reads two values of `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion`, `FirstInstallDateTime` (4 bytes) and `ProductId` (a string), and derives a machine identifier from them. `winsys.c` answers with a fixed pair of plausible values and says in a comment what they are: **values the game asks Windows for**, which a Windows that is not there cannot give. **They are one half of a machine-bound licence check**: see [The licence value](#the-licence-value) below. They are what the game asks Windows for, answered so that it starts; the other half, the `SerialNumber`, is not provided.
- **The process model** (`process.c`): `_spawnl`, `WinExec` and `CreateProcessA` start another `pentamoor-run` for the program the profile names (the game's folder, overlay, display settings, command line and a control pipe of its own passed on), `_P_WAIT` and `GetExitCodeProcess` wait. It is correct for **sequential use** only (the parent waits): named memory is handed over in files (`PORT_SHM`: the parent writes its named mappings before starting, the child reads them when it creates a mapping of the same name and writes them back when it ends, the parent reads them again when it sees the child finished), which is what FaceMaker needs; two programs running at once and sharing memory are not modelled, and neither is a shared window (the child makes its own).
- A DIB section made from a file mapping is that memory (not a copy), which is how FaceMaker's drawing reaches the name screen.
- Installer: `liftrun.py` and `modbuild.py` know the 2.15 programs, and `tools/install/install_sota.py` checks a 2.15 folder file by file, lifts and builds the modules (`./pentamoor sota`, `PENTAMOOR_SOTA` names the folder). It does **not** make the folder: that was still `sotapatch.py` and `sotaoverlay.py` from the research tools applied to 1.0's install, the 2.0 cabinet and the six patch files. **(Done in Milestone 3, below: `pentamoor-install ... --sota ... --patch ...`.)**

**Left from this note's earlier list**, now superseded: `liftsota.py` and `sotamaster.py` are replaced by the lifter's own program row and `mastertable.py` (they stay as research tools); `sota-runtime-experiment.patch` is obsolete: all of it is in `src/port`.

## Milestone 2: shandalar.exe 2.15 through a duel, and sane to run

Milestone 2 was: `shandalar.exe` 2.15 plays through a duel with the mouse (coin toss, mulligan, draw, land, creature, attack, end turn, win or lose), runs at the sizes 1.0 does without using a CPU core for nothing, keeps its hooks only where they were run, and survives a soak, a save and a load. What follows is what ran on this machine (macOS, Apple Silicon, SDL's dummy drivers, the pictures looked at by eye and not kept; Linux and Windows hosts were not run with a 2.15 module). The folder it ran from is the first game's install with the 2.0 files and the six files of the patch over it, made by `tools/research/sotaoverlay.py sources/installed/Magic sources/installed_sota_215 sources/installed_sota_215_m2 --only Program` (`install_sota.py --check` names every file as v2.15).

**What ran** (every item seen on the screen, at 1024x768 unless said):

1. **New game to the first encounter**, driven by the control pipe: the title screen, Start New Game, the difficulty, the colour (FaceMaker starts, the portrait is clicked), the name, and the first encounter's ante screen (cards drawn by `cardartlib.dll` and `drawcardlib.dll`: card pictures, mana symbols, rules text, flavour text, power and toughness; no black card).
2. **A duel against the game's own AI**: "Duel" on the encounter, the coin toss dialog ("You won the coin toss", Play first / Draw first), the mulligan dialog and "Start the duel", the board (both libraries, graveyards, the mana columns, the phase column, the hands; the full-size card on the left), a land played by clicking its row of the hand list, a creature cast by paying with lands, the attack (clicking the creatures, then Done), blockers and spell windows ("Troll Shaman casts..."), the discard prompt, the turn passing to the opponent and back, and the duel ended two ways: **conceded** (right-click menu, Concede, "Yes, I'm sure") and **won**.
3. **A won duel runs on to the reward screens**: the opponent's life is at `0x8f67d4` (the player's is `0x8f67d0`: two dwords, the 2.15 counterparts of 1.0's `0x6a4a00`/`0x6a4a04`, found by dumping memory while the life changed); poking it and acting makes the game show the wizards' movie, then "You have defeated the slimy Sorcerer. Will you... Take the cards. Take the dungeon clue." with the three reward cards drawn, "Take the cards" takes them (the deck's count went from 36/37 to 36/40 and the next encounter followed) and the dungeon clue page ("Tower of Whim, Location: ...", the three clue cards and a Done button) is reached too.
4. **The sizes**: 640x480, 800x600 and 1024x768 each draw the game's own layout for that size (the map, the ante screen, the duel board, the reward screens); see item 1 below.
5. **Save, load, quit and resume** on the overworld (`tools/soak/sota_saveload.py`, run twice with the party's place compared each time): Save to slot 1 with a typed name (MAGIC4.SVE, .map and .fce are written), the party teleported 14 tiles away, Load from slot 1 puts it back where it was saved (within a step: the game walks the avatar a tile or two towards the mouse after a load, as 1.0 does: `saves-and-paths.md`), Quit ends the process by itself, and a new process on the same overlay with Resume Game is where the party was.
6. **The village**: "Buy 10 food for 20 gold" bought exactly once by one click (gold 210 to 190, food 40 to 50), "Buy Cards", the card shown large with "Buy for 15 gold? (Y/N)" and the hint line the port draws for the question, and a left click answering yes (gold 190 to 175, the Swamp gone from the shelf, the deck count 36 to 37). The map's right-click menu (Save, Load, Quit, See/Edit Deck, See Map ...) and its "Ready to Quit?" question. "Edit deck/Sell cards" opens the game's own deck editor (card list with pictures, the gold, the large card; its rules text of a long card runs past the bottom of the box, as in the standalone one), and a right click on a card offers "Sell Card for 20": it sold the card at once with no question (gold 210 to 230, 36 cards to 35). The Wiz Stats window, the quests and the other shops were **not** looked at in this milestone.
7. **The deck builder** (`DECK.EXE` with the 2.15 libraries, 800x600): the card list with pictures, a card chosen and shown large, a double click adding it to the deck (the stats bar says "1 cards"). Its rules text of a long card runs one line over the box (`Aladdin's Ring`), as the notes of 1.0's deck builder say of the full-size card.

**What was fixed or added to get there** (each has a test; none of it changes what 1.0 draws or plays except the two marked):

- **Display** (`.display = 0x57a7d0 / 0x57a7d4`, both 640 and 480 in the data section before the program runs, as 1.0's): the game's layouts follow the port's screen size. 
- **Pacing** (`pace.c`, the profile's `.pace` and `.buttons.pass`/`.mouse_var`): see the table. The 1.0 hooks work as they were (the frame period on the map: 17 frames a second, from the game's own frame counter at `0x7253f0`, was seen; a click is one pass: the village's food bought once). **New for 2.15: the loops that wait for the player take no CPU** (`idle_fn`, `idle_ms`): the title menu's loop calls the button table's pass **1.8 million times a second** and nothing else, the other menus the mouse snapshot, the (Y/N) question the key poll; each now rests 16 ms when no button is down. The process went from **100% of a core** (title screen, menus, shops) to **2% at the title screen, 8% on the map or an encounter, 5% in a duel** (`ps`, 8 s windows, with other jobs running). 1.0 is not changed (`idle_ms` 0, a test says so).
- **Messages that wait for a key** (`HK_KEYS`): the key queue's wait loop and poll, the "Buy for N gold? (Y/N)" site and the new game's name box loop are hooked; the pad hint line appears and a left click answers yes (above), the name box asks for the on-screen keyboard (`PORT_TEXTINPUT=auto`: "text input: on (a text field has the focus)" at the name screen and off after it).
- **`FormatMessageA` with inserts** (`winsys.c`): the game takes its texts from AdvStrings.txt through `FormatMessageA(FROM_STRING)` with `%1`, `%2!d!`, `%n`, `%%`, and the port returned the string as it was (the village and quest texts, "Trade %1 for %2"); the inserts are done now, from a `va_list` or an argument array. The case before the change was not run: it was found by reading the call (the game's wrapper at `0x4ae7a0`) and AdvStrings.txt, and the tests (`test_win32.c`) hold the cases.
- **Code page 1252 in the card fonts** (`font.c`) *(also 1.0)*: the text is in the ANSI code page, whose `0x80..0x9f` are punctuation; the fonts' tables are Unicode and have nothing at U+0080 to U+009F, so the curly quotes, dashes and ellipses of the card texts were drawn as missing glyphs. 2.15's CARDS.DAT has 210 and 212 of the two quote bytes (1.0's has 45 and 44), so it showed more. They map to U+201C and the like now. The glyphs before and after were not compared on a screen (`test_gdi.c` has the mapping and that the glyph is not the missing one).
- **`DefWindowProc(WM_CLOSE)` is `DestroyWindow`** (`user32.c`) *(also 1.0, where nothing in the runs sent it)*: the window procedure now gets `WM_DESTROY` first. 2.15's Quit sets its end flag, posts `WM_CLOSE` to its main window, and the main window's procedure answers `WM_DESTROY` with `PostQuitMessage`; without it the game's own loops ended and the process then waited for a `WM_QUIT` that never came (the Quit question was answered and the process stayed, with a black window, for ever). `test_wm.c` has it.
- `tools/install/install_sota.py` could not be run as `python3 tools/install/install_sota.py` (it imported `builds` before the path was set); it can now.
- `tools/soak`: `Game` takes an overlay seed of None and arguments (2.15 has no saved game to start from); `sota_soak.py` (duels, monkey), `sota_saveload.py`; their addresses are tested (`test_ctl.py`).

**The 2.15 profile, per hook, as it was verified in Milestone 2** (Milestone 4's table, further on, has what changed; "verified" = run, and the effect seen; the others are left out of the row: `hooks_verified = HK_PACE | HK_KEYS | HK_DISPLAY`, a test fails an address of a group whose bit is clear). Address, what it is, how it was matched (`sotahooks.py`), what was seen:

| 1.0 | 2.15 | what | matched | status |
|---|---|---|---|---|
| `0x5016f9` | `0x48a3a5` | tick read-and-clear (overridden) | identical bytes | **verified**: the frame counter runs 17 a second on the map, and the process rests (before: 100% of a core) |
| `0x530da0` | `0x566f3c` | the tick counter | strong (6 of 6 uses) | **verified** (the override reads and clears it; a wrong address would run the map at the wrong speed) |
| `0x4e7873` | `0x438f85` | return site of the tick call in the map loop (the frame is paced there) | changed, 0.88; checked by hand (the instruction after the call) | **verified** (the 17 frames a second) |
| `0x4e73a0`..`0x4e7936` | `0x438a70`..`0x439059` | the map loop, as a range | changed, 0.88 | **verified**: the pass hook leaves it alone, the idle hooks do not nap in it (the map's frame period holds with a button held and without) |
| `0x41f3ea` | `0x4ba087` | the button table's pass (pre-call hook) | changed, 0.97 | **verified**: a click in the village is one pass (food bought once), a press that ends a screen is not seen by the next |
| `0x7039c4` | `0x9199b0` | the mouse button state | strong (31 of 38) | **verified** (the hook clears it, `PORT_UI_LOG` lines "shown as up") |
| `0x44b84b` | `0x4eab14` | the mouse snapshot (nap hook: `idle_fn`) | identical bytes | **verified** as the nap (CPU), **not** as `screens.c`'s hook |
| `0x48ac2f` | `0x4b84d7` | wait for a key | identical bytes | **verified** (the question's loop is where the hint appears and the click is turned into the key) |
| `0x4080b2` | `0x4a8ea2` | pop a key (poll) | identical bytes | **verified** (as the nap of the wait loop, and the name box's signal) |
| `0x48ac3d` | `0x4b84e5` | where the poll in the wait loop returns to | identical bytes | **verified** |
| `0x509e4a` | `0x4a3296` | the "Buy for N gold? (Y/N)" site | changed, 0.76 | **verified** (hint line shown, left click bought the card) |
| `0x4f156e` | `0x468c0e` (and `0x468915`, also in `0x468533`) | the "Sell ... (Y/N)" site | found this time by reading `0x468533`: it draws the question of `@SHOWDECK` and loops on the answer keys `yY`; the earlier note said "none" | **not run**: out of the row (the right-click "Sell Card for N" of the deck editor sells with no question: this site is on another path) |
| `0x45119d` | `0x4f0b96` | the "Take this card? (Y/N)" site (`@SHOWLIST`) | changed, 0.95; seen to be on the stack (`0x4f041d` calling `0x4b84d7`) when the screen was up | **not run as an answer**: out of the row |
| `0x47be64`..`0x47c080` | `0x53aecd`..`0x53b129` | the new game's name box loop | changed, 0.72 | **verified** (the text-input signal came on at the name screen and went off) |
| `0x522458` / `0x52245c` | `0x57a7d0` / `0x57a7d4` | the screen size the layouts read | strong (123 of 182, 111 of 163) | **verified** at 640x480, 800x600 and 1024x768 |
| `0x519c24`, `0x67f780`, `0x67f7d0` | `0x577cec`, `0x7270e0`, `0x727130` | the button table's context, record counts, record pointers | strong | **not run** (`screens.c`, the controller's reading of the screens: out of scope) |
| `0x489748`..`0x489c9c` and the seven text menu globals | `0x4b6fe7`..`0x4b753c`, `0x6a0f54`, `0x6a0f58`, `0x728114`, `0x577c4c`, `0x728120`, `0x728110` (weak), `0x728128` | the text menu ("Will you... Duel this Druid. Pay 40 gold.") | changed 0.96, strong but one | **not run** |
| `0x509517`..`0x509fd4`, `0x61e060`, two frame offsets | `0x4a28c7`..`0x4a347c`, `0x69eb70`, `ebp-0xa8`, `ebp-0xa0` | "Cards for Sale" | changed 0.76 | **not run** (the screen was visited: the shelf drew and a card was bought; the D-pad's reading of it was not tried) |
| `0x48f523`..`0x49094c`, `ebp-0x12d8` | `0x4aa415`..`0x4ab73e`, `ebp-0x12d4` | the clues list | changed 0.83 | **not run** |
| the title menu's loop | not looked for | the one screen where Escape leaves the game with no question | | **not run** |
| `0x40a3e1`, `0x4e7a6f`, `navwm.c`'s four sites | `0x55ac0b`, `0x43923e`, `0x4d9509`, `0x4dac44`, `0x41c8a0` | the comments' sites (the release wait after the deck builder, the map's walking, the duel navigation's icons) | | **not run**; `0x55ac0b` is a loop that spins on the mouse snapshot and the key poll, and the idle hooks calm it |

The row now holds **16 addresses of hooks and the screen size, all verified** (the pacing, the key wait with one of its sites, the name box, the screen size) besides the picture decompressor's; **the rest of the 54 are matched by code shape and left out** until they have been run. The matching of milestone 1's table held everywhere it was run: no address of it was wrong, and the sites that the table calls "changed" (0.72 to 0.97) did what their 1.0 counterparts do.

**Soak** (`tools/soak/sota_soak.py`, 1024x768, SDL dummy drivers, one control pipe and overlay per process, a new game each time because 2.15 has no saved game; duels and monkey runs at once, each round 20 minutes; the first column is the runtime before the last change of `pace.c` (the title menu's nap), the second the runtime of this branch):

| | rounds | process-minutes | games (new game each) | duels played | turns | won / conceded | places visited by the monkey | clicks / keys / right clicks | CRASH | HANG | STUCK | STDERR | SETUP |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| first runtime | 3 (6 jobs) | 123 (duels 60, monkey 63) | 24 (12 + 12) | 14 | 65 | 3 / 2 (the others ended by the game's own result or were restarted) | not counted | 2,172 / 1,451 / 405 | 0 | 0 | 0 | 0 | 3 |
| final runtime | 3 (6 jobs) | 127 (duels 62, monkey 65) | 24 (12 + 12) | 9 | 51 | 3 / 4 (the others ended by the game's own result or were restarted) | 131 | 2,205 / 1,357 / 416 | 0 | 0 | 0 | 0 | 5 |

The resident memory of a game process stays between 450 and 510 MiB for a run of 20 minutes (a first reading of about 460 MiB at 40 seconds, up by 30 to 50 MiB over the next ten minutes, and the system compresses it by itself: some samples read 180 to 210 MiB). The soak stops its processes with SIGTERM, which prints no end-of-run report, so **"not implemented" calls are known from the runs that ended by themselves**: a run through a new game, the duel and the quit with `PORT_CALLS=1` listed 550 imports called and none missing, and the save, load and resume runs (the game ended by its own Quit) printed no list of calls that are not implemented. A `SETUP` event is the soak's own failure to get to its first duel in 180 seconds, not the game's: the new game began in a village, or the party put on a monster of the game's table met a dungeon, a tower or a castle ("You encounter a Warlock ... Leave quietly. Duel the creature.", "Found this card", a clue page: screens the script does not know and clicks the ante screen's line on) and the process was restarted. The first runtime's three came from a game that began in a village or with no monster near; the script now leaves the village and teleports the party onto the first monster of the game's table, which made the last two kinds.

**What does not work or was not done:**

- **The Take and Sell questions are not answered by the mouse** (their sites are not in the row); the Buy question is.
- **No controller navigation for 2.15** (out of scope; `screens.c`'s groups are off), no D-pad targets on the map or the duel (`navwm.c` looks for window classes that 2.15 has, but the movable windows of the duel are new).
- **Rules text**: the deck builder's long card text overruns its box; the duel's own cards looked right at three sizes; the curly quotes were not compared with the original.
- **Sound** and the movies: the wizards' movie plays (a window of the movie class opened; the port plays Indeo clips by ffmpeg when it has one: `/opt/homebrew/bin/ffmpeg` was there) but nothing was listened to; the dummy audio device ate it.
- **The shell** (`magic.exe`), ManaLink 3.0, the installer that builds the 2.15 folder from the discs (**done in Milestone 3**), a real display and a real mouse, Windows and Linux: not tried.
- **The first game's first encounter is not always there**: a new game can begin in a village or on the map; that is the game's.
- **The registry answers** of `winsys.c`, the installer's scope and the process model (sequential only) are the user's decisions and are unchanged.

**Hours.** About five and a half hours of agent time (wall clock from the first command to this note, about two of them waiting for two soak runs of an hour each that went beside the rest), against the 15 to 30 the table below left for "duels, pacing hooks, resolutions and a soak". The largest items were: finding that the loops spun (the profile of where the CPU went, three tries at the nap, the last one only because the title menu's loop turned out to call the pass 1.8 million times a second), the soak harness for a game that has no saved game (a new game each time, FaceMaker's pipe, the monster teleport), and the Quit that never ended. The hooks cost less than estimated because the matched addresses held.

## Milestone 3: one command installs 2.15

Milestone 3 was: **one command takes the player's own discs and patch and makes a playable 2.15 install, as 1.0 has**, with nothing set by hand: `pentamoor-install "MTG v1.0.iso" --sota "MTG v2.00.iso" --patch SOTAV215.EXE`, then `./pentamoor sota`. What follows is what ran on this machine (macOS, Apple Silicon, 8 jobs; the real discs and the real complete patch; SDL dummy drivers; the pictures looked at by eye and not kept). Windows and Linux were not run.

**What the command does, in order** (`tools/install/install.py`, `sotainstall.py`):

1. **Everything it will read is checked before anything is written** (a few seconds): the first disc is the original game's (`Setup/data.z`), the `--sota` disc is Spells of the Ancients 2.0 (`Setup/data1.cab`, its `DATA.TAG`, and the size and SHA-256 of its three cabinets, `builds.SOTA_DISC`), the patch is whole (every CRC-32 and its end record: `sotapatch.load`) and holds exactly the six known files with the known hashes (`builds.SOTA_PATCH`, and the final files' hashes). `--sota` without `--patch`, `--patch` without `--sota`, a missing file, the two discs the wrong way round, a cut-short or damaged patch or disc each stop it here with a message that says what was given, what is wrong with it and the command that is needed (the real ones are listed below).
2. The first game is installed as before (967 files and the music and movies, 35 s) and checked against the 1.0 hashes; if those are not the retail disc's, the 2.15 folder is not made from them.
3. The 2.15 folder, beside the first game's (`<dest>_sota`, by default `sources/installed_sota/Magic/Program`; `--sota-dest`; it may not overlap the first game's folder): a copy of the first game's folder (1,066 files, 265 MB), then the 335 files of `Setup/data1.cab` over it (`Program\x` is `Program/x`, the three files with no folder at the top; names compared ignoring case: 93 replaced, 231 added, 11 the same), then the six patch files (all six replace: `cards.dat` is `CARDS.DAT`, `readme.txt` is `Readme.txt`, the names keep the first game's spelling), through `overlay.place`, which refuses a path with `..`, a drive letter or a leading slash and a symbolic link on the way, so nothing is written outside the folder. `_sys1.cab` and `_user1.cab` hold only the original installer's own helper DLLs and billboard pictures: they are read to the end to see they are whole and are **not installed**. Nothing is written to any registry.
4. **Every program, library and data file of the result is checked by size and SHA-256** against `tools/lift/builds.py` (15 files: the ten programs and libraries the port lifts or provides itself, `magic.exe` and `MSVCRT.DLL` (rows of the role "kept"), and the data files `CARDS.DAT`, `FaceData.txt`, `Readme.txt` (role "data")), and a folder that is not exactly 2.15 is named file by file and refused.
5. The first game's three programs and the three of 2.15 (`shandalar`, `facemaker`, `sotadeck`, with their libraries) are lifted and the modules built with the rest (one `make`, or `modbuild` in a release: six modules), each module smoke-tested in the runtime. `--force` writes and lifts everything again; a second run with no source reads nothing (the folder is verified) and only rebuilds what changed.

**The CD-side files.** The note's earlier sentence ("take the CD files from the 2.0 disc as well, 22 WAV") is the cabinet's own `DuelSounds` folder (22 WAV: the expansion's), which step 3 installs. The 2.0 disc's `Sound` (31 WAV) and `StatWin` (68 AVI) are the first disc's, file for file (compared by name and size: no difference), and its `DuelSounds` (16 WAV) are in the cabinet too, **except that its `Manaball.wav` is another recording of the same size**; the installed game plays the cabinet's (what Milestone 2 played), so the installer only adds a `Sound` or `StatWin` file that is missing (none is) and never replaces one.

**Timings** (from nothing: no 1.0 install, no lifted C, no objects; the installer's own timing lines): the first game's files 35 s, the 2.15 folder 1 s (copy, cabinet, patch, hash check), the lifts 23 s (first game's three) and 32 s (2.15's three), and the rest is the compiler: **2 min 19 s in all in a checkout (`make -j8`, started 21:56:59, ended 21:59:18)** and **2 min 15 s from the release archive** (`package.py` then `pentamoor-install`: `modbuild`, 31 files, 179 MB of C). The first game alone is as before.

**What ran for real** (the real discs and patch):

- **The folder** is the one Milestone 2 played: compared with a copy of the first game's install with `sources/installed_sota_215`'s `Program` over it (the way Milestone 2's folder was made), every file is byte for byte the same except `Readme.txt` at the top (the expansion's, which the old recipe did not take) and `GatheringNet.url`; what the old folder has and this one lacks is what the maintainer's own 1.0 install had in it besides the disc's files: saves, `.tmp` files, an uninstall log and the tutorial's folder.
- **Starting it as a player does** (`tools/soak/sota_launch_check.py`: `sh ./pentamoor sota` with **no setting but the SDL dummy drivers and a control pipe**, in an unpacked release archive built by `package.py` and filled by its own `pentamoor-install`): the program loads, the title screen draws, Start New Game, the difficulty, the colour starts FaceMaker (a second program), FaceMaker's window and portrait, the name, the world is made and its pictures drawn, and the party stands on the map of the overworld (the screen was looked at: the map, the status bar with the gold, food and cards, the party's figure). The launcher made `port_overlay_sota` and no `port_overlay`. The same through a checkout with `--folder` pointing at the installer's folder.
- **Save, load, quit and resume** (`tools/soak/sota_saveload.py`, the way Milestone 2 ran it, winning the first duel) on the installer's folder: **all ok in one run** (MAGIC4.* written, Load puts the party back within a step, Quit ends the process, Resume Game gives back the place); another ended on the "Take this card? (Y/N)" reward question, which the mouse cannot answer (Milestone 2's known gap: the Take site is not in the row). The script's second way, conceding the first duel (`SAVELOAD_CONCEDE=1`), failed in four runs here at the map's right-click menu (once the game began in a village, which the script does not handle) and **failed the same way on a copy of Milestone 2's own folder**, so it is the script or the machine today, not the install; Save, Quit and Resume Game passed in the runs where the menu opened.
- A conceded duel and a five-minute monkey run over ten places (villages, towers, castles, dungeons) with the registry, drive, message-box and CD calls traced: nothing missing, no crash.
- **The first game** from the same fresh run: installed, built, its title screen drawn headless through the launcher, its hash check unchanged. A corrupted copy is refused: a bit of `Setup/data1.cab` in a copy of the disc image (`Setup/data1.cab has SHA-256 00a9c00a57cc1942... where the retail disc's has cb021ce69e08b56a...`), a bit of an entry of the patch in a copy of it (`magic.exe: CORRUPT (CRC-32 ca21f4cd, c505a01d announced)`), a bit of `shandalar.exe` in a copy of the finished folder (`install_sota.py --check`: `shandalar.exe: unknown build`, exit status 1): each before anything was written or built.

**What the wrong sources say** (real runs, abbreviated; the test suite has each with made-up files):

| given | the installer says |
|---|---|
| `--sota` and no `--patch` | `Spells of the Ancients 2.15 needs the patch as well as the expansion's disc: the disc alone is version 2.0, and Pentamoor runs 2.15, not 2.0. --patch is missing; the patch is the file SOTAV215.EXE ... Run again with: pentamoor-install "MTG v1.0.iso" --sota ... --patch "path/to/SOTAV215.EXE"` |
| `--patch` and no `--sota` | `the patch is given, but not the expansion's disc it patches ... --sota is missing` and the command |
| the 2.0 disc as the first | `<it> is the Spells of the Ancients disc (version 2.0), not the original game's. The expansion is installed over the first game, so the installer needs the original game's disc (MTG v1.0, with Setup/data.z) first and this one after --sota, and the 2.15 patch` |
| the 1.0 disc after `--sota` | `<it> is the original game's disc (version 1.0), not the Spells of the Ancients disc. --sota wants the expansion's disc: MTG v2.00, the one with Setup/data1.cab` |
| the cut-short `sotav215.exe` (1,048,331 bytes) | `... is not a whole archive (1048331 bytes): deckdll.dll: TRUNCATED (19716 of 89728 packed bytes present); no end-of-central-directory record: the archive is cut short ... The whole SOTAV215.EXE is 1,207,571 bytes; this file is 1,048,331: it was cut short ... Get the patch again.` |
| a file that is not a patch, or another patch | `has no files in it ... --patch wants SOTAV215.EXE` / `is not the 2.15 patch: it holds ...; it lacks ...` / `its shandalar.exe is not the one of Spells of the Ancients 2.15` |
| a damaged or other release of the disc | `Setup/data1.cab has SHA-256 ... where the retail disc's has ...: the disc image is damaged or another release` |

**What was built:** `tools/install/{iscab,sotapatch,overlay}.py` (the research readers promoted: the cabinet reader now says where a cut-short cabinet is cut and does not trust a table that points outside the file; the patch reader's `load` gives one message with every problem; `overlay.place` is the one-file, case-insensitive, confined writer; the old commands in `tools/research` run them), `sotainstall.py` (the checks and the folder), `install.py` (`--sota`, `--patch`, `--sota-dest`, `--check` says whether 2.15 is installed, the lift and build steps take the 2.15 programs too), `builds.py` (rows for the files the lifter does not lift, `SIZES`, `SOTA_DISC`, `SOTA_PATCH`), `manifest.py` and `check_archive.py` (the release carries the new modules, `tools/lift/libsigs.py` and `mastertable.py`; an archive with `shandalar.exe`, the 2.15 libraries, `CARDS.DAT`, the cabinets, the patch, `game_shandalar`, `game_facemaker`, `game_sotadeck` or any `.cab` is refused, and `check_tree.py` is unchanged and passes), the launchers (`./pentamoor sota` and `pentamoor.bat sota`: the folder `sources/installed_sota/Magic/Program`, `PORT_OVERLAY` defaulting to `port_overlay_sota`, a message that names the one command when it is not installed), and the soak scripts' defaults.

**Tests** (`tools/install/test_sota.py`, `fakediscs.py`: made-up cabinets in both layouts, patches, ISO images with folders; 55 tests, none needs a game file and all run in CI): the cabinet and patch readers (moved from `tools/research` and extended: cut short, damaged, read out of an image or a folder), `place` (case, `..`, absolute paths, drive letters, NUL, symbolic links), every wrong-source case above with the exact checks, the folder (the first game's art stays, the cabinet's files replace, the patch's six replace, nothing doubled, the original installer's files absent, a rerun gives the same folder, a corrupted program and a wrong file length are named, a cabinet with a path out of the folder writes nothing outside), and **the whole command with fakes**: the order of what it says, the lifter and build calls (`lift_all`, `lift_sota`, six modules; a checkout's one `make`), the 2.15 folder where `--sota-dest` says, the refusals writing nothing, a rerun with no source, and `--check`. The launcher's tests cover the `sota` defaults and the overlay.

**What does not work, or was not done:**

- **The Steam Deck's installer with windows** (`tools/steamdeck/install-gui.sh`) is **unchanged**: it asks for one disc. A second and third step (the expansion's disc, the patch) are a follow-up: its progress bar follows the installer's text by stage and would need the 2.15 stages, and its tests drive fake dialogs for a one-disc flow, so it is not a clean seam. `pentamoor-install --sota ... --patch ...` works on a Deck from a terminal.
- **Windows and Linux real runs**, and the `.bat` launchers' new `sota` branch (not run: no Windows machine; CI runs `tools/install`'s tests there, not the batch file).
- The installer prompts for nothing about 2.15: with only the first disc it prints the one line that says how to add it.
- `magic.exe`, ManaLink, controller navigation for 2.15 and the process model's concurrency are out of scope and unchanged.
- **The registry answers of `winsys.c`** (the wording of the comment and of this note's earlier paragraphs about them) are **not changed in this milestone**: tracing what the two values are for found a use that is a machine-bound licence value read from the registry, which the owner has to decide about; nothing about it was changed (the PR description and the report say what was found).

**Hours.** About two hours of agent time, wall clock from the first command to this note (about a quarter of it waiting for builds and a few soak runs), against the 6 to 10 the plan gave. The cabinet, patch and overlay readers existed and were tested; what took the time was the checks that make a wrong source fail early with a useful message, the tests with fakes, and the registry trace. The one surprise: the 2.0 disc's `DuelSounds` is not the cabinet's (`Manaball.wav`).

## Milestone 4: 2.15 with a controller and with touch

Milestone 4 was: `shandalar.exe` 2.15 is as playable with a controller and with touch as 1.0 is: the two (Y/N) questions the mouse could not answer, the D-pad on the screens that matter, the view-card button, touch. What follows is what ran on this machine (macOS, Apple Silicon, SDL's dummy drivers, the pictures looked at by eye and not kept, the install made fresh from the discs by `pentamoor-install ... --sota ... --patch ...` in this checkout, the machine loaded by other jobs: a load average of 14 to 20 for most of the time, which made every run slow). Everything was driven with the control pipe's `pad` steps (SDL's controller events, as `controller.md` says) or its finger steps; no real controller, no real finger, no device. The scripts are `tools/soak/sota_pad_play.py` (the controller), `tools/soak/sota_touch.py` (fingers) and, run on a 2.15 duel, `nav_play.py`'s and `card_view.py`'s own checks.

**Two things the task description had wrong, found by reading and then running.**

- **The sell question is not reachable in 2.15.** `0x468c0e` and `0x468915` are in `0x468533`, a 1.0-style screen (a list of the player's 500 slots with a colour filter on the keys r, b, u, g and w, a click that marks a card and a right click that asks "Sell %1 for %2 gold? (Y/N)") that **nothing calls**: no `call` or `jmp` to its address, no pointer to it in any section (Milestone 2 matched it by code shape; the match was right, the function is dead code). The one sell flow of 2.15, the deck editor's, is `deckdll.dll`'s right-click menu "Sell Card for N", which sells at once with no question (seen with the pad: B on a card, the menu's one row, A: gold 375 to 385). `0x468915`, which Milestone 2 took for a second sell site, is the key menu of the filter, not a question. A hook on `0x468533` over two soaks of 25 minutes (duels, rewards, a monkey run on villages and castles) and the pad runs' villages and deck editors never fired. So **no sell site is in the profile, on purpose**.
- **"Take this card? (Y/N)" is not on the reward screen.** The reward after a won duel ("You have defeated ... Will you... Take the cards. Take the dungeon clue.") takes its cards, or shows its clue page, with no question (seen with the pad). The question is the confirmation of the game's **card picker**, the function at `0x4f041d` (what Milestone 2 saw on the stack): `(player, ids, count, title, ask, ...)`, called from 19 places, which draws a list of cards for the player (a click picks one; with its `ask` flag it then asks the question, whose wait for a key is the call at `0x4f0b91`, returning to `0x4f0b96`) and picks at random for the AI. The callers with the flag are duel-time pickers (the keys in `prompts.txt` that sit before the call sites name Jandor's Ring, Aladdin's Lamp, Sylvan Library, Visions and others); the others are lists of the 500 slots. So **the site is a verified (Y/N) site**, but verified through the game's own function called from the control pipe (below), not through a flow of play: Visions, Demonic Tutor and Sylvan Library, put in a soak deck, used other dialogs or never came to it.

**What ran, screen by screen (controller steps only; "stick" means the left stick moved the cursor and A clicked).**

| Screen | Result |
|---|---|
| Title menu | **D-pad**: 2 targets with no saved game (Load and Resume are greyed), 4 with one; the pointer on the middle of each got the game's own hover on that button (`0x5780bc`) at both. Back: a tap does nothing, 0.3 s does nothing, 0.9 s leaves the game (`--only back`) |
| Difficulty (4 targets), colour (5) | **D-pad**, same hover check |
| FaceMaker (the portrait, a second program) | **stick and A** (no D-pad targets: it has no button table); the cursor on Leave, A |
| Name | X is Enter (an empty name) |
| Map | walking by the right trigger and the left stick (the left button held, the party moved), by the right stick (arrow keys) and by the D-pad (the arrow keys: there is nothing to navigate, as in 1.0); **B opens the game's menu of nine lines** (Save, Load, Quit, See/Edit Deck, See Map, City List, Dungeon Clues, Stats, Wiz Stats), the D-pad walks it, A takes a line, Back closes it. A tap of B can fall between two frames of the map (the game reads the button once a frame): the script holds it 150 to 300 ms |
| Save, load, quit, resume | **all with the pad**: Save (10 slots as targets, hover 10 of 10), the first slot, X for the name, `MAGIC3.SVE .map .fce` on disk; the party moved away; Load (the slot that holds a save is the one target), the party back where it was saved; Quit and its two-line question; a new process, the title menu with 4 targets, Resume Game: the party where it was left |
| Villages | all nine buttons D-pad targets, hover 9 of 9; Buy 10 food by one A (400 to 385 gold, food 100 to 110, once); **Cards for Sale**: the four cards and Done, A on a card asks "Buy for N gold?", **B answers no (gold and card unchanged), A answers yes (gold 385 to 375, the card gone from the targets)**; the deck editor (`deckdll.dll`: 20 cards as strips and five buttons as targets), B on a card opens its menu ("Sell Card for N"), the D-pad reaches the row, A sold the card at once (375 to 385); Done, which when the deck has too many of a card puts up the "Extra Cards" dialog (its buttons are D-pad targets); Wiz Stats (10 targets, hover 10 of 10), the clue list (Done only in a new game: no clue yet), the world map (4 targets) |
| Trade ("Which card do you seek?") | the village in a tower's domain has a trade button; its screen has one table target, Done (the kinds and the names are lists the loop tests itself, as in 1.0: stick) |
| Castles, towers, world magic | a castle's gate (seen in two games) and a tower guard's menu are the text menu (two lines as D-pad targets, A took the second: "Yes, enter the castle", "Pay 40 gold"); "Pay" at a tower led to a village-like screen with nine targets; a world magic is a crystal-ball message that waits for a click, and a place's entry message ("You happen upon ...") too: no targets, A is the click; inside a castle the arrow keys walk, as in 1.0, and a message ("Iron Star in effect.") is closed by A or Back. `sota_pad_play.py --only places` puts the party on each kind by a poke and prints what the D-pad saw; which of these a place shows first varies from game to game, and the poke sometimes lands the party beside the place without the entry firing, so the step checks only that the game is back on the map. The mazes were not walked in detail (below) |
| Duel, encounter to board | the encounter's text menu (2 lines, **D-pad**), "Duel this ...", the intro movie, the coin toss and mulligan dialogs and "Start the duel" (their buttons are D-pad targets: "Play first", "&Start the duel"), then the board: **43 targets** of the five kinds (cards, Done, life totals and faces, piles, mana rows, phase icons) (the D-pad's own checks, `nav_play.duel_checks`, written for 1.0 and run unchanged: the list is what the window tree shows, a click at the middle of every target reaches that target's window (0 wrong); on a board of 47 targets (6 permanents, a hand of 6) every move of 47 targets x 4 directions landed on the middle of a target (165 moves, 0 not) and went the way it was pressed (0 not), 132 of the 165 were undone by the opposite direction (1.0's note says about three in four), every target was reachable from the hand's last card (47 of 47), the big card after D-pad moves onto four cards was the one the real mouse shows there, B on a card opens a menu of five rows (`View in full card`, `Show ID tags`, `Show invisible effects`, `Show all cards' summoning sickness`, `Help...`) that the D-pad walks row by row and Back closes, Done was reached in 2 presses and A on it passed the phase, A on a card of the hand acted as a click); a land was played, a creature cast (A on it, A on the lands to pay), an attack declared and six phases passed with the stick and A |
| Reward | the opponent's life poked to 0 and a phase passed: the wizards' movie, then "Take the cards. Take the dungeon clue." as two D-pad targets; the clue taken, its page (Done is the one target), Done; the map's menu, "Dungeon Clues": **the clue's row is a D-pad target** (`clue 0`, the clue list's group), the pointer on the middle of its buttons got the hover, A on the row opened the clue's page, Done went back, Done left. "Take the cards" (the other line, an earlier run of the step) took the three cards with no question and the map came back. Two 25-minute soaks on this runtime (`sota_soak.py`: 3 games and 6 duels; `--mode monkey`: 4 games, 59 places) ended with no CRASH, HANG, STUCK or STDERR event |

**What was not seen, or not as the task wants it.**

- **The card picker's list** (`0x4f041d`): no flow of play reached it, so the D-pad on it is not seen; its group (`HK_CARDLIST`, written and unit-tested against the game's own test for every pixel at three sizes) is in no row. The one place where its numbers were read from the running game is the call from the control pipe: the arrays are where the profile's offsets say (x 100, 156, 212, 268, 100 and y 16, 16, 16, 16, 100 for five cards) and the boxes match the picture, but the hook read the wrong thread's frame there (the called function runs on a thread of its own and the hook takes the registers of the one that ran last), so the targets were not listed. What does work from that call: the question is entered from `0x4f0b96`, the profile's site, the hint line appears, B answers n (the list's loop goes on) and A answers y (the question ends; what the function returned was not observed, because its thread ran beside the real game loop and the two drew over each other).
- **The mazes of castles, towers and dungeons** were not walked with the pad beyond the gate and a message (a poke put the party next to a place more than once without the entry firing, and the machine was slow); the D-pad is the arrow keys there by design, as in 1.0.
- **FaceMaker**: stick only.
- **2.15's floating duel windows** (the ante, mulligan, hands, situation bar, the minimisable spell chain and combat windows): in the duel's window tree there is no window for the ante or the mulligan (they are dialogs and pictures), the two hands are `MAGICGAME_HandClass` windows (movable by their title; their cards are targets wherever they are), the spell chain is `MAGICGAME_SpellChainClass` with `Spell Card` children of the class the D-pad already reads, and the attack and block column is `MAGICGAME_AttackPhaseDisplayClass`; nothing of it needed a change in `navwm.c`. Dragging a window or minimising one with the pad was not tried. The "Select target card." dialogs of a spell (Demonic Tutor: 24 cards of a 36-card library) are dialogs whose cards are `ShowListCard` windows: D-pad targets, A picks.
- **A real controller, a real finger, a real display**: none, as in every milestone.

**The 2.15 profile, per hook, after Milestone 4** (the rows of Milestone 2's table that changed; the rest are as they were). "Verified" is the same rule as before: run, and the effect seen. `hooks_verified` of the `shandalar.exe` row is now every group but `HK_CARDLIST` (which no row holds): `HK_DISPLAY | HK_PACE | HK_KEYS | HK_BUTTONS | HK_TEXTMENU | HK_BUYCARDS | HK_CLUES | HK_TITLE | HK_VIEWCARD`.

| 1.0 | 2.15 | what | M2 | **M4** |
|---|---|---|---|---|
| `0x44b84b` | `0x4eab14` | the mouse snapshot | verified as the nap, not as `screens.c`'s hook | **verified as `screens.c`'s hook** too: `PORT_SCREENS_TRACE=1` shows every screen's loop taking it, and the screens it notes are read (hover check 100%, below) |
| `0x519c24`, `0x67f780`, `0x67f7d0` | `0x577cec`, `0x7270e0`, `0x727130` | the button table's context, record counts, record pointers; the record's offsets (`+0x10 x, +0x14 y, +0x18 w, +0x1c h, +0x24 handler, +0x40 type`) | not run | **verified**: the pointer put on the middle of every table button of the title menu (2 and 4), difficulty, colour, the village (9), Cards for Sale, the save screen (10), Wiz Stats (10) and the world map got the game's own hover on that button (`0x5780bc`, 1.0's `0x519ff4`), every time; the offsets are 1.0's |
| `0x489748`..`0x489c9c` and the seven globals | `0x4b6fe7`..`0x4b753c`; `0x6a0f54` left, `0x6a0f58` top, `0x728114` right, `0x577c4c` line height, `0x728120` first choice line, `0x728110` choice count, `0x728128` mask | the text menu | not run | **verified**: the encounter's "Duel this ... / Pay N gold" (396,481)-(631,498) and (396,498)-(631,515) at 1024x768, the castle gate, the map's nine-line menu is the same function: A on a line did what a click on it does (gold paid, the duel started); the count global `0x728110` ("weak" in the match) is right (2 for the encounter, 9 for the map's menu) |
| `0x509517`..`0x509fd4`, `0x61e060`, `ebp-0xa8`, `ebp-0xa0` | `0x4a28c7`..`0x4a347c`, `0x69eb70`, `ebp-0xa8`, `ebp-0xa0` | Cards for Sale | not run | **verified**: the four cards' boxes (153..307 by 236..390 and so on) are where the cards are drawn, a sold card's id is -1 and drops out, A on a card asks the question |
| `0x48f523`..`0x49094c`, `ebp-0x12d8` | `0x4aa415`..`0x4ab73e`, `ebp-0x12d4` | the clue list | not run | **verified**: a row `clue 0` (136,119)-(536,216) is a target when the count local says there is one, and A on it opened the clue's page |
| the title loop (`0x47a2e6`..`0x47a94c`) | `0x538e74`..`0x53952f` | the title menu | not looked for | found by `PORT_SCREENS_TRACE` (the table is passed from `0x5394d0`); **verified**: a tap of Back does nothing there and a hold of 0.9 s leaves the game (`sota_pad_play.py --only back`) |
| `0x4f156e`, `0x468c0e`, `0x468915` | the sell question | | not run, out of the row | **not a site, and not reachable**: `0x468c0e` is in `0x468533`, which no instruction calls and no table points at (a scan of every section's bytes found no reference to its address); `0x468915` in the same function is the key menu of its colour filter (r, b, u, g, w), not a question. `PORT_TRACE_ADDRS` on `0x468533` over two soaks (25 minutes each: duels, rewards, the monkey's villages and castles) and the villages and deck editor of the pad run: no call. The deck editor's sale is the card's right-click menu, which sells at once |
| `0x45119d` | `0x4f0b96` | "Take this card?  (Y/N)" | not run | **verified, with the limit below**: the question is the confirmation of the game's **card picker** `0x4f041d` (not of a reward screen); a call of that function from the control pipe put its list on the screen, a click on a card asked the question (`the game waits for a key (called from 0x4f0b96): a (Y/N) question of the profile` in the input log, the hint line on the screen), B answered n and A answered y |
| (no 1.0 counterpart) | `0x4f041d`..`0x4f0cdc`, locals `ebp-0x7d8` count, `ebp-0xfb0` x, `ebp-0x1780` y | the card picker's list (320 x 240 space, 0x30 squares) | | **found, in no row** (`HK_CARDLIST`): the arrays were found in the function's frame by their values (5 cards: x 100, 156, 212, 268, 100; y 16, 16, 16, 16, 100) and the boxes match the picture; the D-pad on a list was not seen, because the only way to put one up was the control pipe's `call`, which runs the function on a thread whose registers the hook does not see (the hook read another thread's frame). The 19 callers are duel-time pickers (the keys in `prompts.txt` name Jandor's Ring, Aladdin's Lamp, Sylvan Library, Visions, Land Tax, Ragman, and others) and the deck lists of 500 slots; none was reached by playing |
| (1.0 `viewcard`) | `.viewcard = {.cmd = 0x6e}` | the card window's own "View in full card" command | LB stays Page Up | **verified**: see "View card" below |


**View card (item 3).** LB, V and the middle button work in 2.15 with **the same command, 0x6e**. 2.15's card windows do not draw their menu from a resource that has no such command, as this note's earlier line and the profile's comment said (that was a guess from `MENUS.TXT`); the window procedure of `MAGICGAME_CardClass` (`0x5102bc`, registered by `0x50fc30`) answers `WM_COMMAND` 0x6e at `0x511132` by sending the Full-size card window (`MAGICGAME_FullCardClass`, created at `0x448cb2`, its handle in `0x83ba94`) the message `WM_USER + 1` with the card's two numbers (the lookup is `0x4f44ae`), exactly as 1.0's does; the three-second hover timers are the same. So `.viewcard = {.cmd = 0x6e}` is the whole change (`HK_VIEWCARD`), nothing is written to the game's memory, and a unit test (`test_wm`) posts the command to the card under the pointer for both builds. **Run**: on a 2.15 duel with cards of both sides, the pointer put on a card of the hand and on permanents of the opponent's territory, LB, V and the middle button each: the big card changed within 0.6 s (the game's own hover takes three seconds), and the picture LB gave was the one the hover gave after its wait. The second press showed the card enlarged and centred (350 px wide at 1024x768) and dimmed all round; B, a key, a click, a right click, A, the D-pad, Back, Y and X each ended it with nothing sent to the game and the window exactly as before; V and the middle button twice did the same; after the pointer moved the next LB was a first press again; and A on Done passed the phase afterwards. (`card_view.py`'s whole duel part passed on 2.15.)

**Touch (item 4)**, through the control pipe's finger steps only (`tools/soak/sota_touch.py`, `PORT_TOUCH=1`: `touch.c` and `front.c` are the real code from the finger on; the iPad, the iOS app and a real finger were not): a tap on "Buy Cards" and on a card, then "Buy for N gold? (Y/N)": **a long press (a right click) answered no** (the log says `n`, gold unchanged) and **a tap answered yes** (`y`, gold 400 to 350); in the deck editor a long press on a card opened its menu ("Sell Card for 30") and a tap on the row sold it (350 to 380). in a duel a long press on a card of the hand opened its menu (`View in full card`, `Show ID tags`, `Show invisible effects`, `Show all cards' summoning sickness`, `Help...`) and a tap on `View in full card` showed the card in the Full-size card window at once. The card pickers' "Take this card?" is the same code, so the same two answers.

**What was built.** `profile.c`: the `shandalar.exe` row's screen groups (`.buttons` complete, `.textmenu`, `.buycards`, `.clues`, `.title`), the Take site, `.viewcard`; `HK_CARDLIST` and `.cardlist` in the structure, in no row; `screens.c`: `SCREEN_CARDLIST` and `screens_cardlist_targets` (the game's own test, compared with every pixel in `test_wm`), `PORT_SCREENS_TRACE=1` (each loop's return address once: how the loops were found); `yesno.c`: a line in the input log for every wait for a key ("the game waits for a key (called from 0x...): a (Y/N) question of the profile / not a profile question", which is how a build's sites are found); `call.c`: eight pre-call hooks were exactly full (2.15's row installs eight), now sixteen; `front.c`, `front_sdl.c`: the control pipe's `call` takes five arguments; tests: `test_profile` (the row's values, the groups, the sites, the loops, the card list in no row), `test_wm` (`test_screens_sota`: every address of the row against what the running game showed, the card list's exhaustive test, the view-card command for both builds, the sites), `tools/soak/test_ctl.py`; `tools/soak/sota_pad_play.py`, `tools/soak/sota_touch.py` (an encounter is made by writing a monster record, `0x725310`: type 22, the party's pixel position plus 40, 3, 5, 0, which the game then meets at its next step; the script's own keeper that empties the table to keep monsters off a menu empties it for good, which is what made two runs find no monster to meet). The decks are random, so the duel step's creature and attack are best effort: after twelve phases with nothing castable they are printed as NOTEs and not counted.

**Hours.** About about five hours (wall clock, counting only the working time, not a pause of a few days for a rate limit) of agent time, wall clock from the first command to this note, against the 10 to 16 the plan gave. More than half of it was waiting: the machine ran at a load of 14 to 20 from other jobs, a new game to the map takes 1.5 to 5 minutes each time, and the scripts were run many times to get past what the machine and the game's randomness (an encounter walking into the party, a village on the way) did to them. What took the thinking: finding that the sell site is dead code and the take site a duel picker, and finding the card window's command by reading its window procedure; the hooks themselves were cheap because the matched addresses held again (no address of Milestone 2's table was wrong).

## Milestone 5: the Magic Shell (magic.exe 2.15)

Milestone 5 was: `magic.exe` 2.15, the "Magic Shell" the expansion's disc starts first (window class `MAGICGAME_MagicShellClass`, 800x600), paints and works, and the shell <-> Shandalar program graph works. What follows is what ran on this machine (macOS, Apple Silicon, SDL's dummy drivers, an 800x600 window, the pictures looked at by eye and not kept, the install made by `pentamoor-install ... --sota ... --patch ...` in this checkout, which now builds a fifth module, `game_shell`). Everything was driven through the control pipe (`click`, `key`, `shot`, `windows`, `peek`), each run with its own pipe and its own overlay. `./pentamoor sota shell` starts it.

### Why it was black

The earlier note ended on "the picture it waits for is not found: not solved". It was not one thing but a chain of five, each hidden by the one before:

1. **The update region was gone before the program looked at it.** The port cleared a window's "needs painting" flag at the moment it handed out `WM_PAINT`. The shell's paint routine begins with `GetUpdateRect` and paints only what that says; the answer was "nothing", so it returned, and the window stayed the colour of its class brush. Windows keeps the update region until `BeginPaint` (or the procedure's return); the port now does the same (`Window.painting`, `user32.c`). This is the generic fix the task asked for, and it was the black screen. It could not be seen earlier because the paint routine does nothing and calls nothing when it is told there is nothing to paint (the note's "about 25 passes a second on timer messages" and "no call" were exactly that).
2. **The picture decompressor's block address in the profile row** was a guess made from 1.0 (`0x5439a8`; the right one is `0x543ba8`), which made every `.pic` come out 16 bytes long. The row is new in this milestone (`ID_V215_SHELL`, `profile.c`), so nothing else was wrong with it.
3. **The port drew push buttons only.** The shell's pages are made of standard controls on ordinary windows (static text, group boxes, check and radio buttons, edit boxes, combo and list boxes, spin buttons, scroll bars) that the port had drawn only inside modal dialogs. `compose.c` draws them on ordinary windows and on modeless dialogs now (`ui_draw_control`), after asking the parent how each is coloured (`WM_CTLCOLOR*`, answered once when the control needs painting and kept for the compositor: `wm_query_ctl_colors`).
4. **The pages lay themselves out in `WM_SIZE`,** and a dialog window never got one (`geometry_changed` returned for windows without `proc`; a dialog has `dlgproc`). All controls of a page sat at 0,0 until that was fixed.
5. **`SetDIBits` read its bitmap-info pointer from the wrong argument,** so the shell's own button faces (it draws its push buttons itself, with pictures) came out black.

### What the shell does now

Seen by eye, every page of it, at 800x600:

| Page | What there is and what works |
|---|---|
| Title (the five round buttons Duel, Tools, World, Help, Player over the blue "Magic: The Gathering, Spells of the Ancients" picture) | draws, with the lit ball for the page that is open; the buttons answer the mouse (hover face, press) and the keys |
| Duel: Solo Duel | player name, "Your deck" and "Opponent's deck" combo boxes, Match parameters (Ante check box, "Best of" spin button), Opponent skill (four radio buttons), Duel Options..., Load match..., Start match. **Start match plays a real duel** with the coin toss, ante and mulligan dialogs, the board, and the AI; see the CD check below |
| Duel: Gauntlet | the difficulty group with its combo box, Ante, two spin buttons, Duel Options..., Load gauntlet..., Run the gauntlet: **starts a duel** (the coin toss window, which plays its movie, then the board) |
| Duel: Sealed Deck | Tournament Setup (rounds, free lands, 40 or 60 cards: spin buttons and radio buttons), Match parameters, Start tournament: the **pack screen** ("Sealed Deck Tournament Information", the starter and booster packs on the Italian garden, DONE) |
| Tools | Deck Builder (the real deck library in the shell's own process: "Deck Maker" with the cards, the filters and the deck strips), Face Builder (starts `FaceMaker.exe` as another process) |
| World | Shandalar (starts `shandalar.exe` and ends the shell; the adventure's Exit starts the shell again on this page), Animation (the page only: its movie files are on the disc) |
| Help | Help File and Read Me (they run Windows' own `WinHelp.exe` and `Write.exe`, which are not programs of the game: the runtime says "process: not started: ..." and the shell goes on), Tutorial and Credits (they look for the disc, below; seen in earlier runs, not repeated at the end) |
| Player | the screen name page (an edit box that takes typing now) |

What a player can do: click the pages, set the spin buttons (the arrows, or type digits), choose decks, tick Ante, start a single duel or a gauntlet and play it to the end with the mouse, open the sealed deck's pack screen, open the deck builder, and go to Shandalar and back. Settings are kept: the shell reads and writes `HKCU\Software\MicroProse\Magic: The Gathering\SoloOptions` (seen written after a play: `Difficulty`, `PlayerDeck`, `OpponentDeck`, `BestOf`, `Ante`, ...) and the keys of its other pages (`GauntletOptions`, `DuelOptions` ... as the program's strings name them), which `regstore` keeps in `registry.dat` of the overlay (the store keeps up to 128 values now and the `HKCU` side of `MicroProse` is no longer ignored).

### What was built

- **Windows layer:** the update region above; `CreateDialogParamA` and `IsDialogMessageA` (Tab, Esc, Enter), `EnumChildWindows`, `WM_SIZE` for dialog procedures, `SetCursor`/`GetCursor`, `ShowScrollBar`, `GetWindowTextLengthA`, `CharLowerA`/`CharUpperA`/`IsCharAlphaNumericA` (code page 1252), `SetDIBits` fixed; standard controls drawn on ordinary windows (the compositor draws the ones the program only subclassed too: the shell subclasses its owner-draw buttons, and the new `EnumChildWindows` is what lets the **deck editor of Shandalar subclass its buttons**, which the D-pad's targets had to learn: `navwm.c`'s `plain()`); **spin buttons** (`msctls_updown32`: range, position, buddy text, arrow clicks, `WM_VSCROLL`, `EN_CHANGE`) and **typing into an edit box** of an ordinary window (a click gives it the focus; characters, Backspace, `ES_NUMBER`, `EM_LIMITTEXT`).
- **C runtime and others:** `FindFirstFileA`/`FindNextFileA`/`FindClose`, `_adjust_fdiv` (a data import), the **MCI** calls of the shell (`mciSendCommandA`/`mciGetErrorStringA`: open, play, stop, pause, seek, set, status and window position of a digital video, played by the port's own movie code into the window the program gives it), `CreateProcessA` (see below).
- **Profile and installer:** the `magic.exe` row, the `programs` lists (the shell starts Shandalar, the deck builder, FaceMaker, and itself), the build of `game_shell`, `tools/install` and the release checks say five programs and list the module; `pentamoor` and `pentamoor.bat` take `sota [shell|shandalar]`.

### The process model, as built, and where it stops

`WinExec`, `CreateProcessA` and `_spawnl` start another `pentamoor-run` for the program the **profile** names (`programs`), with the overlay, folder, size and display settings of the first, a control pipe of its own (`<PORT_CONTROL>.<program>`) and its command line (`PORT_CMDLINE`); a `_P_WAIT` mode and `WaitForSingleObject` wait for it, and the named memory the programs share (the game's "graphic pages") is handed over (`PORT_SHM`). The shell starts Shandalar with `/MTGshell` and **ends itself**; Shandalar's Exit starts `Magic.exe /start3,1`, which is the shell again, on the World page. So one program of the game runs at a time (a short overlap while the next one starts), and the one SDL window is the new program's.

- **`FindWindowA` across processes is not done; a rule in the runtime does the same job.** The original starts by looking for another window of its class and, finding one, brings it forward and ends. The runtime cannot see another process's windows, so `<overlay>/instances.dat` keeps a line per running program of the game: a program that starts while another one runs in the same overlay and was not started by it says so on stderr and ends at once (`PORT_NO_INSTANCE_LOCK=1` turns that off). A program started by another is of the same family (`PORT_FAMILY`) and may start while its parent is still there. `FindWindowA` itself stays a stub that finds nothing.
- **The overlap is two processes and one window for a moment.** There is no hand-over of the window: the first program ends after starting the second, which makes its own.
- **Not done:** `WinHelp.exe` and `Write.exe` (not programs of the game: logged and ignored), and a program that the profile does not name (not started: the message names the file). The Windows and Linux hosts were not run (`plat_win.c` compiles in CI only; the instance lock's liveness test is `kill(pid, 0)` there and `OpenProcess` on Windows).

### The CD check

The shell asks for the game's disc in three places that were reached: **Start match** (the duel starts and ends at once, silently, with the installer's default licence value), **Credits** and **Tutorial**. The code is the checker at `0x497e7c` of `magic.exe`, the function at `0x50111b` that asks it query 8 ("skip the disc check", bit 17 of the flag word; `docs/notes/sota-licence.md`), and `CdTools.dll`'s `CheckOriginalCD`/`CheckSotaCD` behind it. **Nothing was faked:** the runtime answers the disc calls as it did (a fixed disk, no label). To play the shell's duels the run used a scratch overlay whose licence value was made by the installer's own licence step with `--no-cd` (the installer's option, off by default, described in the licence note); that is a test setup, not a result. A user who owns the discs and wants the shell's duels without the disc uses the same installer option.

### What ran for real, and what is unit-tested only

- **Ran for real (the real files, the real lifted code):** every page above; Solo Duel and Gauntlet duels played through (20 turns of 4 duels in the last soak run, 30 turns of 6 in the one before turns in the shell soak, a duel played with lands, spells, attacks and prompts); the Sealed Deck pack screen; the Tools deck builder (with the cards on the screen); the chain shell -> Shandalar (title menu drawn) -> Exit -> shell (World page) -> quit, by process id: no process of the chain was left; the registry values the shell writes (read back from `registry.dat`).
- **Unit tests only (no game files, in CI):** the window layer (`test_wm.c`: update region, modeless dialog, `WM_SIZE`, Tab/Esc/Enter, control colours, a dialog's own paint, spin buttons, typing, the D-pad's targets for a subclassed deck button), MCI (`test_movie.c`), the `Find*` calls, `CharLowerA` and the other character calls (`test_win32.c`), `SetDIBits` (`test_gdi.c`), the process calls and the instance lock (`test_process.c`: the pure text functions of `instances.dat`, the family rule, the profile's `programs` lists), the registry store (`test_regstore.c`), the profile row (`test_profile.c`), the installer's module lists and messages (`test_release.py`, `test_sota.py`, `test_licence.py`), and the soak script's helpers (`tools/soak/test_ctl.py`).
- **Not run:** Face Builder's FaceMaker from the shell was started (it is in the profile's list) but its portrait screen was not driven; Animation and the World page's other movie use `MCI` on files of the disc, which this install does not have; the Help page's two programs; ManaLink's `magic.exe` (out of scope); the Windows and Linux hosts; a controller or touch on the shell (follow-up, below).

### Found by playing, fixed

- **The Sealed Deck pack screen stayed grey.** It is a modal dialog that paints itself (`WM_PAINT`), and the new colour-query pump, which took the update region of anything with a `builtin` flag, took the dialog's own. The pump now leaves windows that have a dialog procedure alone (`test_wm.c`).
- **The spin buttons were pictures,** so "Best of", the rounds and the free lands were empty boxes. They work now, with the edit box beside each.
- **Shandalar's deck editor lost its D-pad targets** (`sota_pad_play.py`: "0 buttons"). The new `EnumChildWindows` is what the deck editor uses to subclass its buttons, and `navwm.c` only took buttons with no procedure at all. `plain()` accepts a subclassed standard control now (`test_wm.c`).
- **A savefile in the install folder** (an earlier run's, copied with the folder) made the title menu offer Load and failed the pad check's first line; not a port bug, but worth knowing: the pad check wants an install with no `MAGIC*.SVE` in it.

### Is Shandalar unchanged?

The 1.0 pad smoke (`pad_play.py`) passes (18 checks), and `make -C src/port test check-front check-module check-run check-program check-build` and `pytest` over the tool folders are green. `sota_pad_play.py` (2.15's Shandalar from a new game to a duel and its reward, with the D-pad) **found one real regression, which is fixed:** the deck editor's buttons (above). It is also a **flaky check on this machine**, and the honest comparison is this: it plays a *new* game, so the world is random (the party starts in a village, or beside a castle; an encounter menu then has one line, not two) and several steps read the game's state on one frame. With the runtime of the previous `main` and the same lifted module it passed completely once (186 checks) and failed one check (the pointer following card to card) another time; on its first part (new game, map, save, village) it failed in 2 of 4 runs ("the D-pad is still the arrow keys on the map", "B opens the game's menu"), and the runtime of this branch failed the same checks in 2 of 4 runs ("Back closes the menu" and the same two). Whole runs: the previous `main`'s runtime failed 0 and 1 checks; this branch's final runtime failed 8 (the Save screen showed 6 slot targets instead of 10, and the Load and village steps after it followed; not seen again in five later runs of that part alone), 3 (the map menu of a run that began in a village, and the duel's poke and reward that followed) and 2 (the stronghold's one-line encounter, then the reward step): not enough runs to tell a difference from the check's own flakiness, and **the Save screen's 6 targets is the one failure that is not explained** (it was read mid-draw, or it was not). Nothing in Shandalar's own paths changed except the controls' hit-targets (an edit box or a spin button of a modal dialog is a target of its own now) and the update region (a window is "painting" until `BeginPaint`: the paint routines of 1.0 and 2.15 that read the region first now see it).

### The soak

`tools/soak/sota_shell_soak.py` (new, in `tools/soak`, helpers tested in `test_ctl.py`) drives the shell and its program graph through the control pipe, each round a fresh copy of a scratch overlay that holds the licence value (made by the installer's own step with `--no-cd`, a test setup). It logs as `soak.py` does (CRASH, HANG, STDERR, SETUP, NOTE; `events.jsonl`, `summary.txt`, `rss.csv` once a minute) and adds ORPHAN: after every round the process group is stopped, and every process id the runtime logged ("process: started ...") must be gone.

- **Monkey mode, the bar:** random clicks on the controls of the window tree (about 45 %), clicks anywhere, right clicks, keys; every 20 to 70 s it goes the way a player goes to the adventure (World, Shandalar), follows to `shandalar.exe` through its own pipe (`<ctl>.shandalar`), lets its title draw, leaves it by the title menu's Exit, which starts the shell again (`<ctl>.shandalar.magic`), and goes on there. **Final build, 20.0 minutes, seed 1022: 8 rounds, 5 hand-offs shell to Shandalar and 5 returns, 2,145 actions (845 clicks anywhere, 648 clicks on controls, 461 keys, 191 right clicks), no crash, no hang, no stderr line outside the known list, no orphan; the resident set of a process stayed between 63 and 94 MiB.** The run before the last two fixes (20.1 minutes, seed 20261022): 6 rounds, 12 hand-offs and 12 returns, 1,880 actions, the same zeros. The known list is the runtime's "process: not started: ...Write.exe / WinHelp.exe" lines (the Help page; the shell goes on) and the program's own `[debug]` lines.
- **Duels mode:** the Duel page's Solo Duel and Gauntlet are started with the buttons and played as `soak.py` plays (lands, spells, attacks by clicking, prompts cancelled at random, the coin toss, ante and mulligan dialogs clicked through), conceded after 3 to 9 turns, and the page comes back for the next. **Final build, 12.1 minutes, seed 79: 4 duels (2 single, 2 gauntlet), 20 turns, no crash, no hang, no stuck screen, no stderr;** an earlier run on the build before the last fix: 12.0 minutes, 6 duels (4 single, 2 gauntlet), 30 turns, the same. One process grows from 67 to 109 MiB over eleven minutes of duels (about 4 MiB a minute: the cards' pictures, as in 1.0's soaks; not looked into).
- **By hand, by process id:** shell (26111) to Shandalar (26132) to its Exit to the shell (26160): the first shell and Shandalar were gone (`ps`) when the second shell was up; the shell's close button (it sends itself `SC_CLOSE`, which the port did not turn into `WM_CLOSE` before) ends it with status 0 and empties `instances.dat`.

### Follow-up, not done

- **Controller and touch on the shell** (`pad`/`touch`): the shell's pages are standard controls inside child dialogs, which `navwm.c`'s dialog collector could take (it collects the controls of a modal dialog); the page buttons are subclassed owner-draw buttons, so the plumbing exists (`plain()`), but the page switching, the combo boxes and the spin buttons need targets and `A`/`B` rules, and a hover check like `sota_pad_play.py`'s. Not almost free, so not done. A mouse and a keyboard work.
- The caret and selection of an edit box (typing appends and Backspace removes the last character).
- `WinHelp.exe`/`Write.exe` (the Help page's two programs): the port has `winhelp.c` for 1.0's help; the shell's help file is not wired to it.
- ManaLink 3.0's `magic.exe` (a second profile row, the 151-slot duel layout): out of scope.

**Hours.** About six hours of agent time (wall clock from the first command to this note, 21:16 to about 03:40; about two and a half of them waiting for runs: a full pad check takes 13 minutes and was run nine times, with the previous runtime for comparison), against the 8 to 20 the plan gave. The largest items: the black screen (the paint routine's silence hid five causes, each found only after the one before was fixed), the standard controls on ordinary windows and the pages' layout (a third of the code), the instance lock (the original's `FindWindow` rule where another process's windows cannot be seen), and three things only playing found: the deck editor's lost D-pad targets, the grey pack screen, and empty spin boxes. The plan's "pad and touch only if almost free" was not, and is the follow-up.

## Effort (hours of agent work, rough)

The first column is the estimate of the first version of this note, the second what the work found since (the profile mechanism has been built; the lifter wrapper and the runtime experiment exist as scratch work; ManaLink 3.0 is new). 2.15 is the target; ManaLink 3.0 is a separate block.

| item | before | now |
|---|---|---|
| Profile mechanism: fingerprint, a profile per version, the runtime reads it instead of constants, hooks only for a verified profile | 8 to 12 | **done**; the rows for 2.15 (a dozen files with `.lzw`, ids, bases) 2 to 3 |
| Lifter: the 47 signatures (best read from the executables), `rol`, reading the master table by its pattern, the libraries' cdecl exports, the second program and the libraries in `liftrun`, `manifest.py`, module build and release layout for two programs | 6 to 10 | 5 to 9: the signatures and the master-table finder exist (`liftsota.py`, `sotamaster.py`) and `rol`/`ror` is a dozen lines (lifter test needed); the DECK.EXE stub, the libraries' bases and the module build for three programs are known |
| Win32 and C runtime additions for shandalar.exe (the 21 calls it lacks, 27 for magic.exe; TLS; the update-region calls; registry values for 2.15's start-up; `qsort`, `strcoll`, `_beginthreadex`, `setjmp`/`longjmp` (the lifter has to model `setjmp`: not trivial)) | 8 to 14 | 6 to 10: the experiment has working versions of most (TLS, `GetVersionExA`, the registry pair, `ExtTextOutA`, the msvcrt alias); real ones need tests, and the registry values need a rule |
| Installer: second disc, cabinet and patch (the readers exist), merge over 1.0, fingerprints, music and video copy, the invented registry values; tests | 6 to 10 | 6 to 10: the readers now catch a cut-short patch and read both cabinet layouts, and `sotaoverlay.py` is the merge; the installer's three sources (the 1.0 disc, the 2.0 cabinet, the six patch files) are all known |
| Process model: the three spawn calls, launcher by program, hand-over of the window, saves and settings shared | 8 to 14 | 8 to 14, **plus 4 to 8 for `FaceMaker.exe`**: Start New Game runs it (`_spawnl(_P_WAIT, ...)`) and waits, so it is a fourth program to lift and a second window to hand over |
| The shell page (magic.exe black screen), the CD checks | 8 to 20 | **done in Milestone 5** (see its row below; the black screen was five things in a chain, the first the update region; the CD checks are not faked and were not part of it: reported where they are); the "garbage name screen" of the first note is replaced by the FaceMaker item above |
| Porting the hooks (pace, screens, yes/no, name box, controller navigation) to 2.15: read the 19 changed sites against 1.0's, re-verify all 54, find the sell site, adapt `navwm.c` to the movable windows and the shell's pages | 10 to 16 | 10 to 16 (not touched here) |
| Tests, a soak on both programs, CI (a SotA job cannot use the discs: only the profile logic, the cabinet reader on a made-up cabinet, and the patch reader on a made-up archive) | 8 to 12 | 6 to 10: the cabinet and patch readers, `cards.dat` reader and overlay have tests on made-up files (`tools/research/test_research.py`, in CI) |
| **Shandalar alone, without the screen hooks (title, new game, overworld, duels with the mouse)** | about 40 to 60 | **about 36 to 55 before Milestone 1; Milestone 1 (title to overworld, walking) took roughly 20 to 28 of it** (an estimate: the agent's time was not metered). Left for duels, pacing hooks, resolutions and a soak: about 15 to 30 |
| **Milestone 2: through a duel, the pacing and display hooks, the (Y/N) and name box hooks, a soak, a save and a load** | 15 to 30 (what Milestone 1 left) | **about 5.5** (wall clock, with about 2 of it waiting for soak rounds that ran beside other work; the hooks cost less than estimated because the matched addresses held, the soak harness and the busy loops more) |
| **Milestone 3: one command installs 2.15 from the discs and the patch** (cabinet, patch and overlay readers promoted, checks before writing, folder, hashes, build of the six modules, launcher, release, tests with fakes) | 6 to 10 | **about 2** (wall clock; the readers existed) |
| **Milestone 4: controller and touch** (the screens' groups, the (Y/N) sites, the view command, the D-pad run on 2.15's screens and duel, touch through the finger steps, docs, tests) | 10 to 16 | **about 5** (wall clock; the addresses held, two of the task's premises did not) |
| **Milestone 5: the Magic Shell** (the black screen, the standard controls and pages, the process graph with its instance lock, the launcher and installer, a soak of the shell) | 8 to 20 | **about 6** (wall clock; about two and a half of it waiting for runs; the controller and touch for the shell were not almost free and are left) |
| **Everything above for 2.15** | about 90 to 140 | **about 80 to 125** (Milestones 1 to 5 are inside it: the lifter, the Win32 additions, the process model and FaceMaker, the installer, the hooks and the controller for Shandalar, and the shell page are done; the controller and touch for the shell, the engine and a clean-C pass remain) |

What Milestone 1 did against the rows above: the lifter row (`rol`/`ror`, `setjmp`, signatures, master table, builds) and the Win32 row (the 21 calls, registry, TLS) are **done**; the process model row is done for sequential use with FaceMaker lifted for real (it took less than the 4 to 8 estimated for FaceMaker, because it lifted without changes beyond `setjmp`); the installer row is half done (lift and build; not the folder); the shell page, the hooks, the engine and the soak are **not started**.
| **ManaLink 3.0 on top of 2.15**: profile rows and bases for 6 files (1 to 2); `ManalinkInterface.dll` provided by the host as 16 "no network" functions (3 to 5), or the two unsupported instructions lifted (2 to 4); the 14 more Win32 and C calls (3 to 5); the shell's new pages (multi-duel, screen names, credits) and `MultiOptions` (3 to 6); installer: a second, optional, add-on cabinet in the other layout and the overlay (2 to 3); the 722-card table and 151-slot duel need nothing in the lifted code | -- | **about 15 to 25** (the shell's black screen is shared with 2.15 and counted there) |
| Not counted: the tutorial; the hand-written engine for SotA (new strides and offsets, and the functions with no counterpart: now **three** layouts, 1.0's, SotA's and ManaLink's); a clean-C pass over the changed parts | 40 and more | 40 and more |

## The licence value

Found in milestone 3 by disassembling `shandalar.exe` 2.15 (capstone) and by running with `PORT_TRACE_IMPORTS` and `PORT_WHO`; not re-checked by a second person. The addresses are 2.15's.

- `WinMain` (call at `0x489886`) runs a **machine-id function** at `0x4e68b9`. It reads `FirstInstallDateTime` and `ProductId` from `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion` (the key and value names are stored XOR 0x41) and builds a 12-byte id: the install time and the last 8 characters of the product id. If the reads fail, the program ends without a message.
- A second function at `0x4e6c0a` reads a 12-byte `REG_BINARY` value **`SerialNumber`** from `HKLM\SOFTWARE\MicroProse\Magic: The Gathering`, unscrambles it with the machine id and checks a nibble-sum checksum. A missing or wrong value is "bad". A good one yields a 32-bit flag word.
- A third function at `0x4e6ebf` does the reverse (encodes a flag word for this machine and writes `SerialNumber`). Nothing in `shandalar.exe` calls it; the original installer presumably did (not checked: its script is compiled).
- **Follow-up research** is in [sota-licence.md](sota-licence.md): what the original installer wrote (it loads a DLL disguised as `DuelSounds\Manaball.wav` from its own cabinet and calls its read and write functions, after both discs are verified), what each bit changes, and what the CD check tests. It corrects the next bullet: 1, 2, 4, 8 and 0x10 are the **query masks** the checker's callers pass, not bit positions of the flag word (they are bits 22, 8, 11, 17 and 28 of it; the query 1 answers yes before anything is read), and the per-entry table's accessor has no caller in `shandalar.exe`.
- **What the flag bits gate** (checker at `0x4d6b4b`, query masks 1, 2, 4, 8, 0x10): mask 8 skips the game's CD check (without it `0x417deb` looks for a CD drive, calls `CheckSotaCD` and shows the "CHECKCD" insert-the-disc message); masks 2 and 4 gate the cards of two sets (`0x4d6a07`, `0x53d883`); a per-entry table at `0x90f7c4` is gated through all five masks (`0x46a421`).
- `deckdll.dll` and `magic.exe` carry the same three functions (both hold the string "SerialNumber"; only deckdll's start-up read was traced).
- The machine id is used by these two functions only: it is not written to files or saves and not shown.

**What the port does.** It answers the two Windows values with fixed ones so that the program starts (`src/port/winsys.c`). It does **not** make up a `SerialNumber` (a read of it is "not found", so the check says "bad"), does not write one, and does not answer as if a CD were present. In every run so far (new game to the map, a conceded duel, a five-minute monkey run over ten places) the game never read `SerialNumber` and never reached the CD check, so what a player sees when the check does run (shops, the deck editor, rewards) is **not known yet**.

**Built (2026-10-18).** The installer now writes the licence value with the original installer's own writer after the discs are verified (`--no-licence-value` skips it); `--no-cd` is an opt-in that also sets the flag the game defines as "skip the disc check". What it does, what it does not do and what was and was not observed: [sota-licence.md](sota-licence.md#what-the-installer-does-now).

**Open (owner's decisions, 2026-10-17).** The owner's position: the game is not for sale anywhere; the aim is to preserve it properly and as ethically as possible. The line kept meanwhile: the runtime and the release archives hold no game code, data or licence value; a 2.15 install needs the user's own discs, which the installer checks before it writes anything; nothing is shipped that makes a copy playable for someone who does not own it (no generic serial). The idea under study, not built: have the installer, after it has verified the user's discs, do what the original installer did (write the value, bound to that machine, on that machine). That needed the original installer's behaviour established first (what flag word it wrote, from its compiled script) and what each bit changes in play: both are now written down in [sota-licence.md](sota-licence.md), with the options and an assessment of each.

## Risks

- **One build only, now with the whole of it at hand.** The first version of this note rested on a cut-short patch and a 2.0 deck library; the complete 2.15 set is checked here (six entries, every CRC-32, hashes above), but it is **one copy**: check the three program hashes against the community's known-good ones before relying on them, and note that the ManaLink add-on's `magic.exe` is not
  known to be byte-identical to the retail Duels of the Planeswalkers disc's (only the add-on was looked at).
- **Two versions never meet**: 2.0 and 2.15 are two profiles (50 of 54 addresses differ). Support one. ManaLink 3.0 is a third set of rows for `magic.exe` and the libraries, on top of 2.15 (it brings no `shandalar.exe`).
- **A mixed install has two duel layouts**: with ManaLink over 2.15 the Shandalar program has 101 slots a player and 622 cards, the shell 151 and 722; nothing here shows what happens to a deck or a saved duel that crosses from one to the other.
- **The matching is not proof**: 19 of the 54 sites are "changed" and two of them are below 0.5. Each needs to be read in both versions and, ideally, checked by running (the oracle VM, `docs/ORACLE_VM.md`: a Windows 98 image with the SotA install would be the way to check 2.15's behaviour, and the VM's disc needs the 2.0 media).
- **Legal and installer**: SotA needs the 1.0 install under it (so two discs are needed from the user), and the installer's checks of the original CD must be reproduced as "the first disc was given", not as a disc check in the game. The registry check in 2.15 reads Windows' own values and is part of a machine-bound licence check (see "The licence value"); what the port does about it, and does not do, is written there.
  Nothing in this work distributes game files or generated code.
- **Process model and display**: two programs that find each other by window class, on one SDL window, is the least certain part; an unexpected exit path (a program that expects the other to be running) can end the session.
- **The shell never painted**: until it does, nothing is known about the sealed deck page, the gauntlet page, the records, or whether any of it needs more of the port (modeless dialogs through `CreateDialogParamA` are there and unimplemented).
- **The engine**: the hand-written native engine and its differential tests (`tools/difftest`) have 1.0's strides and offsets; the new ones are known for two arrays only. The lifted program runs without them, so this is only a risk for the long-term plan (docs/ROADMAP.md).
- **The lifter's output is large** and each version is two more 50 MB sources to compile locally (a minute each here, more on a slow machine), and an installer that builds both 1.0 and SotA modules takes twice as long.

## Hashes

SHA-256 of what the numbers above were measured on (hashes are facts about files; no file is in the repository). The program rows are the build ids of `tools/lift/builds.py` and `src/port/profile.c`; every 2.15 row below (and its size) is also what the installer checks the folder it makes against (`builds.KNOWN`, `builds.SIZES`), and the three cabinets of the 2.0 disc and the patch are what it checks the sources against (`builds.SOTA_DISC`, `builds.SOTA_PATCH`).

| archive | bytes | SHA-256 |
|---|---|---|
| `SOTAV215.EXE` (the whole 2.15 patch) | 1,207,571 | `a428e981d1e920c05081a1c57f4eba0b4b75e9cda52f050cad3e33bc456b9c89` |
| `sotav215.exe` (the copy cut short) | 1,048,331 | `c0eef9b8f12b8a500dffa716500c6b82dcf9e4f9f1c57faeacecdee02903318c` |
| `MTG v2.00.iso` Setup/data1.cab | 55,460,517 | `cb021ce69e08b56a0bbb3acfe392f0dad7ded5d22768643a113f3115eaa8732f` |
| `MTG v2.00.iso` Setup/_sys1.cab | 205,707 | `8dfd7bd0e89fb33e1cfe147462409cf956cbc80b81b4889ad7f680f2584e1cab` |
| `MTG v2.00.iso` Setup/_user1.cab | 2,809,978 | `483e37b99d154024278ef549536629c02598784fe120cc48e356947477608fc0` |
| `ml_sota_us.zip` | 5,247,436 | `14dfc87facbde757ffbe74819d60f721fe731af6f7371c38da11616527624223` |
| ManaLink `data1.cab` | 4,591,805 | `4f94d5d7004c9810c06c658dcc892a9fd8e41e2bb62a18cc691e92adda976037` |
| ManaLink `_user1.cab` | 44,444 | `1b778ed778aeb06cfdd73787fb4d773273f0572b7215ad6dc6bddd256057aaba` |
| ManaLink `_sys1.cab` | 205,135 | `675470b6d0548a231e7c25bd78f3e42edc4c078dc4e2df6028c98c1ac04734cf` |
| ManaLink `setup.ins` | 56,294 | `eee51f0e87f1052e39986fde4576061ddcc9092ebc03e38dc1c28faae474cc36` |

| file | 2.0 | 2.15 | ManaLink 3.0 |
|---|---|---|---|
| shandalar.exe | `3d05f67f0971982602434fa91727b031044aabb627dbd04efd76ac072d175e8b` (1,739,264 B) | `e4e46718c451974756b66e7666ac0bf1cc9ebdbc5897eb04a87b8ea2a02353e7` (1,740,288 B) | -- |
| magic.exe | `a7c5e1cd74f88d779c4028dce551a926d7f6cd2728afb9be394728860409145d` (1,529,856 B) | `e948affc1c1fe74c4a9709350d6c184b8cb01548e57a70b5751a479fa3d2bf65` (1,530,368 B) | `db44ce9b6bfd2530f4c92558cfa484bf8305a77a7844f72679eb708a7e209d5a` (1,700,864 B) |
| deckdll.dll | `f5bc43ba59de9ed3e5847757fa234d2ff25e056fce0a6848f573ba4a51a996cc` (264,192 B) | `ce741d1f5547c143fd8494bbe09c26e918b892a3d9fc3c3761babb3c8268a667` (265,216 B) | `3b4623f412dfa5db31c88ce0b698acf857261e2b75ef35150383dafaa6b881a2` (355,840 B) |
| cardartlib.dll | `689be4a86ca843e76057172543cfa3516d8ccbc2efb1699e7c7935b6dc3ead11` (139,264 B) | same as 2.0 | `fada9019ac4879ff606352194c3926e24f79d67dbf7e705c74b0e95fbfbd611a` (139,264 B) |
| drawcardlib.dll | `c7747313d59b6fa48ec56b479dce9ed5d90f8a95fc47e93990c4369bbd2fa1f8` (178,176 B) | same as 2.0 | `c87d7ac3b8bf46a36a030ce33a0bea09e67205919a432b985479c73b9181dff3` (178,176 B) |
| CdTools.dll | `0d0c2bfa87de02499f1f73f21f34824b1c2572f3e6ae0b5dca7ca343ddf1b77d` (74,752 B) | same as 2.0 | `883602c7d6405fda468cd0eb46313c36b13f9d8bdd5d555e86ca1e479ebf91bc` (75,264 B) |
| cards.dat | `f573b37260e33f26a6c13b33f6aa9045efc6e2d9ebe02d560b3d8596fb125908` (330,587 B) | `d7126faf7f17ef84b6ea2e9779bc8b79449c8190c2a4710a5af5c147b95c41a1` (339,984 B) | `19934360d2de798d91f0bb3b3fd5c37dffcd6c232f770c2b971b3acdee6f5e14` (340,009 B) |
| readme (Program) | `319b41e9edf6a826ebeb75f4b979960df5a13fcfba9734de5a1cbc621425f6a4` (35,749 B) | `44e6c8e72a7521759d2a1c7274c6cd4a327a75b8d69db3fdc23f764d26f10b32` (37,224 B) | `8b4aae9145c1fddd737fb0d5704987fc7846ae157be4ebfe365d94aa458b4c8b` (71,983 B) |
| DECK.EXE | `c7ec116aecdcde9ab976cc97cba81482fc4219278f8042edf667456ede3dd8ef` (16,424 B) | same as 2.0 | -- |
| STATWIN.DLL | `c1ca59496afa786f22fcd97b94052b937910a613f9321399b4ef4dd5dec76940` (55,808 B) | same as 2.0 | -- |
| MAGSND.DLL | `213b7dc2e1d0eed131d38485cba8004c1d7760f8ff0a94486b86bba5f3aeba9e` (25,088 B) | same as 2.0 | -- |
| MAGVID.DLL | `b686bd43bb7f9ba040fc7416d8d74e59e27c3b5b1bbccd76bfc16c5505bcf90a` (45,056 B) | same as 2.0 | -- |
| FaceMaker.exe | `b4f3d19614dcd825da846d097baa3cd9badc0c9852492bc27a8ba62c1741a493` (76,288 B) | same as 2.0 | -- |
| MSVCRT.DLL | `3a4cb4631f9ecd6f3f6013bc0459fca2e305a0ad00dbf34cb46e6f52d96d9d62` (266,240 B) | same as 2.0 | -- |
| FaceData.txt | `eb3c55f48861a8fef6ca556e2b199e39e41fed6269fb94a3c8690e771cde04fa` (378 B) | `3b362d357efc0aba6d29e88e4b750078aa11cf5ee838c34c989322266dc4600f` (208 B) | -- |
| Manalink.exe | -- | -- | `7dbc75c975c3819e2367f6b09d27d56f2738d874f7f5c8d128aeb59261bb531c` (304,640 B) |
| ManalinkInterface.dll | -- | -- | `117a42fe57fbf426f9ed204af0ca661bb5cefc16a013b10f9108788a585c5774` (46,080 B) |
| gcconn.dll | -- | -- | `da1ba49826424c6139b7830754a2a59905cbcd9fd3fc116155d7b53f1608ee6f` (188,416 B) |


## The research tools

All in `tools/research/`, each documented at the top, none holding game data (they print counts and addresses); they need `pefile` and `capstone` and use `tools/lift`.

| script | what |
|---|---|
| `iscab.py` | (**now `tools/install/iscab.py`, the installer uses it; this command runs it**) lists and extracts an InstallShield 5 cabinet, from a file or from a disc image; both layouts of compressed data (the 2.0 disc's chunks, ManaLink 3.0's single stream); says where a cut-short cabinet is cut |
| `sotapatch.py` | (**now `tools/install/sotapatch.py`**) lists, **verifies** and extracts the files of a WinZip self-extractor (the 2.15 patch): CRC-32 and SHA-256 of every entry, `TRUNCATED` / `CORRUPT` for an entry that is cut short or damaged, the archive's end record checked, exit status 1 and nothing written for an archive that is not whole (`--partial`, `--check`); extracts over a game folder keeping the names there |
| `sotaoverlay.py` | (**now `tools/install/overlay.py`**, which also has `place`, the installer's one-file version) copies one extracted install over another as Windows does (names compared ignoring case; `--only Program`); counts replaced, identical and added |
| `sotapeinfo.py` | build identity of programs and libraries: link time, versions, sections, imports, the debug directory and its PDB path, the version resource, the source paths in the strings; `--table` for hashes |
| `sotacmptable.py` | the rows of the two comparison tables above for any pairs of builds, as Markdown |
| `sotamaster.py` | finds the master card table in a program and counts its records (the lifter now does this itself: `tools/lift/mastertable.py`) |
| `sotacards.py` | the structure of `CARDS.DAT` and the differences between builds, as counts |
| `sotastride.py` | which structure sizes a program multiplies by (the duel slot and the slots a player), from the compiler's multiplication sequences |
| `sotastrings.py` | strings one build has that another lacks, only the technical kinds (command-line switches, registry paths, window classes, file names, source paths) |
| `test_research.py` | tests of the `cards.dat` reader and of the three old commands, on files made up in the test (no game file): `python3 -m pytest tools/research`; the readers' own tests are `tools/install/test_sota.py` |
| `sotatree.py` | compares two installed folders (counts by folder and extension; `--list-new` lists names) |
| `sotacmp.py` | matches the functions of two builds of a program and reports the counts; `--json`, `--map` |
| `sotahooks.py` | finds the addresses `src/port` is keyed to in another build, with the old and new call sites of the hooked functions |
| `sotalayout.py` | the same for `src/native/layout.c` |
| `sotaimports.py` | imports of a build against the port's tables and the lifter's signatures (run it with `--libs` naming the game's own libraries; `--sigs` checks each signature against the call sites' pushes and `add esp`) |
| `sotalzw.py` | the picture decompressor's state in another build |
| `liftsota.py` | runs the lifter on another build, with its constants replaced (`liftsota.py dll ...` for the libraries). **Superseded** by the lifter's own 2.15 support (Milestone 1): `tools/install/install_sota.py` does the lifting for a 2.15 folder |
| `sota-runtime-experiment.patch` | the scratch changes to `src/port` of the first version of the experiment. **Obsolete since Milestone 1**: its content is in `src/port` as real, tested code (profile rows, the `msvcrt.dll` alias, the Win32 calls, the process model); kept only as a record |

Reproduce (the paths are the ones this note uses; `sources/` is ignored by the repository):

```bash
# the 2.15 install, from the discs and the patch: one command (Milestone 3); it checks every file of the result by size and SHA-256
./pentamoor-install "sources/Magic_The_Gathering_ISO/MTG v1.0.iso" --sota "sources/Magic_The_Gathering_ISO/MTG v2.00.iso" --patch sources/Magic_The_Gathering_ISO/SOTAV215.EXE
# by hand, with the research commands (a cut-short patch is refused: exit status 1, nothing written)
python3 tools/research/sotaoverlay.py sources/installed sources/installed_sota sources/installed_sota_215 --only Program     # the first game's folder with the 2.0 install over it
python3 tools/research/sotapatch.py sources/Magic_The_Gathering_ISO/SOTAV215.EXE sources/installed_sota_215/Program
# ManaLink 3.0: the cabinet, and the install it makes over 2.15
python3 tools/research/iscab.py sources/Magic_The_Gathering_ISO/ml_sota_us/data1.cab sources/installed_manalink
python3 tools/research/sotaoverlay.py sources/installed_sota_215 sources/installed_manalink sources/installed_manalink_over215 --only Program
# comparisons
python3 tools/research/sotacmptable.py "magic.exe 2.15 -> ManaLink 3.0=sources/installed_sota_215/Program/magic.exe:sources/installed_manalink/Program/magic.exe"
python3 tools/research/sotacmp.py sources/installed/Magic/Program/MAGIC.EXE sources/installed_sota_215/Program/shandalar.exe --json /tmp/m.json
python3 tools/research/sotahooks.py sources/installed/Magic/Program/MAGIC.EXE sources/installed_sota_215/Program/shandalar.exe
python3 tools/research/sotapeinfo.py sources/installed_manalink/Program/magic.exe
python3 tools/research/sotacards.py 2.0=sources/installed_sota/Program/CARDS.DAT 2.15=sources/installed_sota_215/Program/CARDS.DAT ML=sources/installed_manalink/Program/cards.dat
python3 tools/research/sotamaster.py sources/installed_manalink/Program/magic.exe
python3 tools/research/sotastride.py sources/installed_manalink/Program/magic.exe --want 288,300,23328,30300,45300
# lifting
python3 tools/research/liftsota.py --name sota215_shandalar --exe sources/installed_sota_215/Program/shandalar.exe --master 0x568bcc --stride 0x48 --code-hi 0x562000 \
    --libs <the four libraries, comma-separated> --out sources/generated_sota/v215_shandalar
```

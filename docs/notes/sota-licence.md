# The licence value of Spells of the Ancients: what the installer did, what each bit changes, what the CD check tests

*(Research note, 2026-10-17; the section [What the installer does now](#what-the-installer-does-now) was added 2026-10-18 when option 2 below was built at the owner's decision, and revised 2026-10-22 when the disc-check flag became part of the default install (below). The research part built nothing, and no code in this repository writes, derives, generates or encodes a `SerialNumber`, and none is meant to. The scheme is described in
words only, and no value of a serial is written down. Found by disassembly (capstone) of the original programs, by reading the installer's compiled script, and by one run of the real installer in a
Windows 98 virtual machine started from a throwaway overlay of the maintainer's disk image; the tools for that were scratch scripts outside the repository. Not re-checked by a second person.
Addresses are those of the 2.15 files unless a file is named. "Certain" below means seen happening or read in the code; "inferred" means concluded from the code and not seen.)*

Context: [sota-comparison.md](sota-comparison.md), section "The licence value", found that `shandalar.exe` 2.15 reads a machine-bound registry value `SerialNumber`, that the function that writes it is never called
by the game, and asked what the original installer did with it, what the bits are for, and what the CD check wants. This note answers those. The owner's position (2026-10-17) is in the same section: the game is not
sold anywhere, the aim is to preserve it properly and as ethically as possible, and the agreed line is that the runtime and the release archives hold no game code, data or licence value, that a 2.15 install needs
the user's own discs, and that nothing is shipped that makes a copy playable for someone who does not own it.

## What was established

1. **The original installer writes the value, and not by anything in `shandalar.exe`.** Its compiled script (`Setup/setup.ins` on the Spells of the Ancients 2.0 disc) loads a DLL that is disguised as a sound file,
   `Program\DuelSounds\Manaball.wav` (23,040 bytes, SHA-256 `03d06fc50a0bccb78356071dc8aa1401ba6dc059a113e523c8bb25ed30055264`; a PE DLL whose internal name is `SencLib.dll`), and calls its two exports,
   `ReadProgramFlags` and `WriteProgramFlags`. The installer's message texts are named `SENC_SUCCESS`, `SENC_ERROR`, `SENC_TAMPERED` and `SENC_DLLLOADERROR`, under the title "Serial Number". (Certain.)
2. **The DLL has the same three functions as the programs** (a machine-id function that runs when the DLL loads, the reader and the writer), so the programs and the installer are one design: the installer's copy
   of the writer is the "missing caller" of the writer inside `shandalar.exe`. The name `Manaball.wav` is also what the CD check looks for on the disc (below). (Certain.)
3. **What it wrote in the research run**, on a machine that had the first game (1.0) installed and no `SerialNumber`: a 12-byte `REG_BINARY` `SerialNumber` and a DWORD `LastInstallResult` = 1, both under
   `HKLM\SOFTWARE\MicroProse\Magic: The Gathering`, after the files were copied and before the DirectX question, with the message "Your serial number has been successfully updated to indicate that you now own
   Magic: The Gathering "Spells of the Ancients"". Unscrambled in a scratch script (the checksum and the copy inside the value both agreed, which shows the reading was right), the **flag word has exactly two
   bits set: bit 8 and bit 22**. (Certain for that run. Whether the installer adds to a word that is already there is inferred: see below.)
4. **The CD checks come first.** After the Welcome page the installer verifies the first game's disc (`CheckOriginalCD`) and then the expansion's (`CheckSotaCD`), both in `CdTools.dll`; the copying
   of the game's files starts only after both have passed, and the licence value is written at the very end of the copying. (Certain: seen in that order. The installer does change the Autoplay setting of
   Windows around the checks and restores it, and keeps its own helper files in `C:\MPMTG.TMP`; those are not the game's.)
5. **Each bit** of the flag word, and what it changes, is in the table below. With the value the original installer wrote, the cards of "set 1" are available, the cards of "set 2" are not, the game's CD check is
   **not** skipped, and a hidden developer toggle stays off. (Certain from the code; short runs of the port with and without the queries granted, below, only confirm that the checker is asked and what follows.)
6. **The CD check tests very little**: a drive that Windows calls a CD-ROM (or one that gives no free-space figures or reports none free), a volume label that starts with `MTG`, the presence or absence of one
   file, and the exact size of another. No hash, no read of the disc's content. (Certain.)
7. **The single-player adventure never reaches the CD check in `shandalar.exe`.** The function that makes it (`0x417deb`) is a duel launcher that a new game's first duel does not enter (logged in a scratch
   run); `magic.exe` has the same function (`0x50111b`). Where else it is reached is not established. (Certain for the run; the rest inferred.)

## The scheme, in words

The programs and the installer's DLL agree on this, and the description stops where a reader could rebuild it.

- **The machine id** is 12 bytes made from two Windows values, `FirstInstallDateTime` (4 bytes, a number) and `ProductId` (a string: the last eight characters are used), both under
  `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion` (the key and value names are stored XOR 0x41 in the programs, plain text of no secrecy). The programs end at start-up without a message when Windows does not give them.
- **The value** is 12 bytes: three 32-bit words. Two of them carry the flag word, once as it is and once with its bits in reverse order, each mixed with words taken from the machine id (and a rotated copy of
  the install time); the third is a checksum (the sum of the low four bits of each of the eight bytes of the first two) mixed with the install time. A read undoes the mixing and accepts the value only when
  the checksum matches and the two copies of the flag word agree. The reader answers 0 (good, and the flag word), 1 (the key or the value is missing or unreadable) or 2 (the value fails a check:
  "corrupt", which the installer's message calls "tampered"); the game's checker treats 1 and 2 alike, as "no".
- Because the id comes from the machine, a value written on one machine reads as "tampered" on another. The flag word itself is the same for every owner of a product: it comes from constants in the
  installer's script.
- The reader does **not** cache: every question to the checker reads the registry again.

## What the original installer did (the order, as seen)

| Step | What happens | Evidence |
|---|---|---|
| 1 | `SETUP.EXE` (InstallShield 5) starts the compiled script `setup.ins` (67,768 bytes; also `_INST32I.EX_`, `_SETUP.DLL`; the helper DLLs are in `_sys1.cab`). | ran |
| 2 | Welcome page. | ran |
| 3 | "Product Verification": "Please insert your original Magic: The Gathering CD". `CheckOriginalCD` in `CdTools.dll` (copied to `C:\MPMTG.TMP` and loaded from there). The first game's disc must be in the drive. | ran: the page waited until the 1.0 disc was in; the 2.0 disc was swapped out by the monitor's `change` command |
| 4 | "Please insert your Magic: The Gathering "Spells of the Ancients" CD". `CheckSotaCD`. Then "Your original Magic: The Gathering CD-ROM has been successfully identified." | ran |
| 5 | Name and e-mail (the name is put into decks), setup type, Start menu folder. | ran |
| 6 | Copies `data1.cab` to `C:\Magic\Program` (about ten minutes in the emulated machine), which includes `DuelSounds\Manaball.wav`; backs up the old `Decks` and `Playdeck` folders (strings of the script, not looked for on the disk). | ran (the copy) |
| 7 | Loads the copied `Manaball.wav` as a DLL, calls `ReadProgramFlags`, then `WriteProgramFlags` with a flag word made from constants of the script; shows `SENC_SUCCESS` ("successfully updated") or `SENC_ERROR`; a read that says "tampered" has its own message (`SENC_TAMPERED`); a load failure `SENC_DLLLOADERROR`. Writes `LastInstallResult`. | ran for the success path; the other messages by the strings and the order of the calls in the script |
| 8 | Asks whether to install DirectX 5 (answered no in the run), "Setup Complete". | ran |

- **Inferred**: the order Read then Write (in the script the DLL's read is called once, and its write in two places; the two ways out of the block have different messages), and that the written word is
  the bits of this product added to what was already there. The script's block holds the constants of bit 22 and bit 8, combined with the value by one operation, and the constant of bit 11 (set 2) combined
  by a different one; on a clean machine the result has bit 11 **clear**, so the script clears it or tests it (not decoded: the compiled script's operations are not documented anywhere that was to hand).
  Not seen: a second run over an existing value.
- `LastInstallResult` is written under the same key and **no program reads it** (searched in every 1.0 and 2.x program and in the ManaLink add-on).
- **Who else writes or reads the value.** The 1.0 install writes nothing like it (1.0's programs do not carry the check). The ManaLink 3.0 installer has no call of the DLL and no mention of the value; the
  2.15 patch does not touch `Manaball.wav` (the same file, same hash, in the 2.0, 2.15 and ManaLink-over-2.15 installs). **Read** by: `shandalar.exe`, `magic.exe` and `deckdll.dll` of 2.0, 2.15 and
  the ManaLink-over-2.15 install (each carries the string `SerialNumber` and the three functions); not by `FaceMaker.exe`, `Manalink.exe`, `cardartlib.dll`, `drawcardlib.dll`, `STATWIN.DLL`,
  `CdTools.dll` or the 1.0 programs.
- **Nothing the research found sets bit 11, bit 17 or bit 28** (on a clean machine the installer's result has none of them; the ManaLink installer and the patch write nothing). They are presumably for
  editions this collection does not hold (an expansion with set 2, a build that needs no disc, an internal build): inferred.

## What each bit changes

The checker (`0x4d6b4b` in `shandalar.exe`, `0x497e7c` in `magic.exe`, `0x10026e83` in `deckdll.dll`) takes a **query mask** from its caller and answers yes or no. The queries are 2, 4, 8 and 0x10, and 1
(which answers yes at once, before reading anything; the part of the code that would test bit 22 is dead: nothing passes 1 as the six direct callers show). A query is answered by one bit of the flag word:

| Query | Flag-word bit | What a "yes" gives | Asked where (shandalar.exe 2.15) |
|---|---|---|---|
| 1 | 22 (never reached) | always yes | no caller passes it |
| 2 | **8** | the cards of **set 1** are available | `0x4d6a07` (set 1 of "is this card in the pool", called with set 0 and 1 only), `0x53d883` (the card pickers: the answer is "set 0, or, with this bit, set 1") |
| 4 | **11** | the cards of **set 2** are available | `0x4d6a07` when called with set 2: **no caller in `shandalar.exe` does**, so this bit changes nothing there |
| 8 | **17** | **skips the CD check** | `0x417deb`, the first thing the duel launcher does |
| 0x10 | **28** | a hidden **developer toggle** may be switched on | read once, while the options are loaded (`0x53e5f2`, stored in `0x84bf98`); the menu command at `0x447e8a` flips a flag (`0x741c8c`) and forces it off when this bit is clear; the commands after it (`0x447ecc` and following) act only while it is on |

Further, in `deckdll.dll` (the deck editor, loaded in the same process) both card queries are used for **three** sets: a card is listed when it is in set 0, or in set 1 with bit 8, or in set 2 with bit 11
(`0x10010a30`), and the controls for sets 1 and 2 (elements 7 and 8; 9 and 10, in `0x1001d321`) are moved off the window when their bit is clear. In `magic.exe` the same tests are made by `0x497d38`
(cards: queries 2 and 4), `0x4c1202` (the developer toggle: query 0x10, stored in `0x8114f8`), `0x50111b` (the CD check: query 8) and by a table accessor (`0x52d48b`: a mask kept in each entry of a
nine-entry table of 72-byte records that is filled at run time; **what those nine entries are was not established**; the same accessor exists in `shandalar.exe` at `0x46a421` and has **no caller there**).

**The three pools.** `shandalar.exe` holds three bitmaps (128 bytes each, from `0x579110`: one bit per card index, 1,024 indices) that say which cards belong to set 0, set 1 and set 2: **409, 145 and 83**
cards, no card in two of them, 637 in all. 2.15's `CARDS.DAT` names 929 cards, so **292 named cards are in none of the pools and are never offered**, whatever the licence. As examples only: set 1
holds two of the dual lands and a clone, set 2 a banshee, an exorcist and a water wurm. Almost every one of those cards has the same id and name in 1.0's `CARDS.DAT` (141 of 145 and 82 of 83): the
gated cards are mostly cards the first game also had, not cards that Spells of the Ancients adds. (What the sets are called in the game was not found.)

**With all bits clear** (what the port does today, and what a machine with no value does): the random card pickers (nine call sites, all in loops that try again when the answer is no) only ever
choose from the **409** cards of set 0; the 145 cards of set 1 are never offered and the 83 of set 2 neither; the deck editor lists only set 0 and has no controls for sets 1 and 2; the CD check is **active**
(on the paths that reach it); the developer toggle cannot be switched on.

**With the value the original installer wrote** (bits 8 and 22): set 1 is in the pickers and in the deck editor, set 2 is not anywhere, the CD check is still active, the toggle is off. So even a fully
installed original needed the expansion's disc for whatever runs `0x417deb`.

**With every bit set**: set 2 appears in the deck editor (nowhere else), the CD check is skipped, the developer toggle works.

### What was played

A scratch module (a copy of the generated C of `shandalar.exe` in which the checker answers from an environment variable, and which logs each call of the checker and the entry of five functions; built in a
scratch folder from the release's generated C, **not committed**; no `SerialNumber` is read, written or made up by it) was run through the soak driver (`tools/soak/sota_soak.py`: a new game, the first
encounter's duel, about four minutes, two games) with nothing granted and with all four queries granted.

- Nothing granted: five questions of query 2, all from the card picker (`0x53d8ae`), each answered "no". All granted: one query 2 from the picker, answered yes, and one from the set-1 test inside
  `0x4d6a07` (`0x4d6a28`), answered yes. **Queries 4, 8 and 0x10 were never asked** in either run. The options function `0x53e5f2` ran (from `0x419f2c` and `0x401616`) but did not reach its query-0x10 test (its
  first registry call, to `HKEY_CURRENT_USER`, is not answered by the port, so it takes its defaults).
- Both runs played a duel of several turns (one conceded) and went on; neither entered the duel launcher `0x417deb`, its caller `0x4193d5` or `0x4746e7`.
- With the shipped module and nothing granted, a count of imports showed the checker's registry read (`RegOpenKeyA` of the MicroProse key) made six times in one game and **failing to open the key**
  every time (the port does not have it), which the reader reports as "not found" (answer 1).
- So on the single-player path the only effect of the missing value that was seen is the card pool (the picker's query). The CD message was **not seen**, because the code that shows it was not entered.
  **What the message says, and what a user sees on the paths that do enter `0x417deb`, was not observed** (the launcher keeps a table of player slots and takes a lock around it, which looks like
  the multi-player or tournament duel; unconfirmed).
- The effect on the pool (which cards appear) was **not measured** in play: it follows from the code above, not from a count of cards seen.

## What the CD check tests

`CdTools.dll` (the same 74,752-byte file in 2.0 and 2.15; ManaLink 3.0 adds a sixth export, `CheckDoPCD`, not read) has five exports. `IsCDDrive(path)`, `CheckOriginalCD(0, &tries, drive)` and
`CheckSotaCD(0, &tries, drive)` are the checks. The game calls `IsCDDrive` for each drive letter from D to Y, and for the first that answers yes calls `CheckSotaCD`; the installer calls the other.

- **A "CD drive"** is `GetDriveTypeA` = CD-ROM, **or** a drive whose `GetDiskFreeSpaceA` fails, **or** one that reports zero (sectors, bytes or free clusters multiplied): a read-only full volume counts, as a real disc
  does. (Certain: read in the code. Note that this is looser than "a CD".)
- **The label**: `GetVolumeInformationA`, and the first three characters must be `MTG` (the 1.0 disc's label is `MTG v1.0`, the expansion's `MTG v2  0`). The check retries once a second, as often as the
  caller's count says (1 at first in the game; 5 after the user answers OK to the message).
- **Files on the drive**, by `CreateFileA` and `GetFileSize`:

  | | `DuelSounds\Manaball.wav` | `Sound\Locmus15.wav` |
  |---|---|---|
  | `CheckOriginalCD` (the first game's disc) | must **not** exist (if it opens, the answer is no) | must exist and be exactly 3,176,548 bytes |
  | `CheckSotaCD` (the expansion's disc) | must exist (any content) | must exist and be exactly 3,176,548 bytes |

  Both discs hold `LOCMUS15.WAV` of that size; only the expansion's has `DuelSounds\Manaball.wav` (23,040 bytes: the installer's DLL). (Checked on the two disc images.)
- **Not tested**: any hash or content; the disc's other files; copy protection of the physical medium (no sector or subchannel reads: only `CreateFileA`, `GetFileSize`, `GetVolumeInformationA`,
  `GetDriveTypeA` and `GetDiskFreeSpaceA` are imported besides the registry calls that switch Autoplay off and on).
- In play, a failed check shows a message box (the text is the game's string "CHECKCD"; its buttons are OK and Cancel, "OK" tries again five times, "Cancel" gives up and the duel is not started). With **no CD drive
  at all** the function returns "failed" **without a message** (the code at `0x417e93`).

**Can it be met by an owner who has the images but not the discs?** By what it tests: yes, in principle, faithfully: an image of the expansion's disc mounted by the operating system as a virtual CD
drive has the label and the two files and answers CD-ROM, so on Windows the original check could not tell it from the disc. In the port the drive calls are the port's own (`GetDriveTypeA` answers "fixed disk"
for every drive, `GetVolumeInformationA` answers for a fixed disk with no label), so a faithful answer would be a **virtual drive**: report one CD-ROM drive whose files are the owner's expansion image (read through the installer's ISO
reader), with its label. That would let the check do exactly what it did, with the same weakness (anyone who has an image, or just a folder with the right label and the two files, passes). It is a design
decision for the owner; nothing of it is implemented, and `0x417deb` is not on the paths that were played.

## What was not established

- What the CD message says, and what is on screen on the paths that enter the launcher (`0x417deb`, `0x50111b`): not reached in play.
- Whether the installer adds its bits to an existing value (inferred only), and what it does on a "tampered" read.
- What sets 1 and 2 are called in the game, which shops, rewards or opponents' decks use the pickers, and what the nine-entry table with a mask in `magic.exe` holds.
- What the developer toggle's commands do (only that they act while the toggle is on).
- Whether any real machine had a value with bits 11, 17 or 28; nothing in the collection writes them.
- ManaLink 3.0's `CheckDoPCD` and whether its programs ask different queries.
- The text of `SENC_*` and `CHECKCD` (they are in the game's and installer's string resources; not read).

## What the installer does now

Built 2026-10-18, at the owner's decision (option 2 below); changed 2026-10-22, at the owner's decision, so that the default install also sets the game's "skip the disc check" flag (the text below is the state after that change; the 2026-10-18 state was `--no-cd`, an opt-in). Read with [The agreed line](#options-with-an-honest-assessment).

**The step.** `pentamoor-install "MTG v1.0.iso" --sota "MTG v2.00.iso" --patch SOTAV215.EXE` ends with a licence step. It runs only after the discs and the patch have been checked, the 2.15 folder has been made and the modules are built.
It prints one line, `licence: writing the licence value the original Spells of the Ancients installer writes for an owner of the discs, and, because the discs were just verified, the game's own "skip the disc check" flag, so this install does not ask for a disc later (--keep-cd-check keeps the check)`, and never prints the value. It takes the original installer's own library, `DuelSounds/Manaball.wav`
(checked against its SHA-256 and size, three times: when the folder is made, before it is lifted and before it is run; a wrong file is refused and nothing is written), lifts it locally like the game's other libraries
(module `game_senclib`, never committed and never in a release archive) and runs its `WriteProgramFlags` export once, through a generic mode of the runtime (`pentamoor-run -m MODULE --call-export NAME=ADDRESS ...`).
The encoding stays inside that file. The repository holds no implementation, table or value of it, and no tool that produces one.

**What the installer supplies.** The flag word. By default it has three bits: **8 and 22**, the ones the original installer's script passed (as established above), and **17**, the one the game itself defines as "skip the disc check" (query mask 8), which the original installer did **not** set. They are named constants in `tools/install/licence.py` (`ORIGINAL_BITS`, `FLAG_NO_CD_CHECK`, `DEFAULT_BITS`), **not read from the disc** (the script is compiled and was not decoded for this). They are the only thing the installer adds to what the library does. Bits 11 and 28 are never set. With bits 8 and 22 the game offers the 145 cards of set 1 (computed from the game's own pool function: 409, 145 and 0 cards for sets 0, 1 and 2; not seen in a card picker on screen); without the step only the 409 base cards are offered.

**Why bit 17 is in the default (the owner's decision, 2026-10-22).** The installer verifies the user's 1.0 disc, the 2.0 disc and the 2.15 patch before it writes anything. Once the user has proved they have the discs at install time, the install should work without asking for a disc at play time; the shell's Start match, Credits and Tutorial ask for one (see the CD check in [sota-comparison.md](sota-comparison.md#the-cd-check)), and before this change they ended without a message on the default install. The flag is set by the same original-installer writer, in the same step, and only after the discs are verified.

**Options.**
- `--no-licence-value` skips the whole step (no value is written, and the library is not even lifted). The 2.15 install then offers the base pool only, as before, and there is no "skip the disc check" either.
- `--keep-cd-check` (off by default) leaves bit 17 out: the word has only the bits the original installer set (8 and 22), so the install still asks for a disc on the paths that check, as the original did. The installer says so: `licence: writing the licence value the original Spells of the Ancients installer writes for an owner of the discs, without the "skip the disc check" flag (--keep-cd-check): this install asks for a disc where the original did`. It is an error together with `--no-licence-value` (there is then no value to leave the flag out of), and without `--sota`. (`--no-cd`, the opt-in of 2026-10-18 that added bit 17, is gone; giving it ends with `--no-cd is gone: the 2.15 install skips the disc check by default; use --keep-cd-check to keep it`.)

**What it means.** The default install no longer asks for a disc, **because the installer verified both discs when it was made**. That verification is software, and an install folder can be copied like any file, as the original's installed copy could be. The repository and the release archives still hold no scheme and no values, no tool that makes one, and nothing that works without the user's own discs: the licence value is written on the user's machine from the user's own cabinet. The CD-check function itself (`0x417deb`, its message) and what it shows have **still not been observed**; see "Tested" for what was seen.

**Machine binding.** Each install gets its own random pair for the two Windows values (an install time in 1998 to 2000 and a product id), made once at install time and never replaced, kept in the registry file below. The runtime answers the game's two reads from that file, so the library
sees the same pair when it writes. An install without the file falls back to the old fixed pair (and then has no `SerialNumber`). 1.0 opens no file.

**The registry file.** `<overlay>/registry.dat` (`$PORT_OVERLAY`, or `port_overlay_sota` for `./pentamoor sota`): a plain text file, read and written by `src/port/regstore.c` and, for the installer, `tools/install/regstore.py` (same format). It keeps only values under
`HKLM\SOFTWARE\MicroProse` and the two Windows values; everything else is "not found" and a write elsewhere goes nowhere, as before. Deleting the file gives the behaviour without the step.

**Release archives.** `tools/release/check_archive.py` refuses `Manaball.wav`, `SencLib.dll`, `game_senclib.*` and any file with `senclib` in its name, and `registry.dat`.

**What this does not do.** It does not touch the CD check beyond the flag above (the game's own flag, set in the licence value; nothing in the runtime answers for a disc, and it still reports a fixed disk), it does not read or write anything outside the install folder and its overlay, and the installer's verification of the discs is software, so a determined person could skip it by running the runtime's `--call-export` mode by hand on their own files: that was equally true of the original installer.

**Tested.** On 2026-10-18 (before the disc-check flag was made the default): three full installs from the real discs (default, `--no-cd`, `--no-licence-value`); the checker's answers to every query in each; the pool sizes above; five-minute soaks of the first two (no crash, hang or stuck screen). On 2026-10-22, with the real discs and the real writer, scratch folders, SDL dummy drivers: the **default** install (the installer printed the one line above and never the value) and an install with **`--keep-cd-check`**. The game's own checker (`0x4d6b4b` of `shandalar.exe`, run through the control pipe's `call` with `PORT_TRACE_FN`) answered, in the default install, query 1 yes, 2 yes, 4 no, **8 yes**, 0x10 no, and in the `--keep-cd-check` install 1 yes, 2 yes, 4 no, **8 no**, 0x10 no (queries 4 and 0x10, bits 11 and 28, no in both). The Magic Shell's **Start match** on the default install played duels (`tools/soak/sota_shell_soak.py --mode duels`, 4.0 minutes: three single duels, 15 turns, no crash or hang; and through `./pentamoor sota shell` itself: the match-up dialog, then the board with the coin toss); on the `--keep-cd-check` install it showed the match-up dialog and then a black window with no board and no message box (20 seconds by hand, 120 seconds in the soak, the process still running). The installer flow, the failure cases, the registry file and the archive refusal are tested with made-up discs and a fake writer (no game files in CI). **Not tested:** a re-run of the installer over an existing real install (only with the fake writer), Credits and Tutorial after the change, and any play beyond these runs. **Not observed:** the CD-check function's own message (the "CHECKCD" text) was not seen on either install; only the answer of the query that skips it, and what the game does or does not do after Start match.

## Options, with an honest assessment

The agreed line: no game code, data or licence value in the runtime or the release; a 2.15 install needs the user's own discs, verified by the installer before anything is written; nothing shipped that makes
a copy playable for someone who does not own it.

1. **Do nothing** (what is there). The port reads no value, so the game plays with the 409-card base pool; the card pickers never offer the 145 cards of set 1 (two dual lands and a clone among them) and
   the deck editor does not list them. What a player misses is a third of the pool of an original install; the game starts and plays through a duel to the map. There is no legal or ethical question. Cost: zero.
   **Honest verdict: the safe default, and a visible reduction in card variety; not a faithful reproduction of an installed original.**
2. **The installer does what the original did, using the original's own DLL. (Built 2026-10-18, see above; the assessment is as written before.)** After both discs are verified, the installer takes `Manaball.wav` out of the owner's own expansion cabinet (it is in `data1.cab`
   already read by the installer), and the runtime runs its `WriteProgramFlags` (the DLL is a small PE file the lifter already knows how to handle, like `CdTools.dll`) with the one flag word the original script
   uses, into a registry that the port keeps on disk (today a write goes nowhere). The encoding stays in the owner's own DLL; the repository holds no scheme code and no value; the only thing it would carry is
   which bits to ask for, which the script's constants give. This is the closest to "what the original installer did, on that machine, after the disc checks". Costs and risks: a persistent registry store in
   the runtime; the machine id the port gives is a pair of **fixed made-up values**, so the written value would be **identical on every installation** (the machine binding disappears: the value, once
   written, would read well anywhere the same fake id is used, which is the same as a portable serial for anyone who copies the user's registry file); making the id per-install (a random pair kept in the overlay) restores the
   binding at the price of the value not surviving a re-install without the installer running again. The installer's verification is software, so a determined person could skip it: that is true of every
   option that unlocks anything, and the DLL-from-the-owner's-disc design at least does not put the means in the repository. **Honest verdict: the most faithful of the options that unlock anything and the
   one that fits the line best, but it is still a licence that the program grants itself; it needs the owner's explicit decision, and a short legal read-through of "the installer runs the vendor's own
   code on the owner's machine" would be sensible first.**
3. **The installer encodes the value itself** (the scheme re-implemented in the repository's installer). Technically easy (a few lines), and exactly what the line forbids: it is a generator in the repository, behind
   a check that is software; anyone could call it without a disc. **Not recommended.**
4. **Ship a value, or patch the check so every query answers yes.** A distributable constant or a cracked program. **Rejected by the line.**
5. **A virtual CD drive** (for the CD check only; independent of 1 to 4). The runtime would answer the drive calls from the owner's expansion image, so the paths that run `0x417deb` can pass the check
   they were written with. It is not needed for the single-player paths played so far, and it raises one question: keeping the image's location in the user's settings means the owner needs the image at play
   time, not only at install time (which is what the original needed too). **Honest verdict: worth doing only if a path that checks is found to matter; unneeded today.**

The research suggested a split: option 1 now, and option 2 as the explicit, owner-approved step if the missing set-1 cards are found to matter, never 3 or 4. The owner chose option 2 on 2026-10-18 and asked for the opt-in `--no-cd`; option 5 (a virtual CD drive) is not built.

**Decision of 2026-10-22 (owner).** For a 2.15 install, once the user has proved they have the discs at install time, the install works without asking for a disc at play time: the default install also sets the game's own "skip the disc check" flag, through the same writer in the same step and only after the discs are verified. `--no-cd` is replaced by `--keep-cd-check` (the old behaviour). The assessment above of option 2 stands, with this addition: the install the installer makes is now one that does not need a disc at play time, so it is exactly as portable as an install folder is (it can be copied), as the original's installed copy was; the line (no scheme, no values and no game data in the repository or the release archives; discs verified before anything is written) is unchanged.

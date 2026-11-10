# A stranger's first hour with 0.1.0-rc2 (macOS, 2026-11-09)

What happens to someone who downloads the public pre-release [v0.1.0-rc2](https://github.com/MadranFoyle/pentamoor/releases/tag/v0.1.0-rc2) and follows only what the README and the archive's `README.txt` say. Everything below was run on one
Apple Silicon Mac (arm64, macOS 27) with the downloaded archive in an empty scratch folder; the installer's Python and compiler were the ones Apple's command line tools bring (`/usr/bin/python3` 3.9.6, `/usr/bin/cc`, `PATH` with nothing else on it,
as a person who has no Homebrew has), and the real discs. The game ran headless (`SDL_VIDEODRIVER=dummy`, its own control pipe and overlay folder) and was looked at through the pipe's screenshots; **nobody watched it on a real display**.
The fixes that came out of it are in the same change as this note (`tools/install`, the launchers, the two READMEs); the tests are `tools/install/test_messages.py`.

The branch's installer was also tried on the same archive with its files laid over it (the interrupted install, the failure messages, the missing compiler, a full 1.0 and 2.15 install again): those rows say "after".

## The way through

| # | Step | Expected | Observed | Verdict |
|---|---|---|---|---|
| 1 | `gh release download` the macOS archive and `SHA256SUMS`; check the sum | the sum matches | it matches; 19 MB unpacked; the runtime is a universal binary (arm64 and x86-64) that links only system frameworks (SDL is inside it), so a Mac with no Homebrew has what it needs; the capstone library of `tools/pydeps` is universal too | ok |
| 2 | Read `README.txt` | what to install and what to type | clear; two statements were stale or wrong (below: the shell, the size of `--clean`) | fixed |
| 3 | `./pentamoor-install "MTG v1.0.iso"` | extract, lift, build, three modules | 128 s on a busy machine (71 s unpacking the disc's archive, 26 s lifting, about 30 s compiling), 411 MB on disk afterwards (268 MB the game, 98 MB generated C, 16 MB objects), the three modules load in the runtime, "built. Play with: ./pentamoor". The README says 2 to 15 minutes and up to 1 GB | ok |
| 4 | `./pentamoor` with nothing installed, at a terminal | offers to install, asks for the file | "the game is not installed yet ... Install it now? [Y/n]", then "ISO file:"; a path typed the way Terminal pastes a dragged file (`MTG\ v1.0.iso`) works; the game starts when the build is done. There are 15 silent seconds after "reading Setup/data.z (72 MB)" before the first "100/967 files" | ok |
| 5 | `./pentamoor "path/to/MTG v1.0.iso"` in a folder named `Pentamoor Täst ñ 日本語 dir` | same | same; the game starts from that folder | ok |
| 6 | The same install command again | nothing to do, quickly | "967 already there", "all objects are up to date", 0.7 s | ok |
| 7 | The same with Homebrew's Python 3.15 first on `PATH` | works | works | ok |
| 8 | Start the game headless, title menu, Start New Game, difficulty, colour, visage, name, map | the screens of the original | all five screens drawn, the map with the party; walking east met an encounter ("Those who enter the domain of the Mighty Red Wizard ..."); "Duel a Sorceress" twice led to the coin toss and the duel's first main phase with seven cards in hand | ok |
| 9 | (8) as seen through the control pipe | the screen as it is | a dialog the game opens on its own thread (the coin toss's "Start the duel") is in the window tree and not in the pipe's screenshot, so a headless run has to look at the tree; not seen on a real display | note |
| 10 | The game idle on the dummy video driver | little work | 100% of a core; with a real display SDL paces the frames, which is not what this run could show | note |
| 11 | `./pentamoor-install "MTG v1.0.iso" --sota "MTG v2.00.iso" --patch SOTAV215.EXE` (the full patch file) | checks, installs, builds 2.15 and writes the licence value | 77 s more, 896 MB in all (312 MB the 2.15 game, 242 MB generated C, 33 MB objects); eight modules load; the licence step says what it does and where the value went | ok |
| 12 | `./pentamoor sota shell`, Duel, Start match | the shell's duel page, the duel | the page, the "<player> vs. Gloria" box, then the coin toss on the board (with the default overlay) | ok |
| 13 | (12) with `PORT_OVERLAY` pointed at another folder | -- | a black window and no message: the licence value, with the flag that skips the disc check, lives in `port_overlay_sota/registry.dat`, which that run did not look in. The same happens to someone who deletes `port_overlay_sota` to start over | fixed in the README (the installer's own message already says that running it again writes the value again) |
| 14 | `./pentamoor sota`, Start New Game, difficulty, colour | FaceMaker, name, map | the colour starts FaceMaker (a second program, its own pipe), its portrait screen is drawn; after it and the name the map, then a dungeon event after a few steps | ok |

## What a stranger gets wrong, and what the program said

"rc2" is the archive as downloaded; "after" is this change. A judgment of "could a non-programmer act on it" is mine.

| # | Mistake | rc2 said | Could a non-programmer act? | After |
|---|---|---|---|---|
| 15 | a text file or an empty file named `.iso` | "is not an ISO 9660 image (a raw .mdf is not: convert it first, see docs)" | partly: "see docs" says nothing | says what an iso is and what has to be converted (`.mdf/.mds`, `.bin/.cue`, `.nrg`, `.dmg`) |
| 16 | the raw `MTG v1.0.mdf` | the same line | no: which docs? how? | "is a raw .mdf disc image, not an .iso", with the command (`mdf2iso "MTG v1.0.mdf" "MTG v1.0.iso"`) and that macOS gets it with `brew install mdf2iso` |
| 17 | the patch `SOTAV215.EXE` or another program given as the disc | the same line | no | "is a Windows program (an .exe), not a disc image", and that the patch goes after `--patch` |
| 18 | an archive (`.zip`, `.gz`, `.7z`, `.rar`) as the disc | the same line | no | "is a compressed archive ... Unpack it and give the .iso file inside" |
| 19 | **a disc image cut short** (an interrupted download), cut after the first 5 MB, 130 MB or 240 MB of the 590 MB | at 5 MB: "does not look like the ... disc (no Setup/data.z) (label 'MTG v1.0' was found)", which is wrong (it is the right disc); at 130 MB and 240 MB: **a Python traceback** (`struct.error` in `datax.py`) | no | "is cut short: the disc image says it is 590,508,032 bytes and the file has 5,000,000 ... Get the disc image again", from the size the image itself records, before anything is read |
| 20 | **another game's disc** (the 2010 Edition's `.iso`, which has a `Setup/data1.cab` like the expansion) | "is the Spells of the Ancients disc (version 2.0), not the original game's" -- **false** | no: it sends the person to the wrong remedy | "does not look like the Magic: The Gathering disc, version 1.0 (it has no Setup/data.z; the disc's name is 'MAGIC'). It may be the disc of another game or another version ..." The real expansion disc is still told as such |
| 21 | the expansion's disc as the first one, or the two swapped | names both and prints the whole command | yes | unchanged |
| 22 | `--sota` without `--patch`, `--patch` without `--sota`, a missing file, the 2010 disc as `--sota`, the 78 MB Duels of the Planeswalkers patch as `--patch` | each says what it found and what it needs | yes | unchanged |
| 23 | the patch cut short (`SotA Patch 2.15/sotav215.exe`, 1,048,331 of 1,207,571 bytes) | names the entry that is cut, the sizes, "Get the patch again" | yes | unchanged |
| 24 | the readme of the patch (`sotav215.txt`) given as the patch | "has no files in it ... it was cut short" -- wrong | no | "--patch wants SOTAV215.EXE" (cut short is said only of a program) |
| 25 | no disc given, no terminal | "no disc image given. Usage: ..." | yes | unchanged |
| 26 | a mistyped path at the launcher (`./pentamoor MTG.iso`) | the name was passed on to the game, which said "not installed" and asked from the beginning | no | "pentamoor: MTG.iso is not a file (check the path: ... drag the .iso file onto it to paste the path)"; `pentamoor.bat` the same (written, not run: no Windows) |
| 27 | a wrong file typed at "ISO file:" | the installer ended; the launcher's whole question had to be answered again | partly | says what is wrong with it and asks again; an empty line cancels |
| 28 | `./pentamoor` with no terminal (a script, a double click on the file) | "the game is not installed (...). ./pentamoor-install" | yes (the installer then says it needs a disc) | unchanged |
| 29 | **no C compiler on `PATH`** (`PATH` with `python3` and nothing else; the macOS stub that asks to install the command line tools was not run) | "no working C compiler was found (gcc, clang or cc). Download the Zig compiler (about 92 MB, ...) into .../tools/local? [Y/n]" and, on no: "no C compiler: install gcc or clang (on Windows: MSYS2 or w64devkit), or let the installer download Zig (it asks; --yes answers for you)". Without a terminal the question was not asked and the message still said "it asks". The download itself was not tried | partly: nothing for a Mac | the Mac's own remedy ("run xcode-select --install ... then run this again"), Linux's package commands, Windows' MSYS2; "there is no terminal to ask on (add --yes)"; `--no-download` says so |
| 30 | **no Python** | "pentamoor: Python 3 was not found (the installer is a Python program). Install it (macOS: xcode-select --install, or python.org ...)" | yes. (On a Mac without the command line tools `python3` is a stub that opens Apple's own install dialog; that was not run) | unchanged |
| 31 | **a download that macOS has marked (quarantine)**, `xattr -w com.apple.quarantine` on the unpacked tree, then `./pentamoor-run` and `./pentamoor-install --check` | **no message at all**: both hung (the runtime before it printed anything, the installer at its first load of the capstone library, `sample` showed `dlopen` waiting), 20 s, 60 s and 100 s with nothing on screen. Whether Gatekeeper put a dialog up could not be seen (headless, no screen was looked at). `README.txt` says to run `xattr -dr com.apple.quarantine .` "if macOS says the program cannot be opened": a person whose terminal just waits is not told | no | the launcher and the installer look for the mark on `pentamoor-run` first and say "macOS has marked these files as downloaded from the internet ... Clear the mark once, in this folder: xattr -dr com.apple.quarantine ." The README advice is **right**: on a fresh unpack with the mark set and then cleared before the first run, the installer ran at once (0.5 s for `--check`); after the hang it did not recover in the same folder within a minute (the dialog or the assessment of the first attempt was still pending), so the advice has to come before the first run, which the new message makes it |
| 32 | **Ctrl-C, or a stopped install** while the archive is unpacked, then `./pentamoor` again | the traceback of a KeyboardInterrupt; and the next run found `MAGIC.EXE`, said "the game is already extracted ... not reading the disc again" and **built from the half that was there** (the run after that, given the disc, found that 406 of the 967 files had never been written) | no | "install: stopped. Run the same command again to carry on"; an install without its completion mark and with fewer than the retail disc's 1,066 files is "only partly there", the disc is asked for again, and the files already written are kept (582 written, 385 already there in the run that was tried) |
| 33 | a folder that cannot be written (a read-only unpack) | after reading the disc's archive for 10 s, a traceback (`PermissionError`) | no | at the start: "cannot write (...): permission denied. Pentamoor installs into the folder it was unpacked in ... Unpack it where you may write, for example in your home folder" |
| 34 | too little disk (not tried: the disk is not filled; the code was read, and the new check is a unit test) | no check: the lifter or the compiler failed with a traceback when the disk filled, after the disc had been read | no | at the start: "there is not enough free disk space: the install needs about 650 MB (1150 MB with Spells of the Ancients 2.15) on the drive that holds ..., and N MB is free"; a full disk later (`ENOSPC`) says so and says to run the same command again |
| 35 | the second install over the first (rc2: `--sota` added later) | the 1.0 files are skipped, the 2.15 ones made, both built | as expected; 74 s | ok |

## Numbers the README gave, and what was measured

| Claim | Measured |
|---|---|
| "a few minutes (2 to 15, depending on the computer)" | 128 s for the first game, 77 s more for 2.15, on a busy Apple Silicon Mac |
| "up to 1 GB while it builds" | 411 MB for the first game; 896 MB with 2.15 (Zig, if it has to be downloaded, is about 100 MB more) |
| "`--clean` deletes about 200 MB" | 114 MB for the first game; 275 MB with 2.15. The README and the release's README now say that |
| `README.txt`: "The expansion's own shell (magic.exe) ... not part of it" | the shell is built and started by `./pentamoor sota shell` (the repository README says so); the release's README now says so too |

## What was not tested

- **Windows** (`pentamoor.bat`, the bundled Python and Zig, SmartScreen), **Linux**, an **Intel Mac** (the x86-64 half of the universal runtime and of `capstone`; Rosetta is not installed here), **macOS 11 to 14** and any Python older than 3.9.
- A **real display** and speakers: window, full screen, scaling, sound, the quarantine dialogs themselves, the Apple dialog that offers the command line tools.
- The **Zig download** (the point was to see the message, not to fetch a compiler), a machine with **no command line tools at all**, a **full disk**.
- Playing: the duels were started and their first phase seen, not played; Shandalar 2.15 was walked a few steps.

## What came out

Fixed (`tools/install/*.py`, `pentamoor`, `pentamoor.bat`, `README.md`, `tools/release/README.release.txt`; tests in `tools/install/test_messages.py`): rows 15 to 20, 24, 26, 27, 29, 31, 32, 33, 34 and 13. Left alone, for the owner:

- Whether the launcher should **refuse** when it finds the quarantine mark (it does now: a person who has approved the files in System Settings still has the mark, and has to run the one command) or only warn and go on. It refuses because the alternative, in the cases seen, is a frozen terminal.
- Whether the macOS archive should be **ad-hoc signed and notarized** (a Developer ID): the runtime is ad-hoc signed already (`codesign -dv`: `Signature=adhoc`); `spctl` rejects it, as it would any file with the mark. This is a cost and a policy, not a code change.
- A `.dmg` or an `.app` that a double click would open instead of a terminal.

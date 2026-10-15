# Pentamoor

[![CI](https://github.com/MadranFoyle/pentamoor/actions/workflows/ci.yml/badge.svg)](https://github.com/MadranFoyle/pentamoor/actions/workflows/ci.yml)

A native port of MicroProse's 1997 *Magic: The Gathering* (Shandalar), in the spirit of DevilutionX:
the game's own code, running on current systems, using data files from a copy of the game you own.
**No game files are in this repository, no code generated from them, and no decompiler output** (see [Legal](#legal)).

There is no emulator. The game's machine code is translated into C and run against a small
reimplementation of the Windows calls it makes, over SDL2. How that works is in
[CONTRIBUTING.md](CONTRIBUTING.md).

## Install and run

You supply the game: a disc image of the retail *Magic: The Gathering* CD (version 1.0), as an `.iso`
(a raw `.mdf/.mds` pair needs `mdf2iso "MTG v1.0.mdf" "MTG v1.0.iso"` first).

### From a release

The [releases](https://github.com/MadranFoyle/pentamoor/releases) have one download per system. They hold the runtime and the installer, and
**no game files and nothing made from them**: your computer builds the game's part from your own disc, once, in a few minutes (2 to 15, depending on the computer).

| System | Download | What it needs |
|---|---|---|
| Windows 10 or 11 (x86-64) | `pentamoor-<version>-windows-x86_64.zip` | nothing: it carries its own Python and C compiler |
| Linux (x86-64) | `pentamoor-<version>-linux-x86_64.tar.gz` | Python 3 and SDL2 (`sudo apt install python3 libsdl2-2.0-0`) |
| macOS 11 or newer (Apple Silicon or Intel) | `pentamoor-<version>-macos-universal.tar.gz` | Python 3 (Apple's command line tools: `xcode-select --install`) |
| Steam Deck (SteamOS 3) | `pentamoor-<version>-steamdeck.tar.gz` | nothing (see [On a Steam Deck](#on-a-steam-deck)) |

Unpack it, then:

- **Windows:** double-click `pentamoor.bat`. The first time it asks for your `.iso` (type or paste the path, or drag the file onto the window), installs, and starts the game; after that it just starts it.
  You can also drop the `.iso` on `pentamoor.bat`.
- **Linux and macOS:** run `./pentamoor` in the unpacked folder. It offers to install the first time and asks for the `.iso` (drag the file onto the terminal to paste its path).
  `./pentamoor-install "path/to/MTG v1.0.iso"` does only the install.

If there is no C compiler on the machine (on Linux and macOS: no gcc, clang or cc), the installer offers to download one (the Zig compiler, about 100 MB, checked against a known checksum); nothing
else is downloaded. The files are not signed, so Windows SmartScreen and macOS Gatekeeper warn on the first start (`README.txt` in the download says what to click).
The unpacked folder gets a `sources/` (your game files and the C made from them) and the three game modules; do not share those. It needs up to 1 GB while it builds (about 500 MB without the downloaded compiler), and
`pentamoor-install --clean` afterwards deletes about 200 MB of intermediate files.

### On a Steam Deck

Not tried on a real Steam Deck yet: it has been checked on a virtual 1280x800 screen and with the real disc, and the steps below are what a Deck should do. Please report what happens.

1. In desktop mode (Steam button, Power, Switch to Desktop), download `pentamoor-<version>-steamdeck.tar.gz` from the [releases](https://github.com/MadranFoyle/pentamoor/releases) and extract it
   where it can stay, for example in a `Games` folder in your home folder.
2. Double-click **Install Pentamoor**. A window asks for your disc image (the `.iso` of your own *Magic: The Gathering* CD, version 1.0) and shows the progress. It takes 2 to 15 minutes and about 1 GB of
   space, and downloads a C compiler (about 100 MB) into that folder, because SteamOS has none. Nothing else on the Deck is changed.
3. Say yes to **Add Pentamoor to Steam**. (If Steam is running it asks to close it first.) Switch back to Gaming Mode: Pentamoor is in your Library.
4. Open Pentamoor's page, press the controller button, and choose the **Gamepad** layout (Steam's own "Gamepad with Mouse Trackpad" works well: the right trackpad is the mouse). The Pentamoor layout offered
   in step 3 is an alternative that nobody has loaded in Steam yet. The Steam steps are in [docs/notes/steamdeck.md](docs/notes/steamdeck.md).

What to expect: the game starts full screen, at its own 1024x768 with a thin border on the 1280x800 screen. The left stick moves the cursor, A and B click, the buttons are in the table below, and the trackpads
and the touch screen are the mouse. Steam + X brings up Steam's keyboard for typing a name. There is no sound, speed or battery information from a Deck yet.

### From source

You need Python 3, a C compiler, `make` and SDL2 (`brew install sdl2` on macOS, `libsdl2-dev` on Debian).
`ffmpeg` is optional: it plays the ending movie and the spell and wizard clips.

```bash
python3 -m pip install pefile capstone
python3 tools/install/install.py "path/to/MTG v1.0.iso" --build     # extract, translate to C, compile the runtime and the game (a few minutes)
./pentamoor                                                            # play
```

The installer reads the image without mounting it, unpacks the game's own installer archive into
`sources/installed/Magic/Program` as the Windows installer would, and copies the disc's music and
movies. Nothing is downloaded, and none of the game, nor the C translated from it, is in the
repository (`sources/` is git-ignored). The build makes two parts: the runtime (`pentamoor-run`, no game code in it) and, from the C translated
from your files, a game module (a `.so` or `.dylib` per program) that the runtime loads when you run `./pentamoor`.

Other things to run:

- `./pentamoor deck` and `./pentamoor duel` run the standalone deck builder and duel program.
- The game runs at 1024x768, using its own larger layouts; the window is made smaller to fit a small display. `PORT_RES=640x480 ./pentamoor` gives the original's size, `PORT_RES=800x600` the one between.
- `PORT_FRAME_MS=40 ./pentamoor` changes the overworld's speed (default 60; lower is faster).
- Saves go to `port_overlay/`, not into the game's folder.

## Controls

The mouse and keyboard work as in the original (left click, right click for a card's menu, Enter and Escape for the default and cancel). A game controller works with no setup (Steam Deck, Xbox, PlayStation
or Switch pad: anything SDL knows as a game controller, plugged in before or while you play); the mouse takes the cursor back whenever it moves. In a duel the D-pad is enough: it walks the cursor over your hand, your cards, the opponent's, the life totals, the Done button and the phase icons (the card under the cursor is shown as for a mouse; A plays it, B opens its menu), so the stick is only for pointing freely.

| Controller | |
|---|---|
| Left stick | move the cursor (hold the left trigger to go slowly, press the right stick in to go fast) |
| D-pad | in a duel, a dialog or a menu: jump the cursor to the next card, button or row in that direction (hold to keep going); elsewhere the arrow keys (repeating while held) |
| A / B | left click (hold to drag) / right click |
| X or Start / Y or Back | Enter / Escape |
| LB / RB | Page Up / Page Down (lists, the deck builder's card row) |
| Right trigger + left stick | walk on the map in the direction you push |
| Right stick | arrow keys (castles, dungeons) |

Typing a name needs a keyboard (on a Steam Deck, Steam's keyboard: Steam + X). `PORT_NOPAD=1` turns the controller off, `PORT_FULLSCREEN=1` starts full screen (on a Steam Deck it does by itself; `PORT_FULLSCREEN=0` turns that off). Details and what is not tested: [docs/notes/controller.md](docs/notes/controller.md).

## Where things stand

It runs on macOS (Apple Silicon) and Linux (x86-64) and plays through the title screen, a new game,
the overworld, whole duels with the mouse, the deck builder, the game's dialogs, sound, music and the
coin toss movie. The title screen matches the original running in an emulator pixel for pixel.

| | |
|---|---|
| `MAGIC.EXE` (the game) | runs |
| `DECK.EXE` (standalone deck builder) | runs, but starts with an empty deck |
| `DUEL.EXE` (standalone duel program) | runs: setup dialog, coin toss, a duel against the AI |
| Sound and music | sound effects through a WAV mixer; music plays from the disc's WAV files (the game has no MIDI) |
| Video | coin toss movies, the ending movie and the 68 spell and wizard clips (the Indeo ones need `ffmpeg`) |
| macOS | tested |
| Linux (x86-64) | tested: install, build, tests, title screen and a new game into a duel, on CachyOS with gcc, but headless (no real display or speakers). Other distributions and architectures are untried |
| Windows (x86-64) | the runtime builds with MSYS2 MinGW-w64 and its unit tests pass in CI; CI also builds the release archive (own Python, own compiler) and has it build a stub game module and load it; the game itself has not been run there yet (`pentamoor.bat` is the launcher) |
| Steam Deck | the download, the window installer, adding to Steam, full screen and typed text are built and checked by CI and were run on a virtual 1280x800 screen with a real pointer and keyboard and the real disc; **no real Deck** has run it ([docs/notes/steamdeck.md](docs/notes/steamdeck.md) lists what is unchecked) |
| Releases | the four archives are built and checked by CI on every push (Windows, Linux, the Steam Deck's, macOS arm64 and x86-64 in one file); the installer from a release folder, with the real disc, is tested on macOS (arm64) and Linux; the x86-64 half of the macOS build has only been compiled |

After you win a duel against a wizard's creature the game plays two short clips on a black screen and then waits for a click or a key on a black screen ("Click or press a key to continue" is
written at the bottom); the reward screen follows. If something else seems stuck, run `./pentamoor 2> pentamoor.log` and send the log and what was on screen when it stopped
(`PORT_UI_LOG=1 ./pentamoor 2> pentamoor.log` adds what each click did).

Little of it has been played for long with a real mouse and keyboard yet, so expect rough edges and
please report them. Known gaps: the in-game Help and About, and the parts of the game nobody has
played through yet (for example winning a Gauntlet, or every castle event).

## Contributing

Build details, tests, the repository map and the tools for checking against the original game are in
[CONTRIBUTING.md](CONTRIBUTING.md).

## Legal

*Magic: The Gathering* is a trademark of Wizards of the Coast; *Shandalar* and *MicroProse* belong to
their owners. Pentamoor is not affiliated with or endorsed by them. This is preservation and research
work: it needs a copy of the game you own.

What the repository holds, and what it does not:

- **No game files.** No executable, library, picture, sound, movie or data file of the game, and no disc image.
- **No code generated from the game.** The game's own machine code is translated into C on your computer, from your own disc, when you install it. That C
  and the game modules built from it stay in the git-ignored `sources/` folder and are never committed or published, in a release or anywhere else.
  The release downloads hold the runtime and the tools that do the translating, not what they make.
- **No decompiler output.** No decompiled source, and no table made from one. `tools/release/check_tree.py` fails CI if anything that looks like it is tracked.
- What does come from studying the game: hand-written C (`src/native`) that reimplements some of the game's engine functions, written after studying the original's
  machine code (and, early on, a decompiler's reading of it) and checked against the original running; notes on how the game works (`docs/`); and facts about the executables, such as the
  addresses of functions and variables and the argument counts of the Windows calls it makes.

The repository has no license file; do not redistribute game files.

## History

Pentamoor started as a fork of [benprew/microprose-shandalar-source](https://github.com/benprew/microprose-shandalar-source), whose Ghidra decompilation work
(the decompiled C of the game's programs, the renamed functions, and the scripts that produced them) was the starting point for understanding the game.
That material has been removed from the tree, and nothing here depends on it any more: the lifter reads the game's own executables. The tools that only
worked on it (the one that paired the two programs' functions by their decompiled bodies, the name-duplicate audit, two helpers of the lifter's test harness) went with
it, and the maintainer keeps a private copy outside the repository. This repository begins from a copy of the finished tree, so its own history does not contain that material; the earlier history stays in the maintainer's previous repository and is not part of this one. The notes in `docs/` were written while it was in the tree, so they mention its file names, the generated names a decompiler gives
(`FUN_00401000` and the like) and its symbol maps; those refer to the removed material.

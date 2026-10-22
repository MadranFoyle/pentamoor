Pentamoor {version} ({platform})
================================

Pentamoor is a native port of MicroProse's 1997 "Magic: The Gathering" (Shandalar): the game's own
code, running on current systems, using the data files of a copy of the game that you own.
This download has NO game files in it, no code made from them and no decompiler output. You supply the game, and your own
computer builds its part of Pentamoor from it. Nothing is uploaded anywhere.

What you need
-------------
* Your own copy of the game: a disc image (an .iso file) of the retail "Magic: The Gathering" CD,
  version 1.0. (A raw .mdf/.mds pair has to be converted first: mdf2iso "MTG v1.0.mdf" "MTG v1.0.iso".)
@windows * Nothing else: the Python that runs the installer and the C compiler (Zig) that builds your game modules are in this download.
@macos * Python 3 (it comes with Apple's command line tools: xcode-select --install). If there is no C compiler,
@macos   the installer offers to download one (Zig, about 100 MB).
@linux * Python 3 and SDL2 (Debian/Ubuntu: sudo apt install python3 libsdl2-2.0-0; Fedora: sudo dnf install python3 SDL2;
@linux   Arch: sudo pacman -S python sdl2). If there is no C compiler (gcc, clang or cc), the installer offers to
@linux   download one (Zig, about 100 MB).
@steamdeck * A Steam Deck (SteamOS 3, x86-64). Python 3 and SDL2 are part of SteamOS. SteamOS has no C compiler, so the
@steamdeck   installer downloads one (Zig, about 100 MB, checked against a known checksum) into this folder. Nothing is
@steamdeck   installed system-wide: SteamOS's own files are read-only and are not touched.
* Up to 1 GB of free disk space while it builds (pentamoor-install --clean deletes about 200 MB of it afterwards)
  and a few minutes, once (2 to 15, depending on the computer).
* Optional: ffmpeg on the PATH plays the ending movie and the spell and wizard clips.

Install and play
----------------
@windows Double-click pentamoor.bat. The first time it asks for your .iso file (type or paste the path, or drag the
@windows file onto the window), installs, and starts the game. After that it just starts the game.
@windows (You can also drop the .iso file on pentamoor.bat, or run  pentamoor-install.bat "D:\MTG v1.0.iso".)
@windows If Windows SmartScreen warns about the program, choose "More info", then "Run anyway": the files are not signed.
@steamdeck On a Steam Deck, in desktop mode (Steam button > Power > Switch to Desktop), with this folder unpacked where it is to stay
@steamdeck (for example in ~/Games: the game is built here and runs from here; moving the folder later breaks the Steam shortcut):
@steamdeck   1. Double-click "Install Pentamoor" (the icon at the top of this folder). A window asks for your .iso file, shows the
@steamdeck      progress (2 to 15 minutes, up to 1 GB of disk space), and then offers to add Pentamoor to Steam.
@steamdeck      If the double click only asks what to do with the file, right-click it > Properties > Permissions > "Is executable".
@steamdeck   2. Say yes to "Add Pentamoor to Steam" (Steam is closed for a moment if it is running), and switch back to Gaming Mode.
@steamdeck   3. Pentamoor is in the Library (All Games). Press the controller button on its page and choose the "Pentamoor" layout
@steamdeck      (or Steam's own "Gamepad with Mouse Trackpad"): the game needs the Steam Deck to act as a game controller, not as a keyboard.
@steamdeck   The game starts full screen on a Steam Deck by itself (PORT_FULLSCREEN=0 turns that off). Steam + X brings up the on-screen keyboard
@steamdeck   (it is meant to come up by itself when the game wants a name typed; that has not been tried on a real Deck yet).
@steamdeck There is also a terminal way, the same on any Linux:
@unix Open a terminal in this folder and run:
@unix
@unix     ./pentamoor
@unix
@unix The first time it asks for your .iso file (type or paste the path, or drag the file onto the terminal window),
@unix installs, and starts the game. After that it just starts the game.
@unix (You can also run  ./pentamoor "path/to/MTG v1.0.iso"  or  ./pentamoor-install "path/to/MTG v1.0.iso".)
@macos If macOS says the program cannot be opened because it is from an unidentified developer (the files are not
@macos signed), run this once in the folder, then try again:   xattr -dr com.apple.quarantine .

@unix Other things to run: "./pentamoor deck" and "./pentamoor duel" run the standalone deck builder and duel program.
@windows Other things to run: "pentamoor.bat deck" and "pentamoor.bat duel" run the standalone deck builder and duel program.
Spells of the Ancients 2.15 (experimental)
The expansion at its last version is installed over the first game by the same installer, from three files you own: the disc image of the first game (as above), a disc image of
the expansion (Magic: The Gathering "Spells of the Ancients", version 2.0, usually MTG v2.00.iso) and the 2.15 patch SOTAV215.EXE (1,207,571 bytes):
@unix     ./pentamoor-install "path/to/MTG v1.0.iso" --sota "path/to/MTG v2.00.iso" --patch "path/to/SOTAV215.EXE"
@unix then run  ./pentamoor sota
@windows     pentamoor-install.bat "path\to\MTG v1.0.iso" --sota "path\to\MTG v2.00.iso" --patch "path\to\SOTAV215.EXE"
@windows then run  pentamoor.bat sota
It takes a few minutes more than the first game alone. Everything is checked before anything is written; if a file is missing, in the wrong place or the wrong one (a cut-short patch, the
expansion's disc given first) the installer says what it found and what it needs. The 2.15 game is a folder of its own (sources/installed_sota) with its own saves (port_overlay_sota), and
the first game is not changed by it. The expansion's own shell (magic.exe), ManaLink and controller navigation are not part of it.
At the end the installer does what the original Spells of the Ancients installer did for an owner of the discs: it runs the original installer's own writer (a library from the expansion's cabinet
on your machine, checked first by its SHA-256) to write the game's machine-bound licence value into port_overlay_sota/registry.dat, with the flag word the original used (and, by default, one flag more, below), bound to a
random machine id made for this install only. It says so when it does it. Nothing of that is in this download, and the game and the launchers never write it. --no-licence-value skips it
(the game then offers its base pool of 409 cards, with it also the 145 cards of the game's "set 1"). Because the discs were just verified, the licence value also carries the flag the game
itself defines as "skip the disc check", so the install does not ask for a disc later (the original installer did not set that flag); the installer says so. --keep-cd-check leaves that
flag out, so the install asks for a disc where the original did. The installer's check of your discs is software and an install folder can be copied like any file, as the original's installed
copy could; nothing in this download works without your own discs. --keep-cd-check together with --no-licence-value is refused (--no-cd, which added the flag only when asked, is gone: it is the default now).

The game runs at 1024x768 (PORT_RES=640x480 gives the original size). Saves go to the port_overlay folder.
Display: F11 or Alt+Enter switches full screen on and off (on a controller: press both sticks in and hold for a second), Ctrl+F11 changes how the
picture fills the window (fit, integer, stretch), Shift+F11 the filter (nearest, linear, sharp). The window can be resized. The choices are kept
in port_overlay/display.cfg (PORT_SCALE, PORT_FILTER, PORT_FULLSCREEN and PORT_WINDOW=WxH set them for one run).
@unix "./pentamoor-install --help" lists the installer's options: --check shows what is ready, --self-test checks the
@windows "pentamoor-install.bat --help" lists the installer's options: --check shows what is ready, --self-test checks the
compiler, --compiler picks one (for example --compiler gcc), --no-download refuses to fetch anything,
--clean removes the intermediate files (about 200 MB) after a successful build.

What is in this folder
----------------------
@unix pentamoor-run           the runtime: the program that runs the game's code (no game-derived code in it)
@windows pentamoor-run.exe       the runtime: the program that runs the game's code (no game-derived code in it)
@windows SDL2.dll               the SDL2 library it uses (zlib license, see licenses\)
@windows python\                the embeddable Python 3 that runs the installer (Python license)
@windows tools\local\ziglang\   the Zig C compiler that builds your game modules when there is no other (MIT license)
@windows pentamoor.bat, pentamoor-install.bat   start the game / install it
@unix pentamoor, pentamoor-install   start the game / install it
tools/install, tools/lift   the installer and the lifter that turns your game files into C
tools/pydeps            the Python packages the lifter uses (pefile, capstone)
src/                    the headers and glue your game modules are compiled with
SHA256SUMS              checksums of every file here
NOTICE.txt              what this is, licences, trademarks

After installing there will also be sources/ (your game files, the C made from them, objects) and
game_magic, game_deck and game_duel (the game modules built from your files). Do not share those.

Source code, issues and the developer documentation: https://github.com/MadranFoyle/pentamoor

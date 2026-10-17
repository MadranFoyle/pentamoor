# Contributing to Pentamoor

This is the developer's guide: how the project is built, how to test it, where things live, and how
to check a change against the original game. For what Pentamoor is and how to play it, see the
[README](README.md).

## How it fits together

There is no emulator. The game's machine code is translated into C by a lifter (`tools/lift`), and the
Windows calls it makes (kernel32, user32, gdi32, winmm and the C runtime) are answered by a C layer
(`src/port`) over SDL2 for the window, the mouse and keyboard, and the sound.

What the lifter produces is *translated* code, not readable source. It works one instruction at a time
on the same registers and memory as the original, so it adds no new behaviour, but it is not something
a person would write. The aim is to replace lifted functions with clean C one at a time, each checked
against its lifted twin; see [docs/PHASE_C.md](docs/PHASE_C.md),
[docs/PORT_STRATEGY.md](docs/PORT_STRATEGY.md) and, for what new code should keep in mind, [docs/ROADMAP.md](docs/ROADMAP.md).

## Ground rules

- **No game files, no code generated from them, and no decompiler output, in the repository.** `sources/` is git-ignored and
  holds the installers, disc images, the game's files and the lifted C. Do not commit anything from it, and do not add a decompiler's output (a decompiled source, a table of
  names made from one): `python3 tools/release/check_tree.py` fails, in CI, when something that looks like it is tracked.
- Keep commit messages and PR descriptions free of tool-attribution lines.
- Pull requests go to this repository's `main` only (`gh pr create --repo MadranFoyle/pentamoor --base main`),
  not to the upstream repository this was forked from.
- CI (GitHub Actions: Ubuntu, macOS and Windows) runs the tests below that are marked "in CI", plus `tools/release/check_tree.py` and `tools/release/check_links.py`, builds the runtime with no generated sources present, and builds and checks the release archives (see "Making a release"); keep it green. The jobs are described in [docs/notes/ci.md](docs/notes/ci.md).
- **Never publish a game module** (`game_*.so/.dylib/.dll`), a file of the game, or C generated from it: not in a release, not as a CI artifact, not in a PR. The release workflow builds only the runtime; `tools/release/check_archive.py` fails an archive that has any of them.

## Building by hand

`tools/install/install.py "path/to/MTG v1.0.iso" --build` does everything (see the README). Without
`--build` it only extracts the game. The steps it runs are:

```bash
tools/lift/lift_all.sh        # translate MAGIC (with STATWIN, DECKDLL), DECK and DUEL into sources/generated/
make -C src/port -j8          # the runtime (build/pentamoor-run) and the game modules (build/game_magic.so, game_deck, game_duel; .dylib on macOS)
```

The build is in two parts. The **runtime**, `pentamoor-run`, holds no game-derived code (it builds without `sources/generated`, so a
prebuilt one can be published). A **game module** is a shared library made only from the lifted C of one program (`lift_magic_all`: MAGIC.EXE
and its DLLs; `lift_deck`: DECK.EXE; `lift_duel`: DUEL.EXE), and the runtime loads it by path at start:
`src/port/build/pentamoor-run -m src/port/build/game_magic.so sources/installed/Magic/Program/MAGIC.EXE`. The two share no symbol names: the
module exports `pentamoor_game_init` and is handed one table of pointers (how it works: [docs/PHASE_C.md](docs/PHASE_C.md), "The runtime and the game module").
`make -C src/port runtime` and `make -C src/port modules` build one half; `make -C src/port static GEN=../../sources/generated/lift_deck BUILD=build_deck`
still makes the old single executable of one program.

Windows: the same `make -C src/port` in an MSYS2 MINGW64 shell (`pacman -S make mingw-w64-x86_64-gcc mingw-w64-x86_64-SDL2`) makes `build/pentamoor-run.exe` and `build/game_magic.dll`;
`pentamoor.bat` is its launcher. Host-specific code (guest memory, loading the module, `mkdir`, `popen`, ...) goes in `src/port/plat.h`, `plat_posix.c` and `plat_win.c`, not into
the other files; a new call that hands guest memory to a system call needs `plat_guest_commit` (docs/PHASE_C.md, "Windows"). CI builds and tests on Windows too.

There is a second way to build the game modules that needs no `make`: `python3 tools/install/install.py "path/to/MTG v1.0.iso" --modules` lifts (in Python, the three programs at the same time, again only
when the lifter or the game files changed) and then compiles each `*_gen.c` of a program in parallel with `tools/install/modbuild.py`, which picks the compiler (`$PENTAMOOR_CC` or `--compiler`; else the
first of `cc`, `gcc`, `clang` that really builds a shared library; else the Zig in `tools/local`, downloaded from PyPI on a yes, `tools/install/zigdl.py`) and links the library. It is what a release does
(there is no Makefile in a release); its flags are the Makefile's module flags, and a test (`tools/install/test_release.py`) compares the two. `install.py --self-test` builds the small stub module
(`src/port/stubgame`) with the chosen compiler and has the runtime load it, with no game files.

`modbuild.py` can also build the modules for another system than the one it runs on, which is how someone with several machines of their own can build all their modules on one of them:
`python3 tools/install/modbuild.py --target windows-x86_64 --out some/folder` (`--list-targets`: `windows-x86_64`, `linux-x86_64`, `linux-aarch64`, `macos-arm64`, `macos-x86_64`, or a Zig triple such as
`x86_64-windows-gnu`; `--gen` names the lifter's output, default `sources/generated`; `--build-dir` keeps one target's object files apart from another's). Zig is the cross compiler (`zig cc -target ...`, the
one `zigdl.py` fetches into `tools/local`, or `--tools DIR`); for a Mac target on a Mac the system's clang is used first (`-arch arm64` or `x86_64`, macOS 11). The Linux targets are built against glibc 2.35,
the one the release runtime is built with, so the module loads on that and newer. Nothing is run, and a native build (no `--target`) is exactly what it was. The result is a file to carry over, made from
the game: keep it like `sources/`. A macOS module for both processors is two builds joined with `lipo -create`; the runtime of the macOS release is universal and `dlopen` picks the half that matches.
`tools/install/test_modbuild_target.py` checks the command lines, the names and the compiler choice with no game files and no cross compiler.

**iOS** (macOS with Xcode only; [docs/notes/ios.md](docs/notes/ios.md)): there is no module to load on an iPad, so the three programs' lifted C is linked into the app. `tools/ios/build_ios.sh simulator` builds SDL2 (the same pinned source as the macOS runtime), the
three modules (each joined into one object whose only visible symbol is its renamed `pentamoor_game_init_<program>`), the runtime (`make -C src/port ios-runtime`, which also builds with no game files) and `dist/ios/simulator/Pentamoor.app`; `tools/ios/sim.sh` installs it
in a simulated iPad Pro and copies the game in; `tools/ios/gen_xcodeproj.py` writes the Xcode project for a real device, and `tools/ios/deploy.sh` runs the whole device flow in one command (an "iPad kit" with the compiled game modules and the game folder, made locally, lets the Mac the iPad is plugged into skip the build of the game: docs/notes/ios.md, "One command"). **Never commit a built app or a kit** (`dist/` is git-ignored): it holds code made from the game.

The `./pentamoor` launcher runs one of the three (`./pentamoor`, `./pentamoor deck`, `./pentamoor duel`).
Saves go to `port_overlay/` (the variables that change where it looks are in "Environment switches").

## Making a release

A release is the **runtime only**, plus what turns a user's own disc into the game modules on their machine. The reason for the split is legal: a game module is derived from the game's machine
code, so each one is built locally from the user's own ISO and never published (README, "Legal"). `.github/workflows/package.yml` builds the archives and `release.yml` publishes them; `ci.yml` runs
`package.yml` on every push, so the packaging is tested all the time (the archives can be downloaded from the run for a week).

To cut a release (maintainers; pushing a tag is what publishes, so only when `main` is green and the version is chosen):

```bash
git tag -a v0.1.0 -m "Pentamoor 0.1.0"        # v0.1.0-rc1 makes a pre-release
git push origin v0.1.0
```

`release.yml` then calls `package.yml` for the three systems (the Linux job also packs the Steam Deck's download), looks inside every archive for anything made from the game (`check_archive.py --static`), writes `SHA256SUMS`, and runs
`gh release create` with the four archives. Each archive unpacks to `pentamoor-<version>-<system>/`:

| | Windows x86-64 (`.zip`) | Linux x86-64 (`.tar.gz`) | macOS universal (`.tar.gz`) |
|---|---|---|---|
| `pentamoor-run` | MinGW-w64 build (winpthreads linked in), `SDL2.dll` beside it | built on ubuntu-22.04 (glibc 2.35), links the system's `libSDL2-2.0.so.0` | arm64 and x86-64 in one file, SDL2 2.32 built from its pinned source and linked in (only system frameworks needed), signed ad hoc, macOS 11+ |
| launchers | `pentamoor.bat`, `pentamoor-install.bat` (CRLF) | `pentamoor`, `pentamoor-install` | same as Linux |
| Python | `python/` (the embeddable 3.13, pinned and checksummed) | the system's Python 3 | the system's Python 3 |
| `tools/pydeps/` | pefile and capstone for the platform (pip `--platform`; no network at install) | same | same (capstone's universal2 wheel) |
| C compiler | `tools/local/ziglang/` (Zig 0.16, bundled) | system cc/gcc/clang, else Zig downloaded on a yes | same as Linux |

The **Steam Deck** archive, `pentamoor-<version>-steamdeck.tar.gz` (`package.py --platform steamdeck`), is the Linux one (the same runtime and bits) plus `tools/steamdeck/` (the window installer `install-gui.sh`,
`add-to-steam.py`, the Steam Input layout), two `.desktop` icons at the top of the folder (Install Pentamoor, Add Pentamoor to Steam) and a README with a Steam Deck section; `check_archive.py` also tries its scripts on a fake
Steam folder. What it is and what has not been verified: [docs/notes/steamdeck.md](docs/notes/steamdeck.md).

Every archive also has `tools/install`, `tools/lift`, the `src/native` headers and `src/port` glue a module is compiled with, `src/port/stubgame` (for `--self-test`), `README.txt`, `NOTICE.txt`, `VERSION` and its own `SHA256SUMS`. What goes in is listed in `tools/install/manifest.py`
(`install.py --check` reports a release that lacks any of it). CI cannot run the tag push or the publish step; everything before them runs on every push. The same packaging on your own machine:

```bash
make -C src/port runtime                       # macOS: sh tools/release/build_macos.sh universal dist/macos instead (SDL2 linked in)
python3 tools/release/package.py --platform linux-x86_64 --version 0.0.1-test --runtime src/port/build/pentamoor-run --fetch-pydeps --out dist
python3 tools/release/check_archive.py dist/pentamoor-0.0.1-test-linux-x86_64.tar.gz     # unpacks in a new folder, builds the stub module with the archive's own installer, loads it
```

Pins to refresh now and then (each is a checksum or a commit): the Zig wheels in `tools/install/zigdl.py` (PyPI file and checksum per system), the embeddable Python and its checksum in
`tools/release/package.py`, SDL2's version and checksum in `tools/release/build_macos.sh`, and the actions in `ci.yml`, `package.yml` and `release.yml` (full commit SHAs with the tag in a comment; take releases at least two weeks old; the three files use the same SHAs for the same action).

## Adding a build

The port is made from one build of the game (the retail disc's version 1.0). Another build (a patched program, Spells of the Ancients) is a different set of files with different addresses, and the runtime **refuses to start** a program whose build it has no
profile for (exit status 3, `pentamoor: ... is build <id>, which this version does not support`; `PORT_UNKNOWN_BUILD=1` starts it with every address-keyed hook off, for research). What a profile is and how the check works: [docs/PHASE_C.md](docs/PHASE_C.md), "Build profiles". To teach the
port a build:

1. **Get its build id**: `python3 -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" PROGRAM.EXE`, or `sha256sum`; the lifter writes the same into the module it makes (`LIFT_BUILD_ID` in `handlers_gen.c`).
2. **List the files** in `tools/lift/builds.py` (`KNOWN`: build name, file, id, and `"lifted"` for the files the port runs lifted code from, `"host"` for libraries it provides itself). A test keeps this list equal to the table in the runtime.
3. **Add one row per lifted file** to `PROFILES` in `src/port/profile.c`: a struct initialiser with the id (`#define ID_...` above it), `.build`, `.file`, `.program` (the program's `LIFT_PROGRAM`, `""` for a library, with `.base`), and the groups that file has, with its own addresses:
   `.lzw` (where its picture decompressor and the state behind it are; the lifter leaves it out, so without it the game stops at its first picture), `.pace`, `.buttons`, `.textmenu`, `.buycards`, `.clues`, `.title`, `.keys`, `.display`. A field left out is 0 and its hook is not installed;
   there is no code to change for an address. Find the addresses in the new build the way the old ones were found (`docs/notes/sota-comparison.md` shows how they were matched from 1.0, `tools/research/sotahooks.py`).
4. **Lift and build it** as usual (`tools/install/install.py <disc> --build` lifts from the files in `sources/installed`); the module carries the new id.
5. **Add the test**: in `src/port/test_profile.c`, assert the new row's values against the addresses you found (the 1.0 test compares each field with the literal the sources had, which is what keeps a typo out), and that the row is selected by its id.
6. Check what the profile does not cover (docs/PHASE_C.md lists it): the layout table `src/native/layout.c` and the record sizes `src/native/engine.h` are the engine's, per program and not per build, the geometry that `screens.c` assumes is the 640x480 layout, and `navwm.c` looks for the window classes by name.

`python3 -m pytest tools/lift/test_lift.py` fails when a game address is written in the code of `src/port` outside `profile.c`: new hooks take their addresses from the profile too.

## Tests

None of these need the game files. "In CI" marks what the workflow runs (`.github/workflows/ci.yml`; the Windows job runs the C tests and `tools/install` only).

```bash
make -C src/port test                          # (in CI) window manager, graphics, sound, movies, paths, controller logic, D-pad navigation, Steam Deck decisions and typed text, build profiles, lifter runtime
python3 -m pytest tools/lift/test_lift.py      # (in CI) the lifter, and the scan that finds the game's functions; the build id; no game address in src/port outside profile.c
python3 -m pytest tools/install                # (in CI, also on Windows) the installer: disc reader, archive, decompressor; compiler choice, module build commands, Zig download, lifter command lines, release layout, launcher
python3 -m pytest tools/steamdeck              # (in CI, Linux and macOS) the Steam Deck tools: the Steam shortcut writer on a hand-built shortcuts.vdf, the window installer's dialogs, the controller layout
make -C src/port check-front                # (in CI) the SDL front end builds and its checks pass
make -C src/port check-module               # (in CI) the runtime loads a game module (a nearly empty one made here), no game files needed
make -C src/port check-run                  # (in CI) the SDL window starts on SDL's dummy drivers, with that module
make -C src/port check-program              # (in CI) a tiny PE made by stubgame/mkpe.c runs through the loader and the file layer, with that module (PORT_UNKNOWN_BUILD=1: it is in no profile)
make -C src/port check-build                # (in CI) ... and without the switch it is refused (exit status 3, the message), and so is a file that is not the one the module was made from
python3 tools/install/install.py --self-test   # (run on every archive in CI) the module build in Python (compiler choice, flags, link) on the same stub module, loaded by the runtime
python3 tools/release/check_tree.py            # (in CI) nothing tracked looks like decompiler output
python3 tools/release/check_links.py           # (in CI) every link between the Markdown files resolves, anchors included
python3 -m pytest tools/release                # (in CI) check_tree, check_links, and that this file's table of environment variables is the whole list the code reads
python3 -m pytest tools/research               # (in CI) the readers of other builds' files (the Spells of the Ancients research), on files the tests make up
python3 -m pytest tools/ios                    # (in CI) the Xcode project generator, the iOS build script's flags and pins, tools/ios/deploy.sh (JSON, team, stamp, commands, the flow against a fake xcrun) (no Xcode needed); `make -C src/port ios-runtime` (macOS, in CI) compiles the runtime for iOS, and `tools/ios/deploy.sh --selftest` (macOS, in CI) checks its options against the Xcode's own help
python3 -m pytest tools/difftest tools/registry tools/verification_harness/tests   # not in CI: the checks of native engine functions, the name registry, the oracle harness' pure logic
```

`tools/emu_spike/tests` (the Python emulator) need `unicorn` (`pip install -r tools/emu_spike/requirements.txt`) and are not in CI either.

`tools/display/` checks the display work ([docs/notes/display.md](docs/notes/display.md)) against real windows, with the installed game: `xe2e.py` on a Linux box with Xvfb (it builds `minwm.c`, a 150-line window manager, and `xtool.c`, which makes real key and pointer events with XTest, and plays the title screen through full screen, the scaling modes and filters, resizing, `display.cfg` and clicks on the drawn buttons), and `hidden_e2e.py` on any machine with a video driver (a real window that is never shown, `PORT_HIDDEN=1`: a Retina Mac's Metal drawable, the filters, the pointer mapping in window points).

`tools/soak/` plays many duels through the control pipe and reports crashes and hangs (`soak.py`); `pad_play.py` plays a new game and a duel with controller commands only, `nav_play.py` checks the D-pad's moves between cards, buttons and menu rows in a duel, `pad_realtime.py` plays a duel with the pad at a person's speed (buttons held 120 to 150 ms, 450 ms apart) and reads the input log (`SOAK_ENV="SDL_VIDEODRIVER=x11 DISPLAY=:1 PORT_STEAMDECK=1 PORT_FULLSCREEN=1"` runs any of them on a real X server in a Deck's setup), and `screen_nav_play.py` checks it on the screens the game draws itself (title, new game, village, shops, clues, stats, the deck builder). All need the
installed game.

## Environment switches

All are environment variables. This table is the whole list of the ones the runtime, the launchers and the tools read (`tools/release/test_docs.py` fails when the code reads a `PORT_*` or `PENTAMOOR_*` name that is not here, or this table has one that nothing reads); the debugging ones are explained further in [docs/PHASE_C.md](docs/PHASE_C.md).

| Variable | Effect |
|---|---|
| `PORT_HEADLESS=1` | no window (unset, empty or `0` is off, in the front end and in the message-box choice alike) |
| `PORT_MUTE=1` | no sound |
| `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy` | run with no display or speakers (what CI and automated runs use) |
| `PORT_SCRIPT`, `PORT_CONTROL` | drive the window by a script file or by a named pipe (clicks, keys, screenshots) |
| `PORT_RES=640x480` / `800x600` / `1024x768` | the screen's size (default 1024x768, which uses the game's larger layouts; 640x480 is the original's) |
| `PORT_WINDOW=WxH` | the SDL window's size in points (default: the last one used, else the largest whole multiple of the screen that fits 90% of the display; the picture and the mouse scale with it; not written to `display.cfg`) |
| `PORT_NOPAD=1` | no game controller (a pad is otherwise the mouse and keyboard whenever one is used; `docs/notes/controller.md`) |
| `PORT_FULLSCREEN=1` | a borderless full-screen window (the default on a Steam Deck or in Gamescope; `PORT_FULLSCREEN=0` turns that off) |
| `PORT_HIDDEN=1` | a test aid: the window is made and drawn to but never shown (the `winshot FILE` and `wclick X Y` control steps read back what it drew, at the drawable's size in pixels, and click in window coordinates: `tools/display/hidden_e2e.py`) |
| `PORT_SCALE=fit` / `integer` / `stretch` | how the picture fills the window: the largest size with its shape kept (a whole-number scale when that loses under 10%), always a whole-number scale, or the whole window ignoring the shape. Ctrl+F11 cycles it |
| `PORT_FILTER=nearest` / `linear` / `sharp` | crisp pixels, smooth, or a whole-number enlargement then smooth (the default). Shift+F11 cycles it |
| `port_overlay/display.cfg` | the display settings kept between runs (full screen, scale, filter, window size and place), written by the front end in the overlay folder; the three variables above and `PORT_FULLSCREEN` win over it. Not written on SDL's dummy and offscreen drivers. `docs/notes/display.md` |
| `PORT_STEAMDECK=1` / `0` | say this is (or is not) a Steam Deck, for the defaults above and below (otherwise: `SteamDeck=1`, SteamOS in `/etc/os-release`, Gamescope; `docs/notes/steamdeck.md`) |
| `PORT_TEXTINPUT=auto`, `PORT_TEXT_LOG=1` | SDL's text input (what brings up an on-screen keyboard) only while a text field has the focus; the default on a Deck, always on elsewhere. `PORT_TEXT_LOG=1` prints each change |
| `PORT_PAD_LOG=1` | a time-stamped log of what the input does (controllers SDL found, each button, what the pad asked the game to do, the D-pad's mode, the window each click reached) on stderr and in the file `pentamoor-input.log` in the folder the program was started in; `=PATH` names the file, `=stderr` keeps it off disk. For bug reports from a machine with no terminal (a Steam Deck: `docs/notes/steamdeck.md`, "When the pad does nothing in a duel") |
| `PORT_PAD_BACKGROUND=1` | the pad keeps working while another window has the focus (the default on a Deck) |
| `PORT_UNKNOWN_BUILD=1` | start a program whose build has no profile (`src/port/profile.c`) instead of refusing it (exit status 3), with every address-keyed hook, override and write off: for research, the game will probably stop at its first picture |
| `PORT_TOUCH=1` / `0` | fingers are the mouse through `touch.c` (a tap is a left click, a long press or a two-finger tap is a right click, a drag drags; docs/notes/ios.md): on by default on iOS, off elsewhere (SDL's own touch-as-left-button stays) |
| `PENTAMOOR_PROGRAM`, `PENTAMOOR_LOG` | iOS only: `magic` (default), `deck` or `duel` (else `Documents/program.txt`); `PENTAMOOR_LOG=console` keeps stderr on the console instead of `Documents/pentamoor.log` |
| `PORT_FRAME_MS` | the overworld's frame time in ms (default 60) |
| `PORT_OVERLAY` | where saves and other writes go |
| `PORT_MSGBOX=ask` / `auto` | the game's `MessageBoxA`: `ask` shows the box and waits for an answer, `auto` answers at once with the default button (`IDOK`, `IDYES`, ...) and logs it. Unset: `auto` when `PORT_CONTROL`, `PORT_SCRIPT`, `PORT_HEADLESS` or `SDL_VIDEODRIVER=dummy` is in use (nobody can answer), else `ask` |
| `PORT_FFMPEG=/path/to/ffmpeg` | which ffmpeg plays the Indeo clips (`none`: play as if there were none; default: the PATH, then the usual places) |
| `PORT_TRACE_FN=0xADDR`, `PORT_FRAME_LOG=1`, `PORT_UI_LOG=1` | tracing: the arguments of each call of a lifted function; frames slower than the period; what each click did |
| `PORT_TRACE=1`, `PORT_TRACE_IMPORTS=1`, `PORT_CALLS=1`, `PORT_WHO`, `PORT_WHO_LIVE`, `PORT_BLITLOG=1`, `PORT_MSGLOG=1` | more tracing: file and path lookups; every import call from the start; the imports called, with counts, at exit; who called the named imports or functions (`PORT_WHO=GetDC,0x0050db10`); every `BitBlt` and `StretchBlt`; every window message (docs/PHASE_C.md) |
| `PORT_STUB=1` | an import that is not implemented returns 0 and is listed at exit, instead of stopping the run |
| `PORT_SHOT=FILE`, `PORT_SHOT_AT=SECONDS` | write the composed screen to a `.ppm` at those seconds (default 10; a list separated by commas takes several) |
| `PORT_AUDIO_DUMP=FILE` | write what the audio device was given (signed 16 bit stereo, 22,050 Hz) |
| `PORT_COV=FILE`, `PORT_WATCH` | a coverage build only (`make -C src/port BUILD=build_cov EXTRA=-DLIFT_TRACE`): the lifted instructions that ran; every write to a stretch of guest memory (docs/PHASE_C.md) |
| `PENTAMOOR_GAME`, `PENTAMOOR_RUN`, `PENTAMOOR_MODULE` | the launcher `./pentamoor`: the folder that holds `MAGIC.EXE` (default `sources/installed/Magic/Program`), another runtime binary, another game module |
| `PENTAMOOR_CC` | the installer's C compiler (as `--compiler`), for the module build without `make` |
| `PENTAMOOR_TEAM`, `PENTAMOOR_BUNDLE_ID`, `PENTAMOOR_DEVICE`, `PENTAMOOR_IOS_CONFIG` | `tools/ios/deploy.sh` only: the Apple team, the app's bundle id, the iPad, and the settings file that holds them (docs/notes/ios.md, "One command") |

When running several copies at once (for example from scripts), give each its own control pipe and
overlay, and stop them by process id, not by name.

## Repository map

| Path | What |
|---|---|
| `src/port/` | the native program: PE loader, thread scheduler, the Win32 layer (`user32.c`, `gdi*.c`, `kernel32*.c`, `crt.c`...), the dialog and control renderer (`ui.c`), SDL front end (`front_sdl.c`; its pure decisions: `pad.c`, `steamdeck.c`, `textin.c`), sound mixer, movies, tests |
| `tools/lift/` | the lifter: x86 machine code to C (`x86lift.py`, `gen_handlers.py`, `gen_dll.py`), `fnscan.py` (finds the functions of a program in its own code), the import signatures, tests |
| `src/native/` | the runtime header the lifted code uses (`lift_rt.h`, `lift_tables.h`), and hand-written C versions of verified engine functions with the addresses they stand in for (`layout.c`) |
| `src/port/profile.c` | the build profiles: the build id (SHA-256 of a file), the table of known builds with every address of the game the port hard-codes, and the refusal of an unknown build ([docs/PHASE_C.md](docs/PHASE_C.md), "Build profiles") |
| `tools/install/` | the installer: reads the disc image, unpacks the game's InstallShield archive (`blast.py`, `datax.py`, `iso9660.py`), copies the music and movies, then `--build` lifts and compiles (`liftrun.py`: the lifter run from Python; `modbuild.py`, `zigdl.py`: the compiler choice and the module build without make; `manifest.py`: what a release carries) |
| `tools/ios/` | the iPad app: `build_ios.sh` (SDL2, the game modules linked in, the app), `sim.sh` and `sim_drive.py` (the Simulator), `gen_xcodeproj.py` (the Xcode project for a device), `deploy.sh` (one command: check, sign, build, install, copy the game, start; `--dry-run`, `--selftest`, `--simulator`), `Info.plist.in`, `Pentamoor.entitlements`, tests |
| `tools/steamdeck/` | the Steam Deck: `install-gui.sh` (the installer with a file picker and a progress bar), `add-to-steam.py` (writes the Steam shortcut, a menu entry, the layout), `progress.py`, the Steam Input layout, the `.desktop` icons, tests |
| `tools/release/` | the release archives: `package.py` lays one out from a built runtime, `check_archive.py` unpacks and checks it, `build_macos.sh` makes the macOS runtime with SDL2 linked in, `win_libs.sh` lists the DLLs for Windows; `check_tree.py` (nothing tracked looks like decompiler output) and `check_links.py` (the Markdown links resolve); `README.release.txt` and `NOTICE.txt`, the two text files every archive carries |
| `pentamoor`, `pentamoor.bat`, `pentamoor-install`, `pentamoor-install.bat` | the launchers and the one-command installer (they work in a checkout and in a release) |
| `tools/verification_harness/` | boot and drive the original under QEMU (`oracle_*`, `probe_*`), plus the pure-logic pieces of the planned comparison (input script schema, monkey policy, state snapshot, bisection) and their tests |
| `tools/emu_spike/` | the Python Win32 layer that ran the game in a CPU emulator first; it is the specification the C layer follows |
| `tools/registry/` | the names `docs/SYMBOL_VERIFICATION.md` verified, as a CSV, and a check of their addresses against the real executables |
| `tools/difftest/` | check native C versions of engine functions against recorded calls of the original ([SPEC](tools/difftest/SPEC.md)) |
| `tools/soak/` | plays many duels through the control pipe and reports crashes and hangs; the controller and screen-navigation players (all need the installed game) |
| `tools/display/` | checks the display work against real windows (an X server, or a hidden window on any machine; need the installed game) |
| `tools/research/` | readers of the files of other builds of the game (the patch, the cabinet, `cards.dat`, the overlay merge) and the comparisons of [docs/notes/sota-comparison.md](docs/notes/sota-comparison.md); they read files you supply and are tested on files the tests make up |
| `.github/` | the workflows (`ci.yml`, `package.yml`, `release.yml`), `ci-run.sh` and the CI's Python packages |
| `docs/` | the documents below; `docs/notes/` holds the findings of each area (overworld, movies, saves and paths, dialogs, duel prompts, lifter, controller, display, Steam Deck, iOS, CI) |
| `sources/` | local only, ignored by git: installers, disc images, the game's files, and the generated lifted C |

**Names found in the notes are unreliable unless they are verified.** The executables have no names in them; the names in older notes came from a decompiler's guesses (the upstream
project's work, see the README's History): a random sample of 30 "meaningful" ones found about 1 in 5 wrong or misleading and about 1 in 3 unsupported by the
code. Names confirmed by running the real game are logged in [docs/SYMBOL_VERIFICATION.md](docs/SYMBOL_VERIFICATION.md); trust those, and read the code for
the rest. The native program does not depend on any names; it runs the machine code, and the lifter finds the functions in it (`tools/lift/fnscan.py`).

## Checking against the original

To learn what the original code really does, run it. [docs/ORACLE_VM.md](docs/ORACLE_VM.md) describes a
Windows 98 virtual machine (QEMU) that boots the retail game headlessly, with scripted mouse and keyboard
input and a debugger connection, so a function can be checked by watching it run. Media and disk
images stay in the git-ignored `sources/` folder; you supply your own.

```bash
tools/verification_harness/oracle_launch.sh      # boot the original under QEMU
tools/verification_harness/oracle_ctl.py shot    # screenshot; also: click X Y, key ...
```

The title screen of the native build matches, pixel for pixel (0 of 307,200 differ), what the original's code draws in the Python
emulator of `tools/emu_spike` (`src/port/compare_screen.py`, which still starts the old single executable `build/pentamoor` that only `make static` makes now: [docs/notes/audit-2026-10.md](docs/notes/audit-2026-10.md)); that comparison is the model for checking other screens. It was not compared with the Windows 98 virtual machine.

## Docs

- [PHASE_C.md](docs/PHASE_C.md): the native program: how it is built, what each part does, what was found by playing, debugging switches
- [ROADMAP.md](docs/ROADMAP.md): the goals for new code (display, mobile, replacing lifted code with clean C)
- [PORT_STRATEGY.md](docs/PORT_STRATEGY.md): the strategy (emulated original first, native replacement after), with a spike
- [ORACLE_VM.md](docs/ORACLE_VM.md): building and using the emulated original, and its quirks
- [VERIFICATION_HARNESS_PLAN.md](docs/VERIFICATION_HARNESS_PLAN.md): the verification plan and checklist
- [SYMBOL_VERIFICATION.md](docs/SYMBOL_VERIFICATION.md): names confirmed on the running game
- [FILE_FORMATS.md](docs/FILE_FORMATS.md): `.SPR` and `.PIC`, checked against real files
- [docs/notes/](docs/notes/): per-area findings
- [notes/audit-2026-10.md](docs/notes/audit-2026-10.md): the October 2026 audit of the documents against the code: what was checked, and what is still open

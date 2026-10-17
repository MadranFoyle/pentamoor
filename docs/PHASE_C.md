# Phase C: from the emulator to a native program

*(Written in stages as the work went. Where an early section gives a count or a state ("to come", "not yet", "N checks"), a later section or a note in `docs/notes/` supersedes it: for the window and the display [notes/display.md](notes/display.md), for dialogs "Dialogs as Windows 98 draws them" below, for Windows the section "Windows", for what is run on which system [notes/ci.md](notes/ci.md) and the README. Counts of checks are as of writing; `make -C src/port test` prints today's. Documentation audit 2026-10.)*

Phase A runs the original executables in an emulator (Python Win32 layer, Unicorn). Phase B put native C into that run: the
engine functions written by hand, and everything the lifter (`tools/lift`) could turn into C from the machine code, hosted
inside the emulated game. Phase C removes the emulator: the whole program becomes C, the Win32 calls become a C layer over SDL2,
and the Python layer retires.

## The route: lift everything, then replace the lifted code with clean code

1. **Lift the whole program.** The lifter turns machine code into C one instruction at a time, on the same registers and the same
   guest memory, so it adds no new behaviour to be wrong. What it refused was mostly missing import signatures
   (`tools/lift/import_signatures.py` now has them: the stdcall counts of the Windows API, the C runtime's prototypes) and
   a few instruction forms (indirect calls, string instructions, `div`, `mul`, now done). Whole-program coverage, by function:

   | | functions | lift | bytes lifted |
   |---|---|---|---|
   | MAGIC.EXE | 1,854 | 1,801 (97%) | 947 of 1,084 KB (87%) |
   | DUEL.EXE | 1,830 | 1,639 (90%) | 709 of 956 KB (74%) |

   What is left in MAGIC.EXE (53): 36 jump tables whose bound the lifter misjudges, 9 functions that take or pass a register
   argument, 2 with x87 instructions, 3 indirect jumps that are not table dispatches, 1 `shld`. DUEL.EXE adds 67 calls of its own
   statically linked `sprintf` (variadic), 39 `int3` padding functions and 10 of `fscanf`.
2. **A standalone host.** A C program that maps the PE images into a guest address space, sets up the first thread, and runs the
   lifted entry point. Every import goes to a C function by name; one that does not exist yet reports itself and stops, so the
   run itself orders the work list.
3. **The Win32 layer in C** (`src/port`; it was `src/winlayer`, to come, when this was planned): kernel32 and the C runtime first (the start-up code needs them), then user32
   (window classes, windows, message queues, dialogs), gdi32 (device contexts, bitmaps, palettes, `BitBlt`), winmm and the two
   sound/video libraries, over SDL2. The Python layer (`tools/emu_spike/winemu`, 8,500 lines) is the specification: every rule in
   it was found by playing the game. Each function is checked by recording the calls the Python layer receives in a play session
   and replaying them against the C layer (arguments, results, window and bitmap state, pixels).
4. **Threads.** The game runs a main thread, an AI thread, a timer thread and short-lived threads, scheduled cooperatively in the
   emulator. The native host needs the same ordering guarantees (the search driver polls a flag the timer thread sets), so the first
   version runs guest threads as host threads under one lock, switching only at the points the emulator switches (blocking
   imports, `Sleep`, message waits).
5. **Replace lifted code with source.** Once the lifted program runs, any function can be swapped for a clean C version
   (written by hand from the game's code, as `src/native` does) and checked against its lifted twin, as Phase B does now. That is the
   port proper; the lifted code is scaffolding that shrinks.

## What is measured, what is not

Measured: the lift coverage above, that the generated C for all of MAGIC.EXE compiles (36 MB of C, 31 s at -O1), the Win32 surface
the game really calls (the emulator counts it: 227 distinct imports in the first 200 virtual seconds, up to a duel's start: 71 of user32, 61 of the C runtime,
58 of gdi32, 31 of kernel32, 2 of winmm, one each of five others), and how the time goes in a duel.

## Where it is

**Item 2 exists.** `src/port` is a C program with no emulator in it: it reserves the guest's 4 GB address space, maps `MAGIC.EXE` into it,
and runs the lifted program from its entry point. The lifter now takes 1,943 of the 2,002 functions of MAGIC.EXE's code (the C runtime's
start-up code, its import thunks and the unpacker's section included: the entry point uses `fs:[0]`, which is the thread information
block now, and the thunks are `jmp [import]`, which tail-call the import). Imports are found by name in the PE's own import table and
go to C functions (`kernel32.c`, `crt.c`; the C runtime's start-up, memory and string functions are done); one that is not implemented
stops the run and names itself, or with `PORT_STUB=1` returns 0 and is listed, which is how the work list is found. A callback
(`_initterm`'s constructors, later window procedures) is a call back into lifted code (`guest_call`).

    python3 tools/lift/gen_handlers.py --program magic --exe sources/installed/Magic/Program/MAGIC.EXE --out sources/generated/lift_magic_all --all --no-handlers
    make -C src/port                                  # the runtime (build/pentamoor-run) and a game module per program (build/game_magic.so ...), see "The runtime and the game module"
    PORT_STUB=1 src/port/build/pentamoor-run -m src/port/build/game_magic.so sources/installed/Magic/Program/MAGIC.EXE sources/installed/Magic/Program

The program now draws the title screen. It gets through the C start-up and into `WinMain`, registers the window class, creates the main
window and delivers `WM_CREATE` to the game's own (lifted) window procedure, which sets up its bitmaps, palette and fonts through the C
graphics layer, decompresses the title picture (see below) and paints it: a 640x480 screen that is **pixel for pixel the emulator's** (0 of
307,200 pixels differ, `python3 src/port/compare_screen.py`, with the same save folder behind both so the menu is in the same state).
`PORT_SHOT=file.ppm PORT_SHOT_AT=8` writes the composed screen at those seconds.

### The runtime and the game module

The program is two binaries, so that the part with no game-derived code can be built once and published, and only the part made from the player's own files is
built on the player's machine.

- **The runtime**, `src/port/build/pentamoor-run`: the PE loader, the thread scheduler, the Win32 layer, the SDL front end, sound and movies, everything in `src/port`
  except the lifted C. It is the same for MAGIC, DECK and DUEL, and it builds with no generated source present (`make -C src/port runtime`; CI does exactly that and also
  checks that no `lifted_*` function is in it).
- **A game module**, `src/port/build/game_magic.so` (`.dylib` on macOS), `game_deck`, `game_duel`: a shared library made only from `sources/generated/lift_<program>/*.c`
  (`lift_magic_all`, `lift_deck`, `lift_duel`: the program's functions, its DLLs and the list of them) plus `src/port/modglue.c`. `make -C src/port modules` builds them;
  they need no runtime and no SDL. Compiled `-O1 -fPIC -fvisibility=hidden`, plain C99.

`pentamoor-run [-m MODULE] PROGRAM.EXE [GAME-DIR]` opens the module (`-m`, or `$PENTAMOOR_MODULE`) and starts the program. **Neither side names a symbol of the other.**
The module exports one function, `pentamoor_game_init(const LiftHost *)`, and `gamemod.c` (the runtime's side) hands it one `LiftHost` (`src/native/lift_rt.h`): the guest's
address space, a pointer to one `LiftState` block, and the few runtime functions lifted code calls (`call`: a call out of a lifted function, `preempt`, `bad_jump`, and the
coverage build's three). The module keeps the pointers in its own hidden globals (`lift_guest`, `lift_S`, `lift_host`), and `lift_rt.h` defines the names the generated code
uses (`G`, `lift_in`, `lift_call`, `lift_ret_edx`, `lift_budget`, `X87`...) as those pointers' fields, so the lifter's output did not change and no file in `sources/generated` is edited. What
comes back is a `LiftGame` (`src/native/lift_tables.h`): the program's name, its table of lifted functions and their signatures, the import signatures and the lifted DLLs
(`LiftModule`). Both structs carry `LIFT_ABI` and their size, and a module built for another runtime is refused with a message. `LiftGame` and `LiftModule` also carry the **build id** of the file they were lifted from (`LIFT_ABI` 2; see "Build profiles").

`LiftState` also replaces what were thread-locals (`lift_ret_edx`, the x87 registers and control word): a library cannot name a thread-local of the executable without a
by-name symbol (and on macOS reaching one costs a call), so the block holds the running thread's copy and the scheduler swaps it when the baton passes (`set_cur` in `sched.c`; only
one guest thread runs at a time). `lift_in`, `lift_out` and the preemption budget were already plain globals shared by all guest threads.

Opening a library and finding a function are the two small functions `load_module` and `find_symbol` in `gamemod.c` (`plat_dlopen`/`plat_dlsym`: `dlopen`/`dlsym`, or
`LoadLibraryExA`/`GetProcAddress` on Windows). `make -C src/port static GEN=../../sources/generated/lift_magic_all BUILD=build_static` still makes the old single executable (the module's objects linked in;
`make GEN=... BUILD=...` on the command line means that too, as before), and `make -C src/port check-module` builds an empty module (`stubgame/`) and loads it, with no game files.

### Windows

The runtime builds and its tests run on Windows x86-64 with MSYS2's MinGW-w64 (gcc, winpthreads, SDL2 from pacman): CI's `windows` job runs `make -C src/port test`, `check-front`,
`all`, `check-module`, `check-run`, `check-program` and `check-build` in an MSYS2 MINGW64 shell (and `pytest tools/install` with a native Windows Python), and the build is also checked from macOS with `x86_64-w64-mingw32-gcc` and with `zig cc -target x86_64-windows-gnu`
(`python -m ziglang cc`). Nothing has been run on a real Windows machine with the game: the game's files are not in CI, so the title screen, input, sound and so on on Windows are
not verified; what is verified is the build, the unit tests (they make windows, draw, mix sound, read and write files, load the stub module and run lifted-style functions
in it), the SDL window starting on SDL's dummy drivers, and `check-program`: `stubgame/mkpe.c` writes a 1.5 KB PE32 program (no game code in it), `pentamoor-run.exe` maps it,
resolves its kernel32 imports, loads the stub DLL and runs the lifted-style function at the PE's entry point, which writes a file through `CreateFileA`/`WriteFile` into the
overlay (made on the way) and ends with `ExitProcess(7)`; the check is the exit status and that the file is exactly the 24 bytes written (so no text-mode translation).

Everything that is not the same on Windows is behind `src/port/plat.h`, implemented in `plat_posix.c` and `plat_win.c` (the only file that includes `<windows.h>`), and a handful of
`#ifdef _WIN32` spots where it is a different spelling of one call. What each part does:

- **The guest's 4 GB.** POSIX `mmap`s it. Windows `VirtualAlloc`s the range with `MEM_RESERVE` (no commit charge) at whatever base it gives: the guest's addresses are offsets from
  `G`, and the module is handed `G` through `LiftHost`, so the base does not matter. A page is committed (zero, as `mmap` gives it) by a vectored exception handler the first time
  anything touches it, one megabyte at a time. A system call handed a guest address does not fault, it fails (`ReadFile` into reserved memory is `ERROR_NOACCESS`), so the few places
  that pass `G + addr` to `read`/`write` call `plat_guest_commit(addr, len)` first (`kernel32.c` ReadFile, WriteFile and MapViewOfFile, `stdio.c` `_read`, `_write`; it is a no-op
  on POSIX). Any new code that gives guest memory to a system call has to do the same.
- **The module.** `LoadLibraryExA` (with the module's own folder on the search path) and `GetProcAddress` behind `plat_dlopen`/`plat_dlsym`. `modglue.c` exports `pentamoor_game_init`
  with `__declspec(dllexport)`, so it is the only export. The module is linked `-shared -static-libgcc` and needs only the C runtime DLLs of Windows.
- **Threads.** winpthreads, unchanged: `sched.c`'s baton, `front.c`, `sound.c` and `front_sdl.c` use `pthread_*` and `pthread_cond_timedwait` as before. They are linked statically
  (`-Wl,-Bstatic,--whole-archive -lwinpthread`: the whole archive, because its thread-exit hook is in an object nothing names), so a release needs no `libwinpthread-1.dll`. Thread-locals
  (`__thread`) work in MinGW. The stack is 8 MB for every thread (`-Wl,--stack`). `plat_init` asks for a 1 ms timer (`timeBeginPeriod`) so that `usleep`/`Sleep` of a few milliseconds is that.
- **Files.** `paths.c` joins with `/`, which Windows accepts, and `PLAT_IS_SEP` makes `mkdir -p` split on `\` as well; the game's `C:\Magic\...` names resolve under the game
  folder and the overlay as before (the Windows file system matches names without regard to case, so the case-sensitive checks of `test_paths` skip, as on macOS). Every `open()` of a
  game file passes `O_BINARY` (a no-op elsewhere), because the Windows C library would otherwise turn `\r\n` into `\n`; `fopen` calls say `"rb"`/`"wb"`. `access`, `stat`, `unlink`
  and `opendir` are MinGW's; `mkdir` (one argument), `localtime_r`, "same file" (`st_ino` is 0 there) and `fnmatch` (`controls.c` has its own matcher, `port_glob`) are replaced.
- **Time.** `clock_gettime(CLOCK_MONOTONIC)` and `usleep` come with MinGW (winpthreads); `GetTickCount` is still `port_now_ms()`.
- **Signals.** `front_sdl.c` installs `signal(SIGINT/SIGTERM/SIGBREAK)` instead of `sigaction`; the handler sets the same flag. `execinfo.h` (the coverage build's backtrace) is guarded
  and absent on Windows. SDL's own signal handlers stay off.
- **`PORT_CONTROL`.** There is no `mkfifo`: on Windows `PORT_CONTROL=file` is an ordinary file (made if missing) that is read from its start and as it grows, so
  `echo shot a.ppm >> file` does what writing into the FIFO does.
- **ffmpeg** (Indeo clips): found on `PATH` (`;` separated, `ffmpeg.exe`) or in `C:\ffmpeg\bin`, started with `_popen(..., "rb")` through `cmd.exe` (the command is double-quoted and
  `NUL` replaces `/dev/null`). `_popen` needs a console, so a build with `-mwindows` has to give it one (or call `CreateProcess` with pipes) before video works.
- **LLP64.** `long` is 32 bits there: the palette searches in `gdi.c` started their best distance at `1L << 40`, which is now `1L << 30`; the rest of `src/port` uses fixed-size types.
- **Build.** `make -C src/port` in an MSYS2 MINGW64 shell (`pacman -S make mingw-w64-x86_64-gcc mingw-w64-x86_64-SDL2`) makes `build/pentamoor-run.exe`, `build/game_<program>.dll`
  and the tests (`.exe`). The Makefile takes `sdl2-config`'s flags without `-lmingw32 -lSDL2main -mwindows -Dmain=SDL_main` (the runtime has its own `main` and is a console program, so its
  log has somewhere to go), adds `-D__USE_MINGW_ANSI_STDIO=1`, and builds modules without `-fPIC -fvisibility=hidden` (not needed on PE). A cross build: `make WINDOWS=1 CC=x86_64-w64-mingw32-gcc SDL_CFLAGS=... SDL_LIBS=...`.
  The runtime needs `SDL2.dll` beside it (and nothing else of MinGW's).
- **Launcher.** `pentamoor.bat` does what `./pentamoor` does (`pentamoor-run.exe` and `game_<program>.dll` beside it, else under `src\port\build`); `./pentamoor` also works in an MSYS2 shell.
  It is also the double-click entry of a release: with no game installed it asks, then runs `pentamoor-install.bat` (which asks for the `.iso`), and an `.iso` dropped on it is installed first.
  Both batch files are shipped with CRLF line ends (`.gitattributes`, and `package.py` converts again), because `cmd.exe` mis-reads labels in LF-only files.
- **A release on Windows** (see "Releases and the installer" below) carries `SDL2.dll` beside `pentamoor-run.exe`, the embeddable Python 3.13 and the Zig compiler, so the user needs nothing installed.
  CI builds it (the zip is 113 MB with Zig; 19,000 files), unpacks it, and has the unpacked copy build the stub module with its own Zig and its own Python on a PATH of only Windows' folders and
  load it into its own `pentamoor-run.exe` (a green run of the `release archives / windows-x86_64` job; that check takes about 2.5 minutes, most of it unpacking and Zig building its caches on the first compile).
  The 42 MB `handlers_gen.c` has not been compiled with the bundled Zig on Windows by this installer (it was, by hand, from macOS, `-target x86_64-windows-gnu`), and nobody has run the game there.

The lifted C needs nothing GNU-specific: the whole of `lift_magic_all` (42 MB `handlers_gen.c`, `statwin_gen.c`, `deckdll_gen.c`) compiles with `x86_64-w64-mingw32-gcc 16.2 -O1` into a
5.9 MB `game_magic.dll` that exports only `pentamoor_game_init`, and with `zig cc -target x86_64-windows-gnu -O1` (zig 0.17) in under a minute; neither has been *run*. The stub module
(`stubgame/handlers_gen.c`) has three functions written in the lifter's style (loop back-edges, `lift_call`, the x87 stack, `lift_ret_edx`) that `test_module.c` runs through the
loaded module, so CI compiles and runs lifted-style C on Windows without the game.

Not verified, because nothing here ran on Windows with the game: the game itself on Windows (real window, DPI scaling, keyboard layouts, the audio device), `LoadLibrary` of a 40+ MB
module, the vectored-exception commit under the lifted code's real memory pattern (it is exercised by the unit tests, whose guest-memory use is small), `_popen`/ffmpeg with real
clips, and Windows with a non-ASCII user name (host paths are passed to the C library as bytes in the ANSI code page; `fopen` of a UTF-8 name will not open).

### Releases and the installer

What is published is the runtime and the tools; the game modules are always built on the user's machine. The pieces (CONTRIBUTING.md, "Making a release", has the workflow side):

- **`tools/install/install.py`** is one program in a checkout and in a release (`Layout` tells them apart: no `src/port/Makefile` means a release). It reads the disc, extracts the game, and with `--build`
  (a release: always; `pentamoor-install` passes it) lifts and compiles. In a checkout `--build` is as before (the lifter, then `make -C src/port all`); `--modules` builds only the game modules with the
  Python builder. `--check` reports what is ready, `--self-test` builds the stub module and has the runtime load it, `--compiler`, `--no-download`, `--yes`, `--jobs`, `--clean`, `--force` as in `--help`.
- **Lifting** (`liftrun.py`): the commands of `tools/lift/lift_all.sh` as data (a test keeps them equal), run in child Pythons that put the lifter's folder and `tools/pydeps` on `sys.path` themselves,
  so nothing needs `sh`, `PYTHONPATH` or the script's folder being searched (the embeddable Python ignores both). The three programs are lifted at once. `sources/generated/.lifted` holds a fingerprint
  of what each was lifted from (the game's programs, `tools/lift/*.py`, `layout.c`), so running the installer again, or after a failed compile, does not lift again.
- **Python packages** (pefile, capstone): a release carries them in `tools/pydeps` for its platform (pip `--platform`, so the archive is the same wherever it was packed). A checkout is expected to have
  them; if they are missing, the installer asks and runs `pip install --target tools/pydeps` (no other package on the machine changes; PEP 668 does not block `--target`). With no pip and no network it says what to run.
- **The compiler** (`modbuild.find_compiler`), in this order: `$PENTAMOOR_CC` or `--compiler` (a command, or the word `zig`); the first of `cc`, `gcc`, `clang` on the PATH that really compiles a probe file
  and links a 64-bit shared library (so macOS's `/usr/bin/cc` stub, which only asks to install the command line tools, and a 32-bit MinGW are passed over; `xcode-select -p` is asked first); the Zig in `tools/local/ziglang`
  (bundled in the Windows release, or fetched before); else Zig is downloaded: PyPI's `ziglang` wheel for the machine (`zigdl.py`: file URL and SHA-256 per system written down in the source, 0.16.0, about 95 MB,
  400 MB unpacked), fetched with `urllib` (so no pip is needed), checked, and unpacked into `tools/local`, after a yes (or `--yes`; with no terminal and no `--yes` the answer is no). Zig's caches go to
  `tools/local/zig-cache`. 0.17.0 was a week old and had no Windows wheel, so 0.16.0 is pinned.
- **The module build** (`modbuild.build_modules`): what the Makefile's module rules do. Each `*_gen.c` of a program is compiled by itself (`-std=gnu99 -O1 -w -fPIC -fvisibility=hidden -DLIFT_BACKEND_FLAT4G -DLIFT_PREEMPT
  -DLIFT_MODULE -I src/native`; no `-fPIC`/visibility on Windows), plus `modglue.c` and `modules_none.c` when the lifter wrote no module list, up to 8 at a time, biggest first, and an object newer than its source and
  the two headers is kept; then the objects are linked (`-shared`, `-dynamiclib` on macOS, `-shared -static-libgcc` for MinGW) with `-lm`. It prints `[n/total] percent file (time)` as each file ends and, while only
  big ones are running, a line every 20 seconds. Objects go to `sources/build/<program>/`, the module to the folder of the runtime. Afterwards each module is loaded into the runtime to see it is the right kind
  (the runtime's "cannot open" for a program that is not there is the sign it loaded). The wall clock is set by `handlers_gen.c` of MAGIC (42 MB), which is one file: more processors do not shorten it.
- **Timings** (this Mac, 10 cores, `/usr/bin/python3` 3.9, a release folder, the real disc): extract 80 s, lift 28 s, compile 28 s with Apple clang -O1 (96 MB of C in 13 files), link and load check a few seconds: **2 min 18 s**
  from the ISO to a playable game. The same compile with the downloaded Zig (`--compiler zig`; the download and unpacking took 6 s): 62 s, and the title screen it gives is identical to the clang one (0 of 786,432 pixels differ).
  Linux (the CachyOS box, 16 cores shared with other work, Python 3.14, gcc 16.2, the same release folder): extract 47 s, lift 39 s, compile 1 min 10 s: **2 min 38 s** in all; with the downloaded Zig 0.16
  (`--compiler zig`, download and unpacking included) the compile is 1 min 50 s and the whole run 2 min 06 s with the lift skipped; the title screen from the gcc-built and the Zig-built modules is
  byte-identical, and identical to the macOS one. An install from a source checkout (`install.py ... --build`, make) took about the same. These are one run each, on fast machines.
- **The Steam Deck** (`docs/notes/steamdeck.md`): a fourth archive, `pentamoor-<version>-steamdeck.tar.gz`, is the Linux one plus `tools/steamdeck/` and two `.desktop` icons (`package.py --platform steamdeck`, built by the
  Linux job of `package.yml` from the same runtime, checked by `check_archive.py` including `check_steamdeck`). `install-gui.sh` is the installer without a terminal (kdialog or zenity, a progress bar from
  `progress.py` reading the installer's own text, or a Konsole window; it passes `--yes --clean`, so SteamOS's missing compiler means Zig is downloaded into the folder), `add-to-steam.py` writes the shortcut
  into `userdata/<id>/config/shortcuts.vdf` (binary VDF, read back byte for byte before it is touched, a backup kept, refused while Steam runs), a menu entry and the Steam Input layout. The program itself, on a Deck or
  in Gamescope: full screen by default with a whole-number scale where that loses little (`steamdeck.c`), the pad heard while Steam's overlay has the focus, text input on only while a text field has the focus, and
  typed text that arrives with no key turned into the key presses that type it (`textin.c`).
- **Launchers** (`pentamoor`, `pentamoor.bat`): they look for `pentamoor-run` and `game_*` beside themselves (a release) before `src/port/build`. When the game or its module is missing and there is a terminal and
  `pentamoor-install` beside them, they offer to run it (the installer asks for the `.iso`: paste or drop the path; quotes and `\ ` are cleaned); an `.iso` given as the first argument (dropped on the launcher) is installed first.
  Without a terminal they print the command to run. On Linux a missing `libSDL2` is named, with the package to install.
- **macOS runtime** (`tools/release/build_macos.sh`): SDL2 2.32.10 from its pinned source (checksum checked) is built static for arm64 and x86-64 (`./configure --host=<arch>-apple-darwin`, cross-compiled with
  `-arch`), `make runtime` links it with `sdl2-config --static-libs` (system frameworks only: `otool -L` shows nothing of Homebrew's), the halves are joined with `lipo` and signed ad hoc. brew's `sdl2` is
  now `sdl2-compat` (a shim that loads SDL3 at run time), which cannot be bundled by copying one dylib, hence the source build. The x86-64 half is built and linked but nothing here can run it (no Rosetta).
- **Linux runtime**: built on `ubuntu-22.04` against the system's SDL2 (`libSDL2-2.0.so.0`, dynamic: SDL loads X11, Wayland, Pulse and so on itself, so a bundled copy would be stuck with its build's
  versions). `libsdl2` is a stated requirement; the launcher names it if it is missing. A static libSDL2 was not tried.
- **What is checked without the game**: `test_release.py` (compiler choice with fake `which` and probe, the flags equal to the Makefile's, progress and incremental behaviour, the error text, Zig's
  checksum and unpacking including a path-escaping wheel, the lifter command lines, the archive layout and `check_archive.py`'s refusals, the launcher with a dropped ISO) and `check_archive.py` on a real archive in CI.

### Build profiles

The port is made from one build of the game, the retail disc's version 1.0, and it is keyed to it in two ways: the lifted C is that build's machine code, and `src/port` hooks, overrides and writes the game at fixed addresses (the frame
pacing, the D-pad's reading of the screens, the (Y/N) questions, the picture decompressor, the screen size). In another build those addresses name something else; in Spells of the Ancients 2.x the two screen-size globals are inside code
(`docs/notes/sota-comparison.md`: 0 of 54 addresses survive), and until the profiles the hooks looked at the program's *name* and nothing else, so on another build they would have silently not fired or written into the wrong place.
Now each build is a **profile**: a row of a table, found by the **build id** of the file.

- **The build id** is the SHA-256 of the file (a program or a library), 64 lower-case hex characters. The whole file, not its code alone: the hooks also read and write the program's data at fixed addresses, any byte that differs can move them, it costs one pass
  over a megabyte, needs no PE parsing and can be checked with `sha256sum`. They are the same ids the installer has always checked the extracted game against (`tools/lift/builds.py`, which the lifter, the installer and a test share).
- **The lifter writes the id of the file it lifted** into the module: `LIFT_BUILD_ID` of `handlers_gen.c` (`LiftGame.build_id`) and a field of each library's record (`LiftModule.build_id`); `LIFT_ABI` is 2. For version 1.0 that is the only change in the generated C
  (one added line in each program's `handlers_gen.c`, and in each library's file one added line and the library's record, which gains a last field; the rest of the three generated folders is byte for byte what the lifter wrote before). A module without one (an older lifter's, or hand-made) has no build.
- **The runtime hashes the file it loads** (`profile_init` in `main.c`, before any hook is installed; `module_map` in `modules.c` for each library before it is mapped), checks that it is the file the module was lifted from, and looks the id up in the table
  (`src/port/profile.c`). MAGSND.DLL and MAGVID.DLL are not checked: the port provides them itself (`sound.c`, `video.c`, exports by name) and never loads the files.
- **The profile** (`profile.h`, `BuildProfile`) holds every address of the game that `src/port` uses, and the hook installers read `profile->field` and do nothing when theirs is 0. Its fields, by who uses them:

  | group | fields | used by |
  |---|---|---|
  | identity | `id`, `build` ("v1.0"), `file`, `program` ("MAGIC", "DUEL", "DECK"; "" for a library), `base` (a library: where it is lifted for) | the lookup, the messages |
  | `lzw` | `header`, `read`, `read2` (entries), `block` (the dictionary and the state behind it), `in_ptr`, `in_end`, `refill`, `callback`; the offsets inside the block are `LZW_*` in `profile.h` | `lzw.c`: MAGIC.EXE, DUEL.EXE, DECKDLL.DLL |
  | `pace` | `tick_fn` (overridden), `ticks`, `frame_ret`, `map_loop` | `pace.c` |
  | `buttons` | `pass`, `mouse_var`, `snapshot`, `ctx_cur`, `ctx_count`, `ctx_ptrs`, the six offsets in a record | `pace.c`, `screens.c` |
  | `textmenu`, `buycards`, `clues` | the loops' code ranges, the text menu's seven globals, the cards' ids, the frame offsets of the loops' locals | `screens.c` |
  | `title` | `loop` (the title menu's loop, the one screen where Escape leaves the game with no question) | `screens.c`, `main.c` (`pad_set_back_guard`) |
  | `keys` | `wait`, `pop`, `wait_loop_ret`, the (Y/N) `sites`, `name_loop` | `yesno.c`, `textfocus.c` |
  | `display` | `width`, `height` (the globals the screen size is written into) | `main.c` through `profile_write_screen_size` |

  The table has five rows, for version 1.0: MAGIC.EXE (all the groups), DUEL.EXE (`lzw`), DECK.EXE (nothing), DECKDLL.DLL (`lzw`, at its base 0x32000000) and STATWIN.DLL (nothing; it is there so that a library of another build is refused). Their values are exactly the
  literals the sources had; `test_profile.c` compares every field with the old literal, and `test_lift.py` fails when a game address is written in the code of `src/port` anywhere but `profile.c` (comments may name them).
- **An unknown build** (an id no row has, a module without an id, or a file that is not the one the module was lifted from) **is refused**: the runtime prints
  `pentamoor: <file> is build <id>, which this version does not support (supported: v1.0 MAGIC.EXE)` and ends with **exit status 3**, before anything of the game has run. The game cannot run without the picture decompressor override, so an unknown build could not get past its
  first picture anyway. **`PORT_UNKNOWN_BUILD=1`** starts it anyway for research, with a warning and `PROFILE_NONE` as the profile: no pre-call hook, no override and no write is made (`test_profile.c` counts them: `port_hook_count()` and `profile_guest_writes` stay 0; `make -C src/port check-build` runs
  it on a real program through the loader, `check-program` runs the stub program with the switch).
- **The installer** says which build it found: `install.py --check` prints `build:  v1.0 (MAGIC.EXE, DUEL.EXE, ...: the retail disc)` or the files that are of no known build, and the warning after extracting names them and says that the runtime will refuse them.
- **What the profile does not hold**: `src/native/layout.c` (the hand-written engine's function table) is the lifter's input and is keyed by the program's name (`LAYOUT_MAGIC`, `LAYOUT_DUEL`; `tools/lift/gen_handlers.py` `native_entries`), not by build; the strides of the engine's records
  (`src/native/engine.h`); the geometry of the 640x480 layouts the D-pad's clue rows and text menu assume (`screens.c`); and the window class names the duel's navigation looks for (`navwm.c`, `MAGICGAME_*`). A second build needs those looked at too. The guest's own address plan
  (heap, stacks, import stubs: `guest.c`, `sched.c`, `pe.c`) is the runtime's, not the game's.

To add a build: CONTRIBUTING.md, "Adding a build".

### The window manager (item 3, first part)

`src/port` now has the Python layer's USER32 in C, with the same rules: window classes and windows (stacking order, per-window extra bytes,
styles, geometry and the messages `CreateWindow`, `ShowWindow` and `MoveWindow` send), the message queue with per-thread ownership, `SendMessage`
across threads (the sender waits until the owner pumps), `PostQuitMessage` per thread, timers, the pump (`WM_PAINT` and `WM_TIMER`
synthesized, owner-draw buttons painted by their parent, a polling thread backing off), focus and capture, the built-in controls (buttons,
list and combo boxes, scroll bars), dialogs from the PE's `DLGTEMPLATE` resources with the modal loop, popup menus, and the host's mouse and
keyboard as messages (the window under the pointer by stacking order, double clicks, a built-in button's click as `WM_COMMAND`, Enter
and Escape for a dialog). The guest's threads are host threads with a baton (`sched.c`): they switch where the original machine did and
every 200,000 backward jumps in lifted code (`LIFT_BACKEDGE`), so a thread that spins on a flag cannot hold the machine.

`make -C src/port test` runs 70 checks of it without the game (host functions stand in for window procedures): creation messages in
order, child windows, geometry and coordinates, stacking, the queue, `WM_PAINT` once, timers, a cross-thread `SendMessage`, mouse routing and
double clicks, list boxes, scroll bars, rectangles, a dialog from a hand-built template, and a popup menu picked from another thread.

### The graphics layer (item 3, second part)

gdi32 in C, with the Python layer's model: a window's surface holds palette indices (the display is 8-bit) and a direct-colour overlay for
24-bit sources and RGB fills; the system palette is shared with the realized palette so `AnimatePalette` shows at once; bitmaps are device
bitmaps (indices, a 1-bit plane for monochrome ones) or DIB sections whose pixels live in the guest's memory where the game writes them itself.
Device contexts with mapping modes (isotropic and anisotropic scale), origins, clip rectangles, `SaveDC`/`RestoreDC`; `BitBlt`/`StretchBlt`
that copy indices when both sides are indices and colours otherwise, with the combining raster operations the game's bitmap fonts use and a box
filter for the halftone shrink; `SetDIBitsToDevice`, `SetDIBits`, DIB colour tables and `DIB_PAL_COLORS`; pens, brushes (solid and pattern),
rectangles, ellipses, lines, pixels; regions as rectangles; user32's `FillRect`, `FrameRect` and `DrawText`. Text is drawn from the game's own
TrueType files (`AddFontResource`) by a rasterizer of ours (`font.c`: glyf outlines, exact area coverage, whole-pixel advances and kerning; no
hinting, so glyph edges differ slightly from a font library's). The compositor (`compose.c`) paints the window tree and what Windows draws that the
game does not (built-in push buttons, dialogs, popup menus).

The picture decompressor is **hand-written C** (`lzw.c`), not lifted: the code that expands the game's pictures (the `MPS_CODE` section) keeps
decoded strings on a private stack it switches to with `xchg esp`, returns through `jmp ebp`, and passes arguments in registers, none of which the
lifter can express. It is LZW with a variable code width and a run-length escape; the port keeps its state at the same guest addresses, and the
title screen being pixel-identical is the check that it decodes the same.

`make -C src/port test` also runs 39 checks of the graphics layer (DIB sections, raster operations, palettes and palette animation, mapping modes,
clipping, monochrome bitmaps, stretching, text).

The lifter found 16 functions the function table of the time did not list (reached by call or by a stored function pointer, such as the decompressor's refill
callback) and took them too: 1,954 of 2,018 functions. (It finds every function in the program's own code now: `tools/lift/fnscan.py`.)

### The window and input (item 3, third part)

`src/port` opens an SDL2 window (1024x768 by default; how it is sized, scaled and made full screen is [notes/display.md](notes/display.md); the mouse is in screen pixels whatever the size) and the game takes the mouse and keyboard
from it. SDL wants the main thread for the window, so the game runs on a new thread and the window half (`front_sdl.c`) only queues what it
sees; the guest half (`front.c`) serves the queue on whichever guest thread holds the baton, wherever the baton passes and wherever the game
waits for a message, and publishes a composed frame up to 30 times a second. So the guest's state is touched by one thread at a time and the
window never touches it. A pressed button or key is held for 40 ms before the next event is delivered (the game polls their state, and a click
that arrives as press and release together would be missed). Keys are the game's virtual-key and scan codes; characters come from SDL's text
input, so the layout and Shift decide. Closing the window sends `WM_CLOSE` to the game's main window; a second close, or five seconds without
an exit, ends the program. `PORT_HEADLESS=1` runs without a window (the screenshot comparison does).

    src/port/build/pentamoor-run -m src/port/build/game_magic.so sources/installed/Magic/Program/MAGIC.EXE
    PORT_SCRIPT="8:move 330 308;9:down;9.2:up;14:shot /tmp/a.ppm;20:quit" src/port/build/pentamoor-run -m ...

On a Steam Deck (or in Gamescope) the window starts full screen with a scale chosen by `view_scale`, SDL's text input follows the focus of a text field, and text with no key is typed (`docs/notes/steamdeck.md`).

A game controller is a mouse and a keyboard to the game too: `pad.c` (no SDL, no game: the dead zone and curve, the cursor's speed in screen widths per second, what each button presses) and the glue in `front_sdl.c`
(controller events in, the cursor drawn into the shown frame, `PORT_NOPAD=1` off, `PORT_FULLSCREEN=1`); the `pad` steps below drive it without a device. `docs/notes/controller.md` has the button map, the walking and what is not tested.

`PORT_SCRIPT` is a test driver: timed steps (`move x y`, `down [x y]`, `up`, `rdown`, `rup`, `key NAME`, `text abc`, `pad ...`, `shot FILE`, `quit`) pushed as
SDL events through the same path as the real ones; `shot` writes what the window shows. With it, the native program goes from the title
screen through "Start New Game" to the colour and portrait screens, and takes the name typed there. `make -C src/port test` checks the
queue, the hold on a press and frame publication (7 more checks).

### The lifter's gaps, and the overworld

The lifter now takes 2,001 of 2,018 functions. Three things closed the rest of what the first run into the game hit: the compiler's two-level
`switch` (a byte table indexes the table of addresses; the second table is only as long as the largest byte says, which the bound check does not
give), the two runtime helpers that take registers (`_chkstk`, `_allshl`, replaced by inline code found by their machine code), and the few
x87 instructions the game uses to move or clear eight bytes (`fld`/`fst`/`fstp` of a qword and `fldz`, kept as raw bits so a copy is exact),
with `shld`/`shrd`. What does not lift: the hand-written LZW in `MPS_CODE` (done in C), the helpers themselves, and five addresses the discovery
heuristics found that are not functions.

With that the native program goes from the title screen through new game, colour, portrait and name to the overworld: the map, the wizard, the
towns, and the encounter dialogs. (The first overworld frame was a blank parchment with a black box. It was not a drawing bug: the guest's
threads were given stacks by `tid % 120`, and the game's timer callbacks start a new thread every few milliseconds, so after 120 of them a new
thread was handed the stack of the long-lived game thread and wrote its frames over its locals. A thread now takes the lowest stack no live
thread is on; `test_wm` spawns 300 short threads next to a long one and checks they never share a stack.)

Debugging aids, all environment variables of `src/port/build/pentamoor-run`: `PORT_CALLS=1` (every import called, with counts, at exit), `PORT_WHO=GetDC,0x0050db10`
(who called these imports or lifted functions, by return address), `PORT_WHO_LIVE=1` (the same, as it happens), `PORT_TRACE_FN=0xADDR` (the
arguments of each call of a lifted function), `PORT_BLITLOG=1` (every `BitBlt` and `StretchBlt`), `PORT_TRACE=1` (file and path lookups), and in
`PORT_SCRIPT` the step `dump ADDR LENGTH FILE` (raw guest memory). A coverage build, `make -C src/port BUILD=build_cov EXTRA=-DLIFT_TRACE` (the runtime and the module both get the flag),
adds `PORT_COV=file` (the lifted instructions that ran, in order), `PORT_WATCH=lo-hi` or `PORT_WATCH=pc:ADDR` (every write to a stretch of guest
memory, with the instruction that made it, found the stack collision) and a check that each lifted function returns with `esp` where it was entered.

### The game's DLLs

`LoadLibraryA` finds the game's libraries two ways.

- **Lifted.** `tools/lift/gen_dll.py` lifts a DLL for one base address. The functions are found from the code:
  the entry point and the exports, every function they call, the linker's jump table (a run of `jmp rel32` at the start of the code: a function that
  starts with a jump is a thunk), and every address stored as a function pointer, in the code or in the data sections (vtables, callback tables).
  The lifter lets a DLL function read the registers it is entered with (`this` in `ecx` in C++ methods): lifted callers pass them. `pe.c` maps the
  file at that base and applies its base relocations, binds its imports like the executable's, and `LoadLibraryA` calls its `DllMain`.
  `GetProcAddress` reads the export table.

      python3 tools/lift/gen_dll.py --dll sources/installed/Magic/Program/STATWIN.DLL --base 0x30000000 --out sources/generated/lift_magic_all
      python3 tools/lift/gen_dll.py --finish --out sources/generated/lift_magic_all      # modules_gen.c, the list the loader reads

  STATWIN.DLL (the statistics window, 334 functions) is lifted this way. The Makefile builds every `*_gen.c` of the folder. MAGVID.DLL (328
  functions) and DECKDLL.DLL lift as well (DECKDLL is for DECK.EXE).
- **Host.** MAGSND.DLL (sound: it needs DirectSound, the multimedia file I/O and AVIFile) and MAGVID.DLL (video) are tables of C functions
  (`sound.c`, `video.c`; ports of winemu/magsnd.py and movie.py). Sound and video are real (next sections).

With STATWIN loaded, "Resume Game" shows the saved encounter exactly as the emulator does, and "Duel a Sorcerer" starts a duel: the board, the coin
toss, the mulligan and ante dialogs. (The dialogs were the compositor's plain stand-ins for the game's dialog templates, as in the emulator; they are drawn the way Windows 98 draws them now, "Dialogs as Windows 98 draws them" below.)

### A duel, played through

The native program plays a whole duel, from the encounter to the result and back to the encounter screen: coin toss, mulligan and ante dialogs, the
untap, upkeep, draw, main, combat (assign attackers, assign blockers, damage), discard and end-of-turn phases on both sides, land and spell casting with
mana tapped by clicking lands, the opponent's own turns, life going from 10 to -4 ("Sorcerer won": the game was played quickly, one land and a spell or two a turn, with
nothing done about the Goblin Balloon Brigade), and the result dialog. It was played the way a person does it, with the mouse, through `PORT_CONTROL`:

    mkfifo /tmp/magic_ctl; PORT_CONTROL=/tmp/magic_ctl src/port/build/pentamoor-run -m src/port/build/game_magic.so MAGIC.EXE &
    echo "click 330 390" > /tmp/magic_ctl; echo "shot /tmp/a.ppm" > /tmp/magic_ctl; echo windows > /tmp/magic_ctl

(`PORT_CONTROL` is a named pipe of the same steps `PORT_SCRIPT` takes, without times: `click`, `move`, `down`, `up`, `key`, `text`, `shot`, `windows` (the
window tree and the message queue, to stderr), `hit X Y` (which window a click there would reach), `dump`, `quit`.)

Three bugs came out of it (this and the overworld's), none of them in the game:
- A font ("Select an object's font", `GetObjectA` on a font handle) came back unfilled: the game builds its bold dialog font from it, so the new font had a
  height of 137 million pixels and the glyph rasterizer tried to draw a 60-million-pixel square (a crash, then a hang). `GetObjectA` now fills a LOGFONT from
  a font handle, and the rasterizer refuses a glyph no font has.
- Hiding a window did not send it `WM_SHOWWINDOW(0)`. The game's attack window hides its sword-and-shield window from that message, so after combat the
  "assign attackers" panel stayed on top and covered the Done button and the creatures: the duel could not go on.
- (Before it, in the overworld: the thread stacks.)

Not yet: the rest of the lifter gaps (the five bogus addresses, the register-argument fragments). (Done since: [notes/lifter-gaps.md](notes/lifter-gaps.md): the five were not functions, the others are covered another way.)

### Sound

MAGSND.DLL's 27 exports are `sound.c`, with a mixer behind them. `LoadSnd` reads a WAV (8 or 16 bit PCM, mono or stereo, any rate: the game's 197 files are
22.05 kHz mostly, two are 44.1 kHz) into a slot; `PlaySnd(id, opts)` starts a voice on it with the game's option block: volume 0..400, pitch (the
playback rate: 22050 plays it as recorded whatever the file's rate), pan -400..400, and a loop flag. A slot plays one voice at a time; `StopSnd`,
`SetVol`, `SetPan`, `SetPitch`, `GetVol`/`GetPan`/`GetPitch` and `GetSndTime` work on it, and `GetSndState` says whether it is still playing, which is
what the game polls to wait for a sound to end. The mixer (linear interpolation, volume and pan, sums clamped) is pulled by SDL's audio thread
(`front_sdl.c`, 22.05 kHz stereo, 1,024-sample buffer). With no audio device, or `PORT_MUTE=1`, or headless, the sounds are consumed against the clock
instead, so a wait for a sound still ends when the sound would have. `PORT_AUDIO_DUMP=file.raw` writes what the device was given (signed 16 bit stereo,
22,050 Hz): with it the title screen's button click and the intro music show up at the second they start (9 s), and the track ends after its 20 s.
`make -C src/port test` runs 45 checks of the mixer. Not done: the sound's DirectSound-only details (3D, effects), and I have not listened to it: the checks are on the samples, not on how it sounds.

**There is no MIDI.** `PlayMidiFile` is an empty stub in MAGSND.DLL (it returns 0), nothing calls it, and no `.mid` file exists on the install or the disc. The music is
**WAV files on the game CD** (`Sound\LOCMUS0..19.WAV` for the overworld, the castle themes, `DUELTUNE.WAV`, `WINGAME.WAV`, ...), which the retail install does not copy; the game
opens them as `x:\sound\...` on the CD drive. The installer (`tools/install/install.py`) copies them from your disc image (it reads the `.iso` without mounting it) into the game's folder, `Magic/Program/Sound`
(`tools/emu_spike/install_cd_music.py --native` does it to `port_overlay/Program/Sound` for the emulator's sake); without them the game runs silent and the music calls fail quietly. Played with them, the audio the device is given
holds the file's samples exactly (`PORT_AUDIO_DUMP`: the first 1,000 samples of `DUELTUNE.WAV` found in the dump with a ratio of 1.0 and no difference).

What the DLL does, as read from its code, and `sound.c` now follows:
- **Slots and the game's numbers.** `LoadSnd(path, slot, info)` into a slot that holds a sound does nothing and succeeds (the old sound stays); the game unloads first when it
  means to replace. `info` dword 6 is the game's own number for the sound; `IsSndLoaded(number, *slot)` answers 1 and the slot when a sound with that number is loaded
  (otherwise 0, `*slot` untouched). `GetLRUSnd(*slot, lo, hi)` gives a free slot in the range (answer 1) or the one played least (answer 0, and the game unloads it). The game
  keeps its on-demand effects (0x14 and up: the shuffle, the coin toss, ...) in a few slots this way. Before, `IsSndLoaded` answered through the pointer, which made every on-demand
  effect load into slot 0 over the preloaded one: the coin toss now plays `Toss.wav` from slot 0x2f and the shuffle from slot 20.
- **Markers are the file's sampler loops.** The WAVs carry a `smpl` chunk (one loop; for nearly all of them the whole file, `BLAND1.WAV` has the loop 4422..68720 after an
  intro). A looping voice plays to the end of the loop and goes round it. `SetSndMarker(id, n)` answers 5 for a loop the file does not have and 1 for a sound that is not loaded;
  `PlaySndMarker(id, n)` starts the sound again at the start of its loop n with the volume and pan it had (the game calls it when the party enters a town, after `SetVol(0x10, 400)`).


### The deck builder (DECK.EXE, and DECKDLL.DLL inside the game)

DECKDLL.DLL is lifted like STATWIN (1,013 functions, base 0x32000000) and is part of the game's own build: MAGIC.EXE imports `DeckBuilderMain` from it, and
`pe.c` binds that import straight to the lifted export. The DLL reaches back into its host through `GetProcAddress(GetModuleHandle(NULL), "CardIDFromType")`,
`"Gold"`, `"deck"` and the rest, which MAGIC.EXE exports. The loader keeps each image's export table, so they resolve. DECK.EXE, a thin standalone launcher of the
same DLL (the one place the DLL's lookups find nothing: no exports, so it runs on an empty deck), is lifted as a program of its own with `gen_dll.py --main`
(`tools/lift/lift_all.sh` makes both sets) and built into a second binary:

    make -C src/port module-deck                      # (make -C src/port builds all three modules)
    src/port/build/pentamoor-run -m src/port/build/game_deck.so sources/installed/Magic/Program/DECK.EXE

Both work. In the game (`call 0x50ce6c main 1 1` in `PORT_CONTROL` starts it as the town and the overworld do) the deck builder shows the saved game's
46 cards, the 80 gold and the card stock; a card is moved by dragging it from the stock onto the deck, which takes 47, and the Stats window counts them by
type. DECK.EXE does the same with an empty "New Deck". What running them needed:
- **A static C runtime's kernel32 calls** (`kernel32_rt.c`: heap, virtual memory, std handles, locale, strings, time), `GetDesktopWindow`, `InsertMenuA`, and the
  `int3` and masked-index jump tables (`and edx, 3; jmp [edx*4+table]`, the runtime's memmove) in the lifter.
- **The picture decompressor again**: DECKDLL has a copy of the MPS_CODE section (the same code at other addresses), so `lzw.c` takes its addresses from a
  table and is installed for each copy.
- **PeekMessage's range** (`wMsgFilterMin/Max`) was ignored. The deck builder tells a double click from a click by sleeping the double-click time and peeking
  for `WM_LBUTTONDBLCLK` only; the queued button-up was taken for it, and every click was dropped.
- **Dragging a window with the mouse** is `WM_SYSCOMMAND` `SC_MOVE` (0xF012), a modal loop in DefWindowProc that moves the window with the pointer until the button
  comes up, and `WindowFromPoint` (a stub that returned the top window) then says which window it was dropped on.
- **Struct-by-value arguments**: `PtInRect` takes a POINT as two words and `WindowFromPoint` too; the argument table (made from the decompiled code, which writes
  a POINT as one argument) was a word short, so the call copied one word too few and the y coordinate was whatever was on the stack. `import_signatures.py` lists them.
- **Dialogs get WM_PAINT and WM_ERASEBKGND** like any window, and the compositor shows what a dialog procedure drew (the Stats window draws its own table, the
  coin toss its artwork) under the stand-in controls.
`PORT_MSGLOG=1` logs every window message, `trace on`/`off` in `PORT_CONTROL` logs every import call with its arguments and result, and `call ADDR [args]`
starts a guest function (the way to reach a screen from a script).

### Dialogs as Windows 98 draws them

The game's 29 dialog templates (22 in MAGIC.EXE, 7 in DECKDLL.DLL, one in STATWIN.DLL) name classes, styles, positions and a font; what they look like is the
system's. `ui.c` draws them the way Windows 98 does, over the composed screen:
- **The size.** A template's units are the dialog font's: a quarter of its average character width across (the OS/2 table's `xAvgCharWidth`), an eighth of its
  height down (rounded ascent plus descent). With `DS_SETFONT` that is the game's own Benguiat or Zurich at the point size the template says (the coin toss's
  and Deck Info's are 12 and 10 points, which makes them bigger than the old fixed 1.5 x 1.625); without it, MS Sans Serif's 6 x 13. The window is the client area plus
  its frame (`Window.nc_*`: a one-pixel border, or the 3-pixel dialog frame with a 19-pixel gradient caption and a close box), and children are placed inside the
  client area, `GetClientRect` and the mouse's client coordinates follow.
- **The controls.** Push buttons (raised, pressed, default), check boxes, radio buttons, group boxes, static text (wrapped, aligned, with its `&` underlined, and the
  rule, frame and rectangle styles), edit boxes (sunken, password), list boxes with a scroll bar, combo boxes with their drop arrow, and spin buttons, in the
  standard colours, with disabled text embossed.
- **Their colours.** A dialog is asked once, after `WM_INITDIALOG`, what each control should look like (`WM_CTLCOLORSTATIC`, `...BTN`, `...EDIT`, `...LISTBOX`: the game's
  dialog procedures answer with a text colour, a brush, or a null brush for text drawn over their artwork). The answers are applied, so the coin toss's text is
  bold black over the picture its procedure painted on `WM_ERASEBKGND`, and Deck Info's labels sit transparent over its parchment.
- **The rest.** What a dialog's own procedure drew (the Stats table, the artwork) is the dialog's client area, with the controls on top, from the back of the stacking
  order to the front; the game's own classes inside a dialog (the card-choice window) are painted by their own procedures.
Checked by eye against the game's screens (coin toss, ante, Deck Info, Stats, "Sorcerer casts..."); there is no emulator reference for the pixels, which use the
host's fonts when a face is not one of the game's. `make -C src/port test` checks the sizes (client area from the font's units, frame, child positions).

### Video

The game's movies play through SDL: the picture is a window's surface that the compositor repaints on the clock, the sound goes to the mixer.
`movie.c` reads the AVI (RIFF) container and decodes Microsoft Video 1 ("CRAM", 16 bit, 4x4 blocks: one colour, two colours, eight colours, skip runs), which is
what the coin toss movies (`DuelArt/COINTOSS_Heads.avi`, `COINTOSS_Tails.avi`, 320x240, 15 fps, 4 s) use. The decoder matches ffmpeg's output bit for bit
(checked on frame 30 of Heads). The ending movie (`MTGEND.AVI`, 576x340, 18.5 s) is Intel Indeo 4 ("IV41"), which is not decoded here: when `ffmpeg` is on the
`PATH`, it decodes the pictures through a pipe (`ffmpeg -i FILE -an -f rawvideo -pix_fmt rgb24 -fps_mode passthrough -`, read in order; its last 13 AVI frames
are empty, so the last picture stays); without it `LoadAVI` says "cannot be decoded" (4), which the game takes as a movie that is not there. The sound is plain PCM
in the AVI (8 bit, 22.05 kHz) and plays as a stream voice of the mixer (`sound_stream_start`).

Two ways in, both a window (`Window.movie`):
- **The MCI window** (`MCIWndCreateA(parent, instance, style, path)`, cdecl): a child of the coin toss dialog, the size of the movie. The game sends it
  `MCI_PLAY` (0x806), `MCI_STOP` (0x808) and `WM_CLOSE`; the parent is sent `MCIWNDM_NOTIFYMODE` (0x4C8) with 525 when it starts and 524 when it stops.
- **MAGVID.DLL on the host** (`video.c`: its 20 exports, as the emulator did): `LoadAVI(path, *slot, *pos, flags)` (0, or 3 no free slot of three, 4 not
  decodable, 5 no such file) makes a popup window at `pos` (flags 0) or centred (full screen); `PlayAVI`, `StopAVI`, `UnloadAVI`, and `VidStatus` (1 while it
  plays, 0 when over, 2 for a bad handle). STATWIN's `play_video` loops on `VidStatus` and unloads. Only `MTGEND.AVI` and the two coin toss movies exist on the
  game's discs; the spell-hit clips the program names (`cball1.avi`, `Whit-hit.avi`, ...) are not there, and `LoadAVI` answers 5 for them.

Seen playing: the coin toss movie plays in the dialog (the coin spins on its dark background, with its sound); the ending movie, started from a duel with
`call 0x409e6d 0x528934 32 30 0` through `PORT_CONTROL`, plays to its end and unloads. Tests: `test_movie.c` builds a Video 1 movie in memory (all four block
kinds, the sound, a window that plays, ends, stops and closes).

### DUEL.EXE on its own

`DUEL.EXE` (the duel program, with its own setup dialog: Gauntlet or Single Duel, the two decks, Duel Options) runs natively:

    tools/lift/lift_all.sh        # lifts it into sources/generated/lift_duel (with DECKDLL.DLL), among the others
    make -C src/port module-duel
    src/port/build/pentamoor-run -m src/port/build/game_duel.so sources/installed/Magic/Program/DUEL.EXE

Seen playing: the setup dialog, OK, the board with the coin toss movie, the mulligan and ante dialog ("Start the duel"), the first main phase with a hand of eight, a
land played by a click, and a dozen phases of turns with the opponent's AI casting spells (all 1,696 functions of the program lift). It is the same duel engine as
`MAGIC.EXE`'s, at other addresses; the C runtime is statically linked, so the program calls the raw kernel32 and `kernel32_rt.c` answers.

What it needed, all of it in the lifter, none of it specific to this program (the tests are in `tools/lift/test_lift.py`, 41 now):
- **Instructions**: `rcr`/`rcl`, `bt`/`bts`/`btr`/`btc` (a register bit index reaches past the dword, as the C runtime's `strspn` uses it), `xchg`, `jecxz`/`loop`,
  `std` with a direction flag the string instructions follow (`strrchr`), `repe cmpsb/cmpsd`, `wait`/`fnclex`/`fninit`, and the **x87** (loads and stores of floats,
  doubles and integers, add/sub/subr/mul/div with their popping and integer forms, compares and `fnstsw`, `fnstcw`/`fldcw`, `fist(p)` with the control word's
  rounding, `fchs`, `fabs`, `fsqrt`, `fxch`). The unit's state is per guest thread and in double precision (the hardware's is extended); it is what the start-up's
  Pentium FDIV test and the C runtime's float conversions use.
- **Code placed before a function's entry** that the function jumps back into (`strchr`'s tail): the explorer reads backwards when a branch goes there, and the
  lifted function starts with a `goto` to its entry.
- **Carry flags that were wrong**: `adc` and `sbb` took the carry out of `a + b` and `a - b` only, not counting the carry in. The C runtime's `_strcmpi` ends in
  `sbb al,al; sbb al,0xff`, which answered "equal" for ".pcx" against ".pic", so the picture loader took a packed picture for a PCX file and asserted. Fixed in
  `FLAGS_ADC`/`FLAGS_SBB`; this changes every lift, and `MAGIC.EXE` and `DECK.EXE` were lifted again and checked.
- **64-bit results**: a function that returns `EDX:EAX` (the C runtime's `__aulldiv`, `__aullrem`) lost its `EDX`, because the lifted caller set `ECX` and `EDX` to a
  poison value after every call. A lifted `ret` now leaves its `EDX` for the caller (`lift_ret_edx`); a host function leaves the poison value. Without it `sprintf("%d")`
  never ended.
- **The picture decompressor** has a copy in `DUEL.EXE`'s own `MPS_CODE` section (0x6c5000) with its state at other addresses: `lzw.c` has the third context.

Not seen: a whole game to a win, the Gauntlet, Duel Options and Create Deck (the dialogs open but were not played), the standalone duel's sound by ear.

### A duel played to its end

Played the way a person does it, through `PORT_CONTROL` with the mouse and the Return key, in `MAGIC.EXE` against the Sorcerer (the saved game's red wizard):
lands played, creatures cast and paid for by tapping lands and creatures (Llanowar Elves for mana), the spell chain and its Done button, attackers chosen and taken back,
blocks, damage, the opponent's turns with its AI casting (the "Sorcerer casts..." dialog), the right-click menu (go to a phase, arrange cards, Duel Options, Concede with its
"Yes, I'm sure" submenu), and **both ends of a duel**: one won by attacking (the Sorcerer at -1, "You won!" with the next draws of both libraries) and five lost by
conceding (the "Sorcerer won" screen, then the lost-card screen, then the ante screen of the next duel); four duels in a row started and conceded without the game
dying. No crash in a duel's end. What it found:
- **A modal dialog without OK or Cancel never got a key.** The result screen ("You won!", "Sorcerer won") has two hidden buttons (Next round, Quit Gauntlet) and reads
  Enter, Space and Esc itself as `WM_CHAR`; the dialog manager's Enter/Esc shortcut (IDOK/IDCANCEL) found no such control, ate the key, and the game stayed on that screen
  for good. Keys now go to the open dialog as `WM_KEYDOWN`/`WM_CHAR` unless it has the control the shortcut stands for (`test_wm.c`: the test hangs without the fix).
- **`poke ADDR VALUE [BYTES]`** in `PORT_CONTROL` writes guest memory (a debugging aid, e.g. to set a life total).

Not seen: the reward screen of a duel won in the overworld's flow after the Enter key (the win above was dismissed before the fix, and the loss's equivalent after it),
the Gauntlet's Next round, a duel with a counterspell or a stack of spells, and the sound by ear.

### The overworld's speed

On a modern CPU the overworld ran far too fast: a short press of the mouse button moved the party a long way. The game paces its overworld loop with
`while (clock() - last < 60);` (0x4e7897..0x4e78a8), meaning one frame per 60 ms at most, but `last` is a local that the loop head sets to 0 on every pass
(`mov [ebp-0x1c], 0` at 0x4e7867, inside the loop), so after the first 60 ms of the process the wait never waits. The original's speed was therefore whatever the 1997
machine could draw; a held button moves the party a step per frame. (Measured: frames 1 to 3 ms apart.)

`pace.c` makes the loop wait where it starts a frame: it takes over the call of `0x5016f9` (the 33 ms timer's tick counter, read and cleared) that the loop makes at
0x4e786e, and when it is that call it sleeps out the rest of 60 ms since the last frame (frames now come 60.0 ms apart, 16.7 a second: the game's own number).
`PORT_FRAME_MS=100` makes the frame longer (a slower game), `PORT_FRAME_MS=0` takes the pacing away. A press now lasts at least 70 ms (it was 40), so one frame always sees it.
`clock()` is also the wall clock now (the host's counted CPU time). `PORT_TRACE_FN` prints a timestamp, and a `peek ADDR [COUNT]` command joins `poke` in `PORT_CONTROL`. `threads` prints every guest thread to stderr: ready, blocked (with a condition, with a deadline, or with neither: waiting for something nobody will give) and the last import it called and from where (`sched.c`, `sched_dump`); it is what tells a hang from a loop, as in [draw-phase-stuck.md](notes/draw-phase-stuck.md). `trace on|off` prints every import call, and `calls on|off` every call from one lifted function to another with its caller: a few seconds of it, started before a click on a button, is the engine's flow for that click.

Not known: how fast the original really ran; 60 ms is the game's intent, not a measurement of the retail game on a Pentium.

Slowdowns while walking are the game's own design, not the port's. The walking code (the loop's movement step, around the `local_c` divisor) moves the party only on frames
where the frame counter is a multiple of a divisor: 1 on open ground, 3 on terrain types 2 to 5 (unless a spell or item that the flags at 0x67f374 stand for cancels it),
and the party is made to go slower still (2 more, up to 4) when its stamina counter (0x522448) is 0, which walking runs down by one every 32 frames and resting restores.
A divisor of 3 moves it a double step every third frame, which is two thirds of the speed and jerkier. Everything is counted in frames, so the frame period scales all of
it alike. `PORT_FRAME_LOG=1` prints the frames that took more than the period and 15 ms (so a slow draw, as opposed to this, would show).

### Bigger screens: 1024x768 is the default

The program runs at **1024x768** unless `PORT_RES` says otherwise (`PORT_RES=640x480` is the original's size, `PORT_RES=800x600` the one between; `main.c` sets the default, `screen_set` in
`gdi.c` takes the override). The game has its own layouts for 640x480, 800x600 and 1024x768 (code that branches on
`g_DisplayScreenWidth` at 0x522458, and the art: `SPR800/`, `SPR1024/`, `advinter800.pic`, `advinter1024.pic`, `creatures800/1024.pic`), but nothing in the program sets that variable
from anywhere: it starts as 640 (and 480 for the height at 0x52245c) in the data. So the port writes the two numbers into the game's memory before it starts (for `MAGIC.EXE`; `DECK.EXE`
and `DUEL.EXE` take the size from `GetSystemMetrics` alone), and answers `GetSystemMetrics`, the desktop window, the device context and the SDL window with the same size
(`screen_w`/`screen_h`, set once in `main`; the frame buffers are sized for up to 1600x1200).

The SDL window starts as the largest whole-number multiple of the screen that fits 90% of the display's usable area (or the size `display.cfg` remembers), is resizable and called Pentamoor, and the picture is scaled into it by our own rectangle
(`display_layout`; scaling modes `fit`, `integer`, `stretch`, filters `nearest`, `linear`, `sharp`, full screen by F11 / Alt+Enter) with the mouse mapped back by `display_to_screen`: [notes/display.md](notes/display.md). `PORT_WINDOW=WxH` picks a window size.
Scripted mouse positions (`PORT_CONTROL`, `PORT_SCRIPT`) and `shot` are in screen pixels whatever the window is; on SDL's dummy driver the window is the screen's size.

Walked at the three sizes: the title screen and new game, the overworld (walking, scrolling), encounters, villages, Buy Cards, the deck builder inside the game and standalone, the world
map, the Clues screens, Wiz Stats and the Journal, a castle and a dungeon, duels from the coin toss on, and `DUEL.EXE`'s dialogs and file dialog. `docs/notes/resolution.md` has what was
seen where, the two fixes (scripted mouse positions and `shot` in a window that is not the screen's size) and what is the game's own at the larger sizes. The coin toss movie stays 320x240.
A buffer overrun found on the way: the frame copy used the size of the largest buffer; it uses the screen's size now.

### Help and About

The game's **Help** items are `WinHelpA` calls (`HELP_CONTEXT` with a topic number of the game's own, into `<install folder>\duel.hlp`); they sit in the right-click menus of the duel
("Help...", "Help for this card...", "Help for this phase...") and of the ante and card windows. `WinHelpA` used to be a stub that returned 1 and did nothing, so the menu item seemed dead.
`winhelp.c` now answers TRUE and shows a small modal dialog ("In-game help is not available in this port", over an OK button; Enter, Esc and the close box close it too) for every
command that asks for help, and stays silent for `HELP_QUIT` (the game sends it when its palette window is destroyed). The `.HLP` is a real WinHelp 3.x file (compressed topics,
phrase tables, 56 bitmaps), not text, so no help is displayed: a WinHelp engine is not in scope. **About...** is the game's own dialog (template 247, a black box with the three
copyright lines, closed by a click, a key or a command: it has no OK button) and needed nothing: it already ran from its template through the dialog layer, in `MAGIC.EXE`'s duels and in
`DUEL.EXE`. `DECK.EXE` and `DECKDLL.DLL` have no Help or About; F1 is not a help key in the game (its accelerator, command 600, has no handler in `MAGIC.EXE` or `DUEL.EXE`, and `TranslateAcceleratorA` is a stub in any case). What was checked, and what was not: `docs/notes/help-about.md`.

### Message boxes and the game's "(Y/N)" questions

`MessageBoxA` used to log and return `IDOK` without showing anything, so a style other than `MB_OK` got an answer that is none of `IDYES`, `IDNO`, `IDCANCEL` (the deck builder's "Do you wish to
save ...?" is a `MB_YESNOCANCEL`). `msgbox.c` now shows a real modal box in the Windows 98 look (caption, icon, wrapped text, the buttons of the style, `MB_DEFBUTTON1` to 3) and returns the
button's id; Enter and Space press the focused button, Tab and the arrows move the focus, a button's underlined letter presses it, Esc is Cancel (OK for a lone OK button, nothing for Yes/No and
Abort/Retry/Ignore, as on Windows), the mouse and the D-pad and A of a controller work. **`PORT_MSGBOX=ask|auto`**: `ask` shows the box and waits; `auto` returns the default button's id at once
(logging `MessageBox: caption: text -> IDYES`). Unset, it is `auto` when nobody can answer (`PORT_CONTROL` or `PORT_SCRIPT` is set, `PORT_HEADLESS` is set, or `SDL_VIDEODRIVER=dummy`: the soak test, CI
and the driving scripts) and `ask` otherwise. The log gets one `MessageBox:` line for every call either way. `WinHelpA`'s "not available" dialog is the same box and is always shown.

The **Buy Cards "(Y/N)"** is not a message box: the game draws "Buy for N gold?   (Y/N)" itself and waits in its wait-for-key function (0x48ac2f) for `y` or `Y`; any other key is no. Nothing
else could answer it, so with a controller (no Y key) or a mouse the screen could not be left. `yesno.c` knows when one of the three such questions (buy, sell, take) is being asked, from the return
address of that function, and while it is the left mouse button (A) is `y` and the right one (B) is `n`, with a line on the screen saying so. `docs/notes/dialogs.md` has the details.

### Notes by area

Later work is written up per area in `docs/notes/`: `overworld.md` (how to reach the map, what was walked, the click-repeat fix), `movies.md` (the 68 StatWin clips), `saves-and-paths.md` (save round trips,
the file layer on case-sensitive systems), `dialogs.md` (dialog units and fonts, checked against real Windows 98 screenshots), `duel-ux.md` (the prompt bar, how a prompt is cancelled, the soak test),
`lifter-gaps.md` (what the "unlifted" functions of MAGIC.EXE really are), `resolution.md` (the 1024x768 default, the window, what was walked at each size), `ci.md` (the GitHub Actions workflow), `help-about.md` (WinHelp and the About dialog), `controller.md` (game controllers: the button map, the cursor, walking), `controller-nav.md` (the D-pad between cards, buttons and menu rows in a duel and its dialogs: where the cards are, the rules), `steamdeck.md` (the Steam Deck: the download, the installer with windows, adding to Steam, the layout, full screen, typed text, what was and was not checked), `ios.md` (the iPad app: the three game modules linked into it, SDL2 for iOS, touch, the Xcode project, what ran in the Simulator and what has not run on a real iPad).


# Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request. It needs none of the game's files, so it runs the same on a fork. It has three job definitions, which make six jobs in a run: `test` (a matrix of `ubuntu-latest` and `macos-latest`: two jobs), `package` (the release archives: three jobs, below) and `windows`; the badge in the README is for the whole workflow. *(The list of steps was rewritten in the documentation audit of 2026-10; the older one had missed several.)*
The `test` job's steps:

1. SDL2 (`libsdl2-dev` / `brew install sdl2`), Python 3 with `pefile capstone pytest` (pip cached, list in `.github/requirements-ci.txt`).
2. `python tools/release/check_tree.py`: nothing tracked looks like decompiler output. `python tools/release/check_links.py`: every link between the Markdown files resolves (anchors included).
3. `make -C src/port test`: the C unit tests (window manager, graphics, sound, movies, paths, the game module, the controller and its D-pad navigation, touch, display, the Steam Deck's decisions, build profiles). They link `front.c` only, so they do not need SDL.
4. `make -C src/port check-front`: `front_sdl.c` compiled with its warnings on (syntax only, not linked; this is what SDL2 is installed for).
5. macOS only: `make -C src/port ios-runtime` cross-compiles the runtime for an iPad (objects only, nothing linked or run; the iOS-only code is checked here), and `tools/ios/deploy.sh --selftest` checks every `xcodebuild`, `devicectl` and `simctl` option that the script passes against the runner's own Xcode help.
6. The runtime builds with no generated sources (`make -C src/port all` after checking `sources/generated` is absent; no `lifted_*` function may be in `pentamoor-run`), then `make -C src/port check-module` builds a nearly empty game module (`stubgame/`) and has the runtime load it, and refuse a missing file and a file that is not a module;
   `check-run` starts the SDL window on SDL's dummy drivers with that module; `check-program` runs a tiny PE through the loader; `check-build` checks that an unknown build is refused (exit status 3).
7. `python -m pytest tools/install` (the installer: disc reader, archive, decompressor, compiler choice, module build, release layout, launcher) and `python -m pytest tools/ios` (the Xcode project generator, the build script's flags and pins, `deploy.sh` against a fake `xcrun`).
8. `python -m pytest tools/lift/test_lift.py` (the lifter, which compiles small harnesses with `cc`; the scan that finds the game's functions; the build id), `python -m pytest tools/release` (`check_tree` and `check_links` on made-up trees and on this repository, and that CONTRIBUTING's table of environment variables is the whole list the code reads) and `python -m pytest tools/research` (the readers of other builds' files, on files the tests make up).
9. `python -m pytest tools/steamdeck` (Linux and macOS jobs; not Windows, the scripts need `sh`): the Steam shortcut writer against a hand-built `shortcuts.vdf`, the installer's progress, `install-gui.sh`'s dialogs with stand-ins, the controller layout.
10. `python -m pytest tools/soak`: the soak scripts' control-pipe helpers (a teleport of the party tells the map to redraw), on a pipe, no game.

Not in CI: `tools/difftest`, `tools/registry` and `tools/verification_harness/tests` (pure logic and recorded vectors; run them by hand, CONTRIBUTING.md, "Tests"), `tools/emu_spike/tests` (they need `unicorn`), and everything that needs the game (the soak runs themselves, `tools/display`, `src/port/compare_screen.py`).

What CI cannot do: build a real game module or run the game, because that needs the lifted C, which is made from the game files and is never committed. It does build the runtime, which is the part to be published.

Found while setting this up: the lifter's test harness was linked without `-lm`, which fails on Linux (`floor`, `ceil`, `trunc`, `nearbyint`);
macOS links libm by default and hid it. gcc on Linux also prints a few `-Wformat-truncation` / `-Wrestrict` warnings in
`kernel32_rt.c`, `stdio.c`, `paths.c` and `crt.c`; they are not errors, and CI does not use `-Werror`.

## Windows

The `windows` job runs on `windows-latest` in an MSYS2 MINGW64 shell (`msys2/setup-msys2`, pinned to a commit SHA with its release tag in a comment; `make`, `mingw-w64-x86_64-gcc`, `mingw-w64-x86_64-SDL2` from pacman).
It runs `make -C src/port test` (the same unit tests as the other systems plus `test_module`, which loads the stub game module as a DLL and runs lifted-style functions in it),
`check-front`, `all` (the runtime as `pentamoor-run.exe` with no generated sources), `check-module`, `check-run`, `check-program` (a PE made on the spot by `stubgame/mkpe.c` runs through the loader, the imports and the file layer, with the stub module's lifted-style entry point; it is in no build profile, so it runs with `PORT_UNKNOWN_BUILD=1`), `check-build` (and without the switch the runtime refuses it, exit status 3, and refuses a file that is not the one the module was made from), and lists the DLLs the `.exe` and the module import
(`objdump -p`; with the winpthreads linked statically it is Windows' own and `SDL2.dll`). The installer's Python tests run there too, with a native Windows Python (`actions/setup-python`, `python -m pytest tools/install`: the compiler choice, the module build commands, Zig's download, the archive layout; the shell launcher's test skips). The lifter's, `tools/release`'s, `tools/ios`' and `tools/steamdeck`'s tests are not run there.
`check-run`, `check-program` and `check-build` also run in the Linux and macOS jobs.

The logs of a run are shown only to someone signed in to GitHub. The Windows steps go through `.github/ci-run.sh`, which copies the error lines of a failing step (and, with
`CI_NOTICE=1`, the tail of every step) into annotations, which the API gives to anyone: `gh api repos/OWNER/REPO/check-runs/JOB_ID/annotations`. Handy when iterating from a machine
whose `gh` is not signed in.

## Release archives

The `package` job of `ci.yml` calls `.github/workflows/package.yml` (a reusable workflow; `release.yml` calls the same one on a `v*` tag, so what CI builds is what a release publishes). It has three jobs,
each building the runtime and an archive and then checking it with `tools/release/check_archive.py` on its own, unpacked into a new folder:

| Job | Runner | Runtime | Archive |
|---|---|---|---|
| `windows` | `windows-latest`, MSYS2 MINGW64 for the build, native Python for the rest | `make runtime`; `tools/release/win_libs.sh` lists `SDL2.dll` and what it loads | `.zip` with the embeddable Python (3.13, checksummed), Zig (bundled), pefile and capstone (`pip --platform win_amd64`) |
| `linux` | `ubuntu-22.04` (an older glibc runs on newer systems), `libsdl2-dev` | `make runtime`, dynamic SDL2 (documented as a requirement) | `.tar.gz`; and, from the same runtime, the Steam Deck's `pentamoor-<version>-steamdeck.tar.gz` (the Linux archive plus `tools/steamdeck`, `docs/notes/steamdeck.md`), checked the same way and then by `check_archive.py`'s `check_steamdeck` (its scripts parse, `add-to-steam.py` writes a shortcut into a fake Steam folder, the installer's text mode reaches its first question) |
| `macos` | `macos-latest` (arm64) | `tools/release/build_macos.sh universal`: SDL2 built from its pinned source for arm64 and x86-64 (x86-64 cross-compiled with `-arch`, not run), linked in statically, `lipo`, ad hoc `codesign` | `.tar.gz`, universal |

`check_archive.py` looks at: every file against the archive's `SHA256SUMS` (and nothing extra); that nothing made from the game or a game module is in it (no `sources/`, no `*_gen.c` but the hand-written
stub, no `MAGIC.EXE`, no `game_*.so`...); `install.py --check` (run with the archive's own Python on Windows, with a PATH of only Windows' folders, so nothing of the build machine hides a missing file);
pefile and capstone imported from the archive's `tools/pydeps` (capstone disassembles two bytes, so its native library is the right one for the platform); and `install.py --self-test`, which
chooses a compiler (on Windows `--compiler zig`: the bundled Zig), builds the stub module with the archive's own `modbuild.py` and headers, and has the archive's own `pentamoor-run` load it. The
`./pentamoor` launcher of a Unix archive is run with no game installed and must refuse and name `pentamoor-install`. The archives are uploaded as artifacts (7 days).

What this does not cover: a real game module (that needs the game), the game on Windows, the x86-64 half of the macOS binary, a system without a C compiler on Linux and macOS (the Zig download is
tested by unit tests with a local file, and by hand), and the publish step of `release.yml`.

## Badge

A line for the top of the README, under the title:

```markdown
[![CI](https://github.com/MadranFoyle/pentamoor/actions/workflows/ci.yml/badge.svg)](https://github.com/MadranFoyle/pentamoor/actions/workflows/ci.yml)
```

Change the owner and repository if the README lives in another one.

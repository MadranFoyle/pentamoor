#!/usr/bin/env python3
"""
install_sota.py - check, lift and build Spells of the Ancients 2.15 (shandalar.exe, FaceMaker.exe and the deck builder) from a folder that already holds it.   EXPERIMENTAL.
docs/notes/sota-comparison.md ("Milestone 1", "Milestone 2", "Milestone 3")

You do not need this to install: `pentamoor-install "MTG v1.0.iso" --sota "MTG v2.00.iso" --patch SOTAV215.EXE` makes the folder from the discs and the patch (sotainstall.py) and
lifts and builds it (install.py). This script is for a folder made another way, and for rebuilding only the 2.15 modules:

    python3 tools/install/install_sota.py sources/installed_sota/Magic --build           # lift the three programs and build their modules (a checkout: make; a release: modbuild)
    python3 tools/install/install_sota.py sources/installed_sota/Magic --check           # only say which build each file is
    PENTAMOOR_SOTA=sources/installed_sota/Magic/Program ./pentamoor sota                 # run it

The folder is what Windows has after the expansion is installed over the first game and patched: the first game's install (the pictures, sprites and sounds Spells of the Ancients
still reads from it), with the files of the 2.0 install over it (the expansion's disc, `Program\\`), and the six files of the 2.15 patch over those. This script does not make it: it
checks it (the SHA-256 of every program and library against tools/lift/builds.py, the table the runtime's profiles also come from) and says what is wrong. magic.exe (the "Magic Shell")
and ManaLink 3.0 are not part of it.
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "lift"))       # builds.py: run from a checkout as `python3 tools/install/install_sota.py`, it was not found (milestone 1 ran it with tools/lift on PYTHONPATH)

import builds  # noqa: E402
import install  # noqa: E402
import liftrun  # noqa: E402
import modbuild  # noqa: E402

say = install.say
die = install.die


def find_program_folder(folder):
    """The folder that holds shandalar.exe: `folder` itself or its Program (any case); None if there is none."""
    for cand in (folder, os.path.join(folder, "Program")) + tuple(os.path.join(folder, n) for n in (os.listdir(folder) if os.path.isdir(folder) else ()) if n.lower() == "program"):
        if os.path.isdir(cand) and any(n.lower() == "shandalar.exe" for n in os.listdir(cand)):
            return cand
    return None


def detect(program):
    """[(file name, build id or None when the file is not there, 'v2.15 shandalar.exe' or None when it is another build)] for every file of the 2.15 build."""
    out = []
    for name, sha in builds.fingerprints("v2.15").items():
        path = liftrun.sota_file(program, name)
        if not os.path.exists(path):
            out.append((name, None, None))
            continue
        bid = builds.file_build_id(path)
        out.append((name, bid, builds.name_of(name, bid)))
    return out


def problems(detected):
    return [f"{name} is missing" if bid is None else f"{name} is not the 2.15 build (sha256 {bid[:12]})" for name, bid, known in detected if not known]


def report(program, detected):
    bad = problems(detected)
    for name, bid, known in detected:
        say(f"  {name}: {known or ('missing' if bid is None else 'unknown build (sha256 ' + bid[:12] + ')')}")
    if bad:
        say("This is not Spells of the Ancients 2.15: " + "; ".join(bad) + ".")
        say('It needs the first game\'s install with the expansion\'s 2.0 files and the 2.15 patch\'s six files over it: pentamoor-install "MTG v1.0.iso" --sota "MTG v2.00.iso" --patch SOTAV215.EXE makes it.')
    return not bad


def build_with_make(layout, args):
    import shutil
    if not any(shutil.which(c) for c in ("cc", "gcc", "clang")) or shutil.which("make") is None:
        die("a C compiler and make are needed (a release has no Makefile: it builds the modules with modbuild)")
    jobs = str(max(1, min(os.cpu_count() or 1, 8)))
    say("compiling the runtime and the game modules (a few minutes)")
    subprocess.run(["make", "-C", layout.port, "-j" + jobs, "all"], check=True, cwd=install.ROOT)


def build_modules(layout, args):
    cc = modbuild.find_compiler(layout.native, layout.tools, explicit=args.compiler, download=not args.no_download, ask=lambda q: install.ask_yes(q, True, args.yes), say=say)
    say(f"compiler: {cc.describe()}")
    os.makedirs(layout.out_dir, exist_ok=True)
    made = modbuild.build_modules(list(modbuild.SOTA_PROGRAMS), layout.generated, layout.port, layout.native, layout.objects, layout.out_dir, cc, jobs=args.jobs, say=say)
    if os.path.exists(layout.runtime):
        for prog, path in made.items():
            ok, out = modbuild.smoke_test(layout.runtime, path)
            say(f"  game_{prog}: {'loads in the runtime' if ok else 'DID NOT LOAD: ' + out[-400:]}")
            if not ok:
                die(f"the module {path} was built but the runtime does not load it")
    return made


def main(argv=None):
    ap = argparse.ArgumentParser(description="Lift and build Spells of the Ancients 2.15 from a folder of your own files (experimental).")
    ap.add_argument("folder", help="the install: the first game's folder with the 2.0 files and the 2.15 patch over it (the folder that holds Program, or Program itself)")
    ap.add_argument("--build", action="store_true", help="lift the programs to C and compile their modules (a checkout: make; a release, or with --modules: the installer's own compiler step)")
    ap.add_argument("--modules", action="store_true", help="a source checkout: build the modules with modbuild instead of make (what a release does)")
    ap.add_argument("--check", action="store_true", help="only report which build each file is and exit")
    ap.add_argument("--compiler", help="the C compiler for --modules (default: cc, gcc or clang if one works, else Zig downloaded into tools/local)")
    ap.add_argument("--no-download", action="store_true", help="never download the Zig compiler")
    ap.add_argument("--yes", "-y", action="store_const", const=True, default=None, help="answer yes to questions (downloading Zig, pip-installing pefile and capstone)")
    ap.add_argument("--jobs", "-j", type=int, help="how many C files to compile at once")
    ap.add_argument("--force", action="store_true", help="lift again even if these files were lifted already")
    args = ap.parse_args(argv)
    program = find_program_folder(os.path.abspath(args.folder))
    if program is None:
        die(f"{args.folder} holds no shandalar.exe (nor does its Program folder)")
    say(f"Spells of the Ancients folder: {program}")
    ok = report(program, detect(program))
    if args.check:
        return 0 if ok else 1
    if not ok:
        return 1
    if not (args.build or args.modules):
        say("next: run this again with --build to lift the programs and build their modules")
        return 0
    layout = install.Layout()
    paths = install.ensure_python_deps(layout, assume=args.yes)
    say("lifting shandalar.exe, FaceMaker.exe and DECK.EXE with their libraries into C (a few minutes; the C is made from your files and stays on your machine)")
    try:
        liftrun.lift_sota(layout.root, program, sys.executable, paths, force=args.force, say=say)
        if layout.release or args.modules:
            build_modules(layout, args)
        else:
            build_with_make(layout, args)
    except modbuild.BuildError as e:
        die(str(e))
    except (RuntimeError, subprocess.CalledProcessError) as e:
        die(str(e))
    shown = os.path.relpath(program, install.ROOT) if program.startswith(install.ROOT) else program
    say(f"built. Play with:  PENTAMOOR_SOTA={shown} {'./pentamoor' if os.name != 'nt' else 'pentamoor.bat'} sota")
    return 0


if __name__ == "__main__":
    sys.exit(main())

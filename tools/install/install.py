#!/usr/bin/env python3
"""
install.py - "install" the game for Pentamoor from your own copy of the disc.

    python3 tools/install/install.py "MTG v1.0.iso"            # extract the game into sources/installed/Magic
    python3 tools/install/install.py "MTG v1.0.iso" --build    # ...and lift and compile it, ready for ./pentamoor     (a source checkout: make builds the runtime and the modules)
    ./pentamoor-install "MTG v1.0.iso"                         # the same from a release: the runtime is already built, this builds the game modules

What it does, in order: reads the disc image (a plain .iso; a folder that holds the disc's files works too) without mounting it; unpacks the game's own
InstallShield archive (Setup/data.z, 967 files) into <dest>/Magic/Program, the same folder the Windows installer makes; copies the disc's music (Sound/*.WAV)
and the spell and wizard movies (StatWin/*.AVI), which the game reads from the CD, into the same folder; checks the programs against the build this port is
made from. With --build (a release always) it then lifts the game's programs into C (tools/lift, run here in Python), picks a C compiler (cc, gcc or clang if there is
one, else a Zig that it downloads into tools/local; modbuild.py) and compiles the three game modules next to the runtime. The C made from your files stays on your machine
(sources/ is ignored by the repository) and nothing of the game is ever uploaded. The only downloads are the Zig compiler, when there is no C compiler and you say yes, and
the Python packages pefile and capstone with pip, when the release did not carry them.

A raw Alcohol 120% .mdf/.mds pair is not an .iso: convert it first (`mdf2iso "MTG v1.0.mdf" "MTG v1.0.iso"`).
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools", "lift"))      # builds.py: the builds the port knows (the same list as the runtime's profiles, src/port/profile.c)

import builds  # noqa: E402
import datax  # noqa: E402
import iso9660  # noqa: E402
import liftrun  # noqa: E402
import manifest  # noqa: E402
import modbuild  # noqa: E402

# The build the port is made from (the retail disc, version 1.0): docs/ORACLE_VM.md. The ids are the build ids of tools/lift/builds.py (the SHA-256 of each file), the same
# the lifter writes into the game modules and the runtime checks (src/port/profile.c).
FINGERPRINTS = builds.fingerprints("v1.0")
EXE = ".exe" if os.name == "nt" else ""


def say(msg):
    print(msg, flush=True)


def die(msg):
    sys.exit(f"install: {msg}")


# ---- where things are -------------------------------------------------------------------------------------------------------------------------------------
class Layout:
    """A release (the runtime beside the launchers, no Makefile) or a source checkout (src/port/Makefile; the runtime and modules in src/port/build)."""

    def __init__(self, root=ROOT):
        self.root = root
        self.release = not os.path.exists(os.path.join(root, "src", "port", "Makefile"))
        self.tools = os.path.join(root, "tools", "local")                    # Zig goes here
        self.pydeps = os.path.join(root, "tools", "pydeps")                  # pefile and capstone (a release carries them; else pip puts them here)
        self.generated = os.path.join(root, "sources", "generated")
        self.objects = os.path.join(root, "sources", "build")
        self.port = os.path.join(root, "src", "port")
        self.native = os.path.join(root, "src", "native")

    @property
    def out_dir(self):
        """Where the runtime is and the modules go: the folder of the launchers in a release, src/port/build in a checkout."""
        return self.root if os.path.exists(os.path.join(self.root, "pentamoor-run" + EXE)) else os.path.join(self.root, "src", "port", "build")

    @property
    def runtime(self):
        return os.path.join(self.out_dir, "pentamoor-run" + EXE)


def clean_path(text):
    """What a person pastes or drops on a terminal for a file name: quotes around it, backslashes before spaces (macOS Terminal), a trailing space, ~."""
    text = text.strip()
    if len(text) > 1 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    elif os.name != "nt":
        text = re.sub(r"\\(.)", r"\1", text)
    return os.path.expanduser(text.strip())


def ask_yes(question, default=True, assume=None):
    """Ask on the terminal; `assume` (--yes) answers without asking. Without a terminal and without --yes the answer is no."""
    if assume is not None:
        return assume
    if not sys.stdin or not sys.stdin.isatty():
        return False
    try:
        reply = input(f"{question} [{'Y/n' if default else 'y/N'}] ").strip().lower()
    except EOFError:
        return False
    return default if not reply else reply[0] == "y"


def ask_disc():
    if not sys.stdin or not sys.stdin.isatty():
        die("no disc image given. Usage: pentamoor-install \"path/to/MTG v1.0.iso\"")
    say("Pentamoor needs your own copy of the game: a disc image of the retail Magic: The Gathering CD (version 1.0), an .iso file.")
    say("Type or paste its path, or drag the file onto this window and press Enter (leave it empty to cancel).")
    while True:
        try:
            path = clean_path(input("ISO file: "))
        except EOFError:
            path = ""
        if not path:
            die("cancelled")
        if os.path.exists(path):
            return path
        say(f"  {path} does not exist; try again.")


# ---- the Python packages the lifter needs -----------------------------------------------------------------------------------------------------------------
def python_paths(layout):
    return [layout.pydeps] if os.path.isdir(layout.pydeps) else []


def ensure_python_deps(layout, allow_pip=True, assume=None):
    """pefile and capstone must import. A release carries them in tools/pydeps (so this needs no network); a checkout is expected to have them installed. If they are missing,
    pip puts them into tools/pydeps (with --target: nothing else on the machine changes). Returns the folders to add to the lifter's path."""
    for p in python_paths(layout):
        if p not in sys.path:
            sys.path.insert(0, p)
    missing = []
    for mod in ("pefile", "capstone"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if not missing:
        return python_paths(layout)
    cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--target", layout.pydeps, "pefile", "capstone"]
    if allow_pip and ask_yes(f"The lifter needs the Python packages {' and '.join(missing)}. Install them with pip into {layout.pydeps}?", True, assume):
        say("pip install pefile capstone (needs the network)")
        if subprocess.run(cmd).returncode == 0:
            for p in python_paths(layout):
                if p not in sys.path:
                    sys.path.insert(0, p)
            importlib_invalidate()
            try:
                for mod in missing:
                    __import__(mod)
                return python_paths(layout)
            except ImportError:
                pass
    die(f"the lifter needs the Python packages {' and '.join(missing)}: {sys.executable} -m pip install pefile capstone")


def importlib_invalidate():
    import importlib
    importlib.invalidate_caches()


# ---- the game's files -------------------------------------------------------------------------------------------------------------------------------------
def extract_archive(disc, dest, force):
    entry = disc.find("Setup/data.z")
    if entry is None:
        die("this does not look like the Magic: The Gathering disc (no Setup/data.z)")
    say(f"reading Setup/data.z ({entry.size // (1 << 20)} MB)")
    data = disc.read(entry)
    files = datax.parse(data)
    made = skipped = 0
    t0 = time.time()
    for i, (path, size, packed, offset) in enumerate(files, 1):
        rel = path.replace("\\", "/")
        if rel.lower().startswith("program/") or rel.lower() == "program":
            rel = "Program" + rel[len("program"):]
        out = os.path.join(dest, "Magic", rel)
        if not force and os.path.exists(out) and os.path.getsize(out) == size:
            skipped += 1
            continue
        blob = datax.unpack(data, size, packed, offset)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f:
            f.write(blob)
        made += 1
        if i % 100 == 0:
            say(f"  {i}/{len(files)} files")
    say(f"game files: {made} written, {skipped} already there ({time.time() - t0:.0f} s)")
    return files


def copy_media(disc, dest, force):
    """The music and the movies the game reads from the CD (x:\\sound\\..., x:\\statwin\\...), into the folders it looks in on the hard disk too."""
    program = os.path.join(dest, "Magic", "Program")
    for src, dst, pattern in (("Sound", "Sound", ".wav"), ("StatWin", "Statwin", ".avi")):
        entries = [e for e in disc.listdir(src) if not e.is_dir and e.name.lower().endswith(pattern)]
        made = 0
        for e in entries:
            out = os.path.join(program, dst, e.name)
            existing = next((os.path.join(program, dst, n) for n in os.listdir(os.path.join(program, dst)) if n.lower() == e.name.lower()), None) \
                if os.path.isdir(os.path.join(program, dst)) else None
            if existing and not force and os.path.getsize(existing) == e.size:
                continue
            disc.copy(e, existing or out)
            made += 1
        say(f"{src.lower()} from the disc: {len(entries)} files ({made} copied)")


def detect_builds(program_dir):
    """The build of each file the port knows, found in a Program folder: [(file name, build id or None if the file is not there, 'v1.0 MAGIC.EXE' or None if it is not a known build)]."""
    out = []
    for name in FINGERPRINTS:
        path = os.path.join(program_dir, name)
        if not os.path.exists(path):
            # the folder may spell the name in another case (the disc's installer does not keep it)
            found = [n for n in os.listdir(program_dir) if n.lower() == name.lower()] if os.path.isdir(program_dir) else []
            path = os.path.join(program_dir, found[0]) if found else None
        if path is None:
            out.append((name, None, None))
            continue
        bid = builds.file_build_id(path)
        out.append((name, bid, builds.name_of(name, bid)))
    return out


def build_summary(detected):
    """One line for --check: which build the files are."""
    if all(known for _, _, known in detected):
        return f"{detected[0][2].split()[0]} ({', '.join(n for n, _, _ in detected)}: the retail disc)"
    bits = []
    for name, bid, known in detected:
        bits.append(f"{name} is missing" if bid is None else f"{name} is {known}" if known else f"{name} is an unknown build (sha256 {bid[:12]})")
    return "; ".join(bits)


def check_programs(dest):
    program = os.path.join(dest, "Magic", "Program")
    detected = detect_builds(program)
    bad = [f"{name} is missing" if bid is None else f"{name} is an unknown build (sha256 {bid[:12]})" for name, bid, known in detected if not known]
    if bad:
        say("WARNING: " + "; ".join(bad) + ".\n         The port is made from the retail disc, version 1.0, and the runtime refuses to start a program of another build "
            "(`pentamoor: ... is build ..., which this version does not support`).")
    else:
        say(f"programs: all {len(detected)} are build {detected[0][2].split()[0]}, the retail disc the port is made from")
    return not bad


def game_installed(dest):
    return os.path.exists(os.path.join(dest, "Magic", "Program", "MAGIC.EXE"))


def link_install_folder(dest):
    """The lifter and the launcher read sources/installed; point it at --dest when that is somewhere else."""
    program_dest = os.path.abspath(dest)
    link = os.path.join(ROOT, "sources", "installed")
    if program_dest == link:
        return
    say("note: the lifter reads sources/installed; linking it to the install folder")
    os.makedirs(os.path.dirname(link), exist_ok=True)
    if not os.path.lexists(link):
        os.symlink(program_dest, link)
    elif os.path.realpath(link) != os.path.realpath(dest):
        die(f"{link} already exists and is not the install folder; move it away or install there")


# ---- building ---------------------------------------------------------------------------------------------------------------------------------------------
def build_commands():
    """What a source checkout's --build runs after the lifter: (message, argv) pairs. The runtime (`pentamoor-run`: everything but the game's code) and one game module
    per program (a library made only from the C the lifter wrote) are built by the one `make -C src/port` and loaded together by ./pentamoor."""
    jobs = str(max(1, min(os.cpu_count() or 1, 8)))
    return [("compiling the runtime and the game modules src/port/build/{pentamoor-run, game_magic, game_deck, game_duel} (a few minutes)",
             ["make", "-C", os.path.join(ROOT, "src", "port"), "-j" + jobs, "all"])]


def lift(layout, args):
    paths = ensure_python_deps(layout, assume=args.yes)
    say("lifting the game's programs into C (a few minutes; the C is generated from your files and stays on your machine)")
    liftrun.lift_all(layout.root, sys.executable, paths, force=args.force)


def build_with_make(layout, args):
    """A source checkout: the lifter, then make builds the runtime and the modules."""
    if not any(shutil.which(c) for c in ("cc", "gcc", "clang")):
        die("no C compiler found (install Xcode's command line tools, or gcc/clang); `--modules` can fetch one for the game modules, but the runtime needs make and a compiler")
    if shutil.which("make") is None:
        die("make was not found (the runtime is built by make; a release has it already built)")
    lift(layout, args)
    for cmd in build_commands():
        say(cmd[0])
        subprocess.run(cmd[1], check=True, cwd=ROOT)


def build_modules(layout, args):
    """The lifter, then the Python builder compiles the three modules next to the runtime. What a release does; --modules does it in a checkout."""
    native = layout.native
    cc = modbuild.find_compiler(native, layout.tools, explicit=args.compiler, download=not args.no_download,
                                ask=lambda q: ask_yes(q, True, args.yes), say=say)
    say(f"compiler: {cc.describe()}")
    lift(layout, args)
    os.makedirs(layout.out_dir, exist_ok=True)
    made = modbuild.build_modules(list(modbuild.PROGRAMS), layout.generated, layout.port, native, layout.objects, layout.out_dir, cc, jobs=args.jobs, say=say)
    if os.path.exists(layout.runtime):
        for prog, path in made.items():
            ok, out = modbuild.smoke_test(layout.runtime, path)
            say(f"  game_{prog}: {'loads in the runtime' if ok else 'DID NOT LOAD: ' + out[-400:]}")
            if not ok:
                die(f"the module {path} was built but the runtime does not load it")
    else:
        say(f"note: no runtime at {layout.runtime} yet (a source checkout: make -C src/port runtime)")
    return made


def clean_up(layout):
    for d in (layout.generated, layout.objects):
        if os.path.isdir(d):
            shutil.rmtree(d)
            say(f"removed {os.path.relpath(d, layout.root)}")


def check(layout, args):
    """--check: is this folder ready to install into? Prints one line per thing and returns 0 if the release is complete and the Python packages import."""
    problems = []
    say(f"layout: {'release' if layout.release else 'source checkout'} at {layout.root}")
    say(f"python: {sys.version.split()[0]} ({sys.executable})")
    gone = manifest.missing(layout.root)
    if gone:
        problems.append("files missing: " + ", ".join(gone))
    say(f"files:  {'all there' if not gone else 'MISSING ' + ', '.join(gone)}")
    for p in python_paths(layout):
        sys.path.insert(0, p)
    for mod in ("pefile", "capstone"):
        try:
            m = __import__(mod)
            say(f"python package {mod}: {getattr(m, '__version__', 'ok')}")
        except ImportError:
            say(f"python package {mod}: missing (pip would install it into {layout.pydeps})")
            if layout.release and not os.path.isdir(layout.pydeps):
                problems.append(f"{mod} is missing and the release has no tools/pydeps")
    say(f"runtime: {layout.runtime if os.path.exists(layout.runtime) else 'not built: ' + layout.runtime}")
    if layout.release and not os.path.exists(layout.runtime):
        problems.append("no pentamoor-run beside the launchers")
    try:
        cc = modbuild.find_compiler(layout.native, layout.tools, explicit=args.compiler, download=False, say=lambda m: None)
        say(f"compiler: {cc.describe()}")
    except modbuild.BuildError as e:
        local = os.path.isdir(os.path.join(layout.tools, "ziglang"))
        say(f"compiler: none usable now ({e}); " + ("Zig is in tools/local" if local else "the installer would offer to download Zig"))
    installed = os.path.join(layout.root, "sources", "installed")
    say(f"game:   {'installed' if game_installed(installed) else 'not installed yet'}")
    if game_installed(installed):
        say(f"build:  {build_summary(detect_builds(os.path.join(installed, 'Magic', 'Program')))}")
    return 1 if problems else 0


def self_test(layout, args):
    if not os.path.exists(layout.runtime):
        say(f"no runtime at {layout.runtime}")
        return 1
    try:
        cc = modbuild.find_compiler(layout.native, layout.tools, explicit=args.compiler, download=not args.no_download, ask=lambda q: ask_yes(q, True, args.yes), say=say)
        say(f"compiler: {cc.describe()}")
        ok, out = modbuild.self_test(cc, layout.port, layout.native, layout.runtime, say, jobs=args.jobs or 2)
    except modbuild.BuildError as e:
        say(f"self-test failed: {e}")
        return 1
    say("self-test: the stub module built and loaded in the runtime" if ok else f"self-test failed: the runtime did not load it:\n{out[-600:]}")
    return 0 if ok else 1


def parser():
    ap = argparse.ArgumentParser(description="Install the game for Pentamoor from your own disc image.")
    ap.add_argument("disc", nargs="?", help="the disc image (.iso), or a folder with the disc's files (asked for if the game is not installed yet)")
    ap.add_argument("--dest", default=os.path.join(ROOT, "sources", "installed"), help="where to put it (default: sources/installed, which is ignored by the repository)")
    ap.add_argument("--build", action="store_true", help="then lift the programs to C and compile them (a source checkout: make builds the runtime and the game modules; a release: the modules)")
    ap.add_argument("--modules", action="store_true", help="a source checkout: build only the game modules, with this installer's own compiler step instead of make (what a release does)")
    ap.add_argument("--compiler", help="the C compiler to build the modules with, for example gcc or 'zig cc' (default: cc, gcc or clang if one works, else Zig downloaded into tools/local; also $PENTAMOOR_CC)")
    ap.add_argument("--no-download", action="store_true", help="never download the Zig compiler")
    ap.add_argument("--yes", "-y", action="store_const", const=True, default=None, help="answer yes to questions (downloading Zig, pip-installing pefile and capstone)")
    ap.add_argument("--jobs", "-j", type=int, help="how many C files to compile at once (default: the number of processors, at most 8)")
    ap.add_argument("--force", action="store_true", help="write every file again, and lift again")
    ap.add_argument("--clean", action="store_true", help="after a successful build, delete the C made from your files and the object files (sources/generated, sources/build): about 200 MB")
    ap.add_argument("--self-test", action="store_true", help="build the small stub game module that ships in src/port/stubgame with the chosen compiler and load it into the runtime (no game files needed)")
    ap.add_argument("--check", action="store_true", help="only report whether this folder is ready (files, Python packages, runtime, compiler) and exit")
    return ap


def main(argv=None, default_build=False):
    """default_build: what `pentamoor-install` passes, so it builds without --build."""
    args = parser().parse_args(argv)
    layout = Layout()
    if args.check:
        sys.exit(check(layout, args))
    if args.self_test:
        sys.exit(self_test(layout, args))
    if args.compiler and not (args.build or args.modules or default_build or layout.release):
        die("--compiler goes with --build or --modules")
    dest = args.dest
    have_game = game_installed(dest)
    if args.disc is None and have_game:
        say(f"the game is already extracted in {os.path.join(dest, 'Magic')}; not reading the disc again")
    else:
        disc_path = args.disc or ask_disc()
        if not os.path.exists(disc_path):
            die(f"{disc_path} does not exist")
        try:
            disc = iso9660.open_disc(disc_path)
            say(f"disc: {getattr(disc, 'label', '') or disc_path}")
            extract_archive(disc, dest, args.force)
            copy_media(disc, dest, args.force)
        except (iso9660.IsoError, datax.DataZError) as e:
            die(str(e))
    check_programs(dest)
    say(f"installed into {os.path.join(dest, 'Magic')}")
    do_build = args.build or args.modules or default_build or layout.release
    if not do_build:
        say("next: python3 tools/install/install.py <the same disc> --build   (or run tools/lift/lift_all.sh and make -C src/port yourself)")
        return
    link_install_folder(dest)
    try:
        if layout.release or args.modules:
            build_modules(layout, args)
        else:
            build_with_make(layout, args)
    except modbuild.BuildError as e:
        die(str(e))
    except (RuntimeError, subprocess.CalledProcessError) as e:
        die(str(e))
    if args.clean:
        clean_up(layout)
    say("built. Play with:  " + ("pentamoor.bat" if os.name == "nt" else "./pentamoor"))


if __name__ == "__main__":
    main()

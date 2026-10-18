"""
liftrun.py - run the lifter (tools/lift) over the installed game, in Python, so it needs no `sh` (Windows) and the three programs are lifted at the same time.

lift_steps() is tools/lift/lift_all.sh as data; test_install.py checks the two say the same. The lifter's scripts run in a child Python started with `-c` that puts the folders they
need on sys.path first, so nothing depends on PYTHONPATH (the embeddable Python in the Windows release ignores it) or on the script's folder being searched.
A program is not lifted again when what it was lifted from (the game's programs, the lifter's source) has not changed: <generated>/.lifted holds the fingerprint.
"""
import concurrent.futures
import glob
import hashlib
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lift"))
import builds  # noqa: E402

GAME = "sources/installed/Magic/Program"
GENERATED = "sources/generated"

BOOT = "import runpy, sys; sys.path[:0] = %r; sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name='__main__')"


def lift_steps(game=GAME, generated=GENERATED):
    """{program: [(script, [arguments])...]} in the order they must run; paths are relative to the folder the lifter is run in (the release or checkout root)."""
    magic = f"{generated}/lift_magic_all"
    deck = f"{generated}/lift_deck"
    duel = f"{generated}/lift_duel"
    return {
        "magic": [
            ("gen_handlers.py", ["--program", "magic", "--exe", f"{game}/MAGIC.EXE", "--out", magic, "--all", "--no-handlers"]),
            ("gen_dll.py", ["--dll", f"{game}/STATWIN.DLL", "--base", "0x30000000", "--out", magic]),
            ("gen_dll.py", ["--dll", f"{game}/DECKDLL.DLL", "--base", "0x32000000", "--out", magic]),
            ("gen_dll.py", ["--finish", "--out", magic]),
        ],
        "deck": [
            ("gen_dll.py", ["--main", "--dll", f"{game}/DECK.EXE", "--out", deck]),
            ("gen_dll.py", ["--dll", f"{game}/DECKDLL.DLL", "--base", "0x32000000", "--out", deck]),
            ("gen_dll.py", ["--finish", "--out", deck]),
        ],
        "duel": [
            ("gen_dll.py", ["--main", "--dll", f"{game}/DUEL.EXE", "--out", duel]),
            ("gen_dll.py", ["--dll", f"{game}/DECKDLL.DLL", "--base", "0x32000000", "--out", duel]),
            ("gen_dll.py", ["--finish", "--out", duel]),
        ],
    }


# ---- Spells of the Ancients 2.15 ------------------------------------------------------------------------------------------------------------------------
def sota_file(game, name):
    """The path of a file of a 2.15 install, whatever case its name is spelled in (the install's names are not in one case); the name as given if it is not there."""
    if os.path.isdir(game):
        for n in os.listdir(game):
            if n.lower() == name.lower():
                return os.path.join(game, n)
    return os.path.join(game, name)


def sota_steps(game, generated=GENERATED):
    """{module: [(script, [arguments])...]} for the three programs of a 2.15 install (builds.SOTA_MODULES: shandalar, facemaker, sotadeck), `game` being its Program folder. Each module
    is the program and the libraries it loads, lifted at the bases of builds.LIBRARY_BASES (the runtime maps each library at its base: the profile's `.base`)."""
    bases = builds.LIBRARY_BASES["v2.15"]
    steps = {}
    for module, (exe, libs) in builds.SOTA_MODULES.items():
        out = f"{generated}/lift_{module}"
        path = sota_file(game, exe)
        if module == "shandalar":
            chain = [("gen_handlers.py", ["--program", "shandalar", "--exe", path, "--out", out, "--all", "--no-handlers"])]
        else:
            chain = [("gen_dll.py", ["--main", "--dll", path, "--out", out])]
        for lib in libs:
            chain.append(("gen_dll.py", ["--dll", sota_file(game, lib), "--base", f"0x{bases[lib]:08x}", "--out", out]))
        if libs:
            chain.append(("gen_dll.py", ["--finish", "--out", out]))
        steps[module] = chain
    return steps


def sota_fingerprint(root, game):
    """What a lifted 2.15 module depends on: the lifter's own files and the 2.15 files it lifts."""
    h = hashlib.sha256()
    files = sorted(glob.glob(os.path.join(root, "tools", "lift", "*.py"))) + [os.path.join(root, "src", "native", "layout.c")]
    names = sorted({exe for exe, _ in builds.SOTA_MODULES.values()} | {lib for _, libs in builds.SOTA_MODULES.values() for lib in libs})
    files += [sota_file(game, n) for n in names]
    for p in files:
        if not os.path.exists(p):
            continue
        h.update(os.path.basename(p).lower().encode() + b"\0")
        with open(p, "rb") as f:
            h.update(f.read())
    return h.hexdigest()


def lift_sota(root, game, python=sys.executable, pythonpath=(), programs=None, force=False, say=print):
    """Lift the 2.15 programs (the ones not already lifted from these very files) in parallel, as lift_all does for 1.0. `game`: the Program folder of the install."""
    programs = list(programs or builds.SOTA_MODULES)
    stamp = sota_fingerprint(root, game)
    paths = [os.path.join(root, "tools", "lift")] + list(pythonpath)
    todo = []
    for p in programs:
        if not force and is_lifted(root, p, stamp):
            say(f"  [{p}] already lifted from these files; skipping (--force lifts it again)")
        else:
            todo.append(p)
    steps = sota_steps(game)
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(todo))) as pool:
        futs = {pool.submit(run_chain, root, p, steps[p], python, paths, say): p for p in todo}
        for fut in concurrent.futures.as_completed(futs):
            fut.result()
            write_stamp(root, futs[fut], stamp)
    if todo:
        say(f"lifted {', '.join(todo)} in {int(time.time() - t0)} s")
    return todo


# ---- the licence library (the installer's licence step: tools/install/licence.py) -------------------------------------------------------------------------------
def licence_library(game):
    """The path of DuelSounds/Manaball.wav in a 2.15 Program folder, whatever case its folder and name are spelled in (the name as the table gives it if it is not there)."""
    here = game
    for part in builds.SOTA_LICENCE_LIBRARY["path"].split("/"):
        here = sota_file(here, part)
    return here


def licence_steps(game, generated=GENERATED):
    """{module: [(script, [arguments])...]} for the one library of the expansion's cabinet that the installer runs to write the licence value: lifted on its own, as a program (the runtime
    maps it as one and runs an export: src/port/main.c --call-export), into <generated>/lift_senclib. `game` is the 2.15 Program folder."""
    spec = builds.SOTA_LICENCE_LIBRARY
    return {spec["module"]: [("gen_dll.py", ["--main", "--dll", licence_library(game), "--out", f"{generated}/lift_{spec['module']}"])]}


def licence_fingerprint(root, game):
    """What the lifted licence library depends on: the lifter's own files and the library."""
    h = hashlib.sha256()
    files = sorted(glob.glob(os.path.join(root, "tools", "lift", "*.py"))) + [os.path.join(root, "src", "native", "layout.c"), licence_library(game)]
    for p in files:
        if not os.path.exists(p):
            continue
        h.update(os.path.basename(p).lower().encode() + b"\0")
        with open(p, "rb") as f:
            h.update(f.read())
    return h.hexdigest()


def lift_licence(root, game, python=sys.executable, pythonpath=(), force=False, say=print):
    """Lift the licence library (unless it was lifted from this very file already). The file is checked against its hash first: nothing but the retail file is lifted. Returns True when
    it lifted. Raises licence.LicenceError for a file that is not the retail one."""
    import licence
    licence.verify_library(licence.library_path(game))
    module = builds.SOTA_LICENCE_LIBRARY["module"]
    stamp = licence_fingerprint(root, game)
    if not force and is_lifted(root, module, stamp):
        say(f"  [{module}] already lifted from this file; skipping (--force lifts it again)")
        return False
    paths = [os.path.join(root, "tools", "lift")] + list(pythonpath)
    run_chain(root, module, licence_steps(game)[module], python, paths, say)
    write_stamp(root, module, stamp)
    return True


def python_command(python, script_path, args, paths):
    return [python, "-c", BOOT % (list(paths),), script_path] + list(args)


def fingerprint(root, game=GAME):
    """What a lifted program depends on: the game's programs and the lifter's own files."""
    h = hashlib.sha256()
    files = sorted(glob.glob(os.path.join(root, "tools", "lift", "*.py"))) + [os.path.join(root, "src", "native", "layout.c")]
    files += sorted(glob.glob(os.path.join(root, game, "*.EXE"))) + sorted(glob.glob(os.path.join(root, game, "*.DLL")))
    for p in files:
        if not os.path.exists(p):
            continue
        h.update(os.path.relpath(p, root).replace("\\", "/").encode() + b"\0")
        with open(p, "rb") as f:
            h.update(f.read())
    return h.hexdigest()


def read_stamps(root):
    try:
        with open(os.path.join(root, GENERATED, ".lifted")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_stamp(root, program, value):
    stamps = read_stamps(root)
    stamps[program] = value
    os.makedirs(os.path.join(root, GENERATED), exist_ok=True)
    with open(os.path.join(root, GENERATED, ".lifted"), "w") as f:
        json.dump(stamps, f)


def is_lifted(root, program, stamp):
    out = os.path.join(root, GENERATED, {"magic": "lift_magic_all"}.get(program, "lift_" + program))
    return read_stamps(root).get(program) == stamp and os.path.exists(os.path.join(out, "handlers_gen.c"))


def run_chain(root, program, steps, python, paths, say, env=None):
    for script, args in steps:
        t0 = time.time()
        say(f"  [{program}] {script} {' '.join(a for a in args if not a.startswith('--') and '/' in a)}")
        cmd = python_command(python, os.path.join(root, "tools", "lift", script), args, paths)
        r = subprocess.run(cmd, cwd=root, env=dict(os.environ, **(env or {})), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
        for line in r.stdout.strip().splitlines()[-3:] if r.returncode == 0 else r.stdout.strip().splitlines()[-30:]:
            say(f"      [{program}] {line}")
        if r.returncode != 0:
            raise RuntimeError(f"the lifter failed on {script} for {program} (exit {r.returncode})")
        say(f"  [{program}] done in {int(time.time() - t0)} s")


def lift_all(root, python=sys.executable, pythonpath=(), programs=("magic", "deck", "duel"), force=False, say=print, game=GAME):
    """Lift the programs (the ones not already lifted from these very files) in parallel. `pythonpath`: extra folders for the lifter (where pefile and capstone are)."""
    stamp = fingerprint(root, game)
    paths = [os.path.join(root, "tools", "lift")] + list(pythonpath)
    todo = []
    for p in programs:
        if not force and is_lifted(root, p, stamp):
            say(f"  [{p}] already lifted from these files; skipping (--force lifts it again)")
        else:
            todo.append(p)
    steps = lift_steps(game)
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(todo))) as pool:
        futs = {pool.submit(run_chain, root, p, steps[p], python, paths, say): p for p in todo}
        for fut in concurrent.futures.as_completed(futs):
            fut.result()
            write_stamp(root, futs[fut], stamp)
    if todo:
        say(f"lifted {', '.join(todo)} in {int(time.time() - t0)} s")
    return todo

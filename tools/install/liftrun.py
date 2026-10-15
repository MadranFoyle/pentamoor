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

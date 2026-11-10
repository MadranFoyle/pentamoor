#!/usr/bin/env python3
"""
smoke_install.py - made-up discs for the archive smoke test, and the installer's part of it. No game file is used or needed, and nothing in here is the game's.

    python tools/release/smoke_install.py make DIR       # write the made-up discs and the table of their hashes into DIR (what smoke_archive.py does first)

The real disc's fingerprints can never match a made-up disc, so the test has two halves, both run through the archive's own entry point (pentamoor-install, which on Windows is
pentamoor-install.bat and the embedded Python):

  * the wrong discs: a path that is not there, a file that is not a disc image, a disc image that is not the game's, the expansion's disc given first, --sota without --patch,
    no disc at all. Each must stop with exit status 1 and a message that names the problem, and write nothing;
  * the right disc, made up: a 1.0-shaped ISO 9660 image (Setup/data.z in the game's own archive format, the music and movie folders) whose programs the made-up table of known builds
    knows (smoke_inside.py install). The installer reads it, unpacks it, checks the programs, picks the compiler (on Windows the Zig in the archive, with a PATH of only Windows' own
    folders), compiles and links the three game modules and loads each into the runtime; run again it must see the game is installed. The two things that are replaced are said in
    its output (smoke_inside.py).

The discs are made with tools/install/fakediscs.py, the installer tests' own maker (not part of a release, so this runs from a checkout, with any Python 3: it needs no pytest).
"""
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def make(dest):
    """Write the discs into `dest` and return {"first": path, "expansion": path, "other": path, "text": path, "known": path}."""
    sys.path[:0] = [os.path.join(ROOT, "tools", "install"), os.path.join(ROOT, "tools", "lift")]
    try:
        import pytest  # noqa: F401
    except ImportError:                                                   # test_install.py imports pytest at the top; make_archive needs none of it
        sys.modules["pytest"] = types.ModuleType("pytest")
    import fakediscs
    world = fakediscs.World(dest)
    other = os.path.join(dest, "some other disc.iso")
    fakediscs.make_iso_tree(other, {"README.TXT": b"a disc that is not the game's", "Data/FILE.DAT": b"x" * 100}, label="NOT_MAGIC")
    text = os.path.join(dest, "notes.iso")
    with open(text, "w", encoding="utf-8") as f:
        f.write("this is a text file with an .iso name\n" * 20)
    known = os.path.join(dest, "known.json")
    with open(known, "w", encoding="utf-8") as f:
        json.dump([list(r) for r in world.known() if r[0] == "v1.0"], f)
    return {"first": world.iso1, "expansion": world.iso2, "other": other, "text": text, "known": known, "patch": world.patch}


# (what is given, what the message must say). {first} {expansion} {other} {text} {missing} are the made-up files.
WRONG_DISCS = [
    ("a path that is not there", ["{missing}"], "does not exist"),
    ("a file that is not a disc image", ["{text}"], "is not an ISO 9660 image"),
    ("a disc image that is not the game's", ["{other}"], "no Setup/data.z"),
    ("the expansion's disc given first", ["{expansion}"], "is the Spells of the Ancients disc"),
    ("--sota without --patch", ["{first}", "--sota", "{expansion}"], "--patch is missing"),
    ("no disc at all (no terminal to ask on)", [], "no disc image given"),
]


def installer_phase(smoke):
    """`smoke` is the driver (smoke_archive.Smoke): .root, .work, .check(name, ok, detail), .installer(args) -> (code, output), .inside(args) -> (code, output), .launcher_path(), .module_ext."""
    disc_dir = os.path.join(smoke.work, "discs")
    try:
        files = make(disc_dir)
    except Exception as e:                                                # (a failure to make the discs is the test's own, but it must say so)
        smoke.check("installer: made-up discs", False, f"could not make them: {type(e).__name__}: {e}")
        return
    smoke.check("installer: made-up discs", all(os.path.exists(p) for p in files.values()), f"{len(files)} files in {disc_dir}")
    files["dir"] = disc_dir
    files["missing"] = os.path.join(disc_dir, "no such disc.iso")
    for what, args, must in WRONG_DISCS:
        code, out = smoke.installer([a.format(**files) for a in args])
        ok = code == 1 and must in out and "install:" in out
        smoke.check(f"installer: wrong disc, {what}", ok, f"exit {code}, expected exit 1 and '{must}'" + ("" if ok else f"; output: {out.strip()[-400:]}"))
    wrote = os.path.exists(os.path.join(smoke.root, "sources", "installed"))
    smoke.check("installer: the wrong discs wrote nothing", not wrote, "sources/installed was created" if wrote else "no sources/installed")

    code, out = smoke.inside(["install", smoke.root, files["first"], files["known"]], timeout=1500)
    program = os.path.join(smoke.root, "sources", "installed", "Magic", "Program")
    wanted = ["disc: MTG v1.0", "game files:", "programs: all 3 are build v1.0", "game_magic: loads in the runtime", "game_deck: loads in the runtime",
              "game_duel: loads in the runtime", "built. Play with:"]
    missing = [w for w in wanted if w not in out]
    modules = [f"game_{p}.{smoke.module_ext}" for p in ("magic", "deck", "duel")]
    absent = [m for m in modules if not os.path.exists(os.path.join(smoke.root, m))]
    ok = code == 0 and not missing and not absent and os.path.exists(os.path.join(program, "MAGIC.EXE"))
    smoke.check("installer: made-up 1.0 disc installed and three modules built", ok,
                f"exit {code}" + (f"; the output lacks {missing}" if missing else "") + (f"; not built: {absent}" if absent else "") + ("" if ok else f"\n{out.strip()[-1500:]}"))
    for line in out.splitlines():
        if line.startswith("compiler:") or line.startswith("SMOKE NOTE"):
            print(f"      {line}")
    if not ok:
        return
    code, out = smoke.inside(["install", smoke.root, "-", files["known"]], timeout=1500)
    smoke.check("installer: run again, the game is already installed", code == 0 and "already extracted" in out and "built. Play with:" in out,
                f"exit {code}" + ("" if code == 0 and "already extracted" in out else f"; {out.strip()[-400:]}"))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "make":
        for k, v in make(os.path.abspath(sys.argv[2])).items():
            print(f"{k:10} {v}")
    else:
        print(__doc__)
        sys.exit(2)

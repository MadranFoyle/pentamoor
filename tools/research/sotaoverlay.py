#!/usr/bin/env python3
"""
sotaoverlay.py - copy one extracted install over another the way a Windows installer does (case-insensitively), for the research installs of Spells of the Ancients.

    sotaoverlay.py BASE_DIR OVERLAY_DIR DEST_DIR [--only SUBFOLDER] [--dry-run]

Makes DEST_DIR (which must not exist, or be empty) a copy of BASE_DIR, then copies every file of OVERLAY_DIR over it. Windows' file system ignores case, so `cards.dat` replaces
`CARDS.DAT` and `shellart` is the folder `ShellArt`; a plain `cp -R` on a case-sensitive disc would make two of each. The name that was there first is kept. Prints how many files
the overlay replaced (with different bytes), left alone (identical bytes) and added, and the names of the replaced ones (names only). `--only Program` takes just that folder of
OVERLAY_DIR (the extraction of an installer keeps its setup files and cabinets beside the install proper).

Used for: sources/installed_manalink_over215 = sources/installed_sota_215 (BASE) + sources/installed_manalink (OVERLAY), i.e. what the ManaLink 3.0 add-on installer
(setup.ins: reads HKLM\\SOFTWARE\\MicroProse\\Magic: The Gathering\\1.0 "Path2", requires Program\\menusx1.txt there, and copies its cabinet into Program) leaves behind.
It refuses to write through a symbolic link and never writes outside DEST_DIR.
"""
import filecmp
import os
import shutil
import sys


def tree(root):
    """{(lowercased relative path): (real relative path)} for every file under root."""
    out = {}
    for d, _dirs, files in os.walk(root):
        for f in files:
            rel = os.path.relpath(os.path.join(d, f), root)
            out[rel.lower()] = rel
    return out


def resolve(dest, rel):
    """The path in `dest` for `rel`, using the spelling of every part that already exists there (case-insensitively)."""
    cur, parts = dest, rel.replace("\\", "/").split("/")
    for i, part in enumerate(parts):
        have = None
        if os.path.isdir(cur):
            for name in os.listdir(cur):
                if name.lower() == part.lower():
                    have = name
                    break
        cur = os.path.join(cur, have or part)
    return cur


def main(argv):
    argv = list(argv)
    only = argv.pop(argv.index("--only") + 1) if "--only" in argv else None
    args = [a for a in argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in argv
    if len(args) != 3:
        print(__doc__)
        return 2
    base, over, dest = args
    if os.path.exists(dest) and os.listdir(dest):
        print("refusing: %s exists and is not empty" % dest, file=sys.stderr)
        return 2
    if not dry:
        shutil.copytree(base, dest, symlinks=False)
    replaced, same, added = [], 0, 0
    for low, rel in sorted(tree(over).items()):
        if only and not (low == only.lower() or low.startswith(only.lower() + os.sep)):
            continue
        target = resolve(dest, rel)
        src = os.path.join(over, rel)
        if os.path.islink(target) or os.path.islink(src):
            raise SystemExit("refusing: symbolic link at " + target)
        if os.path.exists(target) if not dry else os.path.exists(resolve(base, rel)):
            old = target if not dry else resolve(base, rel)
            if filecmp.cmp(src, old, shallow=False):
                same += 1
                continue
            replaced.append(os.path.relpath(target, dest) if not dry else rel)
        else:
            added += 1
        if not dry:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(src, target)
    print("replaced %d, identical %d, added %d" % (len(replaced), same, added))
    for r in replaced:
        print("  replaced: " + r)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

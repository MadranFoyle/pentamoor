#!/usr/bin/env python3
"""
overlay.py - put files into a game folder the way a Windows installer does, case-insensitively. The installer (sotainstall.py) uses `place` for every file of the expansion's
cabinet and of the patch. Run as a command it copies one extracted install over another (tools/research/sotaoverlay.py is the same command):

    overlay.py BASE_DIR OVERLAY_DIR DEST_DIR [--only SUBFOLDER] [--dry-run]

Makes DEST_DIR (which must not exist, or be empty) a copy of BASE_DIR, then copies every file of OVERLAY_DIR over it. Windows' file system ignores case, so `cards.dat` replaces
`CARDS.DAT` and `shellart` is the folder `ShellArt`; a plain `cp -R` on a case-sensitive disc would make two of each. The name that was there first is kept. Prints how many files
the overlay replaced (with different bytes), left alone (identical bytes) and added, and the names of the replaced ones (names only). `--only Program` takes just that folder of
OVERLAY_DIR (the extraction of an installer keeps its setup files and cabinets beside the install proper).

Used (research) for: sources/installed_manalink_over215 = sources/installed_sota_215 (BASE) + sources/installed_manalink (OVERLAY), i.e. what the ManaLink 3.0 add-on installer
(setup.ins: reads HKLM\\SOFTWARE\\MicroProse\\Magic: The Gathering\\1.0 "Path2", requires Program\\menusx1.txt there, and copies its cabinet into Program) leaves behind.
It refuses to write through a symbolic link and never writes outside DEST_DIR.

`place(dest, rel, data)` writes one file: `rel` is the path the cabinet or the patch gives (either slash); each part is looked up in `dest` ignoring case and the spelling that is
already there is kept. A path with `..`, a leading slash, a drive letter or a NUL is refused (OverlayError) before anything is written, and so is a symbolic link on the way.
It returns "added", "replaced" or "identical" (a file with the very same bytes is left alone).
"""
import filecmp
import os
import shutil
import sys


class OverlayError(Exception):
    pass


def safe_parts(rel):
    """The parts of a relative path from a cabinet or an archive (either slash); OverlayError when it could lead out of the folder."""
    text = rel.replace("\\", "/")
    if not text or text.startswith("/") or "\0" in text or ":" in text:
        raise OverlayError("the path %r is not a path inside the game's folder" % rel)
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        raise OverlayError("the path %r is not a path inside the game's folder" % rel)
    return parts


def place(dest, rel, data):
    """Write `data` as the file `rel` under `dest` (see the top of the file). Returns "added", "replaced" or "identical"."""
    parts = safe_parts(rel)
    target = resolve(dest, "/".join(parts))
    cur = dest
    for part in os.path.relpath(target, dest).split(os.sep):
        cur = os.path.join(cur, part)
        if os.path.islink(cur):
            raise OverlayError("refusing to write through a symbolic link: " + cur)
    if os.path.commonpath([os.path.realpath(dest), os.path.realpath(target)]) != os.path.realpath(dest):
        raise OverlayError("refusing to write outside the folder: " + target)
    if os.path.isdir(target):
        raise OverlayError("%s is a folder, not a file" % target)
    if os.path.exists(target):
        with open(target, "rb") as f:
            if f.read() == data:
                return "identical"
        result = "replaced"
    else:
        result = "added"
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as f:
        f.write(data)
    return result


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

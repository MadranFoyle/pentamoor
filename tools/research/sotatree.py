#!/usr/bin/env python3
"""
sotatree.py - compare two installed game folders (version 1.0 and 2.0): which files are the same, changed in size or content, only in one, by folder.

    sotatree.py OLD/Program NEW/Program [--list-new]

Names are compared without regard to case (Windows). Prints counts and sizes per top-level folder and per extension; --list-new lists the names that exist only in the new
folder (names and sizes only, no content). Nothing is written.
"""
import argparse
import hashlib
import os
from collections import Counter, defaultdict


def tree(root):
    out = {}
    for d, _, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            out[os.path.relpath(p, root).replace("\\", "/").lower()] = p
    return out


def digest(p):
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def top(rel):
    return rel.split("/")[0] if "/" in rel else "(program folder)"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--list-new", action="store_true")
    args = ap.parse_args()
    a, b = tree(args.old), tree(args.new)
    same, changed, only_old, only_new = [], [], [], []
    for k in sorted(set(a) | set(b)):
        if k in a and k in b:
            (same if os.path.getsize(a[k]) == os.path.getsize(b[k]) and digest(a[k]) == digest(b[k]) else changed).append(k)
        elif k in a:
            only_old.append(k)
        else:
            only_new.append(k)
    print("old %d files, new %d files: %d identical, %d in both but different, %d only in old, %d only in new" % (len(a), len(b), len(same), len(changed), len(only_old), len(only_new)))
    rows = defaultdict(Counter)
    for name, lst in (("identical", same), ("changed", changed), ("only old", only_old), ("only new", only_new)):
        for k in lst:
            rows[top(k)][name] += 1
    print("\n%-24s %9s %8s %8s %8s" % ("folder", "identical", "changed", "only old", "only new"))
    for t in sorted(rows):
        r = rows[t]
        print("%-24s %9d %8d %8d %8d" % (t, r["identical"], r["changed"], r["only old"], r["only new"]))
    ext = defaultdict(Counter)
    for name, lst in (("identical", same), ("changed", changed), ("only old", only_old), ("only new", only_new)):
        for k in lst:
            ext[os.path.splitext(k)[1] or "(none)"][name] += 1
    print("\n%-10s %9s %8s %8s %8s" % ("extension", "identical", "changed", "only old", "only new"))
    for t in sorted(ext, key=lambda e: -sum(ext[e].values())):
        r = ext[t]
        print("%-10s %9d %8d %8d %8d" % (t, r["identical"], r["changed"], r["only old"], r["only new"]))
    print("\nchanged, program folder and text/data tables:")
    for k in changed:
        if "/" not in k or os.path.splitext(k)[1] in (".txt", ".csv", ".dat"):
            print("   %-28s %9d -> %9d bytes" % (k, os.path.getsize(a[k]), os.path.getsize(b[k])))
    if args.list_new:
        print("\nonly in the new folder:")
        for k in only_new:
            print("   %-50s %9d" % (k, os.path.getsize(b[k])))


if __name__ == "__main__":
    main()

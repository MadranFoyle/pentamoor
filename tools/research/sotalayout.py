#!/usr/bin/env python3
"""
sotalayout.py - find the addresses of src/native/layout.c (the duel engine's globals and functions in MAGIC.EXE and DUEL.EXE, version 1.0) in the 2.0 programs.

    sotalayout.py OLD.EXE NEW.EXE MAGIC|DUEL

Functions go through the function matching of sotacmp.py (status: same / moved / changed / none, as in sotahooks.py); a global is looked up by the votes of the instructions
that use it. The record sizes of the duel engine are compared too: SLOT_STRIDE and SLOT_PLAYER_STRIDE (src/native/engine.h) are the constants the compiler multiplies by, so
a function that indexes the slot table shows the new constants in its multiplication (found by matching the old function's instruction stream to the new one and reading the
`imul` or the lea/shl chain that stands for it).
"""
import argparse
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sotacmp as sc  # noqa: E402
import sotahooks as sh  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def layout_addresses(program):
    text = open(os.path.join(ROOT, "src", "native", "layout.c")).read()
    block = text.split("const Layout LAYOUT_%s = {" % program, 1)[1].split("\n};", 1)[0]
    out = []
    for m in re.finditer(r"(?:\.([a-z_0-9]+)|\[((?:FN|CALLEE)_[A-Z_0-9]+)\]) = (0x[0-9a-fA-F]+)", block):
        name = m.group(1) or m.group(2)
        a = int(m.group(3), 16)
        if a:
            out.append((name, a, "fn" if m.group(2) else "data"))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("program", choices=["MAGIC", "DUEL"])
    args = ap.parse_args()
    oi, ni = sc.Image(args.old), sc.Image(args.new)
    old, _ = sc.scan_functions(oi)
    new, _ = sc.scan_functions(ni)
    M = sc.match(old, new)
    rows = []
    for name, a, kind in layout_addresses(args.program):
        if kind == "fn":
            r = sh.function_status(M, a, "fn")
        else:
            r = sh.data_status(M, a)
        r.update(name=name, kind=kind)
        rows.append(r)
    for r in rows:
        print("%-34s %-5s 0x%08x -> %-12s %-8s %s" % (r["name"], r["kind"], r["old"], ("0x%08x" % r["new"]) if r["new"] else "-", r["status"], r["how"]))
    print()
    for kind in ("fn", "data"):
        c = Counter(r["status"] for r in rows if r["kind"] == kind)
        print("%s: %d entries: %s" % (kind, sum(c.values()), dict(c)))


if __name__ == "__main__":
    main()

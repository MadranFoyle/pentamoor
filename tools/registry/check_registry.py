#!/usr/bin/env python3
"""Check the verified-name registry (tools/registry/verified_names.csv).

Always: no address is registered twice for a program, every row has a program, a kind and a name.

With the game installed (sources/installed/Magic/Program, or $PENTAMOOR_GAME): every function row must be an address where
tools/lift/fnscan.py finds a function in that program's executable (MAGIC.EXE or DUEL.EXE), and every global row an address
inside the executable's data sections. Without the game that part is skipped, and says so.

Any difference is a failure (exit 1).

    python3 tools/registry/check_registry.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import registry as reg  # noqa: E402

EXES = {"MAGIC": "MAGIC.EXE", "DUEL": "DUEL.EXE"}


def game_dir():
    return os.environ.get("PENTAMOOR_GAME") or os.path.join(reg.REPO, "sources", "installed", "Magic", "Program")


def check(rows=None, game=None):
    """Return the failures, each (program, address, name, what is wrong). `game`: the folder that holds MAGIC.EXE and DUEL.EXE, or None for the checks that need no game."""
    rows = reg.read_registry() if rows is None else rows
    failures, seen = [], {}
    for r in rows:
        key = (r["program"], r["address"])
        if key in seen:
            failures.append((r["program"], r["address"], r["name"], f"registered twice (also as `{seen[key]}`)"))
        seen[key] = r["name"]
        if r["program"] not in reg.PROGRAMS or r["kind"] not in ("function", "global") or not r["name"]:
            failures.append((r["program"], r["address"], r["name"], "not a program, kind and name"))
    if game:
        sys.path.insert(0, os.path.join(reg.REPO, "tools", "lift"))
        import fnscan  # noqa: PLC0415
        import pefile  # noqa: PLC0415
        for prog in reg.PROGRAMS:
            path = os.path.join(game, EXES[prog])
            pe = pefile.PE(path)
            base = pe.OPTIONAL_HEADER.ImageBase
            functions = fnscan.scan_file(path)
            data = [(base + s.VirtualAddress, base + s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData)) for s in pe.sections
                    if not s.Characteristics & 0x20000000]
            for r in rows:
                if r["program"] != prog:
                    continue
                a = r["address"]
                if r["kind"] == "function" and a not in functions:
                    failures.append((prog, a, r["name"], f"not a function start in {EXES[prog]}"))
                if r["kind"] == "global" and not any(lo <= a < hi for lo, hi in data):
                    failures.append((prog, a, r["name"], f"not in a data section of {EXES[prog]}"))
    return failures


def describe(item):
    prog, addr, name, what = item
    return f"{prog} {reg.fmt_addr(addr)} `{name}`: {what}"


def main():
    rows = reg.read_registry()
    game = game_dir()
    have_game = all(os.path.exists(os.path.join(game, e)) for e in EXES.values())
    failures = check(rows, game if have_game else None)
    for f in failures:
        print("MISMATCH:", describe(f))
    print(f"{len(rows)} registry rows checked{'' if have_game else ' (no game files: the addresses were not checked against the executables)'}: {len(failures)} mismatches")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

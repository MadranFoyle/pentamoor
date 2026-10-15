#!/usr/bin/env python3
"""
check_costs.py - does a hand-written native function charge as many instructions as its original runs?

A native function that stands in for the original in a hosted run (tools/lift/compare_hosted.py) adds to `native_cost_extra`
the number of instructions its original would have executed, so that the emulator's clock and thread switches come out the
original's. That number is easy to get wrong in a function with loops and branches. This runs each vector of a native
function twice, through the native function (build/harness) and through the same function lifted from the executable's machine
code (build/harness-lifted, which counts the instructions it executes), with every callee replayed the same way, and
compares the counts the two print as `cost`. A native callee of the function (memcpy, the AI's plan functions) charges itself
in both.

    make -C tools/difftest lifted
    python3 tools/difftest/check_costs.py VECTOR.json...

The lifted function is the native function's twin: gen_handlers.py lifts every native function's machine code as well (host
shadow mode compares the two on every call of a real game, see tools/lift/README.md; this checks the counts on recorded vectors).
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_vectors as rv  # noqa: E402


def run(harness, v, name=None, natives=False):
    v = dict(v)
    if name:
        v["function"] = name
    v["natives_only"] = natives
    if name:   # a lifted function runs on the recorded stack
        v["lifted_handlers"] = False
    proc = subprocess.run([harness], input=rv.protocol(v), capture_output=True, text=True)
    return rv.parse_output(proc.stdout)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("vectors", nargs="+")
    ap.add_argument("--native", default=os.path.join(HERE, "build", "harness"))
    ap.add_argument("--lifted", default=os.path.join(HERE, "build", "harness-lifted"))
    args = ap.parse_args()
    bad = 0
    for path in args.vectors:
        v = rv.load_vector(path)
        if v["address"] is None:
            print(f"SKIP {path}: no address")
            continue
        a = run(args.native, v)
        b = run(args.lifted, v, name="Handler_%08x" % v["address"], natives=True)
        if a["errors"] or b["errors"] or a["cost"] != b["cost"]:
            bad += 1
            print(f"DIFFER {os.path.basename(path)}: native {a['cost']} lifted {b['cost']} {a['errors'][:1]} {b['errors'][:1]}")
        elif len(args.vectors) <= 20:
            print(f"same   {os.path.basename(path)}: {a['cost']} instructions")
    print(f"{len(args.vectors)} vectors, {bad} differ")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

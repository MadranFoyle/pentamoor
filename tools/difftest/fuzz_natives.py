#!/usr/bin/env python3
"""
fuzz_natives.py - a hand-written native function against its own machine code, on states nobody recorded.

Takes recorded vectors of a native function, changes a few bytes of the memory each one provides (a life total, a flag, a count,
a card type, a pointer), and runs the mutated state twice with the same replayed callees: through the native function
(build/harness) and through the same function lifted from the executable's machine code (build/harness-lifted, with every
native callee native, as in check_costs.py). The lifted code is the original's behaviour, so any difference between the two is a
fault of the native function: the return value, the bytes written, the calls made (which callee, with which arguments), or the
memory read that the vector did not provide (a read the original would not make). Both running out of recorded callee results at the
same call, or reading undefined memory the same way, is agreement: the mutation took the function somewhere the recording
does not reach, and that is as far as it can be compared.

    make -C tools/difftest lifted
    python3 tools/difftest/fuzz_natives.py --rounds 500 VECTOR.json...
"""
import argparse
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import run_vectors as rv  # noqa: E402


def run(harness, v, name=None, natives=False):
    v = dict(v, natives_only=natives)
    if name:
        v["function"] = name
        v["lifted_handlers"] = False
    proc = subprocess.run([harness], input=rv.protocol(v), capture_output=True, text=True)
    out = rv.parse_output(proc.stdout)
    out["status"] = proc.returncode   # 0 or 3 (a call the vector does not have); anything else is an abort
    return out


def summary(o, v):
    """What has to agree between the two runs."""
    written = rv.final_written_bytes(o["written"])
    return (o["ret"] & ((1 << (o["retbits"] or 32)) - 1) if o["ret"] is not None and o["retbits"] else None,
            tuple(o["calls"]), tuple(sorted(written.items())), tuple(e.split(" (")[0][:60] for e in o["errors"]))


def mutate(v, rng, count):
    regions = [(a, bytearray(d)) for a, d in v["memory_in"]]
    for _ in range(count):
        a, d = regions[rng.randrange(len(regions))]
        i = rng.randrange(len(d))
        kind = rng.random()
        d[i] = rng.randrange(256) if kind < 0.4 else d[i] ^ (1 << rng.randrange(8)) if kind < 0.7 else (0, 1, 2, 0xff, 0x7f, 0x80)[rng.randrange(6)]
    return dict(v, memory_in=[(a, bytes(d)) for a, d in regions])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("vectors", nargs="+")
    ap.add_argument("--rounds", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--changes", type=int, default=3, help="bytes changed per round")
    ap.add_argument("--native", default=os.path.join(HERE, "build", "harness"))
    ap.add_argument("--lifted", default=os.path.join(HERE, "build", "harness-lifted"))
    ap.add_argument("--keep", default="", help="directory to write the vectors that differ to")
    args = ap.parse_args()
    rng = random.Random(args.seed)
    runs = differ = reached = skipped = unimplemented = 0
    for path in args.vectors:
        base = rv.load_vector(path)
        twin = "Handler_%08x" % base["address"]
        for r in range(args.rounds):
            v = mutate(base, rng, args.changes)
            a, b = run(args.native, v), run(args.lifted, v, twin, True)
            runs += 1
            if a["status"] not in (0, 3):   # the native function stopped on a path it does not implement (NATIVE_UNIMPLEMENTED)
                unimplemented += 1
                continue
            if a["fault_total"] or b["fault_total"]:   # the mutation led to memory the vector does not have: nothing to compare
                skipped += 1
                continue
            reached += not a["errors"]
            if summary(a, v) != summary(b, v):
                differ += 1
                if differ <= 10:
                    print(f"DIFFER {os.path.basename(path)} round {r}: native ret {a['ret']} errors {a['errors'][:1]} | lifted ret {b['ret']} errors {b['errors'][:1]}")
                    if a["calls"] != b["calls"]:
                        print(f"    calls: native {a['calls'][:3]} lifted {b['calls'][:3]}")
                    wa, wb = rv.final_written_bytes(a["written"]), rv.final_written_bytes(b["written"])
                    delta = [(hex(k), wa.get(k), wb.get(k)) for k in sorted(set(wa) | set(wb)) if wa.get(k) != wb.get(k)]
                    if delta:
                        print(f"    bytes written differently (addr, native, lifted): {delta[:6]}")
                if args.keep:
                    import json  # noqa: PLC0415
                    os.makedirs(args.keep, exist_ok=True)
                    with open(os.path.join(args.keep, f"differ_{os.path.basename(path)[:-5]}_{r}.json"), "w") as f:
                        json.dump(rv_to_json(v), f)
    print(f"{runs} mutated runs: {unimplemented} reached a path the native function does not implement, {skipped} read memory the vector lacks, {runs - skipped - unimplemented} compared ({reached} ran to the end on the recorded callee results), {differ} differ")
    return 1 if differ else 0


def rv_to_json(v):
    out = {"function": v["function"], "program": v["program"], "address": "0x%08x" % v["address"], "args": v["args"],
           "expected_return": 0, "memory_in": [{"addr": "0x%08x" % a, "bytes": d.hex()} for a, d in v["memory_in"]],
           "calls": [{"callee": "0x%08x" % c["callee"], "name": c["name"], "args": c["args"], "return": c["return"],
                      "memory_writes": [{"addr": "0x%08x" % a, "bytes": d.hex()} for a, d in c["writes"]]} for c in v["calls"]],
           "memory_out_expected": [], "memory_out_exhaustive": False}
    return out


if __name__ == "__main__":
    sys.exit(main())

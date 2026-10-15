#!/usr/bin/env python3
"""
compare_hosted.py - does the game, with some of its functions replaced, do exactly what the original does?

Runs the same script twice in the emulator, once on the original and once with the lifted functions (and the native ones that
are cheap to make exact) standing in for the originals (`--native-exact`: a replaced function spends the instructions its
original would have run, so the machine's clock, its thread switches and what the game times with them are the original's),
and compares what the guest did: a running hash of every import call (which thread, which function, from where) printed
every N calls with the virtual time, the state digests the script asks for, and the totals. When they part, it runs both
again printing the calls around the first block that differs and shows the first call that is not the same.

    python3 tools/lift/compare_hosted.py --seconds 90 --script "$(cat script.txt)"

Needs the game (sources/installed/...), the generated code (tools/lift/gen_handlers.py) and the library
(make -C tools/difftest host). The hand-written native functions are left to the original by default (their cost in
instructions is an average, not exact); --with-natives replaces them too and accepts that the two then agree only until the
first search the average cost changes.
"""
import argparse
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "tools", "emu_spike"))
from winemu.native_host import exact_native_names  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SPEC = os.path.join(ROOT, "sources", "generated", "lift", "handler_spec.json")


def all_native_names():
    import ctypes  # noqa: PLC0415
    from winemu.native_host import DEFAULT_LIB  # noqa: PLC0415
    lib = ctypes.CDLL(os.environ.get("NATIVE_LIB") or DEFAULT_LIB)
    lib.host_native_name.restype = ctypes.c_char_p
    lib.host_native_name.argtypes = [ctypes.c_int]
    return [lib.host_native_name(i).decode() for i in range(lib.host_native_count())]


def run(args, hosted, every, detail=None):
    cmd = [sys.executable, "-m", "winemu.run", "--exe", args.exe, "--seconds", str(args.seconds), "--script", args.script]
    if hosted:
        names = [e["name"] for e in json.load(open(SPEC)) if e["lifted"]] + exact_native_names()
        if args.shadow:
            exact = set(exact_native_names(shadow=True))
            inexact = [n for n in all_native_names() if n not in exact]
            cmd += ["--native", "--native-exact", "--native-shadow"] + (["--native-skip", ",".join(inexact)] if inexact else [])
        elif args.with_natives:
            cmd += ["--native", "--native-exact"] + (["--native-costs", args.costs] if args.costs else [])
        else:
            cmd += ["--native", "--native-exact", "--native-only", ",".join(names)]
    env = dict(os.environ, EMU_HARD_STOP=str(args.hard_stop), EMU_CALL_HASH=str(every))
    if detail:
        env["EMU_CALL_DETAIL"] = "%d:%d" % detail
    done = subprocess.run(cmd, cwd=os.path.join(ROOT, "tools", "emu_spike"), capture_output=True, text=True, env=env)
    if done.stderr.strip():
        print(done.stderr[-3000:])
    return done.stdout


def blocks(text):
    return re.findall(r"\[calls (\d+)\] (\w+) vt ([\d.]+)", text)


def summary(text):
    return [line.strip() for line in text.splitlines()
            if "[digest" in line or line.startswith("finished") or "emulation error" in line or "[shadow]" in line]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--exe", default=os.path.join(ROOT, "sources", "installed", "Magic", "Program", "DUEL.EXE"))
    ap.add_argument("--seconds", type=float, default=90)
    ap.add_argument("--script", default="")
    ap.add_argument("--every", type=int, default=5000, help="calls per hash block")
    ap.add_argument("--hard-stop", type=int, default=3000, help="real seconds before a run is cut off")
    ap.add_argument("--shadow", action="store_true", help="every native function too, in shadow mode: each call is also run as the original's "
                    "machine code and compared (differences are reported on stderr); the run is then the original's however the native code counts")
    ap.add_argument("--with-natives", action="store_true", help="replace the hand-written native functions too")
    ap.add_argument("--costs", default="", help="with --with-natives: the file from --native-calibrate")
    args = ap.parse_args()
    args.exe = os.path.abspath(args.exe)

    with cf.ThreadPoolExecutor(2) as ex:
        orig, host = ex.map(lambda h: run(args, h, args.every), (False, True))
    for name, text in (("original", orig), ("hosted", host)):
        print(f"{name}:")
        for line in summary(text):
            print("   ", line)
    a, b = blocks(orig), blocks(host)
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            first = int(x[0]) - args.every + 1, int(x[0])
            print(f"\nthe runs part in calls {first[0]}..{first[1]} (original {x[1:]}, hosted {y[1:]})")
            with cf.ThreadPoolExecutor(2) as ex:
                o2, h2 = ex.map(lambda h: run(args, h, 10 ** 9, first), (False, True))
            pat = r"\[call (\d+)\] (t\d+ \S+ <- 0x\w+) vt ([\d.]+)"
            ca, cb = re.findall(pat, o2), re.findall(pat, h2)
            for k, (p, q) in enumerate(zip(ca, cb)):
                if p != q:
                    print("first call that is not the same:")
                    for j in range(max(0, k - 3), min(len(ca), len(cb), k + 3)):
                        print("   original", ca[j], "| hosted", cb[j])
                    break
            return 1
    if len(a) != len(b):
        print(f"\nthe same for {min(len(a), len(b))} blocks, but one run ended before the other ({len(a)} and {len(b)} blocks)")
        return 1
    print(f"\nidentical: {len(a)} blocks of {args.every} import calls, the same threads, functions, callers and virtual times")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Run difftest vectors against the native functions in src/native/ and report pass or fail.

Each vector (SPEC.md) is one call of one original function on a memory snapshot. The runner builds
tools/difftest/build/harness if it is missing or older than its sources, feeds it each vector, and
compares the return value, the calls made to functions that are not native, and the memory
afterwards with what the vector expects.

    python3 tools/difftest/run_vectors.py                 # every tools/difftest/vectors/*.json
    python3 tools/difftest/run_vectors.py -v path/to/x.json more/*.json
    python3 tools/difftest/run_vectors.py --strict        # an unimplemented code path is a failure

Exit status: 0 if nothing failed, 1 if a vector failed or could not be run.
Standard library only.
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
NATIVE = os.path.join(REPO, "src", "native")
SOURCES = [os.path.join(HERE, "harness.c")] + [os.path.join(NATIVE, f) for f in (
    "mem.c", "engine.c", "layout.c", "spell_stack.c", "card_query.c", "event_context.c", "card_util.c", "ai_plan.c", "card_scan.c", "crt.c", "ai_state.c", "ai_eval.c")]
HEADERS = [os.path.join(NATIVE, f) for f in ("mem.h", "engine.h")]
DEFAULT_HARNESS = os.path.join(HERE, "build", "harness")
CFLAGS = ["-std=c99", "-O1", "-g", "-Wall", "-Wextra"]
PROGRAMS = ("MAGIC", "DUEL")
MASK32 = 0xFFFFFFFF


class VectorError(Exception):
    """The vector itself is malformed."""


# --------------------------------------------------------------------------------------------------
# Building the harness


def build_harness(path=DEFAULT_HARNESS, cc=None, force=False):
    cc = cc or os.environ.get("CC") or "cc"
    newest = max(os.path.getmtime(p) for p in SOURCES + HEADERS)
    if not force and os.path.exists(path) and os.path.getmtime(path) >= newest:
        return path
    if not shutil.which(cc):
        raise SystemExit(f"no C compiler '{cc}' (set CC)")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cmd = [cc] + CFLAGS + ["-o", path] + SOURCES
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit("harness build failed:\n" + " ".join(cmd) + "\n" + proc.stderr)
    if proc.stderr.strip():
        print(proc.stderr, file=sys.stderr)
    return path


# --------------------------------------------------------------------------------------------------
# Reading vectors


def num(v, what):
    """An int from a JSON int or a string such as "0x006826c4" or "-1"; wrapped to 32 bits."""
    if isinstance(v, bool) or not isinstance(v, (int, str)):
        raise VectorError(f"{what}: expected a number, got {v!r}")
    try:
        n = int(v, 0) if isinstance(v, str) else v
    except ValueError:
        raise VectorError(f"{what}: not a number: {v!r}")
    if not -(1 << 31) <= n <= MASK32:
        raise VectorError(f"{what}: {v!r} does not fit in 32 bits")
    return n & MASK32


def region_bytes(region, what):
    """(addr, bytes) of a {addr, dwords} or {addr, bytes} region."""
    if not isinstance(region, dict) or "addr" not in region:
        raise VectorError(f"{what}: expected an object with 'addr'")
    addr = num(region["addr"], f"{what}.addr")
    keys = [k for k in ("dwords", "bytes") if k in region]
    if len(keys) != 1:
        raise VectorError(f"{what}: give exactly one of 'dwords' or 'bytes'")
    if keys[0] == "dwords":
        data = b"".join(num(d, f"{what}.dwords[{i}]").to_bytes(4, "little")
                        for i, d in enumerate(region["dwords"]))
    else:
        raw = region["bytes"]
        if isinstance(raw, str):
            try:
                data = bytes.fromhex(raw)
            except ValueError:
                raise VectorError(f"{what}.bytes: not hex: {raw!r}")
        elif isinstance(raw, list):
            values = [num(b, f"{what}.bytes[{i}]") for i, b in enumerate(raw)]
            bad = [i for i, b in enumerate(values) if b > 0xFF]
            if bad:
                raise VectorError(f"{what}.bytes[{bad[0]}]: {raw[bad[0]]!r} is not a byte")
            data = bytes(values)
        else:
            raise VectorError(f"{what}.bytes: expected a hex string or a list of bytes")
    if not data:
        raise VectorError(f"{what}: empty region")
    if addr + len(data) > 1 << 32:
        raise VectorError(f"{what}: runs past the end of the address space")
    return addr, data


def load_vector(path):
    with open(path, encoding="utf-8") as f:
        try:
            v = json.load(f)
        except json.JSONDecodeError as e:
            raise VectorError(f"not JSON: {e}")
    if not isinstance(v, dict):
        raise VectorError("a vector is a JSON object")
    for key in ("function", "program", "args", "expected_return"):
        if key not in v:
            raise VectorError(f"missing '{key}'")
    if v["program"] not in PROGRAMS:
        raise VectorError(f"program must be one of {', '.join(PROGRAMS)}")
    if not isinstance(v["args"], list):
        raise VectorError("'args' must be a list")
    out = {
        "function": v["function"],
        "program": v["program"],
        "address": num(v["address"], "address") if "address" in v else None,
        "args": [num(a, f"args[{i}]") for i, a in enumerate(v["args"])],
        "expected_return": num(v["expected_return"], "expected_return"),
        "return_bits": v.get("return_bits"),
        "lifted_handlers": bool(v.get("lifted_handlers", False)),
        "handler_stack_pointer": num(v["handler_stack_pointer"], "handler_stack_pointer") if "handler_stack_pointer" in v else None,
        "stack_pointer": num(v["stack_pointer"], "stack_pointer") if "stack_pointer" in v else None,
        "memory_in": [region_bytes(r, f"memory_in[{i}]") for i, r in enumerate(v.get("memory_in", []))],
        "memory_out": [region_bytes(r, f"memory_out_expected[{i}]")
                       for i, r in enumerate(v.get("memory_out_expected", []))],
        "exhaustive": bool(v.get("memory_out_exhaustive", False)),
        "calls": [],
    }
    for i, c in enumerate(v.get("calls", [])):
        if not isinstance(c, dict) or "callee" not in c:
            raise VectorError(f"calls[{i}]: expected an object with 'callee'")
        out["calls"].append({
            "callee": num(c["callee"], f"calls[{i}].callee"),
            "name": c.get("name", ""),
            "args": [num(a, f"calls[{i}].args[{j}]") for j, a in enumerate(c.get("args", []))],
            "return": num(c.get("return", 0), f"calls[{i}].return"),
            "writes": [region_bytes(r, f"calls[{i}].memory_writes[{j}]")
                       for j, r in enumerate(c.get("memory_writes", []))],
        })
    if out["return_bits"] not in (None, 0, 8, 16, 32):
        raise VectorError("return_bits must be 0 (the return value is not compared: the function leaves EAX as it was), 8, 16 or 32")
    return out


# --------------------------------------------------------------------------------------------------
# Running one vector


def protocol(v):
    lines = [f"program {v['program']}", f"function {v['function']}"]
    if v.get("natives_only"):
        lines.append("natives")   # a lifted function whose native callees run native and everything else is replayed
    if v["address"] is not None:
        lines.append(f"entry 0x{v['address']:08x}")
    if v.get("lifted_handlers"):
        lines.append("lifted")   # card handlers run lifted (needs the harness built with `make lifted`)
        if v.get("handler_stack_pointer") is not None:
            lines.append(f"handler_esp 0x{v['handler_stack_pointer']:08x}")
    if v.get("stack_pointer") is not None:
        lines.append(f"esp 0x{v['stack_pointer']:08x}")
    lines += [f"arg 0x{a:08x}" for a in v["args"]]
    lines += [f"mem 0x{addr:08x} {data.hex()}" for addr, data in v["memory_in"]]
    for c in v["calls"]:
        lines.append(f"call 0x{c['callee']:08x} 0x{c['return']:08x} {len(c['args'])} "
                     + " ".join(f"0x{a:08x}" for a in c["args"]))
        lines += [f"callmem 0x{addr:08x} {data.hex()}" for addr, data in c["writes"]]
    lines += [f"read 0x{addr:08x} {len(data)}" for addr, data in v["memory_out"]]
    lines.append("run")
    return "\n".join(lines) + "\n"


def parse_output(text):
    out = {"ret": None, "retbits": 32, "cost": None, "calls": [], "written": [], "faults": [], "fault_total": 0,
           "reads": {}, "errors": []}
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        tag = parts[0]
        if tag == "retbits":
            out["retbits"] = int(parts[1])
        elif tag == "ret":
            out["ret"] = int(parts[1], 16)
        elif tag == "cost":
            out["cost"] = int(parts[1])
        elif tag == "call":
            out["calls"].append((int(parts[2], 16), [int(a, 16) for a in parts[4:]]))
        elif tag == "written":
            out["written"].append((int(parts[1], 16), parts[2] if len(parts) > 2 else ""))
        elif tag == "fault":
            out["faults"].append(int(parts[1], 16))
        elif tag == "faults":
            out["fault_total"] = int(parts[1])
        elif tag == "read":
            out["reads"][int(parts[1], 16)] = parts[2] if len(parts) > 2 else ""
        elif tag == "error":
            out["errors"].append(line[len("error "):])
    return out


def final_written_bytes(written):
    """{addr: final byte} of everything the native code wrote."""
    final = {}
    for addr, hexbytes in written:
        for i in range(0, len(hexbytes), 2):
            final[addr + i // 2] = int(hexbytes[i:i + 2], 16)
    return final


def compare(v, out):
    """List of failure messages (empty when the vector passes)."""
    fails = list(out["errors"])
    bits = out["retbits"] if v["return_bits"] is None else v["return_bits"]
    mask = (1 << bits) - 1
    if bits == 0:
        pass
    elif out["ret"] is None and not out["errors"]:
        fails.append("the harness returned no value")
    elif out["ret"] is not None and (out["ret"] & mask) != (v["expected_return"] & mask):
        fails.append(f"return 0x{out['ret'] & mask:x}, expected 0x{v['expected_return'] & mask:x}"
                     + (f" (low {bits} bits)" if bits != 32 else ""))
    # Calls to functions that are not native, in order.
    made, want = out["calls"], v["calls"]
    for i, (c, (addr, args)) in enumerate(zip(want, made)):
        label = f"call {i}" + (f" ({c['name']})" if c["name"] else "")
        if addr != c["callee"]:
            fails.append(f"{label}: went to 0x{addr:08x}, expected 0x{c['callee']:08x}")
        elif args != c["args"]:
            fails.append(f"{label}: args {[hex(a) for a in args]}, expected {[hex(a) for a in c['args']]}")
    if len(made) < len(want) and not out["errors"]:
        missing = ", ".join(f"0x{c['callee']:08x}" + (f" {c['name']}" if c["name"] else "")
                            for c in want[len(made):])
        fails.append(f"{len(want) - len(made)} expected call(s) not made: {missing}")
    # Memory the snapshot did not provide.
    if out["fault_total"]:
        shown = ", ".join(f"0x{a:08x}" for a in out["faults"][:8])
        more = f" (+{out['fault_total'] - 8} more)" if out["fault_total"] > 8 else ""
        fails.append(f"read {out['fault_total']} undefined byte(s), add them to memory_in: {shown}{more}")
    # Memory afterwards.
    for addr, data in v["memory_out"]:
        got = out["reads"].get(addr, "")
        if got != data.hex():
            fails.append(f"memory at 0x{addr:08x}: {format_hex(got)}, expected {format_hex(data.hex())}")
    if v["exhaustive"]:
        before = {}
        for addr, data in v["memory_in"]:
            for i, b in enumerate(data):
                before[addr + i] = b
        for c in v["calls"]:
            for addr, data in c["writes"]:
                for i, b in enumerate(data):
                    before[addr + i] = b
        covered = set()
        for addr, data in v["memory_out"]:
            covered.update(range(addr, addr + len(data)))
        stray = sorted(a for a, b in final_written_bytes(out["written"]).items()
                       if a not in covered and before.get(a) != b)
        if stray:
            fails.append("changed but not in memory_out_expected: "
                         + ", ".join(f"0x{a:08x}" for a in stray[:12]) + (" ..." if len(stray) > 12 else ""))
    return fails


def format_hex(h):
    return " ".join(h[i:i + 8] for i in range(0, len(h), 8)) if h else "(nothing)"


def run_vector(path, harness, timeout=30):
    """(status, messages, details). status is PASS, FAIL, UNIMPLEMENTED or ERROR."""
    try:
        v = load_vector(path)
    except (VectorError, OSError) as e:
        return "ERROR", [f"bad vector: {e}"], None
    try:
        proc = subprocess.run([harness], input=protocol(v), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "FAIL", [f"timed out after {timeout} s"], None
    if "native: unimplemented" in proc.stderr:
        what = proc.stderr.split("native: unimplemented:", 1)[1].strip().splitlines()[0]
        return "UNIMPLEMENTED", [what], None
    out = parse_output(proc.stdout)
    if proc.returncode not in (0, 3):
        return "ERROR", [f"harness exited with {proc.returncode}", proc.stderr.strip()], out
    if proc.returncode == 3 and out["ret"] is None and not out["calls"] and out["errors"]:
        return "ERROR", out["errors"], out   # the harness rejected the vector before running
    fails = compare(v, out)
    return ("FAIL" if fails else "PASS"), fails, out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("vectors", nargs="*", help="vector files (default: tools/difftest/vectors/*.json)")
    ap.add_argument("--harness", help="use this harness binary instead of building one")
    ap.add_argument("--cc", help="C compiler for the harness (default: $CC or cc)")
    ap.add_argument("--rebuild", action="store_true", help="rebuild the harness even if it looks current")
    ap.add_argument("--strict", action="store_true", help="count UNIMPLEMENTED as a failure")
    ap.add_argument("-v", "--verbose", action="store_true", help="show the calls and writes of every vector")
    args = ap.parse_args(argv)

    paths = args.vectors or sorted(glob.glob(os.path.join(HERE, "vectors", "*.json")))
    if not paths:
        print("no vectors found")
        return 1
    harness = args.harness or build_harness(cc=args.cc, force=args.rebuild)
    counts = {"PASS": 0, "FAIL": 0, "UNIMPLEMENTED": 0, "ERROR": 0}
    for path in paths:
        status, messages, out = run_vector(path, harness)
        counts[status] += 1
        print(f"{status:13} {os.path.relpath(path)}")
        for m in messages:
            print(f"              {m}")
        if args.verbose and out:
            for addr, cargs in out["calls"]:
                print(f"              call 0x{addr:08x}({', '.join(hex(a) for a in cargs)})")
            for addr, hexbytes in out["written"]:
                print(f"              wrote 0x{addr:08x} = {format_hex(hexbytes)}")
    print(f"{len(paths)} vectors: {counts['PASS']} passed, {counts['FAIL']} failed, "
          f"{counts['UNIMPLEMENTED']} unimplemented, {counts['ERROR']} errors")
    bad = counts["FAIL"] + counts["ERROR"] + (counts["UNIMPLEMENTED"] if args.strict else 0)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

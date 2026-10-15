#!/usr/bin/env python3
"""
scan_diff.py - find the handler where a native scan with lifted handlers first departs from the original.

For a scan vector recorded with RECORD_LIFTED_HANDLERS=1 that the lifted-handlers harness (make -C tools/difftest lifted)
fails, this runs the vector with LIFT_TRACE, lines up the calls each lifted handler made with the calls the recording says
that handler made (the vector's handler_log gives where each handler's calls start), and prints the first handler whose
calls differ.

    python3 tools/lift/scan_diff.py tools/difftest/build/harness-lifted VECTOR.json
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "difftest"))
import run_vectors as rv  # noqa: E402


def native_entries():
    text = open(os.path.join(ROOT, "src", "native", "layout.c")).read()
    block = text[text.index("const Layout LAYOUT_DUEL"):]
    return {int(a, 16) for a in re.findall(r"\[FN_\w+\] = (0x[0-9a-fA-F]+)", block[block.index(".entry"):])}


def main():
    harness, path = sys.argv[1], sys.argv[2]
    raw = json.load(open(path))
    log = raw.get("handler_log")
    if not log:
        sys.exit("the vector has no handler_log: record it again with the current record_vectors.py")
    v = rv.load_vector(path)
    env = dict(os.environ, LIFT_TRACE="1")
    if raw.get("handler_dumps"):
        env["LIFT_DUMP"] = os.environ.get("LIFT_DUMP", "0x6826c0:0x120,0x6881e0:0x120,0x68ef40:0x60,0x666408:8")
    proc = subprocess.run([harness], input=rv.protocol(v), capture_output=True, text=True, env=env)
    natives = native_entries()
    dumps_lifted = [l.split()[1:] for l in proc.stderr.splitlines() if l.startswith("dump")]
    ran, cur = [], None
    for line in proc.stderr.splitlines():
        m = re.match(r"lifted: Handler_([0-9a-f]+)", line)
        if m:
            cur = [int(m.group(1), 16), []]
            ran.append(cur)
            continue
        m = re.match(r"  calls 0x([0-9a-f]+)", line)
        if m and cur is not None and int(m.group(1), 16) not in natives:
            cur[1].append(int(m.group(1), 16))
    original_natives = [e for e in raw.get("native_trace", []) if not e[0].startswith("Handler_")]
    if original_natives:
        lifted_natives = []
        for line in proc.stderr.splitlines():
            m = re.match(r"  native (\w+)\((.*)\) -> (-?\d+)", line)
            if m:
                lifted_natives.append([m.group(1)] + ([int(x) for x in m.group(2).split(", ")] if m.group(2) else []) + ["->", int(m.group(3))])
        for k, (o, g) in enumerate(zip(original_natives, lifted_natives)):
            if o[:-1] != g[:-1] or (len(o) == len(g) and o[-1] != g[-1]):
                print(f"native call {k} differs: original {o}, lifted {g}")
                break
        else:
            if len(original_natives) != len(lifted_natives):
                print(f"native calls: original {len(original_natives)}, lifted {len(lifted_natives)}")
    expected = [int(c["callee"], 16) if isinstance(c["callee"], str) else c["callee"] for c in raw["calls"]]
    original_dumps = raw.get("handler_dumps")
    if original_dumps and dumps_lifted:
        for i, (orig, got) in enumerate(zip(original_dumps, dumps_lifted)):
            for r, (o, g) in enumerate(zip(orig, got)):
                diff = [k // 2 for k in range(0, len(o), 2) if g[k:k + 2] != "??" and o[k:k + 2] != g[k:k + 2]]
                if diff:
                    print(f"memory range {r} differs before handler {i} (0x{int(log[i][0], 16):08x}): at offsets {diff[:12]}"
                          f"{' ...' if len(diff) > 12 else ''}  original {[o[2 * d:2 * d + 2] for d in diff[:6]]} lifted {[g[2 * d:2 * d + 2] for d in diff[:6]]}")
                    break
            else:
                continue
            break
    for i, (handler, calls) in enumerate(ran):
        start = log[i][4] if i < len(log) else len(expected)
        end = log[i + 1][4] if i + 1 < len(log) else len(expected)
        want = expected[start:end]
        same_handler = i < len(log) and int(log[i][0], 16) == handler
        print(f"handler {i}: lifted 0x{handler:08x}, original 0x{int(log[i][0], 16):08x} args {log[i][1:4]}" if i < len(log) else f"handler {i}: lifted 0x{handler:08x} (the original ran fewer)")
        if not same_handler or calls != want:
            print("   lifted calls:  ", [hex(c) for c in calls])
            print("   original calls:", [hex(c) for c in want])
            print("   first difference is in this handler")
            return
    print("every handler made the calls the recording says; the difference is in what they wrote")


if __name__ == "__main__":
    main()

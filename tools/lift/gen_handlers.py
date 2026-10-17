#!/usr/bin/env python3
"""
gen_handlers.py - lift every card handler of a program with x86lift.py.

A card's behaviour lives in a handler function handler(player, slot, event), one pointer per master-card-table record
(+0x10). This reads those pointers out of the executable the user owns, lifts each distinct handler to C, and writes
  OUT/handlers_gen.c   the lifted functions and the tables the harness consults
  OUT/handler_spec.json  per handler: address, size, whether it lifted (and why not), and the exact functions it calls
Nothing here is committed: the output is derived from the game's machine code, so it stays under sources/ (git-ignored).

    python3 tools/lift/gen_handlers.py --program duel --exe sources/installed/Magic/Program/DUEL.EXE --out sources/generated/lift
"""
import argparse
import json
import os
import struct
import sys

import pefile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from x86lift import Lifter, Unsupported  # noqa: E402
from import_signatures import signature  # noqa: E402
from fnscan import scan_pe  # noqa: E402
from builds import file_build_id  # noqa: E402
import libsigs  # noqa: E402
import mastertable  # noqa: E402

# Imports a handler may call, as (argument count, bytes the callee pops). Anything else is refused.
KNOWN_IMPORTS = {"Sleep": (1, 4), "_assert": (3, 0), "_itoa": (3, 0), "rand": (0, 0), "memcpy": (3, 0), "memset": (3, 0),      # the last two: the C runtime DLL's (cdecl), which MAGIC.EXE imports where DUEL.EXE carries its own copies
                 "GetTickCount": (0, 0), "SendMessageA": (4, 16), "OutputDebugStringA": (1, 4), "DeviceIoControl": (8, 32),
                 "sprintf": (12, 0)}   # takes a variable number of arguments: a call out copies twelve stack words, the format uses what it needs
STUB_BASE = 0x006C5800   # where winemu/run.py `inject` puts a stand-in for each import while it injects: free space after the
STUB_STRIDE = 0x20       # last section's code, in a page the executable maps

# C runtime functions the program carries itself that take a variable number of arguments (`_sprintf`, `_fscanf`, `_sscanf`, `_fprintf` of DUEL.EXE; MAGIC.EXE
# imports its own from the C runtime's DLL): a call out passes a fixed count, so a function that calls one is not lifted.
VARIADIC = {"duel": {0x4D9720, 0x4DCEE0, 0x4DD040, 0x4DE4F0}, "magic": set(), "shandalar": set()}

PROGRAMS = {  # master card table base, the code range its handler pointers fall in
    "duel": dict(master=0x004FF590, code=(0x401000, 0x4F0000)),
    "magic": dict(master=0x0051AEB8, code=(0x401000, 0x510000)),
    # Spells of the Ancients 2.15 (shandalar.exe, the successor of MAGIC.EXE): records of 0x48 bytes, found by their pattern (mastertable.py) in the program's own code range
    "shandalar": dict(master=None, stride=0x48, code=None),
}


def native_entries(program):
    """Addresses of the program's native functions (src/native/layout.c)."""
    import re  # noqa: PLC0415
    text = open(os.path.join(ROOT, "src", "native", "layout.c")).read()
    if f"const Layout LAYOUT_{program.upper()} = {{" not in text:
        return set()          # a build the hand-written engine has no layout for
    block = text.split(f"const Layout LAYOUT_{program.upper()} = {{", 1)[1].split("\n};", 1)[0]
    return {int(m.group(1), 16) for m in re.finditer(r"\[FN_[A-Z_0-9]+\] = (0x[0-9a-fA-F]+)", block)} - {0}


def handler_addresses(pe, master, code):
    """Distinct handler pointers (record +0x10) of the master card table, in order of first use."""
    base = pe.OPTIONAL_HEADER.ImageBase
    out, bad = [], 0
    for i in range(1000):
        h = struct.unpack_from("<I", pe.get_data(master + i * 0x34 - base, 0x34), 0x10)[0]
        if code[0] <= h < code[1]:
            bad = 0
            if h not in out:
                out.append(h)
        else:
            bad += 1
            if bad >= 3:
                break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--program", choices=sorted(PROGRAMS), default="duel")
    ap.add_argument("--exe", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--extra", default="", help="more functions to lift besides the card handlers: hex addresses, comma-separated "
                    "(they are lifted and verified exactly as handlers are, and named Handler_<address> too)")
    ap.add_argument("--extra-file", default="", help="a file of functions to lift besides the handlers, one per line: a hex address, "
                    "then a label (tools/lift/ai_functions.txt)")
    ap.add_argument("--no-handlers", action="store_true", help="lift only the extra functions, not the card handlers (for recording)")
    ap.add_argument("--all", action="store_true", help="lift every function the scan of the program finds (fnscan.py), not only the handlers")
    args = ap.parse_args()
    cfg = PROGRAMS[args.program]

    pe = pefile.PE(args.exe)
    build_id = file_build_id(args.exe)
    base = pe.OPTIONAL_HEADER.ImageBase
    libsigs.register(pe, args.exe)       # the calling conventions of the game's own libraries that this program imports (from the same folder)
    lifter = Lifter()
    import_dll = {}
    for dll in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
        for imp in dll.imports:
            if imp.name:
                lifter.imports[imp.address] = imp.name.decode()
                import_dll[imp.address] = dll.dll.decode()
    import_rows = {}
    sect = {(s.VirtualAddress + base, s.VirtualAddress + base + max(s.Misc_VirtualSize, s.SizeOfRawData)) for s in pe.sections}

    def getbytes(va, n):
        """Bytes at va, up to n, never past the end of the section that contains va."""
        for lo, hi in sect:
            if lo <= va < hi:
                return pe.get_data(va - base, min(n, hi - va))
        raise Unsupported(f"0x{va:x} is not in the image")

    mps_code = [(s.VirtualAddress + base, s.VirtualAddress + base + max(s.Misc_VirtualSize, s.SizeOfRawData)) for s in pe.sections if s.Name.rstrip(b"\0") == b"MPS_CODE"]
    if cfg["master"] is None:        # a build whose master table is found by its pattern
        cfg = dict(cfg)
        cfg["master"] = mastertable.find(pe, cfg["stride"])[0]
        cfg["code"] = mastertable.code_range(pe)
        handlers = mastertable.handler_addresses(pe, cfg["master"], cfg["stride"]) if cfg["master"] else []
    else:
        handlers = handler_addresses(pe, cfg["master"], cfg["code"])
    extra = [int(x, 16) for x in args.extra.split(",") if x]
    if args.extra_file:
        for line in open(args.extra_file):
            line = line.split("#")[0].strip()
            if line:
                extra.append(int(line.split()[0], 16))
    native = native_entries(args.program)   # a native function stands in for its original, whatever registers that used
    # where the program's functions start, how long they are and how many arguments they take: found from its own code (fnscan.py)
    index = scan_pe(pe, lifter, getbytes, [*handlers, *extra, *sorted(native)])
    entries = frozenset(index)
    if args.no_handlers:
        handlers = []
    if args.all:
        extra += sorted(index)      # every function found, the program's start-up code and the C runtime's included
    extra += sorted(native_entries(args.program))   # every native function's machine code too: its lifted twin (host shadow mode, check_costs)
    extra = [a for a in dict.fromkeys(extra) if a not in handlers]
    handlers += extra
    spec, sources, callee_rows = [], [], {}
    register_args = {}
    for addr in handlers:
        info = index.get(addr)
        entry = dict(addr=f"0x{addr:08x}", name=f"Handler_{addr:08x}", size=info["size"] if info else None)
        if addr in extra:
            entry["extra"] = True   # not a card handler: it is called with its own arguments (nargs), not (player, slot, event)
            entry["label"] = info["name"] if info else None
        if not info:
            entry.update(lifted=False, reason="not a function the scan found")
            spec.append(entry)
            continue
        try:
            src, targets, ninsn, (lo, hi) = lifter.lift_function(getbytes, addr, entry["name"], entries)
            # what the function's `ret` pops; a thunk (`jmp [import]`) pops what the import's own return pops
            if lifter.tail_import is not None:
                tail_sig = KNOWN_IMPORTS.get(lifter.imports[lifter.tail_import]) or signature(import_dll[lifter.tail_import], lifter.imports[lifter.tail_import])
                entry["cleanup"] = tail_sig[1] if tail_sig else 0
            else:
                entry["cleanup"] = lifter.ret_cleanup(getbytes, addr, entries)
            entry.update(extent=[f"0x{lo:x}", f"0x{hi:x}"], instructions=ninsn, scan_size=info["size"],
                         nargs=max(info["nargs"], lifter.last_stack_arguments), returns_value=lifter.last_returns_value)
            for site in lifter.dynamic_sites:   # only a card's handler through the master table is understood
                if getbytes(site, 7) != b"\xff\x14\x85" + (cfg["master"] + 0x10).to_bytes(4, "little"):
                    raise Unsupported(f"indirect call at 0x{site:x} that is not through the master card table")
            calls, missing = [], [t for t in targets if t not in index and t not in lifter.imports]
            if missing:
                raise Unsupported("calls an address that is not a function the scan found: " + ", ".join(f"0x{t:x}" for t in missing))
            for t in sorted(targets):
                if t in lifter.imports:
                    name = lifter.imports[t]
                    sig = KNOWN_IMPORTS.get(name) or signature(import_dll[t], name)
                    if sig is None:
                        raise Unsupported(f"calls the import {name}, which the lifter has no signature for")
                    nargs, cleanup = sig
                    row = callee_rows.setdefault(t, dict(addr=t, nargs=nargs, cleanup=cleanup, name=name))
                    stub = import_rows.setdefault(t, STUB_BASE + STUB_STRIDE * len(import_rows))
                    calls.append(dict(addr=f"0x{t:08x}", name=name, nargs=nargs, cleanup=cleanup, import_slot=True,
                                      stub=f"0x{stub:08x}"))
                    continue
                if lifter.intrinsic(t, getbytes):       # a runtime helper the lifter replaces by inline code
                    continue
                row = callee_rows.get(t)
                if t not in register_args and t not in native:
                    register_args[t] = lifter.register_inputs(getbytes, t, entries)
                if t in VARIADIC[args.program]:
                    raise Unsupported(f"calls 0x{t:x}, which takes a variable number of arguments")
                if register_args.get(t):
                    raise Unsupported(f"calls 0x{t:x}, which takes {', '.join(register_args[t])} in registers")
                if row is None:
                    nargs = index[t]["nargs"]       # what its frame reads and what its `ret imm16` pops (fnscan.py)
                    row = callee_rows[t] = dict(addr=t, nargs=nargs,
                                                cleanup=lifter.ret_cleanup(getbytes, t, entries),
                                                name=index[t]["name"])
                calls.append(dict(addr=f"0x{t:08x}", name=row["name"], nargs=row["nargs"], cleanup=row["cleanup"]))
            sources.append(src)
            entry.update(lifted=True, calls=calls, dynamic_sites=[f"0x{x:08x}" for x in lifter.dynamic_sites])
        except Unsupported as e:
            entry.update(lifted=False, reason=str(e))
            if info["dead"]:
                entry.update(dead=True, covered=True)       # the search for code nothing reaches found it: no function of the program calls or points at it
            elif lifter.intrinsic(addr, getbytes):
                entry.update(intrinsic=lifter.intrinsic(addr, getbytes), covered=True)       # calls to it are replaced by inline code
            elif any(lo <= addr < hi for lo, hi in mps_code):
                entry.update(override="lzw.c", covered=True)         # the picture decompressor: hand-written C (src/port/lzw.c) stands in
        spec.append(entry)

    os.makedirs(args.out, exist_ok=True)
    lifted = [e for e in spec if e["lifted"]]
    with open(os.path.join(args.out, "handlers_gen.c"), "w") as f:
        f.write("/* Generated by tools/lift/gen_handlers.py from the user's own executable. Do not commit. */\n")
        f.write('#include "lift_rt.h"\n#include "lift_tables.h"\n\n')
        f.write("\n".join(sources))
        f.write("\nconst LiftedFn LIFTED[] = {\n")
        for e in lifted:
            f.write(f'    {{"{e["name"]}", {e["addr"]}u, lifted_{int(e["addr"], 16):08x}}},\n')
        f.write("    {0, 0, 0}\n};\n")
        f.write(f"const int LIFTED_COUNT = {len(lifted)};\nconst char LIFT_PROGRAM[] = \"{args.program.upper()}\"; /* whose machine code this is */\n"
                f"const char LIFT_BUILD_ID[] = \"{build_id}\"; /* SHA-256 of the file it was lifted from (tools/lift/builds.py) */\n\nconst CalleeRow LIFT_CALLEES[] = {{\n")
        for t in sorted(callee_rows):
            r = callee_rows[t]
            f.write(f"    {{0x{t:08x}u, {r['nargs']}, {r['cleanup']}u}},\n")
        f.write("    {0, 0, 0}\n};\n")
        f.write(f"const int LIFT_CALLEE_COUNT = {len(callee_rows)};\n")
        # every lifted function's argument count and what it pops, and every import's signature: a standalone program (src/port) reaches
        # functions through pointers (window procedures, callbacks), where no call site says how to clean the stack up
        f.write("\nconst CalleeRow LIFT_FUNCTIONS[] = {\n")
        for e in lifted:
            a = int(e["addr"], 16)
            f.write(f"    {{0x{a:08x}u, {e['nargs']}, {e['cleanup']}u}},\n")
        f.write("    {0, 0, 0}\n};\n")
        f.write(f"const int LIFT_FUNCTION_COUNT = {len(lifted)};\n")
        f.write("\nconst LiftImportSig LIFT_IMPORT_SIGS[] = {\n")
        sigs = 0
        for dll in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
            for imp in dll.imports:
                if imp.name:
                    nm = imp.name.decode()
                    sig = KNOWN_IMPORTS.get(nm) or signature(dll.dll.decode(), nm)
                    if sig:
                        f.write(f'    {{"{dll.dll.decode().lower()}", "{nm}", {sig[0]}, {sig[1]}u}},\n')
                        sigs += 1
        f.write("    {0, 0, 0, 0}\n};\n")
        f.write(f"const int LIFT_IMPORT_SIG_COUNT = {sigs};\n")
    with open(os.path.join(args.out, "handler_spec.json"), "w") as f:
        json.dump(spec, f, indent=1)
    reasons = {}
    for e in spec:
        if not e["lifted"]:
            key = e["reason"].split(":")[0]
            reasons[key] = reasons.get(key, 0) + 1
    print(f"{len(handlers)} distinct handlers: {len(lifted)} lifted, {len(spec) - len(lifted)} not")
    for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"   {v:4d}  {k}")
    # every function not lifted, with what stands in for it: a function the port can never run is not a gap
    covered_rows = [e for e in spec if not e["lifted"] and e.get("covered")]
    missing_rows = [e for e in spec if not e["lifted"] and not e.get("covered")]
    print(f"{len(covered_rows)} of them are covered another way, {len(missing_rows)} are not:")
    for e in covered_rows + missing_rows:
        how = e.get("dead") and "dead code, nothing the program runs reaches it" or e.get("override") and f"hand-written ({e['override']})" or e.get("intrinsic") and f"inline code ({e['intrinsic']})" \
            or "NOT COVERED"
        print(f"   {e['addr']} {e.get('label') or ''}: {e['reason']} -> {how}")


if __name__ == "__main__":
    main()

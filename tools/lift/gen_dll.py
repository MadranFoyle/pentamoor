#!/usr/bin/env python3
"""
gen_dll.py - lift a DLL of the game (STATWIN.DLL, DECKDLL.DLL, ...) with x86lift.py, for the standalone program (src/port).

The functions are found from the code itself: the entry point and the exports first, then every function
they call, then every address that is stored as a function pointer (pushed or moved as a constant, or found in the data sections the way a
C++ vtable or a callback table holds them). The DLL is lifted at the base it is given: the lifted code holds absolute addresses, so the
loader (src/port/pe.c) has to map the DLL at that base and apply its relocations (the generated code is for that one base).

  OUT/<name>_gen.c    the lifted functions, their tables, and the module record LIFT_MODULE_<NAME>
  OUT/modules_gen.c   (written by --finish) the list of every module in OUT

    python3 tools/lift/gen_dll.py --dll sources/installed/Magic/Program/STATWIN.DLL --base 0x30000000 --out sources/generated/lift_magic_all
    python3 tools/lift/gen_dll.py --finish --out sources/generated/lift_magic_all
"""
import argparse
import bisect
import glob
import json
import os
import sys

import pefile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from x86lift import Lifter, Unsupported  # noqa: E402
from import_signatures import signature  # noqa: E402
from gen_handlers import KNOWN_IMPORTS  # noqa: E402

PROLOGUES = (0x55, 0x53, 0x56, 0x57, 0x8B, 0x83, 0x81, 0xA1, 0x6A, 0x33, 0x31, 0xC3, 0xB8, 0x64, 0xFF, 0x68, 0xE9)


def c_name(path):
    return os.path.splitext(os.path.basename(path))[0].upper()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dll")
    ap.add_argument("--base", type=lambda s: int(s, 0), help="the address the file is lifted for (default: the one it asks for)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--finish", action="store_true", help="write modules_gen.c for every module in OUT")
    ap.add_argument("--main", action="store_true", help="the file is the program (an .EXE) rather than a library: lifted at its own base, written as handlers_gen.c "
                    "(the tables src/port reads for the program itself); its imports of the other lifted libraries are bound to their exports")
    args = ap.parse_args()
    if args.finish:
        finish(args.out)
        return

    pe = pefile.PE(args.dll)
    old_base = pe.OPTIONAL_HEADER.ImageBase
    base = args.base if args.base is not None else old_base
    # the image as the loader will make it at `base`: the sections in place, then every base relocation applied
    image = bytearray(pe.get_memory_mapped_image())
    delta = base - old_base
    for blk in getattr(pe, "DIRECTORY_ENTRY_BASERELOC", []):
        for ent in blk.entries:
            if ent.type == 3:         # IMAGE_REL_BASED_HIGHLOW
                off = ent.rva
                image[off:off + 4] = ((int.from_bytes(image[off:off + 4], "little") + delta) & 0xFFFFFFFF).to_bytes(4, "little")
    name = c_name(args.dll)
    lifter = Lifter()
    lifter.allow_register_args = True
    import_dll = {}
    for dll in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
        for imp in dll.imports:
            if imp.name:
                lifter.imports[imp.address + delta] = imp.name.decode()
                import_dll[imp.address + delta] = dll.dll.decode()
    sect = [(s.VirtualAddress + base, s.VirtualAddress + base + max(s.Misc_VirtualSize, s.SizeOfRawData), s) for s in pe.sections]
    text = [(lo, hi) for lo, hi, s in sect if s.Characteristics & 0x20000000]
    data_secs = [(lo, hi) for lo, hi, s in sect if not s.Characteristics & 0x20000000 and s.Name.rstrip(b"\0") not in (b".reloc", b".idata", b".rsrc")]

    def in_text(a):
        return any(lo <= a < hi for lo, hi in text)

    def getbytes(va, n):
        for lo, hi, _ in sect:
            if lo <= va < hi:
                return bytes(image[va - base:va - base + min(n, hi - va)])
        raise Unsupported(f"0x{va:x} is not in the image")

    text_lo, text_hi = text[0]
    code = getbytes(text_lo, text_hi - text_lo)

    def looks_like_a_start(t):
        """A function the compiler padded: after int3 fill or a `ret`, with a first instruction that begins a function."""
        at = t - text_lo
        if at <= 0 or at >= len(code) - 4 or code[at] not in PROLOGUES:
            return False
        return code[at - 1] == 0xCC or code[at - 1] == 0xC3 or (code[at - 3] in (0xC2,) and at >= 3) or code[at:at + 3] == b"\x55\x8b\xec"

    roots = {base + pe.OPTIONAL_HEADER.AddressOfEntryPoint}
    exports = {}
    for sym in getattr(getattr(pe, "DIRECTORY_ENTRY_EXPORT", None), "symbols", []):
        va = base + sym.address
        nm = sym.name.decode() if sym.name else f"#{sym.ordinal}"
        exports[nm] = va
        if in_text(va):
            roots.add(va)

    # the linker's thunks, `jmp [import]`, that nothing in the code says are functions
    for lo, hi in text:
        for a in range(lo, hi - 5):
            if image[a - base] == 0xFF and image[a - base + 1] == 0x25 and int.from_bytes(image[a - base + 2:a - base + 6], "little") in lifter.imports:
                roots.add(a)

    # the incremental linker's jump table: a run of `jmp rel32` at the start of the code, one per function (what a pointer to a function points at)
    a = text_lo
    while a + 5 <= text_hi and image[a - base] == 0xE9:
        roots.add(a)
        a += 5

    lifted_src, spec = {}, {}
    extents = []         # sorted (lo, hi) of what has been lifted: a pointer into one is a jump-table entry or a label, not a function
    entries = set(roots)

    def covered(t):
        i = bisect.bisect_right([e[0] for e in extents], t) - 1
        return i >= 0 and extents[i][0] <= t < extents[i][1]

    work = sorted(roots)
    failed = {}
    while True:
        while work:
            addr = work.pop()
            if addr in lifted_src or addr in failed or addr in lifter.imports or lifter.intrinsic(addr, getbytes):
                continue
            try:
                src, targets, ninsn, (lo, hi) = lifter.lift_function(getbytes, addr, f"Handler_{addr:08x}", frozenset(entries))
            except Unsupported as e:
                failed[addr] = str(e)
                continue
            cleanup = lifter.ret_cleanup(getbytes, addr, frozenset(entries))
            if lifter.tail_import is not None:
                nm = lifter.imports[lifter.tail_import]
                sg = KNOWN_IMPORTS.get(nm) or signature(import_dll[lifter.tail_import], nm)
                cleanup = sg[1] if sg else 0
            lifted_src[addr] = src
            spec[addr] = dict(addr=addr, nargs=lifter.last_stack_arguments, cleanup=cleanup, targets=sorted(targets), extent=(lo, hi), instructions=ninsn,
                              returns_value=lifter.last_returns_value, dynamic=list(lifter.dynamic_sites), constants=lifter.last_constants)
            extents.append((lo, hi))
            extents.sort()
            for t in targets:
                if t not in lifter.imports and in_text(t) and t not in lifted_src and not lifter.intrinsic(t, getbytes):
                    entries.add(t)
                    work.append(t)
        # function pointers: in the code (an immediate), and in the data sections (vtables, callback tables)
        found = set()
        for a, sp in list(spec.items()):
            lo, hi = sp["extent"]
            blob = getbytes(lo, hi - lo)
            for off in range(len(blob) - 4):
                b = blob[off]
                if b in (0x68, 0xB8, 0xB9, 0xBA, 0xBB, 0xBE, 0xBF) or (b == 0xC7 and off + 11 <= len(blob)):
                    if b == 0xC7:        # mov r/m32, imm32: the immediate follows the ModRM byte, its SIB byte and its displacement
                        mod, rm = blob[off + 1] >> 6, blob[off + 1] & 7
                        at = off + 2 + (1 if rm == 4 and mod != 3 else 0) + (4 if (mod == 0 and rm == 5) or mod == 2 else 1 if mod == 1 else 0)
                        t = int.from_bytes(blob[at:at + 4], "little")
                    else:
                        t = int.from_bytes(blob[off + 1:off + 5], "little")
                    if in_text(t) and t not in lifted_src and t not in failed and not covered(t) and looks_like_a_start(t):
                        found.add(t)
        for lo, hi in data_secs:
            blob = getbytes(lo, hi - lo)
            for off in range(0, len(blob) - 3, 4):
                t = int.from_bytes(blob[off:off + 4], "little")
                if in_text(t) and t not in lifted_src and t not in failed and not covered(t) and looks_like_a_start(t):
                    found.add(t)
        found -= entries
        if not found:
            break
        for t in sorted(found):
            entries.add(t)
            work.append(t)

    # the callee rows: argument count and what the `ret` pops, for every function a lifted one calls
    callee_rows, import_calls = {}, {}
    for addr, sp in spec.items():
        for t in sp["targets"]:
            if t in lifter.imports:
                nm = lifter.imports[t]
                sg = KNOWN_IMPORTS.get(nm) or signature(import_dll[t], nm)
                if sg is None:
                    sp.setdefault("unknown_imports", []).append(nm)
                else:
                    callee_rows[t] = (sg[0], sg[1])
            elif t in spec:
                callee_rows[t] = (max(spec[t]["nargs"], 0), spec[t]["cleanup"])
            else:
                callee_rows[t] = (lifter.callee_arguments(getbytes, t, frozenset(entries)), lifter.ret_cleanup(getbytes, t, frozenset(entries)))
    missing = sorted({nm for sp in spec.values() for nm in sp.get("unknown_imports", [])})
    if missing:
        print("imports with no signature:", ", ".join(missing))

    os.makedirs(args.out, exist_ok=True)
    out = os.path.join(args.out, "handlers_gen.c" if args.main else f"{name.lower()}_gen.c")
    ids = sorted(spec)
    sigs = []
    for d in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
        for imp in d.imports:
            if imp.name:
                nm = imp.name.decode()
                sg = KNOWN_IMPORTS.get(nm) or signature(d.dll.decode(), nm)
                if sg:
                    sigs.append(f'    {{"{d.dll.decode().lower()}", "{nm}", {sg[0]}, {sg[1]}u}},\n')
    with open(out, "w") as f:
        f.write(f"/* Generated by tools/lift/gen_dll.py from the user's own {os.path.basename(args.dll)}, lifted for the base 0x{base:08x}. Do not commit. */\n")
        f.write('#include "lift_rt.h"\n#include "lift_tables.h"\n\n')
        f.write("\n".join(lifted_src[a] for a in ids))
        suffix = "" if args.main else f"_{name}"
        st = "" if args.main else "static "
        f.write(f"\n{st}const LiftedFn {'LIFTED' if args.main else 'LIFTED_' + name}[] = {{\n")
        for a in ids:
            f.write(f'    {{"{name}_{a:08x}", 0x{a:08x}u, lifted_{a:08x}}},\n')
        f.write("    {0, 0, 0}\n};\n")
        f.write(f"{st}const CalleeRow LIFT_FUNCTIONS{suffix}[] = {{\n")
        for a in ids:
            f.write(f"    {{0x{a:08x}u, {spec[a]['nargs']}, {spec[a]['cleanup']}u}},\n")
        f.write("    {0, 0, 0}\n};\n")
        f.write(f"{st}const LiftImportSig LIFT_IMPORT_SIGS{suffix}[] = {{\n" + "".join(sigs) + "    {0, 0, 0, 0}\n};\n")
        if args.main:
            f.write(f"const int LIFTED_COUNT = {len(ids)};\nconst char LIFT_PROGRAM[] = \"{name}\";\n")
            f.write("const CalleeRow LIFT_CALLEES[] = {{0, 0, 0}};\nconst int LIFT_CALLEE_COUNT = 0;\n")
            f.write(f"const int LIFT_FUNCTION_COUNT = {len(ids)};\nconst int LIFT_IMPORT_SIG_COUNT = {len(sigs)};\n")
        else:
            f.write(f"const LiftModule LIFT_MODULE_{name} = {{\"{os.path.basename(args.dll).lower()}\", 0x{base:08x}u, 0x{base + pe.OPTIONAL_HEADER.AddressOfEntryPoint:08x}u, "
                    f"LIFTED_{name}, {len(ids)}, LIFT_FUNCTIONS_{name}, {len(ids)}, LIFT_IMPORT_SIGS_{name}, {len(sigs)}}};\n")
    with open(os.path.join(args.out, f"{name.lower()}_spec.json"), "w") as f:
        json.dump(dict(lifted=[hex(a) for a in ids], extents={hex(a): [hex(spec[a]["extent"][0]), hex(spec[a]["extent"][1])] for a in ids},
                       failed={hex(a): r for a, r in sorted(failed.items())}, exports={k: hex(v) for k, v in exports.items()}), f, indent=1)
    print(f"{name}: {len(ids)} functions lifted, {len(failed)} not")
    reasons = {}
    for a, r in failed.items():
        reasons.setdefault(r.split(":")[0], []).append(a)
    for r, aa in sorted(reasons.items(), key=lambda kv: -len(kv[1])):
        print(f"   {len(aa):4d}  {r}  ({', '.join(hex(a) for a in aa[:4])})")


def finish(out):
    mods = sorted(os.path.basename(p)[:-6].upper() for p in glob.glob(os.path.join(out, "*_gen.c")) if not os.path.basename(p).startswith(("handlers", "modules")))
    with open(os.path.join(out, "modules_gen.c"), "w") as f:
        f.write("/* Generated by tools/lift/gen_dll.py --finish. Do not commit. */\n")
        f.write('#include "lift_tables.h"\n\n')
        for m in mods:
            f.write(f"extern const LiftModule LIFT_MODULE_{m};\n")
        f.write("const LiftModule *const LIFT_MODULES[] = {\n")
        for m in mods:
            f.write(f"    &LIFT_MODULE_{m},\n")
        f.write("    0\n};\n")
    print("modules:", ", ".join(mods) or "none")


if __name__ == "__main__":
    main()

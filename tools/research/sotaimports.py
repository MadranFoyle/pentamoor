#!/usr/bin/env python3
"""
sotaimports.py - the Windows calls a build of the game imports, against what the port implements (src/port) and what the lifter knows the calling convention of
(tools/lift/import_signatures.py).

    sotaimports.py [--old PROGRAM.EXE ...] --new PROGRAM.EXE ... [--port src/port]

For each program: how many imports it has; which are new compared with the programs given as --old; which of them the port does not implement (a call of one stops the run
with "is not implemented", or with PORT_STUB=1 returns 0); which the lifter has no signature for (it refuses a function that calls one). The port finds an import by the
library's name as written in the executable, lower case, so the same function imported from MSVCRT.dll and from MSVCRTD.dll counts as two (`dll_alias` shows the effect).
A table entry is a line of the form {"kernel32.dll", "GetTickCount", fn} in a .c file of src/port, in the tables pe.c searches.

    sotaimports.py --sigs --new PROGRAM.EXE ...

checks the lifter's signatures (tools/lift/import_signatures.py) against the code that calls each import, which is the only thing the executables say about them: at each call
(`call [slot]`, or a call of the `jmp [slot]` thunk the linker puts in front of a C runtime function) it counts the `push`es since the last call, jump or return (what a stdcall
function's arguments are: the callee pops them) and, after the call, an `add esp, N` (what a cdecl caller does: N/4 arguments). A signature whose number of stack words is more than
the most pushes ever seen before its calls, or less than what the cdecl callers pop, is reported; the fewest pushes seen at any site is printed beside it (a site in the middle of a
function has exactly the arguments; one near a prologue has its saved registers too). Needs capstone.
"""
import argparse
import os
import re
import sys

import pefile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lift"))
from import_signatures import signature  # noqa: E402

ENTRY = re.compile(r'\{\s*"([A-Za-z0-9_.]+\.dll|#?\w*)"\s*,\s*"([^"]+)"\s*,\s*[A-Za-z_0-9]+\s*\}')
# the tables pe.c searches (find_api); the host libraries (MAGSND.DLL, MAGVID.DLL) are separate tables and count as provided by name
TABLE_FILES = ("kernel32.c", "kernel32_rt.c", "winsys.c", "process.c", "crt.c", "stdio.c", "user32.c", "controls.c", "filedlg.c", "winhelp.c", "msgbox.c", "menus.c", "gdi.c", "gdi_blit.c", "gdi_text.c", "video.c")


def port_table(port):
    have = set()
    for name in TABLE_FILES:
        path = os.path.join(port, name)
        if not os.path.exists(path):
            continue
        for m in ENTRY.finditer(open(path, encoding="latin-1").read()):
            have.add((m.group(1).lower(), m.group(2)))
    return have


def imports_of(path):
    pe = pefile.PE(path)
    out = []
    for dll in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
        for imp in dll.imports:
            name = imp.name.decode() if imp.name else "#%d" % imp.ordinal
            out.append((dll.dll.decode().lower(), name))
    return out


def call_sites(path):
    """{import name: [(pushes before the call, words an `add esp` after it pops or None)]} for the calls of `path`'s imports, by a linear sweep of its code."""
    import capstone  # noqa: PLC0415

    pe = pefile.PE(path)
    base = pe.OPTIONAL_HEADER.ImageBase
    slots = {}
    for d in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
        for imp in d.imports:
            if imp.name:
                slots[imp.address] = (d.dll.decode().lower(), imp.name.decode())
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    insns = []
    for sec in pe.sections:
        if not sec.Characteristics & 0x20000000:
            continue
        code, va = sec.get_data(), base + sec.VirtualAddress
        off = 0
        while off < len(code):
            n = 0
            for i in md.disasm(code[off:], va + off):
                insns.append(i)
                n = i.address - (va + off) + i.size
            off += max(n, 1)
    thunks = {}
    for i in insns:
        if i.mnemonic == "jmp" and i.op_str.startswith("dword ptr [0x"):
            slot = int(i.op_str.split("[")[1].rstrip("]"), 16)
            if slot in slots:
                thunks[i.address] = slot
    out = {}
    stop = {"call", "jmp", "ret", "int3", "leave"}
    for k, i in enumerate(insns):
        if i.mnemonic != "call":
            continue
        slot = None
        if i.op_str.startswith("dword ptr [0x"):
            slot = int(i.op_str.split("[")[1].rstrip("]"), 16)
        elif i.op_str.startswith("0x") and int(i.op_str, 16) in thunks:
            slot = thunks[int(i.op_str, 16)]
        if slot not in slots:
            continue
        pushes, j = 0, k - 1
        while j >= 0 and k - j <= 30:
            m = insns[j].mnemonic
            if m in stop or (m.startswith("j") and m != "jmp") or (m in ("add", "sub") and insns[j].op_str.startswith("esp")):
                break
            if m == "push":
                pushes += 1
            j -= 1
        after = None
        if k + 1 < len(insns) and insns[k + 1].mnemonic == "add" and insns[k + 1].op_str.startswith("esp, "):
            try:
                after = int(insns[k + 1].op_str.split(", ")[1], 0) // 4
            except ValueError:
                pass
        out.setdefault(slots[slot][1], []).append((pushes, after))
    return out


def check_signatures(path):
    """Print what the call sites of `path` say about each signature the lifter has for its imports; returns the number of disagreements."""
    sites = call_sites(path)
    bad = 0
    pe = pefile.PE(path)
    dlls = {imp.name.decode(): d.dll.decode() for d in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) for imp in d.imports if imp.name}
    for name in sorted(sites):
        sig = signature(dlls[name], name)
        if sig is None:
            continue
        words, pops = sig
        cdecl = pops == 0 and words > 0
        pushes = [p for p, _ in sites[name]]
        pops_seen = {a for _, a in sites[name] if a is not None}
        issue = []
        if not cdecl and words and max(pushes) < words:
            issue.append("never more than %d pushes before a call, the signature says %d" % (max(pushes), words))
        if cdecl and words < 12 and pops_seen and max(pops_seen) > words:
            issue.append("a caller pops %d words, the signature says %d" % (max(pops_seen), words))
        if cdecl and words < 12 and pops_seen and min(pops_seen) < words:
            issue.append("a caller pops only %d words, the signature says %d" % (min(pops_seen), words))
        if issue:
            bad += 1
        print("   %-28s %2d words %s  %3d sites, fewest pushes %d, pops after %s %s" % (name, words, "cdecl" if cdecl else "stdcall", len(pushes), min(pushes),
                                                                                     sorted(pops_seen) if pops_seen else "-", "<-- " + "; ".join(issue) if issue else ""))
    return bad


def alias(dll):
    return "msvcrtd.dll" if dll == "msvcrt.dll" else dll


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--old", nargs="*", default=[])
    ap.add_argument("--new", nargs="+", required=True)
    ap.add_argument("--port", default=os.path.join(HERE, "..", "..", "src", "port"))
    ap.add_argument("--sigs", action="store_true", help="check the lifter's signatures against the call sites of each program's imports (needs capstone)")
    ap.add_argument("--libs", nargs="*", default=[], help="libraries of the game that are lifted or provided by the host (their exports are not Windows calls): names, lower case")
    args = ap.parse_args()
    if args.sigs:
        total = 0
        for p in args.new:
            print("\n%s:" % os.path.basename(p))
            total += check_signatures(p)
        print("\n%d signature(s) the call sites disagree with" % total)
        return
    have = port_table(args.port)
    own = set(args.libs)
    known_old = set()
    for p in args.old:
        known_old.update(imports_of(p))
    print("the port's tables hold %d (library, function) entries" % len(have))
    for p in args.new:
        imps = [i for i in imports_of(p) if i[0] not in own]
        mine = [i for i in imports_of(p) if i[0] in own]
        new = [i for i in imps if i not in known_old and (alias(i[0]), i[1]) not in known_old]
        missing = [i for i in imps if i not in have]
        missing_alias = [i for i in imps if (alias(i[0]), i[1]) not in have]
        nosig = [i for i in imps if signature(*i) is None]
        print("\n%s: %d imports (%d from the game's own libraries: %s)" % (os.path.basename(p), len(imps), len(mine), ", ".join(sorted({d for d, _ in mine})) or "none"))
        print("   not in the port's tables as written: %d;  if msvcrt.dll were an alias of msvcrtd.dll: %d" % (len(missing), len(missing_alias)))
        print("   no lifter signature: %d: %s" % (len(nosig), ", ".join("%s!%s" % i for i in nosig)))
        if args.old:
            print("   not imported by any of the --old programs: %d" % len(new))
            print("      " + ", ".join("%s!%s" % i for i in sorted(new)))
        print("   missing even with the alias (%d): %s" % (len(missing_alias), ", ".join("%s!%s" % i for i in sorted(missing_alias))))


if __name__ == "__main__":
    main()

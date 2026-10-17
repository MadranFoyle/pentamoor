#!/usr/bin/env python3
"""
sotastride.py - which structure sizes a program multiplies by, read off the compiler's multiplication sequences.

    sotastride.py PROGRAM.EXE [...] [--want 288,300,23328,30300,52,72]

The 1.0 programs index the duel's card slots as `player * 23328 + slot * 288`, the compiler's reduction of which is `lea r,[r+r*8]` three times and `shl r,5` (9*9*9*32 = 23328; 9*32 = 288);
SotA's 30300 and 300 come out as other chains (see docs/notes/sota-comparison.md). This walks every function the scan finds (tools/lift/fnscan.py), follows the registers through
`mov`, `lea r,[s+s*k]`, `lea r,[s*k]`, `add r,r`, `shl r,n` and `imul r,s,imm` chains that start from one unknown value, and counts how often each product (the whole constant a value was
multiplied by) is reached, in how many functions. A chain that reaches 300 is `x * 300`. Only products in --want and every `imul r,s,imm` with an immediate are reported; the default list holds
the strides discussed in the notes (the master record 0x34 / 0x48 = 52 / 72, the duel slot 288 / 300, the slot table of a player 23328 / 30300). Counts are of code sites, not of calls.
"""
import os
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import sotacmp as sc  # noqa: E402
import capstone  # noqa: E402
from capstone import x86  # noqa: E402

WANT_DEFAULT = (52, 72, 288, 300, 23328, 30300, 81 * 288, 101 * 300)


def products(img, funcs, want):
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    hits = Counter()
    where = defaultdict(set)
    text = {}
    for s in img.pe.sections:
        if s.Characteristics & 0x20000000:
            text[img.base + s.VirtualAddress] = s.get_data()
    for a, f in funcs.items():
        data = None
        for va, d in text.items():
            if va <= a < va + len(d):
                data = d[a - va:f.hi - va] if f.hi > a else None
                break
        if not data:
            continue
        mult = {}                                                   # register id -> product
        for ins in md.disasm(data, a):
            ops = ins.operands
            m = ins.mnemonic
            try:
                if m == "mov" and len(ops) == 2 and ops[0].type == x86.X86_OP_REG and ops[1].type == x86.X86_OP_REG:
                    d, s_ = ops
                    mult.setdefault(s_.reg, 1)
                    mult[d.reg] = mult[s_.reg]
                    continue
                if m in ("add", "sub") and len(ops) == 2 and ops[0].type == x86.X86_OP_REG and ops[1].type == x86.X86_OP_REG and ops[0].reg in mult and ops[1].reg in mult:
                    mult[ops[0].reg] = mult[ops[0].reg] + (mult[ops[1].reg] if m == "add" else -mult[ops[1].reg])
                    if mult[ops[0].reg] in want:
                        hits[mult[ops[0].reg]] += 1
                        where[mult[ops[0].reg]].add(a)
                    continue
                if m == "lea" and ops[1].type == x86.X86_OP_MEM:
                    mem = ops[1].mem
                    d = ops[0].reg
                    base, idx, sc_, disp = mem.base, mem.index, mem.scale, mem.disp
                    if disp == 0 and idx and base == idx:
                        k = mult.get(idx, 1) * (sc_ + 1)
                    elif disp == 0 and idx and not base:
                        k = mult.get(idx, 1) * sc_
                    elif disp == 0 and idx and base and idx in mult and base in mult:
                        k = mult[base] + mult[idx] * sc_
                    else:
                        mult.pop(d, None)
                        continue
                    mult[d] = k
                    if k in want:
                        hits[k] += 1
                        where[k].add(a)
                    continue
                if m == "shl" and len(ops) == 2 and ops[0].type == x86.X86_OP_REG and ops[1].type == x86.X86_OP_IMM:
                    r = ops[0].reg
                    mult[r] = mult.get(r, 1) << ops[1].imm
                    if mult[r] in want:
                        hits[mult[r]] += 1
                        where[mult[r]].add(a)
                    continue
                if m == "add" and len(ops) == 2 and ops[0].type == x86.X86_OP_REG and ops[1].type == x86.X86_OP_REG and ops[0].reg == ops[1].reg:
                    mult[ops[0].reg] = mult.get(ops[0].reg, 1) * 2
                    continue
                if m == "imul" and len(ops) == 3 and ops[2].type == x86.X86_OP_IMM:
                    k = mult.get(ops[1].reg, 1) * ops[2].imm if ops[1].type == x86.X86_OP_REG else ops[2].imm
                    mult[ops[0].reg] = k
                    if k in want:
                        hits[k] += 1
                        where[k].add(a)
                    continue
                if m == "imul" and len(ops) == 2 and ops[1].type == x86.X86_OP_IMM:
                    pass
            except (KeyError, IndexError, AttributeError):
                pass
            if m in ("call", "jmp", "ret", "retn") or m.startswith("j"):
                mult.clear()
            elif ops and ops[0].type == x86.X86_OP_REG and m not in ("cmp", "test", "push"):
                mult.pop(ops[0].reg, None)
    return hits, where


def main(argv):
    args = argv[1:]
    want = set(WANT_DEFAULT)
    if "--want" in args:
        i = args.index("--want")
        want = {int(x, 0) for x in args[i + 1].split(",")}
        del args[i:i + 2]
    if not args:
        print(__doc__)
        return 2
    for p in args:
        img = sc.Image(p)
        funcs, _ = sc.scan_functions(img)
        hits, where = products(img, funcs, want)
        print("%s: %d functions; " % (os.path.basename(p), len(funcs)) + ("; ".join("x%d: %d sites in %d functions" % (k, hits[k], len(where[k])) for k in sorted(want) if hits[k]) or "none of the strides"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

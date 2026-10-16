#!/usr/bin/env python3
"""
sotalzw.py - where the picture decompressor's state is in another build of the game.

src/port/lzw.c replaces the game's picture decompressor (the MPS_CODE section, 0x4a8 bytes of code) with C, and needs the addresses of its state for each copy of the code (the
`Lz` records at the end of that file: the block the dictionary and flags are in as an offset `delta` from 1.0's place, the input pointer, the input end, the refill callback's
variable and the function it calls). The code is the same in every copy of version 1.0 and 2.x (only relative jumps differ); the state moved. This reads the relocated operands
of the section in the old program and in each new one, pairs them by position (the code is the same, so the n-th absolute address is the same variable) and prints the record.

    sotalzw.py OLD.EXE NEW[:BASE] ...      BASE: the address a library is lifted at (gen_dll.py --base), added to its addresses (default: the file's own base)

The numbers it prints are addresses of the program's data and nothing else.
"""
import os
import sys

import capstone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sotacmp as sc  # noqa: E402


def mps(path):
    img = sc.Image(path)
    secs = [(lo, hi) for lo, hi, n, c in img.sections if n == "MPS_CODE"]
    if not secs:
        return None
    lo, hi = secs[0]
    data = img.get(lo, hi - lo)
    vals = [int.from_bytes(data[r - lo:r - lo + 4], "little") for r in sorted(img.relocs) if lo <= r < hi]
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    calls = [i.operands[0].imm & 0xFFFFFFFF for i in md.disasm(img.get(lo, 0x4a8), lo)
             if i.mnemonic == "call" and i.operands[0].type == sc.CS_IMM and not lo <= (i.operands[0].imm & 0xFFFFFFFF) < hi]
    return img, lo, vals, calls


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    old = mps(argv[1])
    if old is None:
        raise SystemExit("no MPS_CODE section in " + argv[1])
    ref = old[2]
    for spec in argv[2:]:
        path, _, base = spec.partition(":")
        r = mps(path)
        if r is None:
            print("%s: no MPS_CODE section" % os.path.basename(path))
            continue
        img, lo, vals, calls = r
        shift = (int(base, 0) - img.base) if base else 0
        if len(vals) != len(ref):
            print("%s: %d relocated operands, the old program has %d: not the same code" % (os.path.basename(path), len(vals), len(ref)))
            continue
        d = {a: b + shift for a, b in zip(ref, vals)}
        # the old program's own variables, by their 1.0 addresses: dictionary block 0x532860, input pointer 0x706500, input end 0x5327b0, refill 0x67f43c (MAGIC.EXE)
        print("%s: section at %#x  Lz = {delta %#x, in_ptr %#x, in_end %#x, refill %#x, callback %#x}" % (
            os.path.basename(path), lo + shift, (d[0x532860] - 0x532860) & 0xFFFFFFFF, d[0x706500], d[0x5327b0], d[0x67f43c], calls[0] + shift))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

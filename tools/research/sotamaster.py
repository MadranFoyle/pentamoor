#!/usr/bin/env python3
"""
sotamaster.py - find the master card table inside a program of the game, and count its records, from the machine image alone.

    sotamaster.py PROGRAM.EXE [--stride 0x48] [--field 0x10] [--dump N]

The master table is an array of fixed-size records in the program's data; one field of each record (+0x10 in all builds seen) is the address of the code that implements the card's rules,
so the table is found as the longest run of records, `stride` bytes apart, whose field points into the code section. 1.0 has 463 records of 0x34 bytes, Spells of the Ancients 622 of
0x48 (shandalar.exe and magic.exe; `liftsota.py --master` takes the address). Prints: the start of the run (the address of the field of the first record minus the field offset), the number
of records, how many distinct code pointers there are, how many of the records have the same pointer as the previous one (cards that share a handler), and with --dump the first N records
as hex words (numbers, no text). A record whose handler field is zero ends the run; the table's end is where the pointers stop, so a build that padded the table would be undercounted.
"""
import struct
import sys
import warnings

warnings.simplefilter("ignore")
import pefile  # noqa: E402


def find(path, stride, field):
    pe = pefile.PE(path)
    base = pe.OPTIONAL_HEADER.ImageBase
    text = [(base + s.VirtualAddress, base + s.VirtualAddress + s.Misc_VirtualSize) for s in pe.sections if s.Characteristics & 0x20000000]
    lo, hi = min(a for a, _ in text), max(b for _, b in text)
    best = (0, 0)
    for s in pe.sections:
        if s.Characteristics & 0x20000000 or not s.SizeOfRawData:
            continue
        data = s.get_data()
        va = base + s.VirtualAddress
        n = len(data) // 4
        words = struct.unpack("<%dI" % n, data[:n * 4])
        ok = [lo <= w < hi for w in words]
        i = 0
        while i < n:
            if not ok[i]:
                i += 1
                continue
            run, j = 0, i
            while j < n and ok[j]:
                run += 1
                j += stride // 4
            if run > best[1]:
                best = (va + i * 4 - field, run)
            i += 1
    start, count = best
    return pe, base, start, count


def main(argv):
    args = argv[1:]
    stride, field, dump = 0x48, 0x10, 0
    paths = []
    i = 0
    while i < len(args):
        if args[i] == "--stride":
            stride = int(args[i + 1], 0)
            i += 2
        elif args[i] == "--field":
            field = int(args[i + 1], 0)
            i += 2
        elif args[i] == "--dump":
            dump = int(args[i + 1])
            i += 2
        else:
            paths.append(args[i])
            i += 1
    if not paths:
        print(__doc__)
        return 2
    for p in paths:
        pe, base, start, count = find(p, stride, field)
        if not count:
            print("%s: no run of code pointers with stride 0x%x at +0x%x" % (p, stride, field))
            continue
        ptrs = []
        for k in range(count):
            ptrs.append(struct.unpack("<I", pe.get_data(start + k * stride + field - base, 4))[0])
        same = sum(1 for a, b in zip(ptrs, ptrs[1:]) if a == b)
        print("%s: master table at 0x%x (handler field at 0x%x), %d records of 0x%x bytes, %d distinct handlers, %d repeat the previous record's" % (
            p, start, start + field, count, stride, len(set(ptrs)), same))
        for k in range(dump):
            w = struct.unpack("<%dI" % (stride // 4), pe.get_data(start + k * stride - base, stride))
            print("  [%d] %s" % (k, " ".join("%x" % x for x in w)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

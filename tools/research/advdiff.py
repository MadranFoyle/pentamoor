#!/usr/bin/env python3
"""
advdiff.py - what Spells of the Ancients 2.15 changes in the adventure, against 1.0: the parts of docs/notes/sota-adventure-diff.md that can be rerun on the files.

    advdiff.py decks OLD_DECKS_DIR NEW_DECKS_DIR OLD.EXE [--cards OLD/CARDS.DAT]
    advdiff.py creatures OLD.EXE NEW.EXE
    advdiff.py fn OLD.EXE NEW.EXE ADDR [ADDR ...] [-v]

decks       the Shandalar opponents' deck files (`decks/NNNN.dck`: a title line, then `.ID<TAB>COUNT<TAB>NAME` lines, then in 1.0's files six `.vNAME` blocks of 0 to 5 cards): per file the title, the card counts, how many of the old deck's
            distinct cards are still there, and how many cards of the new deck the OLD program does not implement (its master card table, found by sotamaster.py). Prints names of decks
            and counts only, no card text.
creatures   the creature table of the adventure (57 records: 1.0's stride 0x44 at 0x522628, SotA's 0x8c at 0x57480f), compares the first 28 bytes of each record (colours, ability bits,
            the opponent deck's number, ...): the numbers, not the names (SotA keeps the names in a text file and as strings in the record). The addresses are those of MAGIC.EXE 1.0 and
            shandalar.exe 2.15 (found with sotacmp.py's data-address votes); give others with --old-base/--new-base.
fn          one function of OLD.EXE, found in NEW.EXE by sotacmp.py's matching, and the places where the two differ in a NUMBER (an immediate operand), with the stack slots and the
            addresses of the data left out, so that a recompile (other registers, other strides of a table) does not show. -v prints the instructions around each difference. The matching
            takes about three minutes (it scans and matches every function of both programs).

Needs pefile and capstone (and, for `fn`, tools/research/sotacmp.py and the lifter in tools/lift). Nothing it prints holds game text.
"""
import argparse
import difflib
import os
import re
import struct
import sys
import warnings
from collections import Counter

warnings.simplefilter("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "lift"))


BASIC = {"Plains", "Island", "Swamp", "Mountain", "Forest"}


def read_deck(path):
    """(title, [(card id, count, name)] of the base list, {variant: [...]}) of a `.dck` file. A `.vNAME` line starts a variant block (1.0's files have six: None, Black, Blue, Green, Red,
    White); the loader adds a block's cards when the caller gives it a matching colour mask."""
    lines = open(path, "rb").read().decode("latin-1").replace("\r", "").split("\n")
    base, variants = [], {}
    cur = base
    for line in lines[1:]:
        m = re.match(r"^\.v(\w+)\s*$", line)
        if m:
            cur = variants.setdefault(m.group(1), [])
            continue
        m = re.match(r"^\.(\d+)\t(\d+)\t(.*)$", line)
        if m:
            cur.append((int(m.group(1)), int(m.group(2)), m.group(3)))
    return lines[0], base, variants


def master_ids(exe):
    """The card ids of a program's master card table (word 0 of each record; -1 is a placeholder)."""
    import sotamaster
    stride = 0x34
    best = None
    for s in (0x34, 0x48):
        pe, base, start, count = sotamaster.find(exe, s, 0x10)
        if best is None or count > best[2]:
            best = (pe, start, count, s)
    pe, start, count, s = best
    img = pe.get_memory_mapped_image()
    off = start - pe.OPTIONAL_HEADER.ImageBase
    ids = {struct.unpack_from("<I", img, off + i * s)[0] for i in range(count)}
    ids.discard(0xFFFFFFFF)
    return ids, count, s


def cmd_decks(a):
    old = {f.lower(): os.path.join(a.old_dir, f) for f in os.listdir(a.old_dir) if f.lower().endswith(".dck")}
    new = {f.lower(): os.path.join(a.new_dir, f) for f in os.listdir(a.new_dir) if f.lower().endswith(".dck")}
    implemented, count, stride = master_ids(a.exe)
    print("%d old deck files, %d new, %d in both; the old program's master table has %d records (stride 0x%x), %d card ids" % (len(old), len(new), len(set(old) & set(new)), count, stride, len(implemented)))
    tot = Counter()
    print("| file | old title | new title | cards old (base list) | colour variants old / new | cards new | distinct non-basic old | distinct non-basic new | in both | new cards the old program lacks |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for f in sorted(set(old) & set(new)):
        to, co, vo = read_deck(old[f])
        tn, cn, vn = read_deck(new[f])
        so, sn = sum(c for _, c, _ in co), sum(c for _, c, _ in cn)
        do, dn = {i for i, _, n in co if n.strip() not in BASIC}, {i for i, _, n in cn if n.strip() not in BASIC}
        lack = sum(c for i, c, _ in cn if i not in implemented)
        print("| %s | %s | %s | %d | %d / %d | %d | %d | %d | %d | %d |" % (f, to.strip(), tn.strip(), so, len(vo), len(vn), sn, len(do), len(dn), len(do & dn), lack))
        tot["variant_files_old"] += bool(vo)
        tot["variant_files_new"] += bool(vn)
        tot["old"] += so
        tot["new"] += sn
        tot["lack"] += lack
        tot["decks"] += 1
        tot["decks_with_lack"] += lack > 0
    print("total cards (base lists) old %d, new %d; new cards the old program lacks %d; decks with at least one: %d of %d; decks with colour variants: old %d, new %d"
          % (tot["old"], tot["new"], tot["lack"], tot["decks_with_lack"], tot["decks"], tot["variant_files_old"], tot["variant_files_new"]))


def read_va(exe, va, n):
    import pefile
    pe = pefile.PE(exe)
    img = pe.get_memory_mapped_image()
    off = va - pe.OPTIONAL_HEADER.ImageBase
    return img[off:off + n]


def cmd_creatures(a):
    n = 57
    old = read_va(a.old, a.old_base, n * 0x44)
    new = read_va(a.new, a.new_base, n * 0x8c)
    same = 0
    for i in range(n):
        ro, rn = old[i * 0x44:i * 0x44 + 0x1c], new[i * 0x8c:i * 0x8c + 0x1d]
        # SotA inserts one byte after the first four (an article or a flag): the rest of the 28 bytes is the same layout shifted by one
        if ro[:4] + ro[4:0x1c] == rn[:4] + rn[5:0x1d]:
            same += 1
        else:
            print("record %d differs: %s / %s" % (i, ro.hex(), rn.hex()))
    print("%d of %d creature records have the same first 28 bytes" % (same, n))


def norm(line):
    p = line.split(" ", 1)[1]
    p = re.sub(r"0x[0-9a-f]{5,}", "ADDR", p)
    return re.sub(r"\[ebp [-+] 0x[0-9a-f]+\]", "[ebp LOC]", p)


def immediates(lines):
    c = Counter()
    for line in lines:
        parts = line.split(", ")
        last = parts[-1] if len(parts) > 1 else line.split(" ")[-1]
        if re.fullmatch(r"-?(0x[0-9a-f]+|\d+)", last):
            v = int(last, 16) if "x" in last else int(last)
            if v not in (0, 1, -1):
                c[v] += 1
    return c


def cmd_fn(a):
    import sotacmp as S
    oi, ni = S.Image(a.old), S.Image(a.new)
    old, _ = S.scan_functions(oi)
    new, _ = S.scan_functions(ni)
    M = S.match(old, new, lambda s: print("  " + s, file=sys.stderr))
    for x in a.addr:
        o = int(x, 16)
        if o not in M.pairs:
            print("0x%x: no counterpart" % o)
            continue
        n, score, how = M.pairs[o]
        la = ["%x %s %s" % (i.address, i.mnemonic, i.op_str) for i in old[o].insns]
        lb = ["%x %s %s" % (i.address, i.mnemonic, i.op_str) for i in new[n].insns]
        A, B = [norm(x_) for x_ in la], [norm(x_) for x_ in lb]
        out = []
        for t, i1, i2, j1, j2 in difflib.SequenceMatcher(None, A, B, autojunk=False).get_opcodes():
            if t != "equal":
                ca, cb = immediates(A[i1:i2]), immediates(B[j1:j2])
                if ca != cb:
                    out.append((i1, i2, j1, j2, dict(ca - cb), dict(cb - ca)))
        print("0x%x -> 0x%x (score %.2f, %s): %d places differ in a number" % (o, n, score, how, len(out)))
        for i1, i2, j1, j2, ca, cb in out:
            print("  old %d-%d, new %d-%d: only in old %s, only in new %s" % (i1, i2, j1, j2, ca, cb))
            if a.v:
                for x_ in A[max(0, i1 - 1):i2 + 1]:
                    print("     -", x_)
                for x_ in B[max(0, j1 - 1):j2 + 1]:
                    print("     +", x_)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("decks")
    d.add_argument("old_dir")
    d.add_argument("new_dir")
    d.add_argument("exe", help="the OLD program (MAGIC.EXE 1.0)")
    c = sub.add_parser("creatures")
    c.add_argument("old")
    c.add_argument("new")
    c.add_argument("--old-base", type=lambda s: int(s, 0), default=0x522628)
    c.add_argument("--new-base", type=lambda s: int(s, 0), default=0x57480f)
    f = sub.add_parser("fn")
    f.add_argument("old")
    f.add_argument("new")
    f.add_argument("addr", nargs="+")
    f.add_argument("-v", action="store_true")
    a = ap.parse_args()
    {"decks": cmd_decks, "creatures": cmd_creatures, "fn": cmd_fn}[a.cmd](a)


if __name__ == "__main__":
    main()

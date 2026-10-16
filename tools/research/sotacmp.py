#!/usr/bin/env python3
"""
sotacmp.py - compare the functions of two builds of a program (Magic: The Gathering 1.0 against Spells of the Ancients 2.0), from the machine code alone.

A research tool: nothing here is used by the installer, and nothing it prints holds game data (counts, addresses, scores). Give it two executables the user owns.
Needs pefile and capstone and the lifter in tools/lift (it uses fnscan.py to find the functions).

    sotacmp.py OLD.EXE NEW.EXE [--json out.json] [--map 0x4e7873,0x530da0,...] [--list]

What it does:
 1. finds the functions of each program (tools/lift/fnscan.py) and decodes them with capstone;
 2. makes four views of each function:
      exact   the bytes with every base relocation zeroed (an absolute address of the data moves when a program is relinked) and every call or jump to outside the function
              zeroed (relative), plus the names of the imports it calls (so two functions that differ in a Windows call are not the same);
      shape   the same, as instruction tokens (mnemonic, registers, small constants, field offsets of base+displacement operands; addresses are one token);
      strings the C strings its relocated operands point at;
      calls   the functions it calls, in order;
 3. matches old to new in stages: identical bytes; identical shape; then by the Dice coefficient of the shape's 3-grams (and shared strings), best candidates first, one to
    one; then through the call lists of matched functions, and through the gaps between matched neighbours (a program keeps its functions in the order of its objects);
 4. for an address of the old program (an entry, an address inside a function, or a global in the data), finds the new address: inside a matched pair by aligning the two
    instruction streams (difflib), for a global by the votes of every instruction that uses it.

The score is the Dice coefficient of the 3-grams of shape tokens, 1.0 for the same stream. A pair with a score of 0.5 or more has about half of its instruction triples in common.
"""
import argparse
import bisect
import difflib
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lift"))

import capstone  # noqa: E402
import pefile  # noqa: E402

import fnscan  # noqa: E402
from x86lift import Lifter, Unsupported  # noqa: E402

CS_REG, CS_IMM, CS_MEM = 1, 2, 3
PRINTABLE = re.compile(rb"^[\x20-\x7e\t\r\n]{4,}$")


# ---- a program ---------------------------------------------------------------------------------------------------------------------------------------------
class Image:
    def __init__(self, path):
        self.path = path
        self.pe = pe = pefile.PE(path)
        self.base = base = pe.OPTIONAL_HEADER.ImageBase
        self.sections = [(base + s.VirtualAddress, base + s.VirtualAddress + max(s.Misc_VirtualSize, s.SizeOfRawData), s.Name.rstrip(b"\0").decode(), s.Characteristics)
                         for s in pe.sections]
        self.relocs = set()
        for blk in getattr(pe, "DIRECTORY_ENTRY_BASERELOC", []):
            for ent in blk.entries:
                if ent.type == 3:
                    self.relocs.add(base + ent.rva)
        self.imports = {}                  # slot address -> name
        for dll in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
            for imp in dll.imports:
                if imp.name:
                    self.imports[imp.address] = dll.dll.decode().lower() + "!" + imp.name.decode()
        self.exports = {}
        for sym in getattr(getattr(pe, "DIRECTORY_ENTRY_EXPORT", None), "symbols", []):
            if sym.name:
                self.exports[base + sym.address] = sym.name.decode()
        self.code = [(lo, hi) for lo, hi, n, c in self.sections if c & 0x20000000 or n == "MPS_CODE"]
        self.data = [(lo, hi) for lo, hi, n, c in self.sections if not c & 0x20000000 and n not in (".reloc", ".idata", ".rsrc")]

    def get(self, va, n):
        for lo, hi, _, _ in self.sections:
            if lo <= va < hi:
                return self.pe.get_data(va - self.base, min(n, hi - va))
        raise Unsupported("0x%x is not in the image" % va)

    def in_code(self, a):
        return any(lo <= a < hi for lo, hi in self.code)

    def in_data(self, a):
        return any(lo <= a < hi for lo, hi in self.data)

    def section_of(self, a):
        for lo, hi, n, _ in self.sections:
            if lo <= a < hi:
                return n
        return None

    def cstring(self, a):
        try:
            blob = self.get(a, 120)
        except Unsupported:
            return None
        end = blob.find(b"\0")
        if end < 4:
            return None
        s = blob[:end]
        return s if PRINTABLE.match(s) else None


class Func:
    __slots__ = ("entry", "size", "nargs", "dead", "insns", "lo", "hi", "exact", "tokens", "strings", "calls", "imports", "refs", "shingles", "loose", "index")


def scan_functions(img, extra_roots=()):
    lifter = Lifter()
    lifter.imports.update({a: n.split("!", 1)[1] for a, n in img.imports.items()})
    gap = [(lo, hi) for lo, hi, n, c in img.sections if c & 0x20000000]
    code = list(img.code)
    data = [(lo, hi) for lo, hi in img.data]
    scan = fnscan.Scan(lifter, img.get, code, data, gap)
    found = scan.run([img.base + img.pe.OPTIONAL_HEADER.AddressOfEntryPoint, *extra_roots, *[a for a in img.exports if img.in_code(a)]])
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
    md.detail = True
    funcs = {}
    for a, f in found.items():
        fn = Func()
        fn.entry, fn.size, fn.nargs, fn.dead = a, f["size"], f["nargs"], f["dead"]
        if a in scan.parsed:
            insns = [i for _, i in sorted(scan.parsed[a][0].items())]
        else:
            insns = []
            for i in md.disasm(img.get(a, f["size"]), a):
                insns.append(i)
            while insns and insns[-1].mnemonic in ("int3", "nop") and len(insns) > 1:
                insns.pop()
        fn.insns = insns
        if not insns:
            continue
        fn.lo, fn.hi = insns[0].address, max(i.address + i.size for i in insns)
        describe(img, fn)
        funcs[a] = fn
    return funcs, scan


# ---- the views of a function -------------------------------------------------------------------------------------------------------------------------------
def describe(img, fn):
    raw = bytearray()
    toks, calls, strings, imports, refs = [], [], [], [], []
    for i in fn.insns:
        b = bytearray(i.bytes)
        absrefs = []
        for off in range(0, i.size - 3):
            if i.address + off in img.relocs:
                absrefs.append(int.from_bytes(b[off:off + 4], "little"))
                b[off:off + 4] = b"\0\0\0\0"
        m = i.mnemonic
        target = None
        if m in ("call", "jmp") or (m.startswith("j") and i.size == 6):
            if i.operands and i.operands[0].type == CS_IMM:
                target = i.operands[0].imm & 0xFFFFFFFF
                if i.size in (5, 6) and not (fn.lo <= target < fn.hi):
                    b[i.size - 4:i.size] = b"\0\0\0\0"          # relative: moves with the callee
        raw += bytes([len(b)]) + bytes(b)
        parts = [m]
        for op in i.operands:
            if op.type == CS_REG:
                parts.append(i.reg_name(op.reg))
            elif op.type == CS_IMM:
                if target is not None:
                    parts.append("T" if m != "call" else "C")
                elif (op.imm & 0xFFFFFFFF) in absrefs:
                    parts.append("A")
                else:
                    v = op.imm if op.imm < 0x80000000 else op.imm - (1 << 32)
                    parts.append(str(v) if -256 <= v <= 255 else "I")
            else:
                mm = op.mem
                d = mm.disp if mm.disp < 0x80000000 else mm.disp - (1 << 32)
                if (mm.disp & 0xFFFFFFFF) in absrefs:
                    disp = "A"                              # an address in the data: it moves when the program is relinked
                elif not d:
                    disp = ""
                else:
                    disp = "%+d" % d if abs(d) < 0x1000 else "+D"
                parts.append("[%s%s%s]" % (i.reg_name(mm.base) if mm.base else "", "+" + i.reg_name(mm.index) + "*%d" % mm.scale if mm.index else "", disp))
        for r in absrefs:
            if r in img.imports:
                imports.append(img.imports[r])
                parts.append("IMP:" + img.imports[r])
            elif img.in_code(r):
                parts.append("F")
            elif img.in_data(r):
                s = img.cstring(r)
                if s:
                    strings.append(s)
            refs.append((i.address, r))
        if target is not None and m == "call":
            calls.append(target)
        toks.append(" ".join(parts))
    fn.tokens = toks
    fn.calls = calls
    fn.strings = strings
    fn.imports = imports
    fn.refs = refs
    h = hashlib.sha1(bytes(raw))
    h.update("|".join(imports).encode())
    fn.exact = h.hexdigest()
    fn.loose = hashlib.sha1("\n".join(toks).encode()).hexdigest()
    sh = Counter(" ; ".join(toks[k:k + 3]) for k in range(max(1, len(toks) - 2)))
    for s in strings:
        sh["S:" + s.decode("latin-1")] += 3
    fn.shingles = sh


def dice(a, b):
    if not a or not b:
        return 0.0
    common = sum((a & b).values())
    return 2.0 * common / (sum(a.values()) + sum(b.values()))


# ---- matching ----------------------------------------------------------------------------------------------------------------------------------------------
class Match:
    def __init__(self, old, new):
        self.old, self.new = old, new
        self.pairs = {}               # old entry -> (new entry, score, how)
        self.rev = {}

    def add(self, o, n, score, how):
        if o in self.pairs or n in self.rev:
            return False
        self.pairs[o] = (n, score, how)
        self.rev[n] = o
        return True

    def unmatched_old(self):
        return [a for a in sorted(self.old) if a not in self.pairs]

    def unmatched_new(self):
        return [a for a in sorted(self.new) if a not in self.rev]


def match(old, new, log=lambda s: None):
    M = Match(old, new)
    # 1. identical bytes (relocations and relative targets masked); same bucket on both sides: in address order
    for key, how in (("exact", "identical"), ("loose", "same shape")):
        ob, nb = defaultdict(list), defaultdict(list)
        for a in sorted(old):
            if a not in M.pairs:
                ob[getattr(old[a], key)].append(a)
        for a in sorted(new):
            if a not in M.rev:
                nb[getattr(new[a], key)].append(a)
        for h, os_ in ob.items():
            ns = nb.get(h, [])
            if len(os_) == 1 and len(ns) == 1 or len(os_) == len(ns):
                for o, n in zip(os_, ns):
                    M.add(o, n, 1.0, how)
            else:
                # different counts: pair in order, as far as it goes (the extra ones stay unmatched or are matched below)
                for o, n in zip(os_, ns):
                    M.add(o, n, 1.0, how)
        log("%s: %d matched" % (how, len(M.pairs)))
    # 2. by similarity: candidates from an index of the rarer 3-grams of the new functions
    index = defaultdict(list)
    for a, f in new.items():
        if a in M.rev:
            continue
        for sh in f.shingles:
            index[sh].append(a)
    cands = []
    for o in M.unmatched_old():
        f = old[o]
        votes = Counter()
        for sh in f.shingles:
            lst = index.get(sh)
            if lst and len(lst) <= 25:
                for n in lst:
                    votes[n] += 1
        for n, _ in votes.most_common(8):
            s = dice(f.shingles, new[n].shingles)
            if s >= 0.35:
                cands.append((s, o, n))
    for s, o, n in sorted(cands, key=lambda c: (-c[0], c[1], c[2])):
        M.add(o, n, s, "similar")
    log("similarity: %d matched" % len(M.pairs))
    # 3. through the calls of matched functions and the gaps between matched neighbours, until nothing changes
    while True:
        changed = False
        for o, (n, _, _) in list(M.pairs.items()):
            oc = [c for c in old[o].calls if c in old]
            nc = [c for c in new[n].calls if c in new]
            if len(oc) == len(nc):
                for a, b in zip(oc, nc):
                    if a not in M.pairs and b not in M.rev:
                        s = dice(old[a].shingles, new[b].shingles)
                        if s >= 0.25:
                            changed |= M.add(a, b, s, "by call")
        keys = sorted(M.pairs)
        for k in range(len(keys) - 1):
            lo, hi = keys[k], keys[k + 1]
            nlo, nhi = M.pairs[lo][0], M.pairs[hi][0]
            if nhi <= nlo:
                continue
            os_ = [a for a in old if lo < a < hi and a not in M.pairs]
            ns = [a for a in new if nlo < a < nhi and a not in M.rev]
            if not os_ or not ns or len(os_) * len(ns) > 400:
                continue
            gc = sorted(((dice(old[o].shingles, new[n].shingles), o, n) for o in os_ for n in ns), reverse=True)
            for s, o, n in gc:
                if s >= 0.25:
                    changed |= M.add(o, n, s, "by position")
        if not changed:
            break
    log("propagation: %d matched" % len(M.pairs))
    resolve_ambiguous(M, log)
    return M


def callers_of(funcs):
    """{callee: set of functions that call it or take its address}"""
    out = defaultdict(set)
    for a, f in funcs.items():
        for c in f.calls:
            out[c].add(a)
        for _, r in f.refs:
            if r in funcs:
                out[r].add(a)
    return out


def resolve_ambiguous(M, log=lambda s: None):
    """Functions with identical bytes (small helpers, thunks, copies of one source function) cannot be told apart by their bytes. Pair them again by who calls them:
    an old function and a new one score for each caller of the old that is matched to a caller of the new one, and for each callee in the same way."""
    old, new = M.old, M.new
    oc, nc = callers_of(old), callers_of(new)
    groups = defaultdict(lambda: ([], []))
    for o, (n, s, how) in M.pairs.items():
        if how in ("identical", "same shape"):
            groups[getattr(old[o], "exact" if how == "identical" else "loose")][0].append(o)
            groups[getattr(old[o], "exact" if how == "identical" else "loose")][1].append(n)
    ambiguous = 0
    for key, (os_, ns) in groups.items():
        if len(os_) < 2:
            continue
        ambiguous += len(os_)
        for o in os_:
            del M.rev[M.pairs[o][0]]
        for o in os_:
            del M.pairs[o]
    # pass 1 counts only callers matched uniquely so far, then the groups are paired by score; repeat so that groups help each other
    for rnd in range(3):
        for key, (os_, ns) in groups.items():
            if len(os_) < 2:
                continue
            os_ = [o for o in os_ if o not in M.pairs]
            ns = [n for n in ns if n not in M.rev]
            scored = []
            for o in os_:
                for n in ns:
                    sc = sum(1 for c in oc.get(o, ()) if c in M.pairs and M.pairs[c][0] in nc.get(n, ()))
                    sc += sum(1 for c in old[o].calls if c in M.pairs and M.pairs[c][0] in new[n].calls)
                    scored.append((sc, -abs(o - n), o, n))
            for sc, _, o, n in sorted(scored, reverse=True):
                if sc > 0:
                    M.add(o, n, 1.0, "identical")
    for key, (os_, ns) in groups.items():       # what the callers could not decide: in address order, marked
        os_ = sorted(o for o in os_ if o not in M.pairs)
        ns = sorted(n for n in ns if n not in M.rev)
        for o, n in zip(os_, ns):
            M.add(o, n, 1.0, "identical (ambiguous)")
    log("%d functions had identical twins; resolved by callers" % ambiguous)


def consistency(M):
    """For each matched pair: of the callees of the old function that are matched, the fraction whose counterpart the new function also calls (None if it calls none)."""
    out = {}
    for o, (n, s, how) in M.pairs.items():
        cs = [c for c in set(M.old[o].calls) if c in M.pairs]
        if cs:
            nset = set(M.new[n].calls) | {r for _, r in M.new[n].refs}
            out[o] = sum(1 for c in cs if M.pairs[c][0] in nset) / len(cs)
    return out


def lis_outliers(M):
    """Matched pairs that are not on the longest increasing run of new addresses (the program keeps its functions in order, so these are moved or mismatched)."""
    keys = sorted(M.pairs)
    seq = [M.pairs[k][0] for k in keys]
    tails, idx, prev = [], [], [-1] * len(seq)
    for i, v in enumerate(seq):
        p = bisect.bisect_left(tails, v)
        if p == len(tails):
            tails.append(v)
            idx.append(i)
        else:
            tails[p] = v
            idx[p] = i
        prev[i] = idx[p - 1] if p else -1
    keep, i = set(), idx[-1] if idx else -1
    while i >= 0:
        keep.add(i)
        i = prev[i]
    return [keys[i] for i in range(len(keys)) if i not in keep]


# ---- addresses ---------------------------------------------------------------------------------------------------------------------------------------------
def containing(funcs, a):
    keys = sorted(funcs)
    i = bisect.bisect_right(keys, a) - 1
    if i >= 0 and funcs[keys[i]].lo <= a < funcs[keys[i]].hi + 16:
        return funcs[keys[i]]
    return None


_ALIGN = {}


def align(fo, fn):
    """Map instruction addresses of the old function to the new one: {old address: new address} for the instructions inside matching blocks of the two streams."""
    key = (fo.entry, fn.entry, len(fo.tokens), len(fn.tokens))
    if key in _ALIGN:
        return _ALIGN[key]
    sm = difflib.SequenceMatcher(None, fo.tokens, fn.tokens, autojunk=False)
    out = {}
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            out[fo.insns[a + k].address] = fn.insns[b + k].address
    _ALIGN[key] = out
    return out


def map_code_address(M, a):
    """(new address, how) for an address of the old program: a function entry, or an instruction inside a function."""
    f = containing(M.old, a)
    if f is None:
        return None, "not in a function the scan found"
    if f.entry not in M.pairs:
        return None, "its function (0x%x) has no counterpart" % f.entry
    n, score, how = M.pairs[f.entry]
    if a == f.entry:
        return n, "%s (%.2f)" % (how, score)
    al = align(f, M.new[n])
    if a in al:
        return al[a], "inside 0x%x -> 0x%x, %s (%.2f)" % (f.entry, n, how, score)
    return None, "inside 0x%x -> 0x%x (%.2f), but the instruction is not in a matching block" % (f.entry, n, score)


def map_data_address(M, a, old_img=None, new_img=None, span=1, min_score=0.5):
    """The new address of a global: the vote of every instruction that uses it (an address in a..a+span-1), in matched functions of a score of at least min_score, whose aligned
    instruction in the new function uses one address too. Returns (Counter of new addresses, number of uses seen)."""
    votes = Counter()
    sites = 0
    for o, (n, score, _) in M.pairs.items():
        fo = M.old[o]
        hit = [(ia, r) for ia, r in fo.refs if a <= r < a + span]
        if not hit:
            continue
        sites += len(hit)
        if score < min_score:
            continue
        fn = M.new[n]
        al = align(fo, fn)
        newrefs = {}
        for ia, r in fn.refs:
            newrefs.setdefault(ia, []).append(r)
        for ia, r in hit:
            na = al.get(ia)
            if na is not None and len(newrefs.get(na, [])) == 1:
                votes[newrefs[na][0] - (r - a)] += 1
    return votes, sites


def users_of(old, a, span=1):
    return [(f.entry, ia) for f in old.values() for ia, r in f.refs if a <= r < a + span]


# ---- report ------------------------------------------------------------------------------------------------------------------------------------------------
def band(score, how):
    if how in ("identical", "identical (ambiguous)"):
        return "identical"
    if how == "same shape":
        return "same shape"
    if score >= 0.9:
        return "0.9-1.0"
    if score >= 0.7:
        return "0.7-0.9"
    if score >= 0.5:
        return "0.5-0.7"
    return "below 0.5"


BANDS = ("identical", "same shape", "0.9-1.0", "0.7-0.9", "0.5-0.7", "below 0.5")


def summarize(name, old, new, M):
    cons = consistency(M)
    counts, cons_sum, strs, nbytes = Counter(), defaultdict(list), defaultdict(list), Counter()
    for o, (n, s, h) in M.pairs.items():
        b = band(s, h)
        counts[b] += 1
        nbytes[b] += old[o].hi - old[o].lo
        if o in cons:
            cons_sum[b].append(cons[o])
        if old[o].strings:        # independent of the score, for the pairs that have a string: does the new function show one of the old function's strings?
            strs[b].append(1.0 if set(old[o].strings) & set(new[n].strings) else 0.0)
    live_old = [a for a in old if not old[a].dead]
    live_new = [a for a in new if not new[a].dead]
    row = dict(name=name, old=len(old), new=len(new), old_reachable=len(live_old), new_reachable=len(live_new), matched=len(M.pairs),
               bands={b: counts[b] for b in BANDS},
               ambiguous_identical=sum(1 for _, _, h in M.pairs.values() if h == "identical (ambiguous)"),
               bytes_old={b: nbytes[b] for b in BANDS},
               bytes_old_total=sum(f.hi - f.lo for f in old.values()), bytes_new_total=sum(f.hi - f.lo for f in new.values()),
               string_agreement={b: [round(sum(v) / len(v), 2), len(v)] for b, v in strs.items() if v},
               call_consistency={b: round(sum(v) / len(v), 2) for b, v in cons_sum.items() if v},
               removed=len(old) - len(M.pairs), added=len(new) - len(M.pairs),
               removed_reachable=sum(1 for a in live_old if a not in M.pairs), added_reachable=sum(1 for a in live_new if a not in M.rev),
               matched_by=dict(Counter(h for _, _, h in M.pairs.values())), out_of_order=len(lis_outliers(M)))
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--json")
    ap.add_argument("--map", default="", help="old addresses to find in the new program: hex, comma-separated")
    ap.add_argument("--data", default="", help="old globals to find in the new program: hex, comma-separated")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--min-size", type=int, default=0)
    args = ap.parse_args()
    oi, ni = Image(args.old), Image(args.new)
    old, _ = scan_functions(oi)
    new, _ = scan_functions(ni)
    M = match(old, new, lambda s: print("  " + s, file=sys.stderr))
    row = summarize(os.path.basename(args.old) + " -> " + os.path.basename(args.new), old, new, M)
    print(json.dumps(row, indent=1))
    for x in filter(None, args.map.split(",")):
        a = int(x, 16)
        r, how = map_code_address(M, a)
        print("0x%x -> %s  %s" % (a, "0x%x" % r if r else "-", how))
    for x in filter(None, args.data.split(",")):
        a = int(x, 16)
        votes, sites = map_data_address(M, a, oi, ni)
        print("data 0x%x -> %s  (%d uses)" % (a, ", ".join("0x%x x%d" % kv for kv in votes.most_common(3)) or "-", sites))
    if args.list:
        for a in sorted(M.pairs):
            n, s, h = M.pairs[a]
            print("0x%08x 0x%08x %.2f %s" % (a, n, s, h))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(dict(summary=row, pairs={hex(a): [hex(n), round(s, 3), h] for a, (n, s, h) in sorted(M.pairs.items())},
                           removed=[hex(a) for a in M.unmatched_old()], added=[hex(a) for a in M.unmatched_new()]), f)


if __name__ == "__main__":
    main()

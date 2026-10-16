#!/usr/bin/env python3
"""
sotahooks.py - find the addresses the port keys to MAGIC.EXE 1.0 (src/port: pace.c, screens.c, yesno.c, textfocus.c, main.c, lzw.c, input.c, navwm.c, pad.c) in another build
of the game (the 2.0 executable), with the function matching of sotacmp.py.

    sotahooks.py OLD.EXE NEW.EXE [--json out.json]

The list below is what the port reads or hooks, by address, in version 1.0. Each entry says what the port does with it. The result per entry:
  same       the same address in the new program, and the code there is identical
  moved      identical code (relocations and relative targets masked) at another address
  changed    a counterpart with a similarity score (sotacmp.py); the code differs, so what the port does there has to be looked at again
  none       no counterpart found

Globals (data addresses) are found by the votes of the instructions that use them in matched functions: a global used at the same place of both versions of a
function has the same role. `n` is the number of agreeing uses out of all the uses found.
"""
import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sotacmp as sc  # noqa: E402

# (address, kind, role). kind: fn = a function entry; in = an address inside a function (a return site, an instruction); end = the end of a function; data = a global;
# local = a frame-relative local of the function at `fn` (given as "ebp-0xa8@0x509517")
HOOKS = [
    # pace.c
    (0x5016f9, "fn", "pace.c: overridden. Reads and clears the 33 ms tick counter"),
    (0x4e7873, "in", "pace.c: return site of the tick call in the overworld loop (frame pacing)"),
    (0x4e73a0, "fn", "pace.c, screens.c: the overworld loop (start of the range the map loop is recognised by)"),
    (0x4e7936, "end", "pace.c, screens.c: the overworld loop (end of the range)"),
    (0x41f3ea, "fn", "pace.c, screens.c: pre-call hook, the button table's pass (once per loop of every screen with buttons)"),
    (0x530da0, "data", "pace.c: the tick counter"),
    (0x7039c4, "data", "pace.c: the mouse button state"),
    # screens.c
    (0x41f354, "fn", "screens.c: push a button-table context"),
    (0x41f391, "fn", "screens.c: pop a button-table context"),
    (0x44b84b, "fn", "screens.c: pre-call hook, the mouse snapshot"),
    (0x489748, "fn", "screens.c: the text menu loop (start)"),
    (0x489c9c, "end", "screens.c: the text menu loop (end)"),
    (0x509517, "fn", "screens.c: 'Cards for Sale' loop (start)"),
    (0x509fd4, "end", "screens.c: 'Cards for Sale' loop (end)"),
    (0x48f523, "fn", "screens.c: clues loop (start)"),
    (0x49094c, "end", "screens.c: clues loop (end)"),
    (0x519c24, "data", "screens.c: the current button-table context"),
    (0x67f780, "data", "screens.c: records per context"),
    (0x67f7d0, "data", "screens.c: record pointers per context"),
    (0x539dec, "data", "screens.c: text menu left edge"),
    (0x539df0, "data", "screens.c: text menu top"),
    (0x676d44, "data", "screens.c: text menu right edge"),
    (0x527b30, "data", "screens.c: text menu line height"),
    (0x676d50, "data", "screens.c: text menu first choice line"),
    (0x676d40, "data", "screens.c: text menu choice count"),
    (0x676d58, "data", "screens.c: text menu mask of shut choices"),
    (0x61e060, "data", "screens.c: the cards for sale (ids)"),
    ("ebp-0xa8@0x509517", "local", "screens.c: number of cards for sale (a local of the loop)"),
    ("ebp-0xa0@0x509517", "local", "screens.c: the card boxes (locals of the loop)"),
    ("ebp-0x12d8@0x48f523", "local", "screens.c: number of rows with a dungeon (a local of the clues loop)"),
    # yesno.c, textfocus.c
    (0x48ac2f, "fn", "yesno.c: pre-call hook, wait for a key"),
    (0x4080b2, "fn", "yesno.c, textfocus.c: pre-call hook, pop a key from the game's key queue"),
    (0x48ac3d, "in", "yesno.c: where the poll in the wait loop returns to"),
    (0x509e4a, "in", "yesno.c: yes/no site, 'Buy for N gold? (Y/N)' (return of the wait-for-key call)"),
    (0x4f156e, "in", "yesno.c: yes/no site, 'Sell ... (Y/N)'"),
    (0x45119d, "in", "yesno.c: yes/no site, 'Take ... (Y/N)'"),
    (0x47be64, "fn", "textfocus.c: the new game's name box loop (start)"),
    (0x47c080, "end", "textfocus.c: the name box loop (end)"),
    # main.c
    (0x522458, "data", "main.c: screen width the game's layouts read (written at start for 800x600 and 1024x768)"),
    (0x52245c, "data", "main.c: screen height"),
    # lzw.c
    (0x70d000, "fn", "lzw.c: overridden. Picture decompressor, header reader (MPS_CODE)"),
    (0x70d484, "fn", "lzw.c: overridden. Decoder to a destination"),
    (0x70d1fc, "fn", "lzw.c: overridden. Decoder, second entry"),
    (0x50e8b0, "fn", "lzw.c: the callback it calls with the dictionary block"),
    (0x706500, "data", "lzw.c: input pointer"),
    (0x5327b0, "data", "lzw.c: input end"),
    (0x67f43c, "data", "lzw.c: refill callback"),
    (0x532860, "data", "lzw.c: dictionary block (the state block lies behind it, at fixed offsets)"),
    # other
    (0x40a3e1, "fn", "input.c: (comment) waits for the button release after the deck builder returns"),
    (0x4e7a6f, "fn", "pad.c: (comment) the map's walking code"),
    (0x4262cf, "fn", "navwm.c: (comment) the phase column's icon test"),
    (0x427a0a, "fn", "navwm.c: (comment) the combat column's icons"),
    (0x4b9284, "fn", "navwm.c: (comment) the mana pool's window procedure"),
    (0x424500, "fn", "stdio.c: (comment) reads PROMPTS.TXT"),
]

# functions the port hooks that are called from several places: their call sites are compared old against new (the yes/no sites are the return addresses of the wait-for-key call)
CALLED = [(0x48ac2f, "wait for a key (yesno.c)"), (0x4080b2, "pop a key (yesno.c, textfocus.c)"), (0x41f3ea, "button table pass (pace.c, screens.c)"),
          (0x44b84b, "mouse snapshot (screens.c)"), (0x5016f9, "tick read-and-clear (pace.c)")]

CLASSES = ["MAGICGAME_CardClass", "MAGICGAME_BigCardCardClass", "MAGICGAME_LifeClass", "MAGICGAME_FaceClass", "MAGICGAME_GraveyardClass", "MAGICGAME_LibraryClass",
           "MAGICGAME_ManaSummaryClass", "MAGICGAME_PhaseDisplayClass", "MAGICGAME_AttackPhaseDisplayClass", "MAGICGAME_ScrollbarClass", "MAGIC_TellUserClass",
           "MAGICDECK_CardClass", "MAGICDECK_MainClass", "MAGICGAME_MainClass"]


def function_status(M, a, what):
    n, how = sc.map_code_address(M, a)
    if n is None:
        return dict(old=a, new=None, status="none", how=how)
    f = sc.containing(M.old, a)
    score = M.pairs[f.entry][1]
    how_matched = M.pairs[f.entry][2]
    if how_matched.startswith("identical") or how_matched == "same shape":
        status = "same" if n == a else "moved"
    else:
        status = "changed"
    return dict(old=a, new=n, status=status, score=round(score, 2), how=how)


def local_status(M, spec):
    reg_disp, entry = spec.split("@")
    disp = int(reg_disp.split("ebp")[1], 16)
    entry = int(entry, 16)
    if entry not in M.pairs:
        return dict(old=spec, new=None, status="none", how="its function has no counterpart")
    n = M.pairs[entry][0]
    fo, fn = M.old[entry], M.new[n]
    al = sc.align(fo, fn)
    votes = Counter()
    sites = 0
    idx_o = {i.address: i for i in fo.insns}
    idx_n = {i.address: i for i in fn.insns}
    for ia, i in idx_o.items():
        for op in i.operands:
            if op.type == sc.CS_MEM and op.mem.base and i.reg_name(op.mem.base) == "ebp" and op.mem.disp == disp:
                sites += 1
                na = al.get(ia)
                if na is None:
                    continue
                for nop in idx_n[na].operands:
                    if nop.type == sc.CS_MEM and nop.mem.base and idx_n[na].reg_name(nop.mem.base) == "ebp":
                        votes[nop.mem.disp] += 1
    if not votes:
        return dict(old=spec, new=None, status="none", how="no aligned use of the local in 0x%x (%d uses)" % (n, sites))
    d, k = votes.most_common(1)[0]
    return dict(old=spec, new="ebp%+#x@0x%x" % (d, n), status="same" if d == disp else "moved", how="%d of %d uses agree" % (k, sites))


def data_status(M, a):
    votes, sites = sc.map_data_address(M, a, None, None)
    if not votes:
        return dict(old=a, new=None, status="none", how="%d uses in matched functions, none aligned" % sites)
    (n, k), = votes.most_common(1)
    total = sum(votes.values())
    strong = k >= 3 and k * 2 >= sites and k * 4 >= total * 3
    return dict(old=a, new=n, status="same" if n == a else "moved", conf="strong" if strong else "weak",
                how="%s: %d of %d uses agree (%d aligned)" % ("strong" if strong else "weak", k, sites, total))


def call_sites(funcs, target):
    """[(function entry, return address)] for every direct call of `target` in the scanned functions."""
    out = []
    for f in funcs.values():
        for k, i in enumerate(f.insns):
            if i.mnemonic == "call" and i.operands and i.operands[0].type == sc.CS_IMM and (i.operands[0].imm & 0xFFFFFFFF) == target:
                out.append((f.entry, i.address + i.size))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("old")
    ap.add_argument("new")
    ap.add_argument("--json")
    ap.add_argument("--match-json", help="reuse the pairs a previous sotacmp.py run wrote with --json (saves the scan)")
    args = ap.parse_args()
    oi, ni = sc.Image(args.old), sc.Image(args.new)
    old, _ = sc.scan_functions(oi)
    new, _ = sc.scan_functions(ni)
    M = sc.match(old, new)
    rows = []
    for a, kind, role in HOOKS:
        if kind == "fn" or kind == "in":
            r = function_status(M, a, kind)
        elif kind == "end":
            r = function_status(M, a, kind)
            # an end address is the first byte after the function: the new end is where the counterpart ends
            f = sc.containing(M.old, a - 1)
            if f is not None and f.entry in M.pairs:
                nf = M.new[M.pairs[f.entry][0]]
                r["new"] = nf.hi
                r["how"] = "end of the counterpart of 0x%x (0x%x..0x%x), %s" % (f.entry, nf.lo, nf.hi, M.pairs[f.entry][2])
                r["status"] = "changed" if M.pairs[f.entry][2] not in ("identical", "same shape") else ("same" if nf.hi == a else "moved")
        elif kind == "data":
            r = data_status(M, a)
        else:
            r = local_status(M, a)
        r.update(kind=kind, role=role)
        rows.append(r)
    for r in rows:
        old_s = "0x%x" % r["old"] if isinstance(r["old"], int) else r["old"]
        new_s = ("0x%x" % r["new"] if isinstance(r["new"], int) else r["new"]) or "-"
        print("%-22s %-8s %-8s %-22s %s | %s" % (old_s, r["kind"], r["status"], new_s, r["role"], r["how"]))
    print()
    called = []
    for a, what in CALLED:
        n = M.pairs.get(a, (None,))[0]
        if n is None:
            print("calls of 0x%x (%s): its counterpart was not found" % (a, what))
            continue
        os_, ns = call_sites(old, a), call_sites(new, n)
        paired = sum(1 for f, _ in ns if f in M.rev and any(of == M.rev[f] for of, _ in os_))
        print("calls of 0x%x -> 0x%x (%s): %d sites in the old program, %d in the new; %d of the new sites are in a function that is matched to one of the old callers"
              % (a, n, what, len(os_), len(ns), paired))
        called.append(dict(old=a, new=n, what=what, old_sites=len(os_), new_sites=len(ns), paired=paired, new_returns=[hex(r) for _, r in ns]))
        if a == 0x48ac2f:
            print("   old return addresses: " + " ".join("0x%x" % r for _, r in os_))
            print("   new return addresses: " + " ".join("0x%x" % r for _, r in ns))
    print()
    for c in CLASSES:
        found = False
        for lo, hi, n, ch in ni.sections:
            if not ch & 0x20000000 and c.encode() in ni.pe.get_data(lo - ni.base, hi - lo):
                found = True
        print("class %-36s %s" % (c, "present" if found else "absent"))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(dict(rows=rows, called=called), f, indent=1)


if __name__ == "__main__":
    main()

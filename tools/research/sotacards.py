#!/usr/bin/env python3
"""
sotacards.py - structure and differences of CARDS.DAT across builds (1.0, Spells of the Ancients 2.0 / 2.15, ManaLink 3.0 = Duels of the Planeswalkers). Prints COUNTS, never card text,
apart from at most a few card names as examples (`--examples N`, default 3).

    sotacards.py LABEL=CARDS.DAT [LABEL=CARDS.DAT ...]        the first is the oldest; each file is compared with the one before it and with the first

The file (little-endian; found on the 1.0 and SotA discs and checked against file sizes of every build):

    u32 count (999)    u32 size of the string pool
    count records of 152 bytes (38 u32), indexed by card id (record 0 is the first card; `id` at +0 equals the index but for the first)
    the string pool (NUL-terminated strings) until the end of the file:   file size == 8 + count*152 + pool size, exactly, in all four builds

A record holds a card's id, four string references (offsets into the pool: the full name, the short name, the rules text, the flavour text) and numeric fields (type and colour flags,
cost, power and toughness, the rarity and edition, ...: not all decoded). A slot whose name is the string "None" is unused. The game's own master card table (an array in the program,
0x34 bytes a card in 1.0, 0x48 in SotA, with the code pointer of the card's rules at +0x10) is a separate thing: this file only supplies the texts and the descriptive numbers.

For each pair: used slots, cards added (a name used now and not in the older file), removed, ids whose card changed name, and among the same id and name the records whose rules text,
flavour text, short name or numeric fields differ (the string offsets themselves always move and are not compared).
"""
import struct
import sys

REC = 152
NAME, SHORT, TEXT, FLAVOR = 1, 2, 29, 30
STR_COLS = (NAME, SHORT, TEXT, FLAVOR)
PTR_COLS = (1, 2, 19, 20, 21, 22, 29, 30, 37)    # string references (19 to 22: names of the card's sound files; 37: a short string)
NOISE_COLS = (6, 7, 17)                          # words that differ in nearly every record of every build and are not card data (leftovers of the build that wrote the file)


def load(path):
    with open(path, "rb") as f:
        d = f.read()
    n, pool = struct.unpack_from("<II", d, 0)
    if 8 + n * REC + pool != len(d):
        raise SystemExit("%s: size %d is not 8 + %d*152 + %d" % (path, len(d), n, pool))
    base = 8 + n * REC

    def s(o):
        end = d.index(b"\0", base + o)
        return d[base + o:end].decode("latin-1")

    def ref(v):
        """A string reference if the value points at a sound-file name or a short string, else the value itself (these columns also hold small numbers)."""
        if v < 0x40 or v >= pool:
            return v
        t = s(v)
        return t if t.lower().endswith(".wvl") or (len(t) < 8 and t.isalnum()) else v

    cards = []
    for i in range(n):
        r = struct.unpack_from("<38I", d, 8 + i * REC)
        cards.append(dict(id=i, name=s(r[NAME]), short=s(r[SHORT]), text=s(r[TEXT]), flavor=s(r[FLAVOR]),
                          extra=tuple(ref(r[c]) for c in PTR_COLS if c not in STR_COLS),
                          nums=tuple(v for c, v in enumerate(r) if c not in PTR_COLS and c not in NOISE_COLS and c != 0), raw=r))
    return d, n, pool, cards


def used(cards):
    return {c["name"]: c for c in cards if c["name"] not in ("None", "")}


def main(argv):
    ex = 3
    args = argv[1:]
    if "--examples" in args:
        i = args.index("--examples")
        ex = int(args[i + 1])
        del args[i:i + 2]
    if not args:
        print(__doc__)
        return 2
    loaded = []
    for a in args:
        label, _, path = a.partition("=")
        loaded.append((label, load(path)))
    for k, (label, (d, n, pool, cards)) in enumerate(loaded):
        u = used(cards)
        print("%-6s %7d bytes  %d records of %d bytes, pool %d bytes; used slots %d (unused %d); distinct names %d" % (label, len(d), n, REC, pool, sum(1 for c in cards if c["name"] not in ("None", "")),
                                                                                                    sum(1 for c in cards if c["name"] in ("None", "")), len(u)))
    pairs = [(loaded[i - 1], loaded[i]) for i in range(1, len(loaded))]
    if len(loaded) > 2:
        pairs += [(loaded[0], loaded[i]) for i in range(2, len(loaded))]
    for (la, (_da, _na, _pa, ca)), (lb, (_db, _nb, _pb, cb)) in pairs:
        ua, ub = used(ca), used(cb)
        added = sorted(set(ub) - set(ua))
        removed = sorted(set(ua) - set(ub))
        same_id_other_name = [i for i in range(min(len(ca), len(cb))) if ca[i]["name"] != cb[i]["name"] and ca[i]["name"] not in ("None", "") and cb[i]["name"] not in ("None", "")]
        moved = [n for n in set(ua) & set(ub) if ua[n]["id"] != ub[n]["id"]]
        txt = fl = sh = nm = rf = 0
        changed = []
        for name in set(ua) & set(ub):
            a, b = ua[name], ub[name]
            t, f, s_, n_, r_ = a["text"] != b["text"], a["flavor"] != b["flavor"], a["short"] != b["short"], a["nums"] != b["nums"], a["extra"] != b["extra"]
            txt += t
            fl += f
            sh += s_
            nm += n_
            rf += r_
            if t or f or s_ or n_ or r_:
                changed.append(name)
        print("%s -> %s: added %d, removed %d, ids that hold another card %d, cards at another id %d; same card changed in %d (rules text %d, flavour %d, short name %d, numeric fields %d, "
              "sound-file references %d)" % (la, lb, len(added), len(removed), len(same_id_other_name), len(moved), len(changed), txt, fl, sh, nm, rf))
        if added:
            print("   e.g. added: " + ", ".join(added[:ex]))
        if removed:
            print("   e.g. removed: " + ", ".join(removed[:ex]))
        if changed:
            print("   e.g. changed: " + ", ".join(sorted(changed)[:ex]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

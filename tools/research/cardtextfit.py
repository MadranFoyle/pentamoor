#!/usr/bin/env python3
"""
Which model of Windows' text metrics fits what the original measured (docs/notes/card-text-metrics.md).

    python3 tools/research/cardtextfit.py PROBE.jsonl [SCALE] [TTF]

PROBE.jsonl is the output of tools/verification_harness/probe_card_text.py (GetTextExtentPoint32 of the words and spaces of a card at 640x480); SCALE the horizontal scale of the card's mapping (default 0.745: the
card's MM_ISOTROPIC window 200 x 300 on viewport 160 x 224 is cut to 149 x 224, so x is 149 / 200); TTF the font (default the game's TT0298M_.TTF in sources/installed/Magic/Program, MPZurich Cn BT).
For each guess of the ppem, of the way the advances are rounded (each glyph to a whole pixel, or only the total), of kerning and of the conversion to logical units (truncating or rounding) it counts the
strings whose extent the guess gets wrong. The best row has 0: 8 ppem, each advance rounded, no kerning, the device width divided by the scale and rounded.
"""
import json
import math
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TTF = os.path.join(HERE, "..", "..", "sources", "installed", "Magic", "Program", "TT0298M_.TTF")


class Font:
    def __init__(self, path):
        self.d = d = open(path, "rb").read()
        n = struct.unpack_from(">H", d, 4)[0]
        self.tabs = {}
        for i in range(n):
            tag, _cs, off, ln = struct.unpack_from(">4sIII", d, 12 + 16 * i)
            self.tabs[tag.decode()] = (off, ln)
        self.upem = struct.unpack_from(">H", d, self.tabs["head"][0] + 18)[0]
        self.nh = struct.unpack_from(">H", d, self.tabs["hhea"][0] + 34)[0]
        cm = self.tabs["cmap"][0]
        for i in range(struct.unpack_from(">H", d, cm + 2)[0]):
            pid, eid, off = struct.unpack_from(">HHI", d, cm + 4 + 8 * i)
            if pid == 3 and eid == 1:
                self.sub = cm + off
        self.segc = struct.unpack_from(">H", d, self.sub + 6)[0] // 2
        s, c = self.sub, self.segc
        self.ends = struct.unpack_from(">%dH" % c, d, s + 14)
        self.starts = struct.unpack_from(">%dH" % c, d, s + 16 + 2 * c)
        self.deltas = struct.unpack_from(">%dh" % c, d, s + 16 + 4 * c)
        self.ro = s + 16 + 6 * c
        self.ros = struct.unpack_from(">%dH" % c, d, self.ro)
        self.kern = {}
        if "kern" in self.tabs:
            k = self.tabs["kern"][0]
            o = k + 4
            for _ in range(struct.unpack_from(">H", d, k + 2)[0]):
                _v, ln, cov = struct.unpack_from(">HHH", d, o)
                if cov >> 8 == 0:
                    for j in range(struct.unpack_from(">H", d, o + 6)[0]):
                        l, r, v = struct.unpack_from(">HHh", d, o + 14 + 6 * j)
                        self.kern[(l, r)] = v
                o += ln

    def gid(self, c):
        for i in range(self.segc):
            if self.starts[i] <= c <= self.ends[i]:
                if self.ros[i] == 0:
                    return (c + self.deltas[i]) & 0xFFFF
                g = struct.unpack_from(">H", self.d, self.ro + 2 * i + self.ros[i] + 2 * (c - self.starts[i]))[0]
                return (g + self.deltas[i]) & 0xFFFF if g else 0
        return 0

    def adv(self, ch):
        g = min(self.gid(ord(ch)), self.nh - 1)
        return struct.unpack_from(">H", self.d, self.tabs["hmtx"][0] + 4 * g)[0]


def main():
    recs = [json.loads(l) for l in open(sys.argv[1])]
    scale = float(sys.argv[2]) if len(sys.argv) > 2 else 0.745
    f = Font(sys.argv[3] if len(sys.argv) > 3 else TTF)
    words = {}
    for r in recs:
        if r["k"] == "ext" and r.get("s") is not None and r.get("cx") is not None:
            words.setdefault(r["s"], r["cx"])
    print(len(words), "distinct strings, scale", scale)

    def device(s, ppem, mode, kern):
        w = 0.0
        for i, c in enumerate(s):
            a = f.adv(c) * ppem / f.upem
            w += math.floor(a + 0.5) if mode == "round each" else a
            if kern and i + 1 < len(s):
                w += f.kern.get((f.gid(ord(c)), f.gid(ord(s[i + 1]))), 0) * ppem / f.upem
        return math.floor(w + 0.5) if mode == "total" else w

    rows = []
    for ppem in (8, 8.34, 8.64, 9, 10):
        for mode in ("round each", "total"):
            for kern in (False, True):
                for how in ("truncate", "round"):
                    bad = 0
                    for s, cx in words.items():
                        x = device(s, ppem, mode, kern) / scale
                        if (int(x) if how == "truncate" else int(math.floor(x + 0.5))) != cx:
                            bad += 1
                    rows.append((bad, ppem, mode, "kerning" if kern else "no kerning", how))
    rows.sort()
    for r in rows[:8]:
        print("%3d wrong: ppem %s, advances %s, %s, logical by %s" % r)


if __name__ == "__main__":
    main()

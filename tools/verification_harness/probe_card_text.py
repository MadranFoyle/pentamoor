#!/usr/bin/env python3
"""
What the original's card text routine asks GDI and gets back (docs/notes/card-text-metrics.md).

Breakpoints in MAGIC.EXE 1.0 (virtual addresses; all the programs load at 0x400000, so check a hit's registers before believing it):

    0x49e7c2 / 0x49e7c8   before / after GetTextExtentPoint32A, the spaces of the word layout        (hdc, string, length, &SIZE) -> SIZE
    0x49eb41 / 0x49eb47   the same, the words
    0x49ea69 / 0x49ea6f   the same, a third site of the layout
    GetTextMetricsA at 0x49e0ba, 0x49e625, 0x49d60e, 0x49d7c5, 0x49dcf7, 0x4f4f85   (hdc, &TEXTMETRIC) -> TEXTMETRIC
    CreateFontIndirectA at 0x49e077 and the nine of 0x49b3fd..0x49b4d5                (&LOGFONT)

Prints one JSON object per line: {"k": "ext", "s": the string, "cx", "cy"}, {"k": "tm", "site", "tm": the eleven numbers of the structure}, {"k": "font", "site", "h", "weight", "face"}.

    python3 probe_card_text.py SECONDS [OUTFILE]

Run it after oracle_launch.sh, with the game in the VM at a screen where a card is about to be drawn: an encounter's ante screen (walk on the map until monsters come: oracle_ctl.py hold X Y S). The
breakpoints are in place from the start, so what the game draws in the meantime is logged. Leaves the breakpoints cleared and the guest running, as probe_hits.py does.
"""
import json
import struct
import sys
import time

import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from oracle_qemu import GDBRemote  # noqa: E402

EXT_SITES = {0x49e7c2: 0x49e7c8, 0x49eb41: 0x49eb47, 0x49ea69: 0x49ea6f}        # call site: the address after the call (an indirect call through the import table is 6 bytes)
TM_SITES = {a: a + 6 for a in (0x49e0ba, 0x49e625, 0x49d60e, 0x49d7c5, 0x49dcf7, 0x4f4f85)}
FONT_SITES = [0x49e077, 0x49b3fd, 0x49b418, 0x49b433, 0x49b44e, 0x49b469, 0x49b484, 0x49b49f, 0x49b4ba, 0x49b4d5]


def main(argv):
    seconds = float(argv[0])
    out = open(argv[1], "w") if len(argv) > 1 else sys.stdout
    after = {}
    for a, b in EXT_SITES.items():
        after[b] = (a, "ext")
    for a, b in TM_SITES.items():
        after[b] = (a, "tm")
    breakpoints = list(EXT_SITES) + list(TM_SITES) + list(after) + FONT_SITES
    pending = {}
    g = GDBRemote()
    g.sock.settimeout(30)
    t0 = time.time()
    try:
        for a in breakpoints:
            g.set_breakpoint(a)
        g.cont()
        while time.time() - t0 < seconds:
            try:
                g.wait_stop(timeout=1.0)
            except OSError:
                continue
            regs = g.read_registers()
            eip, esp = regs["eip"], regs["esp"]
            try:
                stack = struct.unpack("<4I", g.read_memory(esp, 16))
            except (OSError, IOError):
                stack = ()
            rec = None
            if eip in EXT_SITES and stack:
                try:
                    s = g.read_memory(stack[1], stack[2]).decode("latin1") if 0 < stack[2] < 200 else None
                except (OSError, IOError):
                    s = None
                pending[eip] = (s, stack[3])
            elif eip in TM_SITES and stack:
                pending[eip] = (None, stack[1])
            elif eip in after:
                site, kind = after[eip]
                p = pending.pop(site, None)
                if p:
                    try:
                        if kind == "ext":
                            cx, cy = struct.unpack("<ii", g.read_memory(p[1], 8))
                            rec = {"k": "ext", "s": p[0], "cx": cx, "cy": cy}
                        else:
                            rec = {"k": "tm", "site": hex(site), "tm": list(struct.unpack("<11i", g.read_memory(p[1], 44)))}
                    except (OSError, IOError):
                        pass
            elif eip in FONT_SITES and stack:
                try:
                    lf = g.read_memory(stack[0], 60)
                    h, w, _esc, _orient, weight = struct.unpack("<5i", lf[:20])
                    rec = {"k": "font", "site": hex(eip), "h": h, "weight": weight, "face": lf[28:60].split(b"\0")[0].decode("latin1")}
                except (OSError, IOError):
                    pass
            if rec:
                rec["t"] = round(time.time() - t0, 2)
                out.write(json.dumps(rec) + "\n")
                out.flush()
            if eip in breakpoints:                  # QEMU's stub re-triggers a breakpoint at the PC on continue: step off it first
                g.clear_breakpoint(eip)
                g.step()
                g.set_breakpoint(eip)
            g.cont()
    finally:
        try:
            g.interrupt()
        except (OSError, IOError):
            pass
        for a in breakpoints:
            try:
                g.clear_breakpoint(a)
            except (OSError, IOError):
                pass
        try:
            g.step()
            g.cont()
            time.sleep(0.3)
        finally:
            g.close()


if __name__ == "__main__":
    main(sys.argv[1:])

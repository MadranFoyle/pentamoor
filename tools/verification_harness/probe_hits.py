#!/usr/bin/env python3
"""
Log every time the original runs one of some addresses: set breakpoints, and for each hit print the time, the label, the registers that matter and the first
stack words (the return address and the arguments of a function entered by `call`), step off the breakpoint, and let the guest go on. Drive the guest (clicks,
keys: oracle_ctl.py) from another terminal while this runs.

    python3 probe_hits.py SECONDS ADDR[=label] [ADDR[=label] ...]

  ADDR            a virtual address in hex (a DLL that loaded at another base than its image base is found by reading a pointer into it first:
                  the guest's STATWIN.DLL sat at 0x01650000, so its 0x10002209 was 0x01652209)
Always leaves the breakpoints cleared and the guest running; if the program was killed hard, `oracle_ctl.py status` says `debug` and `probe_hits.py 0` resumes it.

A breakpoint is matched by EIP in whatever process is running, so check a hit's registers before believing it (all programs load at 0x00400000).
"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from oracle_qemu import GDBRemote


def main(argv):
    seconds = float(argv[0])
    bps = {}
    for arg in argv[1:]:
        addr, _, label = arg.partition("=")
        bps[int(addr, 16)] = label or addr
    g = GDBRemote()
    g.sock.settimeout(30)
    t0 = time.time()
    try:
        for a in bps:
            g.set_breakpoint(a)
        print("armed %d breakpoints" % len(bps), flush=True)
        g.cont()
        while time.time() - t0 < seconds:
            try:
                g.wait_stop(timeout=1.0)
            except OSError:
                continue
            regs = g.read_registers()
            eip = regs["eip"]
            try:
                stack = struct.unpack("<5I", g.read_memory(regs["esp"], 20))
            except (OSError, IOError):
                stack = ()
            label = bps.get(eip, "?")
            print("%7.2f %s eip=%x esp=%x stack=%s eax=%x ecx=%x" % (time.time() - t0, label, eip, regs["esp"], [hex(x) for x in stack], regs["eax"], regs["ecx"]), flush=True)
            if eip in bps:                                  # QEMU's stub re-triggers a breakpoint at the PC on continue: step off it first
                g.clear_breakpoint(eip)
                g.step()
                g.set_breakpoint(eip)
            g.cont()
    finally:
        try:
            g.interrupt()
        except (OSError, IOError):
            pass
        for a in bps:
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

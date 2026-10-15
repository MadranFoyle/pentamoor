#!/usr/bin/env python3
"""
First oracle experiment: is `Magic_DrawCardPhase` (0x00474c7f in MAGIC.EXE) really a draw step?

The decompiled body does not draw anything: it loops 0x14 times, builds a path from
g_DuelSoundsDirectory + a table of *.wav names, and calls InitSndTrack(path, i, 0).
This probe breaks on the function and on that callee in the live game and records:
  * whether/when the function runs (startup, main menu, or only once a duel is under way),
  * for every caller of the callee (by return address): how often, and which strings it passes.

Usage (VM booted with oracle_launch.sh, so the game autolaunches from Startup):
    python3 probe_drawcard.py <qmp.sock> [timeout_seconds]
Writes probe_drawcard.json and probe_drawcard.png into the current directory.
"""

import json
import socket
import sys
import time

from oracle_qemu import QMP, GDBRemote

FUNC = 0x00474C7F       # Magic_DrawCardPhase (decomp name)
FUNC_END = 0x00474D0E   # next function starts here (sizes tile, see docs/ORACLE_VM.md)
CALLEE = 0x00423B57     # InitSndTrack (decomp name)
BPS = {FUNC, CALLEE}
# First bytes of the function in MAGIC.EXE (push ebp; mov ebp,esp; sub esp,0x12c). DUEL.EXE and the
# other programs load at the same base address, so a breakpoint here can fire in the wrong
# process; only trust a hit whose code bytes match.
FUNC_BYTES = bytes.fromhex("558bec81ec2c0100")


def main():
    budget = float(sys.argv[2]) if len(sys.argv) > 2 else 240
    qmp = QMP(sys.argv[1])
    gdb = GDBRemote()                      # attaching pauses the guest
    for a in BPS:
        gdb.set_breakpoint(a)
    print(f"[{time.strftime('%X')}] breakpoints set; resuming guest", flush=True)
    gdb.cont()

    callers = {}           # return address -> {count, strings}
    func_hits = []
    after_func = 0
    t0 = time.time()
    last_key = 0.0
    while time.time() - t0 < budget:
        # Windows shows a harmless vnetbios.vxd "press a key" prompt early in boot.
        if time.time() - t0 < 90 and time.time() - last_key > 8:
            qmp.send_key("ret")
            last_key = time.time()
        try:
            gdb.wait_stop(timeout=2)
        except socket.timeout:
            continue
        regs = gdb.read_registers()
        eip, esp = regs["eip"], regs["esp"]
        if eip == FUNC:
            caller = int.from_bytes(gdb.read_memory(esp, 4), "little")
            func_hits.append({"t": round(time.time() - t0, 1), "called_from": f"0x{caller:08x}",
                              "code_matches_magic_exe": gdb.read_memory(FUNC, 8) == FUNC_BYTES})
            print("Magic_DrawCardPhase entered:", func_hits[-1], flush=True)
        elif eip == CALLEE:
            ret = int.from_bytes(gdb.read_memory(esp, 4), "little")
            arg0 = int.from_bytes(gdb.read_memory(esp + 4, 4), "little")
            s = gdb.read_cstring(arg0).decode("latin-1")
            c = callers.setdefault(f"0x{ret:08x}", {"count": 0, "in_func": FUNC <= ret < FUNC_END,
                                                    "first_seen_s": round(time.time() - t0, 1),
                                                    "strings": []})
            c["count"] += 1
            if s not in c["strings"] and len(c["strings"]) < 6:
                c["strings"].append(s)
                print(f"  caller 0x{ret:08x}: new string {s!r}", flush=True)
        if func_hits:
            after_func += 1
            if after_func > 60:            # enough to see what the function's loop passes
                break
        gdb.resume(BPS)

    result = {"function_hits": func_hits, "InitSndTrack": callers,
              "elapsed_s": round(time.time() - t0, 1)}
    with open("probe_drawcard.json", "w") as f:
        json.dump(result, f, indent=2)
    qmp.screendump("probe_drawcard.png")
    print("done:", json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()

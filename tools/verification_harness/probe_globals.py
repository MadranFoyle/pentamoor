#!/usr/bin/env python3
"""
Live check of the three renamed MAGIC.EXE globals (docs/SYMBOL_VERIFICATION.md):

    0x006b2534  g_EventSourcePlayer  (was g_OverworldPlayerCoordX)
    0x0070100c  g_EventSourceSlot    (was g_OverworldMapGrid)
    0x0068a660  g_CardEventResult    (was g_ActivePalette)

Sets a write watchpoint on each. Every time the game writes one, it records which function
did it, the value now in memory, and the writer's stack arguments (ebp+8 onward), so we can
see whether the values written are the function's own (player, card slot) arguments.

Run while a duel is in progress (the game is MAGIC.EXE):
    python3 probe_globals.py [seconds] [max_events]
Writes probe_globals.json into the current directory.
"""
import json
import os
import socket
import struct
import sys
import time

from oracle_qemu import GDBRemote

HERE = os.path.dirname(os.path.abspath(__file__))
WATCH = {0x006B2534: "g_EventSourcePlayer", 0x0070100C: "g_EventSourceSlot",
         0x0068A660: "g_CardEventResult"}


def load_functions():
    """(address, name, size) of every function of MAGIC.EXE, found in its own code (tools/lift/fnscan.py)."""
    sys.path.insert(0, os.path.join(HERE, "..", "lift"))
    from fnscan import scan_file  # noqa: PLC0415
    exe = os.environ.get("PENTAMOOR_GAME", os.path.join(HERE, "..", "..", "sources", "installed", "Magic", "Program"))
    return sorted((a, f["name"], f["size"]) for a, f in scan_file(os.path.join(exe, "MAGIC.EXE")).items())


def owner(fns, va):
    best = None
    for a, n, sz in fns:
        if a <= va:
            best = (a, n, sz)
        else:
            break
    return best


def u32(gdb, addr):
    return struct.unpack("<I", gdb.read_memory(addr, 4))[0]


def main():
    budget = float(sys.argv[1]) if len(sys.argv) > 1 else 600
    max_events = int(sys.argv[2]) if len(sys.argv) > 2 else 400
    fns = load_functions()
    gdb = GDBRemote()
    for a in WATCH:
        gdb.set_watchpoint(a)
    print(f"[{time.strftime('%X')}] watchpoints set on {[hex(a) for a in WATCH]}; resuming", flush=True)
    gdb.cont()

    events, seen = [], {}
    t0 = time.time()
    while time.time() - t0 < budget and len(events) < max_events:
        try:
            stop = gdb.wait_stop(timeout=2)
        except socket.timeout:
            continue
        addr = GDBRemote.watch_address(stop)
        if addr not in WATCH:
            gdb.cont()
            continue
        regs = gdb.read_registers()
        try:
            at_stop = u32(gdb, addr)
            gdb.step()                                     # let the write complete
            after = u32(gdb, addr)
            r2 = gdb.read_registers()
            args = [u32(gdb, regs["ebp"] + 8 + 4 * i) for i in range(6)]
        except IOError as e:
            print("read failed:", e, flush=True)
            gdb.cont()
            continue
        fn = owner(fns, regs["eip"])
        key = (WATCH[addr], fn[1] if fn else "?")
        seen[key] = seen.get(key, 0) + 1
        ev = {"t": round(time.time() - t0, 1), "global": WATCH[addr], "written_by": fn[1] if fn else "?",
              "fn_addr": f"0x{fn[0]:08x}" if fn else None, "eip": f"0x{regs['eip']:08x}",
              "value_at_stop": at_stop, "value_after_step": after,
              "ebp_args": args}
        events.append(ev)
        if seen[key] <= 4:
            print(json.dumps(ev), flush=True)
        gdb.cont()

    for a in WATCH:
        try:
            gdb.clear_watchpoint(a)
        except Exception:
            pass
    try:
        gdb.cont()
    except Exception:
        pass
    summary = {f"{g} <- {f}": n for (g, f), n in sorted(seen.items())}
    with open("probe_globals.json", "w") as f:
        json.dump({"summary": summary, "events": events}, f, indent=2)
    print("done:", json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Light live check of the three combat call sites of Magic_RunTurnStep in the turn loop
(FUN_00501f50 in MAGIC.EXE). Breaking on Magic_RunTurnStep itself slows the game to a crawl,
because the spell-chain window calls it many times a second; these call instructions run only
when combat steps really happen.

    0x005043fd  call Magic_RunTurnStep(player, 0xdc, "Pay for attacker", 1)
    0x005046ff  call Magic_RunTurnStep(1 - player, 0xda, "Choose Defenders", 0)
    0x0050481e  call Magic_RunTurnStep(player, 0xd9, "Choose Attackers", 0)

    python3 probe_combat_sites.py [seconds]        -> probe_combat_sites.json
"""
import json
import signal
import socket
import struct
import sys
import time

from oracle_qemu import GDBRemote

SITES = {0x005043FD: "Pay for attacker", 0x005046FF: "Choose Defenders", 0x0050481E: "Choose Attackers"}


def u32(gdb, addr):
    return struct.unpack("<I", gdb.read_memory(addr, 4))[0]


def main():
    budget = float(sys.argv[1]) if len(sys.argv) > 1 else 1800
    gdb = GDBRemote()
    for a in SITES:
        gdb.set_breakpoint(a)
    print(f"[{time.strftime('%X')}] armed {[hex(a) for a in SITES]}", flush=True)
    gdb.cont()
    stopping, events, t0 = [], [], time.time()
    signal.signal(signal.SIGTERM, lambda *a: stopping.append(1))
    signal.signal(signal.SIGINT, lambda *a: stopping.append(1))
    while time.time() - t0 < budget and not stopping:
        try:
            gdb.wait_stop(timeout=2)
        except socket.timeout:
            continue
        regs = gdb.read_registers()
        ev = {"t": round(time.time() - t0, 1), "site": f"0x{regs['eip']:08x}", "label": SITES.get(regs["eip"])}
        try:
            ev["code_at_site"] = gdb.read_memory(regs["eip"], 1).hex()      # e8 = the call, so the code is MAGIC.EXE's
            player, code, name_ptr, repeat = [u32(gdb, regs["esp"] + 4 * i) for i in range(4)]
            ev.update(player=player, step_code=f"0x{code:x}", step_name=gdb.read_cstring(name_ptr).decode("latin-1"),
                      repeat_while_active=repeat)
        except IOError as e:
            ev["error"] = str(e)
        events.append(ev)
        print(json.dumps(ev), flush=True)
        gdb.resume(set(SITES))
    try:
        gdb.interrupt()
        pc = gdb.read_registers()["eip"]
        if pc in SITES:
            gdb.clear_breakpoint(pc)
            gdb.step()
    except Exception:
        pass
    for a in SITES:
        try:
            gdb.clear_breakpoint(a)
        except Exception:
            pass
    try:
        gdb.cont()
    except Exception:
        pass
    json.dump(events, open("probe_combat_sites.json", "w"), indent=2)
    print("done:", len(events), "events", flush=True)


if __name__ == "__main__":
    main()

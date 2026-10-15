#!/usr/bin/env python3
"""
Live check of Magic_RunTurnStep (MAGIC.EXE 0x0047624f), g_CurrentStepCode (0x006ff4c0) and the
spell-stack operations (push 0x004751d7, resolve 0x004756a1, drop 0x00475bb0, clear 0x00474d1e).

Static analysis says: Magic_RunTurnStep(player, step_code, step_name, wait_for_pass) sets
g_CurrentStepCode to step_code, runs the step, and sets it back to -1. This probe records, on
the live game,
  * every entry of Magic_RunTurnStep: its four stack arguments, and the step name string;
  * every write to g_CurrentStepCode: the value now in memory and the function that wrote it.

Attach once a duel is on screen (watchpoints on hot pages can make the guest stop taking clicks
if they are armed earlier), then click Done to step through turns.

    python3 probe_steps.py [seconds] [max_events] [nowatch]      -> probe_steps.json
"""
import json
import os
import signal
import socket
import struct
import sys
import time

from oracle_qemu import GDBRemote

HERE = os.path.dirname(os.path.abspath(__file__))
RUN_STEP = 0x0047624F
STEP_CODE = 0x006FF4C0
STACK_COUNT = 0x006A3F78          # g_SpellStackCount
# The spell-stack operations (static names, docs/SYMBOL_VERIFICATION.md); the probe records the stack
# depth on entry and, for the push, its arguments.
STACK_FUNCS = {0x004751D7: ("Magic_PushSpellStack", 5), 0x004756A1: ("Magic_ResolveTopSpell", 0),
               0x00475BB0: ("Magic_DropTopSpell", 0), 0x00474D1E: ("Magic_ClearSpellStack", 0)}
BREAKS = {RUN_STEP} | set(STACK_FUNCS)
NOWATCH = "nowatch" in sys.argv[3:]      # skip the write watchpoint (it can make the duel drop clicks)
PROGRAM = os.path.join(HERE, "..", "..", "sources", "installed", "Magic", "Program", "MAGIC.EXE")


def file_bytes(va, n=8):
    d = open(PROGRAM, "rb").read()
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    nsec, optsz = struct.unpack_from("<H", d, pe + 6)[0], struct.unpack_from("<H", d, pe + 20)[0]
    base = struct.unpack_from("<I", d, pe + 24 + 28)[0]
    for i in range(nsec):
        o = pe + 24 + optsz + i * 40
        vsz, rva, rsz, roff = struct.unpack_from("<IIII", d, o + 8)
        if base + rva <= va < base + rva + max(vsz, rsz):
            return d[roff + (va - base - rva):][:n]
    raise ValueError(hex(va))


def functions():
    """(address, name) of every function of MAGIC.EXE, found in its own code (tools/lift/fnscan.py)."""
    sys.path.insert(0, os.path.join(HERE, "..", "lift"))
    from fnscan import scan_file  # noqa: PLC0415
    exe = os.environ.get("PENTAMOOR_GAME", os.path.join(HERE, "..", "..", "sources", "installed", "Magic", "Program"))
    return sorted((a, f["name"]) for a, f in scan_file(os.path.join(exe, "MAGIC.EXE")).items())


def owner(fns, va):
    best = None
    for a, n in fns:
        if a <= va:
            best = (a, n)
        else:
            break
    return best


def u32(gdb, addr):
    return struct.unpack("<I", gdb.read_memory(addr, 4))[0]


def main():
    budget = float(sys.argv[1]) if len(sys.argv) > 1 else 900
    max_events = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    fns = functions()
    want = {a: file_bytes(a) for a in BREAKS}
    gdb = GDBRemote()
    for a in BREAKS:
        gdb.set_breakpoint(a)
    if not NOWATCH:
        gdb.set_watchpoint(STEP_CODE)
    print(f"[{time.strftime('%X')}] armed: breakpoints {[hex(a) for a in sorted(BREAKS)]}, write watchpoint {'off' if NOWATCH else hex(STEP_CODE)}", flush=True)
    gdb.cont()

    events, recent, t0 = [], [], time.time()
    stopping = []
    signal.signal(signal.SIGTERM, lambda *a: stopping.append(1))   # stop cleanly: breakpoints out, guest resumed
    signal.signal(signal.SIGINT, lambda *a: stopping.append(1))
    while time.time() - t0 < budget and len(events) < max_events and not stopping:
        try:
            stop = gdb.wait_stop(timeout=2)
        except socket.timeout:
            continue
        regs = gdb.read_registers()
        t = round(time.time() - t0, 1)
        watched = GDBRemote.watch_address(stop)
        if watched == STEP_CODE:
            gdb.step()                                    # let the write complete
            ev = {"t": t, "kind": "write g_CurrentStepCode", "value": u32(gdb, STEP_CODE),
                  "written_by": (owner(fns, regs["eip"]) or ("?", "?"))[1],
                  "eip": f"0x{regs['eip']:08x}"}
        elif regs["eip"] in STACK_FUNCS:
            name, nargs = STACK_FUNCS[regs["eip"]]
            try:
                ok = gdb.read_memory(regs["eip"], 8) == want[regs["eip"]]
            except IOError:
                ok = None
            esp = regs["esp"]
            ev = {"t": t, "kind": f"enter {name}", "code_matches": ok, "called_from": f"0x{u32(gdb, esp):08x}"}
            if ok is not None:
                ev["stack_count_before"] = u32(gdb, STACK_COUNT)
                if nargs:
                    ev["args"] = [u32(gdb, esp + 4 + 4 * i) for i in range(nargs)]
        elif regs["eip"] == RUN_STEP:
            try:
                ok = gdb.read_memory(RUN_STEP, 8) == want[RUN_STEP]
            except IOError:                               # code page not resident yet
                ok = None
            esp = regs["esp"]
            try:
                player, code, name_ptr, wait = [u32(gdb, esp + 4 + 4 * i) for i in range(4)]
                name = gdb.read_cstring(name_ptr).decode("latin-1") if name_ptr else None
            except IOError:
                player = code = wait = name = None
            ev = {"t": t, "kind": "enter Magic_RunTurnStep", "code_matches": ok,
                  "player": player, "step_code": None if code is None else f"0x{code:x}",
                  "step_name": name, "wait_for_pass": wait,
                  "step_code_before": u32(gdb, STEP_CODE) if ok is not None else None,
                  "called_from": f"0x{u32(gdb, esp):08x}"}
        else:
            ev = {"t": t, "kind": f"other stop {stop!r}"}
        events.append(ev)
        # The spell-chain window polls (resolve / Casting / End of Turn many times a second):
        # print an event only if its signature was not among the last 40, and save as we go.
        sig = (ev["kind"], ev.get("player"), ev.get("step_code"), ev.get("called_from"), ev.get("stack_count_before"))
        if sig not in recent:
            print(json.dumps(ev), flush=True)
        recent.append(sig)
        del recent[:-40]
        if len(events) % 200 == 0:
            json.dump(events, open("probe_steps.json", "w"))
        gdb.resume(BREAKS)

    try:                                                  # the guest is running here: stop it, and if it is on
        gdb.interrupt()                                   # one of our breakpoints, step off it before removing them
        pc = gdb.read_registers()["eip"]
        if pc in BREAKS:
            gdb.clear_breakpoint(pc)
            gdb.step()
    except Exception:
        pass
    for fn in [lambda a=a: gdb.clear_breakpoint(a) for a in BREAKS] + [lambda: gdb.clear_watchpoint(STEP_CODE), gdb.cont]:
        try:
            fn()
        except Exception:
            pass
    json.dump(events, open("probe_steps.json", "w"), indent=2)
    print("done:", len(events), "events", flush=True)


if __name__ == "__main__":
    main()

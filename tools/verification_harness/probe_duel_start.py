#!/usr/bin/env python3
"""
Second oracle experiment: what runs when a duel starts?

With the game sitting on the "Duel a <wizard>" screen and the pointer over the Duel choice
(see oracle_ctl.py), attach the debugger, click, and record which of these fire:

  * Magic_DrawCardPhase   MAGIC.EXE 0x00474c7f  (decomp label: the draw step)
  * DUEL.EXE entry point  0x004dea30            (proves duels run in a separate process)

Every program loads at 0x00400000, so a hit only counts if the code bytes at the address are
the ones from the matching file in sources/installed (`code_matches`).

    python3 probe_duel_start.py <qmp.sock> [seconds] [noclick] [duel]

With `noclick` it only watches (use it once the duel is already under way). The control channel
is opened only briefly, so other tools (oracle_ctl.py) can use it while the probe waits.
"""
import json
import os
import socket
import struct
import sys
import time

from oracle_qemu import QMP, GDBRemote

PROGRAM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                       "sources", "installed", "Magic", "Program")


def code_bytes(exe, va, n=8):
    """Bytes at virtual address `va` as stored in the PE file on disk."""
    d = open(os.path.join(PROGRAM, exe), "rb").read()
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    nsec, optsz = struct.unpack_from("<H", d, pe + 6)[0], struct.unpack_from("<H", d, pe + 20)[0]
    base = struct.unpack_from("<I", d, pe + 24 + 28)[0]
    for i in range(nsec):
        o = pe + 24 + optsz + i * 40
        vsz, rva, rsz, roff = struct.unpack_from("<IIII", d, o + 8)
        if base + rva <= va < base + rva + max(vsz, rsz):
            return d[roff + (va - base - rva):][:n]
    raise ValueError(hex(va))


MAGIC_TARGETS = {
    0x00474C7F: ("MAGIC.EXE", "Duel_PreloadSoundEffects (was Magic_DrawCardPhase)"),
    0x0046F5D1: ("MAGIC.EXE", "Magic_ExecuteDrawPhase (arg0 = player)"),
    0x0047496B: ("MAGIC.EXE", "Duel_PlaySoundById (arg0 = sound id; only id 2 = draw.wav recorded)"),
}
# DUEL.EXE has twins of the same engine (identified by size and structure, not yet renamed).
DUEL_TARGETS = {
    0x004DEA30: ("DUEL.EXE", "DUEL.EXE entry point"),
    0x00487CE1: ("DUEL.EXE", "draw twin FUN_00487ce1 (arg0 = player)"),
    0x0048D320: ("DUEL.EXE", "sound preloader twin FUN_0048d320"),
    0x0048D00C: ("DUEL.EXE", "sound player twin Sound_PlayTrackById (arg0 = sound id; only id 2 recorded)"),
}
# Select the set with the word "duel" on the command line; the default is MAGIC.EXE.
TARGETS = DUEL_TARGETS if "duel" in sys.argv[3:] else MAGIC_TARGETS
SOUND_PLAYER = 0x0048D00C if "duel" in sys.argv[3:] else 0x0047496B


def main():
    budget = float(sys.argv[2]) if len(sys.argv) > 2 else 120
    click = "noclick" not in sys.argv[3:]
    gdb = GDBRemote()
    expected = {va: code_bytes(exe, va) for va, (exe, _) in TARGETS.items()}
    for va in TARGETS:
        gdb.set_breakpoint(va)
    gdb.cont()
    if click:
        qmp = QMP(sys.argv[1])
        qmp.click()                 # pointer is already over the button to press
        qmp.close()
    t0 = time.time()
    events = []
    while time.time() - t0 < budget:
        try:
            gdb.wait_stop(timeout=2)
        except socket.timeout:
            continue
        regs = gdb.read_registers()
        va = regs["eip"]
        if va in TARGETS:
            exe, label = TARGETS[va]
            try:
                matches = gdb.read_memory(va, 8) == expected[va]
            except IOError:                # page not resident yet (demand paging); the retry
                matches = None             # after resume() will hit again with readable code
            ev = {"t": round(time.time() - t0, 1), "label": label, "eip": f"0x{va:08x}",
                  "code_matches": matches, "matches_exe": exe,
                  "ret": f"0x{int.from_bytes(gdb.read_memory(regs['esp'], 4), 'little'):08x}",
                  "arg0": int.from_bytes(gdb.read_memory(regs["esp"] + 4, 4), "little")}
            if va == SOUND_PLAYER and ev["arg0"] != 2:
                gdb.resume(set(TARGETS))     # ignore every sound except draw.wav (id 2)
                continue
            events.append(ev)
            print(json.dumps(ev), flush=True)
        gdb.resume(set(TARGETS))
        if len(events) >= 60:
            break
    with open("probe_duel_start.json", "w") as f:
        json.dump(events, f, indent=2)
    qmp = QMP(sys.argv[1])
    qmp.screendump(os.path.abspath("probe_duel_start.png"))
    qmp.close()
    print("done:", len(events), "events", flush=True)


if __name__ == "__main__":
    main()

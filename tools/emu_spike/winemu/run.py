#!/usr/bin/env python3
"""
Run MAGIC.EXE (or another PE) in the emulated Win32 host.

    python3 -m winemu.run [--exe PATH] [--seconds N] [--trace] [--trace-only REGEX] [--log-files]
                          [--shots DIR] [--quiet]

Run from tools/emu_spike. Game files come from sources/installed/Magic (your own copy); writes go to
sources/emu_overlay so the installed copy is never modified. The screen is composed from the windows the
game creates and saved as PNG in --shots (default sources/emu_shots) when the run ends.
"""
import argparse
import json
import os
import random
import re
import struct
import sys
import time

import numpy as np
from PIL import Image

from . import crt, gdi, kernel32, kernel32_rt, magsnd, movie, user32                              # noqa: F401  (register handlers)
from .machine import Machine

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))


def draw_dialogs(m, desk):
    """A plain rendering of open dialogs (grey panel, control text) so a script can see what is on screen."""
    from PIL import ImageDraw, ImageFont
    st = m.state.get("u32", {})
    img = Image.fromarray(desk)
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 11)
    except OSError:
        font = ImageFont.load_default()
    for h in st.get("dialogs", []):
        win = st["windows"].get(h)
        if not win:
            continue
        x0, y0 = win["x"], win["y"]
        d.rectangle([x0, y0, x0 + win["w"], y0 + win["h"]], fill=(212, 208, 200), outline=(0, 0, 0))
        d.text((x0 + 6, y0 + 3), win["title"] or "Dialog", fill=(0, 0, 128), font=font)
        sf = win["surface"]
        if sf is not None and (sf.idx.any() or sf.direct.any()):             # what the game itself painted on the dialog (the ante cards)
            painted = np.logical_or(sf.idx != 0, sf.direct)
            rgb = gdi.surface_rgb(m, sf)
            mask = Image.fromarray((painted * 255).astype(np.uint8))
            img.paste(Image.fromarray(rgb), (x0, y0), mask)
        for c in win["children"]:
            cw = st["windows"].get(c)
            if not cw or not cw["visible"]:
                continue
            cx0, cy0, cx1, cy1 = x0 + cw["x"], y0 + cw["y"], x0 + cw["x"] + cw["w"], y0 + cw["y"] + cw["h"]
            cls = str(cw["cls"]).upper()
            text = cw["title"]
            if cw.get("movie"):                                                       # a playing movie (coin toss)
                frame = gdi.surface_rgb(m, cw["surface"])
                img.paste(Image.fromarray(frame), (cx0, cy0))
                d = ImageDraw.Draw(img)
            elif cls == "BUTTON":
                style = cw["style"] & 0xF
                if style in (2, 3, 4, 5, 6, 9):                                       # radio / check boxes
                    d.ellipse([cx0, cy0 + 1, cx0 + 9, cy0 + 10], outline=(0, 0, 0), fill=(255, 255, 255))
                    if cw.get("checked"):
                        d.ellipse([cx0 + 3, cy0 + 4, cx0 + 6, cy0 + 7], fill=(0, 0, 0))
                    d.text((cx0 + 14, cy0), text.replace("&", ""), fill=(0, 0, 0), font=font)
                elif style == 7:                                                      # group box
                    d.rectangle([cx0, cy0 + 5, cx1, cy1], outline=(128, 128, 128))
                    d.text((cx0 + 8, cy0), text.replace("&", ""), fill=(0, 0, 0), font=font)
                else:
                    d.rectangle([cx0, cy0, cx1, cy1], fill=(224, 224, 224), outline=(0, 0, 0))
                    d.text((cx0 + 4, cy0 + 2), text.replace("&", ""), fill=(0, 0, 0), font=font)
            elif cls == "COMBOBOX":
                d.rectangle([cx0, cy0, cx1, cy0 + 16], fill=(255, 255, 255), outline=(0, 0, 0))
                sel = cw.get("sel", -1)
                items = cw.get("items", [])
                d.text((cx0 + 3, cy0 + 2), items[sel][0] if 0 <= sel < len(items) else "", fill=(0, 0, 0), font=font)
            else:
                d.text((cx0, cy0), text.replace("&", ""), fill=(0, 0, 0), font=font)
    return np.asarray(img)


def compose(m):
    """Paint every visible window, parents before children, children offset by their parent's position."""
    st = m.state.get("u32", {})
    desk = np.zeros((gdi.SCREEN_H, gdi.SCREEN_W, 3), np.uint8)
    wins = st.get("windows", {})
    movie.tick(m)

    def paint(win, ox, oy):
        s = win["surface"]
        x, y = ox + win["x"], oy + win["y"]
        if s is not None and (win["proc"] or win.get("ownerdraw") or win.get("movie")):
            x0, y0 = max(x, 0), max(y, 0)
            x1, y1 = min(x + s.w, desk.shape[1]), min(y + s.h, desk.shape[0])
            if x1 > x0 and y1 > y0:
                desk[y0:y1, x0:x1] = gdi.surface_rgb(m, s, x0 - x, y0 - y, x1 - x, y1 - y)
        for c in sorted((wins[c] for c in win["children"] if c in wins), key=lambda w: w["z"]):      # bottom to top
            if c["visible"]:
                paint(c, x, y)

    for hwnd, win in sorted(wins.items(), key=lambda kv: kv[1]["z"]):
        if win["visible"] and not win["style"] & user32.WS_CHILD and hwnd != st.get("desktop_hwnd") \
                and not win.get("dialog"):
            paint(win, 0, 0)
    return draw_popup(m, draw_dialogs(m, draw_buttons(m, desk)))


def draw_buttons(m, desk):
    """Built-in push buttons that live on ordinary windows (the prompt bar's Done button): the game never paints them, Windows does."""
    st = m.state.get("u32", {})
    wins = st.get("windows", {})
    todo = []
    for h, w in wins.items():
        if str(w["cls"]).upper() != "BUTTON" or w["proc"] or w.get("ownerdraw") or not w["visible"] or w["w"] <= 0 or w["h"] <= 0 or (w["style"] & 0xF) not in (0, 1):
            continue
        anc, ok, in_dialog = w, True, False
        while anc["parent"] and anc["parent"] in wins:
            anc = wins[anc["parent"]]
            ok = ok and anc["visible"]
            in_dialog = in_dialog or bool(anc.get("dialog") or anc.get("dlgproc"))
        if ok and not in_dialog and w["title"]:
            todo.append(w)
    if not todo:
        return desk
    from PIL import ImageDraw, ImageFont
    img = Image.fromarray(desk)
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 11)
    except OSError:
        font = ImageFont.load_default()
    for w in todo:
        x0, y0, x1, y1 = user32.abs_rect(m, w)
        pressed = st.get("press") == w["hwnd"]
        d.rectangle([x0, y0, x1 - 1, y1 - 1], fill=(192, 192, 192))
        light, dark = ((128, 128, 128), (255, 255, 255)) if pressed else ((255, 255, 255), (96, 96, 96))
        d.line([(x0, y0), (x1 - 1, y0)], fill=light)
        d.line([(x0, y0), (x0, y1 - 1)], fill=light)
        d.line([(x0, y1 - 1), (x1 - 1, y1 - 1)], fill=dark)
        d.line([(x1 - 1, y0), (x1 - 1, y1 - 1)], fill=dark)
        label = w["title"].replace("&", "")
        tw = int(font.getlength(label))
        d.text((x0 + (x1 - x0 - tw) // 2 + (1 if pressed else 0), y0 + (y1 - y0 - 11) // 2 - 1 + (1 if pressed else 0)), label, fill=(0, 0, 0), font=font)
    return np.asarray(img)


def draw_popup(m, desk):
    """The open popup menu (user32.track_popup_menu), if any, over the screen."""
    popup = m.state.get("u32", {}).get("popup")
    if not popup:
        return desk
    from PIL import ImageDraw, ImageFont
    img = Image.fromarray(desk)
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 12)
    except OSError:
        font = ImageFont.load_default()
    for x, y, w, h, rows in user32.popup_levels(m, popup):
        d.rectangle([x, y, x + w - 1, y + h - 1], fill=(240, 240, 240), outline=(60, 60, 60))
        for it, y0, y1 in rows:
            if it["flags"] & user32.MF_SEPARATOR:
                d.line([x + 3, (y0 + y1) // 2, x + w - 4, (y0 + y1) // 2], fill=(150, 150, 150))
                continue
            grey = bool(it["flags"] & (user32.MF_GRAYED | user32.MF_DISABLED))
            hot = popup["hover"] is it and not grey
            if hot:
                d.rectangle([x + 2, y0, x + w - 3, y1 - 1], fill=(0, 0, 128))
            colour = (255, 255, 255) if hot else (150, 150, 150) if grey else (0, 0, 0)
            if it["flags"] & user32.MF_CHECKED:
                d.text((x + 6, y0 + 2), "v", fill=colour, font=font)
            label, _, accel = it["text"].replace("&", "").partition("\t")           # "Show ID tags<TAB>Ctrl+T": the shortcut sits at the right
            d.text((x + 20, y0 + 2), label, fill=colour, font=font)
            if accel:
                d.text((x + w - 8 - int(font.getlength(accel)), y0 + 2), accel, fill=colour, font=font)
            if it["flags"] & user32.MF_POPUP:
                d.text((x + w - 12, y0 + 2), ">", fill=colour, font=font)
    return np.asarray(img)


def card_desc(m, args):
    """For a call whose first two arguments are (player, slot) of DUEL.EXE: the card's name, its master-record stats
    (colour byte at +6, power/toughness shorts at +0xa/+0xc, abilities dword at +0x14, flag dword at +0x18) and the slot's own fields."""
    pl, sl = args[0], args[1]
    cid = m.r32(0x6826C4 + sl * 0x120 + pl * 0x5B20)
    rec = 0x4FF590 + cid * 0x34
    nm = m.cstr(m.r32(0x618AC4 + m.r32(rec) * 0x98), 30).decode("latin-1")
    sh = lambda a: (lambda v: v - 65536 if v & 0x8000 else v)(m.r32(a) & 0xFFFF)
    return (f"[{nm!r} p{pl}s{sl} flags={m.r32(0x6826CC + sl * 0x120 + pl * 0x5B20):#x} "
            f"rec: col={m.r32(rec + 4) >> 16 & 0xFF} p={sh(rec + 0xa)} t={sh(rec + 0xc)} ab={m.r32(rec + 0x14):#x} w18={m.r32(rec + 0x18):#x}]")


def duel_native_entries():
    """Where the native layer's functions start in DUEL.EXE (src/native/layout.c): the original's versions are left alone when a
    native function, or the native scan, is what is being recorded."""
    text = open(os.path.join(os.path.dirname(__file__), "..", "..", "..", "src", "native", "layout.c")).read()
    block = text[text.index("const Layout LAYOUT_DUEL"):]
    entry = block[block.index(".entry"):]
    return {int(a, 16) for a in re.findall(r"\[FN_\w+\] = (0x[0-9a-fA-F]+)", entry)}


def patch_calls(mm, pending, handler, k, rng, extra=(), skip=frozenset()):
    """Make the functions a lifted handler calls (LIFT_SPEC lists them; `handler` None = the calls of every handler) return
    K at once, so the handler runs on its own: a call that would open a prompt or wait on the UI cannot stall it, and what
    each callee returned is exactly what the lifted code is later given. `r` picks a value per function from the rng. An
    import (Sleep) is called through a slot in the import table: the slot is pointed at a stand-in in free space, as the
    real function would block this thread. Returns what to put back."""
    patched = []
    spec = os.environ.get("LIFT_SPEC")
    if not spec:
        return patched
    if "lift_spec" not in pending:
        pending["lift_spec"] = {int(e["addr"], 16): e for e in json.load(open(spec)) if e.get("lifted")}
    entries = list(pending["lift_spec"].values()) if handler is None else [pending["lift_spec"].get(handler, {})]
    if handler is None:
        skip = set(skip) | set(pending["lift_spec"])   # with every handler in play, a handler another one calls must still run
    entries.append({"calls": [{"addr": f"{a:#x}", "cleanup": 0} for a in extra]})   # functions native code calls that are not lifted
    seen = set()
    for e in entries:
        for c in e.get("calls", []):
            a = int(c["addr"], 16)
            if a in seen or a in skip:
                continue
            seen.add(a)
            kv = rng.choice((0, 1, 2, 3, 5, 8, 16, 100, 0xFFFFFFFF)) if k == "r" else int(k, 0)
            stub = b"\xb8" + struct.pack("<I", kv) + (b"\xc2" + struct.pack("<H", c["cleanup"]) if c["cleanup"] else b"\xc3")
            if c.get("import_slot"):
                where = int(c["stub"], 16)
                mm.uc.mem_write(where, stub)
                mm.uc.ctl_remove_cache(where, where + len(stub))
                patched.append((a, bytes(mm.uc.mem_read(a, 4))))
                mm.uc.mem_write(a, struct.pack("<I", where))
                continue
            patched.append((a, bytes(mm.uc.mem_read(a, len(stub)))))
            mm.uc.mem_write(a, stub)
            mm.uc.ctl_remove_cache(a, a + len(stub))     # or a function the game already ran keeps its old code
    return patched


def fuzz_board(mm, rng, total=None):
    """Put up to a dozen cards with random handlers in play (both players), their fields filled with arbitrary values, and
    list them in the scan's order arrays (DUEL.EXE addresses). Returns [(player, slot)] in scan order. Everything it writes
    is in the data section, which the caller saves and puts back."""
    count = mm.r32(0x665ED0)

    def arbitrary():
        c = rng.random()
        return (0, 1, 2, 3, 0xFFFFFFFF, rng.randrange(0, 20), rng.randrange(0, 0x10000), rng.randrange(0, 0x400000))[int(c * 8)]
    placed = []
    for p in (0, 1):
        for sl in range(rng.randrange(1, 7) if total is None else (total + 1 - p) // 2):
            card = rng.randrange(1, max(2, count))
            for _ in range(20):
                h = mm.r32(0x4FF590 + card * 0x34 + 0x10)
                if 0x401000 <= h < 0x4F0000:
                    break
                card = rng.randrange(1, max(2, count))
            b = 0x6826C0 + p * 0x5B20 + sl * 0x120
            for off in range(0x10, 0x120, 4):
                if rng.random() < 0.3:
                    mm.w32(b + off, arbitrary())
            mm.w32(b + 4, card)
            mm.w32(b + 0xC, 2 | (rng.getrandbits(8) & 0xF4))
            mm.w32(b + 0x34, len(placed))
            placed.append((p, sl))
    rng.shuffle(placed)
    for i, (p, sl) in enumerate(placed):
        mm.w32(0x690320 + 4 * i, p)
        mm.w32(0x681EE0 + 4 * i, sl)
        mm.w32(0x6826C0 + p * 0x5B20 + sl * 0x120 + 0x34, i)
    mm.w32(0x690320 + 4 * len(placed), 0xFFFFFFFF)
    mm.w32(0x666458, rng.randrange(0, 2))              # whose turn it is
    return placed


def main(argv=None):
    if os.environ.get("EMU_SIGUSR1_STACKS"):   # kill -USR1 PID prints every Python thread's stack (where a long run is)
        import faulthandler  # noqa: PLC0415
        import signal  # noqa: PLC0415
        faulthandler.register(signal.SIGUSR1, all_threads=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=os.path.join(ROOT, "sources", "installed", "Magic", "Program", "MAGIC.EXE"))
    ap.add_argument("--seconds", type=float, default=30)
    ap.add_argument("--trace", action="store_true")
    ap.add_argument("--trace-only", default=None)
    ap.add_argument("--log-files", action="store_true")
    ap.add_argument("--shots", default=os.path.join(ROOT, "sources", "emu_shots"))
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--all-counts", action="store_true", help="list more of the most-called imports")
    ap.add_argument("--script", default="", help='timed actions, e.g. "20:click 230 308;25:shot a;30:key 13"')
    ap.add_argument("--dump-windows", action="store_true")
    ap.add_argument("--dump-surfaces", action="store_true", help="save every window's own surface as PNG")
    ap.add_argument("--dump-palette", action="store_true")
    ap.add_argument("--dump-bitmaps", action="store_true", help="save the game's large off-screen bitmaps as PNG")
    ap.add_argument("--break", dest="breaks", action="append", default=[],
                    help="trace a guest function: ADDR:label:nargs[:stringargs], e.g. 0x48e8f2:RunTurnStep:4:2")
    ap.add_argument("--watch", action="append", default=[], help="log writes to a guest dword: ADDR:label")
    ap.add_argument("--native", action="store_true",
                    help="host the native layer (make -C tools/difftest host): run its functions and the lifted card handlers in place of the original's")
    ap.add_argument("--native-count", action="store_true", help="count calls of the functions --native would replace, leaving them")
    ap.add_argument("--native-calibrate", metavar="FILE",
                    help="on the original, measure the instructions each native function executes per call; write FILE")
    ap.add_argument("--native-costs", metavar="FILE", help="with --native: charge the guest's clock for the instructions the replaced functions would have run (FILE from --native-calibrate)")
    ap.add_argument("--profile", metavar="FILE", help="count the guest's instructions per function of the original (the functions fnscan.py finds), write them to FILE")
    ap.add_argument("--profile-gate", default="", help="with --profile: also count apart while this dword (hex address) is non-zero (DUEL: 0x66aaf4, g_IsAiThinking)")
    ap.add_argument("--profile-callers", default="", help="with --profile: report who calls these functions (comma-separated hex addresses) and with what")
    ap.add_argument("--native-log", default="", metavar="ADDRS:FILE", help="write the arguments and result of every call of these functions (hex addresses, comma-separated) to FILE, in the original or hosted, to compare the two")
    ap.add_argument("--native-exact", action="store_true", help="with --native: instead of owing the clock the instructions the replaced functions would have run, run them (a counting loop): the slice ends where the original's would, so the run repeats the original's exactly (lifted code counts exactly; a hand-written native costs its calibrated average)")
    ap.add_argument("--native-shadow", action="store_true", help="with --native-exact: run every native function that has a lifted twin both ways on every call, compare, and keep the twin's result (reports differences on stderr)")
    ap.add_argument("--native-shadow-check", action="store_true", help="like --native-shadow, but lifted code may call any native function (the ones whose instruction count is only an average too): every native call is compared with its machine code, and the run is not exactly the original's")
    ap.add_argument("--native-only", default="", help="with --native: only these functions (comma-separated names)")
    ap.add_argument("--native-skip", default="", help="with --native: not these")
    ap.add_argument("--no-native-handlers", action="store_true", help="with --native: the native functions only, not the lifted handlers")
    ap.add_argument("--shot-every", type=float, default=0, help="also save screen_NNN.png every N seconds")
    ap.add_argument("--live", action="store_true", help="show the game in a window and take mouse and keyboard from it (needs pygame-ce); runs until the window is closed, in real time")
    ap.add_argument("--accel", action="store_true", help="run a few hot pure guest functions as Python (winemu/accel.py): much faster startup, but not the instruction counts the exact comparisons need (implied by --live)")
    ap.add_argument("--host-sound", action="store_true", help="run the game's sound library (MAGSND.DLL) on the host, silently: its DirectSound/mmio needs are not emulated, and the game then waits for a sound that never reports as finished (implied by --live)")
    ap.add_argument("--speed", type=float, default=1.0, help="with --live: game clock speed relative to real time")
    args = ap.parse_args(argv)

    game_root = os.path.join(ROOT, "sources", "installed", "Magic")
    overlay = os.environ.get("EMU_OVERLAY") or os.path.join(ROOT, "sources", "emu_overlay")      # EMU_OVERLAY=DIR: another place for the files the game writes (saves), for runs side by side
    os.makedirs(overlay, exist_ok=True)
    os.makedirs(args.shots, exist_ok=True)
    m = Machine(args.exe, game_root, overlay, log=(lambda *_: None) if args.quiet else print)
    sys.path.insert(0, os.path.join(ROOT, "tools", "lift"))
    from import_signatures import STDCALL  # noqa: PLC0415
    m.state["argc_table"] = dict(STDCALL)           # the stdcall imports' argument counts, for the callee's clean-up
    m.state["log_files"] = args.log_files
    m.state["gdi_debug"] = os.environ.get("GDI_DEBUG") == "1"
    for spec in args.breaks:
        parts = spec.split(":")
        flags = parts[4].split(",") if len(parts) > 4 else []
        mems = [int(x, 16) for f in flags if f.startswith("mem=") for x in f[4:].split("+")]    # dwords shown on entry
        m.add_trace(int(parts[0], 16), parts[1], int(parts[2]),
                    tuple(int(x) for x in parts[3].split(",") if x) if len(parts) > 3 else (),
                    ret="ret" in flags, describe=(lambda a, mm=m, ms=mems, cd=("card" in flags): (card_desc(mm, a) if cd else "")
                                   + (" mem[" + " ".join(f"{x:#x}={mm.r32(x):#x}" for x in ms) + "]" if ms else "")))
    for spec in args.watch:
        a, lab = spec.split(":", 1)
        m.add_watch(int(a, 16), lab)
    m.trace = args.trace or bool(args.trace_only)
    if args.trace_only:
        rx = re.compile(args.trace_only)
        m.trace_filter = lambda n: bool(rx.search(n))
    crt.init_argv(m, m.exe_guest_path)
    if args.host_sound or args.live:
        magsnd.install(m, audio=args.live and not os.environ.get("EMU_NO_AUDIO"))
        movie.install_magvid(m)
        print("   [sound] MAGSND.DLL runs on the host" + (" and plays the game's sounds" if args.live and not os.environ.get("EMU_NO_AUDIO") else " (silent)"))
    if args.accel or args.live:
        from . import accel  # noqa: PLC0415
        print(f"   [accel] {accel.install(m)} guest functions run as Python")
    t0 = time.time()
    tick = {"n": 0, "next": args.shot_every}
    actions = []
    for part in filter(None, (p.strip() for p in args.script.split(";"))):
        at, cmd = part.split(":", 1)
        actions.append((float(at), cmd.split()))
    actions.sort(key=lambda a: a[0])
    passto_last = {}
    pending = {"clicks": []}                                   # (due_time, kind, x, y) follow-ups of a click

    def run_action(mm, cmd, now):
        op = cmd[0]
        if op == "click":                                      # move, press, then release 0.3 s later
            x, y = int(cmd[1]), int(cmd[2])
            user32.inject_mouse(mm, "move", x, y)
            pending["clicks"].append((now + 0.2, "down", x, y))                   # let the hover register first
            hold = float(cmd[3]) if len(cmd) > 3 else 0.3            # click X Y [hold seconds]
            pending["clicks"].append((now + 0.2 + hold, "up", x, y))
        elif op == "dclick":                                   # double click: down, up, dblclk, up
            x, y = int(cmd[1]), int(cmd[2])
            user32.inject_mouse(mm, "move", x, y)
            for k, dt in (("down", 0), ("up", 0.05), ("dbl", 0.1), ("up", 0.15)):
                pending["clicks"].append((now + dt, k, x, y))
        elif op == "move":
            user32.inject_mouse(mm, "move", int(cmd[1]), int(cmd[2]))
        elif op == "key":
            user32.inject_key(mm, int(cmd[1]), int(cmd[2]) if len(cmd) > 2 else None)
        elif op == "digest":                                   # digest [LABEL]: hash the game's card and event state (compare two runs)
            import hashlib
            if mm.exe_guest_path.lower().endswith("\\magic.exe"):      # MAGIC.EXE's addresses (src/native/layout.c LAYOUT_MAGIC): slots, card counts, query counters, event source
                parts = [bytes(mm.uc.mem_read(0x6A5F30, 2 * 0x5B20)), bytes(mm.uc.mem_read(0x6808B8, 0x20)),
                         bytes(mm.uc.mem_read(0x677340, 0x20)), bytes(mm.uc.mem_read(0x6B2534, 0x20))]
            else:
                parts = [bytes(mm.uc.mem_read(0x6826C0, 2 * 0x5B20)), bytes(mm.uc.mem_read(0x666408, 0x20)),
                         bytes(mm.uc.mem_read(0x6663E0, 0x100)), bytes(mm.uc.mem_read(0x68ECB0, 0x40))]
            print(f"   [digest {now:.1f}s {cmd[1] if len(cmd) > 1 else ''}] " + " ".join(hashlib.md5(p).hexdigest()[:8] for p in parts))
        elif op == "slots":                                    # slots: list the occupied slots (debugging aid)
            for p in (0, 1):
                for sl in range(0x50):
                    b = 0x6826C0 + p * 0x5B20 + sl * 0x120
                    if mm.r32(b + 4) != 0xFFFFFFFF:
                        print(f"   [slots {now:.1f}s] p{p} s{sl} card={mm.r32(b + 4):#x} +8={mm.r32(b + 8):#x} +c={mm.r32(b + 0xC):#x}")
        elif op == "inject":                                   # inject HANDLER EVENT NTH [K [CARD [SEED [POKES]]]]: run a card handler on demand
            # Calls handler(player, slot, event) for the NTH card in play (both players, in slot order), on a new guest
            # thread, with the event globals set the way the game's own dispatcher sets them. DUEL.EXE addresses. The
            # game is put back afterwards: this is for recording what a handler does (tools/lift), not for play.
            #   K     what every function the handler calls returns (default 0; `r` picks one per function from the seed)
            #   CARD  `own` puts a card whose handler this is into that slot first; a number puts that card id there;
            #         `-` (default) leaves the card alone
            #   POKES `address:size:value,...` (hex; `sOFFSET:size:value` is a field of the slot itself) set those last (a handler is often gated on a global such as the step code)
            #   SEED  (nonzero) fills the slot's fields with arbitrary values and moves other cards into play, from a
            #         generator seeded with it, so the same op always makes the same situation
            handler, event, nth = int(cmd[1], 0), int(cmd[2], 0), int(cmd[3])
            live = [(p, sl) for p in (0, 1) for sl in range(0x50)
                    if mm.r32(0x6826C0 + p * 0x5B20 + sl * 0x120 + 4) != 0xFFFFFFFF
                    and mm.r32(0x6826C0 + p * 0x5B20 + sl * 0x120 + 0xC) & 2]
            if not live:
                print(f"   [script] inject: no card in play at {now:.1f}s")
            else:
                # The game stays as it was: the data section is saved before anything is changed and put back (the thread
                # ended) a little later, so that one handler's effects do not change what the next one sees. The functions
                # the handler calls (LIFT_SPEC lists them) are patched to return K at once, so the handler runs on its own:
                # a call that would open a prompt or wait on the UI cannot stall it, and what each callee returned is
                # exactly what the lifted code is later given.
                snap = bytes(mm.uc.mem_read(0x4F2000, 0x1D1000))
                k = cmd[4] if len(cmd) > 4 else "0"           # `r`: a different value for each function, from the seed
                token = cmd[5] if len(cmd) > 5 else "-"
                seed = int(cmd[6], 0) if len(cmd) > 6 else 0
                rng = random.Random(seed)
                pl, sl = live[nth % len(live)]
                base = 0x6826C0 + pl * 0x5B20 + sl * 0x120
                if token == "own":
                    ids = [i for i in range(1000) if mm.r32(0x4FF590 + i * 0x34 + 0x10) == handler]
                    if ids:
                        mm.w32(base + 4, ids[rng.randrange(len(ids))])
                elif token != "-":
                    mm.w32(base + 4, int(token, 0))
                if seed:
                    def arbitrary():                              # never a value that could be a pointer into memory: wild stores wedge the game
                        c = rng.random()
                        return (0, 1, 2, 3, 0xFFFFFFFF, rng.randrange(0, 20), rng.randrange(0, 0x10000), rng.randrange(0, 0x400000))[int(c * 8)]
                    for off in range(0x10, 0x120, 4):            # the slot's own fields
                        if off != 0xC and rng.random() < 0.4:
                            mm.w32(base + off, arbitrary())
                    mm.w32(base + 0xC, mm.r32(base + 0xC) | 2)   # it stays in play
                    for p2 in (0, 1):                            # other cards move around: into play, or out of it
                        for s2 in range(0x50):
                            b2 = 0x6826C0 + p2 * 0x5B20 + s2 * 0x120
                            if (p2, s2) != (pl, sl) and mm.r32(b2 + 4) != 0xFFFFFFFF and rng.random() < 0.5:
                                mm.w32(b2 + 0xC, mm.r32(b2 + 0xC) ^ 2)
                for poke in (cmd[7].split(",") if len(cmd) > 7 and cmd[7] != "-" else []):
                    addr, size, value = (int(x.lstrip("s"), 16) for x in poke.split(":"))   # a global the handler tests, set to a value it tests for
                    if poke.startswith("s"):                       # `sOFFSET:...`: a field of the slot the handler is called for
                        addr += base
                    mm.uc.mem_write(addr, (value & ((1 << (8 * size)) - 1)).to_bytes(size, "little"))
                card = mm.r32(base + 4)
                mm.w32(0x68ECB0, pl)                             # event source player and slot
                mm.w32(0x690C48, sl)
                mm.w32(0x681ECC, card)                           # the card, and its colour byte
                mm.w32(0x68EE64, mm.r32(0x4FF590 + (card & 0x3FF) * 0x34 + 4) >> 16 & 0xFF)
                mm.w32(0x690310, 1 - pl)                         # target player and slot
                mm.w32(0x68ECFC, 0xFFFFFFFF)
                mm.w32(0x66642C, 0)                              # the event result
                patched = patch_calls(mm, pending, handler, k, rng)
                th = mm.spawn(handler, [pl, sl, event], "inject", one_shot=True)
                th.slice = 200_000   # a handler stuck in a loop (a callee that always returns the same value) is cut off soon
                actions.append((now + float(os.environ.get("INJECT_RESTORE", "0.08")), ["_restore", snap, th, patched]))
                actions.sort(key=lambda a: a[0])
        elif op == "scan":                                     # scan EVENT SEED [K [CARDS]]: Magic_ScanCards on a board of arbitrary cards
            # The native card scan (src/native/card_scan.c) runs every card in play's handler for an event. This puts up to
            # a dozen cards with random handlers in play, their fields filled with arbitrary values, and calls the original
            # scan (DUEL.EXE 0x0048c5a8) for EVENT on a new guest thread, with every function a handler can call made to
            # return a value from the seed. What the scan recorded from this is what the native scan, with the handlers
            # running lifted inside it, must reproduce. The game is put back afterwards.
            event, seed = int(cmd[1], 0), int(cmd[2], 0)
            k = cmd[3] if len(cmd) > 3 else "r"
            rng = random.Random(seed)
            snap = bytes(mm.uc.mem_read(0x4F2000, 0x1D1000))
            placed = fuzz_board(mm, rng, int(cmd[4]) if len(cmd) > 4 else None)
            patched = patch_calls(mm, pending, None, k, rng, extra=(0x48AF80, 0x48C50B, 0x48B64F, 0x46E571, 0x46E793, 0x4D695B), skip=duel_native_entries())
            th = mm.spawn(0x48C5A8, [event], "inject", one_shot=True)
            th.slice = 200_000
            actions.append((now + max(0.15, float(os.environ.get("INJECT_RESTORE", "0.08"))), ["_restore", snap, th, patched]))
            actions.sort(key=lambda a: a[0])
        elif op == "callfn":                                   # callfn ADDR SEED [K] ARGS...: a function, on an arbitrary board
            # ARGS are numbers, or `p` / `s`: the player / slot of a random card of the board. The function is called on a
            # new guest thread, as `scan` does, with the handlers' callees made to return values from the seed.
            addr, seed = int(cmd[1], 0), int(cmd[2], 0)
            k = cmd[3]
            rng = random.Random(seed)
            snap = bytes(mm.uc.mem_read(0x4F2000, 0x1D1000))
            placed = fuzz_board(mm, rng)
            pick = placed[rng.randrange(len(placed))]
            call_args = [pick[0] if t == "p" else pick[1] if t == "s" else int(t, 0) for t in cmd[4:]]
            patched = patch_calls(mm, pending, None, k, rng, extra=(0x48AF80, 0x48C50B, 0x48B64F, 0x46E571, 0x46E793, 0x4D695B), skip=duel_native_entries())
            if os.environ.get("INJECT_FLUSH_TB"):
                mm.uc.ctl_flush_tb()
            th = mm.spawn(addr, call_args, "inject", one_shot=True)
            th.slice = 200_000
            actions.append((now + max(0.15, float(os.environ.get("INJECT_RESTORE", "0.08"))), ["_restore", snap, th, patched]))
            actions.sort(key=lambda a: a[0])
        elif op == "_restore":
            if cmd[2].state != "done":
                cmd[2].state = "done"
                for hook in mm.kill_hooks:
                    hook()
                print(f"   [script] inject: handler still running at {now:.2f}s ({cmd[2].state}), stopped")
            mm.uc.mem_write(0x4F2000, cmd[1])
            for a, orig in cmd[3]:
                mm.uc.mem_write(a, orig)
                mm.uc.ctl_remove_cache(a, a + len(orig))
        elif op == "dlg":                                      # dlg ID: press a button in the open dialog
            if user32.press_dialog_button(mm, int(cmd[1])):
                print(f"   [script] dlg {cmd[1]} pressed at {now:.1f}s")
            else:                                              # not there yet: try again shortly
                actions.append((now + 0.25, cmd))
                actions.sort(key=lambda a: a[0])
        elif op == "dlgsel":                                   # dlgsel ID INDEX
            user32.select_dialog_item(mm, int(cmd[1]), int(cmd[2]))
        elif op in ("hand", "cast", "tap", "pick", "board"):
            # card windows carry (player, slot) in their window longs 0 and 4; find them, name them, click them
            wins = mm.state.get("u32", {}).get("windows", {})
            cards = []
            for h, w in wins.items():
                if w["cls"] == "MAGICGAME_CardClass" and w["visible"] and w["w"] > 0:
                    pl, sl = w["extra"].get(0, -1), w["extra"].get(4, -1)
                    if pl in (0, 1) and 0 <= sl < 80:
                        cid = mm.r32(0x6826C4 + sl * 0x120 + pl * 0x5B20)
                        try:
                            ident = mm.r32(0x4FF590 + cid * 0x34)
                            nm = mm.cstr(mm.r32(0x618AC4 + ident * 0x98), 30).decode("latin-1")
                            mtype = mm.r32(0x4FF590 + cid * 0x34 + 4) & 0xFF
                        except Exception:
                            nm, mtype = "?", 0
                        par = wins.get(w["parent"], {})
                        cards.append(dict(h=h, player=pl, slot=sl, name=nm, mtype=mtype,
                                          flags=mm.r32(0x6826CC + sl * 0x120 + pl * 0x5B20), parent=par.get("title", "")))
            if op == "cast" and len(cmd) >= 2:
                want = " ".join(cmd[1:]).lower()
                hand = [c for c in cards if c["player"] == 0 and c["parent"].lower().startswith("your hand")]
                pick = [c for c in hand if (want == "land" and c["mtype"] & 1) or (want != "land" and want in c["name"].lower())]
                if not pick:
                    print(f"   [script] cast {want!r}: nothing in hand matches; hand = {[c['name'] for c in hand]}")
                else:
                    x0, y0, x1, y1 = user32.abs_rect(mm, wins[pick[0]["h"]])
                    print(f"   [script] cast {pick[0]['name']} (slot {pick[0]['slot']}) at {now:.0f}s")
                    run_action(mm, ["click", str(x0 + 40), str(y0 + 4), "0.05"], now)
            elif op == "pick" and len(cmd) >= 2:                # click any permanent of mine by name
                want = " ".join(cmd[1:]).lower()
                mine = [c for c in cards if c["player"] == 0 and c["parent"].lower().startswith("player territory")
                        and want in c["name"].lower()]
                if not mine:
                    print(f"   [script] pick {want!r}: nothing of mine matches")
                else:
                    x0, y0, x1, y1 = user32.abs_rect(mm, wins[mine[0]["h"]])
                    print(f"   [script] pick {mine[0]['name']} (slot {mine[0]['slot']}) at {now:.0f}s rect {(x0, y0, x1, y1)}")
                    run_action(mm, ["click", str((x0 + x1) // 2), str((y0 + y1) // 2), "0.05"], now)
            elif op == "tap" and len(cmd) >= 2:
                want = " ".join(cmd[1:]).lower()
                mine = [c for c in cards if c["player"] == 0 and c["parent"].lower().startswith("player territory")
                        and (want == "land" and c["mtype"] & 1 or want != "land" and want in c["name"].lower()) and not c["flags"] & 0x1]
                if not mine:
                    print(f"   [script] tap {want!r}: no untapped match on my side")
                else:
                    x0, y0, x1, y1 = user32.abs_rect(mm, wins[mine[0]["h"]])
                    print(f"   [script] tap {mine[0]['name']} (slot {mine[0]['slot']}) at {now:.0f}s rect {(x0, y0, x1, y1)}")
                    run_action(mm, ["click", str((x0 + x1) // 2), str((y0 + y1) // 2), "0.05"], now)
            else:
                for c in cards:
                    print(f"   [script {now:.0f}s] p{c['player']} slot {c['slot']:2d} {c['name']!r} type=0x{c['mtype']:x} flags=0x{c['flags']:x} in {c['parent']!r}")
        elif op == "dlgitems":                                 # dlgitems ID: list a combo/list box of the open dialog
            st = mm.state.get("u32", {})
            if st.get("dialogs"):
                h = user32.dlg_item(mm, st["dialogs"][-1], int(cmd[1]))
                w = user32.window(mm, h)
                print(f"   [script] items of {cmd[1]}: " + " | ".join(f"{i}:{it[0]}" for i, it in enumerate((w or {}).get("items", []))))
        elif op == "passto":                                   # passto PROMPT-PREFIX...: press Done until it shows
            want = " ".join(cmd[1:])
            tu = [w for w in mm.state.get("u32", {}).get("windows", {}).values() if w["cls"] == "MAGIC_TellUserClass"]
            cur = tu[0]["title"] if tu else ""
            if cur.startswith(want) and now - passto_last.get("t", -9) > 1.0:
                print(f"   [script] passto reached {cur!r} at {now:.0f}s")
            else:
                btn = [b for b in mm.state.get("u32", {}).get("windows", {}).values()
                       if str(b["cls"]).upper() == "BUTTON" and b["visible"] and b["w"] > 0 and b["parent"] == (tu[0]["hwnd"] if tu else -1)]
                if btn and now - passto_last.get("t", -9) > 2.5:
                    passto_last["t"] = now
                    x0, y0, _, _ = user32.abs_rect(mm, btn[0])
                    run_action(mm, ["click", str(x0 + 8), str(y0 + 5), "0.05"], now)
                actions.append((now + 0.5, cmd))                # look again shortly
                actions.sort(key=lambda a: a[0])
        elif op == "threads":                                  # where every thread is right now
            mm.report_threads()
        elif op == "state":                                    # print the duel's card slots (DUEL.EXE addresses)
            tu = [w["title"] for w in mm.state.get("u32", {}).get("windows", {}).values() if w["cls"] == "MAGIC_TellUserClass"]
            print(f"   [state {now:.0f}s] prompt: {tu[0] if tu else None!r}")
            for pl in (0, 1):
                rows = []
                for slot in range(80):
                    a = 0x6826C4 + slot * 0x120 + pl * 0x5B20
                    cid, flags = mm.r32(a), mm.r32(a + 8)
                    if cid not in (0xFFFFFFFF, 0):
                        name = ""
                        try:      # the slot holds a master-table index; its record's field 4 is the card id, which indexes the names
                            rec = 0x4FF590 + cid * 0x34
                            ident = mm.r32(rec)
                            name = mm.cstr(mm.r32(0x618AC4 + ident * 0x98), 30).decode("latin-1")
                            name = f"{name}#{ident},m=0x{mm.r32(rec + 4):x}"
                        except Exception as e:
                            name = f"?{e}"
                        rows.append(f"{slot}:{cid}({name})/0x{flags:x}")
                print(f"   [state {now:.0f}s] player {pl}: " + " ".join(rows))
        elif op == "shot":
            Image.fromarray(compose(mm)).save(os.path.join(args.shots, f"{cmd[1]}.png"))
            print(f"   [script] shot {cmd[1]} at {now:.1f}s virtual, {time.time() - t0:.1f}s real")

    def schedule(mm):
        kernel32.on_schedule(mm)
        now = mm.vt                                            # script times are virtual seconds
        while actions and now >= actions[0][0]:
            run_action(mm, actions.pop(0)[1], now)
        for c in [c for c in pending["clicks"] if c[0] <= now]:
            pending["clicks"].remove(c)
            user32.inject_mouse(mm, c[1], c[2], c[3])
        # tell the scheduler when the next thing will happen, so an idle machine can jump the virtual clock
        due = [a[0] for a in actions[:1]] + [c[0] for c in pending["clicks"]]
        due += [(tm["next"] - 60000) / 1000 for tm in mm.state.get("k32", {}).get("timers", {}).values()]
        due += [(tm["next"] - 60000) / 1000 for tm in mm.state.get("u32", {}).get("timers", {}).values()]
        if args.shot_every:
            due.append(tick["next"])
        mm.state["next_host_event"] = min(due) if due else None
        if args.shot_every and now >= tick["next"]:
            tick["next"] = now + args.shot_every
            tick["n"] += 1
            Image.fromarray(compose(mm)).save(os.path.join(args.shots, f"screen_{tick['n']:03d}.png"))
    m.state["on_schedule"] = schedule
    m.state["hard_stop"] = t0 + float(os.environ.get("EMU_HARD_STOP") or max(args.seconds * 6, 120))   # real-time safety net
    m.state["should_stop"] = lambda mm: mm.vt > args.seconds
    m.state["virtual_limit"] = args.seconds
    m.state["next_host_event"] = None
    nh = None
    if args.native_count:
        from . import native_host  # noqa: PLC0415
        nh = native_host.NativeHost(m)
        nh.count_only()
    if args.native_calibrate:
        from . import native_host  # noqa: PLC0415
        nh = native_host.NativeHost(m)
        print("   [native] calibrating %d native functions on the original" % nh.calibrate(args.native_calibrate))
    if args.native:
        from . import native_host  # noqa: PLC0415
        nh = native_host.NativeHost(m)
        if args.native_costs or args.native_exact:
            nh.load_costs(args.native_costs, exact=args.native_exact)
        n = nh.install(only=set(filter(None, args.native_only.split(","))) or None,
                       skip=set(filter(None, args.native_skip.split(","))), handlers=not args.no_native_handlers)
        print(f"   [native] {n} functions of the original replaced by the native layer")
        if args.native_shadow or args.native_shadow_check:
            nh.shadow_mode(check=args.native_shadow_check)
    if args.native_log:
        from . import native_host  # noqa: PLC0415
        addrs, path = args.native_log.split(":", 1)
        if nh is None:
            nh = native_host.NativeHost(m)
        nh.log_calls([int(a, 16) for a in addrs.split(",")], path, hosted=args.native)
    if os.environ.get("EMU_PEEK"):   # EMU_PEEK=addr[,addr]: print the dword at ESP each time the guest reaches `addr` (a local read before it is written)
        from unicorn import UC_HOOK_CODE  # noqa: PLC0415
        from unicorn.x86_const import UC_X86_REG_ESP  # noqa: PLC0415

        def peek(uc, address, size, user):
            esp = uc.reg_read(UC_X86_REG_ESP)
            from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI,  # noqa: PLC0415
                                           UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESI)
            regs = " ".join("%s=%08x" % (n, uc.reg_read(r)) for n, r in (("eip", UC_X86_REG_EIP), ("eax", UC_X86_REG_EAX), ("ebx", UC_X86_REG_EBX), ("ecx", UC_X86_REG_ECX), ("edx", UC_X86_REG_EDX), ("esi", UC_X86_REG_ESI), ("edi", UC_X86_REG_EDI), ("ebp", UC_X86_REG_EBP)))
            print("   [peek %.6f] t%s esp=%08x [esp]=%08x %s | %s" % (m.vt, m.cur.tid if m.cur else "?", esp, m.r32(esp), " ".join("%08x" % m.r32(esp + 4 * i) for i in range(1, 4)), regs))
        for a in os.environ["EMU_PEEK"].split(","):
            m.uc.hook_add(UC_HOOK_CODE, peek, begin=int(a, 16), end=int(a, 16))
    prof = None
    if args.profile:
        from .profile import Profile  # noqa: PLC0415
        prof = Profile(m, gate=int(args.profile_gate, 16) if args.profile_gate else None)
        for a in filter(None, args.profile_callers.split(",")):
            prof.callers(int(a, 16))
    if args.live:
        from .live import Live  # noqa: PLC0415
        live = Live(speed=args.speed)
        live.attach(m, compose)
        inner = m.state["on_schedule"]
        m.state["on_schedule"] = lambda mm: (inner(mm), live.on_schedule(mm))
        code = live.run(m)
    else:
        code = m.run()
    m.flush_trace()
    if prof:
        print(prof.report())
        print(prof.caller_report())
        prof.dump(args.profile)
    if nh and args.native_calibrate:
        out = nh.finish_calibration()
        print("   [native] instructions per call: " + ", ".join(f"{k} {v:.1f}" for k, v in sorted(out.items()) if v))
        print(f"   [native] written to {args.native_calibrate}")
    if nh and nh.shadow:
        compared, differ, unchecked = nh.shadow_report()
        print(f"   [shadow] {compared} calls of native functions compared with their machine code, {differ} differ; {unchecked} not compared (a call out to the guest: "
              + ", ".join(f"{k} x{v}" for k, v in sorted(nh.escalated.items(), key=lambda kv: -kv[1])[:6]) + ")")
    if nh and nh.runs and os.environ.get("NATIVE_RUNS_FILE"):
        import json as _json  # noqa: PLC0415
        _json.dump(nh.runs, open(os.environ["NATIVE_RUNS_FILE"], "w"), indent=0, sort_keys=True)
    if nh and nh.callers:
        print("   [callers] run again on a thread (a call out to the guest): " + ", ".join(
            f"{k} x{v}" for k, v in sorted(nh.escalated.items(), key=lambda kv: -kv[1])[:12]))
        for (fn, ret), n in sorted(nh.callers.items(), key=lambda kv: -kv[1])[:int(os.environ.get("HOST_CALLERS_TOP", "40"))]:
            print(f"   [callers] {n:9d} {fn} from {ret:#010x}" if fn != "callout" else f"   [callers] {n:9d} hosted code calls out to {ret:#010x}")
    if nh and nh.runs:
        top = sorted(nh.runs.items(), key=lambda kv: -kv[1])
        print(f"   [native] ran natively: {sum(nh.runs.values())} calls of {len(nh.runs)} functions; "
              + ", ".join(f"{k} x{v}" for k, v in top[:int(os.environ.get("NATIVE_TOP", "8"))]) + f"; memory faults {nh.faults}; charged {getattr(nh, 'charged_total', 0):.0f} instructions; run again on a thread: {sum(nh.escalated.values())}; host seconds {nh.seconds}")
    print(f"\nfinished: exit code {code}, {m.calls} import calls, {m.vt:.1f}s virtual, {time.time() - t0:.1f}s real")
    shot = os.path.join(args.shots, "screen.png")
    Image.fromarray(compose(m)).save(shot)
    print(f"screen: {shot}")
    print("most-called imports:")
    for (dll, name), n in sorted(m.counts.items(), key=lambda kv: -kv[1])[:(400 if args.all_counts else 12)]:
        print(f"  {n:8d}  {dll}!{name}")
    if args.dump_surfaces:
        for h, w in m.state.get("u32", {}).get("windows", {}).items():
            if w["surface"] is not None and w["surface"].w * w["surface"].h > 100 and w["proc"] and \
                    (w["surface"].idx.any() or w["surface"].direct.any()):
                Image.fromarray(gdi.surface_rgb(m, w["surface"])).save(
                    os.path.join(args.shots, f"win_{h:x}_{str(w['cls'])[-12:]}.png"))
    if args.dump_palette:
        pal = m.state.get("gdi", {}).get("system_palette", [])
        uniq = len(set(map(tuple, pal)))
        print(f"system palette: {len(pal)} entries, {uniq} distinct; first 8 {pal[:8]}; 100..104 {pal[100:104]}")
        for h, o in m.state.get("gdi", {}).get("objs", {}).items():
            if isinstance(o, tuple) and o[0] == "palette":
                print(f"  palette obj 0x{h:x}: {len(o[1])} entries, {len(set(map(tuple, o[1])))} distinct, shared_with_system={o[1] is pal}")
    if args.dump_bitmaps:
        st = m.state.get("gdi", {})
        n = 0
        for h, o in sorted(st.get("objs", {}).items()):
            if isinstance(o, gdi.Bitmap) and o.w * o.h >= 4000:
                if o.kind == "dib":
                    px = gdi.read_dib_rgb(m, o, 0, 0, o.w, o.h)
                else:
                    px = gdi.system_lut(m)[o.idx]
                if px.size and px.any():
                    Image.fromarray(px).save(os.path.join(args.shots, f"bmp_{h:x}_{o.kind}{o.bpp}_{o.w}x{o.h}.png"))
                    n += 1
        print(f"dumped {n} non-empty bitmaps to {args.shots}")
    if args.dump_windows:
        print("windows (hwnd class title visible x,y w x h parent style):")
        for h, w in m.state.get("u32", {}).get("windows", {}).items():
            print(f"  0x{h:x} {w['cls']!r} {w['title']!r} vis={int(w['visible'])} {w['x']},{w['y']} {w['w']}x{w['h']} "
                  f"parent=0x{w['parent']:x} style=0x{w['style']:08x} tid={w.get('tid')} "
                  f"invalid={int(w['invalid'])} painted={int((w['surface'].idx != 0).sum()) if w['surface'] is not None else 0}px")
    if m.unimplemented:
        top = sorted(m.unimplemented.items(), key=lambda kv: -kv[1])
        print("unimplemented imports called (stubbed to 0):")
        for (dll, name), n in top[:40]:
            print(f"  {n:6d}  {dll}!{name}")
    if m.state.get("messageboxes"):
        print("message boxes:", m.state["messageboxes"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

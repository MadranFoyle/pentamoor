#!/usr/bin/env python3
"""
Drive the live window without a screen: the game runs with SDL's dummy video driver and a script of real pygame events (clicks, keys)
is posted to it, so what the window would show can be saved as PNG and the run repeated.

    cd tools/emu_spike
    SEQ="w:10 c:330,390 w:40 s:menu" python3 live_drive.py                # Resume Game, wait, save the frame as live_menu.png
    OUT=/tmp/shot SEQ="..." SESSION=/tmp/cmds.txt python3 live_drive.py   # then append tokens to /tmp/cmds.txt while it runs; `quit` ends

Tokens (space separated, run in order):
    w:SECS         wait
    rc:X,Y         right click
    c:X,Y          click (mouse move, 0.3 s, button down 0.12 s, up)
    dc:X,Y         double click
    call:ADDR,ARG,..  run the guest function at ADDR (hex) on a new thread; ARG: a number, or s=text (a string in guest memory)
    btn:TEXT       click the visible button whose title contains TEXT (underscores are spaces)
    pass:TEXT[,SECS] press Done until the prompt bar shows TEXT
    auto:SECS      press the prompt bar's Done button whenever it shows, logging each prompt (a duel autopilot for soak tests)
    until:TEXT[,SECS] wait until a window or button with that title shows (prints how long it took)
    play:SECS      a duel autopilot (coin toss, start dialog, play top card, discard, Done); stops when the duel window is gone
    find:A,B / poke:ADDR,VALUE  look for a dword pair / write a dword in the data section (debugging aids)
    m:X,Y          move the mouse (hover)
    k:NAME         press a key (pygame name; enter, esc, space, tab, a..z, 1..0; shift+b for a capital)
    s:NAME         save the frame the window shows as $OUT_NAME.png
    sent:          pending cross-thread SendMessage calls
    top:SECS       the imports called during SECS
    n:             print the counters of a few imports        win:   list the windows         rec:  the last imports called
    dump:          save the window's indices / colours / the system palette as .npy
    pal:           system palette and index statistics         thr:   thread states            r:A,B  read guest dwords (hex)
    p:SECS         histogram of where the guest is (needs LIVE_SAMPLE=1)
Other arguments are passed to winemu.run (for example --dump-windows, --break ...). Environment: EMU_SRAND=N fixes the game's random
seed, LIVE_TICK_MS / LIVE_STATS / GDI_DEBUG as in winemu/live.py.

Everything here reads Python-side state only: reading the guest's registers from another thread while it runs corrupts it.
"""
import os
import sys
import threading
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pygame  # noqa: E402
from PIL import Image  # noqa: E402

from winemu import live, run  # noqa: E402

OUT = os.environ.get("OUT", "live")
KEYS = {"enter": "return", "esc": "escape"}


def post(*a, **k):
    pygame.event.post(pygame.event.Event(*a, **k))


def press(arg):
    *mods, key = arg.split("+")
    key = KEYS.get(key, key)
    code = pygame.key.key_code
    for mod in mods:
        post(pygame.KEYDOWN, key=code("left " + mod), unicode="", mod=0, scancode=0)
        time.sleep(0.05)
    ch = {"return": "\r", "space": " "}.get(key, key if len(key) == 1 else "")
    if "shift" in mods and len(key) == 1:
        ch = key.upper()
    post(pygame.KEYDOWN, key=code(key), unicode=ch, mod=0, scancode=0)
    time.sleep(0.08)
    post(pygame.KEYUP, key=code(key), mod=0, scancode=0)
    time.sleep(0.05)
    for mod in reversed(mods):
        post(pygame.KEYUP, key=code("left " + mod), mod=0, scancode=0)
        time.sleep(0.05)


def tokens():
    for tok in os.environ.get("SEQ", "").split():
        yield tok
    sess = os.environ.get("SESSION")
    if sess:
        pos = 0
        open(sess, "a").close()
        while True:
            with open(sess) as fh:
                fh.seek(pos)
                data = fh.read()
                pos = fh.tell()
            for tok in data.split():
                if tok == "quit":
                    return
                yield tok
            time.sleep(0.3)


def helper(lv):
    t0 = time.time()
    for tok in tokens():
        op, _, arg = tok.partition(":")
        m = lv.machine
        if op == "w":
            time.sleep(float(arg))
        elif op == "s":
            with lv.lock:
                f = lv.frame
            Image.fromarray(f).save(f"{OUT}_{arg}.png")
            print(f"[{time.time() - t0:6.1f}s real, vt {m.vt:6.1f}] saved {arg}", flush=True)
        elif op == "c":
            x, y = map(int, arg.split(","))
            post(pygame.MOUSEMOTION, pos=(x, y), rel=(0, 0), buttons=(0, 0, 0))
            time.sleep(0.3)
            post(pygame.MOUSEBUTTONDOWN, pos=(x, y), button=1)
            time.sleep(0.12)
            post(pygame.MOUSEBUTTONUP, pos=(x, y), button=1)
        elif op == "call":                                 # call:ADDR,ARG,... run a guest function (cdecl/stdcall alike) on a new thread; ARG is a number (0x.. ok) or s=text for a string
            parts = arg.split(",")
            lv.events.put(("call", int(parts[0], 16), [a[2:] if a.startswith("s=") else int(a, 0) for a in parts[1:]]))
        elif op == "dc":                                   # dc:X,Y  double click
            x, y = map(int, arg.split(","))
            post(pygame.MOUSEMOTION, pos=(x, y), rel=(0, 0), buttons=(0, 0, 0))
            time.sleep(0.3)
            for _ in range(2):
                post(pygame.MOUSEBUTTONDOWN, pos=(x, y), button=1)
                time.sleep(0.08)
                post(pygame.MOUSEBUTTONUP, pos=(x, y), button=1)
                time.sleep(0.08)
        elif op == "rc":                                   # rc:X,Y  right click
            x, y = map(int, arg.split(","))
            post(pygame.MOUSEMOTION, pos=(x, y), rel=(0, 0), buttons=(0, 0, 0))
            time.sleep(0.3)
            post(pygame.MOUSEBUTTONDOWN, pos=(x, y), button=3)
            time.sleep(0.12)
            post(pygame.MOUSEBUTTONUP, pos=(x, y), button=3)
        elif op == "btn":                                  # btn:TEXT  click the visible button (or prompt window) whose title contains TEXT
            from winemu import user32
            want = arg.replace("_", " ").lower()
            hit = None
            for w in list(m.state.get("u32", {}).get("windows", {}).values()):
                if w["visible"] and w["w"] > 0 and want in str(w["title"]).lower() and (str(w["cls"]).upper() == "BUTTON" or w["cls"] == "STATIC"):
                    hit = w
            if hit is None:
                print("btn: nothing matches", arg, flush=True)
            else:
                x0, y0, x1, y1 = user32.abs_rect(m, hit)
                x, y = (x0 + x1) // 2, (y0 + y1) // 2
                post(pygame.MOUSEMOTION, pos=(x, y), rel=(0, 0), buttons=(0, 0, 0))
                time.sleep(0.3)
                post(pygame.MOUSEBUTTONDOWN, pos=(x, y), button=1)
                time.sleep(0.12)
                post(pygame.MOUSEBUTTONUP, pos=(x, y), button=1)
        elif op == "auto":                                 # auto:SECS  press the prompt bar's Done button whenever it shows, logging each prompt and how long it took
            from winemu import user32
            end = time.time() + float(arg or 120)
            last, since = None, time.time()
            while time.time() < end:
                wins = list(m.state.get("u32", {}).get("windows", {}).values())
                tu = next((w for w in wins if w["cls"] == "MAGIC_TellUserClass" and w["visible"]), None)
                title = tu["title"] if tu else None
                if title != last:
                    print(f"AUTO {time.time() - t0:7.1f}s  +{time.time() - since:5.1f}s  prompt: {last!r} -> {title!r}", flush=True)
                    last, since = title, time.time()
                if tu is not None and time.time() - since > 2.0:
                    btn = next((b for b in wins if str(b["cls"]).upper() == "BUTTON" and b["visible"] and b["w"] > 0 and b["parent"] == tu["hwnd"]), None)
                    if btn is not None:
                        x0, y0, x1, y1 = user32.abs_rect(m, btn)
                        x, y = (x0 + x1) // 2, (y0 + y1) // 2
                        post(pygame.MOUSEMOTION, pos=(x, y), rel=(0, 0), buttons=(0, 0, 0))
                        time.sleep(0.3)
                        post(pygame.MOUSEBUTTONDOWN, pos=(x, y), button=1)
                        time.sleep(0.12)
                        post(pygame.MOUSEBUTTONUP, pos=(x, y), button=1)
                        since = time.time()
                time.sleep(0.25)
        elif op == "pass":                                 # pass:TEXT[,SECS]  press Done until the prompt bar shows TEXT (underscores are spaces)
            from winemu import user32
            want, _, secs = arg.partition(",")
            want = want.replace("_", " ").lower()
            end = time.time() + float(secs or 120)
            last_click = 0.0
            while time.time() < end:
                wins = list(m.state.get("u32", {}).get("windows", {}).values())
                tu = next((w for w in wins if w["cls"] == "MAGIC_TellUserClass" and w["visible"]), None)
                title = (tu["title"] if tu else "") or ""
                if want in title.lower():
                    print(f"PASS reached {title!r} at {time.time() - t0:.1f}s", flush=True)
                    break
                if tu is not None and time.time() - last_click > 2.5:
                    btn = next((b for b in wins if str(b["cls"]).upper() == "BUTTON" and b["visible"] and b["w"] > 0 and b["parent"] == tu["hwnd"]), None)
                    if btn is not None:
                        x0, y0, x1, y1 = user32.abs_rect(m, btn)
                        x, y = (x0 + x1) // 2, (y0 + y1) // 2
                        post(pygame.MOUSEMOTION, pos=(x, y), rel=(0, 0), buttons=(0, 0, 0))
                        time.sleep(0.3)
                        post(pygame.MOUSEBUTTONDOWN, pos=(x, y), button=1)
                        time.sleep(0.12)
                        post(pygame.MOUSEBUTTONUP, pos=(x, y), button=1)
                        last_click = time.time()
                time.sleep(0.25)
            else:
                print(f"PASS gave up waiting for {want!r}", flush=True)
        elif op == "until":                                # until:TEXT[,SECS]  wait until a visible window or button whose title contains TEXT exists (underscores are spaces)
            want, _, secs = arg.partition(",")
            want = want.replace("_", " ").lower()
            t1 = time.time()
            end = t1 + float(secs or 180)
            while time.time() < end:
                if any(w["visible"] and want in str(w["title"]).lower() for w in list(m.state.get("u32", {}).get("windows", {}).values())):
                    break
                time.sleep(0.2)
            print(f"UNTIL {want!r}: {'found' if time.time() < end else 'timed out'} after {time.time() - t1:.1f} s", flush=True)
        elif op == "cpu":                                  # cpu:  print the process's CPU seconds and the wall clock so far (call twice to see an interval)
            print(f"CPU {time.process_time():.1f} s cpu at {time.time() - t0:.1f} s wall", flush=True)
        elif op in ("play", "duel"):                       # duel:SECS is play: with the real autopilot (autoplay.py); play:SECS  a duel autopilot: answers the coin toss and start dialogs, plays the top card of the hand in each main phase, discards, presses Done; stops when the duel's window is gone
            from winemu import user32
            end = time.time() + float(arg or 600)
            seen_duel, last_click, last_title, turn_played, dlg_seen = False, 0.0, None, False, time.time()
            log = lambda msg: print(f"PLAY {time.time() - t0:7.1f}s {msg}", flush=True)       # noqa: E731
            smart, turn_no = op == "duel", 0
            bucket, prev_snap, prev_title, last_t = {}, __import__("collections").Counter(), "x", time.time()

            def click_at(x, y):
                post(pygame.MOUSEMOTION, pos=(x, y), rel=(0, 0), buttons=(0, 0, 0))
                time.sleep(0.3)
                post(pygame.MOUSEBUTTONDOWN, pos=(x, y), button=1)
                time.sleep(0.12)
                post(pygame.MOUSEBUTTONUP, pos=(x, y), button=1)

            def click_win(w):
                x0, y0, x1, y1 = user32.abs_rect(m, w)
                click_at((x0 + x1) // 2, (y0 + y1) // 2)
            if smart:
                import autoplay
                def shot(name):
                    with lv.lock:
                        f = lv.frame
                    Image.fromarray(f).save(f"{OUT}_{name}_{int(time.time() - t0)}.png")
                ap = autoplay.Autoplay(m, click_at, log, shot=shot)
            while time.time() < end:
                wins = list(m.state.get("u32", {}).get("windows", {}).values())
                duel = any(w["cls"] == "MAGICGAME_MainClass" and w["visible"] for w in wins)
                seen_duel = seen_duel or duel
                if seen_duel and not duel:
                    log("the duel window is gone")
                    if smart:
                        shot("end")
                        me, them = ap.last_life
                        log(f"RESULT {'WON' if them <= 0 < me else 'LOST' if me <= 0 < them else 'unknown'} (last seen life: me {me}, them {them})")
                    break
                if duel:
                    ended_at = None
                    if smart and seen_duel and time.time() - last_click > 0.4:
                        ap.watch_life()
                if smart and lv.samples is not None:                   # LIVE_SAMPLE=1: where the guest runs while the prompt bar is empty (the AI's turn) and while it is not
                    snap = __import__("collections").Counter({k[1]: v for k, v in dict(m.counts).items()})
                    cls = "idle" if prev_title else "ai"
                    bucket.setdefault(cls, __import__("collections").Counter()).update(snap - prev_snap)
                    bucket.setdefault(cls + "_secs", __import__("collections").Counter())["real"] += time.time() - last_t
                    last_t = time.time()
                    prev_snap = snap
                    for _t, name, ret in list(m.recent)[-40:]:              # who calls the imports the AI's turn is made of
                        bucket.setdefault(cls + "_callers", __import__("collections").Counter())[(name, hex(ret))] += 1
                vis = [w for w in wins if w["visible"] and w["w"] > 0]
                btn = lambda text: next((w for w in vis if str(w["cls"]).upper() == "BUTTON" and text in str(w["title"]).lower()), None)   # noqa: E731
                tu = next((w for w in vis if w["cls"] == "MAGIC_TellUserClass"), None)
                title = (tu["title"] if tu else "") or ""
                prev_title = title
                if title != last_title:
                    log(f"prompt {title!r}")
                    last_title = title
                    if title.startswith("Main phase (before"):
                        turn_played = False
                        turn_no += 1
                    if smart and title:
                        ap.new_prompt(title)
                if time.time() - last_click < 2.5:
                    time.sleep(0.25)
                    continue
                dlg = next((w for w in vis if w["cls"] == "#32770"), None)
                if dlg is None:
                    dlg_seen = time.time()
                dlg_btn = next((w for w in vis if dlg is not None and str(w["cls"]).upper() == "BUTTON" and w["parent"] == dlg["hwnd"]), None)
                pick = btn("play first") or btn("start the duel") or dlg_btn
                if pick is not None:
                    click_win(pick); last_click = time.time(); log(f"clicked {pick['title']!r}")
                elif dlg is not None and dlg_btn is None and seen_duel and time.time() - dlg_seen > 5:
                    click_win(dlg); last_click = time.time(); log("clicked inside a dialog with no buttons")
                elif tu is not None and title.startswith("Select card to discard"):
                    click_at(565, 395); last_click = time.time(); log("discard")
                elif smart and tu is not None and ap.step(title, turn_no):
                    last_click = time.time()
                elif tu is not None and title.startswith("Main phase (before") and not turn_played and not smart:
                    click_at(565, 405); turn_played = True; last_click = time.time(); log("played the top card")
                elif tu is not None:
                    b = next((x for x in vis if str(x["cls"]).upper() == "BUTTON" and x["parent"] == tu["hwnd"]), None)
                    if b is not None:
                        click_win(b); last_click = time.time()
                time.sleep(0.25)
            else:
                log("time is up")
            for cls, cnt in bucket.items():
                print("SAMPLES", cls, sum(cnt.values()), cnt.most_common(14), flush=True)
        elif op == "texts":                                # texts:  the text each visible window of the duel last wrote (class, title, then x,y: text)
            for h, w in list(m.state.get("u32", {}).get("windows", {}).items()):
                if w.get("texts") and w["visible"]:
                    print(f"TEXTS 0x{h:x} {w['cls']!r} {w['title']!r} at {w['x']},{w['y']}: " + " | ".join(f"{x},{y}:{t[0]!r}" for (x, y), t in sorted(w["texts"].items(), key=lambda kv: (kv[0][1], kv[0][0]))[:40]), flush=True)
        elif op == "hand":                                 # hand:  the duel's card windows with rectangle, text and the slot's flag words
            from winemu import duelview, user32 as u32m
            for c in duelview.cards(m):
                w = m.state["u32"]["windows"][c["h"]]
                x0, y0, x1, y1 = u32m.abs_rect(m, w)
                base = duelview.slot_addr(c["player"], c["slot"])
                print(f"HAND p{c['player']} s{c['slot']:2d} {w['title']!r} in {c['parent']!r} rect {x0},{y0},{x1},{y1} texts {[t[0] for _, t in sorted(w.get('texts', {}).items(), key=lambda kv: (kv[0][1], kv[0][0]))][:3]} "
                      f"cid={c['cid']:#x} flags={c['flags']:#x} tap={m.r32(base + 0xEC):#x} sick={m.r32(base + 0xF0):#x} pt={m.r32(base + 0xC):#x}", flush=True)
        elif op == "cards":                                # cards:  every card window in the duel, with the raw record dwords (for finding fields)
            from winemu import duelview
            for c in duelview.cards(m):
                print("   master", bytes(m.rd(duelview.TYPE_TABLE + c["cid"] * duelview.TYPE_SIZE, 0x34)).hex(" "), flush=True)
                rec, typ, slot = duelview.dump(m, c)
                print(f"CARD p{c['player']} s{c['slot']:2d} {c['name']!r} in {c['parent']!r} type=0x{c['mtype']:x} flags=0x{c['flags']:x} cid={c['cid']:#x} extra={bytes(m.state['u32']['windows'][c['h']]['extra'].b).hex()}", flush=True)
                if arg == "raw":
                    print("   rec ", " ".join(f"{v:x}" for v in rec), flush=True)
                    print("   typ ", " ".join(f"{v:x}" for v in typ), flush=True)
                    print("   slot", " ".join(f"{v:x}" for v in slot[:64]), flush=True)
        elif op == "find":                                 # find:A,B  addresses of a dword A with a dword B within 0x80 bytes after it (data section); host-side read of the mapped memory
            a_, b_ = (int(x, 0) for x in arg.split(","))
            hits = []
            for base, size, host, buf in m.regions:
                if not 0x516000 <= base + 0 < 0x800000 and not (base <= 0x516000 < base + size):
                    continue
                lo, hi = max(base, 0x516000), min(base + size, 0x715000)
                data = bytes(buf[lo - base:hi - base])
                for off in range(0, len(data) - 4, 4):
                    if int.from_bytes(data[off:off + 4], "little") == a_:
                        for k in range(1, 0x20):
                            if off + 4 * k + 4 <= len(data) and int.from_bytes(data[off + 4 * k:off + 4 * k + 4], "little") == b_:
                                hits.append((hex(lo + off), hex(lo + off + 4 * k)))
            print("FIND", hits[:30], flush=True)
        elif op == "poke":                                 # poke:ADDR,VALUE  write a dword into guest memory (a debugging aid: races with the emulator thread)
            a_, v_ = (int(x, 0) for x in arg.split(","))
            m.w32(a_, v_)
            print("POKE", hex(a_), hex(v_), flush=True)
        elif op == "m":                                    # m:X,Y  move the mouse (hover)
            x, y = map(int, arg.split(","))
            post(pygame.MOUSEMOTION, pos=(x, y), rel=(0, 0), buttons=(0, 0, 0))
        elif op == "k":
            press(arg)
        elif op == "n":
            c = {k[1]: v for k, v in m.counts.items()}
            print("COUNTS", {k: c.get(k) for k in ("SetPixelV", "BitBlt", "TextOutA", "GetMessageA", "SetDIBitsToDevice")},
                  "calls", m.calls, "vt", round(m.vt, 1), flush=True)
        elif op == "win":
            for h, w in list(m.state.get("u32", {}).get("windows", {}).items()):
                print(f"WIN 0x{h:x} {w['cls']!r} {w['title']!r} vis={int(w['visible'])} en={int(w.get('enabled', 1))} {w['x']},{w['y']} "
                      f"{w['w']}x{w['h']} parent=0x{w['parent']:x} tid={w.get('tid')}", flush=True)
        elif op == "top":                                      # top:SECS  the imports called during SECS, most first
            before = dict(m.counts)
            n0, v0 = m.calls, m.vt
            time.sleep(float(arg or 5))
            diff = sorted(((v - before.get(k, 0), k) for k, v in dict(m.counts).items() if v > before.get(k, 0)), reverse=True)[:8]
            print("TOP", m.calls - n0, "calls,", round(m.vt - v0, 2), "virtual s:", [(k[1], n) for n, k in diff], flush=True)
        elif op == "imp":                                  # imp:  all import counts so far, top 15 (call again and subtract to see an interval)
            top = sorted(m.counts.items(), key=lambda kv: -kv[1])[:15]
            print("IMP", {k[1]: v for k, v in top}, flush=True)
        elif op == "sent":
            st = m.state.get("u32", {})
            for r in list(st.get("sent", [])):
                w = st["windows"].get(r["hwnd"], {})
                owner = next((t for t in m.threads if t.tid == r["tid"]), None)
                print(f"SENT to t{r['tid']} ({owner.name + ' ' + owner.state if owner else 'gone'}): window 0x{r['hwnd']:x} {w.get('cls')!r} {w.get('title')!r} "
                      f"msg=0x{r['msg']:x} wp=0x{r['wp']:x} lp=0x{r['lp']:x} done={r['done']} running={r.get('running')}", flush=True)
        elif op == "rec":
            print("REC", [(t, n, hex(r)) for t, n, r in list(m.recent)[-30:]], flush=True)
        elif op == "thr":
            for t in list(m.threads):
                what = ""
                if t.state == "blocked":
                    w = t.wait
                    call = m.stubs.get(t.retry[0]) if t.retry else None
                    g = t.gen[0] if t.gen else None
                    gname = g.gi_code.co_name if g is not None else ""
                    gline = (g.gi_frame.f_lineno if g.gi_frame else 0) if g is not None else 0
                    what = f"in {call[1] if call else (('handler ' + gname + ':' + str(gline) + ' conts=' + str(len(t.conts))) if g is not None else 'a handler')} until={getattr(w, 'until', None)} ready={'yes' if getattr(w, 'ready', None) else 'no'}"
                print("THR", t.tid, t.name, t.state, what, flush=True)
        elif op == "dump":                                 # dump:  save the main window's palette indices, colours and the system palette as $OUT_*.npy
            import numpy as np
            from winemu import gdi, user32
            sf = m.state["u32"]["windows"][user32.main_hwnd(m)]["surface"]
            np.save(f"{OUT}_idx.npy", sf.idx)
            np.save(f"{OUT}_rgb.npy", sf.rgb)
            np.save(f"{OUT}_direct.npy", sf.direct)
            np.save(f"{OUT}_pal.npy", np.array(gdi.system_lut(m)))
            print("DUMP saved", f"{OUT}_*.npy", flush=True)
        elif op == "tab":                                  # tab:ADDR  show 8 palette entries (4 bytes each: B G R flags) at a guest address, with a few from the middle
            a0 = int(arg, 16)
            ent = lambda i: tuple(m.rd(a0 + 4 * i, 4))          # noqa: E731
            print("TAB", hex(a0), [ent(i) for i in (0, 1, 2, 3, 100, 179, 180, 189, 231, 255)], flush=True)
        elif op == "pal":
            import numpy as np
            from winemu import gdi, user32
            sf = m.state["u32"]["windows"][user32.main_hwnd(m)]["surface"]
            lut = np.array(gdi.system_lut(m))
            print("PAL nonblack entries", int((lut.sum(1) > 0).sum()), "indices used", len(np.unique(sf.idx)),
                  "direct fraction", float(sf.direct.mean()), flush=True)
        elif op == "r":
            print("MEM", {a: hex(m.r32(int(a, 16))) for a in arg.split(",")}, flush=True)
        elif op == "p":
            lv.samples.clear()
            time.sleep(float(arg or 3))
            print("SAMPLE", sum(lv.samples.values()), [(hex(a), n) for a, n in lv.samples.most_common(14)], flush=True)
        else:
            print("unknown token", tok, flush=True)
    post(pygame.QUIT)


_run = live.Live.run


def patched(self, m):
    def go():
        try:
            helper(self)
        except BaseException:                                   # noqa: BLE001  (shown, then the window is closed)
            import traceback
            traceback.print_exc()
            post(pygame.QUIT)
    threading.Thread(target=go, daemon=True).start()
    return _run(self, m)


live.Live.run = patched
sys.exit(run.main(["--live"] + sys.argv[1:]))

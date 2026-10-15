#!/usr/bin/env python3
"""soak.py: play many duels of Pentamoor through PORT_CONTROL and log what goes wrong.

    python3 tools/soak/soak.py --res 800x600 --minutes 20 --workdir /tmp/soak-800
    tools/soak/run_all.sh 20                     # the three sizes at once, 20 minutes each

It starts MAGIC.EXE (SDL's dummy video and audio drivers, its own control pipe, its own copy of sources/emu_overlay), takes "Resume Game" and
"Duel a Sorcerer" (the saved game's encounter; the overlay must have one), and plays duels the way a player does, through the window tree:
plays lands and whatever it can cast (paying by clicking its permanents), cancels prompts at random in the ways a player can (the bar's
Cancel button, Esc, the right-click menu), attacks with everything, passes turns, then concedes (or wins), and starts the next duel.
A game process plays a few duels and is restarted, so the start-up is soaked too.

What it logs (<workdir>/events.jsonl, summary on stdout and in <workdir>/summary.txt):
  CRASH   the process died (exit status or signal; a macOS crash report is copied if there is one)
  HANG    the process did not answer `windows` for 20 s (a `sample` / gdb thread dump is saved)
  STUCK   the state (prompt bar, dialogs, hands) did not change for --stall-s seconds although the script kept acting (screenshot saved)
  STDERR  a line on stderr that is not a window dump (the program is silent when all is well)
  SETUP   the way to a duel did not work (screenshot saved)
  NOTE    things worth knowing (a prompt cancelled with Esc that did not go away, ...)
No game file is in this script; it needs the installed game (sources/installed) and the overlay (sources/emu_overlay), as the port does.
"""
import argparse
import collections
import glob
import json
import os
import random
import re
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pentamoor_ctl import Game  # noqa: E402

# Where things are on the screen at each size (the title screen and the ante screen are pictures, not windows). Measured on the game's own layouts.
RESUME = {640: (330, 390), 800: (412, 487), 1024: (528, 624)}
DUEL = {640: (290, 325), 800: (360, 388), 1024: (470, 486)}

DUMP_PREFIXES = ("  win ", "  queue", "  popup", "  item ", "  peek", "  poke", "  hit ", "  pad:", "  nav:", "  target ")
KNOWN_STDERR = (re.compile(r"^loaded .* at 0x"), re.compile(r"^LoadLibraryA\((deckdll|statwin)\.dll\) -> mapped"))


class Soak:
    def __init__(self, a):
        self.a = a
        self.rnd = random.Random(a.seed)
        self.w, self.h = (int(v) for v in a.res.split("x"))
        self.workdir = os.path.abspath(a.workdir)
        os.makedirs(self.workdir, exist_ok=True)
        self.events = open(os.path.join(self.workdir, "events.jsonl"), "a")
        self.counts = collections.Counter()
        self.stderr_seen = collections.Counter()
        self.stats = collections.Counter()
        self.t0 = time.time()
        self.game = None
        self.log_off = 0
        self.nshots = 0
        self.in_title = False

    # ---- logging ------------------------------------------------------------------------------------------------------
    def ev(self, kind, msg, **kw):
        self.counts[kind] += 1
        rec = dict(t=round(time.time() - self.t0, 1), kind=kind, res=self.a.res, msg=msg, **kw)
        self.events.write(json.dumps(rec) + "\n")
        self.events.flush()
        print("[%s %6.0fs] %-6s %s %s" % (self.a.res, rec["t"], kind, msg, kw or ""), flush=True)

    def shot(self, tag):
        self.nshots += 1
        p = os.path.join(self.workdir, "%s-%03d.png" % (tag, self.nshots))
        return self.game.shot(p) if self.game and self.game.alive() else None

    def scan_stderr(self):
        """New lines in the game's log that are neither a window dump nor on the known list."""
        g = self.game
        size = g.log_size()
        if size <= self.log_off:
            return
        text = g.read_log(self.log_off)
        self.log_off = size
        for line in text.split("\n"):
            if self.in_title:                        # the rest of a window title that has a newline in it
                if re.search(r"' \(-?\d+,-?\d+\)-\(-?\d+,-?\d+\) z=", line):
                    self.in_title = False
                continue
            if line.startswith("  win ") and not re.search(r"' \(-?\d+,-?\d+\)-\(-?\d+,-?\d+\) z=", line):
                self.in_title = True
                continue
            if not line or line.startswith(DUMP_PREFIXES) or any(k.match(line) for k in KNOWN_STDERR):
                continue
            key = re.sub(r"\d+", "#", line)[:200]
            self.stderr_seen[key] += 1
            if self.stderr_seen[key] == 1:
                self.ev("STDERR", line[:300])

    # ---- the process --------------------------------------------------------------------------------------------------
    def new_game(self):
        wd = os.path.join(self.workdir, "game%d" % (self.stats["games"]))
        self.stats["games"] += 1
        g = Game(self.a.repo, res=self.a.res, workdir=wd, exe=self.a.exe, program=self.a.program, module=self.a.module)
        g.start()
        self.game = g
        self.log_off = 0
        self.started_wall = time.time()
        return g

    def thread_dump(self, tag):
        g = self.game
        out = os.path.join(self.workdir, "%s-%d.txt" % (tag, self.nshots))
        self.nshots += 1
        try:
            if sys.platform == "darwin":
                subprocess.run(["sample", str(g.pid), "3", "-file", out], timeout=60, capture_output=True)
            elif shutil.which("gdb"):
                r = subprocess.run(["gdb", "-p", str(g.pid), "-batch", "-ex", "thread apply all bt"], timeout=60, capture_output=True)
                open(out, "wb").write(r.stdout + r.stderr)
            else:
                return None
            return out
        except Exception as e:  # noqa: BLE001
            return "thread dump failed: %s" % e

    def cpu_seconds(self):
        try:
            out = subprocess.run(["ps", "-o", "time=", "-p", str(self.game.pid)], capture_output=True, text=True).stdout.strip()
            return out
        except Exception:  # noqa: BLE001
            return "?"

    def check_alive(self, where):
        g = self.game
        if g.alive():
            return True
        st = g.exit_status()
        report = None
        if sys.platform == "darwin":
            for p in sorted(glob.glob(os.path.expanduser("~/Library/Logs/DiagnosticReports/pentamoor*")), key=os.path.getmtime, reverse=True)[:1]:
                if os.path.getmtime(p) >= self.started_wall - 5:
                    report = os.path.join(self.workdir, os.path.basename(p))
                    shutil.copy(p, report)
        tail = g.read_log(max(0, g.log_size() - 1500))
        tail = "\n".join(l for l in tail.split("\n") if not l.startswith(DUMP_PREFIXES))[-600:]
        self.ev("CRASH", "process gone (%s) at %s" % ("exit %s" % st if st is not None and st >= 0 else "signal %s" % -st if st is not None else "?", where),
                report=report, log_tail=tail)
        return False

    def look(self, where):
        """The window tree, or None with the failure logged (crash; hang)."""
        g = self.game
        if not self.check_alive(where):
            return None
        t = g.windows(timeout=8)
        self.scan_stderr()
        if t is not None:
            return t
        if not self.check_alive(where):
            return None
        for _ in range(2):                           # 3 tries over 20 s before it is called a hang
            t = g.windows(timeout=6)
            if t is not None:
                return t
        self.ev("HANG", "no answer to `windows` for 20 s at %s (cpu time %s)" % (where, self.cpu_seconds()), dump=self.thread_dump("hang"),
                shot=self.shot("hang"))
        return None

    # ---- reading the board --------------------------------------------------------------------------------------------
    @staticmethod
    def sig(t):
        b = t.bar()
        title = b[0].title if b and b[0].visible else None
        buttons = (bool(b and b[1]), bool(b and b[2]))
        dl = tuple((d.title, tuple((c.cls, c.title) for c in t.children(d) if c.visible)) for d in t.dialogs())
        hands = tuple(w.title for w in t.wins if w.cls == "MAGICGAME_HandClass")
        n_in = sum(1 for w in t.wins if w.title in ("In-play Card", "Hand Card") and w.visible and not w.empty)
        duel = bool(t.find("MAGICGAME_MainClass"))
        return (title, buttons, dl, hands, n_in, bool(t.items), duel)

    @staticmethod
    def hand_rows(t):
        hand = [w for w in t.wins if w.cls == "MAGICGAME_HandClass" and w.title.startswith("Your hand") and w.visible]
        if not hand:
            return []
        cards = [w for w in t.children(hand[0]) if w.title == "Hand Card" and w.visible and not w.empty]
        cards.sort(key=lambda c: c.y0)
        return [(c.x0 + 40, c.y0 + 4) for c in cards]

    @staticmethod
    def my_permanents(t):
        terr = [w for w in t.wins if w.cls == "MAGICGAME_TerritoryClass" and w.title == "Player Territory"]
        if not terr:
            return []
        return [c.center for c in t.children(terr[0]) if c.title == "In-play Card" and c.visible and not c.empty]

    @staticmethod
    def their_permanents(t):
        terr = [w for w in t.wins if w.cls == "MAGICGAME_TerritoryClass" and w.title == "Oppon Territory"]
        if not terr:
            return []
        return [c.center for c in t.children(terr[0]) if c.title == "In-play Card" and c.visible and not c.empty]

    # ---- dialogs ------------------------------------------------------------------------------------------------------
    def handle_dialog(self, t):
        """Click through a dialog; returns a short description. Prefers the buttons that move on."""
        g = self.game
        d = t.dialogs()[0]
        kids = [c for c in t.children(d) if c.visible]
        texts = " | ".join(c.title for c in kids if c.title)
        buttons = [c for c in kids if c.cls.startswith("BUTTON") and c.title and not c.empty]
        want = ("start the duel", "play first", "draw first", "ok", "yes", "continue", "next", "done", "accept")
        for w in want:
            for b in buttons:
                if w in b.title.lower():
                    if w in ("play first", "draw first") and self.rnd.random() < 0.5:
                        continue
                    g.click(*b.center)
                    return "dialog '%s': %s -> %s" % (d.title or d.cls, texts[:80], b.title)
        if buttons:
            b = buttons[0]
            g.click(*b.center)
            return "dialog '%s': %s -> %s" % (d.title or d.cls, texts[:80], b.title)
        g.key("return")
        return "dialog '%s': %s -> Return" % (d.title or d.cls, texts[:80])

    # ---- the menu -----------------------------------------------------------------------------------------------------
    def concede(self):
        """Right-click, Concede, Yes I'm sure: through the menu's own rows."""
        g = self.game
        g.rclick(self.w // 2, self.h // 5)
        for step in range(3):
            time.sleep(1.0)
            t = self.look("concede menu")
            if t is None:
                return False
            if not t.items:
                if step == 0:
                    g.rclick(self.w // 2, self.h // 5)
                    continue
                return False
            lvl = max(i.level for i in t.items)
            cand = [i for i in t.items if i.level == lvl and not i.separator and not i.disabled]
            pick = [i for i in cand if "concede" in i.text.lower() or "sure" in i.text.lower()]
            if not pick:
                return False
            g.click(*pick[0].center)
            if "sure" in pick[0].text.lower():
                return True
        return False

    # ---- one tick of the duel policy ----------------------------------------------------------------------------------
    def prompt_tick(self, t, ctx, title, cancel, done):
        """CASTING / ACTIVATING / Pick ... / Select ...: the bar asks for something."""
        g = self.game
        n = ctx["n"]
        if ctx["n"] == 0:
            ctx["mode"] = self.rnd.choice(["pay", "pay", "button", "esc", "rclick-esc"]) if cancel else "pick"
        mode = ctx["mode"]
        if n >= 3 and mode in ("button", "esc", "rclick-esc") and not ctx.get("noted"):
            ctx["noted"] = True                    # three ticks later the prompt is still there
            self.ev("NOTE", "prompt %r not cancelled by %s after %d tries" % (title, mode, n), shot=self.shot("nocancel"))
        mine = self.my_permanents(t)
        theirs = self.their_permanents(t)
        hand = self.hand_rows(t)
        if cancel and n >= 8:                      # nothing worked: give it up the plain way
            g.click(*cancel.center)
            return "prompt %r: give up (Cancel button)" % title
        if mode == "pay":
            if mine:
                g.click(*mine[n % len(mine)])
                return "prompt %r: pay with permanent #%d" % (title, n % len(mine))
            mode = "button"
        if mode == "button":
            if cancel:
                g.click(*cancel.center)
                return "prompt %r: Cancel button" % title
            mode = "pick"
        if mode == "esc":
            if n >= 3 and cancel:
                self.ev("NOTE", "Esc did not cancel the prompt %r (3 tries); using the button" % title)
                ctx["mode"] = "button"
            g.key("escape")
            return "prompt %r: Esc" % title
        if mode == "rclick-esc":
            if n % 2 == 0:
                g.rclick(self.w // 2, self.h // 5)
                return "prompt %r: right-click" % title
            g.key("escape")
            if n >= 4:
                ctx["mode"] = "button"
            return "prompt %r: Esc (menu)" % title
        # a forced choice (discard, pick a target): click things
        pool = []
        if "discard" in title.lower() or "card" in title.lower():
            pool += hand
        pool += mine + theirs
        pool += [w.center for w in t.wins if w.cls == "MAGICGAME_FaceClass" and w.visible and not w.empty]
        if pool:
            g.click(*self.rnd.choice(pool))
            return "prompt %r: click something" % title
        g.key("return")
        return "prompt %r: Return" % title

    def tick(self, t, ctx):
        """One action for the state in `t`. Returns (description, state_kind)."""
        g = self.game
        b = t.bar()
        title = b[0].title if b and b[0].visible else ""
        cancel, done = (b[1], b[2]) if b else (None, None)
        if t.items:                                 # a popup menu is open: close it
            g.key("escape")
            return "close popup", "popup"
        if t.dialogs():
            return self.handle_dialog(t), "dialog"
        if not t.find("MAGICGAME_MainClass") or not title:
            return None, "none"
        low = title.lower()
        if any(k in title for k in ("CASTING", "ACTIVATING", "PROCESSING")) or low.startswith(("pick", "select")) or "pick " in low:
            return self.prompt_tick(t, ctx, title, cancel, done), "prompt"
        if "attackers" in low and done:
            if ctx["n"] == 0 or ctx["n"] == 1:
                mine = self.my_permanents(t)
                if mine:
                    for p in mine:
                        g.click(*p)
                        time.sleep(0.25)
                    return "attack with %d permanents" % len(mine), "attack"
            g.click(*done.center)
            return "Done (attackers)", "attack"
        if "main phase (before combat)" in low and done:
            limit = ctx.setdefault("limit", self.rnd.randint(1, 5))
            hand = self.hand_rows(t)
            if ctx["n"] < limit and hand:
                g.click(*self.rnd.choice(hand))
                return "main: try a hand card", "main"
            g.click(*done.center)
            return "Done (main)", "main"
        if done:
            g.click(*done.center)
            return "Done (%s)" % title[:40], "done"
        if cancel:
            g.click(*cancel.center)
            return "Cancel (%s)" % title[:40], "cancel"
        g.key("return")
        return "Return (%s)" % title[:40], "return"

    # ---- one duel -----------------------------------------------------------------------------------------------------
    def play_duel(self, end_wall):
        """Plays until the duel is over. Returns 'over', 'restart' (the game process is gone or must be replaced)."""
        g = self.game
        a = self.a
        t_start = time.time()
        sig_prev, sig_t = None, time.time()
        ctx = {"n": 0}
        turns = 0
        seen_duel = False
        concede_after = self.rnd.randint(a.min_turns, a.max_turns)
        conceded = False
        last_kind = None
        while time.time() < end_wall:
            t = self.look("duel")
            if t is None:
                return "restart"
            s = self.sig(t)
            now = time.time()
            if s != sig_prev:
                sig_prev, sig_t = s, now
                ctx = {"n": 0}
            stalled = now - sig_t
            in_duel = s[6]
            if in_duel:
                seen_duel = True
            if seen_duel and not in_duel and not t.dialogs():
                return "over"                        # the board is gone
            if stalled > a.stall_s:
                self.ev("STUCK", "no change for %.0f s: bar=%r dialogs=%s last action %r" % (stalled, s[0], [d[0] for d in s[2]], last_kind),
                        cpu=self.cpu_seconds(), shot=self.shot("stuck"), dump=self.thread_dump("stuck"))
                self.stats["stuck"] += 1
                if not self.concede():
                    return "restart"
                sig_t = time.time()
                ctx = {"n": 0}
                if self.stats["stuck_run"] >= 2:
                    return "restart"
                self.stats["stuck_run"] += 1
            # the duel's life: concede after a few turns, or when it runs long
            if s[0] and "discard phase" in s[0].lower() and ctx["n"] == 0:
                turns += 1
                self.stats["turns"] += 1
            if in_duel and not conceded and (turns > concede_after or now - t_start > a.max_duel_s):
                conceded = True
                ok = self.concede()
                self.stats["concede_try"] += 1
                last_kind = "concede(%s)" % ok
                time.sleep(2.0)
                continue
            desc, kind = self.tick(t, ctx)
            if self.a.verbose and desc:
                print("[%s] %s" % (self.a.res, desc), flush=True)
            if kind not in ("none",):
                ctx["n"] += 1
                self.stats["act_" + kind] += 1
                last_kind = desc
                self.stats["stuck_run"] = 0 if kind != "popup" else self.stats["stuck_run"]
            if kind == "none":
                # no board, no dialog, no bar: the overworld's screens (ante, lost card...) -- handled by the caller after "over"
                if now - sig_t > 15:
                    return "over"
            time.sleep(self.a.tick_s)
        return "restart"

    # ---- getting to a duel --------------------------------------------------------------------------------------------
    def to_ante(self):
        g = self.game
        time.sleep(9)
        g.click(*RESUME[self.w])
        time.sleep(9)
        return True

    def start_duel_from_ante(self, first=True):
        """Click "Duel a Sorcerer" and click through the coin toss and mulligan dialogs to the first main phase. After a duel the saved game
        usually moves on (a second duel, then the overworld), so a later duel that does not come is not an error: the game is restarted."""
        g = self.game
        g.click(*DUEL[self.w])
        t_end = time.time() + (75 if first else 30)
        while time.time() < t_end:
            time.sleep(2.0)
            t = self.look("starting a duel")
            if t is None:
                return False
            if t.find("MAGICGAME_MainClass") and t.bar() and t.bar()[0].visible and t.bar()[0].title:
                return True
            if t.dialogs():
                self.handle_dialog(t)
        if first:
            self.ev("SETUP", "no duel board 75 s after Duel", shot=self.shot("setup"))
        else:
            self.ev("NOTE", "no further duel after the last one (the game moved on): restarting the game", shot=self.shot("moved-on"))
        return False

    def after_duel(self):
        """From the board's end to the ante screen again: results, lost-card screens. Keys and a click on the screen's middle, as a player would."""
        g = self.game
        for i in range(12):
            t = self.look("after duel")
            if t is None:
                return False
            if t.dialogs():
                self.handle_dialog(t)
            elif t.find("MAGICGAME_MainClass") and t.bar() and t.bar()[0].visible and t.bar()[0].title:
                return True                          # a new duel has started by itself?
            else:
                g.key("return")
                time.sleep(1.5)
                g.click(self.w // 2, self.h // 2)
            time.sleep(3.0)
        return True

    def session(self, end_wall):
        g = self.new_game()
        self.to_ante()
        for duel_no in range(self.a.duels_per_game):
            if time.time() >= end_wall:
                break
            if not self.start_duel_from_ante(first=duel_no == 0):
                break
            self.stats["duels"] += 1
            res = self.play_duel(end_wall)
            self.ev("NOTE", "duel %d (game %d) ended: %s after %d turns total" % (self.stats["duels"], self.stats["games"], res, self.stats["turns"]))
            if res == "restart":
                break
            if not self.after_duel():
                break
        self.scan_stderr()
        g.stop()

    def run(self):
        end_wall = time.time() + self.a.minutes * 60
        try:
            while time.time() < end_wall:
                self.session(end_wall)
        finally:
            if self.game:
                self.game.stop()
            self.summary()

    def summary(self):
        lines = ["soak %s for %.1f min: %d games, %d duels, %d turns" % (self.a.res, (time.time() - self.t0) / 60, self.stats["games"],
                                                                      self.stats["duels"], self.stats["turns"])]
        lines.append("events: " + ", ".join("%s %d" % kv for kv in sorted(self.counts.items())))
        lines.append("actions: " + ", ".join("%s %d" % (k[4:], v) for k, v in sorted(self.stats.items()) if k.startswith("act_")))
        for k, v in self.stderr_seen.most_common(20):
            lines.append("stderr x%d: %s" % (v, k))
        text = "\n".join(lines)
        print(text, flush=True)
        open(os.path.join(self.workdir, "summary.txt"), "w").write(text + "\n")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--res", default="640x480", choices=["640x480", "800x600", "1024x768"])
    ap.add_argument("--minutes", type=float, default=20)
    ap.add_argument("--repo", default=os.path.abspath(os.path.join(here, "..", "..")))
    ap.add_argument("--exe", default="src/port/build/pentamoor-run")
    ap.add_argument("--module", default=None, help="the game module the runtime loads (default: game_magic next to --exe); \"none\" for the old single executable")
    ap.add_argument("--program", default="sources/installed/Magic/Program/MAGIC.EXE")
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--duels-per-game", type=int, default=3)
    ap.add_argument("--min-turns", type=int, default=3)
    ap.add_argument("--max-turns", type=int, default=9)
    ap.add_argument("--max-duel-s", type=float, default=300)
    ap.add_argument("--stall-s", type=float, default=60)
    ap.add_argument("--tick-s", type=float, default=1.0)
    ap.add_argument("--verbose", action="store_true", help="print every action")
    a = ap.parse_args()
    if a.workdir is None:
        a.workdir = "/tmp/soak-%s" % a.res
    if a.seed is None:
        a.seed = int(time.time())
    print("soak: seed %d, workdir %s" % (a.seed, a.workdir), flush=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))     # so the game process is stopped (the `finally` in run) when this is killed
    Soak(a).run()


if __name__ == "__main__":
    main()

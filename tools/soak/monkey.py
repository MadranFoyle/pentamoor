#!/usr/bin/env python3
"""monkey.py: random clicks and keys on the overworld's places, headless: what soak.py (duels only) and the screen scripts (one pass over each screen) do not do.

    python3 tools/soak/monkey.py --res 640x480 --minutes 20 --workdir /tmp/monkey-640 [--seed N]
    python3 tools/soak/monkey.py --program sources/installed/Magic/Program/DECK.EXE --minutes 5     # the standalone deck builder (./pentamoor deck); DUEL.EXE too (its setup dialog)

The program is started as soak.py starts it (SDL's dummy drivers, its own control pipe and overlay). The saved game's first encounter is conceded to reach the world map; then, until the time
is up, the party is put on a random place of the map (a village, a tower, a castle, a free dungeon made "known"; `Game.teleport_party`: the way the game's own teleports do it), the monsters are
kept away, and for a few seconds the monkey presses what a person might: left and right clicks anywhere on the screen (a third of them on the right-hand column's buttons), the arrow keys, Return,
Escape, space, letters, digits, the function keys. Between the actions the window tree is asked for (`windows`: the program must answer) and the process must be alive. Logged as soak.py logs
(events.jsonl, summary.txt): CRASH (process gone, with the log's tail), HANG (no answer to `windows` for 20 s; a thread dump), STDERR (a line that is not a window dump), plus the place the monkey was
at, which is in the event. The game is restarted after a crash or a hang, and every 40 places (--places-per-game) in any case. It does not check that a place was really entered (screen_nav_play.py does that for
the village, the castle and the others, with the same teleport); it is a fuzzer for "nothing dies, nothing hangs, nothing is printed". With --program DECK.EXE or DUEL.EXE (the programs of
`./pentamoor deck` and `./pentamoor duel`) there is no map: the same random actions go to the program's own screens for a minute and a half at a time, and the program closing itself
(the Exit button, status 0) is not an event.
Needs the installed game and the saved game (sources/installed, sources/emu_overlay), as the soak does.
"""
import argparse
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soak  # noqa: E402

LOCATIONS, DUNGEONS, MONSTERS = 0x67bdf0, 0x67f000, 0x67f2d0
KEYS = ["Escape", "Escape", "Return", "Return", "space", "Up", "Down", "Left", "Right", "Home", "End", "PageUp", "PageDown", "Tab", "BackSpace"] \
    + list("abcdefghijklmnopqrstuvwxyz0123456789") + ["F%d" % i for i in range(1, 11)]


class Monkey(soak.Soak):
    def __init__(self, a):
        super().__init__(a)
        self.where = "start"
        self.plain = os.path.basename(a.program).lower() != "magic.exe"       # DECK.EXE, DUEL.EXE: no map to teleport on
        if self.plain:                                                        # random clicks open the deck builder's own message boxes (answered by the port, and logged) and, from DUEL.EXE's "Create Deck", the deck builder
            self.known_stderr += [re.compile(r"^MessageBox: "), re.compile(r"^GetProcAddress\(0x[0-9a-f]+, \w+\) -> not found$")]

    def check_alive(self, where):
        if self.plain and not self.game.alive() and self.game.exit_status() == 0:
            self.stats["closed_itself"] += 1                                    # its Exit button
            return False
        return super().check_alive(where)

    def run_plain(self, end_wall):
        """The standalone programs: random actions on whatever screen there is, a new process every 90 s or when it ends."""
        while time.time() < end_wall:
            g = self.new_game()
            self.where = os.path.basename(self.a.program)
            time.sleep(6)
            end = min(end_wall, time.time() + 90)
            n = 0
            while time.time() < end and g.alive():
                self.monkey_action()
                time.sleep(self.rnd.uniform(0.15, 0.7))
                n += 1
                if n % 6 == 0:
                    if self.look(self.where) is None:
                        break
            self.stats["places"] += 1
            self.scan_stderr()
            g.stop()

    def to_map(self):
        """New process, the saved game, the first duel conceded: the world map. False if that did not work."""
        g = self.new_game()
        self.to_ante()
        if not self.start_duel_from_ante(first=True):
            return False
        time.sleep(3)
        if not self.concede():
            self.ev("SETUP", "could not concede the first duel", shot=self.shot("setup"))
            return False
        time.sleep(4)
        for _ in range(8):                                  # the result pages close on a click, then the lost-card pages, then the map
            t = self.look("to the map")
            if t is None:
                return False
            if not t.dialogs() and not t.find("MAGICGAME_MainClass", visible=True):
                break
            if t.dialogs():
                self.handle_dialog(t)
            else:
                g.click(self.w // 2, self.h // 2)
            time.sleep(2.5)
        g.click(self.w // 2, self.h // 2)
        time.sleep(1.5)
        g.key("Return")
        time.sleep(2.5)
        return True

    def places(self):
        g = self.game
        loc = g.peek(LOCATIONS, 25 * 128)
        dun = g.peek(DUNGEONS, 12 * 15)
        if not loc or not dun:
            return []
        out = []
        for i in range(128):
            if loc[25 * i] in (1, 2, 3, 4):
                out.append(("loc%d type %d" % (i, loc[25 * i]), loc[25 * i + 1], loc[25 * i + 2], None))
        for d in range(5, 15):
            out.append(("dungeon %d" % d, dun[12 * d], dun[12 * d + 1], d))
        return out

    def monkey_action(self):
        g, r = self.game, self.rnd
        x = r.randrange(self.w) if r.random() < 0.65 else (self.w - r.randrange(60, 100) if r.random() < 0.5 else r.randrange(20, 80))
        y = r.randrange(self.h)
        k = r.random()
        if k < 0.55:
            g.click(x, y)
            kind = "click"
        elif k < 0.65:
            g.rclick(x, y, hold=0.1)
            kind = "rclick"
        else:
            g.key(r.choice(KEYS))
            kind = "key"
        self.stats["act_" + kind] += 1

    def visit(self, place):
        name, tx, ty, d = place
        g, r = self.game, self.rnd
        self.where = "%s at %d,%d" % (name, tx, ty)
        for i in range(12):
            g.poke(MONSTERS + 0x14 * i, 0xffffffff)
        g.poke(0x522444, 5000)
        g.poke(0x522448, 200)
        if d is not None:
            g.poke(DUNGEONS + 0x10 + 0x30 * d, 7)
        g.teleport_party(tx, ty)
        g.poke(0x5659b0, 0)
        time.sleep(2.0)
        end = time.time() + r.uniform(5, 12)
        n = 0
        while time.time() < end:
            self.monkey_action()
            time.sleep(r.uniform(0.15, 0.7))
            n += 1
            if n % 6 == 0:
                if self.look(self.where) is None:
                    return False
                for i in range(12):
                    g.poke(MONSTERS + 0x14 * i, 0xffffffff)
        self.stats["places"] += 1
        return self.look(self.where) is not None

    def run(self):
        end_wall = time.time() + self.a.minutes * 60
        try:
            if self.plain:
                self.run_plain(end_wall)
                return
            while time.time() < end_wall:
                if not self.to_map():
                    self.game.stop()
                    continue
                pl = self.places()
                if not pl:
                    self.ev("SETUP", "no places read from the game's tables")
                    self.game.stop()
                    continue
                self.ev("NOTE", "game %d on the map: %d places" % (self.stats["games"], len(pl)))
                for _ in range(self.a.places_per_game):
                    if time.time() >= end_wall:
                        break
                    if not self.visit(self.rnd.choice(pl)):
                        break
                self.scan_stderr()
                self.game.stop()
        finally:
            if self.game:
                self.game.stop()
            self.summary()

    def summary(self):
        lines = ["monkey %s %s for %.1f min: %d games, %d %s visited" % (os.path.basename(self.a.program), self.a.res, (time.time() - self.t0) / 60, self.stats["games"], self.stats["places"],
                                                                      "runs" if self.plain else "places")]
        lines.append("events: " + ", ".join("%s %d" % kv for kv in sorted(self.counts.items())))
        lines.append("actions: " + ", ".join("%s %d" % (k[4:], v) for k, v in sorted(self.stats.items()) if k.startswith("act_")))
        if self.stats["closed_itself"]:
            lines.append("the program closed itself %d times (Exit button, status 0)" % self.stats["closed_itself"])
        for k, v in self.stderr_seen.most_common(20):
            lines.append("stderr x%d: %s" % (v, k))
        lines += self.rss_lines()
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
    ap.add_argument("--module", default=None)
    ap.add_argument("--program", default="sources/installed/Magic/Program/MAGIC.EXE")
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--places-per-game", type=int, default=40, help="places visited before the process is restarted (a large number: one process for the whole run, for the resident memory series)")
    ap.add_argument("--stall-s", type=float, default=60)
    ap.add_argument("--tick-s", type=float, default=1.0)
    a = ap.parse_args()
    a.min_turns = a.max_turns = 0
    a.max_duel_s = 20
    a.duels_per_game = 1
    a.verbose = False
    if a.workdir is None:
        a.workdir = "/tmp/monkey-%s" % a.res
    if a.seed is None:
        a.seed = int(time.time())
    print("monkey: seed %d, workdir %s" % (a.seed, a.workdir), flush=True)
    import signal
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))
    Monkey(a).run()


if __name__ == "__main__":
    main()

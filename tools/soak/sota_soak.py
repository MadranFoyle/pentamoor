#!/usr/bin/env python3
"""sota_soak.py: soak Spells of the Ancients 2.15 (shandalar.exe) through PORT_CONTROL, as soak.py and monkey.py do for 1.0.

    python3 tools/soak/sota_soak.py --mode duels  --minutes 20 --workdir /tmp/sota-duels
    python3 tools/soak/sota_soak.py --mode monkey --minutes 20 --workdir /tmp/sota-monkey

It needs what `./pentamoor sota` needs: the 2.15 folder (`--program`, default sources/installed_sota/Magic/Program/shandalar.exe; the first game's install with the expansion's files and
the patch over it), the modules built by tools/install/install_sota.py, and the runtime. Each game starts with an empty overlay, or with a copy of --overlay-seed (an install's port_overlay_sota, with its registry.dat). Spells of the Ancients has no saved game to start from, so each game process starts a NEW GAME
(title, Start New Game, the colour, FaceMaker's portrait, the name), which ends at the first encounter's ante screen, and then:

  duels    play that duel and what follows the way soak.py does (lands, creatures, attacks by clicking, prompts cancelled at random), end it by conceding or, one in two, by winning (the
           opponent's life poked to 0: WIN_LIFE below), click through the reward screens, and go on to the map; the process is restarted after --duels-per-game duels
  monkey   after the first duel is conceded, teleport the party to villages, towers, castles and dungeons of the world map and press random clicks and keys there (monkey.py)

What it logs is soak.py's (CRASH, HANG, STUCK, STDERR, SETUP, NOTE; <workdir>/events.jsonl and summary.txt; rss.csv once a minute). The addresses are those of shandalar.exe 2.15 (the
profile's build); they are not 1.0's. No game file is in this script.
"""
import argparse
import os
import re
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soak  # noqa: E402
from pentamoor_ctl import Game  # noqa: E402

# shandalar.exe 2.15 (found by running it: the notes' "Milestone 2")
LIVES = 0x8f67d0                 # the two life totals, a dword each: you, then the opponent (1.0: 0x6a4a00)
WIN_LIFE = LIVES + 4             # the opponent's
LOCATIONS = 0x721e30             # 128 records of 25 dwords: type (1..4: village, tower, castle, dungeon), tile x, tile y, ...
MONSTERS, MONSTER_STRIDE, N_MONSTERS = 0x725310, 24, 8      # the wandering monsters: type -1 is none (1.0's table is at 0x67f2d0, 20 bytes a record)
PARTY_PIXEL = (0x5645b0, 0x5645b4)
PARTY_TILE = (0x912870, 0x912874)
# the map's cache, as the game's own teleport (the function at 0x49313e) resets it
MAP_RESET = [(0x69e220, 0xffffffff), (0x56758c, 0xffffffff), (0x567590, 1), (0x8b82d0, 0)]
KEYS = ["Escape", "Escape", "Return", "Return", "space", "Up", "Down", "Left", "Right", "Home", "End", "PageUp", "PageDown", "Tab", "BackSpace"] \
    + list("abcdefghijklmnopqrstuvwxyz0123456789") + ["F%d" % i for i in range(1, 11)]

# the title screen, and the new game's screens, as fractions of the screen (measured at 1024x768; the game's own layouts for 800x600 and 640x480 scale the same way)
TITLE_NEW_GAME = (0.5, 0.648)
DIFFICULTY_APPRENTICE = (0.566, 0.247)
COLOUR_RED = (0.132, 0.215)
FACE_PORTRAIT = (0.386, 0.208)           # in FaceMaker's window
ANTE_DUEL = {640: (290, 320), 800: (360, 379), 1024: (470, 486)}       # "Duel this Sorceress." (the first line of the encounter's choices), in pixels at each size
ANTE_PAY = {640: (290, 335), 800: (360, 393), 1024: (470, 508)}
VILLAGE_LEAVE = (0.733, 0.628)           # "Leave the village": a new game can begin in a village, not at an encounter


def teleport_pokes(tx, ty):
    """The pokes that put the party on the middle of tile (tx, ty) and make the map draw itself whole (the 1.0 version is Game.teleport_party; these are 2.15's addresses)."""
    return [(PARTY_PIXEL[0], tx * 32 + 16), (PARTY_PIXEL[1], ty * 32 + 16), (PARTY_TILE[0], tx), (PARTY_TILE[1], ty)] + MAP_RESET


def read_ppm(path):
    """(width, height, bytes of RGB) of a binary PPM, or None."""
    try:
        with open(path, "rb") as f:
            data = f.read()
        m = re.match(rb"P6\s+(\d+)\s+(\d+)\s+(\d+)\s", data)
        if not m:
            return None
        w, h = int(m[1]), int(m[2])
        return w, h, data[m.end():m.end() + 3 * w * h]
    except OSError:
        return None


class SotaSoak(soak.Soak):
    def __init__(self, a):
        super().__init__(a)
        self.known_stderr += [re.compile(r"^LoadLibraryA\((cardartlib|drawcardlib|cdtools)\.dll\) -> mapped"), re.compile(r"^process: started \w+\.exe \(module game_\w+, id \d+\)"),
                              re.compile(r"^process: .* finished"), re.compile(r"^MessageBox: ")]
        self.module = a.module
        self.where = "start"

    # ---- the process --------------------------------------------------------------------------------------------------
    def new_game(self):
        wd = os.path.join(self.workdir, "game%d" % (self.stats["games"]))
        self.stats["games"] += 1
        ext = "dylib" if sys.platform == "darwin" else "so"
        module = self.module or os.path.join(os.path.dirname(os.path.join(self.a.repo, self.a.exe)), "game_shandalar." + ext)
        g = Game(self.a.repo, res=self.a.res, workdir=wd, exe=self.a.exe, program=self.a.program, module=module, overlay_seed=self.a.overlay_seed or None)
        g.start()
        self.game = g
        self.log_off = 0
        self.started_wall = time.time()
        return g

    def engine_state(self):
        g = self.game
        return {"lives": g.peek(LIVES, 2)}

    def at(self, frac):
        return int(frac[0] * self.w), int(frac[1] * self.h)

    def log_has(self, text, since=0):
        try:
            return text in self.game.read_log(since)
        except OSError:
            return False

    def wait_log(self, text, timeout, since=0):
        end = time.time() + timeout
        while time.time() < end:
            if self.log_has(text, since):
                return True
            if not self.game.alive():
                return False
            time.sleep(0.5)
        return False

    # ---- a new game, to the first encounter ----------------------------------------------------------------------------
    def to_ante(self):
        """Title, Start New Game, difficulty, colour, FaceMaker's portrait, the name: to the first encounter's ante screen. False (a SETUP event) if a step did not happen."""
        g = self.game
        if not self.wait_log("loaded ", 30):
            self.ev("SETUP", "the program did not load", shot=self.shot("setup"))
            return False
        time.sleep(9)                                           # the title screen draws
        g.click(*self.at(TITLE_NEW_GAME))
        time.sleep(2.5)
        g.click(*self.at(DIFFICULTY_APPRENTICE))
        time.sleep(2.5)
        g.click(*self.at(COLOUR_RED))
        fm = g.ctl_path + ".facemaker"
        end = time.time() + 90
        while time.time() < end and not os.path.exists(fm):     # the second program is started with a pipe of its own
            time.sleep(0.5)
        if not os.path.exists(fm):
            self.ev("SETUP", "FaceMaker was not started", shot=self.shot("setup"))
            return False
        fd = os.open(fm, os.O_RDWR | os.O_NONBLOCK)
        try:
            off = g.log_size()
            os.write(fd, b"windows\n")                          # FaceMaker is ready when its window is there
            t_end = time.time() + 120
            while time.time() < t_end and "FacemakerMainClass" not in g.read_log(off):
                time.sleep(1.0)
                os.write(fd, b"windows\n")
            time.sleep(3)
            x, y = self.at(FACE_PORTRAIT)
            os.write(fd, ("move %d %d\n" % (x, y)).encode())
            time.sleep(0.5)
            os.write(fd, ("down %d %d\n" % (x, y)).encode())
            time.sleep(0.3)
            os.write(fd, ("up %d %d\n" % (x, y)).encode())      # the portrait: its click ends FaceMaker
        finally:
            os.close(fd)
        time.sleep(7)
        for k in ("a", "b", "return"):                          # the name
            g.key(k)
            time.sleep(0.2)
        # the world is made (about 25 s here), then the first encounter's ante screen
        time.sleep(8)
        if not self.wait_log("statwin.dll", 120):
            self.ev("SETUP", "the game did not start after the name", shot=self.shot("setup"))
            return False
        time.sleep(6)
        return True

    def start_duel_from_ante(self, first=True):
        g = self.game
        t0 = time.time()
        t_end = t0 + (180 if first else 40)
        clicked = left = 0.0
        while time.time() < t_end:
            t = self.look("starting a duel")
            if t is None:
                return False
            if t.find("MAGICGAME_MainClass") and t.bar() and t.bar()[0].visible and t.bar()[0].title:
                return True
            if t.dialogs():
                self.handle_dialog(t)
            elif time.time() - clicked > 6:                     # the ante screen is a picture, not a window: click its "Duel" line now and then until the board comes
                g.click(*ANTE_DUEL[self.w])
                clicked = time.time()
            if first and time.time() - t0 > 25 and time.time() - left > 45:       # the game began in a village (or on the map): leave it; the monsters come to the party
                g.click(*self.at(VILLAGE_LEAVE))
                time.sleep(2.5)
                mon = self.monsters()
                if mon:                                         # on the map with no monster near: put the party on the first one, as the game's own encounters do
                    g.poke_many(teleport_pokes(mon[0][0] // 32, mon[0][1] // 32))
                else:
                    x, y = self.rnd.randrange(self.w // 3, 2 * self.w // 3), self.rnd.randrange(self.h // 4, 3 * self.h // 5)
                    g.cmd("move %d %d" % (x, y))                # (a monster beside the party starts its encounter when the party moves)
                    time.sleep(0.3)
                    g.cmd("down %d %d" % (x, y))
                    time.sleep(1.2)
                    g.cmd("up %d %d" % (x, y))
                left = time.time()
            time.sleep(2.0)
        if first:
            self.ev("SETUP", "no duel board 180 s after the first screen", shot=self.shot("setup"))
        else:
            self.ev("NOTE", "no further duel after the last one: restarting the game", shot=self.shot("moved-on"))
        return False

    def monsters(self):
        """[(pixel x, pixel y)] of the wandering monsters on the map (the table at MONSTERS: type, x, y, ... in 6 dwords; type -1 is none)."""
        v = self.game.peek(MONSTERS, 6 * N_MONSTERS)
        if not v:
            return []
        return [(v[6 * i + 1], v[6 * i + 2]) for i in range(N_MONSTERS) if v[6 * i] != 0xffffffff and 0 < v[6 * i + 1] < 4000 and 0 < v[6 * i + 2] < 4000]

    def win(self):
        """Win the duel the way a player cannot: the opponent's life to 0, then any action makes the engine look at the totals (tools/soak/won_dialog.py does the same for 1.0). The poke
        is repeated, a pass at a time, until the board is gone or a dialog (the result) is up: a poke made before the engine has set the life totals at the start of a duel is overwritten."""
        g = self.game
        for _ in range(8):
            g.poke(WIN_LIFE, 0)
            t = self.look("win")
            if t is None:
                return False
            texts = " ".join(c.title.lower() for d in t.dialogs() for c in t.children(d) if c.visible)
            if not t.find("MAGICGAME_MainClass") or "won" in texts or "defeated" in texts or "lost" in texts:
                return True
            if t.dialogs():
                self.handle_dialog(t)
            b = t.bar()
            if b and b[2]:
                g.click(*b[2].center)
            time.sleep(3)
        return False

    def play_duel(self, end_wall):
        """soak.Soak.play_duel; the duel is ended by winning it (the opponent's life poked to 0) or, otherwise, by conceding: chosen at random for each duel."""
        self._want_win = self.rnd.random() < 0.5
        return super().play_duel(end_wall)

    def concede(self):
        """Where soak.Soak ends a duel by conceding, half of them are won instead."""
        if getattr(self, "_want_win", False):
            self._want_win = False
            self.stats["won"] += 1
            self.win()
            return True
        self.stats["conceded"] += 1
        return super().concede()

    def after_duel(self):
        """The movie after a won duel, the reward screens ("Take the cards"), the lost-card pages: clicks and keys, until the map."""
        g = self.game
        for i in range(14):
            t = self.look("after duel")
            if t is None:
                return False
            if t.dialogs():
                self.handle_dialog(t)
            elif t.find("MAGICGAME_MainClass") and t.bar() and t.bar()[0].visible and t.bar()[0].title:
                return True
            else:
                g.click(self.w // 2, int(0.70 * self.h) if i % 3 == 1 else self.h // 2)
                time.sleep(1.2)
                if i % 4 == 3:
                    g.key("return")
            time.sleep(3.0)
        return True

    # ---- duels ---------------------------------------------------------------------------------------------------------
    def session(self, end_wall):
        self.new_game()
        if not self.to_ante():
            self.scan_stderr()
            self.game.stop()
            return
        for duel_no in range(self.a.duels_per_game):
            if time.time() >= end_wall:
                break
            if not self.start_duel_from_ante(first=duel_no == 0):
                break
            self.stats["duels"] += 1
            res = self.play_duel(end_wall)
            self.ev("NOTE", "duel %d (game %d) ended: %s after %d turns total (won %d, conceded %d)" % (self.stats["duels"], self.stats["games"], res, self.stats["turns"],
                                                                                                    self.stats["won"], self.stats["conceded"]))
            if res == "restart":
                break
            if not self.after_duel():
                break
        self.scan_stderr()
        self.game.stop()

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
        lines = ["sota soak %s for %.1f min: %d games, %d duels, %d turns (won %d, conceded %d)" % (self.a.res, (time.time() - self.t0) / 60, self.stats["games"], self.stats["duels"],
                                                                                               self.stats["turns"], self.stats["won"], self.stats["conceded"])]
        lines.append("events: " + ", ".join("%s %d" % kv for kv in sorted(self.counts.items())))
        lines.append("actions: " + ", ".join("%s %d" % (k[4:], v) for k, v in sorted(self.stats.items()) if k.startswith("act_")))
        for k, v in self.stderr_seen.most_common(20):
            lines.append("stderr x%d: %s" % (v, k))
        lines += self.rss_lines()
        text = "\n".join(lines)
        print(text, flush=True)
        open(os.path.join(self.workdir, "summary.txt"), "w").write(text + "\n")


class SotaMonkey(SotaSoak):
    """After the first duel, places of the world map and random clicks and keys (monkey.py)."""

    def places(self):
        loc = self.game.peek(LOCATIONS, 25 * 128)
        if not loc:
            return []
        return [("loc%d type %d" % (i, loc[25 * i]), loc[25 * i + 1], loc[25 * i + 2]) for i in range(128) if loc[25 * i] in (1, 2, 3, 4)]

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
        name, tx, ty = place
        g, r = self.game, self.rnd
        self.where = "%s at %d,%d" % (name, tx, ty)
        g.poke_many([(MONSTERS + MONSTER_STRIDE * i, 0xffffffff) for i in range(N_MONSTERS)] + teleport_pokes(tx, ty))
        time.sleep(2.0)
        end = time.time() + r.uniform(8, 20)
        n = 0
        while time.time() < end:
            self.monkey_action()
            time.sleep(r.uniform(0.15, 0.7))
            n += 1
            if n % 6 == 0:
                if self.look(self.where) is None:
                    return False
                g.poke_many([(MONSTERS + MONSTER_STRIDE * i, 0xffffffff) for i in range(N_MONSTERS)])       # no encounter walks into the party meanwhile
        self.stats["places"] += 1
        return self.look(self.where) is not None

    def session(self, end_wall):
        self.new_game()
        if not self.to_ante() or not self.start_duel_from_ante(first=True):
            self.scan_stderr()
            self.game.stop()
            return
        time.sleep(3)
        if not self.concede():
            self.ev("SETUP", "could not concede the first duel", shot=self.shot("setup"))
            self.game.stop()
            return
        time.sleep(4)
        self.after_duel()
        self.game.click(self.w // 2, self.h // 2)
        time.sleep(2)
        pl = self.places()
        if not pl:
            self.ev("SETUP", "no places read from the game's tables")
            self.game.stop()
            return
        self.ev("NOTE", "game %d on the map: %d places" % (self.stats["games"], len(pl)))
        for _ in range(self.a.places_per_game):
            if time.time() >= end_wall or not self.visit(self.rnd.choice(pl)):
                break
        self.scan_stderr()
        self.game.stop()

    def summary(self):
        super().summary()
        line = "places visited: %d" % self.stats["places"]
        print(line, flush=True)
        open(os.path.join(self.workdir, "summary.txt"), "a").write(line + "\n")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["duels", "monkey"], default="duels")
    ap.add_argument("--res", default="1024x768", choices=["640x480", "800x600", "1024x768"])
    ap.add_argument("--minutes", type=float, default=20)
    ap.add_argument("--repo", default=os.path.abspath(os.path.join(here, "..", "..")))
    ap.add_argument("--exe", default="src/port/build/pentamoor-run")
    ap.add_argument("--module", default=None, help="the game module (default: game_shandalar next to --exe)")
    ap.add_argument("--program", default="sources/installed_sota/Magic/Program/shandalar.exe")
    ap.add_argument("--overlay-seed", default=None, help="a folder copied to be each game's overlay (default: an empty one): an install's port_overlay_sota keeps its registry.dat, and with it the licence value, "
                    "so a run with a copy of it plays as that install does")
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--duels-per-game", type=int, default=2)
    ap.add_argument("--places-per-game", type=int, default=15)
    ap.add_argument("--min-turns", type=int, default=3)
    ap.add_argument("--max-turns", type=int, default=9)
    ap.add_argument("--max-duel-s", type=float, default=300)
    ap.add_argument("--stall-s", type=float, default=60)
    ap.add_argument("--tick-s", type=float, default=1.0)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    if a.workdir is None:
        a.workdir = "/tmp/sota-%s-%s" % (a.mode, a.res)
    if a.seed is None:
        a.seed = int(time.time())
    if a.mode == "monkey":
        a.min_turns = a.max_turns = 0
        a.max_duel_s = 20
    print("sota_soak: mode %s, seed %d, workdir %s" % (a.mode, a.seed, a.workdir), flush=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))
    (SotaMonkey if a.mode == "monkey" else SotaSoak)(a).run()


if __name__ == "__main__":
    main()

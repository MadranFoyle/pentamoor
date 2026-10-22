#!/usr/bin/env python3
"""sota_shell_soak.py: soak the Magic Shell of Spells of the Ancients 2.15 (magic.exe) and the program graph around it through PORT_CONTROL.

    python3 tools/soak/sota_shell_soak.py --minutes 20 --workdir /tmp/sota-shell-soak --overlay-seed /tmp/overlay-with-licence

It needs what `./pentamoor sota shell` needs: the 2.15 folder (`--program`, default sources/installed_sota/Magic/Program/magic.exe), the modules built by tools/install/install_sota.py (game_shell,
game_shandalar, game_facemaker, ...) and the runtime. --overlay-seed is a folder copied to be each session's overlay (an install's port_overlay_sota, with its registry.dat and the licence value in it, which the installer's default makes with the game's "skip the disc check" flag; an
empty one if not given, or one from an install made with --keep-cd-check: the shell's "Start match" then does not get to the board, which is the disc check and not what this script tests).

With --mode duels it plays the shell's own duels instead (single duel and gauntlet from the Duel page, a few turns each: ShellDuels).

A session starts the shell and, for a few minutes, presses random things in it: clicks on the controls of the window tree (the pages' buttons, list and combo boxes), clicks anywhere, right clicks,
keys. When a click starts the adventure (the World page's Shandalar; the shell ends itself and the runtime starts shandalar.exe), the script follows to the new program through its own control pipe
(<ctl>.shandalar), looks at the title for a few seconds, presses a few random things, and leaves it by its Exit button, which starts the shell again (<ctl>.shandalar.magic), and the monkey goes on there.
When the shell is left by its own exit (status 0) the session is over. After every session the process group is stopped and the process ids the runtime logged ("process: started ...") must be gone: an ORPHAN
event if one is not.

What it logs is soak.py's (CRASH, HANG, STDERR, SETUP, NOTE; <workdir>/events.jsonl and summary.txt; rss.csv once a minute), plus ORPHAN. The summary has rounds (sessions), actions by kind, handoffs
(shell -> Shandalar), returns (Shandalar -> shell) and quits. No game file is in this script.
"""
import argparse
import glob
import os
import re
import shutil
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soak  # noqa: E402
from pentamoor_ctl import Game  # noqa: E402

KEYS = ["Escape", "Escape", "Return", "Return", "space", "Up", "Down", "Left", "Right", "Home", "End", "PageUp", "PageDown", "Tab", "BackSpace"] \
    + list("abcdefghijklmnopqrstuvwxyz0123456789") + ["F%d" % i for i in range(1, 11)]
STARTED_RE = re.compile(r"^process: started (\S+) \(module (\S+), id (\d+)\)", re.M)
# the title menu's Exit button of shandalar.exe, as fractions of the screen (measured at 800x600)
TITLE_EXIT = (315 / 800, 543 / 600)
# the shell's own way to the adventure (measured at 800x600): the World tab of the left-hand menu, then the "Shandalar" button on its page
SHELL_WORLD = (80 / 800, 305 / 600)
SHELL_SHANDALAR = (250 / 800, 78 / 600)
# the Duel page (measured at 800x600): the tab, the three kinds, and the button that starts each
SHELL_DUEL = (85 / 800, 98 / 600)
SHELL_KIND = {"solo": (295 / 800, 79 / 600), "gauntlet": (292 / 800, 105 / 600)}
SHELL_START = {"solo": (681 / 800, 511 / 600), "gauntlet": (672 / 800, 511 / 600)}
START_TITLES = {"solo": "Start &match", "gauntlet": "&Run the gauntlet"}


def started_programs(log_text):
    """[(exe, module, pid)] for every "process: started" line of the log, in order."""
    return [(m[1], m[2], int(m[3])) for m in STARTED_RE.finditer(log_text)]


def child_control(parent_ctl, exe):
    """The control pipe of the program that `parent_ctl`'s program started (src/port/process.c: <control>.<stem of the program's name>)."""
    return "%s.%s" % (parent_ctl, os.path.splitext(exe)[0].lower())


def pid_gone(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return True
    return False


class ShellSoak(soak.Soak):
    def __init__(self, a):
        super().__init__(a)
        self.known_stderr += [re.compile(r"^LoadLibraryA\(\w+\.dll\) -> mapped"), re.compile(r"^process: started \w+\.exe \(module game_\w+, id \d+\)"),
                              re.compile(r"^process: .* finished"), re.compile(r"^MessageBox: "),
                              # the Help page's Read Me and Help File run Windows' own Write.exe and WinHelp.exe, which are not programs of the game: the runtime says so and the shell goes on
                              re.compile(r"^process: not started: C:\\WINDOWS\\(Write|WinHelp)\.exe is not a program the profile"),
                              re.compile(r"^\[debug\] ")]
        self.root = None
        self.where = "start"
        self.pids = []
        self.tree = None

    # ---- the process graph --------------------------------------------------------------------------------------------
    def new_game(self):
        wd = os.path.join(self.workdir, "round%d" % self.stats["games"])
        self.stats["games"] += 1
        ext = "dylib" if sys.platform == "darwin" else "so"
        module = self.a.module or os.path.join(os.path.dirname(os.path.join(self.a.repo, self.a.exe)), "game_shell." + ext)
        g = Game(self.a.repo, res=self.a.res, workdir=wd, exe=self.a.exe, program=self.a.program, module=module, overlay_seed=self.a.overlay_seed or None)
        g.start()
        self.root = self.game = g
        self.pids = [g.pid]
        self.log_off = 0
        self.started_wall = time.time()
        return g

    def follow(self, want):
        """The runtime logged that the current program started others: every one not seen yet is recorded (for the orphan check), and the first named `want` becomes the current program,
        driven through its own control pipe. Returns its exe name or None."""
        cur = self.game
        found = None
        for exe, _, pid in started_programs(self.root.read_log(0)):
            if pid in self.pids:
                continue
            self.pids.append(pid)
            if found is None and exe.lower() == want:
                found = (exe, pid)
        if found is None:
            return None
        exe, pid = found
        nxt = Game(self.a.repo, res=self.a.res, workdir=self.root.workdir, exe=self.a.exe, program=self.a.program)
        nxt.ctl_path = child_control(cur.ctl_path, exe)
        end = time.time() + 20
        while time.time() < end and not os.path.exists(nxt.ctl_path):
            time.sleep(0.2)
        if not os.path.exists(nxt.ctl_path):
            self.ev("SETUP", "no control pipe %s for %s" % (os.path.basename(nxt.ctl_path), exe))
            return None
        nxt.attach(pid)
        self.game = nxt
        return exe

    def crash_report(self, pid):
        """macOS: the crash report of that process (a copy of it in the workdir), or None."""
        if sys.platform != "darwin":
            return None
        for p in sorted(glob.glob(os.path.expanduser("~/Library/Logs/DiagnosticReports/pentamoor*")), key=os.path.getmtime, reverse=True)[:5]:
            if os.path.getmtime(p) >= self.started_wall - 5:
                try:
                    text = open(p, errors="replace").read(4000)
                except OSError:
                    continue
                if re.search(r'"pid"\s*:\s*%d\b|\[%d\]' % (pid, pid), text):
                    dst = os.path.join(self.workdir, os.path.basename(p))
                    shutil.copy(p, dst)
                    return dst
        return None

    def check_alive(self, where):
        """A program of the graph that is gone is a CRASH unless it ended itself: the root with status 0, one we did not start with no crash report (we cannot read its status)."""
        g = self.game
        if g.alive():
            return True
        if g is self.root:
            if g.exit_status() == 0:
                return False
            return super().check_alive(where)
        report = self.crash_report(g.pid)
        if report is None:
            return False
        self.ev("CRASH", "program %d gone at %s" % (g.pid, where), report=report, log_tail="\n".join(l for l in g.read_log(max(0, g.log_size() - 1500)).split("\n") if not l.startswith(soak.DUMP_PREFIXES))[-600:])
        return False

    def orphans(self):
        """Process ids this round started that are still there after the group was stopped: killed (by id) and reported."""
        time.sleep(1.5)
        for pid in self.pids:
            if not pid_gone(pid):
                self.ev("ORPHAN", "process %d is still running after the session ended" % pid)
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass

    # ---- the monkey ---------------------------------------------------------------------------------------------------
    def action(self, tree):
        g, r = self.game, self.rnd
        targets = []
        if tree is not None:
            targets = [w for w in tree.wins if w.visible and not w.empty and w.x1 - w.x0 < self.w // 2 and w.y1 - w.y0 < self.h // 2 and w.cls not in ("MAGICGAME_MainClass",)]
        k = r.random()
        if targets and k < 0.5:
            x, y = r.choice(targets).center
            g.click(x, y)
            kind = "click_control"
        elif k < 0.7:
            g.click(r.randrange(self.w), r.randrange(self.h))
            kind = "click"
        elif k < 0.78:
            g.rclick(r.randrange(self.w), r.randrange(self.h), hold=0.1)
            kind = "rclick"
        else:
            g.key(r.choice(KEYS))
            kind = "key"
        self.stats["act_" + kind] += 1

    def try_shandalar(self):
        """Press the way a player goes to the adventure: the World page, then Shandalar. Whether the shell was on a page where that works is for `follow` to find out."""
        self.stats["tries_shandalar"] += 1
        self.game.click(int(SHELL_WORLD[0] * self.w), int(SHELL_WORLD[1] * self.h))
        time.sleep(2.5)
        self.game.click(int(SHELL_SHANDALAR[0] * self.w), int(SHELL_SHANDALAR[1] * self.h))
        time.sleep(3.0)

    def monkey(self, seconds, label):
        end = time.time() + seconds
        n = 0
        tree = None
        while time.time() < end:
            self.action(tree)
            time.sleep(self.rnd.uniform(0.15, 0.7))
            n += 1
            if n % 6 == 0:
                tree = self.look(label)
                if tree is None:
                    return False
        return True

    def adventure(self):
        """shandalar.exe is up: let its title draw, press a few things, leave it by Exit, which starts the shell again. True if the shell is there again."""
        self.stats["handoffs"] += 1
        self.where = "shandalar.exe"
        time.sleep(self.rnd.uniform(8, 12))
        if self.look(self.where) is None:
            return False
        self.shot("adventure")
        if self.rnd.random() < 0.5:
            for _ in range(self.rnd.randrange(2, 6)):          # a few random keys (not clicks: a click may begin a new game, which is FaceMaker's business and not the shell's)
                self.game.key(self.rnd.choice(["Up", "Down", "Tab", "Escape", "space"]))
                time.sleep(0.5)
        self.game.click(int(TITLE_EXIT[0] * self.w), int(TITLE_EXIT[1] * self.h))
        end = time.time() + 40
        while time.time() < end:
            if self.follow("magic.exe"):
                self.stats["returns"] += 1
                self.where = "magic.exe"
                time.sleep(4)
                return True
            time.sleep(1.0)
        self.ev("NOTE", "the adventure's Exit did not bring the shell back", shot=self.shot("no-shell"))
        return False

    def session(self, end_wall):
        g = self.new_game()
        end_s = min(end_wall, time.time() + self.rnd.uniform(self.a.session_min_s, self.a.session_max_s))
        t_end = time.time() + 30
        while time.time() < t_end and "loaded " not in g.read_log(0) and g.alive():
            time.sleep(0.5)
        if "loaded " not in g.read_log(0):
            self.ev("SETUP", "the shell did not load", shot=self.shot("setup"))
        else:
            time.sleep(5)
            self.where = "magic.exe"
            due = time.time() + self.rnd.uniform(self.a.handoff_min_s, self.a.handoff_max_s)
            while time.time() < end_s:
                bad = self.counts["CRASH"] + self.counts["HANG"]
                if time.time() > due and self.game.alive():
                    self.try_shandalar()
                    due = time.time() + self.rnd.uniform(self.a.handoff_min_s, self.a.handoff_max_s)
                if self.monkey(min(8.0, max(1.0, end_s - time.time())), self.where):
                    continue
                if self.game.alive() or self.counts["CRASH"] + self.counts["HANG"] > bad:
                    break                                       # a hang, or a crash: the round is over
                # the shell is gone without a crash: it began the adventure (the World page) or it was quit
                time.sleep(1.0)
                if self.follow("shandalar.exe"):
                    if not self.adventure():
                        break
                    continue
                self.stats["quits"] += 1
                self.ev("NOTE", "the shell ended itself without starting the adventure: quit")
                break
        self.scan_stderr()
        self.root.stop()
        self.orphans()

    def run(self):
        end_wall = time.time() + self.a.minutes * 60
        try:
            while time.time() < end_wall:
                self.session(end_wall)
        finally:
            if self.root:
                self.root.stop()
            self.summary()

    def summary(self):
        lines = ["sota shell soak %s for %.1f min: %d rounds, %d hand-offs to Shandalar, %d returns to the shell, %d quits" % (
            self.a.res, (time.time() - self.t0) / 60, self.stats["games"], self.stats["handoffs"], self.stats["returns"], self.stats["quits"])]
        lines.append("events: " + ", ".join("%s %d" % kv for kv in sorted(self.counts.items())))
        lines.append("actions: " + ", ".join("%s %d" % (k[4:], v) for k, v in sorted(self.stats.items()) if k.startswith("act_")))
        for k, v in self.stderr_seen.most_common(20):
            lines.append("stderr x%d: %s" % (v, k))
        lines += self.rss_lines()
        text = "\n".join(lines)
        print(text, flush=True)
        open(os.path.join(self.workdir, "summary.txt"), "w").write(text + "\n")


class ShellDuels(ShellSoak):
    """The shell's own duels: a single duel or a gauntlet, started from the Duel page with the licence value in the overlay (without it the duel ends at once: the disc check), played as soak.py
    plays one (lands, spells, attacks, prompts cancelled at random) for a few turns and conceded, and back to the page for the next."""

    def engine_state(self):
        return {}                                               # (the lives are not at shandalar.exe's address in this program)

    def look(self, where):
        """The window tree, in which "a dialog" is a pop-up one (the coin toss, the mulligan, the results): the shell's pages are child dialogs that stay there all the time."""
        t = super().look(where)
        if t is not None:
            all_dialogs = t.dialogs
            t.dialogs = lambda: [d for d in all_dialogs() if d.style & 0x80000000]
        return t

    def at(self, frac):
        return int(frac[0] * self.w), int(frac[1] * self.h)

    def page_buttons(self, t):
        return [w for w in t.wins if w.cls.startswith("BUTTON") and w.visible and not w.empty]

    def on_duel_page(self, t, kind):
        return any(START_TITLES[kind] in b.title for b in self.page_buttons(t))

    def to_board(self, kind):
        """From the shell's window to the first main phase of a duel. True if the board came."""
        g = self.game
        t = self.look("the Duel page")
        if t is None:
            return False
        if not any("Solo" in b.title or "Gauntlet" in b.title for b in self.page_buttons(t)):       # (the Duel tab again would close the page: it is a toggle)
            g.click(*self.at(SHELL_DUEL))
            time.sleep(1.5)
        g.click(*self.at(SHELL_KIND[kind]))
        time.sleep(1.5)
        g.click(*self.at(SHELL_START[kind]))
        end = time.time() + 120
        while time.time() < end:
            time.sleep(2.0)
            t = self.look("starting a %s duel" % kind)
            if t is None:
                return False
            if t.find("MAGICGAME_MainClass") and t.bar() and t.bar()[0].visible and t.bar()[0].title:
                return True
            if t.dialogs():
                self.handle_dialog(t)
        self.ev("NOTE", "no duel board 120 s after %s" % START_TITLES[kind], shot=self.shot("no-board"))
        return False

    def to_page(self, kind):
        """After a duel: results and what follows, clicked through, until the Duel page is there again."""
        g = self.game
        end = time.time() + 90
        while time.time() < end:
            t = self.look("after the duel")
            if t is None:
                return False
            if self.on_duel_page(t, kind):
                return True
            if t.dialogs():
                self.handle_dialog(t)
            else:
                g.key("return")
                time.sleep(1.0)
                g.click(self.w // 2, self.h // 2)
            time.sleep(2.0)
        self.ev("NOTE", "the Duel page did not come back after the duel", shot=self.shot("no-page"))
        return False

    def session(self, end_wall):
        g = self.new_game()
        t_end = time.time() + 30
        while time.time() < t_end and "loaded " not in g.read_log(0) and g.alive():
            time.sleep(0.5)
        time.sleep(5)
        self.where = "magic.exe"
        for _ in range(self.a.duels_per_game):
            if time.time() >= end_wall:
                break
            kind = self.rnd.choice(["solo", "solo", "gauntlet"])
            if not self.to_board(kind):
                break
            self.stats["duels"] += 1
            self.stats["duels_" + kind] += 1
            res = self.play_duel(end_wall)
            self.ev("NOTE", "%s duel %d (round %d) ended: %s after %d turns total" % (kind, self.stats["duels"], self.stats["games"], res, self.stats["turns"]))
            if res == "restart" or not self.to_page(kind):
                break
        self.scan_stderr()
        self.root.stop()
        self.orphans()

    def summary(self):
        super().summary()
        line = "duels: %d (single %d, gauntlet %d), turns %d" % (self.stats["duels"], self.stats["duels_solo"], self.stats["duels_gauntlet"], self.stats["turns"])
        print(line, flush=True)
        open(os.path.join(self.workdir, "summary.txt"), "a").write(line + "\n")


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["monkey", "duels"], default="monkey")
    ap.add_argument("--duels-per-game", type=int, default=3)
    ap.add_argument("--min-turns", type=int, default=3)
    ap.add_argument("--max-turns", type=int, default=9)
    ap.add_argument("--max-duel-s", type=float, default=300)
    ap.add_argument("--res", default="800x600", choices=["640x480", "800x600", "1024x768"])
    ap.add_argument("--minutes", type=float, default=20)
    ap.add_argument("--repo", default=os.path.abspath(os.path.join(here, "..", "..")))
    ap.add_argument("--exe", default="src/port/build/pentamoor-run")
    ap.add_argument("--module", default=None, help="the shell's module (default: game_shell next to --exe)")
    ap.add_argument("--program", default="sources/installed_sota/Magic/Program/magic.exe")
    ap.add_argument("--overlay-seed", default=None, help="a folder copied to be each session's overlay (its registry.dat holds the licence value)")
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--session-min-s", type=float, default=120)
    ap.add_argument("--session-max-s", type=float, default=240)
    ap.add_argument("--handoff-min-s", type=float, default=20, help="the monkey goes the way to the adventure (World, Shandalar) every so many seconds (a random time between the two)")
    ap.add_argument("--handoff-max-s", type=float, default=70)
    ap.add_argument("--stall-s", type=float, default=60)
    ap.add_argument("--tick-s", type=float, default=1.0)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()
    if a.workdir is None:
        a.workdir = "/tmp/sota-shell-%s" % a.res
    if a.seed is None:
        a.seed = int(time.time())
    print("sota_shell_soak: seed %d, workdir %s" % (a.seed, a.workdir), flush=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))
    (ShellDuels if a.mode == "duels" else ShellSoak)(a).run()


if __name__ == "__main__":
    main()

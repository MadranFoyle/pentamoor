"""pentamoor_ctl: drive a running Pentamoor (MAGIC.EXE) through its PORT_CONTROL pipe.

No game files are in here: the program is started from a game folder you give it, on SDL's dummy video and audio drivers, with its own
control pipe, its own overlay directory (a copy of sources/emu_overlay, so saves are not shared with anyone else) and its own log.

    g = Game(repo_dir, res="800x600", workdir="/tmp/soak1")
    g.start()
    g.click(330, 390)
    ws = g.windows()           # the window tree (list of Win)
    g.shot("/tmp/a.png")       # needs PIL
    g.stop()

Everything the program prints on stderr goes to <workdir>/game.log; `windows` dumps are read back from there.
"""
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

WIN_RE = re.compile(
    r"^  win 0x(?P<h>[0-9a-f]+) parent 0x(?P<p>[0-9a-f]+) (?P<cls>\S+) '(?P<title>.*)' "
    r"\((?P<x0>-?\d+),(?P<y0>-?\d+)\)-\((?P<x1>-?\d+),(?P<y1>-?\d+)\) z=(?P<z>\S+) style=0x(?P<style>[0-9a-f]+) "
    r"tid=(?P<tid>\d+)(?P<rest>.*)$")


class Win:
    __slots__ = ("h", "parent", "cls", "title", "x0", "y0", "x1", "y1", "z", "style", "tid", "visible")

    def __init__(self, m):
        self.h = int(m["h"], 16)
        self.parent = int(m["p"], 16)
        self.cls = m["cls"]
        self.title = m["title"]
        self.x0, self.y0, self.x1, self.y1 = (int(m[k]) for k in ("x0", "y0", "x1", "y1"))
        self.z = m["z"]
        self.style = int(m["style"], 16)
        self.tid = int(m["tid"])
        self.visible = " visible" in m["rest"]

    @property
    def empty(self):
        return self.x1 <= self.x0 or self.y1 <= self.y0

    @property
    def center(self):
        return ((self.x0 + self.x1) // 2, (self.y0 + self.y1) // 2)

    def __repr__(self):
        return "<Win 0x%x %s %r (%d,%d)-(%d,%d)%s>" % (self.h, self.cls, self.title, self.x0, self.y0, self.x1, self.y1,
                                                       " vis" if self.visible else "")


ITEM_RE = re.compile(r"^  item (?P<l>\d+)\.(?P<i>\d+) '(?P<text>.*)' \((?P<x0>-?\d+),(?P<y0>-?\d+)\)-\((?P<x1>-?\d+),(?P<y1>-?\d+)\)(?P<rest>.*)$")


class Item:
    """A row of an open popup menu."""

    def __init__(self, m):
        self.level, self.index, self.text = int(m["l"]), int(m["i"]), m["text"]
        self.x0, self.y0, self.x1, self.y1 = (int(m[k]) for k in ("x0", "y0", "x1", "y1"))
        self.separator = "separator" in m["rest"]
        self.disabled = "disabled" in m["rest"]

    @property
    def center(self):
        return ((self.x0 + self.x1) // 2, (self.y0 + self.y1) // 2)

    def __repr__(self):
        return "<Item %d.%d %r>" % (self.level, self.index, self.text)


class Tree:
    """One `windows` dump."""

    def __init__(self, wins, queue_line="", items=None):
        self.items = items or []
        self.wins = wins
        self.by_h = {w.h: w for w in wins}
        self.queue_line = queue_line

    def find(self, cls=None, title=None, visible=None):
        out = []
        for w in self.wins:
            if cls is not None and w.cls != cls:
                continue
            if title is not None and title not in w.title:
                continue
            if visible is not None and w.visible != visible:
                continue
            out.append(w)
        return out

    def children(self, w):
        return [c for c in self.wins if c.parent == w.h]

    def shown(self, w):
        """visible itself and every ancestor visible."""
        while w is not None:
            if not w.visible:
                return False
            w = self.by_h.get(w.parent)
        return True

    def bar(self):
        """The prompt bar (MAGIC_TellUserClass): (window, cancel_button, done_button) or None. Cancel is the button created first (id 1),
        Done the second (id 2); a button that is not shown is None."""
        bars = self.find("MAGIC_TellUserClass")
        if not bars:
            return None
        b = bars[0]
        btns = [c for c in self.children(b) if c.cls.startswith("BUTTON")]
        cancel = btns[0] if len(btns) > 0 and btns[0].visible and not btns[0].empty else None
        done = btns[1] if len(btns) > 1 and btns[1].visible and not btns[1].empty else None
        return b, cancel, done

    def bar_shown(self):
        b = self.bar()
        return b is not None and b[0].visible and b[0].title != ""

    def dialogs(self):
        """Visible top-level dialog windows of the game (class #32770)."""
        return [w for w in self.wins if w.cls.startswith("#32770") and w.visible]


class Game:
    def __init__(self, repo, res="640x480", workdir=None, exe="src/port/build/pentamoor-run", program="sources/installed/Magic/Program/MAGIC.EXE",
                 extra_env=None, module=None, overlay_seed="sources/emu_overlay", args=()):
        self.repo = repo
        self.res = res
        self.w, self.h = (int(v) for v in res.split("x"))
        self.workdir = workdir or tempfile.mkdtemp(prefix="soak-")
        os.makedirs(self.workdir, exist_ok=True)
        self.exe = os.environ.get("PENTAMOOR_RUN") or os.path.join(repo, exe)          # the launcher's variables: another runtime, another game module
        self.program = os.path.join(repo, program)
        # the game module (the library made from the lifted C) the runtime loads: game_magic / game_deck / game_duel next to it, by the program's name
        ext = "dylib" if sys.platform == "darwin" else "so"
        # module="none": the old single executable (make -C src/port static), which has the game linked in and takes no -m
        self.module = module or os.environ.get("PENTAMOOR_MODULE") or os.path.join(os.path.dirname(self.exe), "game_%s.%s" % (os.path.basename(program).split(".")[0].lower(), ext))
        self.extra_env = extra_env or {}
        self.overlay_seed = overlay_seed          # a folder copied to be the run's overlay (saves, settings); None or "" starts with an empty one (Spells of the Ancients has no seed)
        self.args = list(args)
        self.proc = None
        self.log_path = os.path.join(self.workdir, "game.log")
        self.ctl_path = os.path.join(self.workdir, "ctl")
        self._ctl = None
        self.started = 0.0

    # ---- process ------------------------------------------------------------------------------------------------------
    def start(self):
        overlay = os.path.join(self.workdir, "overlay")
        shutil.rmtree(overlay, ignore_errors=True)
        if self.overlay_seed:
            shutil.copytree(os.path.join(self.repo, self.overlay_seed), overlay)
        else:
            os.makedirs(overlay)
        if os.path.exists(self.ctl_path):
            os.unlink(self.ctl_path)
        os.mkfifo(self.ctl_path)
        env = dict(os.environ, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy", PORT_CONTROL=self.ctl_path, PORT_OVERLAY=overlay,
                   PORT_STUB="1", PORT_RES=self.res)
        env.update(self.extra_env)
        for pair in os.environ.get("SOAK_ENV", "").split():      # SOAK_ENV="SDL_VIDEODRIVER=x11 DISPLAY=:80 PORT_STEAMDECK=1": the game's environment for a run on a real X server, a Deck's settings ...
            if "=" in pair:
                k, v = pair.split("=", 1)
                env[k] = v
        self._log = open(self.log_path, "wb")
        # start_new_session: our own process group, so nothing we do can reach anyone else's game
        self.proc = subprocess.Popen([self.exe] + ([] if self.module == "none" else ["-m", self.module]) + [self.program] + self.args, cwd=self.repo, env=env, stdout=self._log, stderr=subprocess.STDOUT,
                                     stdin=subprocess.DEVNULL, start_new_session=True)
        self.started = time.time()
        self._ctl = os.open(self.ctl_path, os.O_RDWR | os.O_NONBLOCK)
        return self.proc.pid

    def _stop_group(self, sig):
        """Signal the group this game was started in (start_new_session: its own, which holds only this game and what it started)."""
        try:
            os.killpg(self.proc.pid, sig)
        except OSError:
            pass

    def attach(self, pid):
        """Use a game that is already running (started earlier with the same workdir) -- for driving one by hand from separate commands."""
        self.attached_pid = pid
        self._ctl = os.open(self.ctl_path, os.O_RDWR | os.O_NONBLOCK)

    @property
    def pid(self):
        return self.proc.pid if self.proc else getattr(self, "attached_pid", None)

    def alive(self):
        if self.proc is None:
            pid = getattr(self, "attached_pid", None)
            if pid is None:
                return False
            try:
                os.kill(pid, 0)
                return True
            except OSError:
                return False
        return self.proc.poll() is None

    def exit_status(self):
        return self.proc.poll() if self.proc else None

    def stop(self):
        if self.proc:
            self._stop_group(signal.SIGTERM)             # the programs it started (Spells of the Ancients: the shell starts Shandalar, which starts FaceMaker and the shell again) are in its group
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self._stop_group(signal.SIGKILL)
                self.proc.kill()
                self.proc.wait()
        if self._ctl is not None:
            os.close(self._ctl)
            self._ctl = None
        if getattr(self, "_log", None):
            self._log.close()

    # ---- commands -----------------------------------------------------------------------------------------------------
    def cmd(self, line):
        if self._ctl is None:
            return
        try:
            os.write(self._ctl, (line + "\n").encode())
        except OSError:
            pass

    def click(self, x, y):
        self.cmd("click %d %d" % (x, y))

    def rclick(self, x, y, hold=0.25):
        self.cmd("rdown %d %d" % (x, y))
        time.sleep(hold)
        self.cmd("rup %d %d" % (x, y))

    def key(self, name):
        self.cmd("key " + name)

    # ---- reading back -------------------------------------------------------------------------------------------------
    def log_size(self):
        try:
            return os.path.getsize(self.log_path)
        except OSError:
            return 0

    def read_log(self, offset):
        with open(self.log_path, "rb") as f:
            f.seek(offset)
            return f.read().decode("latin-1")

    def windows(self, timeout=8.0):
        """Ask for a window dump and parse it; None if the program did not answer (it is hung or gone)."""
        off = self.log_size()
        self.cmd("windows")
        end = time.time() + timeout
        while time.time() < end:
            text = self.read_log(off)
            i = text.find("  queue (")
            if i >= 0 and text.find("\n", i) >= 0:
                wins, items = [], []
                for line in text[:i].split("\n"):
                    m = WIN_RE.match(line)
                    if m:
                        wins.append(Win(m))
                    m = ITEM_RE.match(line)
                    if m:
                        items.append(Item(m))
                return Tree(wins, text[i:].split("\n")[0], items)
            if not self.alive():
                return None
            time.sleep(0.1)
        return None

    def shot(self, path):
        """Screenshot to a PNG (needs PIL; else a PPM next to it); returns the path of the file made, or None."""
        ppm = os.path.join(self.workdir, "shot.ppm")
        if os.path.exists(ppm):
            os.unlink(ppm)
        self.cmd("shot " + ppm)
        end = time.time() + 8
        while time.time() < end:
            if os.path.exists(ppm) and os.path.getsize(ppm) > 100:
                time.sleep(0.4)
                break
            time.sleep(0.2)
        else:
            return None
        try:
            from PIL import Image
            Image.open(ppm).save(path)
            return path
        except Exception:
            shutil.copy(ppm, path.replace(".png", ".ppm"))
            return path.replace(".png", ".ppm")

    def peek(self, addr, n=1):
        off = self.log_size()
        self.cmd("peek 0x%x %d" % (addr, n))
        end = time.time() + 4
        while time.time() < end:
            vals = re.findall(r"peek 0x[0-9a-f]+ = (\d+)", self.read_log(off))
            if len(vals) >= n:
                return [int(v) for v in vals[:n]]
            time.sleep(0.1)
        return None

    def poke(self, addr, val, nbytes=4):
        self.cmd("poke 0x%x %d %d" % (addr, val, nbytes))

    def poke_many(self, pokes):
        """Several pokes in one write to the pipe, so that the program reads them together (the game's frame cannot run between them): [(addr, val), ...]."""
        self.cmd("\n".join("poke 0x%x %d 4" % (a, v) for a, v in pokes))

    def teleport_party(self, tx, ty):
        """Put the party on the middle of the world map's tile (tx, ty) the way the game's own teleports do (the function at 0x4e7f51 does it for a random tile and for a stored one,
        then calls 0x4c05ba): the position, and the map told to redraw itself whole. Poking only the position makes the next frame scroll the map's picture by the whole distance,
        and the game's scroll (0x4c06df: it copies the part that stays, width = the view's width minus the distance) has no case for a distance of more than the view's width: at 640x480
        a jump of 688 pixels made a copy of -48 bytes, which is the process's SIGSEGV (docs/notes/castle-dungeon-stats.md). Needs the map on screen."""
        self.poke_many([(0x52eff0, tx * 32 + 16), (0x52eff4, ty * 32 + 16), (0x641010, tx), (0x641014, ty),
                        (0x558dc8, 0xffffffff), (0x52d774, 0xffffffff), (0x52d778, 1),     # 0x4c05ba's first lines: the map's cache is stale
                        (0x641884, 0)])                                                    # ... and its last: "the map has not been drawn", so the next frame draws it all, no scroll

    # ---- a game controller (the `pad` steps of PORT_CONTROL; docs/notes/controller.md) --------------------------------------
    def pad(self, text):
        """`pad axis lx 0.5`, `pad stick l 1 0`, `pad button a down`, `pad press x`, ... (see front_sdl.c)."""
        self.cmd("pad " + text)

    def pad_press(self, name, hold=0.0):
        """A button pressed and let go (after `hold` seconds, if given)."""
        if hold:
            self.pad("button %s down" % name)
            time.sleep(hold)
            self.pad("button %s up" % name)
        else:
            self.pad("press " + name)

    def pad_pos(self, timeout=3.0):
        """(x, y, active, left_button_down) of the pad's cursor, in screen pixels; None if the program did not answer."""
        off = self.log_size()
        self.cmd("pad pos")
        end = time.time() + timeout
        while time.time() < end:
            m = re.search(r"  pad: (-?\d+) (-?\d+) active=(\d) left=(\d)", self.read_log(off))
            if m:
                return tuple(int(v) for v in m.groups())
            time.sleep(0.05)
        return None

    def pad_goto(self, tx, ty, tol=6, timeout=12.0):
        """Put the pad's cursor on (tx, ty) with the left stick, as a person does: full push far away, a gentle one near, the slow trigger for the last stretch."""
        end = time.time() + timeout
        slow = False
        while time.time() < end:
            p = self.pad_pos()
            if p is None:
                return None
            dx, dy = tx - p[0], ty - p[1]
            d = (dx * dx + dy * dy) ** 0.5
            if d <= tol:
                self.pad("stick l 0 0")
                if slow:
                    self.pad("axis lt 0")
                time.sleep(0.1)
                return self.pad_pos()
            if (d < 90) != slow:
                slow = d < 90
                self.pad("axis lt %d" % (1 if slow else 0))
            mag = 1.0 if d > 150 else 0.75 if d > 40 else 0.6
            self.pad("stick l %g %g" % (dx / d * mag, dy / d * mag))
            time.sleep(0.04)
        self.pad("stick l 0 0")
        return self.pad_pos()

    def pad_click(self, x, y, button="a"):
        """Walk the cursor to (x, y) and press a button there (a: left click, b: right click)."""
        p = self.pad_goto(x, y)
        self.pad_press(button)
        return p

    # ---- the D-pad's navigation (the `nav` and `hit` steps; docs/notes/controller-nav.md) -----------------------------------
    def hit(self, x, y, timeout=3.0):
        """The window a click at (x, y) would go to (the handle), or None."""
        off = self.log_size()
        self.cmd("hit %d %d" % (x, y))
        end = time.time() + timeout
        while time.time() < end:
            m = re.search(r"  hit \(-?\d+,-?\d+\) -> window 0x([0-9a-f]+)", self.read_log(off))
            if m:
                return int(m.group(1), 16)
            time.sleep(0.05)
        return None

    def nav_targets(self, timeout=4.0):
        """What the D-pad can move between now, as the program sees it: (mode, [Target]) or None. Each Target has zone, kind, id, x0, y0, x1, y1, scroll, label and a `cur` flag."""
        off = self.log_size()
        self.cmd("pad nav")
        end = time.time() + timeout
        while time.time() < end:
            text = self.read_log(off)
            m = re.search(r"  nav: mode (\w+), (\d+) targets, pointer \((-?\d+),(-?\d+)\) on (-?\d+)", text)
            if m and len(re.findall(r"^  target \d+ ", text, re.M)) >= int(m.group(2)):
                out = []
                for t in re.finditer(r"^  target (\d+) zone (-?\d+) kind (\d+) id 0x([0-9a-f]+) \((-?\d+),(-?\d+)\)-\((-?\d+),(-?\d+)\) scroll (\d+) '(.*)'$", text, re.M):
                    out.append(Target(int(t[1]), int(t[2]), int(t[3]), int(t[4], 16), int(t[5]), int(t[6]), int(t[7]), int(t[8]), int(t[9]), t[10], int(t[1]) == int(m.group(5))))
                return m.group(1), out
            time.sleep(0.05)
        return None

    def dpad(self, name, wait=0.6):
        """Press a D-pad direction (up, down, left, right) and return where the pad's cursor is afterwards (x, y), waiting for it to settle: the same place if there was nowhere to go."""
        p0 = self.pad_pos()
        self.pad_press(name)
        end = time.time() + wait
        p = p0
        while time.time() < end:
            time.sleep(0.05)
            p = self.pad_pos()
            if p is None:
                return None
            if p[:2] != p0[:2]:
                time.sleep(0.15)                      # it has moved: let the move reach the game
                return self.pad_pos()[:2]
        return p[:2]


class Target:
    __slots__ = ("index", "zone", "kind", "id", "x0", "y0", "x1", "y1", "scroll", "label", "cur")

    def __init__(self, index, zone, kind, id_, x0, y0, x1, y1, scroll, label, cur):
        self.index, self.zone, self.kind, self.id, self.x0, self.y0, self.x1, self.y1, self.scroll, self.label, self.cur = index, zone, kind, id_, x0, y0, x1, y1, scroll, label, cur

    def contains(self, x, y):
        return self.x0 <= x < self.x1 and self.y0 <= y < self.y1

    @property
    def center(self):
        return ((self.x0 + self.x1 - 1) // 2, (self.y0 + self.y1 - 1) // 2)

    def __repr__(self):
        return "<Target %d kind %d %r (%d,%d)-(%d,%d)>" % (self.index, self.kind, self.label, self.x0, self.y0, self.x1, self.y1)

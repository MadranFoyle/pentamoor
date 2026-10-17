#!/usr/bin/env python3
"""xe2e.py - the display feature (full screen, scaling modes, filters, window, display.cfg, the mouse mapping) on a real X server.

Needs a Linux box with Xvfb, ImageMagick's `import`, a C compiler, libX11 and libXtst, a built runtime and a game module, and the installed game (it plays the real title screen):

    XE2E_RUNTIME=src/port/build/pentamoor-run XE2E_MODULE=src/port/build/game_magic.so XE2E_EXE=sources/installed/Magic/Program/MAGIC.EXE python3 tools/display/xe2e.py [scenario ...]

What it does: starts Xvfb (its own display number, its own size), a minimal window manager (minwm.c: EWMH full screen, a free area, minimum sizes, no frames) and the game with its own overlay
and control pipe, then drives it like a person: real X key events and pointer clicks through XTest (xtool.c), window resizes and moves like a window manager would get them. It reads what
is on the screen (the whole X screen as an image) and what the game says (stderr: PORT_PAD_LOG lines for the mouse and keys that reach the game, `view` in the control pipe for the picture's
layout). The expected geometry is worked out here, apart from the C code, so a mistake in either shows up. Every process it starts is stopped by its own pid; it never signals any other.

Scenarios: default, fullscreen, modes, filters, resize, persist, pad, click. Without arguments all of them run. Exit status 1 if any check fails."""
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.environ.get("XE2E_WORK", os.path.join(os.path.expanduser("~"), "display", "x"))
RUNTIME = os.environ.get("XE2E_RUNTIME", "src/port/build/pentamoor-run")
MODULE = os.environ.get("XE2E_MODULE", "src/port/build/game_magic.so")
EXE = os.environ.get("XE2E_EXE", "sources/installed/Magic/Program/MAGIC.EXE")
SW, SH = 1024, 768                      # the game's screen
START_NEW_GAME = (528, 493)             # the middle of "Start New Game" on the title screen at 1024x768

failures = 0
checks = 0


def check(ok, what):
    global failures, checks
    checks += 1
    if not ok:
        failures += 1
    print(("PASS " if ok else "FAIL ") + what, flush=True)
    return ok


# ---- what the layout should be, worked out apart from the C code (display.c) ----
def layout(mode, ow, oh, sw=SW, sh=SH):
    """(x, y, w, h) of the picture in an ow x oh output"""
    if mode == "stretch":
        return (0, 0, ow, oh)
    f = min(ow / sw, oh / sh)
    k = int(f + 1e-9)
    if mode == "integer":
        s = k if k >= 1 else f
    else:
        s = k if (k >= 1 and k * 100 >= f * 90) else f
    w, h = int(sw * s + 0.5), int(sh * s + 0.5)
    w, h = min(w, ow), min(h, oh)
    return ((ow - w) // 2, (oh - h) // 2, w, h)


def initial_window(usable_w, usable_h, sw=SW, sh=SH):
    fit = min(usable_w * 0.9 / sw, usable_h * 0.9 / sh)
    k = int(fit + 1e-9)
    s = k if k >= 1 else max(fit, 0.25)
    return (int(sw * s + 0.5), int(sh * s + 0.5))


def read_ppm(data):
    parts = data.split(b"\n", 3)
    w, h = map(int, parts[1].split())
    return w, h, parts[3]


VIEW_RE = re.compile(r"display \(view\): (full screen|window), window (\d+)x(\d+) points, drawable (\d+)x(\d+) pixels \(([\d.]+) per point\), picture (\d+)x(\d+) at (-?\d+),(-?\d+) "
                     r"\(scale ([\d.]+) x ([\d.]+)(, whole numbers)?\), scale (\w+), filter (\w+)")


def parse_view(text):
    """the game's `view` line: {'window': (w,h) points, 'drawable': (w,h) pixels, 'dpi': pixels per point, 'pic': (w,h,x,y) in pixels, 'fs': bool, 'whole': bool, 'scale': str, 'filter': str}"""
    m = VIEW_RE.search(text)
    if not m:
        return None
    g = m.groups()
    return dict(fs=g[0] == "full screen", window=(int(g[1]), int(g[2])), drawable=(int(g[3]), int(g[4])), dpi=float(g[5]), pic=(int(g[6]), int(g[7]), int(g[8]), int(g[9])),
                whole=bool(g[12]), scale=g[13], filter=g[14])


# ---- the processes ----
class Setup:
    """Xvfb, the window manager, the game"""

    def __init__(self, name, screen=(1280, 800), panel=40, env=None, overlay=None, wait_title=True):
        self.name = name
        self.screen = screen
        self.dir = os.path.join(WORK, name)
        if overlay is None:
            shutil.rmtree(self.dir, ignore_errors=True)
        os.makedirs(self.dir, exist_ok=True)
        self.overlay = overlay or os.path.join(self.dir, "ov")
        self.procs = []
        self.disp = self.pick_display()
        self.env = dict(os.environ, DISPLAY=self.disp)
        self.xtool = os.path.join(WORK, "xtool")
        self.log_path = os.path.join(self.dir, "game.log")
        self.ctl_path = os.path.join(self.dir, "ctl")
        self.ctl = -1
        try:
            self.start_x(panel)
            self.start_game(env or {}, wait_title)
        except BaseException:
            self.stop()                       # no stray Xvfb or game when something is wrong
            raise

    def pick_display(self):
        for n in range(180, 200):
            if not os.path.exists("/tmp/.X11-unix/X%d" % n) and not os.path.exists("/tmp/.X%d-lock" % n):
                return ":%d" % n
        raise RuntimeError("no free X display number")

    def spawn(self, argv, **kw):
        p = subprocess.Popen(argv, **kw)
        self.procs.append(p)
        return p

    def start_x(self, panel):
        w, h = self.screen
        self.spawn(["Xvfb", self.disp, "-screen", "0", "%dx%dx24" % (w, h), "-nolisten", "tcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            time.sleep(0.1)
            if os.path.exists("/tmp/.X11-unix/X%s" % self.disp[1:]):
                break
        self.wm_log = open(os.path.join(self.dir, "wm.log"), "w")
        self.spawn([os.path.join(WORK, "minwm"), str(panel)], env=self.env, stdout=self.wm_log, stderr=subprocess.STDOUT)
        time.sleep(0.5)

    def start_game(self, env, wait_title=True):
        if os.path.exists(self.ctl_path):
            os.unlink(self.ctl_path)
        os.mkfifo(self.ctl_path)
        e = dict(self.env, SDL_AUDIODRIVER="dummy", SDL_VIDEODRIVER="x11", PORT_OVERLAY=self.overlay, PORT_CONTROL=self.ctl_path, PORT_PAD_LOG="stderr", PORT_MUTE="1")
        for k in ("PORT_FULLSCREEN", "PORT_SCALE", "PORT_FILTER", "PORT_WINDOW"):
            e.pop(k, None)
        e.update(env)
        self.log = open(self.log_path, "w")
        self.game = self.spawn([RUNTIME, "-m", MODULE, EXE], env=e, stdout=self.log, stderr=subprocess.STDOUT)
        self.ctl = os.open(self.ctl_path, os.O_RDWR | os.O_NONBLOCK)
        self.win = None
        for _ in range(100):
            time.sleep(0.2)
            r = subprocess.run([self.xtool, "find", "Pentamoor"], env=self.env, capture_output=True, text=True)
            if r.returncode == 0:
                self.win = r.stdout.strip()
                break
        if wait_title:
            self.wait_title()

    def stop_game(self, sig="TERM"):
        """end the game by its own pid (TERM is what its handler saves display.cfg on) and wait"""
        self.game.send_signal(15 if sig == "TERM" else 9)
        try:
            self.game.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.game.kill()
        os.close(self.ctl)
        self.ctl = -1

    def stop(self):
        for p in reversed(self.procs):
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
        if self.ctl >= 0:
            os.close(self.ctl)
            self.ctl = -1

    # ---- the game ----
    def say(self, line):
        os.write(self.ctl, (line + "\n").encode())

    def log_text(self):
        with open(self.log_path, "r", errors="replace") as f:
            return f.read()

    def shot(self, name="shot.ppm"):
        """the game's own screen (its size, whatever the window is)"""
        path = os.path.join(self.dir, name)
        if os.path.exists(path):
            os.unlink(path)
        self.say("shot " + path)
        for _ in range(50):
            time.sleep(0.1)
            if os.path.exists(path):
                time.sleep(0.2)
                break
        with open(path, "rb") as f:
            return read_ppm(f.read())

    def wait_title(self):
        for _ in range(120):
            time.sleep(0.5)
            try:
                w, h, d = self.shot("probe.ppm")
            except (OSError, ValueError):
                continue
            if sum(d[::4001]) > 20 * len(d[::4001]):
                time.sleep(1.0)
                return True
        return False

    def view(self):
        """what the game says about the window and the picture (parse_view)"""
        mark = len(self.log_text())
        self.say("view")
        for _ in range(30):
            time.sleep(0.1)
            v = parse_view(self.log_text()[mark:])
            if v:
                return v
        return None

    # ---- the X server ----
    def xt(self, *args):
        return subprocess.run([self.xtool] + [str(a) for a in args], env=self.env, capture_output=True, text=True)

    def geom(self):
        r = self.xt("geom", self.win)
        x, y, w, h, fs = map(int, r.stdout.split())
        return dict(x=x, y=y, w=w, h=h, fs=bool(fs))

    def key(self, name):
        self.xt("key", name)
        time.sleep(0.5)

    def click(self, x, y, button=1, hold=100):
        self.xt("click", x, y, button, hold)

    def xshot(self):
        r = subprocess.run(["import", "-display", self.disp, "-window", "root", "-depth", "8", "ppm:-"], capture_output=True)
        return read_ppm(r.stdout)

    def click_logical(self, lx, ly):
        """click where the game's pixel (lx, ly) is drawn, worked out from the window's place and the layout of the picture in it"""
        g = self.geom()
        vx, vy, vw, vh = layout(self.mode(), g["w"], g["h"])
        x = g["x"] + vx + (lx + 0.5) * vw / SW
        y = g["y"] + vy + (ly + 0.5) * vh / SH
        mark = len(self.log_text())
        self.click(int(x), int(y))
        t = self.log_text()[mark:]
        m = re.search(r"mouse left down at \((-?\d+),(-?\d+)\)", t)
        return (int(m.group(1)), int(m.group(2))) if m else None

    def mode(self):
        v = self.view()
        return v["scale"] if v else "fit"


def picture_matches(s, mode, filt, tol=None):
    """compare the X screen with the game's own screen drawn as the layout says it should be: returns (mean abs error over a sample, share of the bars that are black)"""
    gw, gh, game = s.shot("cmp.ppm")
    xw, xh, xs = s.xshot()
    g = s.geom()
    vx, vy, vw, vh = layout(mode, g["w"], g["h"])
    ox, oy = g["x"] + vx, g["y"] + vy
    err = n = 0
    for j in range(0, vh, 5):
        gy = min(SH - 1, int((j + 0.5) * SH / vh))
        if oy + j >= xh:
            break
        for i in range(0, vw, 5):
            gx = min(SW - 1, int((i + 0.5) * SW / vw))
            if ox + i >= xw:
                break
            px = ((oy + j) * xw + ox + i) * 3
            q = (gy * SW + gx) * 3
            err += abs(xs[px] - game[q]) + abs(xs[px + 1] - game[q + 1]) + abs(xs[px + 2] - game[q + 2])
            n += 3
    # the bars inside the window (and outside the picture) are black
    bars = black = 0
    for j in range(g["y"], min(g["y"] + g["h"], xh), 7):
        for i in range(g["x"], min(g["x"] + g["w"], xw), 7):
            if i < ox or i >= ox + vw or j < oy or j >= oy + vh:
                bars += 1
                p = (j * xw + i) * 3
                black += xs[p] == 0 and xs[p + 1] == 0 and xs[p + 2] == 0
    return err / max(n, 1), (black / bars if bars else 1.0)


def clicks_land(s, label):
    """clicks at the corners and the middle land on the game's pixel that is drawn there"""
    g = s.geom()
    if not g["fs"] and (g["x"] + g["w"] > s.screen[0] or g["y"] + g["h"] > s.screen[1]):
        s.xt("moveto", s.win, 0, 0)                   # a pointer cannot go beyond the screen
        time.sleep(0.4)
    ok = True
    for lx, ly in ((6, 6), (1017, 6), (6, 761), (1017, 761), (512, 384), START_NEW_GAME):
        if (lx, ly) == START_NEW_GAME:
            break
        got = s.click_logical(lx, ly)
        good = got is not None and abs(got[0] - lx) <= 1 and abs(got[1] - ly) <= 1
        ok &= good
        if not good:
            print("   click at game pixel (%d,%d) reached %r" % (lx, ly, got))
    check(ok, label + ": clicks land on the pixel drawn under them")


# ---- scenarios ----
def scenario_default():
    """the start size, the title, the minimum size, shot, the window's own look"""
    for screen, panel in (((1280, 800), 40), ((1920, 1080), 40), ((2560, 1440), 40)):
        s = Setup("default_%dx%d" % screen, screen, panel)
        try:
            exp = initial_window(screen[0], screen[1] - panel)
            g = s.geom()
            check((g["w"], g["h"]) == exp and not g["fs"], "%dx%d display, free area %dx%d: starts as a %dx%d window (got %dx%d)" % (screen + (screen[0], screen[1] - panel) + exp + (g["w"], g["h"])))
            check(g["x"] + g["w"] <= screen[0] and g["y"] + g["h"] <= screen[1], "  the window is on the display")
            r = subprocess.run(["xprop", "-display", s.disp, "-id", s.win, "_NET_WM_NAME"], capture_output=True, text=True).stdout
            check('"Pentamoor"' in r, "  window title is Pentamoor (%s)" % r.strip())
            v = s.view()
            check(v and v["pic"][:2] == layout("fit", g["w"], g["h"])[2:] and v["window"] == (g["w"], g["h"]), "  the game and the layout agree: %r" % (v and v["pic"],))
            err, bars = picture_matches(s, "fit", v["filter"])
            check(err < 6.0 and bars > 0.999, "  the X screen shows the game's picture there (mean error %.2f, bars black %.3f)" % (err, bars))
            w, h, _ = s.shot()
            check((w, h) == (SW, SH), "  shot is %dx%d whatever the window is" % (w, h))
            clicks_land(s, "  fit")
            mw, mh = s.xt("resize", s.win, 200, 150), None
            time.sleep(0.4)
            g2 = s.geom()
            check(g2["w"] >= min(SW, exp[0]) and g2["h"] >= min(SH, exp[1]), "  cannot be made smaller than the picture (or than it started, on a small display): %dx%d" % (g2["w"], g2["h"]))
        finally:
            s.stop()


def scenario_fullscreen():
    """F11 and Alt+Enter toggle full screen and come back; the keys do not reach the game"""
    s = Setup("fullscreen", (1280, 800), 40)
    try:
        g0 = s.geom()
        s.xt("moveto", s.win, 60, 20)
        time.sleep(0.5)
        g0 = s.geom()
        mark = len(s.log_text())
        s.key("F11")
        g = s.geom()
        check(g["fs"] and (g["w"], g["h"]) == (1280, 800), "F11: full screen, the display's size (%r)" % (g,))
        v = s.view()
        check(v["fs"] and v["pic"] == (1024, 768, 128, 16) if v else False, "  1280x800: the picture is 1024x768 at 128,16 (whole number): %r" % (v and v["pic"],))
        err, bars = picture_matches(s, "fit", "sharp")
        check(err < 3.0 and bars > 0.999, "  the X screen shows it there (error %.2f, bars %.3f)" % (err, bars))
        got = s.click_logical(*START_NEW_GAME) if False else None
        clicks_land(s, "  full screen")
        s.key("F11")
        g2 = s.geom()
        check(not g2["fs"] and (g2["w"], g2["h"]) == (g0["w"], g0["h"]) and (g2["x"], g2["y"]) == (g0["x"], g0["y"]), "F11 again: back to the window as it was (%r -> %r)" % (g0, g2))
        s.key("alt+Return")
        g = s.geom()
        check(g["fs"], "Alt+Enter: full screen")
        s.key("alt+Return")
        g2 = s.geom()
        check(not g2["fs"] and (g2["w"], g2["h"]) == (g0["w"], g0["h"]), "Alt+Enter again: back (%r)" % (g2,))
        t = s.log_text()[mark:]
        delivered = re.findall(r"key vk (0x[0-9a-f]+)", t)
        check("0x7a" not in delivered and "0xd" not in delivered and "0x12" not in delivered, "the keys of the display did not reach the game (it got: %s)" % ", ".join(delivered) if delivered else "the keys of the display did not reach the game (nothing reached it)")
        s.key("Return")
        t = s.log_text()[mark:]
        check("0xd" in re.findall(r"key vk (0x[0-9a-f]+)", t), "a plain Enter still does reach the game")
        s.key("alt+F11")
        t = s.log_text()[mark:]
        g3 = s.geom()
        check(not g3["fs"] and "0x7a" in re.findall(r"key vk (0x[0-9a-f]+)", t), "Alt+F11 is not ours: it reaches the game, the window stays")
        # moved while windowed, the place is remembered across full screen
        s.xt("moveto", s.win, 100, 50)
        time.sleep(0.5)
        gm = s.geom()
        s.key("F11")
        s.key("F11")
        g4 = s.geom()
        check((g4["x"], g4["y"], g4["w"], g4["h"]) == (gm["x"], gm["y"], gm["w"], gm["h"]), "a moved window comes back to where it was moved (%r -> %r)" % (gm, g4))
    finally:
        s.stop()


def scenario_modes():
    """Ctrl+F11 cycles the scaling, Shift+F11 the filter: layout, picture on the X screen, clicks, the message"""
    s = Setup("modes", (1920, 1080), 0, env={"PORT_FULLSCREEN": "1"})
    try:
        screen = (1920, 1080)
        want = {"fit": layout("fit", *screen), "integer": layout("integer", *screen), "stretch": layout("stretch", *screen)}
        v = s.view()
        check(v and v["fs"] and v["scale"] == "fit" and v["filter"] == "sharp" and v["pic"] == (want["fit"][2], want["fit"][3], want["fit"][0], want["fit"][1]), "starts full screen, fit, sharp: %r" % (v and v["pic"],))
        for mode in ("fit", "integer", "stretch", "fit"):
            if s.mode() != mode:
                s.key("ctrl+F11")
            v = s.view()
            exp = want[mode]
            check(v["scale"] == mode and v["pic"] == (exp[2], exp[3], exp[0], exp[1]), "Ctrl+F11 -> %s: picture %dx%d at %d,%d (got %r)" % ((mode,) + exp[2:] + exp[:2] + (v["pic"],)))
            for filt in ("sharp", "nearest", "linear"):
                while v["filter"] != filt:
                    s.key("shift+F11")
                    v = s.view()
                err, bars = picture_matches(s, mode, filt)
                whole = want[mode][2] % SW == 0 and want[mode][3] % SH == 0
                limit = 0.01 if filt != "linear" and whole else 8.0          # a whole-number scale is exact for nearest and sharp
                check(err < limit and bars > 0.999, "  %s/%s: the X screen matches the game's picture (error %.2f, limit %.2f, bars black %.3f)" % (mode, filt, err, limit, bars))
                if filt == "sharp":
                    clicks_land(s, "  %s/%s" % (mode, filt))
            while v["filter"] != "sharp":
                s.key("shift+F11")
                v = s.view()
        # the one-line message
        s.say("move 5 5")
        s.key("shift+F11")
        time.sleep(0.5)
        w, h, d = s.shot("notice.ppm")
        v = s.view()
        edge = (200, 180, 100)
        found = any(tuple(d[(12 * w + x) * 3:(12 * w + x) * 3 + 3]) == edge for x in range(w)) or any(tuple(d[(10 * w + x) * 3:(10 * w + x) * 3 + 3]) == edge for x in range(w))
        check(found, "the message box is on the game's screen right after the key (Scaling: %s, filter: %s)" % (v["scale"], v["filter"]))
        time.sleep(2.0)
        w, h, d = s.shot("notice2.ppm")
        found = any(tuple(d[(10 * w + x) * 3:(10 * w + x) * 3 + 3]) == edge for x in range(w))
        check(not found, "... and gone after 2 s")
        # nearest at a fractional scale draws only colours the game made (no blending); linear blends
        while s.view()["scale"] != "fit":
            s.key("ctrl+F11")
        for filt, expect_pure in (("nearest", True), ("linear", False)):
            while s.view()["filter"] != filt:
                s.key("shift+F11")
            time.sleep(1.0)
            gw, gh, game = s.shot("g.ppm")
            xw, xh, xs = s.xshot()
            colours = set(game[i:i + 3] for i in range(0, len(game), 3))
            vx, vy, vw, vh = want["fit"]
            pure = total = 0
            for j in range(vy + 2, vy + vh - 2, 3):
                for i in range(vx + 2, vx + vw - 2, 3):
                    total += 1
                    pure += xs[(j * xw + i) * 3:(j * xw + i) * 3 + 3] in colours
            share = pure / total
            check((share > 0.999) if expect_pure else (share < 0.97), "1.41x %s: %.1f%% of the pixels are colours the game drew" % (filt, 100 * share))
    finally:
        s.stop()


def scenario_resize():
    """a resized window gets the picture re-fitted; the mouse follows"""
    s = Setup("resize", (1920, 1080), 40)
    try:
        for w, h in ((1400, 900), (1100, 700), (1024, 1000), (1700, 760), (1030, 770)):
            s.xt("resize", s.win, w, h)
            time.sleep(0.8)
            g = s.geom()
            v = s.view()
            exp = layout("fit", g["w"], g["h"])
            check(v and v["window"] == (g["w"], g["h"]) and v["pic"] == (exp[2], exp[3], exp[0], exp[1]), "resized to %dx%d (window %dx%d): picture %r, expected %r" % (w, h, g["w"], g["h"], v and v["pic"], exp))
            err, bars = picture_matches(s, "fit", v["filter"])
            check(err < 8.0 and bars > 0.999, "  the X screen shows it (error %.2f, bars %.3f)" % (err, bars))
            clicks_land(s, "  %dx%d" % (g["w"], g["h"]))
        s.xt("resize", s.win, 100, 100)
        time.sleep(0.6)
        g = s.geom()
        check((g["w"], g["h"]) == (SW, SH), "a window dragged tiny stops at the picture's size: %dx%d" % (g["w"], g["h"]))
        # stretch in a resized window: mouse follows each axis
        s.xt("resize", s.win, 1500, 800)
        time.sleep(0.6)
        while s.view()["scale"] != "stretch":
            s.key("ctrl+F11")
        g = s.geom()
        v = s.view()
        check(v["pic"] == (g["w"], g["h"], 0, 0), "stretch fills the 1500x800 window: %r" % (v["pic"],))
        clicks_land(s, "  stretch 1500x800")
    finally:
        s.stop()


def read_cfg(path):
    try:
        with open(path) as f:
            return dict(l.strip().split("=", 1) for l in f if "=" in l and not l.lstrip().startswith("#"))
    except OSError:
        return None


def scenario_persist():
    """display.cfg: written in the overlay, read at the next start, overridden by the environment, survives junk"""
    s = Setup("persist", (1920, 1080), 40)
    try:
        cfg = os.path.join(s.overlay, "display.cfg")
        s.xt("resize", s.win, 1300, 800)
        time.sleep(0.5)
        s.xt("moveto", s.win, 100, 60)
        time.sleep(0.5)
        s.key("ctrl+F11")
        s.key("shift+F11")
        time.sleep(2.0)
        c = read_cfg(cfg)
        check(c is not None, "display.cfg is written in the overlay folder within seconds of a change, before the game ends: %r" % c)
        check(c and c.get("scale") == "integer" and c.get("filter") == "nearest" and c.get("window") == "1300x800" and c.get("position") == "100,60", "  it holds the scale, the filter, the window and its place")
        s.key("F11")
        time.sleep(2.0)
        s.stop_game()
        c = read_cfg(cfg)
        check(c and c.get("fullscreen") == "1" and c.get("window") == "1300x800" and c.get("position") == "100,60", "  after quitting in full screen: fullscreen=1 and the window's own size and place are kept: %r" % c)
        check(not os.path.exists(cfg + ".tmp"), "  no temporary file is left")
        stray = [n for n in os.listdir(s.overlay) if n != "display.cfg"] if os.path.isdir(s.overlay) else []
        # next run, same overlay, nothing in the environment
        s.start_game({})
        v = s.view()
        check(v and v["fs"] and v["scale"] == "integer" and v["filter"] == "nearest", "the next start is full screen, integer, nearest again: %r" % ((v and (v["fs"], v["scale"], v["filter"])),))
        s.key("F11")
        g = s.geom()
        check((g["w"], g["h"], g["x"], g["y"]) == (1300, 800, 100, 60) and not g["fs"], "  and leaving full screen goes to the saved window: %r" % (g,))
        s.stop_game()
        # the environment wins and is not written back
        before = read_cfg(cfg)
        s.start_game({"PORT_FULLSCREEN": "0", "PORT_SCALE": "stretch", "PORT_FILTER": "linear", "PORT_WINDOW": "900x700"})
        v = s.view()
        g = s.geom()
        check(v and not v["fs"] and v["scale"] == "stretch" and v["filter"] == "linear" and (g["w"], g["h"]) == (900, 700), "environment over the file: window 900x700, stretch, linear: %r %r" % ((v and (v["fs"], v["scale"], v["filter"])), (g["w"], g["h"])))
        s.stop_game()
        after = read_cfg(cfg)
        same = all(after.get(k) == before.get(k) for k in ("fullscreen", "scale", "filter", "window")) if after else False
        check(same, "  the file keeps what it had (only the window's place may differ): %r -> %r" % (before, after))
        # junk, then an old file with unknown lines
        for text in ("\x00\x01\xff\xfe junk \n\n=\n===\nscale\n", "", "version=0\nzoom=3\nscale=sideways\nwindow=5x5\nfullscreen=perhaps\n"):
            with open(cfg, "w", errors="replace") as f:
                f.write(text)
            s.start_game({})
            v = s.view()
            g = s.geom()
            exp = initial_window(1920, 1080 - 40)
            check(v and not v["fs"] and v["scale"] == "fit" and v["filter"] == "sharp" and (g["w"], g["h"]) == exp, "a corrupt or outdated file (%r...): the defaults, %dx%d window: %r" % (text[:12], exp[0], exp[1], v and (v["scale"], v["filter"])))
            s.stop_game()
        # a window saved on a display that is bigger than this one is made to fit; one placed off the display is put back
        with open(cfg, "w") as f:
            f.write("window=5000x4000\nposition=9000,9000\n")
        s.start_game({})
        g = s.geom()
        check(g["w"] <= 1920 and g["h"] <= 1040 and g["x"] < 1920 and g["y"] < 1080, "a saved window larger than the display, placed off it: made to fit and brought back (%r)" % (g,))
        s.stop_game()
        check(not os.path.exists(os.path.join(WORK, "persist", "display.cfg")), "nothing written outside the overlay (no display.cfg beside the work folder)")
    finally:
        s.stop()


def scenario_pad():
    """the two sticks pressed in for a second toggle full screen; one stick, or a short press, does not"""
    s = Setup("pad", (1280, 800), 40)
    try:
        s.say("pad button l3 down")
        time.sleep(1.4)
        s.say("pad button l3 up")
        time.sleep(0.4)
        check(not s.geom()["fs"], "L3 alone, held 1.4 s: nothing")
        s.say("pad button l3 down")
        s.say("pad button r3 down")
        time.sleep(0.5)
        check(not s.geom()["fs"], "both sticks for 0.5 s: not yet")
        s.say("pad button l3 up")
        s.say("pad button r3 up")
        time.sleep(0.3)
        check(not s.geom()["fs"], "... and let go: nothing")
        s.say("pad button l3 down")
        s.say("pad button r3 down")
        time.sleep(1.5)
        check(s.geom()["fs"], "both sticks for 1.5 s: full screen")
        time.sleep(1.5)
        check(s.geom()["fs"], "... once, not again while they stay down")
        s.say("pad button l3 up")
        s.say("pad button r3 up")
        time.sleep(0.4)
        s.say("pad button l3 down")
        s.say("pad button r3 down")
        time.sleep(1.5)
        check(not s.geom()["fs"], "held again: back to the window")
        s.say("pad button l3 up")
        s.say("pad button r3 up")
    finally:
        s.stop()


def scenario_click():
    """a click on the drawn "Start New Game" opens the new game screen at every scaling mode, windowed and full screen"""
    for label, env, screen in (("windowed fit", {}, (1280, 800)), ("full screen fit 1920x1080", {"PORT_FULLSCREEN": "1"}, (1920, 1080)),
                               ("full screen integer", {"PORT_FULLSCREEN": "1", "PORT_SCALE": "integer"}, (1920, 1080)),
                               ("full screen stretch", {"PORT_FULLSCREEN": "1", "PORT_SCALE": "stretch"}, (1920, 1080)),
                               ("windowed stretch 1200x700", {"PORT_SCALE": "stretch", "PORT_WINDOW": "1200x700"}, (1920, 1080)),
                               ("full screen nearest on 4K", {"PORT_FULLSCREEN": "1", "PORT_FILTER": "nearest"}, (3840, 2160))):
        s = Setup("click_" + label.replace(" ", "_"), screen, 40, env=env)
        try:
            _, _, before = s.shot("before.ppm")
            got = s.click_logical(*START_NEW_GAME)
            time.sleep(3.0)
            _, _, after = s.shot("after.ppm")
            diff = sum(abs(a - b) for a, b in zip(before[::97], after[::97])) / len(before[::97])
            check(got is not None and abs(got[0] - START_NEW_GAME[0]) <= 1 and abs(got[1] - START_NEW_GAME[1]) <= 1 and diff > 5.0,
                  "%s: a click on the drawn Start New Game reached the game at %r and opened the new game screen (screen changed by %.1f)" % (label, got, diff))
        finally:
            s.stop()


SCENARIOS = {"default": scenario_default, "fullscreen": scenario_fullscreen, "modes": scenario_modes, "resize": scenario_resize, "persist": scenario_persist, "pad": scenario_pad,
             "click": scenario_click}


def build_tools():
    os.makedirs(WORK, exist_ok=True)
    for name, libs in (("xtool", ["-lX11", "-lXtst"]), ("minwm", ["-lX11"])):
        subprocess.run(["cc", "-O1", "-o", os.path.join(WORK, name), os.path.join(HERE, name + ".c")] + libs, check=True)


def main(argv):
    global RUNTIME, MODULE, EXE
    RUNTIME, MODULE, EXE = (os.path.abspath(p) for p in (RUNTIME, MODULE, EXE))
    build_tools()
    names = argv or list(SCENARIOS)
    for n in names:
        print("== %s" % n, flush=True)
        SCENARIOS[n]()
    print("xe2e: %d checks, %d failed" % (checks, failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

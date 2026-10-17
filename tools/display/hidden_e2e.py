#!/usr/bin/env python3
"""hidden_e2e.py - the picture, the filters and the pointer mapping in a REAL window of the platform's own video driver that is never shown (PORT_HIDDEN=1).

For machines where there is no X server to drive and a window on the desktop would be in the way: a Mac (Cocoa and Metal, and a Retina drawable when the display is one), Windows, a Linux desktop. The window
is made, sized and drawn to like any other, with SDL_WINDOW_ALLOW_HIGHDPI, and the game's `winshot` command reads back what the renderer drew into it at the size of its drawable in pixels; `wclick` sends a click in WINDOW
coordinates (points), the way a real mouse event arrives, through the display's own mapping (display_to_screen). Keys go through the same event queue as real ones. Nothing is shown and nothing is typed on the machine.
It cannot test full screen, a window manager's resizing or real pointer hardware (tools/display/xe2e.py does, on X11).

    XE2E_RUNTIME=src/port/build/pentamoor-run XE2E_MODULE=src/port/build/game_magic.dylib XE2E_EXE=sources/installed/Magic/Program/MAGIC.EXE python3 tools/display/hidden_e2e.py

The first line it prints says what the display is (points, pixels, the factor between them); on a Retina Mac the factor is 2."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xe2e
from xe2e import SH, SW, check, layout, parse_view, read_ppm

WORK = os.environ.get("HIDDEN_WORK", os.path.join(tempfile.gettempdir(), "pentamoor_hidden"))


class Hidden:
    def __init__(self, name, env=None):
        self.dir = os.path.join(WORK, name)
        shutil.rmtree(self.dir, ignore_errors=True)
        os.makedirs(self.dir)
        self.ctl_path = os.path.join(self.dir, "ctl")
        os.mkfifo(self.ctl_path)
        self.log_path = os.path.join(self.dir, "game.log")
        e = dict(os.environ, SDL_AUDIODRIVER="dummy", PORT_HIDDEN="1", PORT_OVERLAY=os.path.join(self.dir, "ov"), PORT_CONTROL=self.ctl_path, PORT_PAD_LOG="stderr", PORT_MUTE="1")
        for k in ("PORT_FULLSCREEN", "PORT_SCALE", "PORT_FILTER", "PORT_WINDOW", "SDL_VIDEODRIVER"):
            e.pop(k, None)
        e.update(env or {})
        self.log = open(self.log_path, "w")
        self.p = subprocess.Popen([xe2e.RUNTIME, "-m", xe2e.MODULE, xe2e.EXE], env=e, stdout=self.log, stderr=subprocess.STDOUT)
        self.ctl = os.open(self.ctl_path, os.O_RDWR | os.O_NONBLOCK)
        try:
            self.wait_title()
        except BaseException:
            self.stop()
            raise

    def stop(self):
        if self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.p.kill()
        if self.ctl >= 0:
            os.close(self.ctl)
            self.ctl = -1

    def say(self, line):
        os.write(self.ctl, (line + "\n").encode())

    def log_text(self):
        with open(self.log_path, "r", errors="replace") as f:
            return f.read()

    def _image(self, cmd, name):
        path = os.path.join(self.dir, name)
        if os.path.exists(path):
            os.unlink(path)
        self.say("%s %s" % (cmd, path))
        last = -1
        for _ in range(100):
            time.sleep(0.1)
            if os.path.exists(path):
                size = os.path.getsize(path)
                if size == last and size > 0:
                    break
                last = size
        with open(path, "rb") as f:
            return read_ppm(f.read())

    def shot(self, name="shot.ppm"):
        return self._image("shot", name)

    def winshot(self, name="win.ppm"):
        return self._image("winshot", name)

    def wait_title(self):
        for _ in range(120):
            time.sleep(0.5)
            if self.p.poll() is not None:
                raise RuntimeError("the game ended: " + self.log_text()[-500:])
            try:
                w, h, d = self.shot("probe.ppm")
            except (OSError, ValueError):
                continue
            if sum(d[::4001]) > 20 * len(d[::4001]):
                time.sleep(1.0)
                return
        raise RuntimeError("no title screen")

    def view(self):
        mark = len(self.log_text())
        self.say("view")
        for _ in range(30):
            time.sleep(0.1)
            v = parse_view(self.log_text()[mark:])
            if v:
                return v
        return None

    def key(self, name):
        self.say("key " + name)
        time.sleep(0.4)

    def wclick(self, x, y):
        mark = len(self.log_text())
        self.say("wclick %d %d" % (x, y))
        for _ in range(30):
            time.sleep(0.1)
            m = re.search(r"mouse left down at \((-?\d+),(-?\d+)\)", self.log_text()[mark:])
            if m:
                return int(m.group(1)), int(m.group(2))
        return None


def compare(g, v, label, tol_nearest=None):
    """the window's pixels (winshot) against the game's own frame laid out as the layout says, and the bars"""
    gw, gh, game = g.shot("cmp.ppm")
    ow, oh, out = g.winshot("cmp_win.ppm")
    check((ow, oh) == v["drawable"], "%s: winshot is the drawable's size, %dx%d pixels (the view says %r)" % (label, ow, oh, v["drawable"]))
    vx, vy, vw, vh = layout(v["scale"], ow, oh)
    check(v["pic"] == (vw, vh, vx, vy), "%s: the layout agrees with the independent one: %r vs %r" % (label, v["pic"], (vw, vh, vx, vy)))
    err = n = 0
    for j in range(0, vh, 3):
        gy = min(SH - 1, int((j + 0.5) * SH / vh))
        for i in range(0, vw, 3):
            gx = min(SW - 1, int((i + 0.5) * SW / vw))
            p = ((vy + j) * ow + vx + i) * 3
            q = (gy * SW + gx) * 3
            err += abs(out[p] - game[q]) + abs(out[p + 1] - game[q + 1]) + abs(out[p + 2] - game[q + 2])
            n += 3
    black = bars = 0
    for j in range(0, oh, 5):
        for i in range(0, ow, 5):
            if i < vx or i >= vx + vw or j < vy or j >= vy + vh:
                bars += 1
                p = (j * ow + i) * 3
                black += out[p] == 0 and out[p + 1] == 0 and out[p + 2] == 0
    whole = vw % SW == 0 and vh % SH == 0
    limit = 0.01 if (v["filter"] == "nearest" or (v["filter"] == "sharp" and whole)) and whole else 8.0
    if v["filter"] == "nearest" and not whole:
        limit = 0.5                                            # crisp pixels are the game's own at any scale; the GPU may round a sample on a pixel's edge the other way here and there
    return err / max(n, 1), (black / bars if bars else 1.0), limit


def clicks(g, v, label):
    """clicks sent in window points land on the game pixel drawn there"""
    ww, wh = v["window"]
    ow, oh = v["drawable"]
    vx, vy, vw, vh = v["pic"][2], v["pic"][3], v["pic"][0], v["pic"][1]
    ok = True
    for lx, ly in ((6, 6), (1017, 6), (6, 761), (1017, 761), (512, 384)):
        wx = int((vx + (lx + 0.5) * vw / SW) * ww / ow)
        wy = int((vy + (ly + 0.5) * vh / SH) * wh / oh)
        got = g.wclick(wx, wy)
        tol = max(1, int(round(ow / ww / (vw / SW))))          # a point can be more than one game pixel when the picture is drawn smaller than a point per pixel
        good = got is not None and abs(got[0] - lx) <= tol and abs(got[1] - ly) <= tol
        ok &= good
        if not good:
            print("   window point (%d,%d) should be game pixel (%d,%d); the game got %r" % (wx, wy, lx, ly, got))
    check(ok, "%s: a click at a window point reaches the game pixel drawn under it (window %dx%d points, drawable %dx%d pixels)" % (label, ww, wh, ow, oh))


def scenario(name, env):
    g = Hidden("h_" + name, env)
    try:
        v = g.view()
        print("== %s: window %dx%d points, drawable %dx%d pixels, %.2f pixels per point" % (name, v["window"][0], v["window"][1], v["drawable"][0], v["drawable"][1], v["dpi"]), flush=True)
        for mode in ("fit", "integer", "stretch"):
            while v["scale"] != mode:
                g.key("ctrl+f11")
                v = g.view()
            for filt in ("sharp", "nearest", "linear"):
                while v["filter"] != filt:
                    g.key("shift+f11")
                    v = g.view()
                err, bars, limit = compare(g, v, "%s %s/%s" % (name, mode, filt))
                check(err < limit and bars > 0.999, "%s %s/%s: what the window drew matches the game's frame (error %.2f, limit %.2f, bars black %.3f)" % (name, mode, filt, err, limit, bars))
                if filt == "sharp":
                    clicks(g, v, "%s %s" % (name, mode))
        return g, v
    except BaseException:
        g.stop()
        raise


def main():
    xe2e.RUNTIME, xe2e.MODULE, xe2e.EXE = (os.path.abspath(p) for p in (xe2e.RUNTIME, xe2e.MODULE, xe2e.EXE))
    os.makedirs(WORK, exist_ok=True)
    for name, env in (("default", {}), ("1500x1000", {"PORT_WINDOW": "1500x1000"}), ("700x525", {"PORT_WINDOW": "700x525"})):
        g, v = scenario(name, env)
        if name == "default":
            # the default start size: the largest whole multiple (in pixels) of the picture that fits the display
            check(v["window"][0] * v["dpi"] >= SW - 1 and v["window"][1] * v["dpi"] >= SH - 1, "default window is at least the picture's size in pixels: %r points at %.2f" % (v["window"], v["dpi"]))
            while v["scale"] != "fit":
                g.key("ctrl+f11")
                v = g.view()
            _, _, before = g.shot("before.ppm")
            got = None
            ww, wh = v["window"]
            ow, oh = v["drawable"]
            vx, vy, vw, vh = v["pic"][2], v["pic"][3], v["pic"][0], v["pic"][1]
            got = g.wclick(int((vx + (528 + 0.5) * vw / SW) * ww / ow), int((vy + (493 + 0.5) * vh / SH) * wh / oh))
            time.sleep(3.0)
            _, _, after = g.shot("after.ppm")
            diff = sum(abs(a - b) for a, b in zip(before[::97], after[::97])) / len(before[::97])
            check(got is not None and abs(got[0] - 528) <= 1 and abs(got[1] - 493) <= 1 and diff > 5.0, "a click on the drawn Start New Game reached %r and opened the new game screen (changed by %.1f)" % (got, diff))
        g.stop()
    print("hidden_e2e: %d checks, %d failed" % (xe2e.checks, xe2e.failures))
    return 1 if xe2e.failures else 0


if __name__ == "__main__":
    sys.exit(main())

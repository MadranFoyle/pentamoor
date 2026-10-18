#!/usr/bin/env python3
"""sota_launch_check.py: start Spells of the Ancients 2.15 the way a player does, through the launcher, and play the first minute: title screen, Start New Game, the difficulty, the colour,
FaceMaker's portrait, the name, to the world (the first encounter or the map). A check that what the installer made is what `./pentamoor sota` runs.

    python3 tools/soak/sota_launch_check.py [--folder PATH] [--workdir DIR] [--res 1024x768] [--default-overlay]

It runs `sh ./pentamoor sota` (the launcher of this checkout or release) with the SDL dummy drivers and a control pipe of its own, and NO other setting: the 2.15 folder is where the
installer puts it (sources/installed_sota/Magic/Program) unless --folder says another (then PENTAMOOR_SOTA is set to it). PORT_OVERLAY is a folder of the check's own, unless
--default-overlay: then it is left unset and the check says whether the launcher made port_overlay_sota (the saves of 2.15 are kept apart from the first game's) and not port_overlay.
It stops the game by its exact process id. Exit status 1 if a step did not happen. The screen is saved as <workdir>/final.png (or .ppm), looked at by a person and never committed.
The addresses and click places are those of tools/soak/sota_soak.py.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sota_soak  # noqa: E402
from pentamoor_ctl import Game  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


class LauncherGame(Game):
    """A Game whose process is the launcher's `sota` command (which execs the runtime, so the pid is the runtime's)."""

    def __init__(self, repo, folder, overlay, **kw):
        super().__init__(repo, **kw)
        self.folder = folder
        self.fixed_overlay = overlay

    def start(self):
        os.makedirs(self.workdir, exist_ok=True)
        if os.path.exists(self.ctl_path):
            os.unlink(self.ctl_path)
        os.mkfifo(self.ctl_path)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PENTAMOOR_", "PORT_"))}
        env.update(SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy", PORT_CONTROL=self.ctl_path, PORT_RES=self.res, PORT_STUB="1")
        if self.folder:
            env["PENTAMOOR_SOTA"] = self.folder
        if self.fixed_overlay:
            shutil.rmtree(self.fixed_overlay, ignore_errors=True)
            os.makedirs(self.fixed_overlay)
            env["PORT_OVERLAY"] = self.fixed_overlay
        self._log = open(self.log_path, "wb")
        self.proc = subprocess.Popen(["sh", os.path.join(self.repo, "pentamoor"), "sota"], cwd=self.repo, env=env, stdout=self._log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     start_new_session=True)
        self.started = time.time()
        self._ctl = os.open(self.ctl_path, os.O_RDWR | os.O_NONBLOCK)
        return self.proc.pid


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folder", help="the Program folder of the 2.15 install (PENTAMOOR_SOTA); default: where the installer puts it")
    ap.add_argument("--workdir", default="/tmp/sota-launch-check")
    ap.add_argument("--res", default="1024x768")
    ap.add_argument("--default-overlay", action="store_true", help="leave PORT_OVERLAY unset and check which overlay folder the launcher made")
    a = ap.parse_args()
    w, h = (int(v) for v in a.res.split("x"))
    wd = os.path.abspath(a.workdir)
    shutil.rmtree(wd, ignore_errors=True)
    before = {n for n in ("port_overlay", "port_overlay_sota") if os.path.exists(os.path.join(REPO, n))}
    g = LauncherGame(REPO, os.path.abspath(a.folder) if a.folder else None, None if a.default_overlay else os.path.join(wd, "overlay"), res=a.res, workdir=wd, overlay_seed=None)
    ok = True

    def check(what, cond, detail=""):
        nonlocal ok
        print("%-58s %s %s" % (what, "ok" if cond else "FAIL", detail), flush=True)
        ok = ok and bool(cond)
        return cond

    def wait_log(text, timeout):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if text in g.read_log(0):
                    return True
            except OSError:
                pass
            if not g.alive():
                return False
            time.sleep(0.5)
        return False

    def at(frac):
        return int(frac[0] * w), int(frac[1] * h)

    pid = g.start()
    print("started: sh ./pentamoor sota (pid %d)%s" % (pid, " PENTAMOOR_SOTA=" + a.folder if a.folder else ""), flush=True)
    try:
        if not check("the program loads", wait_log("loaded ", 60)):
            return 1
        time.sleep(9)
        check("the title screen draws", g.alive())
        g.click(*at(sota_soak.TITLE_NEW_GAME))
        time.sleep(2.5)
        g.click(*at(sota_soak.DIFFICULTY_APPRENTICE))
        time.sleep(2.5)
        g.click(*at(sota_soak.COLOUR_RED))
        fm = g.ctl_path + ".facemaker"
        end = time.time() + 90
        while time.time() < end and not os.path.exists(fm):
            time.sleep(0.5)
        if not check("the colour starts FaceMaker (a second program)", os.path.exists(fm)):
            return 1
        fd = os.open(fm, os.O_RDWR | os.O_NONBLOCK)
        try:
            off = g.log_size()
            os.write(fd, b"windows\n")
            t_end = time.time() + 120
            while time.time() < t_end and "FacemakerMainClass" not in g.read_log(off):
                time.sleep(1.0)
                os.write(fd, b"windows\n")
            check("FaceMaker's window is up", "FacemakerMainClass" in g.read_log(off))
            time.sleep(3)
            x, y = at(sota_soak.FACE_PORTRAIT)
            os.write(fd, ("move %d %d\n" % (x, y)).encode())
            time.sleep(0.5)
            os.write(fd, ("down %d %d\n" % (x, y)).encode())
            time.sleep(0.3)
            os.write(fd, ("up %d %d\n" % (x, y)).encode())
        finally:
            os.close(fd)
        time.sleep(7)
        for k in ("a", "b", "return"):                          # the name
            g.key(k)
            time.sleep(0.2)
        time.sleep(8)
        check("the world is made and its pictures are drawn (cardartlib, statwin)", wait_log("statwin.dll", 120))
        time.sleep(6)
        tile = g.peek(sota_soak.PARTY_TILE[0], 2)
        check("the party is on the map", tile is not None and tile[0] > 0 and tile[1] > 0, "tile %s" % (tile,))
        shot = g.shot(os.path.join(wd, "final.png"))
        data = sota_soak.read_ppm(os.path.join(wd, "shot.ppm"))
        lit = bool(data) and len(set(data[2][i:i + 3] for i in range(0, min(len(data[2]), 3 * 40000), 3 * 97))) > 8
        check("the screen is not blank", lit, "(%s)" % (shot,))
        check("the game is still running", g.alive())
        log = g.read_log(0)
        check("no import is missing", "not implemented" not in log, "" if "not implemented" not in log else [l for l in log.splitlines() if "not implemented" in l][:3])
    finally:
        g.stop()
    if a.default_overlay:
        after = {n for n in ("port_overlay", "port_overlay_sota") if os.path.exists(os.path.join(REPO, n))}
        check("saves go to port_overlay_sota, not port_overlay", "port_overlay_sota" in after and ("port_overlay" in after) == ("port_overlay" in before), "(%s)" % sorted(after))
    print("log: %s" % g.log_path)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""back_guard.py: the controller's Back button is Escape, and Escape leaves the game from the title menu with no question. There Back must be held half a second (docs/notes/controller.md);
everywhere else a tap is a tap. Headless, with controller commands only:

    python3 tools/soak/back_guard.py [640x480] [/tmp/back-guard]

  title       a tap of Back does nothing (the game is still on the title menu), a hold of 0.8 s ends the game
  difficulty  a tap of Back goes back to the title menu (the new game's screens answer Escape with "back")
  map         a tap of Back opens "Ready to Quit?" (a text menu of two lines), a second one closes it

Run it from the repository root with sources/ in place (as soak.py). Exits 1 if a check failed.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pentamoor_ctl import Game  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
failures = 0


def check(ok, what):
    global failures
    print("%s  %s" % ("ok  " if ok else "FAIL", what), flush=True)
    if not ok:
        failures += 1


def nav(g):
    r = g.nav_targets()
    return (r[0], len(r[1])) if r else (None, 0)


def wait_nav(g, pred, timeout=15.0):
    end, last = time.time() + timeout, (None, 0)
    while time.time() < end:
        last = nav(g)
        if pred(*last):
            return last
        time.sleep(0.5)
    return last


ap = argparse.ArgumentParser()
ap.add_argument("res", nargs="?", default="640x480", help="only 640x480: the encounter's line is clicked at its place")
ap.add_argument("workdir", nargs="?", default="/tmp/back-guard")
a = ap.parse_args()

g = Game(REPO, res=a.res, workdir=os.path.join(a.workdir, "a"))
g.start()
try:
    mode, n = wait_nav(g, lambda m, n: m == "screen" and n == 4, 20)
    check(mode == "screen" and n == 4, "the title menu is up (4 targets)")
    g.pad_press("back")
    time.sleep(2)
    check(g.alive() and nav(g) == ("screen", 4), "a tap of Back at the title menu does nothing")
    g.pad_press("back", hold=0.3)
    time.sleep(2)
    check(g.alive() and nav(g) == ("screen", 4), "nor does a hold of 0.3 s")
    g.pad("button back down")
    time.sleep(0.9)
    g.pad("button back up")
    end = time.time() + 6
    while g.alive() and time.time() < end:
        time.sleep(0.2)
    check(not g.alive(), "a hold of 0.9 s leaves the game (as Escape does there)")
finally:
    g.stop()

g = Game(REPO, res=a.res, workdir=os.path.join(a.workdir, "b"))
g.start()
try:
    wait_nav(g, lambda m, n: m == "screen" and n == 4, 20)
    t = sorted(g.nav_targets()[1], key=lambda t: (t.y0, t.x0))[0]
    g.click(*t.center)                                  # Start New Game
    time.sleep(4)                                       # the difficulty screen (4 targets, like the title menu)
    g.pad_press("back")
    time.sleep(3)
    check(g.alive() and nav(g) == ("screen", 4), "a tap of Back on the difficulty screen goes back (the title menu again, alive)")
    # resume the saved game: the map
    g.click(*sorted(g.nav_targets()[1], key=lambda t: (t.y0, t.x0))[2].center)      # Resume Game
    time.sleep(10)
    time.sleep(2)
    for k in range(12):                                  # monsters out of the way, gold in the purse; the encounter's second line ("Pay N gold", 640x480) takes them off the screen
        g.poke(0x67f2d0 + 0x14 * k, 0xffffffff)
    g.poke(0x522444, 5000)
    g.click(285, 336)
    time.sleep(3)
    for k in range(12):
        g.poke(0x67f2d0 + 0x14 * k, 0xffffffff)
    g.poke(0x522444, 5000)
    time.sleep(2)
    mode, n = nav(g)
    check(mode in ("none", None), "on the map (mode %s)" % mode)
    g.pad_press("back")
    mode, n = wait_nav(g, lambda m, n: m == "screen" and n == 2, 6)
    check(g.alive() and mode == "screen" and n == 2, "a tap of Back on the map asks 'Ready to Quit?' (%s, %d lines)" % (mode, n))
    g.pad_press("back")
    time.sleep(2)
    check(g.alive() and nav(g)[0] in ("none", None), "a second tap closes the question: the game goes on")
finally:
    g.stop()
print("%d failed" % failures)
sys.exit(1 if failures else 0)

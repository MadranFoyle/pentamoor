#!/usr/bin/env python3
"""casts_dialog.py: play the Sorcerer duel until the "Sorcerer casts..." dialog is on screen, then take a screenshot and stop (the game keeps running).

    python3 tools/soak/casts_dialog.py 800x600 /tmp/casts-800 [--pid-file F]

Run it from the repository root with sources/ in place (as soak.py). Leaves <workdir>/casts.png, <workdir>/game0/game.log with a window dump at the
moment of the dialog, and prints the game's pid (kill that pid when done). See docs/notes/sorcerer-casts-dialog.md.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soak  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("res", nargs="?", default="640x480")
ap.add_argument("workdir", nargs="?", default="/tmp/casts-dialog")
ap.add_argument("--seconds", type=int, default=420)
a = ap.parse_args()
args = argparse.Namespace(res=a.res, minutes=10, repo=os.getcwd(), exe="src/port/build/pentamoor-run", module=None, program="sources/installed/Magic/Program/MAGIC.EXE",
                          workdir=a.workdir, seed=3, duels_per_game=1, min_turns=3, max_turns=9, max_duel_s=300, stall_s=60, tick_s=1.0, verbose=False)
sk = soak.Soak(args)
g = sk.new_game()
sk.to_ante()
if not sk.start_duel_from_ante(True):
    sys.exit("no duel")
ctx, prev, t0 = {"n": 0}, None, time.time()
while time.time() - t0 < a.seconds:
    t = sk.look("casts")
    if t is None:
        sys.exit("game gone")
    s = sk.sig(t)
    if s != prev:
        prev, ctx = s, {"n": 0}
    # the dialog has no title of its own: its only child, a MAGICGAME_BigCardChoiceClass window, carries "Sorcerer casts..."
    if any(w.visible and w.title.startswith("Sorcerer ") for w in t.find("MAGICGAME_BigCardChoiceClass")):
        g.shot(os.path.join(a.workdir, "casts.png"))
        g.cmd("windows")
        print("dialog on screen; game pid", g.pid, flush=True)
        break
    desc, kind = sk.tick(t, ctx)               # (the soak policy presses Return on dialogs, so look first)
    if kind != "none":
        ctx["n"] += 1
    time.sleep(1)
else:
    sys.exit("no casts dialog in %d s" % a.seconds)

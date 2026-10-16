#!/usr/bin/env python3
"""won_dialog.py: win the Sorcerer duel (the opponent's life poked to 0) and check the keys of the "You won!" dialog: Return must not close it (the original's dialog manager takes
Enter and the dialog's procedure ignores IDOK), a click must.

    python3 tools/soak/won_dialog.py [640x480] [/tmp/won-dialog]

Run it from the repository root with sources/ in place (as soak.py). Prints what it saw and exits 1 if the dialog behaved otherwise. See docs/notes/dialogs.md ("Enter in a dialog with nothing to press").
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soak  # noqa: E402

OPP_LIFE = 0x6a4a04

ap = argparse.ArgumentParser()
ap.add_argument("res", nargs="?", default="640x480")
ap.add_argument("workdir", nargs="?", default="/tmp/won-dialog")
ap.add_argument("--seconds", type=int, default=300)
a = ap.parse_args()
args = argparse.Namespace(res=a.res, minutes=10, repo=os.getcwd(), exe="src/port/build/pentamoor-run", module=None, program="sources/installed/Magic/Program/MAGIC.EXE",
                          workdir=a.workdir, seed=3, duels_per_game=1, min_turns=3, max_turns=9, max_duel_s=300, stall_s=60, tick_s=1.0, verbose=False)
sk = soak.Soak(args)
g = sk.new_game()
sk.to_ante()
if not sk.start_duel_from_ante(True):
    sys.exit("no duel")


def won_dialog(tree):
    """The "You won!" dialog (class #32770 with that text), or None."""
    for d in tree.dialogs():
        if any(c.visible and "won" in c.title.lower() for c in tree.children(d)):
            return d
    return None


result, poked, t0 = "no dialog", False, time.time()
while time.time() - t0 < a.seconds:
    t = sk.look("x")
    if t is None:
        result = "the program is gone"
        break
    bar = t.bar()
    if not poked and t.find("MAGICGAME_MainClass") and bar and bar[0].visible and bar[0].title and bar[2]:
        g.poke(OPP_LIFE, 0)
        g.click(*bar[2].center)                    # any action makes the engine look at the life totals again
        poked = True
        time.sleep(3)
        continue
    d = won_dialog(t)
    if d is not None:
        g.key("return")
        time.sleep(2)
        after_return = won_dialog(sk.look("x"))
        print("Return: the dialog is %s" % ("still there" if after_return else "gone (wrong)"))
        if after_return is None:
            result = "FAIL"
            break
        g.click(*d.center)
        time.sleep(3)
        after_click = won_dialog(sk.look("x"))
        print("click: the dialog is %s" % ("still there (wrong)" if after_click else "gone"))
        result = "FAIL" if after_click else "ok"
        break
    if t.dialogs():
        sk.handle_dialog(t)                        # the coin toss, the start of the duel ...
    time.sleep(2)
g.stop()
print("RESULT", result)
sys.exit(0 if result == "ok" else 1)

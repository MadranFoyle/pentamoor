#!/usr/bin/env python3
"""sota_saveload.py: a save and load round trip on the overworld of Spells of the Ancients 2.15 (shandalar.exe), through PORT_CONTROL.

    python3 tools/soak/sota_saveload.py [--workdir /tmp/sota-saveload]

New game (sota_soak.py's way), the first duel won (the opponent's life poked), then on the map: the party's place and the gold are read, the game is SAVED to slot 1 (right-click menu, Save,
the first row, a name), the party is teleported to another tile, the game is LOADED from slot 1, and the place must be the saved one again. Then the game is left (the menu's Quit and its
question), a new process is started on the same overlay, "Resume Game" is taken at the title screen, and the place must be the saved one again once more. Exit status 1 if a step fails.
Prints what it saw (the numbers are addresses of the 2.15 build: tools/soak/sota_soak.py).
"""
import argparse
import os
import shutil
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sota_soak  # noqa: E402
import soak  # noqa: E402
from pentamoor_ctl import Game  # noqa: E402

GOLD = None            # not read: the status bar's number is compared on the screenshot only by the person; the place is what the check uses
MENU_SAVE = (0.168, 0.18)
MENU_LOAD = (0.156, 0.206)
MENU_QUIT = (0.168, 0.234)
SLOT1 = (0.342, 0.208)
QUIT_YES = (0.344, 0.474)               # "Ready to Quit?  No.  Yes."


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workdir", default="/tmp/sota-saveload")
    ap.add_argument("--repo", default=os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
    ap.add_argument("--exe", default="src/port/build/pentamoor-run")
    ap.add_argument("--program", default="sources/installed_sota_215_m2/Program/shandalar.exe")
    ap.add_argument("--res", default="1024x768")
    a = ap.parse_args()
    a.minutes, a.seed, a.module = 10, 7, None
    a.duels_per_game, a.min_turns, a.max_turns, a.max_duel_s, a.stall_s, a.tick_s, a.verbose = 1, 3, 9, 300, 60, 1.0, False
    a.workdir = os.path.abspath(a.workdir)
    s = sota_soak.SotaSoak(a)
    ok = True

    def check(what, cond, detail=""):
        nonlocal ok
        print("%-52s %s %s" % (what, "ok" if cond else "FAIL", detail), flush=True)
        ok = ok and bool(cond)
        return cond

    def clear(g):
        g.poke_many([(sota_soak.MONSTERS + sota_soak.MONSTER_STRIDE * i, 0xffffffff) for i in range(sota_soak.N_MONSTERS)])

    keep = {"on": False, "game": None}

    def keeper():
        """No wandering monster reaches the party while the script presses menus: the table is emptied four times a second."""
        while True:
            time.sleep(0.25)
            if keep["on"] and keep["game"] is not None and keep["game"].alive():
                clear(keep["game"])

    threading.Thread(target=keeper, daemon=True).start()

    def at(frac):
        return int(frac[0] * s.w), int(frac[1] * s.h)

    def menu_is_open(g):
        """The right-click menu's panel (a dark green, 23,59,15) at the top left of the map's view."""
        ppm = os.path.join(g.workdir, "menu.ppm")
        if os.path.exists(ppm):
            os.unlink(ppm)
        g.cmd("shot " + ppm)
        end = time.time() + 6
        while time.time() < end and not (os.path.exists(ppm) and os.path.getsize(ppm) > 1000):
            time.sleep(0.2)
        time.sleep(0.5)
        img = sota_soak.read_ppm(ppm)
        if not img:
            return False
        w, h, data = img
        x, y = int(0.122 * w), int(0.326 * h)
        r, gg, b = data[3 * (y * w + x):3 * (y * w + x) + 3]
        return abs(r - 23) < 12 and abs(gg - 59) < 14 and abs(b - 15) < 12

    def menu(g, item):
        """Open the map's right-click menu (three tries: the click must come between two frames of the map) and click one of its lines."""
        for _ in range(3):
            clear(g)
            g.rclick(s.w // 2, s.h // 3, hold=0.3)
            time.sleep(1.5)
            if menu_is_open(g):
                break
            g.key("escape")
            time.sleep(1)
        else:
            check("the right-click menu opens", False)
            return False
        g.click(*at(item))
        time.sleep(3)
        return True

    g = s.new_game()
    if not (check("new game to the first ante screen", s.to_ante()) and check("the first duel starts", s.start_duel_from_ante(True))):
        g.stop()
        return 1
    time.sleep(3)
    for _ in range(4):                                    # the first encounter can be followed by another (monsters that were next to the party): end each, until the map
        if os.environ.get("SAVELOAD_CONCEDE"):
            soak.Soak.concede(s)                          # the right-click menu's Concede, as monkey.py does (the default is to win: the reward screens)
        else:
            s.win()
        s.after_duel()
        t = s.look("after the duel")
        if t is None or not t.find("MAGICGAME_MainClass", visible=True):
            break
        time.sleep(3)
    g.click(s.w // 2, s.h // 2)
    time.sleep(3)
    keep["game"], keep["on"] = g, True
    clear(g)
    time.sleep(1)
    pos = g.peek(sota_soak.PARTY_PIXEL[0], 2)
    tile = g.peek(sota_soak.PARTY_TILE[0], 2)
    check("on the map", pos is not None and tile is not None, "party at %s tile %s" % (pos, tile))
    menu(g, MENU_SAVE)
    g.click(*at(SLOT1))                      # the first row: the line to type a name in
    time.sleep(2)
    for k in "sav1":
        g.key(k)
        time.sleep(0.2)
    g.key("return")
    time.sleep(3)
    overlay = os.path.join(g.workdir, "overlay", "Program")
    names = sorted(os.listdir(overlay)) if os.path.isdir(overlay) else []
    check("the save is on disk (MAGIC4.SVE, .map, .fce)", all(any(n.lower() == "magic4." + e for n in names) for e in ("sve", "map", "fce")), str([n for n in names if n.lower().startswith("magic")]))
    tx, ty = (tile[0] + 9) % 100 + 5, (tile[1] + 7) % 90 + 5
    g.poke_many(sota_soak.teleport_pokes(tx, ty))
    time.sleep(3)
    clear(g)
    moved = g.peek(sota_soak.PARTY_PIXEL[0], 2)
    check("the party was moved before loading", moved != pos, str(moved))
    menu(g, MENU_LOAD)
    g.click(*at(SLOT1))
    time.sleep(6)
    clear(g)
    back = g.peek(sota_soak.PARTY_TILE[0], 2)
    near = back is not None and abs(back[0] - tile[0]) <= 3 and abs(back[1] - tile[1]) <= 3 and back != (tx, ty)
    # right after a Load the avatar walks a few steps towards the mouse (the pointer is where the slot was clicked): the same as 1.0's (docs/notes/saves-and-paths.md), so "near" is the check
    check("Load: the party is back at the saved place (within 3 tiles)", near, "saved %s, now %s (moved to %s before)" % (tile, back, (tx, ty)))
    g.shot(os.path.join(a.workdir, "after-load.png"))
    # leave the game by its menu: Quit and its question, so that the autosave is written, then resume from the title screen
    time.sleep(2)
    left_at = g.peek(sota_soak.PARTY_TILE[0], 2)          # where the party is when the game is left: what Resume Game must give back
    menu(g, MENU_QUIT)
    time.sleep(2)
    if os.environ.get("SAVELOAD_TRACE_QUIT"):
        g.cmd("trace on")                                # every import call from here on, in game.log (a debugging aid)
        time.sleep(0.3)
    g.click(*at(QUIT_YES))
    t_end = time.time() + 20
    while g.alive() and time.time() < t_end:
        time.sleep(0.5)
    g.shot(os.path.join(a.workdir, "after-quit.png"))
    ended = not g.alive()
    print("(Quit: the program %s)" % ("ended" if ended else "is still running: the question was not answered, the process is stopped"))
    check("Quit: the program ended by itself", ended)
    if not ended:
        print("  stack of the process that did not end:", s.thread_dump("quit-hang"))
        t = g.windows(timeout=5)
        print("  windows left:", [(w.cls, w.title[:20], w.visible) for w in t.wins] if t else "(no answer)")
    keep["on"] = False
    overlay_copy = g.workdir
    g.stop()
    g2 = Game(a.repo, res=a.res, workdir=os.path.join(a.workdir, "game-resume"), exe=a.exe, program=a.program, module=s.module or os.path.join(os.path.dirname(os.path.join(a.repo, a.exe)), "game_shandalar." + ("dylib" if sys.platform == "darwin" else "so")),
              overlay_seed=None)
    os.makedirs(g2.workdir, exist_ok=True)
    g2.overlay_seed = None
    g2.start()
    shutil.rmtree(os.path.join(g2.workdir, "overlay"), ignore_errors=True)       # start() made an empty overlay: put the first game's in (the process is already reading it: the title screen only)
    shutil.copytree(os.path.join(overlay_copy, "overlay"), os.path.join(g2.workdir, "overlay"))
    s.game = g2
    time.sleep(14)
    g2.click(int(0.516 * s.w), int(0.813 * s.h))     # Resume Game
    time.sleep(10)
    clear(g2)
    resumed = g2.peek(sota_soak.PARTY_TILE[0], 2)
    check("Resume Game: the party is where it was when the game was left", resumed == left_at, "left at %s, now %s" % (left_at, resumed))
    g2.shot(os.path.join(a.workdir, "after-resume.png"))
    g2.stop()
    print("RESULT", "ok" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

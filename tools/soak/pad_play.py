#!/usr/bin/env python3
"""pad_play.py: play Pentamoor with controller input only (no mouse, no keyboard command), headless, and check what the game did.

    python3 tools/soak/pad_play.py [--seed N[,N...]] [--res 1024x768] [--workdir /tmp/pad_play] [--shots DIR]

The program is started on SDL's dummy drivers with its own control pipe and overlay (as tools/soak does) and is driven with the `pad` steps of PORT_CONTROL, which go through the same
code as a real controller's events (docs/notes/controller.md). Two games are played:

  1. a new game from the title screen: Start New Game, difficulty, colour and visage by moving the cursor with the left stick and pressing A, the name accepted with X (Enter), then
     walking on the map with the right trigger and the left stick, and with the right stick as arrow keys; the party's position is read back from the game's memory.
  2. a duel from the saved game: Resume Game, the encounter's Duel, the coin toss dialogs by their buttons and X, then a card played from the hand with A, a card's menu opened with B
     and closed with Y, and the turn passed by the Done button.

A new game is a random world and a duel starts from shuffled decks, so every run is made with PORT_SEED (src/port/seed.h) set to one of the PINNED seeds below, which makes the world and the
draws the same every time (docs/notes/controller.md, "A repeatable run"); --seed picks others. Prints one line per check and exits 1 if one failed. --shots DIR keeps a screenshot after each step (PNG, needs PIL; PPM otherwise). Needs the installed game (sources/installed) and the saved game
(sources/emu_overlay), as the soak does. Only 1024x768 (the default size) is laid out below.
"""
import argparse
import hashlib
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pentamoor_ctl import Game  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# where things are on the screen at 1024x768 (the title and menu screens are pictures, not windows)
NEW_GAME = (528, 493)
APPRENTICE = (565, 190)
RED = (133, 155)
VISAGE = (190, 200)
RESUME = (528, 624)
DUEL = (470, 486)
PARTY_X, PARTY_Y, GOLD, FOOD = 0x52eff0, 0x52eff4, 0x522444, 0x522448
LOCATIONS = 0x67bdf0                       # 128 records of 25 dwords: the world's places

# The seeds the script is played with. The new game of each starts the party on open ground (the first steps east walk; no encounter comes first); the duel is from the saved game, so its world is fixed
# and the seed decides the shuffles.
PINNED = {
}

failures = 0


def check(ok, what):
    global failures
    print("%s  %s" % ("ok  " if ok else "FAIL", what), flush=True)
    if not ok:
        failures += 1
    return ok


class Run:
    def __init__(self, a, name):
        self.a = a
        self.n = 0
        self.name = name
        self.g = Game(REPO, res=a.res, workdir=os.path.join(a.workdir, name))

    def shot(self, tag):
        if self.a.shots:
            os.makedirs(self.a.shots, exist_ok=True)
            self.n += 1
            self.g.shot(os.path.join(self.a.shots, "%s_%02d_%s.png" % (self.name, self.n, tag)))

    def party(self):
        v = self.g.peek(PARTY_X, 2)
        return tuple(v) if v else None


def new_game_once(a, attempt):
    """One new game up to the first steps on the map. Returns False if the world started the party at an encounter (the start is random), so nothing could be walked."""
    r = Run(a, "newgame%d" % attempt)
    g = r.g
    g.start()
    try:
        time.sleep(10)
        if attempt == 0:
            check(g.pad_pos() is not None, "the program answers the pad steps")
            check(g.pad_pos()[2] == 0, "no pad cursor before the pad is used")
        g.pad_click(*NEW_GAME)
        if attempt == 0:
            check(g.pad_pos()[2] == 1, "the pad is the active device once it is used")
        time.sleep(3)
        r.shot("difficulty")
        g.pad_click(*APPRENTICE)
        time.sleep(3)
        g.pad_click(*RED)
        time.sleep(3)
        r.shot("visage")
        g.pad_click(*VISAGE)
        time.sleep(3)
        r.shot("name")
        g.pad_press("x")                                   # Enter accepts the name
        time.sleep(10)
        r.shot("map")
        p0 = r.party()
        gold = g.peek(GOLD, 1)
        check(p0 is not None and p0[0] > 0 and gold and gold[0] > 0, "a new game reached the map (party at %s, gold %s)" % (p0, gold))
        loc = g.peek(LOCATIONS, 25 * 128)
        print("DIGEST world %s %s" % (p0, hashlib.sha1(repr(loc).encode()).hexdigest()[:12]), flush=True)       # the same seed must make the same world
        g.pad("axis rt 1")                                 # the walk button held ...
        g.pad("stick l 1 0")                               # ... and the stick pushed east: the party walks
        time.sleep(2.5)
        pos = g.pad_pos()
        g.pad("stick l 0 0")
        time.sleep(0.4)
        g.pad("axis rt 0")
        r.shot("walked")
        p1 = r.party()
        if p1 == p0:
            print("NOTE  the party did not move: an encounter came first (the start is random), starting again", flush=True)
            return False
        check(pos and pos[3] == 1, "walking holds the left button (pad pos %s)" % (pos,))
        check(g.pad_pos()[3] == 0, "letting go of the stick lets go of the button")
        check(p1[0] > p0[0], "the party walked east: %s -> %s" % (p0, p1))
        if g.alive():
            p2 = r.party()
            g.pad("stick r 0 1")                           # the right stick, down: the arrow key
            time.sleep(1.5)
            g.pad("stick r 0 0")
            time.sleep(0.5)
            p3 = r.party()
            r.shot("arrows")
            check(p2 is not None and p3 is not None and p3 != p2, "the right stick walked the party: %s -> %s" % (p2, p3))
            nav = g.nav_targets()
            check(nav is not None and nav[0] == "none" and not nav[1], "on the map there is nothing for the D-pad to navigate (%s)" % (nav and nav[0]))
            g.pad("button up down")                        # the D-pad up, held: the arrow key (nothing to navigate to), which walks the party
            time.sleep(1.5)
            g.pad("button up up")
            time.sleep(0.5)
            p4 = r.party()
            r.shot("dpad")
            check(p3 is not None and p4 is not None and p4 != p3, "the D-pad is still the arrow keys where there is nothing to navigate: %s -> %s" % (p3, p4))
        check(g.alive(), "the program is still running")
        return True
    finally:
        g.stop()


def new_game(a):
    for attempt in range(3):
        if new_game_once(a, attempt):
            return
    check(False, "a new game that starts on the map, in three tries")


def hand_cards(t):
    """The rows of the player's hand list (the windows of its cards, top row first)."""
    hands = [w for w in t.find("MAGICGAME_HandClass") if w.title.startswith("Your hand")]
    if not hands:
        return []
    h = hands[0]
    cards = [w for w in t.find("MAGICGAME_CardClass", title="Hand Card") if w.visible and h.x0 <= w.x0 <= h.x1 and h.y0 <= w.y0 <= h.y1]
    return sorted(cards, key=lambda w: w.y0)


def duel(a):
    r = Run(a, "duel")
    g = r.g
    g.start()
    try:
        time.sleep(9)
        g.pad_click(*RESUME)
        time.sleep(9)
        r.shot("ante")
        g.pad_click(*DUEL)
        t = None
        end = time.time() + 75
        while time.time() < end:                           # the coin toss: a movie, then a dialog; its buttons are clicked, the rest closed with Enter
            time.sleep(2)
            t = g.windows()
            if t is None:
                break
            if t.bar() and t.bar_shown():
                break
            btns = [w for d in t.dialogs() for w in t.children(d) if w.cls.startswith("BUTTON") and w.visible and not w.empty]
            if btns:
                g.pad_click(*btns[0].center)
            else:
                g.pad_press("x")
        r.shot("board")
        check(t is not None and t.bar_shown(), "the duel started and the prompt bar is up")
        h0 = hand_cards(t)
        if t is not None and h0:
            time.sleep(2)
            print("DIGEST hand %s" % g.region_hash((min(w.x0 for w in h0), min(w.y0 for w in h0), max(w.x1 for w in h0), max(w.y1 for w in h0))), flush=True)
        if not (t and t.bar_shown()):
            return
        title0 = t.bar()[0].title
        cards = hand_cards(t)
        check(len(cards) >= 5, "the hand is on the board (%d cards)" % len(cards))
        hand0 = [w.title for w in t.find("MAGICGAME_HandClass") if w.title.startswith("Your hand")]
        hand1 = hand0
        for i in range(len(cards)):                        # A on each row in turn: a spell without mana does nothing, the land is played
            g.pad_click(cards[i].x0 + 40, cards[i].y0 + 8)
            time.sleep(1.5)
            t = g.windows()
            hand1 = [w.title for w in t.find("MAGICGAME_HandClass") if w.title.startswith("Your hand")]
            if hand1 != hand0 or t.bar()[0].title != title0:
                break
            g.pad_press("back")
        r.shot("played")
        check(hand0 != hand1 or t.bar()[0].title != title0, "A on a card in the hand did something: %s -> %s, bar %r -> %r" % (hand0, hand1, title0, t.bar()[0].title))
        g.pad_press("back")                                   # Escape backs out of a spell that wants a target or mana
        time.sleep(1)
        t = g.windows()
        cards = hand_cards(t)
        if cards:
            g.pad_click(cards[0].x0 + 40, cards[0].y0 + 8, "b")      # B: the right button, a menu
        time.sleep(1)
        t = g.windows()
        r.shot("menu")
        check(len(t.items) > 0, "B opened a popup menu (%d rows)" % len(t.items))
        g.pad_press("back")                                   # Back (Escape) closes it
        time.sleep(1)
        t = g.windows()
        check(len(t.items) == 0, "Y closed the popup menu")
        bar = t.bar()
        if bar and t.bar_shown() and bar[2]:
            title = bar[0].title
            g.pad_click(*bar[2].center)                    # the Done button
            time.sleep(4)
            t = g.windows()
            r.shot("done")
            check(t is not None and (t.dialogs() or not t.bar_shown() or t.bar()[0].title != title), "Done passed the phase (bar %r before)" % title)
        check(g.alive(), "the program is still running")
    finally:
        g.stop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", help="PORT_SEED for the run(s), comma separated (default: the PINNED seeds, one whole run each)")
    ap.add_argument("--res", default="1024x768")
    ap.add_argument("--workdir", default="/tmp/pad_play")
    ap.add_argument("--shots", default=None)
    ap.add_argument("--only", choices=["newgame", "duel", "nav"], default=None, help="nav: the D-pad between cards in a duel (nav_play.py, which has more options)")
    a = ap.parse_args()
    if a.only == "nav":
        import nav_play
        sys.argv = [sys.argv[0], "--workdir", os.path.join(a.workdir, "nav")] + (["--shots", a.shots] if a.shots else []) + (["--seed", a.seed.split(",")[0]] if a.seed else [])
        return nav_play.main()
    if a.res != "1024x768":
        print("only 1024x768 is laid out here", file=sys.stderr)
        return 2
    base = a.workdir
    for seed in [int(x) for x in a.seed.split(",")] if a.seed else sorted(PINNED) or [1]:
        os.environ["PORT_SEED"] = str(seed)                         # every program of the run, and the nav_play above
        a.workdir = os.path.join(base, "seed%d" % seed)
        os.makedirs(a.workdir, exist_ok=True)
        print("=== seed %d: %s" % (seed, PINNED.get(seed, "(not a pinned seed)")), flush=True)
        if a.only in (None, "newgame"):
            new_game(a)
        if a.only in (None, "duel"):
            duel(a)
    print("%d check(s) failed" % failures if failures else "all checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

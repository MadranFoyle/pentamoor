#!/usr/bin/env python3
"""screen_nav_play.py: the D-pad on the screens MAGIC.EXE draws itself (docs/notes/controller-screens.md), headless, with controller commands only.

    python3 tools/soak/screen_nav_play.py [--res 1024x768] [--workdir /tmp/screen_nav_play] [--shots DIR] [--only title,village,...]

The program is started on SDL's dummy drivers with its own control pipe and overlay (as tools/soak does) and played from the title screen: the new game's four screens (difficulty, colour, visage,
name) with the D-pad and A, then, on the map, put at a place by `poke` (the location table, docs/notes/castle-dungeon-stats.md) and with the monsters kept away:

  title        the four menu items are targets, and the pointer put on each with the mouse gets the game's own hover on that button (the table's index: DAT_00519ff4)
  newgame      D-pad + A through difficulty (4 targets), colour (5), visage (14), X for the name: the map
  encounter    the "Will you... Duel / Pay" text menu of the first encounter, if there is one: down, A pays (gold goes down)
  castle       a castle's gate (a text menu of two lines): up and down move between them, A on the first leaves it
  village      the buttons (hover checked at every one), A on "Buy 10 food" (once: 15 gold, +10 food), "Buy Cards": the cards and Done as targets, a card bought with A, A (the Y/N question: A is Y)
  worldmap     the four buttons of the world map, A on Done
  clues        the clue list: the twelve rows, Done and the arrows; A on a row opens its page, Done comes back
  stats        Wiz Stats: the table's buttons and the owned world magics; the Journal opened and left with its Done eight times (each press must count)
  deck         F1 opens the deck builder: its cards' strips and buttons are targets; A on Exit leaves
  map          on the map `pad nav` says none and the D-pad is the arrow keys (the party walks); B opens the game's menu of the map, whose eight lines are targets

Prints one line per check and exits 1 if one failed. Needs the installed game and the saved game (sources/installed, sources/emu_overlay), as the soak does.
"""
import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pentamoor_ctl import Game  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GOLD, FOOD, HOVER, UI_CTX, PARTY_X, PARTY_Y = 0x522444, 0x522448, 0x519ff4, 0x519c24, 0x52eff0, 0x52eff4
MONSTERS, LOCATIONS, DUNGEONS = 0x67f2d0, 0x67bdf0, 0x67f000
K_CARD, K_BUTTON, K_ROW, K_MENU = 1, 2, 4, 9

failures = 0


def check(ok, what):
    global failures
    print("%s  %s" % ("ok  " if ok else "FAIL", what), flush=True)
    if not ok:
        failures += 1
    return ok


class Session:
    def __init__(self, a):
        self.a = a
        self.res = a.res
        self.w, self.h = (int(v) for v in a.res.split("x"))
        self.g = Game(REPO, res=a.res, workdir=os.path.join(a.workdir, a.res))
        self.nshot = 0
        self.quiet = False

    # ---- the program ------------------------------------------------------------------------------------------------------------------------------------
    def wait(self, s):
        end = time.time() + s
        while time.time() < end:
            if self.quiet:
                self.clear_monsters()
            time.sleep(min(0.4, max(0.0, end - time.time())))

    def clear_monsters(self):
        for i in range(12):
            self.g.poke(MONSTERS + 0x14 * i, 0xffffffff)

    def shot(self, tag):
        if not self.a.shots:
            return
        os.makedirs(self.a.shots, exist_ok=True)
        self.nshot += 1
        self.g.shot(os.path.join(self.a.shots, "%s_%02d_%s.png" % (self.res, self.nshot, tag)))

    def mem(self, addr, n=1):
        v = self.g.peek(addr, n)
        return v if v is None else [x - (1 << 32) if x >= 1 << 31 else x for x in v]

    def gold(self):
        return self.mem(GOLD)[0]

    def food(self):
        return self.mem(FOOD)[0]

    # ---- the D-pad --------------------------------------------------------------------------------------------------------------------------------------
    def nav(self):
        r = self.g.nav_targets()
        return r if r else (None, [])

    def pos(self):
        p = self.g.pad_pos()
        return (p[0], p[1]) if p else None

    def wait_nav(self, pred, timeout=20.0):
        """Poll `pad nav` until pred(mode, targets) is true; returns (mode, targets) then, else the last answer."""
        end, last = time.time() + timeout, (None, [])
        while time.time() < end:
            last = self.nav()
            if pred(*last):
                return last
            self.wait(0.5)
        return last

    def dpad_to(self, goal, limit=16):
        """Press the D-pad until the pointer is on the target `goal` (a function of the target list returning one target): returns the number of presses, or None if it never got there."""
        tried = set()
        for n in range(limit):
            mode, tl = self.nav()
            try:
                tgt = goal(tl)
            except IndexError:
                tgt = None
            p = self.pos()
            if tgt is None or p is None:
                return None
            if tgt.contains(*p):
                return n
            dx, dy = tgt.center[0] - p[0], tgt.center[1] - p[1]
            dirs = (["right" if dx > 0 else "left", "down" if dy > 0 else "up"] if abs(dx) > abs(dy) else ["down" if dy > 0 else "up", "right" if dx > 0 else "left"])
            for d in dirs:
                if (p, d) in tried:
                    continue
                tried.add((p, d))
                q = self.g.dpad(d, wait=0.5)
                if q is not None and q != p:
                    break
            else:
                return None
            time.sleep(0.15)
        return None

    def press_a(self, wait=2.5):
        self.g.pad_press("a")
        self.wait(wait)

    def hover_check(self, targets, what):
        """The pointer put on the middle of every table button with the real mouse gets the game's own hover on that button: the table's index is in the label ('button N')."""
        bad = []
        for t in targets:
            m = re.match(r"button (\d+)$", t.label)
            if not m:
                continue
            self.g.cmd("move %d %d" % t.center)
            time.sleep(0.35)
            h = self.mem(HOVER)
            if h is None or h[0] != int(m.group(1)):
                bad.append((t.label, h))
        check(not bad, "%s: the pointer on the middle of each of its %d buttons gets the game's hover on that button%s" % (what, len(targets), (" (wrong: %s)" % bad[:3]) if bad else ""))

    # ---- places -----------------------------------------------------------------------------------------------------------------------------------------
    def teleport(self, kind, n=0, dungeon=False):
        g = self.g
        if dungeon:
            d = self.mem(DUNGEONS, 12 * 15)
            tx, ty = d[12 * n], d[12 * n + 1]
            g.poke(DUNGEONS + 0x10 + 0x30 * n, 7)
        else:
            loc = self.mem(LOCATIONS, 25 * 128)
            sel = [(loc[25 * i + 1], loc[25 * i + 2]) for i in range(128) if loc[25 * i] == kind]
            tx, ty = sel[n]
        self.clear_monsters()
        g.poke(GOLD, 5000)
        g.poke(FOOD, 200)
        g.poke(PARTY_X, tx * 32 + 16)
        g.poke(PARTY_Y, ty * 32 + 16)
        g.poke(0x641010, tx)
        g.poke(0x641014, ty)
        g.poke(0x5659b0, 0)
        self.wait(3.5)


def to_map(s):
    """A village that the walk of the `map` step may have entered: leave it by its last button."""
    for _ in range(3):
        mode, tl = s.nav()
        if mode == "screen" and len(tl) == 9:
            s.dpad_to(lambda tl: sorted([t for t in tl if t.x0 > 0.05 * s.w], key=lambda t: (t.y0, t.x0))[-1])
            s.press_a(4)
        else:
            return


def is_screen(minimum=1):
    return lambda mode, tl: mode == "screen" and len(tl) >= minimum


def title_and_newgame(s):
    g = s.g
    g.start()
    s.wait(10)
    mode, tl = s.nav()
    check(mode == "screen" and len(tl) == 4, "the title menu: 4 targets in mode screen (%s, %d)" % (mode, len(tl)))
    s.hover_check(tl, "the title menu")
    s.shot("title")
    check(s.pos() is not None, "the program answers the pad steps")
    # the first press takes the nearest target (the pointer starts in the middle of the screen, on nothing)
    n = s.dpad_to(lambda tl: min(tl, key=lambda t: t.y0) if tl else None)
    check(n is not None and n <= 4, "the D-pad reaches 'Start New Game' (%s presses)" % n)
    s.press_a()
    for name, want in (("difficulty", 4), ("colour", 5), ("visage", 14)):
        mode, tl = s.wait_nav(is_screen(want), 8)
        check(mode == "screen" and len(tl) == want, "%s: %d targets (%d)" % (name, want, len(tl)))
        s.hover_check(tl, name)
        s.shot(name)
        n = s.dpad_to(lambda tl: min(tl, key=lambda t: (t.y0, t.x0)) if tl else None)       # the first of them: Apprentice, Red, the first face
        check(n is not None, "the D-pad reaches the first choice of the %s screen (%s presses)" % (name, n))
        s.press_a(3)
    s.shot("name")
    mode, tl = s.nav()
    check(mode in ("none", None) and not tl, "the name box has no targets: the D-pad is the arrow keys there (mode %s)" % mode)
    g.pad_press("x")                                   # Enter accepts the name
    s.wait(12)
    s.quiet = True
    for attempt in range(4):
        mode, tl = s.wait_nav(lambda m, t: m == "screen" and t and t[0].label == "line 0", 14)
        if mode == "screen" and len(tl) == 1:
            print("NOTE  the first encounter is a forced duel (one line): starting again (%d)" % (attempt + 1), flush=True)
            restart_quick(s)
        else:
            break


def restart_quick(s):
    """Stop the game and start a new one by clicking the table's buttons (no checks): for a start that was a forced duel."""
    g = s.g
    g.stop()
    g.start()
    s.quiet = False
    s.wait(10)
    for k in (0, 0, 0, 0):
        mode, tl = s.wait_nav(is_screen(1), 10)
        t = sorted(tl, key=lambda t: (t.y0, t.x0))[0]
        g.click(*t.center)
        s.wait(3)
    g.key("return")
    s.wait(12)
    s.quiet = True


def encounter(s):
    mode, tl = s.wait_nav(lambda m, t: m == "screen" and len(t) == 2 and t[0].label == "line 0", 6)
    if mode != "screen" or len(tl) != 2:
        print("NOTE  no encounter at the start this time: not checked", flush=True)
        return
    s.shot("encounter")
    gold = s.gold()
    check(all(t.kind == K_MENU for t in tl) and tl[0].y1 == tl[1].y0, "the encounter's text menu: two lines one above the other (%s)" % tl)
    n = s.dpad_to(lambda tl: tl[1] if len(tl) > 1 else None)
    check(n is not None and n <= 2, "the D-pad reaches the second line, 'Pay N gold' (%s presses)" % n)
    s.press_a(4)
    mode, tl = s.nav()
    check(s.gold() < gold, "A on it paid: gold %s -> %s" % (gold, s.gold()))
    check(mode in ("none", "screen"), "the encounter is over (mode %s)" % mode)
    s.wait(3)


def castle(s):
    to_map(s)
    s.teleport(4, 0)
    mode, tl = s.wait_nav(lambda m, t: m == "screen" and len(t) == 2, 8)
    s.shot("castle")
    check(mode == "screen" and len(tl) == 2 and all(t.kind == K_MENU for t in tl), "a castle's gate is a text menu of two lines (%s)" % [t.label for t in tl])
    if len(tl) != 2:
        return
    n = s.dpad_to(lambda tl: tl[1] if len(tl) > 1 else None)
    check(n is not None, "down to 'Yes, enter the castle' (%s presses)" % n)
    p = s.g.dpad("up")
    check(p is not None and tl[0].contains(*p), "up goes back to 'Well... No.'")
    p1 = s.g.dpad("up")
    check(p1 == p, "up from the first line stays (no wrapping)")
    party = s.mem(PARTY_X, 2)
    s.press_a(4)
    mode, tl = s.nav()
    check(mode in ("none", None) and not tl, "A on 'No': back on the map, the D-pad is the arrow keys again (mode %s)" % mode)
    check(s.mem(PARTY_X, 2) == party, "and the party is where it was")
    s.shot("castle_no")


def village(s):
    g = s.g
    to_map(s)
    s.teleport(1, 0)
    mode, tl = s.wait_nav(is_screen(9), 10)
    s.shot("village")
    check(mode == "screen" and len(tl) == 9, "a village: 9 targets, its five buttons and the map's four (%s, %d)" % (mode, len(tl)))
    s.hover_check(tl, "the village")
    # the bottom left button of the five is "Buy 10 food", the top left "Buy Cards"
    five = lambda tl: sorted([t for t in tl if t.x0 > 0.05 * s.w], key=lambda t: (t.y0, t.x0))
    food_btn = lambda tl: five(tl)[3] if len(five(tl)) == 5 else None            # (134,374): after the two top ones, the middle one, then the lower left
    gold, food = s.gold(), s.food()
    n = s.dpad_to(food_btn)
    check(n is not None, "the D-pad reaches 'Buy 10 food' (%s presses)" % n)
    s.press_a(3)
    check(s.gold() == gold - 15 and s.food() == food + 10, "one A press bought food once: gold %d -> %d, food %d -> %d" % (gold, s.gold(), food, s.food()))
    cards_btn = lambda tl: five(tl)[0] if len(five(tl)) == 5 else None
    n = s.dpad_to(cards_btn)
    check(n is not None, "the D-pad reaches 'Buy Cards' (%s presses)" % n)
    s.press_a(4)
    mode, tl = s.wait_nav(lambda m, t: m == "screen" and any(x.kind == K_CARD for x in t), 6)
    if not any(x.kind == K_CARD for x in tl):          # the card seller's hint ("If you combine this ... you can make ...") waits for a click first
        print("NOTE  the card seller's hint is up (no targets, a click goes on): A", flush=True)
        s.press_a(3)
        mode, tl = s.wait_nav(lambda m, t: m == "screen" and any(x.kind == K_CARD for x in t), 8)
    s.shot("buycards")
    cards = [t for t in tl if t.kind == K_CARD]
    check(len(cards) >= 3 and sum(1 for t in tl if t.kind == K_BUTTON) == 1, "Cards for Sale: the cards (%d) and Done are targets" % len(cards))
    gold = s.gold()
    n = s.dpad_to(lambda tl: sorted([t for t in tl if t.kind == K_CARD], key=lambda t: t.x0)[0] if tl else None)
    check(n is not None, "the D-pad reaches the first card (%s presses)" % n)
    s.press_a(2.5)
    mode, tl2 = s.nav()
    check(not [t for t in tl2 if t.kind == K_CARD], "the question 'Buy for N gold? (Y/N)' has no targets (mode %s): it is a key prompt" % mode)
    s.shot("buy_question")
    s.press_a(3)                                       # A answers it: yes (yesno.c)
    mode, tl3 = s.wait_nav(lambda m, t: m == "screen" and any(x.kind == K_CARD for x in t), 8)
    check(s.gold() < gold and len([t for t in tl3 if t.kind == K_CARD]) == len(cards) - 1, "A answered yes: gold %d -> %d and the card is gone from the targets (%d left)" % (gold, s.gold(), len([t for t in tl3 if t.kind == K_CARD])))
    n = s.dpad_to(lambda tl: [t for t in tl if t.kind == K_BUTTON][0] if tl else None)
    check(n is not None, "the D-pad reaches Done (%s presses)" % n)
    s.press_a(3)
    mode, tl = s.wait_nav(is_screen(9), 8)
    check(mode == "screen" and len(tl) == 9, "Done is back at the village (%d targets)" % len(tl))
    # leave: the lower right button
    n = s.dpad_to(lambda tl: sorted([t for t in tl if t.x0 > 0.05 * s.w], key=lambda t: (t.y0, t.x0))[-1] if tl else None)
    check(n is not None, "the D-pad reaches 'Leave the village' (%s presses)" % n)
    s.press_a(4)
    mode, tl = s.nav()
    check(mode in ("none", None), "A on it: the map (mode %s)" % mode)


def worldmap(s):
    to_map(s)
    s.teleport(1, 1)
    mode, tl = s.wait_nav(is_screen(9), 10)
    left = sorted([t for t in tl if t.x0 < 0.05 * s.w], key=lambda t: t.y0)
    if len(left) != 4:
        check(False, "the village's four map buttons are targets")
        return
    n = s.dpad_to(lambda tl: sorted([t for t in tl if t.x0 < 0.05 * s.w], key=lambda t: t.y0)[1] if tl else None)
    check(n is not None, "the D-pad reaches the world map button (%s presses)" % n)
    s.press_a(4)
    mode, tl = s.wait_nav(lambda m, t: m == "screen" and len(t) == 4 and all(x.y1 < 0.15 * s.h for x in t), 8)
    s.shot("worldmap")
    check(mode == "screen" and len(tl) == 4, "the world map: Plain Map, Info Map, City Info and Done are targets (%d)" % len(tl))
    s.hover_check(tl, "the world map")
    n = s.dpad_to(lambda tl: max(tl, key=lambda t: t.x0) if tl else None)
    check(n is not None, "right along the row to Done (%s presses)" % n)
    s.press_a(3)
    mode, tl = s.wait_nav(is_screen(9), 8)
    check(len(tl) == 9, "Done is back at the village")


def clues(s):
    for d in range(15):
        s.g.poke(DUNGEONS + 0x10 + 0x30 * d, 7)
    n = s.dpad_to(lambda tl: sorted([t for t in tl if t.x0 < 0.05 * s.w], key=lambda t: t.y0)[2] if tl else None)
    check(n is not None, "the D-pad reaches the dungeon-door button (%s presses)" % n)
    s.press_a(4)
    mode, tl = s.wait_nav(lambda m, t: m == "screen" and sum(1 for x in t if x.kind == K_ROW) >= 6, 8)
    s.shot("clues")
    rows = [t for t in tl if t.kind == K_ROW]
    check(len(rows) == 12, "the clue list: 12 rows are targets (%d) and %d buttons (Done, the arrows)" % (len(rows), len(tl) - len(rows)))
    if len(rows) != 12:
        return
    check(all(a.y1 - a.y0 > 40 for a in rows) and len({t.x0 for t in rows}) == 2, "two columns of six rows")
    rows.sort(key=lambda t: (t.y0, t.x0))
    n = s.dpad_to(lambda tl: sorted([t for t in tl if t.kind == K_ROW], key=lambda t: (t.y0, t.x0))[5] if tl else None)
    check(n is not None, "the D-pad reaches the third row of the right column... (%s presses)" % n)
    s.press_a(4)
    mode, tl2 = s.wait_nav(lambda m, t: m == "screen" and not any(x.kind == K_ROW for x in t), 8)
    s.shot("clue_page")
    check(mode == "screen" and len(tl2) >= 1 and not any(x.kind == K_ROW for x in tl2), "A on a row opens its page: Done is a target (%d)" % len(tl2))
    n = s.dpad_to(lambda tl: tl[0] if tl else None)
    s.press_a(3)
    mode, tl3 = s.wait_nav(lambda m, t: m == "screen" and sum(1 for x in t if x.kind == K_ROW) >= 6, 8)
    check(sum(1 for x in tl3 if x.kind == K_ROW) == 12, "Done goes back to the list")
    done = [t for t in tl3 if t.kind == K_BUTTON and t.x0 > 0.6 * s.w and t.y1 < 0.2 * s.h]
    if done:
        s.dpad_to(lambda tl: [t for t in tl if t.kind == K_BUTTON and t.x0 > 0.6 * s.w and t.y1 < 0.2 * s.h][0] if tl else None)
        s.press_a(3)
        mode, tl4 = s.wait_nav(is_screen(9), 8)
        check(len(tl4) == 9, "Done leaves the clues: the village again")


def stats(s):
    n = s.dpad_to(lambda tl: sorted([t for t in tl if t.x0 < 0.05 * s.w], key=lambda t: t.y0)[3] if tl else None)
    check(n is not None, "the D-pad reaches the wizard button (%s presses)" % n)
    s.press_a(5)
    mode, tl = s.wait_nav(lambda m, t: m == "screen" and len(t) >= 6 and any(x.y0 < 0.1 * s.h and x.x0 > 0.5 * s.w for x in t), 10)
    s.shot("stats")
    check(mode == "screen" and len(tl) >= 8, "Wiz Stats: the table's buttons are targets (%d)" % len(tl))
    s.hover_check(tl, "Wiz Stats")
    top = sorted([t for t in tl if t.y1 < 0.1 * s.h], key=lambda t: t.x0)
    check(len(top) == 3, "Wiz Stats, Journal and Done on the top row")
    if len(top) == 3:
        journal_rounds(s, 8)
        n = s.dpad_to(lambda tl: sorted([t for t in tl if t.y1 < 0.1 * s.h], key=lambda t: t.x0)[2])
        s.press_a(4)
        mode, tl2 = s.wait_nav(is_screen(9), 10)
        check(len(tl2) == 9, "Done leaves the stats: the village (%d targets)" % len(tl2))


def journal_rounds(s, rounds):
    """The Journal (the loop at 0x40b4e8) and its Done, `rounds` times with the D-pad and A: every Done must come back to Wiz Stats. The press used to be lost about half the time (docs/notes/journal-done.md):
    the loop reads the button again after its pass and takes a press that came in meanwhile for "next page"."""
    bad = []
    for i in range(rounds):
        n = s.dpad_to(lambda tl: sorted([t for t in tl if t.y1 < 0.1 * s.h], key=lambda t: t.x0)[1])
        s.press_a(2.5)
        mode, tl = s.wait_nav(lambda m, t: m == "screen" and len(t) == 2, 8)
        if not (mode == "screen" and len(tl) == 2):
            bad.append("round %d: the Journal did not open (%d targets)" % (i, len(tl)))
            break
        n = s.dpad_to(lambda tl: [t for t in tl if t.y1 < 0.1 * s.h][0])
        s.press_a(1.5)
        mode, tl = s.wait_nav(lambda m, t: m == "screen" and len(t) >= 8, 4)
        if len(tl) < 8:
            bad.append("round %d: Done left the Journal on the screen (%d targets)" % (i, len(tl)))
            break
    s.shot("journal")
    check(not bad, "the Journal opens and its Done leaves it, %d times in a row, each with one A%s" % (rounds, (" (" + bad[0] + ")") if bad else ""))


def deck(s):
    mode, tl = s.nav()
    if mode == "screen":                               # still in the village: leave by its last button, then F1 on the map
        s.dpad_to(lambda tl: sorted([t for t in tl if t.x0 > 0.05 * s.w], key=lambda t: (t.y0, t.x0))[-1])
        s.press_a(4)
    s.g.cmd("key f1")
    mode, tl = s.wait_nav(lambda m, t: m == "deck", 10)
    s.shot("deck")
    cards = [t for t in tl if t.kind == K_CARD]
    buttons = [t for t in tl if t.kind == K_BUTTON]
    check(mode == "deck" and len(cards) >= 10 and len(buttons) == 5, "the deck builder: %d cards (strips) and %d buttons (Stats, three decks, Exit) are targets" % (len(cards), len(buttons)))
    tw = s.w
    check(all(t.x1 <= tw and t.y1 <= s.h for t in tl), "all of them on the screen")
    n = s.dpad_to(lambda tl: [t for t in tl if t.kind == K_CARD][0] if tl else None)
    check(n is not None, "the D-pad reaches the first card (%s presses)" % n)
    ups = 0
    p = s.pos()
    for _ in range(3):
        q = s.g.dpad("down")
        if q is not None and q[1] > p[1]:
            ups += 1
        p = q
    check(ups == 3, "down walks the strips of the deck")
    n = s.dpad_to(lambda tl: max([t for t in tl if t.kind == K_BUTTON], key=lambda t: t.x0) if tl else None)
    check(n is not None, "the D-pad reaches Exit (%s presses)" % n)
    s.press_a(5)
    mode, tl = s.wait_nav(lambda m, t: m != "deck", 10)
    check(mode != "deck", "A on Exit leaves the deck builder (mode %s)" % mode)


def maponly(s):
    s.wait(2)
    mode, tl = s.nav()
    check(mode in ("none", None) and not tl, "on the map there is nothing for the D-pad to navigate (mode %s)" % mode)
    p0 = s.mem(PARTY_X, 2)
    s.g.pad("button down down")
    s.wait(1.5)
    s.g.pad("button down up")
    s.wait(0.5)
    p1 = s.mem(PARTY_X, 2)
    check(p0 is not None and p1 is not None and p1 != p0, "the D-pad is still the arrow keys on the map: the party walked %s -> %s" % (p0, p1))
    # B is a right click: the game's menu of the map (Save, Quit, the deck, the map, the cities, the clues, the stats, the wizard's stats), which the D-pad walks: the way to the map's own buttons
    s.g.pad_press("b")
    mode, tl = s.wait_nav(lambda m, t: m == "screen" and len(t) >= 8, 6)
    s.shot("map_menu")
    check(mode == "screen" and len(tl) == 8 and all(t.kind == K_MENU for t in tl), "B on the map opens the game's menu: its 8 lines are targets (%d)" % len(tl))
    if len(tl) == 8:
        n = s.dpad_to(lambda tl: tl[5])
        check(n is not None, "the D-pad reaches 'See Dungeon Clues' (%s presses)" % n)
        s.g.pad_press("back")                          # Escape closes it
        s.wait(2)
        mode, tl = s.nav()
        check(mode in ("none", None), "Back closes the menu (mode %s)" % mode)


STEPS = [("title", title_and_newgame), ("encounter", encounter), ("map", maponly), ("castle", castle), ("village", village), ("worldmap", worldmap), ("clues", clues), ("stats", stats), ("deck", deck)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", default="1024x768")
    ap.add_argument("--workdir", default="/tmp/screen_nav_play")
    ap.add_argument("--shots")
    ap.add_argument("--only", help="comma separated: title is always run first; the village, worldmap, clues and stats go together")
    a = ap.parse_args()
    s = Session(a)
    only = set(a.only.split(",")) if a.only else None
    try:
        for name, fn in STEPS:
            if only and name not in only and name != "title":
                continue
            print("--- %s (%s)" % (name, a.res), flush=True)
            fn(s)
            if not s.g.alive():
                check(False, "the program died in %s" % name)
                break
    finally:
        s.g.stop()
    print("%d failed" % failures)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

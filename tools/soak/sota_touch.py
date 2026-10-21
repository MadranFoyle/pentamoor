#!/usr/bin/env python3
"""sota_touch.py: Spells of the Ancients 2.15 with fingers (touch.c's gestures through the control pipe's `tdown`, `tmove`, `tup`), headless. What a person does on an iPad, as far as the program can be
told it: the finger steps go through the same code (touch.c, then front.c) as SDL's finger events, so the game's side is real; the iOS app, the screen and the real finger are not.

    python3 tools/soak/sota_touch.py [--workdir /tmp/sota_touch]

A new game (the mouse: the new game's screens are not what is tested here), the party put on a village (poke), then with fingers only:

  village   a tap on "Buy Cards", a tap on a card (the game's "Buy for N gold? (Y/N)" question): a long press (500 ms, a right click) answers NO, a tap (a left click) answers YES
  deck      a tap on "Edit deck/Sell cards", a long press on a card of the deck editor opens its menu ("Sell Card for N"), a tap on that row sells (no question in 2.15)
  duel      the first encounter's Duel by a tap, the dialogs by taps, a long press on a card of the hand opens its menu (with "View in full card" in 2.15 as in 1.0)

Prints one line per check, exits 1 if one failed. Needs the 2.15 install and the runtime (PORT_TOUCH=1: the iOS app has touch on by itself).
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sota_pad_play as sp  # noqa: E402
import sota_soak  # noqa: E402
sp_soak_ppm = sota_soak.read_ppm

failures = 0
K_CARD, K_BUTTON = 1, 2


def check(ok, what):
    global failures
    print("%s  %s" % ("ok  " if ok else "FAIL", what), flush=True)
    if not ok:
        failures += 1
    return ok


class Fingers:
    def __init__(self, g):
        self.g = g

    def tap(self, x, y, hold=0.12):
        self.g.cmd("tdown 1 %d %d" % (x, y))
        time.sleep(hold)
        self.g.cmd("tup 1 %d %d" % (x, y))

    def long_press(self, x, y, hold=0.8):
        self.g.cmd("tdown 1 %d %d" % (x, y))
        time.sleep(hold)
        self.g.cmd("tup 1 %d %d" % (x, y))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workdir", default="/tmp/sota_touch")
    a = ap.parse_args()
    import types
    s = sp.Session(types.SimpleNamespace(res="1024x768", workdir=a.workdir, shots=os.path.join(a.workdir, "shots")))
    s.extra_env = {"PORT_TOUCH": "1"}
    try:
        print("--- a new game (pad: sota_pad_play.newgame)", flush=True)
        ok = sp.newgame(s)
        g = s.g
        if not ok:
            check(False, "a new game to the map")
            return 1
        s.keeper_on.set()
        f = Fingers(g)
        # ---- the village ----
        check(sp.enter_village(s), "the party is in a village (9 targets)")
        mode, tl = s.nav()
        five = sp.five(s, tl)
        gold = s.gold()
        f.tap(*five[0].center)                           # Buy Cards
        mode, tl = s.wait_nav(lambda m, t: m == "screen" and any(x.kind == K_CARD for x in t), 6)
        if not any(x.kind == K_CARD for x in tl):
            f.tap(s.w // 2, s.h // 2)                    # the card seller's hint waits for a click
            mode, tl = s.wait_nav(lambda m, t: m == "screen" and any(x.kind == K_CARD for x in t), 8)
        cards = sorted([t for t in tl if t.kind == K_CARD], key=lambda t: t.x0)
        check(len(cards) >= 3, "a finger on 'Buy Cards': the cards for sale (%d)" % len(cards))
        off = g.log_size()
        f.tap(*cards[0].center)                          # the card: the question
        time.sleep(2.5)
        log = g.read_log(off)
        check("(Y/N) question: asking" in log, "a tap on a card asks 'Buy for N gold? (Y/N)'")
        off = g.log_size()
        f.long_press(*cards[0].center)                   # a long press is a right click: NO
        time.sleep(3)
        log = g.read_log(off)
        check("with 'n'" in log and s.gold() == gold, "a long press answered NO (the log says 'n'; gold %d -> %d)" % (gold, s.gold()))
        mode, tl = s.wait_nav(lambda m, t: m == "screen" and any(x.kind == K_CARD for x in t), 6)
        cards = sorted([t for t in tl if t.kind == K_CARD], key=lambda t: t.x0)
        f.tap(*cards[0].center)
        time.sleep(2.5)
        off = g.log_size()
        f.tap(*cards[0].center)                          # a tap is a left click: YES
        time.sleep(3)
        log = g.read_log(off)
        check("with 'y'" in log and s.gold() < gold, "a tap answered YES (the log says 'y'; gold %d -> %d)" % (gold, s.gold()))
        # ---- the deck editor ----
        mode, tl = s.wait_nav(lambda m, t: m == "screen" and any(x.kind == K_BUTTON for x in t), 6)
        f.tap(*[t for t in tl if t.kind == K_BUTTON][0].center)               # Done
        mode, tl = s.wait_mode(("screen",), 8, 9)
        f.tap(*sp.five(s, tl)[1].center)                 # Edit deck/Sell cards
        mode, tl = s.wait_mode(("deck",), 12, 10)
        check(mode == "deck", "a tap on 'Edit deck/Sell cards': the deck editor (%s)" % mode)
        cardt = [t for t in tl if t.kind == K_CARD]
        gold = s.gold()
        f.long_press(*cardt[1].center)
        mode, tl = s.wait_mode(("menu",), 4, 1)
        check(mode == "menu" and tl and tl[0].label.startswith("Sell Card for"), "a long press on a card opens its menu: %s" % [t.label for t in tl])
        if mode == "menu" and tl:
            time.sleep(0.5)
            f.tap(*tl[0].center)
            time.sleep(2.5)
            check(s.gold() > gold, "a tap on the row sold the card (gold %d -> %d)" % (gold, s.gold()))
        mode, tl = s.nav()
        f.tap(*max([t for t in tl if t.kind == K_BUTTON], key=lambda t: t.x0).center)         # Done
        time.sleep(3)
        mode, tl = s.nav()
        if mode == "dialog":                                                                  # "Extra Cards": the dialog's own button
            f.tap(*[t for t in tl if t.label.startswith("Remove")][0].center)
        mode, tl = s.wait_mode(("screen",), 10, 9)
        f.tap(*sp.five(s, tl)[-1].center)                                                      # Leave the village
        s.wait(3)
        # ---- a duel ----
        print("--- a duel (the encounter and the dialogs with the pad: sota_pad_play.start_duel)", flush=True)
        sp_ok = sp.start_duel(s)
        if sp_ok:
            for _ in range(8):                                                                # the last dialogs ("Start the duel") can come after the board is up
                s.wait(2)
                mode, tl = s.nav()
                if mode != "dialog" or not tl:
                    break
                sp.dialog_step(s, tl)
            s.wait(2)
            t = g.windows(timeout=10)
            hand = sp.hand_windows(t)
            check(len(hand) >= 5, "the board: a hand of %d cards" % len(hand))
            c = (hand[0].x0 + 40, hand[0].y0 + 6)
            fc = [w for w in t.find("MAGICGAME_FullCardClass") if w.visible and not w.empty][0]
            import hashlib
            def big():
                ppm = os.path.join(g.workdir, "big.ppm")
                if os.path.exists(ppm):
                    os.unlink(ppm)
                g.cmd("shot " + ppm)
                end = time.time() + 6
                while time.time() < end and not (os.path.exists(ppm) and os.path.getsize(ppm) > 1000):
                    time.sleep(0.1)
                time.sleep(0.4)
                im = sp_soak_ppm(ppm)
                w, h, d = im
                return hashlib.md5(b"".join(d[(y * w + max(fc.x0, 0)) * 3:(y * w + fc.x1) * 3] for y in range(fc.y0 + 20, fc.y1 - 20))).hexdigest()[:8]
            before = big()
            f.long_press(*c)
            mode, tl = s.wait_mode(("menu",), 4, 2)
            check(mode == "menu" and len(tl) >= 2, "a long press on a card of the hand opens its menu: %s" % [t.label for t in tl][:6])
            view = [t for t in tl if "full card" in t.label.lower()]
            check(bool(view), "the menu has 'View in full card' (the command LB posts)")
            if view:
                time.sleep(0.5)
                f.tap(*view[0].center)
                time.sleep(1.2)
                after = big()
                check(after != before, "a tap on it showed the card in the Full-size card window at once (%s -> %s)" % (before, after))
    finally:
        if s.g is not None:
            s.g.stop()
    failures_all = failures + sp.failures
    print("%d failed" % failures_all if failures_all else "all checks passed")
    return 1 if failures_all else 0


if __name__ == "__main__":
    sys.exit(main())

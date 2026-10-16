#!/usr/bin/env python3
"""pad_realtime.py: the pad in a duel at a person's speed, headless, with PORT_PAD_LOG=1 on: what the scripted runs (nav_play.py, pad_play.py) cannot say.

    python3 tools/soak/pad_realtime.py [--res 1024x768] [--workdir /tmp/pad_realtime] [--seed N] [--env "K=V ..."]

The scripted runs press a button and let it go in the same instant, wait for the answer after every press, and put the pointer where they want it with the *mouse*. A person holds a button for
100 to 150 ms, presses the next after 400 ms or more, holds a direction to run along a row of cards, moves the pointer with the stick, and never waits for anything. This plays a duel that way,
with the pad only, after the duel has been set up the way nav_play.py sets it up (a board with permanents on both sides), and reads the program's own log (`PORT_PAD_LOG`, docs/notes/steamdeck.md)
for what the program thought it was doing:

  * the stick brings the pointer near a card of the hand, and the D-pad, pressed for 120 ms every 450 ms, walks from target to target: every press lands on the middle of a target, and no
    arrow key goes to the game;
  * a D-pad direction held for 1.3 s runs along the targets (the repeat) and ends on a target;
  * A, held 150 ms, on the Done button (the stick brings the pointer there) passes the phase;
  * B, held 150 ms, opens a card's menu, the D-pad walks its rows and Back closes it;
  * the D-pad's mode in the log stays "duel" from the first main phase on (it never drops to "none": that would be arrow keys, which the duel ignores), the game's own (Y/N) question, which
    turns A and B into the keys y and n, is never reported while no question is asked, and the game opened no message box.

Prints one line per check and exits 1 if one failed. --env adds to the game's environment (a Steam Deck's settings: "PORT_STEAMDECK=1 PORT_FULLSCREEN=1 SDL_VIDEODRIVER=x11 DISPLAY=:1" on an
X server). Needs the installed game and the saved game (sources/installed, sources/emu_overlay), as the soak does.
"""
import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nav_play  # noqa: E402
from nav_play import Nav, Player, check, pad_start  # noqa: E402

HOLD = 0.12          # a button is down this long (s)
GAP = 0.45           # and the next press comes this long after


def press(g, name, hold=HOLD, gap=GAP):
    """A button pressed and let go the way a hand does it."""
    g.pad("button %s down" % name)
    time.sleep(hold)
    g.pad("button %s up" % name)
    time.sleep(gap)


def settle(g, tries=8):
    """The pad cursor's place once it has stopped moving."""
    last = g.pad_pos()
    for _ in range(tries):
        time.sleep(0.15)
        p = g.pad_pos()
        if p is None:
            return None
        if p[:2] == last[:2]:
            return p[:2]
        last = p
    return last[:2]


def log_lines(g, pattern):
    """The text after "padlog: " of the lines of the program's log that start with `pattern`."""
    return re.findall(r"^\d\d:\d\d:\d\d\.\d+ padlog: (%s.*)$" % pattern, g.read_log(0), re.M)


def real_time(g, res):
    nv = Nav(g, res)
    mode, targets = nv.targets()
    check(mode == "duel", "the program is navigating a duel (mode %s, %d targets)" % (mode, len(targets)))
    if mode != "duel":
        return
    hand = sorted([x for x in targets if x.label == "Hand Card"], key=lambda x: x.y0)
    done = [x for x in targets if x.kind == nav_play.K_BUTTON and not x.label][0]

    # 1. the stick brings the pointer near the hand
    p = g.pad_goto(hand[-1].center[0] - 70, hand[-1].center[1] - 10)
    print("      the stick left the pointer at %s (the last card of the hand is at %s)" % (p[:2] if p else None, hand[-1].center), flush=True)

    # 2. the D-pad at a person's speed: 12 presses, 120 ms down, 450 ms apart, along the hand and out of it
    bad = []
    for d in ("left", "up", "up", "down", "left", "right", "up", "down", "down", "left", "up", "right"):
        press(g, d)
        pos = settle(g)
        mode, tl = nv.targets()
        if mode != "duel" or not any(x.center == pos for x in tl):
            bad.append((d, pos, mode))
    check(not bad, "12 D-pad presses at a person's speed land on the middle of a target (%d did not: %s)" % (len(bad), bad[:3]))
    keys = log_lines(g, r"pad: key down")
    check(not keys, "and no arrow key went to the game (%d: %s)" % (len(keys), keys[:2]))

    # 3. a direction held runs along the targets
    nv.put(*hand[-1].center)
    p0 = g.pad_pos()[:2]
    g.pad("button up down")
    time.sleep(1.3)
    g.pad("button up up")
    time.sleep(0.4)
    p1 = settle(g)
    mode, tl = nv.targets()
    check(p1 != p0 and any(x.center == p1 for x in tl), "up held for 1.3 s ran along the targets: %s -> %s, on a target" % (p0, p1))
    check(g.windows() is not None and g.alive(), "the program answers")

    # 4. A held 150 ms on the Done button, reached with the stick (the D-pad's way to it is nav_play.py's), passes the phase
    g.pad_goto(*done.center)
    check(g.hit(*g.pad_pos()[:2]) == done.id, "the stick brought the pointer onto the Done button %s" % (done.center,))
    t = g.windows()
    title0 = t.bar()[0].title if t and t.bar() else None
    title1 = title0
    for _ in range(3):                               # (a phase that waits for a second Done, as the attack's does, is pressed again)
        press(g, "a", hold=0.15, gap=2.2)
        t = g.windows()
        title1 = t.bar()[0].title if t and t.bar() else None
        if title1 != title0:
            break
    check(title1 != title0, "A held 150 ms on Done passed the phase: %r -> %r" % (title0, title1))

    # 5. B held 150 ms opens a card's menu; the D-pad walks its rows; Back closes it
    for _ in range(10):                              # on to a main phase
        t = g.windows()
        if t is None or not t.bar() or "main phase" in t.bar()[0].title.lower() or t.dialogs():
            break
        press(g, "a", hold=0.15, gap=2.0)
    mode, tl = nv.targets()
    cards = sorted([x for x in tl if x.label == "Hand Card"], key=lambda x: x.y0)
    if cards:
        nv.put(*cards[len(cards) // 2].center)
        press(g, "b", hold=0.15, gap=1.0)
        t = g.windows()
        check(len(t.items) > 0, "B held 150 ms opened the card's menu (%d rows)" % len(t.items))
        if t.items:
            before = g.pad_pos()[:2]
            press(g, "down")
            after = settle(g)
            check(after != before, "the D-pad walks the menu's rows: %s -> %s" % (before, after))
            press(g, "back")
            time.sleep(0.6)
            check(not g.windows().items, "Back closed the menu")

    # 6. what the program's log says about the whole run
    modes = log_lines(g, r"D-pad mode: ")
    print("      D-pad modes in the log: %s" % [m.replace("D-pad mode: ", "") for m in modes], flush=True)
    seq = [m.split(" -> ")[1] for m in modes]
    first_duel = seq.index("duel") if "duel" in seq else None
    drops = [s for s in (seq[first_duel:] if first_duel is not None else []) if s in ("none", "screen", "deck")]
    check(first_duel is not None and not drops, "the D-pad mode never fell to none, screen or deck once the duel was on (%s)" % (drops,))
    asks = log_lines(g, r"the game's \(Y/N\) question: asking")
    check(not asks, "the game's (Y/N) question was never reported (%d times)" % len(asks))
    answered = log_lines(g, r"the press answered")
    check(not answered, "no click was turned into y or n (%d)" % len(answered))
    boxes = re.findall(r"^MessageBox: .*$", g.read_log(0), re.M)
    check(not boxes, "the game opened no message box (%d: %s)" % (len(boxes), boxes[:2]))
    check(g.alive(), "the program is still running")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", default="1024x768", choices=["640x480", "800x600", "1024x768"])
    ap.add_argument("--workdir", default="/tmp/pad_realtime")
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--shots", default=None)
    ap.add_argument("--env", default="", help='the game\'s environment, "K=V K=V" (added to $SOAK_ENV)')
    a = ap.parse_args()
    if a.env:
        os.environ["SOAK_ENV"] = (os.environ.get("SOAK_ENV", "") + " " + a.env).strip()
    os.environ["PORT_PAD_LOG"] = "stderr"          # to the game's log, which the checks read
    os.makedirs(a.workdir, exist_ok=True)
    p = Player(a)
    g = p.new_game()
    try:
        p.to_ante()
        check(pad_start(p, g, a.res), "a duel started with the D-pad in the dialogs (the coin toss, the mulligan and ante)")
        t = p.populate()
        check(t is not None, "the board has several permanents on both sides")
        if t is None:
            return 1
        real_time(g, a.res)
    finally:
        g.stop()
    print("%d check(s) failed" % nav_play.failures if nav_play.failures else "all checks passed")
    return 1 if nav_play.failures else 0


if __name__ == "__main__":
    sys.exit(main())

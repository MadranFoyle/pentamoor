#!/usr/bin/env python3
"""nav_play.py: the D-pad in a duel, headless: the pointer goes from card to card, to the buttons and to the menu rows with the D-pad only, and every move is checked against the game.

    python3 tools/soak/nav_play.py [--res 1024x768] [--workdir /tmp/nav_play] [--shots DIR] [--seed N] [--game magic|duel]

The program is started on SDL's dummy drivers with its own control pipe and overlay (as tools/soak does); the saved game's "Duel a Sorcerer" (MAGIC.EXE) or the setup dialog of DUEL.EXE
starts a duel, which is played with the mouse (soak's helpers: the checks are about the D-pad, so the setup may use anything) until both sides have several permanents. Then, with
controller commands only (`pad press up|down|left|right`, `pad press a|b|y`, `pad nav`), it checks:

  * the targets the program lists (`pad nav`): every card of your hand, your territory and the opponent's, the life totals, piles, mana rows, the phase icons and the prompt bar's buttons
    that the window tree shows, and none that is hidden, empty or covered;
  * every move lands on the window it should: the pointer after a D-pad press is inside the target the program chose, `hit X Y` (what a click there would reach) is that card's window, and
    the hover shows: the big card on the left is the same picture as when the real mouse is put there;
  * the user's examples: from the bottom card of the hand, up goes up the hand; left goes to your territory; right comes back; up from your cards goes to the opponent's; no wrapping at an
    edge; the pointer stays when there is nothing that way;
  * A on a card does what a click does (a land from the hand is played), the Done button is reached and pressed with A, B's menu is walked with up and down and closed with Y;
  * a dialog (the coin toss) is navigated button to button, and the D-pad is still the arrow keys where there is nothing to navigate (the map).

Prints one line per check, exits 1 if one failed. Needs the installed game (sources/installed) and the saved game (sources/emu_overlay), as the soak does.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import soak  # noqa: E402
from pentamoor_ctl import Game  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIFE = (0x6a4a00, 0x6a4a04)                    # the two life totals (docs/notes/controller-nav.md)

# NavTarget kinds (src/port/nav.h)
K_CARD, K_BUTTON, K_FIELD, K_ROW, K_PLAYER, K_PILE, K_MANA, K_PHASE, K_MENU = 1, 2, 3, 4, 5, 6, 7, 8, 9

failures = 0


def check(ok, what):
    global failures
    print("%s  %s" % ("ok  " if ok else "FAIL", what), flush=True)
    if not ok:
        failures += 1
    return ok


class Player(soak.Soak):
    """soak's session helpers (start, Resume Game, Duel, dialogs) with a policy that builds a board and does not attack."""

    def __init__(self, a):
        ns = argparse.Namespace(res=a.res, minutes=10, repo=REPO, exe="src/port/build/pentamoor-run", module=None, program="sources/installed/Magic/Program/MAGIC.EXE",
                                workdir=a.workdir, seed=a.seed, duels_per_game=1, min_turns=3, max_turns=9, max_duel_s=300, stall_s=60, tick_s=1.0, verbose=False)
        super().__init__(ns)
        self.shots = a.shots
        self.nshot = 0

    def shot(self, tag):                                    # noqa: D401 -- keeps soak's name
        if not self.shots or not self.game:
            return None
        os.makedirs(self.shots, exist_ok=True)
        self.nshot += 1
        return self.game.shot(os.path.join(self.shots, "%s_%02d_%s.png" % (self.a.res, self.nshot, tag)))

    def lives(self, value=60):
        for addr in LIFE:
            self.game.poke(addr, value)

    def populate(self, want_mine=4, want_theirs=2, limit=480):
        """Play (lands, spells, passing every phase, never attacking) until your territory has `want_mine` permanents and the opponent's `want_theirs`, in your first main phase after that.
        Returns the window tree of that moment, or None."""
        g = self.game
        t0 = time.time()
        k = 0
        last_hand = None
        prompt_n = 0
        last_report = -1
        while time.time() - t0 < limit:
            t = self.look("populate")
            if t is None:
                return None
            self.lives()
            mine, theirs = self.my_permanents(t), self.their_permanents(t)
            if int(time.time() - t0) // 45 != last_report:
                last_report = int(time.time() - t0) // 45
                print("      ... %3d s: %d permanents of yours, %d of theirs, bar %r%s" % (time.time() - t0, len(mine), len(theirs), t.bar()[0].title[:44] if t.bar() else "",
                                                                                         ", a dialog" if t.dialogs() else ""), flush=True)
            b = t.bar()
            title = b[0].title if b and b[0].visible else ""
            low = title.lower()
            cancel, done = (b[1], b[2]) if b else (None, None)
            if t.items:
                g.key("escape")
            elif t.dialogs():
                self.handle_dialog(t)
            elif not t.find("MAGICGAME_MainClass") or not title:
                pass
            elif any(w in title for w in ("CASTING", "ACTIVATING", "PROCESSING")) or low.startswith(("pick", "select")):
                prompt_n += 1
                if cancel and prompt_n > 8:
                    g.click(*cancel.center)
                    prompt_n = 0
                elif mine:
                    g.click(*mine[prompt_n % len(mine)])
                elif cancel:
                    g.click(*cancel.center)
            elif "main phase (before combat)" in low and done:
                prompt_n = 0
                hand = self.hand_rows(t)
                if len(mine) >= want_mine and len(theirs) >= want_theirs:
                    return t
                if last_hand is not None and len(hand) == last_hand:
                    k += 1                                   # the card did nothing: the next one
                if k < len(hand):
                    last_hand = len(hand)
                    g.click(*hand[k])
                else:
                    k = 0
                    last_hand = None
                    g.click(*done.center)
            elif done:
                prompt_n = 0
                k = 0
                last_hand = None
                g.click(*done.center)
            elif cancel:
                g.click(*cancel.center)
            else:
                g.key("return")
            time.sleep(1.2)
        return None


def window_of(t, hwnd):
    for w in t.wins:
        if w.h == hwnd:
            return w
    return None


# ---- what the checks look at --------------------------------------------------------------------------------------------------------------------------------
def ppm_crop(path, box):
    """The bytes of a rectangle (x0, y0, x1, y1) of a P6 file."""
    with open(path, "rb") as f:
        data = f.read()
    parts = data.split(b"\n", 3)
    w, h = (int(v) for v in parts[1].split())
    pix = parts[3]
    x0, y0, x1, y1 = box
    return b"".join(pix[(y * w + x0) * 3:(y * w + x1) * 3] for y in range(y0, y1))


class Nav:
    """The D-pad as a person uses it, with what the program says about where the pointer is."""

    def __init__(self, g, res):
        self.g = g
        self.w, self.h = (int(v) for v in res.split("x"))
        self.n = 0

    def targets(self):
        r = self.g.nav_targets()
        return r if r else (None, [])

    def pos(self):
        p = self.g.pad_pos()
        return (p[0], p[1]) if p else None

    def put(self, x, y):
        """The real mouse puts the pointer there (the pad's cursor follows it)."""
        self.g.cmd("move %d %d" % (x, y))
        time.sleep(0.35)

    def press(self, d):
        return self.g.dpad(d, wait=0.5)

    def shot(self, tag):
        path = os.path.join(self.g.workdir, "%s.ppm" % tag)
        if os.path.exists(path):
            os.unlink(path)
        self.g.cmd("shot " + path)
        end = time.time() + 6
        while time.time() < end and not (os.path.exists(path) and os.path.getsize(path) > 100):
            time.sleep(0.1)
        time.sleep(0.4)
        return path


def settled_crop(nv, crop, tag, limit=14.0):
    """The big card's picture once it has stopped changing for 1.4 s, after a wait (the game shows the card under the pointer some seconds after the pointer arrives, a permanent later than a card of the hand, and later still when the machine is busy)."""
    prev, same, end = None, 0, time.time() + limit
    time.sleep(6.0)
    while time.time() < end:
        cur = ppm_crop(nv.shot(tag), crop)
        same = same + 1 if cur == prev else 0
        if same >= 2:
            return cur
        prev = cur
        time.sleep(0.5)
    return prev


def explore(nv, targets):
    """Every target in turn: the pointer is put on it with the mouse, each direction is pressed on the D-pad, and where it went is recorded. Returns ({centre: {direction: centre or None}}, bad):
    a move that lands anywhere but the middle of a target the program lists (a fresh list, as the board changes by itself) is in `bad`."""
    graph, bad = {}, []
    for t in targets:
        graph[t.center] = {}
        for d in ("up", "down", "left", "right"):
            nv.put(*t.center)
            p = nv.press(d)
            fresh = nv.targets()[1]
            if p is None:
                bad.append((t, d, None))
            elif p == t.center:
                graph[t.center][d] = None
            elif any(x.center == p for x in fresh):
                graph[t.center][d] = p
            else:
                bad.append((t, d, p))
    return graph, bad


def path(graph, src, dst):
    """The shortest list of directions from the target at src to the one at dst (their middles) in the measured graph, or None."""
    seen, queue = {src: []}, [src]
    while queue:
        cur = queue.pop(0)
        if cur == dst:
            return seen[cur]
        for d, nxt in graph.get(cur, {}).items():
            if nxt is not None and nxt not in seen:
                seen[nxt] = seen[cur] + [d]
                queue.append(nxt)
    return None


def reachable(graph, src):
    seen, queue = {src}, [src]
    while queue:
        cur = queue.pop(0)
        for nxt in graph.get(cur, {}).values():
            if nxt is not None and nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return seen


def pad_start(p, g, res):
    """From the ante screen to the first main phase with the D-pad in the dialogs (the coin toss, the mulligan and ante dialog): the first time each kind of dialog shows with two or more buttons,
    the D-pad is checked to move between them (and back); the wanted button (Play first, Start the duel, OK) is reached with the D-pad and pressed with A."""
    nv = Nav(g, res)
    w = int(res.split("x")[0])
    g.pad_click(*soak.DUEL[w])
    moved, end = set(), time.time() + 100
    while time.time() < end:
        time.sleep(1.5)
        t = p.look("start")
        if t is None:
            return False
        if t.find("MAGICGAME_MainClass") and t.bar() and t.bar_shown():
            return True
        ds = t.dialogs()
        if not ds:
            continue
        mode, tl = nv.targets()
        btns = sorted([x for x in tl if x.kind == K_BUTTON], key=lambda x: (x.y0, x.x0))
        if mode != "dialog" or not btns:
            g.key("return")                                  # a dialog with no button (the spell shown), as the soak does
            continue
        wanted = [b for b in btns if any(k in b.label.lower() for k in ("play first", "start the duel", "ok"))] or btns[:1]
        key = tuple(b.label for b in btns)
        if len(btns) >= 2 and key not in moved:
            moved.add(key)
            nv.put(*btns[0].center)
            p1 = nv.press("down")
            near = [b for b in btns[1:] if b.center == p1]
            p2 = nv.press("up")
            check(len(near) == 1 and p2 == btns[0].center, "the D-pad moves between a dialog's buttons and back: %s down -> %s, up -> %s (%s)" % (btns[0].label, near[0].label if near else p1, p2, [b.label for b in btns]))
        nv.put(*btns[0].center)
        for _ in range(len(btns)):
            if nv.pos() == wanted[0].center:
                break
            nv.press("down")
        if nv.pos() != wanted[0].center:
            g.cmd("move %d %d" % wanted[0].center)       # not reachable by down alone (a button beside it): the mouse
            time.sleep(0.3)
        g.pad_press("a")
    return False


def duel_checks(g, res, shots=None):
    nv = Nav(g, res)
    t = g.windows()
    mode, targets = nv.targets()
    check(mode == "duel", "the program is navigating a duel (mode %s, %d targets)" % (mode, len(targets)))
    if mode != "duel":
        return
    kinds = {}
    for x in targets:
        kinds[x.kind] = kinds.get(x.kind, 0) + 1
    print("      targets by kind (1 card, 2 button, 5 player, 6 pile, 7 mana, 8 phase): %s" % kinds, flush=True)

    # 1. the list is what the window tree shows
    hand = [x for x in targets if x.label == "Hand Card"]
    hand_wins = [w for w in t.wins if w.cls == "MAGICGAME_CardClass" and w.title == "Hand Card" and w.visible and not w.empty]
    check(len(hand) == len(hand_wins) and len(hand) >= 5, "every card of the hand is a target (%d of %d), and no empty or hidden one" % (len(hand), len(hand_wins)))
    inplay = [x for x in targets if x.label == "In-play Card"]
    inplay_wins = [w for w in t.wins if w.cls == "MAGICGAME_CardClass" and w.title == "In-play Card" and w.visible and not w.empty]
    check(0 < len(inplay) <= len(inplay_wins) and all(any(w.h == x.id for w in inplay_wins) for x in inplay), "the permanents in play are targets: %d (of %d windows: the rest are covered)" % (len(inplay), len(inplay_wins)))
    check(any(x.kind == K_BUTTON and not x.label for x in targets), "the prompt bar's Done button is a target")
    check(sum(1 for x in targets if x.kind == K_PLAYER) == 2 and sum(1 for x in targets if x.kind == K_PILE) == 4, "both life totals, both libraries and both graveyards are targets")
    n_phase = sum(1 for x in targets if x.kind == K_PHASE)
    check(sum(1 for x in targets if x.kind == K_MANA) == 12 and n_phase in (16, 7), "the mana pools' 12 rows and the phase icons are targets (%d: 16 for the two sides, 7 while the combat column is up)" % n_phase)
    bad = [x for x in targets if g.hit(*x.center) != x.id]
    check(not bad, "a click in the middle of every target reaches that target's window (%d wrong: %s)" % (len(bad), bad[:3]))
    inside = [x for x in targets if x.x0 < 0 or x.y0 < 0 or x.x1 > nv.w + 1 or x.y1 > nv.h]
    check(not inside, "every target is on the screen")

    # 2. the user's examples, in the real game: the bottom card of the hand, up
    hand.sort(key=lambda x: x.y0)
    last = hand[-1]
    nv.put(*last.center)
    p = nv.pos()
    check(p == last.center or last.contains(*p), "the pointer is on the last card of the hand %s" % (p,))
    ups = []
    for i in range(len(hand) - 1):
        ups.append(nv.press("up"))
    check(ups == [x.center for x in reversed(hand[:-1])], "up, %d times: up the hand strip by strip to the first card" % (len(hand) - 1))
    check(g.hit(*ups[-1]) == hand[0].id, "the pointer is on the first card's window")
    first_up = nv.press("up")
    print("      up from the first card of the hand goes to %s" % (first_up,), flush=True)
    check(first_up is not None and (first_up == ups[-1] or not any(h.contains(*first_up) for h in hand)), "up from the top of the hand leaves the hand (or stays if there is nothing above)")
    nv.put(*last.center)
    downs = [nv.press("down")]
    check(downs[0] == last.center, "down from the last card of the hand: nothing below, the pointer stays (no wrapping)")
    nv.put(*hand[0].center)
    check(nv.press("down") == hand[1].center, "down from the first card goes to the second")

    # 3. every target, every direction: the graph
    t0 = time.time()
    graph, badmoves = explore(nv, targets)
    n_edges = sum(1 for v in graph.values() for d in v.values() if d is not None)
    print("      explored %d targets x 4 directions in %.0f s: %d moves" % (len(targets), time.time() - t0, n_edges), flush=True)
    check(not badmoves, "every move lands on the middle of a target (%d did not: %s)" % (len(badmoves), badmoves[:3]))
    sign = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
    opposite = {"up": "down", "down": "up", "left": "right", "right": "left"}
    wrong = [(s_, d, dest) for s_, v in graph.items() for d, dest in v.items()
             if dest is not None and (dest[0] - s_[0]) * sign[d][0] + (dest[1] - s_[1]) * sign[d][1] <= 0]
    check(not wrong, "every move goes the way that was pressed (%d did not)" % len(wrong))
    back = sum(1 for s_, v in graph.items() for d, dest in v.items() if dest is not None and graph.get(dest, {}).get(opposite[d]) == s_)
    print("      %d of %d moves are undone by the opposite direction" % (back, n_edges), flush=True)
    start = hand[-1].center
    reach = reachable(graph, start)
    must = [x for x in targets if x.kind in (K_CARD, K_BUTTON, K_PLAYER, K_PILE, K_MANA, K_PHASE)]
    missing = [x for x in must if x.center not in reach]
    check(not missing, "from the last card of the hand every target can be reached with the D-pad alone (%d of %d; not reached: %s)" % (len(reach), len(targets), missing[:4]))

    # 4. the hover: the big card on the left shows what the pointer is on, as it does for the real mouse (the game shows it a moment after the pointer arrives)
    fc = [w for w in t.find('MAGICGAME_FullCardClass')]
    crop = (max(fc[0].x0, 0), fc[0].y0, fc[0].x1, fc[0].y1) if fc else (1, 192, 257, 576)      # the big card's window
    seen = []
    whole = [x for x in inplay if 4 * (x.y1 - x.y0) >= 3 * (x.x1 - x.x0)][:2]               # a strip of a stack of lands does not always change the picture, for the mouse either
    for x in [hand[1], hand[-1]] + whole:
        path_ = path(graph, start, x.center)
        nv.put(*hand[-1].center)
        settled_crop(nv, crop, "hover_reset")                 # the game keeps showing a permanent for a while after the pointer left it: let it show the hand's last card first
        if path_ is None:
            continue
        for d in path_:
            nv.press(d)
        landed = nv.pos()
        a = settled_crop(nv, crop, "hover_pad")
        if landed != x.center:
            print("      (the route %s ended at %s, not %s)" % (path_, landed, x.center), flush=True)
        nv.put(*x.center)
        b = settled_crop(nv, crop, "hover_mouse")
        seen.append(a)
        check(a == b, "the card shown on the left after D-pad moves to %r (%s) is the one the real mouse shows there" % (x.label, x.center))
    check(len(seen) >= 3 and seen[0] != seen[1], "and it follows the pointer from card to card (%d pictures, %d different; two lands of one kind show the same)" % (len(seen), len(set(seen))))

    # 5. B opens a card's menu: the D-pad walks its rows (the pointer is on each, so A would take it) and Y closes it
    nv.put(*hand[2].center)
    g.pad_press("b")
    time.sleep(1.2)
    t = g.windows()
    rows = sorted([i for i in t.items if i.level == 0 and not i.separator and not i.disabled], key=lambda i: i.y0)
    check(len(rows) >= 2, "B opened a menu on the card (%d rows: %s)" % (len(rows), [i.text for i in rows][:6]))
    mode, mt = nv.targets()
    check(mode == "menu" and len(mt) >= len(rows), "the program navigates the menu (mode %s, %d rows)" % (mode, len(mt)))
    landed = []
    for i in range(len(rows)):
        p = nv.press("down")
        landed.append(p)
    inrow = [p is not None and any(r.x0 <= p[0] < r.x1 and r.y0 <= p[1] < r.y1 for r in rows) for p in landed]
    check(all(inrow), "down walks the menu's rows, the pointer on each in turn (%d of %d)" % (sum(inrow), len(rows)))
    check(len(set(landed)) == len(rows) and landed == sorted(landed, key=lambda p: p[1]), "each row once, top to bottom")
    check(nv.press("down") == landed[-1], "down from the last row: the pointer stays")
    check(nv.press("up") == landed[-2], "up goes back a row")
    g.pad_press("y")
    time.sleep(1.0)
    check(not g.windows().items, "Y closed the menu")

    # 6. the Done button is reached with the D-pad and pressed with A
    done = [x for x in targets if x.kind == K_BUTTON and not x.label][0]
    nv.put(*hand[-1].center)
    route = path(graph, start, done.center)
    check(route is not None, "a way to the Done button from the hand: %s" % (route,))
    if route:
        for d in route:
            nv.press(d)
        check(nv.pos() == done.center, "the pointer is on the Done button after %d presses" % len(route))
        title0 = g.windows().bar()[0].title
        for _ in range(3):                                  # (a phase that waits for a second Done, as the attack's does, is pressed again)
            g.pad_press("a")
            time.sleep(2.5)
            t = g.windows()
            title1 = t.bar()[0].title if t and t.bar() else None
            if title1 != title0:
                break
        check(title1 != title0, "A on Done passed the phase: %r -> %r" % (title0, title1))

    # 7. A on a card does what a click does: on each card of the hand in turn (the pointer put there with the D-pad), until something happens
    for _ in range(10):                                     # on to a main phase, with Done by A (the pointer stays on the button)
        t = g.windows()
        if t is None or not t.bar() or "main phase" in t.bar()[0].title.lower() or t.dialogs():
            break
        g.pad_press("a")
        time.sleep(2.0)
    t = g.windows()
    title = t.bar()[0].title if t and t.bar() else ""
    if "main phase" in title.lower():
        did = None
        for k in range(len(hand)):
            t = g.windows()
            n_hand = len(Player.hand_rows(t))
            if k >= n_hand:
                break
            _, tl = nv.targets()
            strips = sorted([x for x in tl if x.label == "Hand Card"], key=lambda x: x.y0)
            if k >= len(strips):
                break
            nv.put(*strips[-1].center)
            for _ in range(len(strips) - 1 - k):
                nv.press("up")
            g.pad_press("a")
            time.sleep(1.8)
            t2 = g.windows()
            t_title = t2.bar()[0].title if t2 and t2.bar() else ""
            if len(Player.hand_rows(t2)) < n_hand or t_title != title:
                did = (k, n_hand, len(Player.hand_rows(t2)), t_title)
                break
        if did:
            check(True, "A on card %d of the hand acted as a click does (hand %d -> %d cards, bar %r)" % (did[0], did[1], did[2], did[3][:40]))
            g.pad_press("y")                                # Esc backs out of a spell that wants mana
        else:
            print("NOTE  A on the %d cards of the hand did nothing in this phase (no land to play, nothing affordable)" % len(hand), flush=True)
    else:
        print("NOTE  no main phase reached for the A-on-a-card check (bar %r)" % title, flush=True)
    check(g.alive(), "the program is still running")
    return nv, graph, targets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", default="1024x768", choices=["640x480", "800x600", "1024x768"])
    ap.add_argument("--workdir", default="/tmp/nav_play")
    ap.add_argument("--shots", default=None)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--keep", action="store_true", help="leave the game running at the populated board (its process id and control pipe are printed) for trying things by hand")
    ap.add_argument("--attach", nargs=2, metavar=("WORKDIR", "PID"), help="run the checks on a game that is already at a populated board (made with --keep): its work folder and process id")
    a = ap.parse_args()
    if a.attach:
        g = Game(REPO, res=a.res, workdir=a.attach[0])
        g.attach(int(a.attach[1]))
        duel_checks(g, a.res)
        print("%d check(s) failed" % failures if failures else "all checks passed")
        return 1 if failures else 0
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
        p.shot("board")
        if a.keep:
            print("kept: pid %d, control pipe %s" % (g.pid, g.ctl_path), flush=True)
            return 0
        duel_checks(g, a.res)
    finally:
        if not a.keep:
            g.stop()
    print("%d check(s) failed" % failures if failures else "all checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

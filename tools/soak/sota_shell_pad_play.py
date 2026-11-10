#!/usr/bin/env python3
"""sota_shell_pad_play.py: the Magic Shell of Spells of the Ancients 2.15 (magic.exe, 800x600) with the controller's D-pad and with fingers, headless (docs/notes/controller-screens.md, "The Magic Shell").

    python3 tools/soak/sota_shell_pad_play.py [--workdir /tmp/sota_shell_pad] [--seed 8] [--only title,duel,gauntlet,sealed,tools,world,help,player,dialogs,touch] [--overlay-seed DIR]

The shell is started on SDL's dummy drivers with its own control pipe and overlay and PORT_SEED (src/port/seed.h: the same decks, draws and coin toss every run), and driven with the `pad` steps of
PORT_CONTROL, which go through the same code as a real controller's events (docs/notes/controller.md): the D-pad's presses and A, B and Back; the mouse is used only to put the pointer on a target
for the measurement of the moves (`move`, as nav_play.py does) and the window tree and the pictures are read to check what the pad did. Nothing here reads the game's memory: the shell's pages are
standard controls on its main window (and five round buttons it draws itself) and the targets come from the window tree. Every read waits for the page to settle (the same list twice, the page's own
buttons shown) instead of sleeping, and every press waits for the program's own answer (the line of the input log, PORT_PAD_LOG) instead of for a time.

  title     the five round buttons are the only targets; each is reached from the one above with the D-pad and A opens its page (the page's own buttons show)
  duel      Solo Duel, Gauntlet and Sealed Deck: every control of the page is a target (compared with the controls the window tree shows) and every one is reached from every other (every target in
            every direction is pressed from the pointer put on it; each move lands on the middle of another target and goes the way it was pressed); a spin button's arrows count, a check box and the
            radio buttons toggle with A, a combo box drops with A, the D-pad chooses (the first press goes to the choice shown), A takes it, B and Back leave it alone; Duel Options... (a modal
            dialog: its controls are targets, B and Back close it); the Sealed Deck's pack screen
  tools     Deck Builder (the deck library: its cards and buttons, Exit with A), Face Builder
  world, help, player   the pages' controls; the Player page's edit boxes (A gives one the keyboard: the on-screen keyboard is wanted while it has the focus), its spin button and combo box
  dialogs   Start match: the match-up screen, the coin toss, the ante dialog ("Start the duel" with A), the board (D-pad targets of the duel); needs the licence value in the overlay (--overlay-seed: an
            install's port_overlay_sota; the default is port_overlay_sota of this checkout if there is one), else the step is skipped
  touch     fingers (PORT_TOUCH=1: `tdown`, `tup`): a tap on a round button, a tap near a spin button's arrow, a check box and a combo box lands on it (the shell's controls are small), a long press
            closes a list that is down

Prints one line per check and exits 1 if one failed (and 2 if the shell could not be started). Needs the 2.15 install (`pentamoor-install ... --sota ... --patch ...`), the module game_shell and the runtime.
"""
import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pentamoor_ctl import Game  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCREEN = (800, 600)
K_BUTTON, K_FIELD, K_ROW = 2, 3, 4
DIRS = ("up", "down", "left", "right")
COMBO_CLOSED_H = 21
BALLS = ["Duel", "Tools", "World", "Help", "Player"]
# a button of each page that is shown only on it: how the script knows the page is up
MARKER = {"Duel": "Solo &Duel", "Tools": "&Deck Builder", "World": "&Shandalar", "Help": "&Help File", "Player": "&Screen Name"}
# 6 s is a long time for the shell to draw a page; the polls stop as soon as the page is there
SETTLE_S = 10.0

failures = 0
skipped = 0


def check(ok, what):
    global failures
    print("%s  %s" % ("ok  " if ok else "FAIL", what), flush=True)
    if not ok:
        failures += 1
    return ok


def note(what):
    print("     %s" % what, flush=True)


def clean(label):
    return label.replace("&", "").strip()


def key_of(t):
    return (t.x0, t.y0, t.x1, t.y1)


class Shell:
    """One shell process, driven by the pad."""

    def __init__(self, a, name, seed, touch=False, overlay=None):
        self.a = a
        self.name = name
        ext = "dylib" if sys.platform == "darwin" else "so"
        sota = os.environ.get("PENTAMOOR_SOTA") or "sources/installed_sota/Magic/Program"
        env = {"PORT_PAD_LOG": "stderr", "PORT_TEXTINPUT": "auto", "PORT_TEXT_LOG": "1", "PORT_SEED": str(seed)}
        if touch:
            env["PORT_TOUCH"] = "1"
        self.g = Game(REPO, res="800x600", workdir=os.path.join(a.workdir, name), exe="src/port/build/pentamoor-run", program=os.path.join(sota, "magic.exe"),
                      module=os.environ.get("PENTAMOOR_MODULE") or os.path.join(REPO, "src/port/build", "game_shell." + ext), overlay_seed=overlay or None, extra_env=env)
        self.graph = {}
        self.mouse_puts = 0               # how often the mouse had to put the pointer on a target because the D-pad's walk had nothing to start from (a list or dialog had just closed)

    def start(self):
        self.g.start()
        return self.wait(lambda mode, ts: mode == "page" and len(ts) == 5, SETTLE_S)[0]

    def stop(self):
        self.g.stop()

    def restart(self):
        """A new process for what follows a flow that cannot be left from the pad (the sealed deck's tournament is a chain of dialogs): the same pipe, workdir and overlay copy, a fresh title page."""
        self.g.stop()
        return self.start()

    # ---- reads that settle ---------------------------------------------------------------------------------------------------------
    def nav(self):
        r = self.g.nav_targets()
        return r if r else ("?", [])

    def wait(self, pred, timeout=SETTLE_S, quiet=0.25):
        """(ok, mode, targets): the first time `pred(mode, targets)` held on two reads in a row with the same list `quiet` seconds apart (a page that is still being laid out, or the previous one's list
        still there, does not pass)."""
        end = time.time() + timeout
        prev = None
        mode, ts = self.nav()
        while True:
            sig = (mode, tuple((t.label, key_of(t)) for t in ts))
            if pred(mode, ts) and sig == prev:
                return True, mode, ts
            if time.time() > end:
                return False, mode, ts
            prev = sig if pred(mode, ts) else None
            time.sleep(quiet)
            mode, ts = self.nav()

    def tree(self):
        return self.g.windows()

    def shown(self, title, cls="BUTTON"):
        t = self.tree()
        if t is None:
            return None
        for w in t.wins:
            if w.cls.rstrip("*") == cls and w.title == title and t.shown(w) and not w.empty:
                return w
        return None

    def wait_shown(self, title, cls="BUTTON", timeout=SETTLE_S):
        end = time.time() + timeout
        while time.time() < end:
            if self.shown(title, cls):
                return True
            time.sleep(0.1)
        return False

    def checked(self, title):
        t = self.tree()
        for w in t.wins:
            if w.cls.rstrip("*") == "BUTTON" and w.title == title and t.shown(w):
                return w.checked
        return None

    def spin_text(self, up):
        """The number a spin button shows: the text of the edit box at its left (the spin target `up`'s window tree neighbour), or None."""
        tree = self.tree()
        for w in tree.wins:
            if w.cls.rstrip("*") == "EDIT" and tree.shown(w) and abs(w.x1 - up.x0) <= 2 and w.y0 <= up.y0 < w.y1:
                return w.title
        return None

    def wait_spin(self, up, was, timeout=4.0):
        """The spin button's number once it is not `was` (or the last one read when it never is within the time)."""
        end = time.time() + timeout
        v = was
        while time.time() < end:
            v = self.spin_text(up)
            if v != was:
                return v
            time.sleep(0.1)
        return v

    def text_input(self):
        """Whether SDL's text input (what brings up an on-screen keyboard) is on now: the control pipe's `textinput` step answers "text input: on|off managed=N" on stderr (PORT_TEXTINPUT=auto: on while a text field has the focus); None if it did not answer."""
        off = self.g.log_size()
        self.g.cmd("textinput")
        end = time.time() + 3
        while time.time() < end:
            m = re.search(r"^  text input: (on|off) managed=", self.g.read_log(off), re.M)
            if m:
                return m[1] == "on"
            time.sleep(0.03)
        return None

    def kind_targets(self, ts, cls):
        """The targets that are windows of class `cls` (COMBOBOX, EDIT), found through the window tree: a combo box's closed box is as tall as an edit box, so the list cannot tell them apart."""
        tree = self.tree()
        boxes = set()
        for w in tree.wins:
            if w.cls.rstrip("*") == cls and w.visible and tree.shown(w) and w.enabled and not w.empty:
                boxes.add((w.x0, w.y0, w.x1, min(w.y1, w.y0 + COMBO_CLOSED_H) if cls == "COMBOBOX" else w.y1))
        return [t for t in ts if key_of(t) in boxes]

    def region(self, box, settle=True):
        """A hash of the screen's box; with `settle`, once it is the same on two reads 0.25 s apart (a control repaints a moment after its state changes)."""
        h = self.g.region_hash(box)
        if not settle:
            return h
        end = time.time() + 4
        while time.time() < end:
            time.sleep(0.25)
            h2 = self.g.region_hash(box)
            if h2 == h:
                return h
            h = h2
        return h

    def changed(self, box, was, timeout=4.0):
        """The box's settled hash once it differs from `was` (or the last one read when it never does within the time)."""
        end = time.time() + timeout
        h = was
        while time.time() < end:
            h = self.region(box)
            if h != was:
                return h
        return h

    # ---- the pad ------------------------------------------------------------------------------------------------------------------
    def pos(self):
        p = self.g.pad_pos()
        return (p[0], p[1]) if p else None

    def put(self, x, y):
        """The mouse puts the pointer on (x, y) (the pad's cursor follows it); returns when it is there."""
        self.g.cmd("move %d %d" % (x, y))
        end = time.time() + 3
        while time.time() < end:
            if self.pos() == (x, y):
                return True
            time.sleep(0.02)
        return False

    def press(self, d):
        """A D-pad press, answered by the program's own line of the input log: returns the pointer afterwards (the same place when there was nowhere to go) and what the program said."""
        off = self.g.log_size()
        before = self.pos()
        self.g.pad_press(d)
        end = time.time() + 4
        while time.time() < end:
            text = self.g.read_log(off)
            m = re.search(r"D-pad: the game chose a target, the pointer goes to \((-?\d+),(-?\d+)\)", text)
            if m:
                to = (int(m[1]), int(m[2]))
                for _ in range(100):
                    if self.pos() == to:
                        break
                    time.sleep(0.01)
                return to, "moved"
            if "no target that way" in text:
                return before, "none"
            if "a list there scrolls" in text:
                return before, "scroll"
            time.sleep(0.02)
        return self.pos(), "silent"

    def a_button(self):
        self.g.pad_press("a")

    def b_button(self):
        self.g.pad_press("b")

    def back(self):
        self.g.pad_press("back")

    def log_since(self, off):
        return self.g.read_log(off)

    # ---- the graph of one page -----------------------------------------------------------------------------------------------------
    def explore(self, ts):
        """Every target in every direction: the pointer is put on it with the mouse and the direction pressed. {centre: {dir: centre or None}} and the moves that were wrong."""
        graph, bad = {}, []
        for t in ts:
            graph[t.center] = {}
            for d in DIRS:
                if not self.put(*t.center):
                    bad.append((t.label, d, "pointer not placed"))
                    continue
                p, what = self.press(d)
                fresh = self.nav()[1]
                if what in ("none", "scroll") or p == t.center:
                    graph[t.center][d] = None
                    continue
                dest = next((x for x in fresh if x.center == p), None)
                if dest is None:
                    bad.append((t.label, d, "landed on %s, no target's middle" % (p,)))
                    continue
                dx, dy = p[0] - t.center[0], p[1] - t.center[1]
                way = {"up": dy < 0, "down": dy > 0, "left": dx < 0, "right": dx > 0}[d]
                if not way:
                    bad.append((t.label, d, "went the wrong way to %s" % (p,)))
                    continue
                graph[t.center][d] = p
        self.graph = graph
        return graph, bad

    def path(self, src, dst):
        """The shortest list of presses from the target at `src` to the one at `dst` in the measured graph, or None."""
        seen, queue = {src: []}, [src]
        while queue:
            cur = queue.pop(0)
            if cur == dst:
                return seen[cur]
            for d, nxt in self.graph.get(cur, {}).items():
                if nxt is not None and nxt not in seen:
                    seen[nxt] = seen[cur] + [d]
                    queue.append(nxt)
        return None

    def walk_to(self, ts, want):
        """Walk to the target `want` (a Target of the list `ts`) with the D-pad only, from the target the pointer is on; True if it got there. Each press must land where the measured graph said."""
        here = next((t for t in ts if t.x0 <= self.pos()[0] < t.x1 and t.y0 <= self.pos()[1] < t.y1), None)
        if here is None:
            return False
        if here.center == want.center:
            return True
        route = self.path(here.center, want.center)
        if route is None:
            return False
        cur = here.center
        for d in route:
            p, _ = self.press(d)
            if p != self.graph[cur][d]:
                return False
            cur = p
        return True


def strongly_connected(graph):
    nodes = list(graph)
    if not nodes:
        return False, []
    out = []
    for src in nodes:
        seen, queue = {src}, [src]
        while queue:
            cur = queue.pop(0)
            for nxt in graph.get(cur, {}).values():
                if nxt is not None and nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        if len(seen) != len(nodes):
            out.append((src, len(seen)))
    return not out, out


def expected_from_tree(tree):
    """What the window tree says the D-pad must be able to reach on the shell's page: a box for every shown, enabled push, check or radio button (not a group box), edit box and combo box (its closed box),
    two (the arrows' halves) for every spin button. The five round buttons are no windows and are counted apart."""
    boxes = []
    for w in tree.wins:
        cls = w.cls.rstrip("*")
        if not (w.visible and tree.shown(w) and w.enabled) or w.empty or w.x1 <= 0:
            continue
        if cls == "BUTTON" and (w.style & 0xF) != 7:
            boxes.append((w.x0, w.y0, w.x1, w.y1))
        elif cls == "EDIT":
            boxes.append((w.x0, w.y0, w.x1, w.y1))
        elif cls == "COMBOBOX":
            boxes.append((w.x0, w.y0, w.x1, min(w.y1, w.y0 + COMBO_CLOSED_H)))
        elif cls == "msctls_updown32":
            mid = w.y0 + (w.y1 - w.y0) // 2
            boxes.append((w.x0, w.y0, w.x1, mid))
            boxes.append((w.x0, mid, w.x1, w.y1))
    return sorted(boxes)


def page_checks(sh, name, ts, tag):
    """The checks every page has: the list is what the tree shows plus the five round buttons, and every target is reached from every other. Returns the explored graph's targets."""
    tree = sh.tree()
    balls = [t for t in ts if t.label == "page button"]
    others = sorted(key_of(t) for t in ts if t.label != "page button")
    want = expected_from_tree(tree)
    check(len(balls) == 5 and all(t.kind == K_BUTTON for t in balls), "%s: the five round buttons are targets" % name)
    check(others == want, "%s: %d targets besides them, the controls the window tree shows (%d)%s" % (name, len(others), len(want),
                                                                                                    "" if others == want else "; only in the list: %s; only in the tree: %s" % (sorted(set(others) - set(want))[:4], sorted(set(want) - set(others))[:4])))
    t0 = time.time()
    graph, bad = sh.explore(ts)
    check(not bad, "%s: every target in every direction (%d moves in %.0f s): each lands on the middle of another target and goes the way it was pressed%s" % (name, 4 * len(ts), time.time() - t0, "" if not bad else " (%d did not: %s)" % (len(bad), bad[:3])))
    ok, short = strongly_connected(graph)
    check(ok, "%s: every target can be reached from every other by the D-pad alone%s" % (name, "" if ok else " (from %s: %s)" % (short[0][0], short[0][1])))
    return graph


def go_ball(sh, ts, ball):
    """From wherever the pointer is on the page's targets to the round button `ball` with the D-pad, then A; waits for the page's own button to show. Returns the settled list of the page."""
    balls = sorted([t for t in ts if t.label == "page button"], key=lambda t: t.y0)
    want = balls[BALLS.index(ball)]
    if not on_target(sh, ts):                                  # a fresh process, or a list has just closed over the pointer: the mouse puts it on the first target
        sh.mouse_puts += 1
        sh.put(*ts[0].center)
    reached = sh.walk_to(ts, want)
    check(reached, "the D-pad walks to the round button %s (%d presses at most)" % (ball, 12))
    if not reached:
        sh.put(*want.center)
    sh.a_button()
    ok = sh.wait_shown(MARKER[ball])
    check(ok, "A on %s: its page is up (%s shown)" % (ball, clean(MARKER[ball])))
    ok, mode, ts2 = sh.wait(lambda m, t: m == "page" and any(x.label == MARKER[ball] for x in t) and len(t) >= 7)
    return ts2


def find(ts, label, nth=0):
    hits = [t for t in ts if t.label == label]
    return hits[nth] if len(hits) > nth else None


def press_target(sh, ts, label, nth=0):
    """Walk to the target with that label with the D-pad and press A on it. Returns the target (or None). When the pointer is on no target (a list or a dialog has just closed over it) the walk
    has nothing to start from: the mouse puts the pointer on the first target of the page's list, which is the start of a walk; if the walk still does not arrive, that is a failed check."""
    t = find(ts, label, nth)
    if t is None:
        check(False, "a target '%s' is there" % clean(label))
        return None
    if not on_target(sh, ts):
        sh.mouse_puts += 1
        sh.put(*ts[0].center)
    if not sh.walk_to(ts, t):
        check(False, "the D-pad walks to '%s'" % clean(label))
        sh.put(*t.center)
    sh.a_button()
    return t


def on_target(sh, ts):
    p = sh.pos()
    return p is not None and any(t.x0 <= p[0] < t.x1 and t.y0 <= p[1] < t.y1 for t in ts)


# ---- the pages ------------------------------------------------------------------------------------------------------------------------
def spin_checks(sh, ts, nth=0):
    """A on a spin button's arrows counts (the edit box beside it shows the number): the up arrow adds one and the down arrow takes it back; at the top of its range the down arrow goes first."""
    up = find(ts, "spin up", nth)
    down = find(ts, "spin down", nth)
    if not up or not down:
        check(False, "spin button %d has both arrows as targets" % nth)
        return
    before = sh.spin_text(up)
    press_target(sh, ts, "spin up", nth)
    after = sh.wait_spin(up, before)
    second = "spin down"
    what = "up"
    try:
        good = int(after) == int(before) + 1
    except (TypeError, ValueError):
        good = False
    if after == before:                                           # at the top of its range: the down arrow goes first
        press_target(sh, ts, "spin down", nth)
        after = sh.wait_spin(up, before)
        second = "spin up"
        what = "down (the number was at the top of its range)"
        try:
            good = int(after) == int(before) - 1
        except (TypeError, ValueError):
            good = False
    check(good, "A on the %s arrow of spin button %d counts: %s -> %s" % (what, nth, before, after))
    press_target(sh, ts, second, nth)
    back = sh.wait_spin(up, after)
    check(back == before, "A on the other arrow puts it back: %s -> %s" % (after, back))


def toggle_checks(sh, ts, label, radio=False):
    """A on a check box flips it; on a radio button that is off it turns it on. Returns (before, after)."""
    was = sh.checked(label)
    press_target(sh, ts, label)
    end = time.time() + 3
    now = was
    while time.time() < end and now == was:
        time.sleep(0.1)
        now = sh.checked(label)
    check(now is not None and now != was, "A on '%s' %s (%s -> %s)" % (clean(label), "turns it on" if radio else "flips it", was, now))
    return was, now


def radio_checks(sh, ts, labels):
    """The radio buttons of one group: A on one that is off turns it on and the one that was on goes off; then A on the first one puts the group back."""
    on = next((l for l in labels if sh.checked(l)), None)
    off = next((l for l in labels if sh.checked(l) is False), None)
    check(on is not None and off is not None, "the group %s has one button on (%s) and others off" % ([clean(l) for l in labels], clean(on) if on else None))
    if on is None or off is None:
        return
    was, now = toggle_checks(sh, ts, off, radio=True)
    check(sh.checked(on) is False, "the radio button that was on ('%s') went off" % clean(on))
    toggle_checks(sh, ts, on, radio=True)


def press_target_at(sh, ts, t):
    """Walk to the target `t` (a Target of the list) with the D-pad and press A on it."""
    if not on_target(sh, ts):
        sh.mouse_puts += 1
        sh.put(*ts[0].center)
    if not sh.walk_to(ts, t):
        check(False, "the D-pad walks to the target at %s" % (t.center,))
        sh.put(*t.center)
    sh.a_button()


def combo_checks(sh, ts, nth=0, name="the combo box"):
    """A drops the list (mode combo), the D-pad's first press goes to the choice the box shows and the next one further, A takes the row; B and Back leave the choice as it was."""
    combos = sh.kind_targets(ts, "COMBOBOX")
    if len(combos) <= nth:
        check(False, "%s is a target" % name)
        return
    c = combos[nth]
    box = (c.x0 + 2, c.y0 + 2, min((c.x0 + c.x1) // 2 - 4, c.x0 + 150), c.y1 - 2)      # the left of the closed box: the pointer's arrow (a screenshot shows it) is drawn right of and under where the pointer is, which is the middle
    press_target_at(sh, ts, c)
    h0 = sh.region(box)
    ok, mode, rows = sh.wait(lambda m, t: m == "combo" and len(t) >= 2, 5)
    check(ok and all(r.kind == K_ROW for r in rows), "A on %s drops its list: mode combo, %d rows" % (name, len(rows)))
    if not ok:
        return
    p1, _ = sh.press("down")
    row0 = next((r for r in rows if r.x0 <= p1[0] < r.x1 and r.y0 <= p1[1] < r.y1), None)
    check(row0 is not None, "%s: the first press goes to a row, the choice the box shows (%s), not to the first row under the box" % (name, row0.label.strip() if row0 else None))
    p2, _ = sh.press("down")
    row1 = next((r for r in rows if r.x0 <= p2[0] < r.x1 and r.y0 <= p2[1] < r.y1), None)
    check(row0 is not None and row1 is not None and rows.index(row1) == rows.index(row0) + 1, "%s: the next press goes one row down (%s)" % (name, row1.label.strip() if row1 else None))
    sh.b_button()                                                 # B: cancel: the choice is as it was
    ok, mode, ts2 = sh.wait(lambda m, t: m == "page", 5)
    check(ok and sh.region(box) == h0, "%s: B closes the list and the choice is as it was" % name)
    sh.put(*c.center)
    sh.a_button()
    sh.wait(lambda m, t: m == "combo" and len(t) >= 2, 5)
    sh.press("down")
    sh.press("down")
    sh.back()
    ok, mode, ts2 = sh.wait(lambda m, t: m == "page", 5)
    check(ok and sh.region(box) == h0, "%s: Back (Escape) closes it too, nothing chosen" % name)
    sh.put(*c.center)
    sh.a_button()
    sh.wait(lambda m, t: m == "combo" and len(t) >= 2, 5)
    sh.press("down")
    sh.press("down")
    sh.a_button()
    ok, mode, ts2 = sh.wait(lambda m, t: m == "page", 5)
    h1 = sh.changed(box, h0)
    check(ok and h1 != h0, "%s: A on a row takes it (the box shows another choice)" % name)


def options_checks(sh, ts, label, name):
    """A on the page's Options button: a modal dialog (mode dialog) whose controls are targets, reached from one another by the D-pad; a check box toggles with A, B closes it, Back closes it, OK closes it."""
    page_graph = sh.graph
    press_target(sh, ts, label)
    ok, mode, dts = sh.wait(lambda m, tt: m == "dialog" and any(x.label == "OK" for x in tt) and any(x.label == "Cancel" for x in tt), 8)
    check(ok, "A on %s: the modal dialog (mode dialog, %d targets), with OK and Cancel" % (clean(label), len(dts)))
    if not ok:
        return
    tree = sh.tree()
    dlg = [w for w in tree.wins if w.cls.startswith("#32770") and w.visible and (w.style & 0x80000000)]
    if dlg:
        d = dlg[-1]
        inside = [w for w in tree.wins if w.parent == d.h and tree.shown(w) and w.enabled and not w.empty and w.cls.rstrip("*") == "BUTTON" and (w.style & 0xF) != 7]
        check(sorted((w.x0, w.y0, w.x1, w.y1) for w in inside) == sorted(key_of(x) for x in dts), "the dialog's targets are its %d enabled buttons, check boxes and radio buttons" % len(inside))
    t0 = time.time()
    graph, bad = sh.explore(dts)
    check(not bad, "the dialog: every target in every direction (%d moves in %.0f s)%s" % (4 * len(dts), time.time() - t0, "" if not bad else ": %s" % bad[:3]))
    ok, short = strongly_connected(graph)
    check(ok, "the dialog: every control can be reached from every other by the D-pad alone")
    box = next((x for x in dts if x.label.startswith("Show ")), None)
    if box:
        was = sh.checked(box.label)
        sh.put(*dts[0].center)
        reached = sh.walk_to(dts, box)
        check(reached, "the D-pad walks to the check box '%s'" % clean(box.label))
        sh.a_button()
        end = time.time() + 3
        now = was
        while time.time() < end and now == was:
            time.sleep(0.1)
            now = sh.checked(box.label)
        check(now != was, "A on a check box of the dialog flips it")
    sh.b_button()
    ok, mode, _ = sh.wait(lambda m, tt: m == "page", 6)
    check(ok, "B closes the dialog (it has a Cancel button)")
    sh.graph = page_graph
    press_target(sh, ts, label)
    sh.wait(lambda m, tt: m == "dialog" and any(x.label == "Cancel" for x in tt), 8)
    sh.back()
    ok, mode, _ = sh.wait(lambda m, tt: m == "page", 6)
    check(ok, "Back closes it too")
    press_target(sh, ts, label)
    ok, mode, dts = sh.wait(lambda m, tt: m == "dialog" and any(x.label == "OK" for x in tt), 8)
    ok_t = find(dts, "OK")
    if ok_t:
        sh.put(*ok_t.center)
        sh.a_button()
    ok, mode, _ = sh.wait(lambda m, tt: m == "page", 6)
    check(ok, "A on OK closes it")


def recover(sh, ts):
    """Leave whatever is open (a list, a dialog) with Back and return the page's settled list (the previous one if the shell does not show a page)."""
    for _ in range(4):
        mode, now = sh.nav()
        if mode == "page":
            break
        sh.back()
        sh.wait(lambda m, t: m != mode, 3)
    ok, mode, now = sh.wait(lambda m, t: m == "page" and len(t) >= 5, 5)
    return now if ok else ts


def step_title(sh, state):
    ok, mode, ts = sh.wait(lambda m, t: m == "page" and len(t) == 5)
    check(ok and all(t.label == "page button" and t.kind == K_BUTTON for t in ts), "the title page: mode page, five targets, the round buttons Duel, Tools, World, Help, Player (%d)" % len(ts))
    ys = [t.y0 for t in ts]
    check(ys == sorted(ys) and len({t.y0 for t in ts}) == 5, "they are in a column, Duel on top")
    graph, bad = sh.explore(ts)
    state["title_graph"] = graph
    check(not bad, "every target in every direction (20 moves)%s" % ("" if not bad else ": %s" % bad[:3]))
    ok, short = strongly_connected(graph)
    check(ok, "each round button can be reached from every other")
    # from nothing (the pointer is in the middle of the screen): the first press takes the nearest in that direction
    sh.put(400, 300)
    p, what = sh.press("left")
    check(what == "moved" and any(t.x0 <= p[0] < t.x1 and t.y0 <= p[1] < t.y1 for t in ts), "from the middle of the screen, left lands on a round button (%s)" % (p,))
    state["title"] = ts


def visit(sh, state, name, ts_from):
    """Switch to the page `name` with the D-pad and A, from the targets `ts_from`; returns its settled list."""
    return go_ball(sh, ts_from, name)


def step_duel(sh, state):
    ts = visit(sh, state, "Duel", state["ts"])
    check(find(ts, "Solo &Duel") and find(ts, "&Gauntlet") and find(ts, "&Sealed Deck"), "the Duel page: Solo Duel, Gauntlet and Sealed Deck are targets (%d targets)" % len(ts))
    page_checks(sh, "Solo Duel", ts, "solo")
    # the controls
    spin_checks(sh, ts, nth=0)
    toggle_checks(sh, ts, "&Ante")
    toggle_checks(sh, ts, "&Ante")
    radio_checks(sh, ts, ["Apprentice", "Magician", "Sorcerer", "Wizard"])
    combo_checks(sh, ts, 0, "'Your deck' combo box")
    combo_checks(sh, ts, 1, "'Opponent's deck' combo box")
    options_checks(sh, ts, "Duel &Options...", "Duel Options")
    # the other kinds
    t = press_target(sh, ts, "&Gauntlet")
    ok, mode, gts = sh.wait(lambda m, tt: m == "page" and any(x.label == "&Run the gauntlet" for x in tt))
    check(ok, "A on Gauntlet: its page (%d targets)" % len(gts))
    page_checks(sh, "Gauntlet", gts, "gauntlet")
    spin_checks(sh, gts, nth=0)
    spin_checks(sh, gts, nth=1)
    combo_checks(sh, gts, 0, "the Gauntlet's difficulty combo box")
    press_target(sh, gts, "&Sealed Deck")
    ok, mode, sts = sh.wait(lambda m, tt: m == "page" and any(x.label == "Start &tournament" for x in tt))
    check(ok, "A on Sealed Deck: its page (%d targets)" % len(sts))
    page_checks(sh, "Sealed Deck", sts, "sealed")
    for n in range(3):
        spin_checks(sh, sts, nth=n)
    radio_checks(sh, sts, ["&40 cards", "&60 cards"])
    # the pack screen: a dialog of its own that the shell hides its window under: its DONE button is a window, its packs are places it tests a click against (learned from the first click on it)
    press_target(sh, sts, "Start &tournament")
    ok, mode, pts = sh.wait(lambda m, tt: m == "dialog" and len(tt) >= 1, 12)
    done = next((t for t in pts if t.kind == K_BUTTON and t.id), None)
    check(ok and done is not None, "A on Start tournament: the pack screen is a dialog (mode dialog) and its DONE button is a D-pad target (%d target(s))" % len(pts))
    if ok and done:
        p, what = sh.press("left")
        check(done.x0 <= p[0] < done.x1 and done.y0 <= p[1] < done.y1, "the first D-pad press in it goes to DONE (%s)" % (p,))
        sh.put(400, 560)                                           # a click on the picture, where the dialog has nothing: the dialog tests its packs against it, and so they are known
        sh.a_button()
        ok, mode, pts = sh.wait(lambda m, tt: m == "dialog" and len(tt) >= 4, 6)
        areas = [t for t in pts if t.label == "dialog area"]
        check(ok and len(areas) >= 3, "after a click on it: DONE and the %d packs (the places the dialog tests a click against) are targets" % len(areas))
        if areas:
            before = sh.region((0, 180, 800, 600), settle=True)
            sh.put(*areas[0].center)
            sh.a_button()
            after = sh.changed((0, 180, 800, 600), before)
            check(after != before, "A on a pack shows what is in it (the picture changed)")
        sh.put(*done.center)
        sh.a_button()
        # DONE goes on to the tournament: the deck library in a dialog, its Stats, Deck Info and Exit buttons; the Edit deck, Next Round and Quit buttons of the ladder are under a window of the library
        ok, mode, tts = sh.wait(lambda m, tt: m == "dialog" and any(x.label == "Exit" for x in tt), 12)
        names = sorted(clean(x.label) for x in tts if x.kind == K_BUTTON)
        check(ok and {"Deck Info", "Exit"} <= set(names) and not ({"Quit", "Next Round"} & set(names)), "A on DONE: the tournament's deck library is a dialog; its buttons that can be pressed are targets (%s), the ones under its card list are not" % ", ".join(names))
    # the tournament is a chain of dialogs (free lands, the ladder) that the pad cannot leave without playing it: a new process for the rest
    ok = sh.restart()
    check(ok, "the shell is started again (a fresh title page) for the pages that follow")
    state["ts"] = sh.wait(lambda m, tt: m == "page" and len(tt) == 5)[2]
    sh.graph = state.get("title_graph", {})


def step_tools(sh, state):
    ts = visit(sh, state, "Tools", state["ts"])
    page_checks(sh, "Tools", ts, "tools")
    t = press_target(sh, ts, "&Deck Builder")
    ok, mode, dts = sh.wait(lambda m, tt: m == "deck" and len(tt) >= 3, 15)
    check(ok, "A on Deck Builder: the deck library (mode deck, %d targets)" % len(dts))
    if ok:
        buttons = [x for x in dts if x.kind == K_BUTTON]
        check(len(buttons) >= 2, "its buttons are targets (%s)" % ", ".join(clean(b.label) for b in buttons))
        exit_b = next((b for b in buttons if "Exit" in b.label or "exit" in b.label), buttons[-1] if buttons else None)
        if exit_b:
            sh.put(*exit_b.center)
            sh.a_button()
            ok, mode, ts2 = sh.wait(lambda m, tt: m == "page" and any(x.label == "&Face Builder" for x in tt), 15)
            check(ok, "A on %s leaves it: back on the Tools page" % clean(exit_b.label))
            state["ts"] = ts2 if ok else ts
            return
    state["ts"] = ts


def step_world(sh, state):
    ts = visit(sh, state, "World", state["ts"])
    page_checks(sh, "World", ts, "world")
    state["ts"] = ts


def step_help(sh, state):
    ts = visit(sh, state, "Help", state["ts"])
    page_checks(sh, "Help", ts, "help")
    state["ts"] = ts


def step_player(sh, state):
    ts = visit(sh, state, "Player", state["ts"])
    page_checks(sh, "Player", ts, "player")
    edits = sh.kind_targets(ts, "EDIT")
    check(len(edits) >= 4, "the Player page's edit boxes are targets (%d)" % len(edits))
    # an edit box: A gives it the keyboard (text input on while it has the focus), so first nothing has it
    name = next((t for t in edits if t.label == "<player>"), edits[0] if edits else None)
    if name:
        check(sh.text_input() is False, "before it: no text field has the focus (text input off)")
        press_target_at(sh, ts, name)
        end = time.time() + 4
        on = False
        while time.time() < end and not on:
            on = sh.text_input() is True
            time.sleep(0.05)
        check(on, "A on the screen-name box: the keyboard is wanted (text input on)")
        sh.g.cmd("text xy")                                          # typed characters (WM_CHAR), as a keyboard or the Deck's on-screen keyboard gives them
        end = time.time() + 3
        typed = False
        while time.time() < end and not typed:
            w = next((x for x in sh.tree().wins if x.cls.rstrip("*") == "EDIT" and x.y0 == name.y0 and x.x0 == name.x0), None)
            typed = bool(w and w.title.endswith("xy"))
            time.sleep(0.1)
        check(typed, "the keys typed go into it ('<player>' + xy)")
    spin_checks(sh, ts, nth=0)
    combo_checks(sh, ts, 0, "the Player page's combo box")
    state["ts"] = ts


def step_dialogs(sh, state, a):
    """Start match: the match-up screen, the coin toss and the ante dialog, then the board."""
    sh.graph = state.get("title_graph", {})
    ts = visit(sh, state, "Duel", state["ts"])                    # the round button by the D-pad (the title page's moves are known), the page's own button with the mouse (this process has not measured the page)
    t = find(ts, "Start &match")
    sh.put(*t.center)
    sh.a_button()
    ok, mode, ds = sh.wait(lambda m, tt: m == "dialog", 15)
    check(ok, "A on Start match: a dialog (the match-up screen) comes up (%d targets)" % len(ds))
    note("the match-up screen has no button: a click anywhere (A) goes on")
    # the coin toss and the ante dialog: A on whatever the dialog offers until the board is up
    seen = []
    end = time.time() + 90
    board = False
    while time.time() < end:
        mode, ts = sh.nav()
        if mode == "duel" and len(ts) >= 20:
            board = True
            break
        if mode == "dialog":
            labels = tuple(clean(t.label) for t in ts)
            if ts and labels not in seen:
                seen.append(labels)
                note("dialog with %s" % (list(labels),))
            if ts:
                sh.put(*ts[0].center)
                sh.a_button()
            else:
                sh.put(400, 300)
                sh.a_button()
        time.sleep(0.5)
    check(any("Start the duel" in " ".join(s) for s in seen), "the ante dialog's 'Start the duel' was a D-pad target and A took it")
    check(board, "the board: mode duel with %d targets (the hand, the piles, the phases, ...)" % len(ts))


def step_touch(a, seed, overlay):
    sh = Shell(a, "touch", seed, touch=True, overlay=overlay)
    if not sh.start():
        check(False, "touch: the shell started with fingers on")
        sh.stop()
        return
    try:
        g = sh.g

        def tap(x, y, hold=0.1):
            g.cmd("tdown 1 %d %d" % (x, y))
            time.sleep(hold)
            g.cmd("tup 1 %d %d" % (x, y))

        def long_press(x, y):
            g.cmd("tdown 1 %d %d" % (x, y))
            time.sleep(0.8)
            g.cmd("tup 1 %d %d" % (x, y))

        ok, mode, ts = sh.wait(lambda m, t: m == "page" and len(t) == 5)
        balls = sorted(ts, key=lambda t: t.y0)
        tap(*balls[0].center)
        ok = sh.wait_shown(MARKER["Duel"])
        check(ok, "a tap on the round button Duel opens the page")
        ok, mode, ts = sh.wait(lambda m, t: m == "page" and any(x.label == "Solo &Duel" for x in t) and len(t) >= 15)
        up, down = find(ts, "spin up"), find(ts, "spin down")
        v0 = sh.spin_text(up)
        tap(up.x1 + 9, up.y0 + 5)                                 # 9 pixels right of the arrow, on nothing
        v1 = sh.wait_spin(up, v0)
        if v1 == v0:                                                # at the top of its range: the other arrow first
            tap(down.x0 + 6, down.y1 + 6)
            v1 = sh.wait_spin(up, v0)
            check(v1 != v0, "a tap 6 pixels under the down arrow counts down: %s -> %s (the number was at the top of its range)" % (v0, v1))
            tap(up.x1 + 9, up.y0 + 5)
            v2 = sh.wait_spin(up, v1)
            check(v2 == v0, "a tap 9 pixels beside the up arrow of a spin button (12 pixels wide) counts up: %s -> %s" % (v1, v2))
        else:
            check(v1 != v0, "a tap 9 pixels beside the up arrow of a spin button (12 pixels wide) counts up: %s -> %s" % (v0, v1))
            tap(down.x0 + 6, down.y1 + 6)                          # just under the down arrow
            v2 = sh.wait_spin(up, v1)
            check(v2 == v0, "a tap 6 pixels under the down arrow counts down: %s -> %s" % (v1, v2))
        ante = find(ts, "&Ante")
        was = sh.checked("&Ante")
        tap(ante.x1 + 8, ante.y0 + 7)                              # beside the check box
        end = time.time() + 3
        now = was
        while time.time() < end and now == was:
            time.sleep(0.1)
            now = sh.checked("&Ante")
        check(now != was, "a tap 8 pixels beside the check box flips it")
        c = sh.kind_targets(ts, "COMBOBOX")[0]
        tap(c.x0 + 100, c.y1 + 7)                                  # under the closed box
        ok, mode, rows = sh.wait(lambda m, t: m == "combo" and len(t) >= 2, 5)
        check(ok, "a tap 7 pixels under a combo box drops its list (%d rows)" % len(rows))
        if ok:
            long_press(rows[2].x0 + 30, rows[2].y0 + 5)
            ok, mode, _ = sh.wait(lambda m, t: m == "page", 5)
            check(ok, "a long press (a right click) closes the list")
            tap(c.x0 + 100, c.y0 + 8)
            ok, mode, rows = sh.wait(lambda m, t: m == "combo" and len(t) >= 2, 5)
            if ok:
                h0 = sh.region((c.x0 + 2, c.y0 + 2, min((c.x0 + c.x1) // 2 - 4, c.x0 + 150), c.y1 - 2))
                tap(rows[3].x0 + 30, rows[3].y0 + 8)
                ok, mode, _ = sh.wait(lambda m, t: m == "page", 5)
                h1 = sh.changed((c.x0 + 2, c.y0 + 2, min((c.x0 + c.x1) // 2 - 4, c.x0 + 150), c.y1 - 2), h0)
                check(ok and h1 != h0, "a tap on a row takes it")
    finally:
        sh.stop()


STEPS = ["title", "duel", "tools", "world", "help", "player", "dialogs", "touch"]


def main():
    global skipped
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workdir", default="/tmp/sota_shell_pad")
    ap.add_argument("--seed", type=int, default=8, help="PORT_SEED for every process (default 8)")
    ap.add_argument("--only", default=",".join(STEPS), help="steps: %s (the page steps follow one another in one process: title is needed first)" % ",".join(STEPS))
    ap.add_argument("--overlay-seed", default=None, help="a folder with registry.dat holding the licence value (default: port_overlay_sota of this checkout, if there is one)")
    a = ap.parse_args()
    only = [s for s in a.only.split(",") if s]
    overlay = a.overlay_seed or (os.path.join(REPO, "port_overlay_sota") if os.path.isdir(os.path.join(REPO, "port_overlay_sota")) else None)
    os.makedirs(a.workdir, exist_ok=True)
    pages = [s for s in only if s in ("title", "duel", "tools", "world", "help", "player")]
    t_start = time.time()
    if pages or "dialogs" in only:
        sh = Shell(a, "pages", a.seed, overlay=overlay)
        if not sh.start():
            print("FAIL  the shell did not come up with its five round buttons as targets (log: %s)" % sh.g.log_path)
            sh.stop()
            return 2
        state = {}
        try:
            print("--- the title page", flush=True)
            step_title(sh, state)
            state["ts"] = state["title"]
            for name, fn in (("duel", step_duel), ("tools", step_tools), ("world", step_world), ("help", step_help), ("player", step_player)):
                if name in only:
                    print("--- %s" % name, flush=True)
                    try:
                        fn(sh, state)
                    except Exception as e:                         # a step that cannot go on is one failed check, and the next one starts from the page the shell is on
                        check(False, "%s: the step stopped: %s: %s" % (name, type(e).__name__, e))
                    state["ts"] = recover(sh, state.get("ts"))
        finally:
            sh.stop()
        note("(the mouse put the pointer on a page's first target %d time(s) where a list or a dialog had just closed over it or a process had just started: nothing for a D-pad walk to start from)" % sh.mouse_puts)
        if "dialogs" in only:
            if overlay is None:
                skipped += 1
                print("SKIP  dialogs: no overlay with the licence value (--overlay-seed): Start match asks for the disc without it", flush=True)
            else:
                print("--- dialogs", flush=True)
                sh2 = Shell(a, "dialogs", a.seed, overlay=overlay)
                if sh2.start():
                    try:
                        st2 = {"ts": sh2.nav()[1], "title_graph": state.get("title_graph", {})}
                        step_dialogs(sh2, st2, a)
                    finally:
                        sh2.stop()
                else:
                    check(False, "the shell started for the dialogs")
                    sh2.stop()
    if "touch" in only:
        print("--- touch", flush=True)
        step_touch(a, a.seed, overlay)
    print("%s: %d check(s) failed, %d step(s) skipped, %.0f s" % ("FAILED" if failures else "ok", failures, skipped, time.time() - t_start), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

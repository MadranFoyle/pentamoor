#!/usr/bin/env python3
"""card_view.py: "view card" in a duel, headless: LB (a pad), V (a key) and the middle mouse button show the card under the pointer in the game's own Full-size card window at once; a second press
on the same card shows it enlarged over the whole window; and the game is sent nothing while that picture is up.

    python3 tools/soak/card_view.py [--res 1024x768] [--workdir /tmp/card_view] [--shots DIR] [--seed N] [--game magic|duel] [--deck]

The program is started on SDL's dummy drivers with its own control pipe and overlay (as tools/soak does), PORT_PAD_LOG=stderr so that the log says what reached the game. A duel is played with
the mouse (nav_play's helpers) until both sides have permanents, then, with controller commands (`pad press lb`), keys (`key v`) and the middle button (`viewcard X Y`), it checks:

  * a card of the hand and permanents of both sides: the pointer is put on a card, 0.5 s later the big card has not changed (the game's own hover waits three seconds), LB, and 0.6 s later the
    Full-size card window shows another picture, each time; V and the middle button do the same, and the card shown is the same picture as the hover shows after the wait;
  * a pointer on no card: LB is Page Up (the log says so), V and the middle button do nothing;
  * the enlarged card: the second LB on the same card gives a picture of the window (`winshot`) that is dimmed all round and has the card in the middle, of the size display_zoom_layout says, and
    the log says the enlarged card is up; while it is up the pad's stick, a mouse move, a click, a key and a pad button (B) send the game nothing (no `mouse` or `key` line of the log, no menu, the pad's
    cursor where it was), each of them ends it, and after it the window is exactly what it was before (a hash of the picture), and the game goes on: A on Done passes the phase;
  * --deck: DECK.EXE (the stand-alone deck builder): its big card follows the pointer at once (no button is needed there), LB and RB are still Page Up and Page Down, V and the middle button do nothing.

Prints one line per check, exits 1 if one failed. Needs the installed game (sources/installed) and the saved game (sources/emu_overlay), as the soak does.
"""
import argparse
import hashlib
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nav_play  # noqa: E402
import soak  # noqa: E402
from pentamoor_ctl import Game  # noqa: E402

REPO = nav_play.REPO
# The seeds the checks are run with (--seed; tools/soak/nav_play.py has the table of what each deals)
PINNED = {
}

failures = 0


def check(ok, what):
    global failures
    print("%s  %s" % ("ok  " if ok else "FAIL", what), flush=True)
    if not ok:
        failures += 1
    return ok


def read_ppm(path):
    with open(path, "rb") as f:
        data = f.read()
    parts = data.split(b"\n", 3)
    w, h = (int(v) for v in parts[1].split())
    return w, h, parts[3]


class View:
    """What a person sees and what the game log says."""

    def __init__(self, g, res, shots=None):
        self.g = g
        self.w, self.h = (int(v) for v in res.split("x"))
        self.shots = shots
        self.n = 0
        self.nv = nav_play.Nav(g, res)

    # ---- pictures ----
    def _wait_file(self, path, secs=8):
        end = time.time() + secs
        while time.time() < end and not (os.path.exists(path) and os.path.getsize(path) > 100):
            time.sleep(0.1)
        time.sleep(0.35)

    def frame(self, tag="f"):
        """The frame as the game drew it (`shot`), as (w, h, bytes)."""
        return read_ppm(self.nv.shot(tag))

    def window(self, tag="w"):
        """What the window shows (`winshot`: the picture, the enlarged card and the bars as the renderer draws them), as (w, h, bytes)."""
        path = os.path.join(self.g.workdir, tag + ".ppm")
        if os.path.exists(path):
            os.unlink(path)
        self.g.cmd("winshot " + path)
        self._wait_file(path)
        return read_ppm(path)

    def keep(self, im, name):
        """--shots: the picture as a PNG next to the others (a PPM when PIL is not there). Never committed: it shows the game."""
        if not self.shots:
            return
        os.makedirs(self.shots, exist_ok=True)
        self.n += 1
        w, h, pix = im
        path = os.path.join(self.shots, "%02d_%s" % (self.n, name))
        try:
            from PIL import Image
            Image.frombytes("RGB", (w, h), pix).save(path + ".png")
        except Exception:
            with open(path + ".ppm", "wb") as f:
                f.write(b"P6\n%d %d\n255\n" % (w, h) + pix)

    @staticmethod
    def crop(im, box):
        w, h, pix = im
        x0, y0, x1, y1 = box
        return b"".join(pix[(y * w + x0) * 3:(y * w + x1) * 3] for y in range(y0, y1))

    @staticmethod
    def mean(im, box):
        c = View.crop(im, box)
        return sum(c) / max(1, len(c))

    def big_card(self):
        """The Full-size card window's rectangle (x0, y0, x1, y1), from the window tree."""
        t = self.g.windows()
        fc = [w for w in t.find("MAGICGAME_FullCardClass") if w.visible and not w.empty] or [w for w in t.find("MagicFullCardClass") if w.visible and not w.empty]
        return (max(fc[0].x0, 0), fc[0].y0, min(fc[0].x1, self.w), fc[0].y1) if fc else None

    def big_hash(self, box, tag="b"):
        return hashlib.md5(self.crop(self.frame(tag), box)).hexdigest()[:8]

    # ---- the log ----
    def log_mark(self):
        return self.g.log_size()

    def log_since(self, off):
        return self.g.read_log(off)

    def settle(self, secs=0.8):
        time.sleep(secs)


def wait_log(v, off, text, secs=8.0):
    """Wait until the input log, from `off`, has `text`; returns whether it came."""
    end = time.time() + secs
    while time.time() < end:
        if text in v.log_since(off):
            return True
        time.sleep(0.1)
    return False


def open_enlarged(v, g, c, how="lb"):
    """The pointer is moved off the card and back (a move to another place makes the next view a first press) and the card is viewed twice: the game's own card, then the enlarged one.
    Returns (whether the enlarged card came up (the log says so), the window as it is with the game's own card shown, before the enlarged one: what it must be again after)."""
    g.cmd("move %d %d" % (v.w // 2 + 30, 20))
    time.sleep(0.4)
    g.cmd("move %d %d" % c.center)
    time.sleep(0.5)
    base = None
    for step in ("first", "second"):
        if step == "second":
            base = v.window("base_win")
        off = v.log_mark()
        if how == "lb":
            g.pad_press("lb")
        elif how == "v":
            g.cmd("key v")
        else:
            g.cmd("viewcard %d %d" % c.center)
        if not wait_log(v, off, "told 'View in full card'" if step == "first" else "the enlarged card is up"):
            return False, base
        time.sleep(0.4)
    return True, base


def deliveries(text):
    """The lines of the input log that say something reached the game: a mouse button, a key (guest side: `mouse left down at ... -> window ...`, `key vk 0x.. ch .. -> window ...`)."""
    return [ln for ln in text.split("\n") if re.search(r"padlog: (mouse (left|right) (down|up) at|key vk 0x)", ln)]


def duel_checks(g, res, shots):
    v = View(g, res, shots)
    nv = v.nv
    t = g.windows()
    box = v.big_card()
    check(box is not None, "the Full-size card window is on the screen: %s" % (box,))
    if not box:
        return
    mode, targets = nv.targets()
    cards = [x for x in targets if x.kind == nav_play.K_CARD]
    hand = sorted([x for x in cards if x.label == "Hand Card"], key=lambda x: x.y0)
    inplay = [x for x in cards if x.label == "In-play Card"]
    check(mode == "duel" and len(hand) >= 3 and len(inplay) >= 3, "a board to look at: %d cards of the hand, %d permanents" % (len(hand), len(inplay)))
    pick = [hand[0], hand[-1]] + inplay[:4]

    # ---- LB shows the card at once, V and the middle button too ----
    g.cmd("move %d %d" % (v.w // 2, v.h - 10))
    time.sleep(0.6)
    last = v.big_hash(box)
    shown = []
    for how in ("lb", "v", "middle"):
        for x in pick[:4] if how == "lb" else pick[1:3]:
            g.cmd("move %d %d" % x.center)
            time.sleep(0.5)
            before = v.big_hash(box)
            if how == "lb":
                g.pad_press("lb")
            elif how == "v":
                g.cmd("key v")
            else:
                g.cmd("viewcard %d %d" % x.center)
            time.sleep(0.6)
            after = v.big_hash(box)
            shown.append((how, x.label, x.center, before, after))
            check(after != before or before == last and after == last, "%s on %s at %s: the big card %s -> %s within 0.6 s" % (how, x.label, x.center, before, after))
            last = after
    # the hover (three seconds) shows the same picture the button did
    byc = {}
    for how, label, center, before, after in shown:
        byc.setdefault(center, after)                                 # what each card's picture was when LB showed it
    first = pick[0]
    second = next((p for p in pick if byc.get(p.center) != byc.get(first.center)), pick[1])      # a card whose picture is another one (two lands of one kind show the same)
    x = first
    g.cmd("move %d %d" % x.center)
    time.sleep(0.5)
    g.pad_press("lb")
    time.sleep(0.6)
    by_button = v.big_hash(box)
    g.cmd("move %d %d" % second.center)
    time.sleep(0.5)
    g.pad_press("lb")
    time.sleep(0.6)
    other = v.big_hash(box)
    g.cmd("move %d %d" % x.center)                                   # back on the first: the game's own hover shows it after its wait
    nav_play.settled_crop(nv, box, "hover_wait", limit=16.0)
    by_hover = v.big_hash(box)
    check(by_button != other and by_hover == by_button, "the picture LB gives is the one the game's own hover gives after its wait (%s, %s)" % (by_button, by_hover))

    # ---- a pointer on no card: Page Up, and V and the middle button do nothing ----
    g.cmd("move %d %d" % (v.w // 2 + 30, 20))
    time.sleep(0.6)
    off = v.log_mark()
    pic = v.big_hash(box)
    g.pad_press("lb")
    g.cmd("key v")
    g.cmd("viewcard %d %d" % (v.w // 2 + 30, 20))
    time.sleep(0.8)
    log = v.log_since(off)
    check(v.big_hash(box) == pic, "no card under the pointer: LB, V and the middle button leave the big card alone")
    check("pad: key down vk 0x21" in log, "no card under the pointer: LB is Page Up (the log has its key)")
    check("the enlarged card is up" not in log, "and no enlarged card")

    # ---- the enlarged card ----
    c = hand[-1]
    g.cmd("move %d %d" % c.center)
    time.sleep(0.5)
    g.pad_press("lb")
    time.sleep(0.8)
    before_frame = v.frame("before")
    before_win = v.window("before_win")
    pos0 = nv.pos()
    off = v.log_mark()
    g.pad_press("lb")
    time.sleep(1.0)
    log = v.log_since(off)
    check("the enlarged card is up" in log, "the second LB on the same card shows it enlarged (the log says so)")
    win = v.window("zoom_win")
    v.keep(before_win, "window_before")
    v.keep(win, "window_zoom_lb")
    ww, wh, _ = win
    zx0, zy0, zx1, zy1 = ww // 2 - 40, wh // 2 - 60, ww // 2 + 40, wh // 2 + 60
    check(win[2] != before_win[2], "the window shows something else with the enlarged card up")
    corner = (4, 4, 40, 40)
    check(v.mean(win, corner) < 0.6 * max(1.0, v.mean(before_win, corner)) or v.mean(before_win, corner) < 8, "the rest of the picture is dimmed (%.0f -> %.0f)" % (v.mean(before_win, corner), v.mean(win, corner)))
    # where the card is: the bright part of the middle column, found from the picture itself
    row = v.crop(win, (0, wh // 2, ww, wh // 2 + 1))                  # the dimmed picture is at most 255 - ZOOM_DIM_ALPHA bright: only the card's white border passes 200
    bright = [x for x in range(ww) if min(row[3 * x:3 * x + 3]) > 200]
    left, right = (bright[0], bright[-1]) if bright else (0, 0)
    mid = (left + right) / 2.0
    check(bright and abs(mid - ww / 2.0) <= ww * 0.03 and (right - left) > 0.3 * wh * (box[2] - box[0]) / (box[3] - box[1]) and left > ww * 0.05,
          "the enlarged card is centred (middle %.0f of %d) and about the size display_zoom_layout gives (%d px wide)" % (mid, ww, right - left))
    # nothing reaches the game while it is up
    off = v.log_mark()
    g.pad("stick l 1 0")
    time.sleep(0.5)
    g.pad("stick l 0 0")
    g.cmd("move %d %d" % (v.w // 3, v.h // 3))
    g.cmd("wmove 20 20")
    time.sleep(0.4)
    p1 = nv.pos()
    log = v.log_since(off)
    check(p1 == pos0 and not deliveries(log), "a pad stick pushed and the mouse moved while it is up: the pad's cursor stays %s, the game is sent nothing" % (pos0,))
    check(v.window("still_up")[2] == win[2], "and the picture is still up and unchanged")
    off = v.log_mark()
    g.cmd("key escape")                      # the picture is still up from the checks above: end it, then each kind of press is tried on a fresh one
    check(wait_log(v, off, "the enlarged card is closed", 4), "Escape ends the first one")
    for how, act in (("B", lambda: g.pad_press("b")), ("a key", lambda: g.cmd("key return")), ("a click", lambda: g.click(v.w // 3, v.h // 3)), ("a right click", lambda: g.cmd("rdown 100 100\nrup")),
                     ("A", lambda: g.pad_press("a")), ("the D-pad", lambda: g.pad_press("down")), ("Back", lambda: g.pad_press("back")), ("Y", lambda: g.pad_press("y")), ("X", lambda: g.pad_press("x"))):
        up, base = open_enlarged(v, g, c)
        check(up, "the enlarged card is up (before testing %s)" % how)
        off = v.log_mark()
        act()
        time.sleep(1.0)
        log = v.log_since(off)
        t = g.windows()
        after_win = v.window("after_" + how.replace(" ", "_"))
        check("the enlarged card is closed" in log and not deliveries(log) and not t.items and not t.dialogs(),
              "%s ends the enlarged card and the game is sent nothing (log: %s; menu rows %d; dialogs %d)" % (how, [ln[-60:] for ln in deliveries(log)][:2] or "no input line", len(t.items), len(t.dialogs())))
        same = base is not None and after_win[2] == base[2]
        check(same, "after %s the window is exactly what it was before the enlarged card" % how)
        if not same:
            v.keep(base, "base_" + how.replace(" ", "_"))
            v.keep(after_win, "differs_after_" + how.replace(" ", "_"))
    # the keyboard's second step (V twice), the middle button's (twice), and how each is ended
    up, _ = open_enlarged(v, g, c, "v")
    check(up, "V twice on a card: the second shows it enlarged")
    v.keep(v.window("zoom_v"), "window_zoom_v")
    off = v.log_mark()
    g.cmd("key escape")
    check(wait_log(v, off, "the enlarged card is closed", 4) and not deliveries(v.log_since(off)), "Escape ends it and is not the game's")
    up, _ = open_enlarged(v, g, inplay[0], "middle")
    check(up, "the middle button twice on a permanent: the second shows it enlarged")
    v.keep(v.window("zoom_mid"), "window_zoom_middle")
    off = v.log_mark()
    g.click(60, 60)
    check(wait_log(v, off, "the enlarged card is closed", 4) and not deliveries(v.log_since(off)), "a click ends it and is not the game's")
    # a pointer that moved between the two presses makes the second a first one
    g.cmd("move %d %d" % (v.w // 2 + 30, 20))
    time.sleep(0.4)
    g.cmd("move %d %d" % c.center)
    time.sleep(0.5)
    off = v.log_mark()
    g.pad_press("lb")
    check(wait_log(v, off, "told 'View in full card'"), "LB on a card: the game's own card")
    g.cmd("move %d %d" % (c.center[0], c.center[1] + 1))
    time.sleep(0.4)
    off = v.log_mark()
    g.pad_press("lb")
    ok1 = wait_log(v, off, "told 'View in full card'")
    check(ok1 and "the enlarged card is up" not in v.log_since(off), "after the pointer moved, the next LB is a first press again (the game's own card, not the enlarged one)")

    # ---- the game goes on ----
    t = g.windows()
    b = t.bar()
    title0 = b[0].title if b else ""
    done = b[2] if b else None
    check(done is not None, "the Done button is there")
    if done:
        for _ in range(3):
            g.cmd("move %d %d" % done.center)
            time.sleep(0.4)
            g.pad_press("a")
            time.sleep(2.5)
            t = g.windows()
            title1 = t.bar()[0].title if t and t.bar() else None
            if title1 != title0:
                break
        check(title1 != title0, "the game goes on after the enlarged card: A on Done passed the phase (%r -> %r)" % (title0[:30], (title1 or "")[:30]))
    check(g.alive(), "the program is still running")


def deck_checks(args):
    g = Game(REPO, res=args.res, workdir=os.path.join(args.workdir, "deck"), program="sources/installed/Magic/Program/DECK.EXE")
    g.start()
    try:
        time.sleep(12)
        v = View(g, args.res, args.shots)
        box = v.big_card()
        check(box is not None, "the deck builder's Full-size card window (MagicFullCardClass) is on the screen: %s" % (box,))
        if not box:
            return
        t = g.windows()
        lst = [w for w in t.wins if w.cls == "MAGICDECK_HorzListClass" and w.visible]
        check(bool(lst), "the card picture list is there")
        if not lst:
            return
        row = lst[0]
        x, y = row.x0 + 220, (row.y0 + row.y1) // 2
        base = v.big_hash(box)
        g.cmd("move %d %d" % (x, y))
        time.sleep(0.8)
        check(v.big_hash(box) != base, "the deck builder's big card follows the pointer at once (no button needed): %s -> %s" % (base, v.big_hash(box)))
        off = v.log_mark()
        g.pad_press("lb")
        g.pad_press("rb")
        g.cmd("key v")
        g.cmd("viewcard %d %d" % (x, y))
        time.sleep(1.0)
        log = v.log_since(off)
        check("pad: key down vk 0x21" in log and "pad: key down vk 0x22" in log, "LB and RB are still Page Up and Page Down there")
        check("the enlarged card is up" not in log and "View in full card" not in log, "V and the middle button do nothing there")
        check(g.alive(), "the program is still running")
    finally:
        g.stop()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--res", default="1024x768", choices=["640x480", "800x600", "1024x768"])
    ap.add_argument("--workdir", default="/tmp/card_view")
    ap.add_argument("--shots", default=None, help="keep the window pictures here (they show the game: never commit them)")
    ap.add_argument("--seed", type=int, default=5, help="the script's own choices, and PORT_SEED for the game (src/port/seed.h): the same seed plays the same duel")
    ap.add_argument("--game", choices=["magic", "duel"], default="magic", help="magic: MAGIC.EXE's saved game; duel: DUEL.EXE's setup dialog")
    ap.add_argument("--deck", action="store_true", help="also check DECK.EXE, the stand-alone deck builder")
    a = ap.parse_args()
    os.environ["PORT_SEED"] = str(a.seed)               # the game's own chance (src/port/seed.h) is pinned too: the same seed deals the same cards
    os.environ["PORT_PAD_LOG"] = "stderr"
    os.makedirs(a.workdir, exist_ok=True)
    p = nav_play.Player(a)
    g = p.new_game()
    try:
        p.to_ante()
        ok = nav_play.pad_start(p, g, a.res)
        check(ok, "a duel started")
        t = p.populate() if ok else None
        check(t is not None, "the board has several permanents on both sides")
        if t is not None:
            duel_checks(g, a.res, a.shots)
    finally:
        g.stop()
    if a.deck:
        deck_checks(a)
    bad = failures + nav_play.failures
    print("%d check(s) failed" % bad if bad else "all checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

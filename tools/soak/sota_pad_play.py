#!/usr/bin/env python3
"""sota_pad_play.py: play Spells of the Ancients 2.15 (shandalar.exe) with controller input only, headless, and check what the game did (docs/notes/sota-comparison.md, "Milestone 4").

    python3 tools/soak/sota_pad_play.py [--res 1024x768] [--workdir /tmp/sota_pad_play] [--shots DIR] [--only newgame,map,save,village,duel,reward,back]

The program is started on SDL's dummy drivers with its own control pipe and an empty overlay (as sota_soak.py does) and driven with the `pad` steps of PORT_CONTROL only, which go through the
same code as a real controller's events (docs/notes/controller.md); the only other things the script does are reading the game's memory and the window tree to check each step, keeping the wandering
monsters off the map (pokes: they walk into the party at every step otherwise) and putting the party on a place or a monster of the map (pokes, as sota_soak.py does: walking there with the stick
is not what is tested). 2.15 has no saved game to start from, so every run begins with a new game:

  newgame   the title menu, difficulty and colour with the D-pad and A, FaceMaker (a second program, no D-pad targets: the left stick and A put the portrait in), the name accepted empty with X
  map       walking (right trigger and the left stick; the right stick as arrow keys; the D-pad is the arrow keys there), B opening the game's menu of nine lines, the D-pad on it, Back closing it
  save      B, Save, the first slot, the name accepted empty with X; B, Load, the slot: the party is where it was; Resume Game from the title menu on a new process gives it back again
  places    a castle, a tower and a dungeon (put there by pokes): the gate's text menu with the D-pad and A, the maze with the arrow keys (the right stick, the D-pad), Back out
  village   the nine buttons (hover checked at each), Buy 10 food by one A, Cards for Sale, the "Buy for N gold? (Y/N)" question answered yes with A and no with B, the deck editor (its cards and
            buttons as targets, B on a card, "Sell Card for N" chosen with the D-pad and A), the wizard's stats, the clues, the world map
  duel      an encounter's text menu, Duel, the intro dialogs, a land played, a creature cast (Y on it), an attack (A on the creature, then Done) and the phases passed with Done, the opponent's life poked
            to 0 to end the duel
  reward    "Take the cards", the card list, a card taken with A on it and the "Take this card? (Y/N)" question: B (no) and A (yes); the dungeon clue's page and the clue list
  back      Back at the title menu: a tap does nothing, a hold of 0.9 s leaves the game

Prints one line per check and exits 1 if one failed. Needs the 2.15 install (`pentamoor-install ... --sota ... --patch ...`) and the runtime; the addresses are shandalar.exe 2.15's.
"""
import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screen_nav_play as base  # noqa: E402
import sota_soak  # noqa: E402
from pentamoor_ctl import Game  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# shandalar.exe 2.15
GOLD, FOOD, HOVER = 0x57a7bc, 0x57a7c0, 0x5780bc
base.GOLD, base.FOOD, base.HOVER = GOLD, FOOD, HOVER
LIVES = sota_soak.LIVES
K_CARD, K_BUTTON, K_ROW, K_MENU = 1, 2, 4, 9
FACE_LEAVE = (395, 160)             # FaceMaker's "Leave" button at 1024x768 (what sota_soak.py clicks for the portrait): the stick and A

failures = 0


def check(ok, what):
    global failures
    print("%s  %s" % ("ok  " if ok else "FAIL", what), flush=True)
    if not ok:
        failures += 1
    return ok


class Session(base.Session):
    def __init__(self, a):
        self.a = a
        self.res = a.res
        self.w, self.h = (int(v) for v in a.res.split("x"))
        self.nshot = 0
        self.quiet = False
        self.wd = os.path.join(a.workdir, a.res)
        self.g = None
        self.keeper_on = threading.Event()
        threading.Thread(target=self._keeper, daemon=True).start()
        self.facemaker = None
        self.extra_env = {}

    def new_process(self, seed=None, name="game"):
        """A new game process; `seed`: a folder copied to be its overlay (the saves of an earlier process)."""
        ext = "dylib" if sys.platform == "darwin" else "so"
        wd = os.path.join(self.wd, name)
        self.g = Game(REPO, res=self.res, workdir=wd, exe="src/port/build/pentamoor-run", program="sources/installed_sota/Magic/Program/shandalar.exe",
                      module=os.path.join(REPO, "src/port/build", "game_shandalar." + ext), overlay_seed=seed, extra_env=dict({"PORT_PAD_LOG": "stderr"}, **self.extra_env))
        return self.g

    # ---- the monsters ------------------------------------------------------------------------------------------------
    def clear_monsters(self):
        self.g.poke_many([(sota_soak.MONSTERS + sota_soak.MONSTER_STRIDE * i, 0xffffffff) for i in range(sota_soak.N_MONSTERS)])

    def _keeper(self):
        while True:
            time.sleep(0.25)
            g = self.g
            if self.keeper_on.is_set() and g is not None and g.alive():
                self.clear_monsters()

    def monsters(self):
        v = self.g.peek(sota_soak.MONSTERS, 6 * sota_soak.N_MONSTERS)
        if not v:
            return []
        return [(v[6 * i + 1], v[6 * i + 2]) for i in range(sota_soak.N_MONSTERS) if v[6 * i] != 0xffffffff and 0 < v[6 * i + 1] < 4000 and 0 < v[6 * i + 2] < 4000]

    def places(self):
        loc = self.mem(sota_soak.LOCATIONS, 25 * 128)
        return [(loc[25 * i], loc[25 * i + 1], loc[25 * i + 2]) for i in range(128) if loc[25 * i] in (1, 2, 3, 4)]

    def teleport(self, tx, ty):
        """The party on tile (tx, ty), the map told to draw itself whole (sota_soak.teleport_pokes), no monster near."""
        self.keeper_on.clear()
        self.clear_monsters()
        self.g.poke(GOLD, max(self.mem(GOLD)[0], 400))
        self.g.poke(FOOD, max(self.mem(FOOD)[0], 100))
        self.g.poke_many(sota_soak.teleport_pokes(tx, ty))
        self.wait(3.5)
        self.keeper_on.set()

    def tile(self):
        v = self.g.peek(sota_soak.PARTY_TILE[0], 2)
        return tuple(v) if v else None

    # ---- the pad ------------------------------------------------------------------------------------------------------
    def tap(self, name, wait=0.5):
        self.g.pad_press(name)
        time.sleep(wait)

    def hold(self, name, secs=0.3):
        """A button held: the map reads the button once a frame, so a tap of 70 ms can fall between two frames."""
        self.g.pad_press(name, hold=secs)

    def stick_to(self, x, y):
        return self.g.pad_goto(x, y)

    def wait_mode(self, modes, timeout=20.0, minimum=0):
        return self.wait_nav(lambda m, t: m in modes and len(t) >= minimum, timeout)

    def to_target(self, goal, limit=24):
        """D-pad presses until the pointer is on the target `goal(targets)` picks (see Session.dpad_to); the number of presses or None."""
        return self.dpad_to(goal, limit)

    def press_target(self, goal, wait=2.5, limit=24):
        n = self.to_target(goal, limit)
        if n is None:
            return None
        self.press_a(wait)
        return n

    def stick_press(self, goal, wait=2.5, button="a"):
        """The left stick puts the cursor on the target `goal(targets)` picks and a button is pressed there (the D-pad's jumps in a duel are tested on their own: dpad_checks)."""
        mode, tl = self.nav()
        tgt = goal(tl)
        if tgt is None:
            return None
        self.g.pad_goto(*tgt.center)
        self.tap(button, 0.2)
        self.wait(wait)
        return tgt

    def screen_png(self, tag):
        self.shot(tag)

    def dismiss(self, tries=6):
        """A screen that waits for a click and has no targets (a message, a movie, a page): A, until something with targets (or the map) is there."""
        for _ in range(tries):
            mode, tl = self.nav()
            if mode not in (None, "none"):
                return mode, tl
            self.tap("a", 1.5)
        return self.nav()


# ---- new game ---------------------------------------------------------------------------------------------------------------------------
def newgame(s):
    g = s.new_process(name="game")
    g.start()
    s.wait(12)
    mode, tl = s.wait_mode(("screen",), 20, 2)
    check(mode == "screen" and len(tl) == 2, "the title menu: 2 targets (Load and Resume are greyed: no saved game yet): mode %s, %d" % (mode, len(tl)))
    s.hover_check(tl, "the title menu")
    check(g.pad_pos() is not None and g.pad_pos()[2] == 0, "no pad cursor before the pad is used")
    s.shot("title")
    n = s.to_target(lambda tl: min(tl, key=lambda t: t.y0) if tl else None)
    check(n is not None and n <= 3, "the D-pad reaches 'Start New Game' (%s presses)" % n)
    check(g.pad_pos()[2] == 1, "the pad is the active device once it is used")
    s.press_a(3)
    for name, want in (("difficulty", 4), ("colour", 5)):
        mode, tl = s.wait_mode(("screen",), 10, want)
        check(mode == "screen" and len(tl) == want, "%s: %d targets (%d)" % (name, want, len(tl)))
        s.hover_check(tl, name)
        s.shot(name)
        n = s.to_target(lambda tl: min(tl, key=lambda t: (t.y0, t.x0)) if tl else None)
        check(n is not None, "the D-pad reaches the first choice of the %s screen (%s presses)" % (name, n))
        s.press_a(3 if name == "difficulty" else 1)
    # the colour starts FaceMaker, a second program with a control pipe of its own
    fm = g.ctl_path + ".facemaker"
    end = time.time() + 90
    while time.time() < end and not os.path.exists(fm):
        time.sleep(0.5)
    check(os.path.exists(fm), "the colour starts FaceMaker (a second process)")
    if not os.path.exists(fm):
        return False
    fgame = Game(REPO, res=s.res, workdir=g.workdir)
    fgame.attach(g.pid)
    os.close(fgame._ctl)
    fgame._ctl = os.open(fm, os.O_RDWR | os.O_NONBLOCK)
    t_end = time.time() + 120
    off = g.log_size()
    while time.time() < t_end:
        fgame.cmd("windows")
        time.sleep(1.0)
        if "FacemakerMainClass" in g.read_log(off):
            break
    time.sleep(4)
    s.fm_shot = lambda tag: fgame.shot(os.path.join(s.a.shots, "%s.png" % tag)) if s.a.shots else None
    s.fm_shot("facemaker")
    r = fgame.nav_targets()
    check(r is not None and r[0] == "none", "FaceMaker has no D-pad targets (mode %s): the stick and A" % (r and r[0]))
    p = fgame.pad_goto(*FACE_LEAVE, tol=10)
    check(p is not None and 335 <= p[0] <= 455 and 140 <= p[1] <= 182, "the left stick puts the cursor on Leave (%s)" % (p,))
    fgame.pad_press("a")
    t_end = time.time() + 30
    while time.time() < t_end and os.path.exists(fm) and fgame.windows(timeout=3) is not None:
        time.sleep(1)
    time.sleep(6)
    s.shot("name")
    mode, tl = s.nav()
    check(mode in ("none", None) and not tl, "the name box has no targets: mode %s" % mode)
    s.keeper_on.set()
    g.pad_press("x")                                      # Enter: the name stays empty
    t_end = time.time() + 120
    ok = False
    while time.time() < t_end:
        time.sleep(2)
        if not g.alive():
            break
        t = s.tile()
        if t and t[0] > 0 and t[1] > 0 and "statwin.dll" in g.read_log(0):
            ok = True
            break
    time.sleep(5)
    check(ok and g.alive(), "X accepted the empty name: the world is made and the party stands at tile %s" % (s.tile(),))
    s.shot("map")
    return ok


def first_menu(s):
    """A first encounter can be at the very start (a monster next to the party): the text menu of two lines. Pay it with the D-pad."""
    mode, tl = s.nav()
    if mode == "screen" and len(tl) == 2 and tl[0].label == "line 0":
        gold = s.gold()
        s.press_target(lambda tl: tl[1] if len(tl) > 1 else None, 4)
        check(s.gold() < gold, "the first encounter was paid with the D-pad: gold %s -> %s" % (gold, s.gold()))
        s.wait(2)
        s.dismiss(2)
    s.keeper_on.set()


# ---- the map --------------------------------------------------------------------------------------------------------------------------
def to_map(s):
    """Walking can end in a village or at an encounter (the map's places and the wandering monsters): a village is left by its last button, an encounter's two lines by the second one (pay or leave), a message by A."""
    for _ in range(4):
        s.clear_monsters()
        mode, tl = s.nav()
        if mode == "screen" and len(tl) == 9 and all(t.kind == K_BUTTON for t in tl):
            s.press_target(lambda tl: sorted([t for t in tl if t.x0 > 0.05 * s.w], key=lambda t: (t.y0, t.x0))[-1] if tl else None, 4)
        elif mode == "screen" and len(tl) == 2 and tl[0].label == "line 0":
            s.press_target(lambda tl: tl[1] if len(tl) > 1 else None, 4)
        else:
            return


def open_map_menu(s, tries=12):
    """B opens the game's menu of the map: a text menu of nine lines. A tap of B can fall between two frames of the map (it is read once a frame), so the button is held a little."""
    for i in range(tries):
        s.clear_monsters()
        s.stick_to(s.w // 2 + 40 * (i % 3), s.h // 3 + 30 * (i % 2))
        s.hold("b", 0.3 if i % 2 == 0 else 0.15)
        mode, tl = s.wait_mode(("screen",), 2.5, 5)
        if mode == "screen" and len(tl) == 9:
            return tl
        if mode == "screen":
            s.tap("back", 1.0)
        elif mode not in (None, "none"):
            return None
    return None


def maponly(s):
    g = s.g
    s.keeper_on.set()
    s.wait(2)
    mode, tl = s.nav()
    check(mode in ("none", None) and not tl, "on the map there is nothing for the D-pad to navigate (mode %s)" % mode)
    pix1 = pix0 = g.peek(sota_soak.PARTY_PIXEL[0], 2)
    for dx, dy, name in ((1, 0, "east"), (0, 1, "south"), (-1, 0, "west"), (0, -1, "north")):      # the ground can be in the way on one side
        g.pad("axis rt 1")                                # walk mode: the right trigger held, the left stick pushed
        g.pad("stick l %d %d" % (dx, dy))
        s.wait(2.5)
        pos = g.pad_pos()
        g.pad("stick l 0 0")
        s.wait(0.4)
        g.pad("axis rt 0")
        pix1 = g.peek(sota_soak.PARTY_PIXEL[0], 2)
        if pix1 != pix0:
            break
    check(pos is not None and pos[3] == 1, "walking holds the left button (pad pos %s)" % (pos,))
    check(g.pad_pos()[3] == 0, "letting go of the stick lets go of the button")
    check(pix1 is not None and pix0 is not None and pix1 != pix0, "the party walked %s: %s -> %s" % (name, pix0, pix1))
    g.pad("stick r 0 1")                                  # the right stick: arrow keys
    s.wait(1.5)
    g.pad("stick r 0 0")
    s.wait(0.5)
    pix2 = g.peek(sota_soak.PARTY_PIXEL[0], 2)
    check(pix2 is not None and pix2 != pix1, "the right stick walked the party as the arrow keys do: %s -> %s" % (pix1, pix2))
    g.pad("button up down")                               # the D-pad has nothing to navigate to here: it is the arrow key, which walks
    s.wait(1.2)
    g.pad("button up up")
    s.wait(0.4)
    pix3 = g.peek(sota_soak.PARTY_PIXEL[0], 2)
    check(pix3 is not None and pix3 != pix2, "the D-pad is still the arrow keys on the map: %s -> %s" % (pix2, pix3))
    to_map(s)
    tl = open_map_menu(s)
    s.shot("map_menu")
    check(tl is not None and len(tl) == 9 and all(t.kind == K_MENU for t in tl), "B on the map opens the game's menu: its 9 lines are targets (%s)" % (len(tl) if tl else None))
    if not tl:
        return
    n = s.to_target(lambda tl: tl[6] if len(tl) > 6 else None)
    check(n is not None, "the D-pad reaches 'See Dungeon Clues' (%s presses)" % n)
    g.pad_press("back")                                   # Escape closes the menu
    s.wait(2)
    mode, tl = s.nav()
    check(mode in ("none", None), "Back closes the menu (mode %s)" % mode)


# ---- save and load -----------------------------------------------------------------------------------------------------------------
def menu_line(s, index, what):
    to_map(s)
    tl = open_map_menu(s)
    if not tl:
        check(False, "B opens the map's menu for %s" % what)
        return False
    n = s.to_target(lambda tl: tl[index] if len(tl) > index else None)
    if n is None:
        check(False, "the D-pad reaches the menu line for %s" % what)
        return False
    s.press_a(3)
    return True


def saveload(s):
    g = s.g
    s.keeper_on.set()
    tile0 = s.tile()
    if not menu_line(s, 0, "Save"):
        return
    mode, tl = s.wait_mode(("screen",), 8, 10)
    s.shot("save")
    check(mode == "screen" and len(tl) == 10 and all(t.kind == K_BUTTON for t in tl), "Save: the ten slots are targets (%s, %d)" % (mode, len(tl)))
    s.hover_check(tl, "the save screen")
    n = s.to_target(lambda tl: min(tl, key=lambda t: t.y0) if tl else None)
    check(n is not None, "the D-pad reaches the first slot (%s presses)" % n)
    s.press_a(2)
    g.pad_press("x")                                      # the name stays empty: Enter
    s.wait(4)
    overlay = os.path.join(g.workdir, "overlay", "Program")
    names = sorted(os.listdir(overlay)) if os.path.isdir(overlay) else []
    check(all(any(n.lower() == "magic3." + e for n in names) for e in ("sve", "map", "fce")), "the save is on disk (MAGIC3.SVE, .map, .fce): %s" % [n for n in names if n.lower().startswith("magic")])
    mode, tl = s.nav()
    check(mode in ("none", None), "back on the map (mode %s)" % mode)
    # move the party away, then load
    tx, ty = (tile0[0] + 5) % 40 + 10, (tile0[1] + 4) % 30 + 10
    s.keeper_on.clear()
    g.poke_many(sota_soak.teleport_pokes(tx, ty))
    s.wait(3)
    s.keeper_on.set()
    check(s.tile() != tile0, "the party was moved away from %s: now at %s" % (tile0, s.tile()))
    if not menu_line(s, 1, "Load"):
        return
    mode, tl = s.wait_mode(("screen",), 8, 10)
    check(mode == "screen" and len(tl) >= 1, "Load: the slot with a save in it is a target (%d)" % len(tl))
    n = s.to_target(lambda tl: min(tl, key=lambda t: t.y0) if tl else None)
    s.press_a(8)
    s.keeper_on.set()
    back = s.tile()
    check(back is not None and abs(back[0] - tile0[0]) <= 3 and abs(back[1] - tile0[1]) <= 3, "Load: the party is back where it was saved: saved %s, now %s" % (tile0, back))
    mode, tl = s.nav()
    check(mode in ("none", None), "and the map is on (mode %s)" % mode)
    # leave by the menu's Quit (line 2) and its question, then Resume Game on a new process
    if not menu_line(s, 2, "Quit"):
        return
    mode, tl = s.wait_mode(("screen",), 6, 2)
    s.shot("quit")
    check(mode == "screen" and len(tl) == 2, "Quit asks 'Ready to Quit?': two lines as targets (%d)" % len(tl))
    left_at = s.tile()
    n = s.to_target(lambda tl: tl[1] if len(tl) > 1 else None)
    s.press_a(1)
    end = time.time() + 25
    while g.alive() and time.time() < end:
        time.sleep(0.5)
    check(not g.alive(), "the question's second line quit the game by itself")
    overlay_dir = os.path.join(g.workdir, "overlay")
    g.stop()
    s.keeper_on.clear()
    import shutil
    seed = os.path.join(s.wd, "seed")
    shutil.rmtree(seed, ignore_errors=True)
    shutil.copytree(overlay_dir, seed)
    g2 = s.new_process(seed=seed, name="resume")
    g2.start()
    s.wait(12)
    mode, tl = s.wait_mode(("screen",), 20, 4)
    check(mode == "screen" and len(tl) == 4, "the title menu now has 4 targets: Load Saved Game and Resume Game are open (%d)" % len(tl))
    s.hover_check(tl, "the title menu with a saved game")
    n = s.to_target(lambda tl: sorted(tl, key=lambda t: t.y0)[2] if len(tl) > 2 else None)
    check(n is not None, "the D-pad reaches 'Resume Game' (%s presses)" % n)
    s.press_a(12)
    s.keeper_on.set()
    resumed = s.tile()
    check(resumed is not None and abs(resumed[0] - left_at[0]) <= 3 and abs(resumed[1] - left_at[1]) <= 3, "Resume Game: the party is where it was when the game was left: %s, now %s" % (left_at, resumed))
    s.shot("resumed")


# ---- a village -------------------------------------------------------------------------------------------------------------------------
def five(s, tl):
    """The village's five big buttons, top to bottom, left to right: Buy Cards, (Begin a Quest in the middle), Edit deck/Sell cards, Buy 10 food, Leave"""
    return sorted([t for t in tl if t.x0 > 0.05 * s.w], key=lambda t: (t.y0, t.x0))


def left(s, tl):
    return sorted([t for t in tl if t.x0 < 0.05 * s.w], key=lambda t: t.y0)


def enter_village(s):
    for attempt in range(3):
        to_map(s)
        vil = [p for p in s.places() if p[0] == 1]
        t = s.tile()
        vil.sort(key=lambda p: (p[1] - t[0]) ** 2 + (p[2] - t[1]) ** 2)
        s.teleport(vil[min(attempt, len(vil) - 1)][1], vil[min(attempt, len(vil) - 1)][2])
        mode, tl = s.wait_mode(("screen",), 12, 9)
        if mode == "screen" and len(tl) == 9:
            return True
    return False


def village(s):
    s.keeper_on.set()
    ok = enter_village(s)
    mode, tl = s.nav()
    s.shot("village")
    check(ok, "a village: 9 targets, its five buttons and the map's four (%s, %d)" % (mode, len(tl)))
    if not ok:
        return
    s.hover_check(tl, "the village")
    gold, food = s.gold(), s.food()
    n = s.to_target(lambda tl: five(s, tl)[3] if len(five(s, tl)) == 5 else None)
    check(n is not None, "the D-pad reaches 'Buy 10 food' (%s presses)" % n)
    s.press_a(3)
    check(s.gold() == gold - 15 and s.food() == food + 10, "one A press bought food once: gold %d -> %d, food %d -> %d" % (gold, s.gold(), food, s.food()))
    # Cards for Sale
    n = s.to_target(lambda tl: five(s, tl)[0] if len(five(s, tl)) == 5 else None)
    check(n is not None, "the D-pad reaches 'Buy Cards' (%s presses)" % n)
    s.press_a(4)
    mode, tl = s.wait_nav(lambda m, t: m == "screen" and any(x.kind == K_CARD for x in t), 6)
    if not any(x.kind == K_CARD for x in tl):             # the card seller's hint waits for a click first
        s.press_a(3)
        mode, tl = s.wait_nav(lambda m, t: m == "screen" and any(x.kind == K_CARD for x in t), 8)
    s.shot("buycards")
    cards = [t for t in tl if t.kind == K_CARD]
    check(len(cards) >= 3 and sum(1 for t in tl if t.kind == K_BUTTON) == 1, "Cards for Sale: the cards (%d) and Done are targets" % len(cards))
    s.hover_check([t for t in tl if t.kind == K_BUTTON], "Cards for Sale")
    cards.sort(key=lambda t: t.x0)
    gold = s.gold()
    n = s.to_target(lambda tl: sorted([t for t in tl if t.kind == K_CARD], key=lambda t: t.x0)[0] if tl else None)
    check(n is not None, "the D-pad reaches the first card (%s presses)" % n)
    s.press_a(2.5)
    mode, tl2 = s.nav()
    check(not [t for t in tl2 if t.kind == K_CARD], "the question 'Buy for N gold? (Y/N)' has no targets (mode %s): it is a key prompt" % mode)
    s.shot("buy_question")
    s.tap("b", 3)                                         # B answers no: the card stays on the shelf
    mode, tl3 = s.wait_nav(lambda m, t: m == "screen" and any(x.kind == K_CARD for x in t), 8)
    check(s.gold() == gold and len([t for t in tl3 if t.kind == K_CARD]) == len(cards), "B answered no: gold %d -> %d, the card is still there (%d cards)" % (gold, s.gold(), len([t for t in tl3 if t.kind == K_CARD])))
    n = s.to_target(lambda tl: sorted([t for t in tl if t.kind == K_CARD], key=lambda t: t.x0)[0] if tl else None)
    s.press_a(2.5)
    s.tap("a", 3)                                         # A answers yes
    mode, tl3 = s.wait_nav(lambda m, t: m == "screen" and any(x.kind == K_CARD for x in t), 8)
    check(s.gold() < gold and len([t for t in tl3 if t.kind == K_CARD]) == len(cards) - 1, "A answered yes: gold %d -> %d and the card is gone from the targets (%d left)" % (gold, s.gold(), len([t for t in tl3 if t.kind == K_CARD])))
    n = s.to_target(lambda tl: [t for t in tl if t.kind == K_BUTTON][0] if tl else None)
    s.press_a(3)
    mode, tl = s.wait_mode(("screen",), 8, 9)
    check(mode == "screen" and len(tl) == 9, "Done is back at the village (%d targets)" % len(tl))
    # the deck editor
    n = s.to_target(lambda tl: five(s, tl)[1] if len(five(s, tl)) == 5 else None)
    check(n is not None, "the D-pad reaches 'Edit deck/Sell cards' (%s presses)" % n)
    s.press_a(6)
    mode, tl = s.wait_mode(("deck",), 12, 10)
    s.shot("deck")
    cardt = [t for t in tl if t.kind == K_CARD]
    buttons = [t for t in tl if t.kind == K_BUTTON]
    check(mode == "deck" and len(cardt) >= 10 and len(buttons) == 5, "the deck editor: %d cards (strips) and %d buttons (Stats, three decks, Done) are targets (%s)" % (len(cardt), len(buttons), mode))
    gold = s.gold()
    col0 = lambda tl: sorted([t for t in tl if t.kind == K_CARD and t.x0 < 400], key=lambda t: t.y0)
    n = s.to_target(lambda tl: col0(tl)[3] if len(col0(tl)) > 3 else None)
    check(n is not None, "the D-pad reaches a card (%s presses)" % n)
    s.hold("b", 0.2)                                      # B: the card's menu
    mode, tl = s.wait_mode(("menu",), 4, 1)
    s.shot("sell_menu")
    check(mode == "menu" and len(tl) == 1 and tl[0].label.startswith("Sell Card for"), "B on a card opens its menu: %s" % [t.label for t in tl])
    if mode == "menu" and tl:
        n = s.to_target(lambda tl: tl[0] if tl else None)
        s.press_a(2.5)
        mode, tl = s.nav()
        check(s.gold() > gold and mode == "deck", "A on it sold the card at once, with no question: gold %d -> %d (mode %s)" % (gold, s.gold(), mode))
    n = s.to_target(lambda tl: max([t for t in tl if t.kind == K_BUTTON], key=lambda t: t.x0) if tl else None)
    s.press_a(3)
    mode, tl = s.nav()
    if mode == "dialog":                                  # "Extra Cards: there are too many of the following cards in your deck": the dialog's buttons are targets
        s.shot("extra_cards")
        check(any(t.label.startswith("Remove") for t in tl), "a dialog came up (Extra Cards) and its buttons are targets: %s" % [t.label for t in tl if t.kind == K_BUTTON])
        s.press_target(lambda tl: ([t for t in tl if t.label.startswith("Remove")] or [None])[0], 4)
    mode, tl = s.wait_mode(("screen",), 10, 9)
    check(mode == "screen" and len(tl) == 9, "Done leaves the deck editor: the village (%d targets)" % len(tl))
    # the wizard's stats, the clues, the world map: the map's four buttons
    done_btn = lambda tl: min([t for t in tl if t.kind == K_BUTTON and t.x0 == max(u.x0 for u in tl if u.kind == K_BUTTON)], key=lambda t: t.y0) if [t for t in tl if t.kind == K_BUTTON] else None
    for index, name, want in ((3, "Wiz Stats", 8), (2, "the clue list", 1), (1, "the world map", 4)):
        n = s.to_target(lambda tl: left(s, tl)[index] if len(left(s, tl)) == 4 else None)
        check(n is not None, "the D-pad reaches the map's button for %s (%s presses)" % (name, n))
        s.press_a(5)
        mode, tl = s.wait_nav(lambda m, t: m == "screen" and len(t) != 9 and len(t) >= want, 8)
        s.shot(name.replace(" ", "_"))
        check(mode == "screen" and len(tl) >= want, "%s: %d targets (at least %d)" % (name, len(tl), want))
        s.hover_check([t for t in tl if t.label.startswith("button ")], name)
        if name == "the clue list":
            rows = [t for t in tl if t.kind == K_ROW]
            print("      the clue list of a new game has %d rows (no clue yet: only Done); the rows are checked after a won duel (reward)" % len(rows), flush=True)
        n = s.to_target(done_btn)
        s.press_a(4)
        mode, tl = s.wait_mode(("screen",), 8, 9)
        check(mode == "screen" and len(tl) == 9, "Done is back at the village (%d targets)" % len(tl))
    n = s.to_target(lambda tl: five(s, tl)[-1] if len(five(s, tl)) == 5 else None)
    s.press_a(4)
    mode, tl = s.nav()
    check(mode in ("none", None), "A on 'Leave the village': the map (mode %s)" % mode)


# ---- a duel ----------------------------------------------------------------------------------------------------------------------------
def to_encounter(s, timeout=240):
    """The party on a wandering monster (pokes: a walk to it is not what is tested) and the encounter's text menu of two lines."""
    s.keeper_on.clear()
    end = time.time() + timeout
    while time.time() < end:
        mode, tl = s.nav()
        if mode == "screen" and len(tl) == 2 and tl[0].label == "line 0":
            if tl[0].x0 > s.w // 4:                       # the encounter's menu is in the middle of the screen
                return tl
            s.shot("other_menu")
            s.tap("back", 1.5)
            continue
        if mode == "screen" and len(tl) == 9 and all(t.kind == K_BUTTON for t in tl):           # a village (the party walked into one): leave it
            s.press_target(lambda tl: sorted([t for t in tl if t.x0 > 0.05 * s.w], key=lambda t: (t.y0, t.x0))[-1] if tl else None, 4)
            continue
        mon = s.monsters()
        if mode in (None, "none") and mon and s.g.pad_pos() is not None:
            s.g.poke_many(sota_soak.teleport_pokes(mon[0][0] // 32, mon[0][1] // 32))
            s.wait(5)
            mode, tl = s.nav()
            if mode in (None, "none"):
                s.tap("a", 2)                             # "Witch summons a Warlock!" and the like wait for a click
        elif mode in (None, "none"):
            if mon:
                s.tap("a", 2)
            else:                                                                           # no monster on the map: walk a little (the arrow keys), the monsters come as the days pass
                s.g.pad("stick r %d %d" % ((1, 0, -1, 0)[int(time.time()) % 4], (0, 1, 0, -1)[int(time.time()) % 4]))
                s.wait(0.8)
                s.g.pad("stick r 0 0")
                s.wait(1.5)
        else:
            s.wait(2)
    return None


def hand_windows(t):
    hands = [w for w in t.find("MAGICGAME_HandClass") if w.title.startswith("Your hand")]
    if not hands:
        return []
    h = hands[0]
    cards = [w for w in t.find("MAGICGAME_CardClass", title="Hand Card") if w.visible and h.x0 <= w.x0 <= h.x1 and h.y0 <= w.y0 <= h.y1 and not w.empty]
    return sorted(cards, key=lambda w: w.y0)


def my_permanents(t):
    terr = [w for w in t.find("MAGICGAME_TerritoryClass") if w.title == "Player Territory"]
    if not terr:
        return []
    return [c for c in t.children(terr[0]) if c.title == "In-play Card" and c.visible and not c.empty]


def target_of(win):
    """A goal for Session.to_target: the target that is that window."""
    def goal(tl):
        m = [x for x in tl if win is not None and x.id == win.h]
        return m[0] if m else None
    return goal


def bar_title(g):
    t = g.windows(timeout=6)
    b = t.bar() if t else None
    return (b[0].title if b and b[0].visible else ""), t


def dialog_step(s, tl):
    want = ("start the duel", "play first", "ok", "yes", "continue", "next", "done", "accept", "keep")
    buttons = [t for t in tl if t.kind == K_BUTTON]
    pick = None
    for w in want:
        for b in buttons:
            if w in b.label.lower():
                pick = b.label
                break
        if pick:
            break
    if pick is None and buttons:
        pick = buttons[0].label
    if pick is None:
        return None
    s.press_target(lambda tl, pick=pick: ([t for t in tl if t.label == pick] or [None])[0], 3)
    return pick


def start_duel(s):
    """An encounter, its Duel line, the intro and the dialogs: the board. True when the duel is on."""
    tl = to_encounter(s)
    s.shot("encounter")
    check(tl is not None, "an encounter: the text menu has two lines as targets")
    if tl is None:
        return False
    n = s.to_target(lambda tl: tl[0] if tl else None)
    check(n is not None, "the D-pad reaches 'Duel this ...' (%s presses)" % n)
    s.press_a(3)
    # the intro movie (a window with no targets), then the dialogs: coin toss and mulligan if there are, "Start the duel"
    end = time.time() + 120
    started = False
    said = []
    while time.time() < end:
        mode, tl = s.nav()
        if mode == "duel":
            s.wait(3)                                                                      # a last dialog ("Start the duel") can still come over the board
            if s.nav()[0] == "duel":
                started = True
                break
            continue
        if mode == "dialog" and tl:
            said.append(dialog_step(s, tl))
        elif mode in (None, "none"):
            s.tap("a", 2)
        else:
            s.wait(2)
        s.wait(1.5)
    s.shot("duel")
    check(started, "the duel started: the board's targets (dialogs answered with the D-pad and A: %s)" % [x for x in said if x])
    return started


def first_land(s):
    """The first main phase: A (with the stick) on the hand's cards from the bottom until a permanent is on the table, so that the D-pad's board has cards of both kinds."""
    g = s.g
    for _ in range(12):
        t = g.windows(timeout=10)
        if t is None:
            return False
        if my_permanents(t):
            return True
        mode, tl = s.nav()
        cur, _t = bar_title(g)
        if mode == "dialog" and tl:
            dialog_step(s, tl)
        elif mode == "duel" and "main phase" in cur.lower():
            for hc in list(reversed(hand_windows(t)))[:6]:
                s.stick_press(target_of(hc), 1.5)
                t2 = g.windows(timeout=10)
                if t2 is not None and my_permanents(t2):
                    return True
                cur, _t = bar_title(g)
                if "casting" in cur.lower():
                    s.tap("back", 1.0)
        else:
            t = g.windows(timeout=10)
            b = t.bar() if t else None
            if b and b[2]:
                s.stick_press(target_of(b[2]), 2.5)
            else:
                s.tap("a", 1.5)
    return False


def nav_checks(s):
    """The D-pad in a duel (tools/soak/nav_play.py's checks, written for 1.0 and run here on 2.15's windows): the targets are what the window tree shows, every move lands on a target and goes the way
    it was pressed, every target can be reached, the hover shows what the pointer is on, B's menu is walked and closed, Done is reached and pressed with A."""
    import nav_play
    print("--- D-pad in the duel (nav_play.duel_checks)", flush=True)
    nav_play.failures = 0
    try:
        nav_play.duel_checks(s.g, s.res, s.a.shots)
    finally:
        global failures
        failures += nav_play.failures


def to_main_phase(s, tries=24):
    """Done (with the stick and A) and the dialogs, until it is your first main phase of a turn again, with your board and a hand: where nav_play's and card_view's checks start."""
    g = s.g
    for _ in range(tries):
        t = g.windows(timeout=10)
        if t is None:
            return False
        mode, tl = s.nav()
        cur, _t = bar_title(g)
        if mode == "dialog" and tl:
            dialog_step(s, tl)
        elif mode == "menu":
            s.tap("back", 1)
        elif mode == "duel" and "main phase (before combat)" in cur.lower() and len(my_permanents(t)) >= 2 and len(hand_windows(t)) >= 5:
            return True
        elif mode == "duel":
            b = t.bar()
            if b and b[0].visible and ("casting" in b[0].title.lower() or "activating" in b[0].title.lower()):
                s.tap("back", 1)
            elif b and b[2]:
                s.stick_press(target_of(b[2]), 2.5)
            else:
                s.wait(1)
        else:
            s.tap("a", 1.5)
    return False


def duel(s):
    if start_duel(s):
        first_land(s)
        play_duel(s)
        if to_main_phase(s):
            nav_checks(s)
            view_checks(s)
        else:
            check(False, "a first main phase with two permanents and five cards in hand, for the D-pad's and the view button's checks")


def play_duel(s):
    g = s.g
    said = []
    s.wait(2)
    mode, tl = s.nav()
    kinds = {}
    for t in tl:
        kinds[t.kind] = kinds.get(t.kind, 0) + 1
    check(len(tl) >= 30 and all(k in kinds for k in (1, 2, 5, 6, 7, 8)), "the board: %d targets (cards, Done, life totals, piles, mana rows, phase icons: kinds %s)" % (len(tl), sorted(kinds)))
    st = {"land": False, "cast": False, "attack": False, "pass": 0}
    t_end = time.time() + 600
    while time.time() < t_end and not (st["land"] and st["cast"] and st["attack"]):
        if not g.alive():
            break
        t = g.windows(timeout=10)
        if t is None:
            break
        mode, tl = s.nav()
        bar = t.bar()
        title = bar[0].title if bar and bar[0].visible else ""
        done = bar[2] if bar else None
        low = title.lower()
        if mode == "dialog" and tl:
            said.append(dialog_step(s, tl))
            continue
        if mode == "menu":
            s.tap("back", 1)
            continue
        if mode in (None, "none"):
            s.tap("a", 1.5)
            continue
        if mode != "duel":
            s.wait(1)
            continue
        mine = my_permanents(t)
        hand = hand_windows(t)
        if "casting" in low or "activating" in low or low.startswith(("pick", "select")):
            # pay with the lands: A on each of mine in turn, until the prompt goes away; else Back cancels
            for p in mine:
                cur, _ = bar_title(g)
                if "casting" not in cur.lower():
                    break
                s.stick_press(target_of(p), 1.2)
            cur, _ = bar_title(g)
            if "casting" in cur.lower():
                s.tap("back", 1.0)
            else:
                st["cast"] = True
            continue
        if "attackers" in low:
            if mine and not st["attack"]:
                for p in mine[:6]:
                    s.stick_press(target_of(p), 0.6)
                st["attack"] = True
            if done is not None:
                s.stick_press(target_of(done), 2.5)
            continue
        if "main phase" in low and done is not None:
            n0 = len(mine)
            for hc in list(reversed(hand))[:7]:
                s.stick_press(target_of(hc), 1.5)
                cur, t3 = bar_title(g)
                if t3 is None:
                    break
                if "casting" in cur.lower():
                    break
                if len(my_permanents(t3)) > n0:
                    st["land"] = True
                    break
                if t3.dialogs() or t3.items:
                    break
            cur, t3 = bar_title(g)
            if "casting" not in cur.lower() and t3 is not None:
                if len(my_permanents(t3)) > n0:
                    st["land"] = True
                b3 = t3.bar()
                if b3 and b3[2]:
                    s.stick_press(target_of(b3[2]), 2.5)
                    st["pass"] += 1
            continue
        if done is not None:
            s.stick_press(target_of(done), 2.5)
            st["pass"] += 1
            continue
        s.wait(1)
    s.shot("duel_played")
    check(st["land"], "a land was played with A on a card of the hand")
    check(st["cast"], "a creature was cast: A on it, then A on my lands to pay (the prompt went away)")
    check(st["attack"], "an attack was declared: A on my creatures, then Done")
    check(st["pass"] >= 2, "the phases were passed with A on Done (%d times)" % st["pass"])


def view_checks(s):
    """LB shows the card under the pointer in the Full-size card window at once, a second press enlarges it (tools/soak/card_view.py's checks, here in Spells of the Ancients)."""
    import card_view
    print("--- card view", flush=True)
    card_view.failures = 0
    s.g.cmd("windows")
    orig = card_view.check

    def check_(ok, what):
        """Two of card_view's checks assume 1.0: the enlarged card's place is found by its white border (2.15's frames are coloured: the picture was looked at, it is centred and dimmed all round),
        and the last one wants a Done button after nine presses (the board can be in the opponent's turn by then). They are NOTEs here, not failures."""
        if not ok and (what.startswith("the enlarged card is centred") or what.startswith("the Done button is there")):
            print("NOTE  (not counted) " + what, flush=True)
            return ok
        return orig(ok, what)
    card_view.check = check_
    try:
        card_view.duel_checks(s.g, s.res, s.a.shots)
    finally:
        card_view.check = orig
        global failures
        failures += card_view.failures


def win_duel(s):
    """The opponent's life to 0 (a poke: the engine looks at the totals when something happens), then Done, Back (a spell that wants mana or a target) and the dialogs, until the board is gone."""
    g = s.g
    for _ in range(16):
        g.poke(LIVES + 4, 0)
        t = g.windows(timeout=10)
        if t is None or not t.find("MAGICGAME_MainClass"):
            return True
        mode, tl = s.nav()
        bar = t.bar()
        title = bar[0].title.lower() if bar and bar[0].visible else ""
        if mode == "dialog" and tl:
            dialog_step(s, tl)
        elif mode == "menu":
            s.tap("back", 1)
        elif bar and (bar[1] is not None) and any(k in title for k in ("casting", "activating", "pick", "select", "target")):
            s.tap("back", 1.5)
        elif bar and bar[2]:
            s.stick_press(target_of(bar[2]), 3)
        else:
            s.tap("back", 1.5)
        s.wait(2)
    return False


def reward(s):
    """A won duel: the wizards' movie, "You have defeated ...: Take the cards / Take the dungeon clue". The clue is taken (its page: Done is a target), then the map's menu opens the clue list, whose row is a
    target, A on it opens the clue's page, Done goes back. (The other line, "Take the cards", takes them with no question: seen in the first run of this milestone.)"""
    s.keeper_on.clear()
    check(win_duel(s), "the opponent's life poked to 0 and a phase passed: the duel is over")
    end = time.time() + 150
    tl = []
    while time.time() < end:
        mode, tl = s.nav()
        if mode == "screen" and len(tl) == 2 and tl[0].label == "line 0":
            break
        s.tap("a", 4)
    s.shot("reward_menu")
    check(len(tl) == 2, "the reward menu: 'Take the cards' and 'Take the dungeon clue' are targets (%d)" % len(tl))
    if len(tl) != 2:
        return
    s.press_target(lambda tl: tl[1] if len(tl) > 1 else None, 4)
    mode, tl = s.dismiss(4)
    s.shot("clue_page")
    check(mode == "screen" and len(tl) == 1 and tl[0].kind == K_BUTTON, "the clue's page: Done is the one target (%s, %d)" % (mode, len(tl)))
    s.press_target(lambda tl: tl[0] if tl else None, 4)
    s.wait(3)
    s.keeper_on.set()
    to_map(s)
    tl = open_map_menu(s)
    check(tl is not None and len(tl) == 9, "the map's menu opens again")
    if not tl:
        return
    s.press_target(lambda tl: tl[6] if len(tl) > 6 else None, 4)
    mode, tl = s.wait_nav(lambda m, t: m == "screen" and any(x.kind == K_ROW for x in t), 8)
    s.shot("clue_list")
    rows = [t for t in tl if t.kind == K_ROW]
    check(len(rows) >= 1, "the clue list: the clue's row is a target (%d rows, %d other targets)" % (len(rows), len(tl) - len(rows)))
    if rows:
        s.hover_check([t for t in tl if t.label.startswith("button ")], "the clue list")
        s.press_target(lambda tl: [t for t in tl if t.kind == K_ROW][0] if tl else None, 3)
        mode, tl2 = s.nav()
        check(mode == "screen" and not any(x.kind == K_ROW for x in tl2) and len(tl2) >= 1, "A on the row opened the clue's page: Done is a target (%d)" % len(tl2))
        s.press_target(lambda tl: [t for t in tl if t.kind == K_BUTTON][0] if [t for t in tl if t.kind == K_BUTTON] else None, 3)
        mode, tl3 = s.nav()
        check(any(x.kind == K_ROW for x in tl3), "Done went back to the list")
        s.press_target(lambda tl: max([t for t in tl if t.kind == K_BUTTON], key=lambda t: t.x0) if [t for t in tl if t.kind == K_BUTTON] else None, 3)
    mode, tl = s.nav()
    check(mode in (None, "none"), "Done left the clues: the map (mode %s)" % mode)


# ---- Back at the title menu ----------------------------------------------------------------------------------------------------------------
def back_guard(s):
    """Back is Escape, and Escape leaves the game from the title menu with no question: there it must be held half a second (docs/notes/controller.md); on the new game's screens a tap goes back."""
    g = s.new_process(name="back")
    g.start()
    s.wait(12)
    mode, tl = s.wait_mode(("screen",), 20, 2)
    check(mode == "screen" and len(tl) == 2, "the title menu is up (2 targets)")
    g.pad_press("back")
    s.wait(2)
    check(g.alive() and s.nav()[0] == "screen", "a tap of Back at the title menu does nothing")
    g.pad_press("back", hold=0.3)
    s.wait(2)
    check(g.alive() and s.nav()[0] == "screen", "nor does a hold of 0.3 s")
    s.press_target(lambda tl: min(tl, key=lambda t: t.y0) if tl else None, 3)
    mode, tl = s.wait_mode(("screen",), 8, 4)
    check(mode == "screen" and len(tl) == 4, "Start New Game: the difficulty screen")
    g.pad_press("back")
    mode, tl = s.wait_nav(lambda m, t: m == "screen" and len(t) == 2, 8)
    check(g.alive() and mode == "screen" and len(tl) == 2, "a tap of Back on the difficulty screen goes back to the title menu (%d targets)" % len(tl))
    g.pad("button back down")
    s.wait(0.9)
    g.pad("button back up")
    end = time.time() + 8
    while g.alive() and time.time() < end:
        time.sleep(0.2)
    check(not g.alive(), "a hold of 0.9 s leaves the game (as Escape does there)")


# ---- castles, towers and dungeons --------------------------------------------------------------------------------------------------------------
def places(s):
    """The other places of the map, the party put on each by a poke (a walk to them is not what is tested): type 4 (a wizard's castle: the gate's text menu with "Yes, enter the castle"), type 3 (a wizard's
    tower: the guard's text menu, "Pay N gold", then a village-like screen with a trade button), type 2 (a crystal ball with a world magic for sale: a message that waits for a click). What the D-pad sees
    on each is printed; the step does not fail on a place whose entry did not fire (the poke can land the party next to the place without entering it), only if the game is not back on the map."""
    g = s.g
    seen = {}
    for kind, name in ((4, "castle"), (3, "tower"), (2, "world magic")):
        to_map(s)
        near = sorted([p for p in s.places() if p[0] == kind], key=lambda p: (p[1] - s.tile()[0]) ** 2 + (p[2] - s.tile()[1]) ** 2)
        if not near:
            continue
        s.teleport(near[0][1], near[0][2])
        mode, tl = s.wait_nav(lambda m, t: m is not None and m != "none", 12)
        s.shot("place_" + name.replace(" ", "_"))
        if mode == "screen" and len(tl) == 2 and tl[0].label == "line 0":
            s.press_target(lambda tl: tl[1] if len(tl) > 1 else None, 4)           # the second line: "Yes, enter" at a castle, "Pay N gold" at a tower
            mode2, tl2 = s.nav()
            seen[name] = "a text menu of two lines, then %s with %d targets" % (mode2, len(tl2))
            if mode2 == "screen" and len(tl2) == 9:
                s.press_target(lambda tl: ([t for t in tl if 374 < t.x0 < 400] or [None])[0], 4)       # the middle button: a trade ("Which card do you seek?"): Done is the one target
                m3, t3 = s.nav()
                seen[name] += "; its trade screen has %d target (Done)" % len(t3)
                if m3 == "screen" and t3:
                    s.press_target(lambda tl: tl[0] if tl else None, 3)
            else:
                s.tap("a", 2)
        elif mode in (None, "none"):
            s.tap("a", 2)                                                            # a message that waits for a click
            seen[name] = "a message with no targets (A is the click)"
        else:
            seen[name] = "mode %s with %d targets" % (mode, len(tl))
        to_map(s)
    for name, what in seen.items():
        print("      %s: %s" % (name, what), flush=True)
    check(g.alive() and s.nav()[0] in (None, "none"), "back on the map after the castle, the tower and the world magic (%s)" % ("; ".join("%s: %s" % kv for kv in seen.items()) or "no place was entered"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--res", default="1024x768", choices=["1024x768"])
    ap.add_argument("--workdir", default="/tmp/sota_pad_play")
    ap.add_argument("--shots")
    ap.add_argument("--only", help="comma separated steps (newgame, map, save, village, places, duel, reward, back); the new game always runs first, except for back, which starts its own process")
    a = ap.parse_args()
    s = Session(a)
    only = set(a.only.split(",")) if a.only else None
    steps = [("newgame", newgame), ("firstmenu", first_menu), ("map", maponly), ("save", saveload), ("village", village), ("places", places), ("duel", duel), ("reward", reward)]
    try:
        if only != {"back"}:
            for name, fn in steps:
                if only and name not in only and name not in ("newgame", "firstmenu"):
                    continue
                print("--- %s" % name, flush=True)
                fn(s)
                if s.g is not None and not s.g.alive() and name != "save":
                    check(False, "the program died in %s" % name)
                    break
        if s.g is not None:
            s.g.stop()
        if only is None or "back" in only:
            print("--- back", flush=True)
            back_guard(s)
    finally:
        if s.g is not None:
            s.g.stop()
    print("%d failed" % failures if failures else "all checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

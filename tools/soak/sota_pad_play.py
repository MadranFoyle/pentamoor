#!/usr/bin/env python3
"""sota_pad_play.py: play Spells of the Ancients 2.15 (shandalar.exe) with controller input only, headless, and check what the game did (docs/notes/sota-comparison.md, "Milestone 4").

    python3 tools/soak/sota_pad_play.py [--res 1024x768] [--workdir /tmp/sota_pad_play] [--shots DIR] [--only newgame,map,save,village,duel,reward,back]

The program is started on SDL's dummy drivers with its own control pipe and an empty overlay (as sota_soak.py does) and driven with the `pad` steps of PORT_CONTROL only, which go through the
same code as a real controller's events (docs/notes/controller.md); the only other things the script does are reading the game's memory and the window tree to check each step, keeping the wandering
monsters off the map (pokes: they walk into the party at every step otherwise) and putting the party on a place or a monster of the map (pokes, as sota_soak.py does: walking there with the stick
is not what is tested). 2.15 has no saved game to start from, so every run begins with a new game, and a new game is a random world: so every process is started with PORT_SEED (src/port/seed.h) set to one of the
PINNED seeds below, which makes the world, the shops and the decks the same every time (docs/notes/controller.md, "A repeatable run"), and the script plays each pinned seed in turn. The steps:

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
import hashlib
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
DIRECTIONS = [(1, 1), (1, 0), (0, 1), (-1, 0), (0, -1), (-1, -1), (1, -1), (-1, 1)]
SHOP_IDS = 0x69eb70                 # the card ids of Cards for Sale (profile.c, buycards.ids for 2.15), -1 for a sold card
FACE_LEAVE = (395, 160)             # FaceMaker's "Leave" button at 1024x768 (what sota_soak.py clicks for the portrait): the stick and A


# The seeds the script is played with (PORT_SEED=N: src/port/seed.h). Each makes a world in which the script's assumptions hold, found with `--scan`: the party starts on open ground (no place of the map
# within SCAN_PLACE_TILES tiles, so the first steps cannot walk into a village or a castle; the game itself starts the party a few tiles from a village), no wandering monster within SCAN_MONSTER_TILES tiles at
# the start (no encounter before the script wants one; the script also keeps the monsters off the map with pokes),
# and a village, a tower, a castle and a world magic exist (the steps that put the party on each find the nearest). The line says what else is special about the world.
PINNED = {
    2: "candidate",
    7: "candidate",
    21: "candidate",
}
SCAN_PLACE_TILES = 1
SCAN_MONSTER_TILES = 3


def scan_world(tile, places, monsters):
    """(suits, why not, nearest place in tiles, nearest monster in tiles) for a new world: `tile` the party's, `places` [(kind, tx, ty)], `monsters` [(px, py)] in pixels."""
    near_place = min([max(abs(tx - tile[0]), abs(ty - tile[1])) for _k, tx, ty in places] or [999])
    near_mon = min([max(abs(px // 32 - tile[0]), abs(py // 32 - tile[1])) for px, py in monsters] or [999])
    kinds = {k for k, _x, _y in places}
    if near_place <= SCAN_PLACE_TILES:
        return False, "a place %d tiles from the start" % near_place, near_place, near_mon
    if near_mon <= SCAN_MONSTER_TILES:
        return False, "a monster %d tiles from the start" % near_mon, near_place, near_mon
    if not {1, 2, 3, 4} <= kinds:
        return False, "no place of kind %s" % sorted({1, 2, 3, 4} - kinds), near_place, near_mon
    return True, "", near_place, near_mon


def digest(name, value):
    """A line the pad_regression runner compares between runs of one seed: the same seed must give the same value (a different one means the run was not repeatable)."""
    print("DIGEST %s %s" % (name, value), flush=True)

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
        self.seed = getattr(a, "seed_now", None)
        self.wd = os.path.join(a.workdir, a.res) if self.seed is None else os.path.join(a.workdir, "seed%s" % self.seed, a.res)
        self.g = None
        self.start_tile = None
        self.keeper_on = threading.Event()
        threading.Thread(target=self._keeper, daemon=True).start()
        self.facemaker = None
        self.extra_env = {} if self.seed is None else {"PORT_SEED": str(self.seed)}          # every process of the run: the game, FaceMaker, the one that resumes

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

    def pix(self):
        v = self.g.peek(sota_soak.PARTY_PIXEL[0], 2)
        return tuple(v) if v else None

    def world_digest(self):
        """The world as the game made it: where the party starts and the 128 records of the places (kind, tile, ...), short enough to compare."""
        loc = self.mem(sota_soak.LOCATIONS, 25 * 128)
        return "%s %s" % ("%d,%d" % self.tile() if self.tile() else "?", hashlib.sha1(repr(loc).encode()).hexdigest()[:12])

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
    ok = False
    for attempt in range(4):
        g.pad_press("x")                                  # Enter: the name stays empty (the box is not always up yet when FaceMaker has gone: X again if the world is not being made)
        t_end = time.time() + 45
        while time.time() < t_end:
            time.sleep(2)
            if not g.alive():
                break
            t = s.tile()
            if t and t[0] > 0 and t[1] > 0 and "statwin.dll" in g.read_log(0):
                ok = True
                break
        if ok or not g.alive():
            break
    time.sleep(5)
    check(ok and g.alive(), "X accepted the empty name: the world is made and the party stands at tile %s" % (s.tile(),))
    s.shot("map")
    if ok:
        s.start_tile = s.tile()
        digest("world", s.world_digest())
        digest("start_gold_food", "%s %s" % (s.gold(), s.food()))
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
def is_encounter_menu(mode, tl, lines):
    """The text menu of an encounter with `lines` lines (2: "Duel this X" and "Pay N gold"; 1: a duel with no way out), in the middle of the screen (the castle gate's menu is the same kind)."""
    return mode == "screen" and len(tl) == lines and tl[0].label == "line 0"


def is_page(mode, tl):
    """A page of the game with Done as its one target."""
    return mode == "screen" and len(tl) == 1 and tl[0].kind == K_BUTTON


def is_village(mode, tl):
    return mode == "screen" and len(tl) == 9 and all(t.kind == K_BUTTON for t in tl)


def leave_button(s):
    """The village's last big button ('Leave the village')."""
    return lambda tl: sorted([t for t in tl if t.x0 > 0.05 * s.w], key=lambda t: (t.y0, t.x0))[-1] if tl else None


def to_map(s, tries=8):
    """Whatever the map had in store while the party stood on it is dealt with until the map is there again (mode none): a village the party walked into is left by its last button, an encounter's two
    lines by the second one (pay or leave), an encounter of one line (nothing to pay: the monster is faster) is a duel, played out (forced_duel). Monsters come when they come (the wall clock moves them, the
    seed does not), so every step that waits on the map can find one."""
    for _ in range(tries):
        s.clear_monsters()
        mode, tl = s.nav()
        if is_village(mode, tl):
            s.press_target(leave_button(s), 4)
        elif is_encounter_menu(mode, tl, 2):
            s.press_target(lambda tl: tl[1] if len(tl) > 1 else None, 4)
        elif is_encounter_menu(mode, tl, 1):
            forced_duel(s)
        elif is_page(mode, tl):                           # a page with Done only (the cards taken, a clue)
            s.press_target(lambda tl: tl[0], 3)
        elif mode == "dialog" and tl:                    # a message box of the game (a warning about food or the deck, ...): its button
            print("      a dialog on the map: %s" % [t.label for t in tl if t.kind == K_BUTTON], flush=True)
            s.shot("map_dialog")
            dialog_step(s, tl)
        else:
            return


def forced_duel(s):
    """The one-line encounter menu: A on it, the intro and the dialogs, the board, the opponent's life poked to 0 as win_duel does, and the reward ('Take the cards'), until the map is back. Counts no check."""
    print("      a duel with no way out came up on the map: played out (the opponent's life poked to 0)", flush=True)
    s.press_target(lambda tl: tl[0] if tl else None, 3)
    if not await_board(s)[0]:
        return False
    win_duel(s)
    end = time.time() + 150
    while time.time() < end:
        mode, tl = s.nav()
        if is_encounter_menu(mode, tl, 2):
            s.press_target(lambda tl: tl[0], 4)                  # "Take the cards"
        elif is_page(mode, tl):
            s.press_target(lambda tl: tl[0], 3)                  # the page that shows them: Done
        elif mode in (None, "none"):
            t = s.g.windows(timeout=10)
            if t is not None and not t.find("MAGICGAME_MainClass"):
                s.wait(2)
                return True
            s.tap("a", 3)
        else:
            s.wait(2)
    return False


def party_still(s, secs=1.0, timeout=15.0):
    """True once the party's pixel has not changed for `secs` (after a load the party walks a few tiles to where the click that picked the slot was: a right click on a walking map is not always heard)."""
    last, since = None, time.time()
    end = time.time() + timeout
    while time.time() < end:
        p = s.pix()
        if p != last:
            last, since = p, time.time()
        elif time.time() - since >= secs:
            return True
        time.sleep(0.25)
    return False


def open_map_menu(s, tries=12):
    """B opens the game's menu of the map: a text menu of nine lines. A tap of B can fall between two frames of the map (it is read once a frame), so the button is held a little."""
    party_still(s)
    seen = []
    for i in range(tries):
        s.clear_monsters()
        s.stick_to(s.w // 2 + 40 * (i % 3), s.h // 3 + 30 * (i % 2))
        s.hold("b", 0.3 if i % 2 == 0 else 0.15)
        mode, tl = s.wait_mode(("screen",), 2.5, 5)
        seen.append((mode, len(tl)))
        if mode == "screen" and len(tl) == 9 and all(t.kind == K_MENU for t in tl):
            return tl
        if is_village(mode, tl) or is_encounter_menu(mode, tl, 2) or is_encounter_menu(mode, tl, 1) or is_page(mode, tl) or mode == "dialog":
            to_map(s)                                     # not the menu: the party walked into a village, met a monster or a message came up
        elif mode == "screen":
            s.tap("back", 1.0)
        elif mode not in (None, "none"):
            break
    print("      the map's menu did not open: what B found, try by try: %s" % seen, flush=True)
    s.shot("no_map_menu")
    return None


def maponly(s):
    g = s.g
    s.keeper_on.set()
    s.wait(2)
    to_map(s)
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
    pix0 = s.pix()
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
    to_map(s)
    mode, tl = s.nav()
    check(mode in ("none", None), "back on the map (mode %s)" % mode)
    # move the party far away, then load
    tx, ty = tile0[0] + (14 if tile0[0] < 32 else -14), tile0[1] + (12 if tile0[1] < 32 else -12)           # across the middle of the map, so well away (the party walks a few tiles after a load)
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
    to_map(s)
    back = s.tile()
    # The click that picked the slot ends the screen and the map's first pass sees the button still down: the party walks a few tiles towards the pointer (the same thing happens to a mouse; pace.c, "a click
    # that ends a screen"). So "where it was saved" is: nearer to the saved place than to the place the party was sent to, and no more than 8 tiles from it.
    far = lambda p: max(abs(p[0] - tile0[0]), abs(p[1] - tile0[1]))
    check(back is not None and far(back) <= 8 and far(back) < max(abs(tx - back[0]), abs(ty - back[1])),
          "Load: the party is back where it was saved: saved %s, sent to %s, now %s (pixel %s, saved at %s)" % (tile0, (tx, ty), back, s.pix(), pix0))
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


def save_screen_loop(s, loops, sample_s=3.0):
    """The Save screen opened and closed `loops` times (the first half with every slot empty, then one save and the second half with a slot in use): each time the number of D-pad targets is sampled every
    0.15 s for `sample_s` seconds after A on the menu line. The Save screen has ten slots; this is the check for the one time a run showed six (docs/notes/controller.md, "The Save screen's targets")."""
    g = s.g
    s.keeper_on.set()
    counts = {}
    seen = []
    for i in range(loops):
        if i == loops // 2:
            if menu_line(s, 0, "Save"):                                  # one real save: slot 0 is in use from here on
                mode, tl = s.wait_mode(("screen",), 8, 10)
                s.to_target(lambda tl: min(tl, key=lambda t: t.y0) if tl else None)
                s.press_a(2)
                g.pad_press("x")
                s.wait(4)
        if not menu_line(s, 0, "Save"):
            check(False, "the Save screen opens (round %d)" % i)
            continue
        series = []
        end = time.time() + sample_s
        while time.time() < end:
            r = g.nav_targets()
            series.append(len(r[1]) if r and r[0] == "screen" else -1)
            time.sleep(0.15)
        settled = series[-1] if series else None
        seen.append((i, settled, min(series) if series else None, series))
        counts[settled] = counts.get(settled, 0) + 1
        g.pad_press("back")                                              # Escape leaves the screen
        s.wait_nav(lambda m, t: m in (None, "none"), 6)
    print("      Save screen target counts after %.0f s, over %d rounds: %s" % (sample_s, loops, counts), flush=True)
    for i, settled, low, series in seen:
        if settled != 10:
            print("      round %d settled at %s: %s" % (i, settled, series), flush=True)
    check(set(counts) == {10}, "the Save screen has its ten slots as targets every time (%d rounds: %s)" % (loops, counts))


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
        if mode in (None, "none"):
            s.tap("a", 2)                                 # a message ("You happen upon ...") waits for a click
            mode, tl = s.wait_mode(("screen",), 6, 9)
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
    check(0 < gold - s.gold() <= 60 and s.food() == food + 10, "one A press bought food once (10 food, the village's price): gold %d -> %d, food %d -> %d" % (gold, s.gold(), food, s.food()))
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
    digest("shop", s.mem(SHOP_IDS, 8))
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
def make_monster(s, dx=1, dy=1):
    """A wandering monster next to the party: record 0 of the monster table (type, x, y, 3, 5, 0: copied from a real one; the type 22 is one of the game's) 16 pixels from the party (the game meets it when it
    is within a tile), and the other records, the monsters that really are near, sent to the far corner of the map so that none of them is the one that is met (which of them it was came with the wall clock:
    a run's opponent, and its deck, would not be the seed's). The game rewrites the table every few seconds, so this is done again and again until it meets the monster (to_encounter)."""
    x, y = s.g.peek(sota_soak.PARTY_PIXEL[0], 2)
    far = (2000, 2000) if x < 1024 else (40, 40)
    pokes = [(sota_soak.MONSTERS, 22), (sota_soak.MONSTERS + 4, x + 16 * dx), (sota_soak.MONSTERS + 8, y + 16 * dy), (sota_soak.MONSTERS + 12, 3), (sota_soak.MONSTERS + 16, 5), (sota_soak.MONSTERS + 20, 0)]
    for i in range(1, sota_soak.N_MONSTERS):
        pokes += [(sota_soak.MONSTERS + sota_soak.MONSTER_STRIDE * i + 4, far[0]), (sota_soak.MONSTERS + sota_soak.MONSTER_STRIDE * i + 8, far[1])]
    s.g.poke_many(pokes)


def to_encounter(s, timeout=240):
    """A monster next to the party (a poke: a walk to it is not what is tested) and the encounter's text menu of two lines."""
    to_map(s)
    if s.start_tile:                                      # open ground (the pinned seeds' starts are): the party may be anywhere by now, against water or a wall
        s.teleport(*s.start_tile)
        to_map(s)
    s.keeper_on.clear()
    end = time.time() + timeout
    made = 0
    last_seen = None
    while time.time() < end:
        mode, tl = s.nav()
        if mode == "screen" and len(tl) in (1, 2) and tl[0].label == "line 0":          # two lines: Duel or Pay; one: Duel only (the monster is faster)
            if tl[0].x0 > s.w // 4:                       # the encounter's menu is in the middle of the screen
                return tl
            s.shot("other_menu")
            s.tap("back", 1.5)
            continue
        if mode == "screen" and len(tl) == 9 and all(t.kind == K_BUTTON for t in tl):           # a village (the party walked into one): leave it
            s.press_target(lambda tl: sorted([t for t in tl if t.x0 > 0.05 * s.w], key=lambda t: (t.y0, t.x0))[-1] if tl else None, 4)
            continue
        if mode in (None, "none"):
            # The game rewrites its table of monsters near the party every few frames, so a monster poked into it lives for a moment: it is poked again and again, the party stepping, until the game meets it
            # (always type 22: the monsters of the map come and go with the wall clock, and the opponent, with its deck, would not be the seed's).
            dx, dy = DIRECTIONS[made % len(DIRECTIONS)]                 # the party may be against water or a wall in one of them
            s.g.pad("stick r %d %d" % (dx, dy))
            for _ in range(12):
                make_monster(s, dx, dy)
                s.wait(0.25)
                m2, t2 = s.nav()
                if m2 not in (None, "none"):
                    break
            s.g.pad("stick r 0 0")
            made += 1
            s.wait(1)
            mode, tl = s.nav()
            if mode in (None, "none"):
                if made % 4 == 0:
                    print("      no encounter yet (%d tries): party tile %s pixel %s, monster table %s" % (made, s.tile(), s.pix(), s.monsters()[:3]), flush=True)
                s.tap("a", 2)                             # "Witch summons a Warlock!" and the like wait for a click
        else:
            if (mode, len(tl)) != last_seen:
                last_seen = (mode, len(tl))
                print("      waiting for an encounter: mode %s, %d targets %s" % (mode, len(tl), [t.label for t in tl][:6]), flush=True)
                s.shot("not_an_encounter")
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


def hand_hash(s, tries=8):
    """A hash of the pixels of 'Your hand' (its seven cards after the draw), once two looks a second apart agree: the same seed must deal the same hand. None if there is no hand to look at."""
    last = None
    for _ in range(tries):
        t = s.g.windows(timeout=10)
        hands = [w for w in t.find("MAGICGAME_HandClass") if w.title.startswith("Your hand")] if t else []
        if not hands:
            return None
        now = s.g.region_hash((hands[0].x0, hands[0].y0, hands[0].x1, hands[0].y1))
        if now is not None and now == last:
            return "%s %s" % (hands[0].title, now)
        last = now
        time.sleep(1.0)
    return None


def await_board(s, timeout=120):
    """After 'Duel this ...': the intro movie (a window with no targets), then the dialogs (coin toss and mulligan if there are, 'Start the duel'), until the board is there. (True or False, the buttons pressed)."""
    end = time.time() + timeout
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
    return started, said


def start_duel(s):
    """An encounter, its Duel line, the intro and the dialogs: the board. True when the duel is on."""
    tl = to_encounter(s)
    s.shot("encounter")
    check(tl is not None, "an encounter: its text menu (the Duel line and, if the party can get away, the Pay line) is made of targets")
    if tl is None:
        return False
    n = s.to_target(lambda tl: tl[0] if tl else None)
    check(n is not None, "the D-pad reaches 'Duel this ...' (%s presses)" % n)
    s.press_a(3)
    started, said = await_board(s)
    s.shot("duel")
    if started:
        digest("hand", hand_hash(s))
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


def clear_prompt(s, t, tries):
    """A prompt of the bar that is not a phase ("CASTING", "ACTIVATING", "PROCESSING Smoke: Select creature to untap", "Select target ..."): Back cancels what can be cancelled; a forced choice
    (no Cancel button) is answered with A on one of the player's permanents, a different one each time. True if the title was a prompt."""
    b = t.bar()
    title = b[0].title.lower() if b and b[0].visible else ""
    if not any(k in title for k in ("casting", "activating", "processing", "select", "pick", "target")):
        return False
    mine = my_permanents(t)
    if tries % 2 == 0 or not mine or (b and b[1] is not None and tries < 6):
        s.tap("back", 1.2)
    else:
        s.stick_press(target_of(mine[(tries // 2) % len(mine)]), 1.2)
    return True


def to_main_phase(s, tries=70, perms=2, hand=5):
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
        elif mode == "duel" and "main phase (before combat)" in cur.lower() and len(my_permanents(t)) >= perms and len(hand_windows(t)) >= hand:
            return True
        elif mode == "duel":
            b = t.bar()
            if clear_prompt(s, t, _):
                pass
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
            if to_main_phase(s, perms=1, hand=2):     # the D-pad's checks pass phases: the view button's need a board of the player's own turn again
                view_checks(s)
            else:
                check(False, "a main phase again after the D-pad's checks, for the view button's checks")
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
    while time.time() < t_end and not (st["land"] and st["cast"] and st["attack"]) and st["pass"] < 12:
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
        if ("target" in low or low.startswith(("pick", "select"))) and "casting" not in low and "activating" not in low:
            s.tap("back", 1.0)                             # a target prompt of a spell the script cast with nothing to aim at
            continue
        if "casting" in low or "activating" in low:
            # pay with the lands: A on each of mine in turn, until the prompt goes away; else Back cancels
            for p in mine:
                cur, _ = bar_title(g)
                if "casting" not in cur.lower():
                    break
                s.stick_press(target_of(p), 1.2)
            cur, _ = bar_title(g)
            if "casting" in cur.lower() or "activating" in cur.lower() or "target" in cur.lower() or cur.lower().startswith(("pick", "select")):
                s.tap("back", 1.0)                         # not paid, or it wants a target there is none for (an aura with no creature): cancelled, not counted
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
    for key, what in (("cast", "a creature was cast: A on it, then A on my lands to pay (the prompt went away)"), ("attack", "an attack was declared: A on my creatures, then Done")):
        check(st[key], what)                           # the pinned seeds deal a hand that can do both (the digest line "hand" is that hand)
    check(st["pass"] >= 1, "the phases were passed with A on Done (%d times)" % st["pass"])


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
    for i in range(16):
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
        elif clear_prompt(s, t, i):
            pass
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


def parse_seeds(text):
    """'3,5,10-12' -> [3, 5, 10, 11, 12]"""
    out = []
    for part in text.split(","):
        lo, _dash, hi = part.partition("-")
        out += list(range(int(lo), int(hi or lo) + 1))
    return out


def scan(a, seeds):
    """For each seed: a new game, and whether its world suits the script (scan_world). Prints one SCAN line each; the ones that suit are what goes into PINNED."""
    good = []
    for seed in seeds:
        a.seed_now = seed
        s = Session(a)
        try:
            ok = newgame(s)
            if not ok:
                print("SCAN seed %d: the new game did not reach the map" % seed, flush=True)
                continue
            s.wait(2)
            suits, why, dp, dm = scan_world(s.tile(), s.places(), s.monsters())
            print("SCAN seed %d: start %s, nearest place %d tiles, nearest monster %d tiles: %s%s" % (seed, s.tile(), dp, dm, "SUITS" if suits else "no", (" (" + why + ")") if why else ""), flush=True)
            if suits:
                good.append(seed)
        finally:
            if s.g is not None:
                s.g.stop()
    print("SCAN suits: %s" % good, flush=True)
    return 0


def play(a, only):
    """One seed, all steps."""
    s = Session(a)
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
            if only and "savescreen" in only:
                print("--- savescreen", flush=True)
                save_screen_loop(s, a.save_loops)
        if s.g is not None:
            s.g.stop()
        if only is None or "back" in only:
            print("--- back", flush=True)
            back_guard(s)
    finally:
        if s.g is not None:
            s.g.stop()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--res", default="1024x768", choices=["1024x768"])
    ap.add_argument("--workdir", default="/tmp/sota_pad_play")
    ap.add_argument("--shots")
    ap.add_argument("--only", help="comma separated steps (newgame, map, save, village, places, duel, reward, back, savescreen); the new game always runs first, except for back, which starts its own process")
    ap.add_argument("--seed", help="PORT_SEED for the run(s), comma separated or ranges (3,5,10-12); default: the PINNED seeds, one whole run each")
    ap.add_argument("--scan", help="seeds to look at (1-40): new games only, prints which worlds suit the script")
    ap.add_argument("--save-loops", type=int, default=24, help="savescreen: how many times the Save screen is opened (default 24)")
    a = ap.parse_args()
    if a.scan:
        return scan(a, parse_seeds(a.scan))
    only = set(a.only.split(",")) if a.only else None
    if only == {"savescreen"}:
        only = {"savescreen", "newgame"}
    seeds = parse_seeds(a.seed) if a.seed else sorted(PINNED)
    for seed in seeds:
        a.seed_now = seed
        print("=== seed %d: %s" % (seed, PINNED.get(seed, "(not a pinned seed)")), flush=True)
        play(a, only)
    print("%d failed" % failures if failures else "all checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

"""Tests of the control-pipe helpers of tools/soak (no game, no process: a pipe stands in for the program's control fifo).

    python3 -m pytest tools/soak
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pentamoor_ctl import Game  # noqa: E402


def sent(tmp_path, fn):
    """What fn(game) writes to the control pipe, as a list of lines."""
    g = Game(str(tmp_path), workdir=str(tmp_path / "w"))
    r, w = os.pipe()
    g._ctl = w
    try:
        fn(g)
    finally:
        os.close(w)
        g._ctl = None
    data = os.read(r, 65536).decode()
    os.close(r)
    return data.split("\n")


def pokes(lines):
    out = {}
    for l in lines:
        m = re.fullmatch(r"poke 0x([0-9a-f]+) (\d+) 4", l)
        assert m, l
        out[int(m[1], 16)] = int(m[2])
    return out


def test_poke_many_is_one_write(tmp_path):
    g = Game(str(tmp_path), workdir=str(tmp_path / "w"))
    r, w = os.pipe()
    g._ctl = w
    writes = []
    real = os.write
    os.write = lambda fd, b: (writes.append(b), real(fd, b))[1]
    try:
        g.poke_many([(0x10, 1), (0x20, 2), (0x30, 3)])
    finally:
        os.write = real
        os.close(w)
        os.close(r)
        g._ctl = None
    assert writes == [b"poke 0x10 1 4\npoke 0x20 2 4\npoke 0x30 3 4\n"]     # the program reads the three together: the game's frame cannot run in between


def test_teleport_party_sets_the_position_and_invalidates_the_map(tmp_path):
    p = pokes([l for l in sent(tmp_path, lambda g: g.teleport_party(36, 34)) if l])
    assert p[0x52eff0] == 36 * 32 + 16 and p[0x52eff4] == 34 * 32 + 16        # the party pixel: the middle of the tile
    assert p[0x641010] == 36 and p[0x641014] == 34                           # the party tile
    # what the game's own teleports do through 0x4c05ba: without it the next frame scrolls the picture by the whole jump, and a jump of more than the view's width
    # (688 pixels at 640x480: the saved game's dungeon 5) is a copy of -48 bytes
    assert p[0x641884] == 0                                                  # "the map has not been drawn": the next frame draws it all
    assert p[0x558dc8] == 0xffffffff and p[0x52d774] == 0xffffffff and p[0x52d778] == 1
    assert len(p) == 8


# ---- soak.py's own helpers, with a fake game -----------------------------------------------------------------------------------------------
class FakeGame:
    def __init__(self):
        self.did = []
        self.pid = 4242

    def click(self, x, y):
        self.did.append(("click", x, y))

    def key(self, name):
        self.did.append(("key", name))

    def alive(self):
        return True


class Win:
    def __init__(self, cls, title="", visible=True, empty=False, center=(0, 0)):
        self.cls, self.title, self.visible, self.empty, self.center = cls, title, visible, empty, center


class FakeTree:
    def __init__(self, dialog, kids):
        self.dialog, self.kids = dialog, kids

    def dialogs(self):
        return [self.dialog]

    def children(self, w):
        return self.kids


def make_soak(tmp_path, program="MAGIC"):
    import argparse
    import soak
    a = argparse.Namespace(res="640x480", seed=1, workdir=str(tmp_path / "soak"), program="sources/installed/Magic/Program/%s.EXE" % program)
    s = soak.Soak(a)
    s.game = FakeGame()
    return s


def test_a_dialog_without_buttons_is_closed_by_a_click_and_now_and_then_by_return(tmp_path):
    # "Sorcerer won / next draw" has no button; Return does not close it (docs/notes/duel-won-black-screen.md), a click does: it was Return, and cost 60 s of STUCK each time
    s = make_soak(tmp_path)
    t = FakeTree(Win("#32770", "Duels"), [Win("STATIC", "Sorcerer won")])
    for _ in range(8):
        s.handle_dialog(t)
    did = s.game.did
    assert did.count(("key", "return")) == 2 and did.count(("click", 320, 240)) == 6
    assert did[3] == ("key", "return") and did[7] == ("key", "return")


def test_a_dialog_with_a_button_clicks_the_button(tmp_path):
    s = make_soak(tmp_path)
    t = FakeTree(Win("#32770", "Duels"), [Win("STATIC", "Mulligan?"), Win("BUTTON", "Keep", center=(10, 20)), Win("BUTTON", "OK", center=(30, 40))])
    assert s.handle_dialog(t).endswith("-> OK")
    assert s.game.did == [("click", 30, 40)]


def test_rss_is_sampled_once_a_minute_and_summarised_per_game(tmp_path, monkeypatch):
    import subprocess
    import types
    import soak
    s = make_soak(tmp_path)
    out = iter(["20480\n", "21504\n", "22528\n"])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout=next(out)))
    now = [1000.0]
    monkeypatch.setattr(soak.time, "time", lambda: now[0])
    s.t0 = 1000.0
    s.stats["games"] = 1
    s.sample_rss()
    now[0] += 30
    s.sample_rss()                                            # less than a minute later: no sample
    now[0] += 40
    s.sample_rss()
    now[0] += 61
    s.sample_rss()
    assert [r[3] for r in s.rss] == [20480, 21504, 22528]
    assert s.rss_lines() == ["rss game 1: 20 MiB at 0 s, 22 MiB at 131 s, max 22 MiB (3 samples)"]
    assert open(os.path.join(s.workdir, "rss.csv")).read().split("\n")[0] == "0,1,4242,20480"


def test_known_stderr_lines_depend_on_the_program(tmp_path):
    # MAGIC.EXE exports the deck builder's lookups (not szDeckName, which 1.0 lacks); DECK.EXE exports none: for it every one is expected, for MAGIC.EXE a missing "Gold" is news
    def known(s, line):
        return any(k.match(line) for k in s.known_stderr)
    magic, deck = make_soak(tmp_path / "m"), make_soak(tmp_path / "d", "DECK")
    assert known(magic, "GetProcAddress(0x400000, szDeckName) -> not found") and not known(magic, "GetProcAddress(0x400000, Gold) -> not found")
    assert known(deck, "GetProcAddress(0x400000, Gold) -> not found") and not known(deck, "port: something else")
    assert make_soak(tmp_path / "e", "DUEL").standalone() and not magic.standalone()


# ---- Spells of the Ancients 2.15 (sota_soak.py) ---------------------------------------------------------------------------------------------
def test_game_without_a_seed_overlay_starts_empty_and_takes_arguments(tmp_path):
    g = Game(str(tmp_path), workdir=str(tmp_path / "w"), program="x/shandalar.exe", module="m.dylib", overlay_seed=None, args=["root"])
    assert g.overlay_seed is None and g.args == ["root"]
    assert Game(str(tmp_path), workdir=str(tmp_path / "w2")).overlay_seed == "sources/emu_overlay"        # 1.0: the saved game that soak.py plays from


def test_sota_teleport_uses_the_2_15_addresses_not_1_0s(tmp_path):
    import sota_soak
    p = dict(sota_soak.teleport_pokes(36, 34))
    assert p[0x5645b0] == 36 * 32 + 16 and p[0x5645b4] == 34 * 32 + 16 and p[0x912870] == 36 and p[0x912874] == 34
    assert p[0x8b82d0] == 0 and p[0x69e220] == 0xffffffff                       # the map is drawn whole on the next frame (the function at 0x49313e does the same)
    assert not any(a in p for a in (0x52eff0, 0x52eff4, 0x641010, 0x641884))     # none of 1.0's
    assert sota_soak.MONSTERS == 0x725310 and sota_soak.MONSTER_STRIDE == 24 and sota_soak.LIVES == 0x8f67d0 and sota_soak.WIN_LIFE == 0x8f67d4


def test_sota_soak_expects_its_own_messages_on_stderr(tmp_path):
    import argparse
    import sota_soak
    a = argparse.Namespace(res="1024x768", seed=1, workdir=str(tmp_path / "s"), program="sources/installed_sota_215_m2/Program/shandalar.exe", module=None, repo=str(tmp_path), exe="x")
    s = sota_soak.SotaSoak(a)
    known = lambda line: any(k.match(line) for k in s.known_stderr)           # noqa: E731
    assert known("LoadLibraryA(drawcardlib.dll) -> mapped at 0x36000000") and known("process: started facemaker.exe (module game_facemaker, id 61333)")
    assert known("build: v2.15 shandalar.exe (sha256 e4e46718c451)") and not known("overworld frame took 700 ms (the period is 60)")


def test_read_ppm(tmp_path):
    import sota_soak
    p = tmp_path / "a.ppm"
    p.write_bytes(b"P6\n2 1\n255\n" + bytes([1, 2, 3, 4, 5, 6]))
    assert sota_soak.read_ppm(str(p)) == (2, 1, bytes([1, 2, 3, 4, 5, 6]))
    assert sota_soak.read_ppm(str(tmp_path / "none.ppm")) is None

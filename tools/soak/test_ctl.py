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

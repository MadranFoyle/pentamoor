"""Tests of the research readers, on files made up here (no game file is needed or used).   python3 -m pytest tools/research

  sotacards.py   a CARDS.DAT-shaped file and the comparison of two
  iscab.py, sotapatch.py, sotaoverlay.py   moved to tools/install (the installer uses them: tools/install/test_sota.py tests them); what is left here are the old commands, which run the
                 installer's readers
"""
import contextlib
import io
import os
import struct
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import sotacards  # noqa: E402


# ---- CARDS.DAT ------------------------------------------------------------------------------------------------------------------------------------------------
def make_cards(cards):
    """cards: list of (name, short, rules, flavour, third numeric field). 999 slots are not needed: the reader takes the count from the file."""
    pool = b""
    refs = []
    for c in cards:
        r = []
        for s in c[:4]:
            r.append(len(pool))
            pool += s.encode() + b"\0"
        refs.append(r)
    recs = b""
    for i, (c, r) in enumerate(zip(cards, refs)):
        w = [0] * 38
        w[0] = i
        w[1], w[2], w[29], w[30] = r
        w[3] = c[4]
        recs += struct.pack("<38I", *w)
    return struct.pack("<II", len(cards), len(pool)) + recs + pool


def test_cards_dat_comparison_counts(tmp_path):
    a = tmp_path / "a.dat"
    b = tmp_path / "b.dat"
    a.write_bytes(make_cards([("Alpha", "Alpha", "Flying", "-", 1), ("Beta", "Beta", "Haste", "-", 2), ("None", "None", "None", "None", 0)]))
    b.write_bytes(make_cards([("Alpha", "Alpha", "Flying and more", "-", 1), ("Gamma", "Gamma", "Haste", "-", 2), ("None", "None", "None", "None", 0)]))
    d, n, pool, cards = sotacards.load(str(a))
    assert n == 3 and len(d) == 8 + 3 * 152 + pool and cards[0]["text"] == "Flying"
    assert set(sotacards.used(cards)) == {"Alpha", "Beta"}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert sotacards.main(["x", "old=" + str(a), "new=" + str(b)]) == 0
    text = buf.getvalue()
    assert "added 1, removed 1" in text and "rules text 1" in text and "e.g. added: Gamma" in text


def test_cards_dat_with_the_wrong_size_is_refused(tmp_path):
    p = tmp_path / "bad.dat"
    p.write_bytes(make_cards([("A", "A", "x", "y", 1)]) + b"extra")
    with pytest.raises(SystemExit):
        sotacards.load(str(p))


# ---- the old commands, which now run the installer's readers --------------------------------------------------------------------------------------------------
def run_command(name, *args):
    return subprocess.run([sys.executable, os.path.join(HERE, name), *args], capture_output=True, text=True)


def test_the_old_patch_command_runs_the_installers_reader(tmp_path):
    sys.path.insert(0, os.path.join(HERE, "..", "install"))
    import fakediscs
    arc = tmp_path / "p.exe"
    arc.write_bytes(fakediscs.make_patch({"a.txt": b"hello" * 20}))
    r = run_command("sotapatch.py", "--check", str(arc))
    assert r.returncode == 0 and "a.txt" in r.stdout and "crc" in r.stdout
    arc.write_bytes(arc.read_bytes()[:-30])
    assert run_command("sotapatch.py", "--check", str(arc)).returncode == 1


def test_the_old_cabinet_command_lists_a_cabinet(tmp_path):
    sys.path.insert(0, os.path.join(HERE, "..", "install"))
    import fakediscs
    cab = tmp_path / "data1.cab"
    cab.write_bytes(fakediscs.make_cab(0x01005100, {"Program/a.txt": b"hello " * 100}, True))
    r = run_command("iscab.py", str(cab), str(tmp_path / "out"))
    assert r.returncode == 0 and "Program\\a.txt" in r.stdout
    assert (tmp_path / "out" / "Program" / "a.txt").read_bytes() == b"hello " * 100


def test_the_old_overlay_command_merges_two_folders(tmp_path):
    base, over, dest = tmp_path / "base", tmp_path / "over", tmp_path / "dest"
    (base / "Program").mkdir(parents=True)
    (over / "Program").mkdir(parents=True)
    (base / "Program" / "CARDS.DAT").write_bytes(b"old")
    (over / "Program" / "cards.dat").write_bytes(b"new")
    r = run_command("sotaoverlay.py", str(base), str(over), str(dest))
    assert r.returncode == 0 and "replaced 1, identical 0, added 0" in r.stdout
    assert [p.name for p in (dest / "Program").iterdir()] == ["CARDS.DAT"]

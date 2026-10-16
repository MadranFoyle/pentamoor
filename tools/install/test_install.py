"""Tests of the installer's parts with data made here: no game files and no disc are needed.   python3 -m pytest tools/install"""
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blast as blastmod  # noqa: E402
import datax  # noqa: E402
import iso9660  # noqa: E402


# ---- an encoder for DCL streams (the decoder's tables read the other way), for the tests only ---------------------------------------------------------------
def codes(rep):
    count, symbol = blastmod._construct(rep)
    table, code, index = {}, 0, 0
    # decode() accumulates inverted bits: the first bit read is the most significant of the code
    first = 0
    for length in range(1, 16):
        for i in range(count[length]):
            table[symbol[index + i]] = (first + i, length)
        index += count[length]
        first = (first + count[length]) << 1
    return table


LEN_CODES, DIST_CODES = codes(blastmod._LENLEN), codes(blastmod._DISTLEN)


class Bits:
    def __init__(self):
        self.out, self.acc, self.n = bytearray(), 0, 0

    def put(self, value, nbits):
        self.acc |= value << self.n
        self.n += nbits
        while self.n >= 8:
            self.out.append(self.acc & 255)
            self.acc >>= 8
            self.n -= 8

    def huff(self, entry):                      # codes are sent most significant bit first, inverted
        code, length = entry
        for i in range(length - 1, -1, -1):
            self.put(((code >> i) & 1) ^ 1, 1)

    def finish(self):
        if self.n:
            self.out.append(self.acc & 255)
        return bytes(self.out)


def len_symbol(length):
    for sym in range(15, -1, -1):
        if blastmod._BASE[sym] <= length and length - blastmod._BASE[sym] < (1 << blastmod._EXTRA[sym]):
            return sym
    raise ValueError(length)


def implode(literals, matches=(), dict_bits=4):
    """A DCL stream: the literals (raw 8-bit), then each (length, distance) match, then the end mark."""
    b = Bits()
    b.put(0, 8)
    b.put(dict_bits, 8)
    for c in literals:
        b.put(0, 1)
        b.put(c, 8)
    for length, dist in matches:
        b.put(1, 1)
        sym = len_symbol(length)
        b.huff(LEN_CODES[sym])
        b.put(length - blastmod._BASE[sym], blastmod._EXTRA[sym])
        shift = 2 if length == 2 else dict_bits
        d = dist - 1
        b.huff(DIST_CODES[d >> shift])
        b.put(d & ((1 << shift) - 1), shift)
    b.put(1, 1)
    b.huff(LEN_CODES[15])
    b.put(519 - blastmod._BASE[15], blastmod._EXTRA[15])
    return b.finish()


def test_blast_literals_and_matches():
    out = blastmod.blast(implode(b"hello, world. ", [(5, 14), (3, 2)]))
    assert out[:14] == b"hello, world. "
    assert out[14:19] == b"hello"                         # five bytes from fourteen back
    assert out[19:22] == bytes([out[17], out[18], out[17]])   # three from two back: the pair repeats
    assert len(out) == 22


def test_blast_overlapping_copy_repeats():
    out = blastmod.blast(implode(b"ab", [(10, 2)]))
    assert out == b"ab" * 6


def test_blast_rejects_what_is_not_a_stream():
    with pytest.raises(blastmod.BlastError):
        blastmod.blast(b"\x07\x04abc")
    with pytest.raises(blastmod.BlastError):
        blastmod.blast(implode(b"abc")[:3])


# ---- the archive ------------------------------------------------------------------------------------------------------------------------------------------
def make_archive(files, dirs):
    """files: [(name, data)] in order, the first two outside the table; dirs: [(dirname, count)]. Returns the archive bytes."""
    body = bytearray(b"\0" * 0x40)
    metas = []
    for name, data in files:
        packed = implode(data)
        metas.append((len(data), len(packed), len(body)))
        body += packed
    tbl = len(body)
    body += b"\x02\x00\x0b\x00" + b"\0" * 7
    for dirname, count in dirs:
        nb = dirname.encode()
        body += struct.pack("<HHH", count, len(nb) + 11, len(nb)) + nb + b"\0" * 5
    body += b"\0\0\0" + struct.pack("<III", *metas[0]) + struct.pack("<I", 0)
    for k, (name, data) in enumerate(files):
        nb = name.encode()
        nxt = metas[k + 1] if k + 1 < len(metas) else (0, 0, 0)
        rec = struct.pack("<II", 0x20, 0) + b"\0\0" + bytes([len(nb)]) + nb + b"\0" * 12 + struct.pack("<III", *nxt) + struct.pack("<I", 0)
        rec = rec[:4] + struct.pack("<I", len(rec)) + rec[8:]
        body += rec
    body[0:4] = struct.pack("<I", datax.SIGNATURE)
    struct.pack_into("<I", body, 0x12, len(body))
    struct.pack_into("<I", body, 0x29, tbl)
    return bytes(body)


def test_archive_lists_and_unpacks_files_in_their_directories():
    files = [("README.TXT", b"read me"), ("shortcut.url", b"[url]"), ("A.PIC", b"aaaa" * 30), ("B.SPR", b"bee"), ("C.WAV", b"")]
    arc = make_archive(files, [("program", 2), ("program\\Sound", 1)])
    listed = datax.parse(arc)
    assert [p for p, *_ in listed] == ["program\\A.PIC", "program\\B.SPR", "program\\Sound\\C.WAV"]
    got = {p: datax.unpack(arc, *rest) for p, *rest in listed}
    assert got["program\\A.PIC"] == b"aaaa" * 30 and got["program\\B.SPR"] == b"bee" and got["program\\Sound\\C.WAV"] == b""


def test_archive_that_is_not_one_is_refused():
    with pytest.raises(datax.DataZError):
        datax.parse(b"\0" * 100)


# ---- the disc ---------------------------------------------------------------------------------------------------------------------------------------------
def make_iso(path, files):
    """A one-level ISO 9660 image: files = {name: bytes}."""
    sector = 2048
    names = sorted(files)
    root_lba = 18
    data_lba = 19
    out = bytearray(sector * (data_lba + sum((len(files[n]) + sector - 1) // sector + 1 for n in names) + 1))
    pvd = bytearray(sector)
    pvd[0:7] = b"\x01CD001\x01"
    pvd[40:72] = b"TESTDISC".ljust(32)
    root_rec = bytearray(34)
    root_rec[0] = 34
    struct.pack_into("<I", root_rec, 2, root_lba)
    struct.pack_into("<I", root_rec, 10, sector)
    root_rec[25] = 2
    root_rec[32] = 1
    pvd[156:190] = root_rec
    out[16 * sector:17 * sector] = pvd
    term = bytearray(sector)
    term[0:7] = b"\xffCD001\x01"
    out[17 * sector:18 * sector] = term
    d = bytearray()
    lba = data_lba
    for n in names:
        nb = n.upper().encode() + b";1"
        rec = bytearray(33 + len(nb) + (len(nb) % 2 == 0))
        rec[0] = len(rec)
        struct.pack_into("<I", rec, 2, lba)
        struct.pack_into("<I", rec, 10, len(files[n]))
        rec[32] = len(nb)
        rec[33:33 + len(nb)] = nb
        d += rec
        out[lba * sector:lba * sector + len(files[n])] = files[n]
        lba += (len(files[n]) + sector - 1) // sector
    out[root_lba * sector:root_lba * sector + len(d)] = d
    with open(path, "wb") as f:
        f.write(out)


def test_iso_reader_finds_files_without_regard_to_case(tmp_path):
    p = tmp_path / "t.iso"
    make_iso(str(p), {"data.z": b"Z" * 5000, "hello.txt": b"hi"})
    disc = iso9660.open_disc(str(p))
    assert disc.label == "TESTDISC"
    e = disc.find("Data.Z")
    assert e is not None and e.size == 5000 and disc.read(e) == b"Z" * 5000
    assert disc.read(disc.find("HELLO.TXT")) == b"hi"
    assert disc.find("missing") is None
    out = tmp_path / "x" / "copy.bin"
    disc.copy(e, str(out))
    assert out.read_bytes() == b"Z" * 5000


def test_a_raw_mdf_or_other_file_is_not_an_iso(tmp_path):
    p = tmp_path / "t.mdf"
    p.write_bytes(b"\0" * 40000)
    with pytest.raises(iso9660.IsoError):
        iso9660.open_disc(str(p))


def test_a_folder_reads_like_a_disc(tmp_path):
    (tmp_path / "Setup").mkdir()
    (tmp_path / "Setup" / "DATA.Z").write_bytes(b"abc")
    disc = iso9660.open_disc(str(tmp_path))
    e = disc.find("setup/data.z")
    assert e is not None and disc.read(e) == b"abc"


# ---- the build and the launcher: the runtime and the game module are separate ----------------------------------------------------------------------------
def test_build_makes_the_runtime_and_the_game_modules_in_one_make():
    import install
    cmds = install.build_commands()
    assert len(cmds) == 1
    argv = cmds[0][1]
    assert argv[0] == "make" and argv[-1] == "all" and argv[1] == "-C" and argv[2].replace(os.sep, "/").endswith("src/port")
    assert not any(a.startswith(("GEN=", "BUILD=")) for a in argv)         # no per-program rebuild of the runtime


@pytest.mark.skipif(sys.platform == "win32", reason="./pentamoor is a shell script")
def test_launcher_starts_the_runtime_with_the_module_of_the_program(tmp_path):
    import shutil
    import stat
    import subprocess
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    shutil.copy(os.path.join(root, "pentamoor"), tmp_path / "pentamoor")
    build = tmp_path / "src" / "port" / "build"
    build.mkdir(parents=True)
    run = build / "pentamoor-run"
    run.write_text('#!/bin/sh\necho "$@"\n')
    run.chmod(run.stat().st_mode | stat.S_IEXEC)
    game = tmp_path / "sources" / "installed" / "Magic" / "Program"
    game.mkdir(parents=True)
    ext = "dylib" if sys.platform == "darwin" else "so"

    def launch(*args):
        return subprocess.run(["sh", str(tmp_path / "pentamoor"), *args], capture_output=True, text=True)

    r = launch()
    assert r.returncode == 1 and "the game is not installed" in r.stderr
    for exe in ("MAGIC.EXE", "DECK.EXE", "DUEL.EXE"):
        (game / exe).write_bytes(b"")
    r = launch()
    assert r.returncode == 1 and "game module is not built" in r.stderr
    for prog in ("magic", "deck", "duel"):
        (build / f"game_{prog}.{ext}").write_bytes(b"")
    assert launch().stdout.split() == ["-m", f"src/port/build/game_magic.{ext}", "sources/installed/Magic/Program/MAGIC.EXE"]
    assert launch("deck").stdout.split() == ["-m", f"src/port/build/game_deck.{ext}", "sources/installed/Magic/Program/DECK.EXE"]
    out = launch("duel", "extra").stdout.split()
    assert out[:2] == ["-m", f"src/port/build/game_duel.{ext}"] and out[-2:] == ["sources/installed/Magic/Program/DUEL.EXE", "extra"]
    run.unlink()
    r = launch()
    assert r.returncode == 1 and "runtime is not built" in r.stderr


# ---- which build the installed files are (builds.py, the same ids as the runtime's profiles) --------------------------------------------------------------
def test_the_installers_fingerprints_are_the_retail_discs():
    import install
    assert install.FINGERPRINTS == {
        "MAGIC.EXE": "4dc592695b6ee390485f283feb2a248cd3f3f739749c2800ab3b1100ea03845c",
        "DUEL.EXE": "7c4e618b4a8ab4330c71d2dd30637c522573c133d32c667c97924dc8edc2efed",
        "DECK.EXE": "193f8abea01d4f2c03b769224b06eece6e263a18f13a5b4e2509ed25a01e3d90",
        "DECKDLL.DLL": "a21f714bea465077c4fabe4a407ff7503b0ce5f9bb1a277826e74276e35c2c18",
        "STATWIN.DLL": "95bd14de41e8fff84217cdf627a48392da5e7be9c3d064a68e04ed1455334bd7",
        "MAGSND.DLL": "6f6d51cd2b8a5800b0b3c994e3ee8217f7b40ba2621f9738783387f3250a9882",
        "MAGVID.DLL": "d2db1435ae96e9e41d77ded7a7b222969d44d5af642fa9968fe51768c1ce83a3",
    }


@pytest.fixture
def fake_build(monkeypatch):
    """Two files that stand for a build: their ids replace the retail disc's in the installer's list."""
    import builds
    import install
    files = {"MAGIC.EXE": b"the shell", "DUEL.EXE": b"the duel"}
    known = [("v9.9", n, builds.build_id(b), "lifted") for n, b in files.items()]
    monkeypatch.setattr(builds, "KNOWN", known)
    monkeypatch.setattr(install, "FINGERPRINTS", builds.fingerprints("v9.9"))
    return files


def program_dir(tmp_path, files):
    d = tmp_path / "installed" / "Magic" / "Program"
    d.mkdir(parents=True)
    for n, b in files.items():
        (d / n).write_bytes(b)
    return d


def test_detect_builds_names_the_build_of_each_file(tmp_path, fake_build):
    import install
    d = program_dir(tmp_path, fake_build)
    got = install.detect_builds(str(d))
    assert [(n, k) for n, _, k in got] == [("MAGIC.EXE", "v9.9 MAGIC.EXE"), ("DUEL.EXE", "v9.9 DUEL.EXE")]
    assert install.build_summary(got) == "v9.9 (MAGIC.EXE, DUEL.EXE: the retail disc)"
    # another file under a known name is an unknown build; a file that is not there is missing; the case of the name is the disc's business
    (d / "MAGIC.EXE").write_bytes(b"a patched shell")
    (d / "DUEL.EXE").rename(d / "Duel.exe")
    got = install.detect_builds(str(d))
    assert got[0][2] is None and got[0][1] and got[1][2] == "v9.9 DUEL.EXE"
    assert "MAGIC.EXE is an unknown build (sha256 " in install.build_summary(got) and "DUEL.EXE is v9.9 DUEL.EXE" in install.build_summary(got)
    (d / "Duel.exe").unlink()
    got = install.detect_builds(str(d))
    assert got[1][1] is None and "DUEL.EXE is missing" in install.build_summary(got)


def test_the_extracted_game_is_checked_against_the_known_build(tmp_path, fake_build, capsys):
    import install
    program_dir(tmp_path / "x", fake_build)
    assert install.check_programs(str(tmp_path / "x" / "installed")) is True
    assert "are build v9.9" in capsys.readouterr().out
    (tmp_path / "x" / "installed" / "Magic" / "Program" / "MAGIC.EXE").write_bytes(b"other")
    assert install.check_programs(str(tmp_path / "x" / "installed")) is False
    out = capsys.readouterr().out
    assert "MAGIC.EXE is an unknown build" in out and "refuses to start a program of another build" in out


def test_check_reports_the_build_of_the_installed_game(tmp_path, fake_build, capsys):
    import install

    class Args:
        compiler = None

    root = tmp_path / "root"
    program_dir(root / "sources", fake_build)
    install.check(install.Layout(str(root)), Args())
    out = capsys.readouterr().out
    assert "build:  v9.9 (MAGIC.EXE, DUEL.EXE: the retail disc)" in out
    (root / "sources" / "installed" / "Magic" / "Program" / "MAGIC.EXE").write_bytes(b"x")
    install.check(install.Layout(str(root)), Args())
    assert "build:  MAGIC.EXE is an unknown build" in capsys.readouterr().out


def test_the_release_carries_the_build_list():
    import manifest
    assert "tools/lift/builds.py" in manifest.REQUIRED
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    assert "tools/lift/builds.py" in manifest.release_files(root)

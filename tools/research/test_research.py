"""Tests of the research readers, on archives and files made up here (no game file is needed or used).   python3 -m pytest tools/research

  sotapatch.py   a WinZip-style self-extractor: a whole one, one cut short, one with a damaged entry, false signatures in the stub, case-insensitive extraction
  iscab.py       an InstallShield 5 cabinet in both layouts of compressed data (chunks of the 2.0 disc, one stream of ManaLink 3.0's cabinet)
  sotacards.py   a CARDS.DAT-shaped file and the comparison of two
  sotaoverlay.py an install copied over another as Windows does it
"""
import io
import os
import struct
import sys
import zipfile
import zlib

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import iscab  # noqa: E402
import sotacards  # noqa: E402
import sotaoverlay  # noqa: E402
import sotapatch  # noqa: E402

STUB = b"MZ" + b"\0" * 60 + b"PK\x03\x04" + b"\xff" * 40 + b"PK\x03\x04\x14\0\0\0\x08\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\x03\0\0\0abc" + b"\0" * 100   # false signatures: one with junk fields, one with a name


def make_archive(files, method=zipfile.ZIP_DEFLATED):
    """A self-extractor-shaped file: a stub with false ZIP signatures, then a ZIP with the given {name: bytes}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", method) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return STUB + buf.getvalue()


FILES = {"shandalar.exe": bytes(range(256)) * 40, "readme.txt": b"hello world\n" * 300, "cards.dat": os.urandom(5000), "FaceData.txt": b"x" * 208}


def run(argv):
    return sotapatch.main(["sotapatch.py"] + argv)


def test_a_whole_archive_lists_verifies_and_extracts(tmp_path, capsys):
    arc = tmp_path / "patch.exe"
    arc.write_bytes(make_archive(FILES))
    good, problems = sotapatch.report(arc.read_bytes())
    assert problems == []
    assert [e["name"] for e in good] == list(FILES) and all(e["status"] == "ok" for e in good)
    out = tmp_path / "out"
    assert run([str(arc), str(out)]) == 0
    assert {p.name: p.read_bytes() for p in out.iterdir()} == FILES
    text = capsys.readouterr().out
    assert "sha256" in text and "crc" in text


def test_the_old_interface_still_lists_whole_entries():
    data = make_archive(FILES)
    assert [e[1] for e in sotapatch.entries(data)] == list(FILES)
    assert sotapatch.read(data, sotapatch.entries(data)[1]) == FILES["readme.txt"]


def test_an_archive_cut_short_is_reported_and_not_extracted(tmp_path, capsys):
    data = make_archive(FILES)
    arc = tmp_path / "patch.exe"
    arc.write_bytes(data[:len(data) - 3000])                    # the end record, the directory and the tail of the last entry are gone
    good, problems = sotapatch.report(arc.read_bytes())
    assert any("TRUNCATED" in p for p in problems)
    assert any("end-of-central-directory" in p for p in problems)
    assert [(e["name"], e["status"]) for e in good] == [("shandalar.exe", "ok"), ("readme.txt", "ok"), ("cards.dat", "truncated")]
    out = tmp_path / "out"
    assert run([str(arc), str(out)]) == 1
    assert not out.exists()                                     # nothing written: a half patch must not be overlaid
    assert run(["--partial", str(arc), str(out)]) == 1
    assert (out / "shandalar.exe").read_bytes() == FILES["shandalar.exe"]
    assert (out / "readme.txt").read_bytes() == FILES["readme.txt"] and not (out / "cards.dat").exists()
    assert "NOT a whole archive" in capsys.readouterr().err


def test_an_archive_that_lost_only_its_end_is_reported(tmp_path):
    data = make_archive(FILES)
    end = data.rfind(b"PK\x05\x06")
    good, problems = sotapatch.report(data[:end])
    assert all(e["status"] == "ok" for e in good)
    assert len(problems) == 1 and "end-of-central-directory" in problems[0]


def test_a_damaged_entry_is_corrupt(tmp_path):
    data = bytearray(make_archive(FILES, zipfile.ZIP_STORED))
    at = data.find(b"hello world") + 20
    data[at] ^= 0xFF
    good, problems = sotapatch.report(bytes(data))
    assert any("CORRUPT" in p and "readme.txt" in p for p in problems)


def test_false_signatures_in_the_stub_are_not_entries():
    assert [e for e in sotapatch.scan(STUB) if e["status"] == "ok"] == []
    assert sotapatch.report(STUB)[0] == [] or all(e["status"] != "ok" for e in sotapatch.report(STUB)[0])


def test_extraction_keeps_the_name_that_is_already_there_ignoring_case(tmp_path):
    arc = tmp_path / "patch.exe"
    arc.write_bytes(make_archive(FILES))
    out = tmp_path / "Program"
    out.mkdir()
    (out / "CARDS.DAT").write_bytes(b"old")
    (out / "Readme.TXT").write_bytes(b"old")
    assert run([str(arc), str(out)]) == 0
    names = sorted(p.name for p in out.iterdir())
    assert "CARDS.DAT" in names and "Readme.TXT" in names and "cards.dat" not in names and "readme.txt" not in names
    assert (out / "CARDS.DAT").read_bytes() == FILES["cards.dat"]


def test_extraction_refuses_to_write_through_a_symbolic_link(tmp_path):
    arc = tmp_path / "patch.exe"
    arc.write_bytes(make_archive({"a.bin": b"data"}))
    target = tmp_path / "target.bin"
    target.write_bytes(b"precious")
    out = tmp_path / "out"
    out.mkdir()
    os.symlink(target, out / "a.bin")
    with pytest.raises(SystemExit):
        run([str(arc), str(out)])
    assert target.read_bytes() == b"precious"


# ---- an InstallShield 5 cabinet -------------------------------------------------------------------------------------------------------------------------------
def raw_deflate(data):
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    return c.compress(data) + c.flush()


def make_cab(version, files, chunked):
    """The cabinet layout iscab.py documents: header, descriptor at 0x200, file table (directory names, strings, 0x2a-byte file descriptors), then the data."""
    dirs = sorted({os.path.dirname(n) for n in files})
    strings = b""
    dir_off, name_off = [], {}
    n_entries = len(dirs) + len(files)
    pos = 4 * n_entries
    for d in dirs:
        dir_off.append(pos + len(strings))
        strings += d.encode() + b"\0"
    for n in files:
        name_off[n] = pos + len(strings)
        strings += os.path.basename(n).encode() + b"\0"
    desc_start = pos + len(strings)
    table_size = desc_start + 0x2a * len(files)
    ft_off_in_desc = 0x40
    data_start = 0x200 + ft_off_in_desc + table_size
    blobs, data = [], b""
    for n, d in files.items():
        if chunked:
            raw = b"".join(struct.pack("<H", len(c)) + c for c in (raw_deflate(d[i:i + 100]) for i in range(0, max(len(d), 1), 100)))
        else:
            raw = raw_deflate(d)
        blobs.append((n, d, raw, data_start + len(data)))
        data += raw
    descs = b""
    for n, d, raw, off in blobs:
        e = bytearray(0x2a)
        struct.pack_into("<IIHII", e, 0, name_off[n], dirs.index(os.path.dirname(n)), 4, len(d), len(raw))
        struct.pack_into("<I", e, 0x26, off)
        descs += bytes(e)
    table = b"".join(struct.pack("<I", o) for o in dir_off) + b"".join(struct.pack("<I", desc_start + 0x2a * i) for i in range(len(files))) + strings + descs
    assert len(table) == table_size
    desc = bytearray(ft_off_in_desc)
    struct.pack_into("<III", desc, 0x0c, ft_off_in_desc, 0, table_size)
    struct.pack_into("<I", desc, 0x1c, len(dirs))
    struct.pack_into("<I", desc, 0x28, len(files))
    head = bytearray(0x200)
    head[:4] = b"ISc("
    struct.pack_into("<I", head, 4, version)
    struct.pack_into("<II", head, 0x0c, 0x200, len(desc) + len(table))
    return bytes(head) + bytes(desc) + table + data


CAB_FILES = {"Program\\a.txt": b"hello " * 100, "Program\\Sub\\b.bin": bytes(range(256)) * 4, "Program\\c.dat": b"z"}


@pytest.mark.parametrize("version,chunked", [(0x01005100, True), (0x01000004, False)])
def test_cabinet_layouts_extract(version, chunked):
    files = {k.replace("\\", "/"): v for k, v in CAB_FILES.items()}
    cab = iscab.Cab(io.BytesIO(make_cab(version, files, chunked)))
    assert cab.chunked == chunked
    got = {e[0].replace("\\", "/"): cab.read(e) for e in cab.files}
    assert got == files


def test_a_cabinet_read_with_the_wrong_layout_falls_back():
    files = {"Program/a.txt": b"hello " * 100}
    cab = iscab.Cab(io.BytesIO(make_cab(0x01000004, files, True)))       # chunked data under the version that says "one stream"
    assert cab.read(cab.files[0]) == files["Program/a.txt"]


def test_a_cabinet_that_inflates_to_the_wrong_size_is_an_error():
    cab = iscab.Cab(io.BytesIO(make_cab(0x01000004, {"Program/a.txt": b"abc" * 50}, False)))
    e = list(cab.files[0])
    e[1] += 1
    with pytest.raises(iscab.CabError):
        cab.read(tuple(e))


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
    import contextlib
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


# ---- the overlay ------------------------------------------------------------------------------------------------------------------------------------------------
def test_overlay_replaces_ignoring_case_and_counts(tmp_path, capsys):
    base, over, dest = tmp_path / "base", tmp_path / "over", tmp_path / "dest"
    (base / "Program" / "ShellArt").mkdir(parents=True)
    (over / "Program" / "shellart").mkdir(parents=True)
    (over / "_setup").mkdir()
    (base / "Program" / "CARDS.DAT").write_bytes(b"old")
    (base / "Program" / "same.txt").write_bytes(b"same")
    (base / "Program" / "ShellArt" / "a.pic").write_bytes(b"old")
    (over / "Program" / "cards.dat").write_bytes(b"new")
    (over / "Program" / "same.txt").write_bytes(b"same")
    (over / "Program" / "shellart" / "A.PIC").write_bytes(b"new")
    (over / "Program" / "added.exe").write_bytes(b"x")
    (over / "_setup" / "setup.ins").write_bytes(b"not part of the install")
    assert sotaoverlay.main(["x", str(base), str(over), str(dest), "--only", "Program"]) == 0
    assert "replaced 2, identical 1, added 1" in capsys.readouterr().out
    assert sorted(p.name for p in (dest / "Program").iterdir()) == ["CARDS.DAT", "ShellArt", "added.exe", "same.txt"]
    assert (dest / "Program" / "CARDS.DAT").read_bytes() == b"new"
    assert [p.name for p in (dest / "Program" / "ShellArt").iterdir()] == ["a.pic"]
    assert not (dest / "_setup").exists()
    assert (base / "Program" / "CARDS.DAT").read_bytes() == b"old"       # the base is untouched


def test_overlay_refuses_a_destination_that_is_not_empty(tmp_path):
    base, over, dest = tmp_path / "base", tmp_path / "over", tmp_path / "dest"
    for d in (base, over, dest):
        d.mkdir()
    (dest / "keep").write_bytes(b"x")
    assert sotaoverlay.main(["x", str(base), str(over), str(dest)]) == 2

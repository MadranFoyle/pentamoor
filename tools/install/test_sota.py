"""Tests of the Spells of the Ancients 2.15 installer, on discs, cabinets and patches made up here (no game file and no disc are needed).   python3 -m pytest tools/install

  iscab.py       an InstallShield 5 cabinet in both layouts of compressed data (chunks of the 2.0 disc, one stream of ManaLink 3.0's cabinet); cut short; damaged
  sotapatch.py   a WinZip-style self-extractor: a whole one, one cut short, one with a damaged entry, false signatures in the stub, case-insensitive extraction
  overlay.py     files put into a folder as Windows does it (names compared ignoring case), and refused when they would lead out of it
  sotainstall.py the discs and the patch are told apart and checked before anything is written; the folder comes out as exactly 2.15 or is refused file by file
  install.py     the whole command with fakes: what it reads, what it writes, in which order it builds, what it says when a source is missing or wrong
"""
import io
import os
import sys
import types
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lift"))
import fakediscs  # noqa: E402
import iscab  # noqa: E402
import iso9660  # noqa: E402
import overlay  # noqa: E402
import sotapatch  # noqa: E402

needs_symlinks = pytest.mark.skipif(sys.platform == "win32", reason="making a symbolic link needs a privilege on Windows")

FILES = {"shandalar.exe": bytes(range(256)) * 40, "readme.txt": b"hello world\n" * 300, "cards.dat": os.urandom(5000), "FaceData.txt": b"x" * 208}


# ---- the patch --------------------------------------------------------------------------------------------------------------------------------------------
def run(argv):
    return sotapatch.main(["sotapatch.py"] + argv)


def test_a_whole_patch_lists_verifies_and_extracts(tmp_path, capsys):
    arc = tmp_path / "patch.exe"
    arc.write_bytes(fakediscs.make_patch(FILES))
    good, problems = sotapatch.report(arc.read_bytes())
    assert problems == []
    assert [e["name"] for e in good] == list(FILES) and all(e["status"] == "ok" for e in good)
    assert sotapatch.load(str(arc)) == list(FILES.items())
    out = tmp_path / "out"
    assert run([str(arc), str(out)]) == 0
    assert {p.name: p.read_bytes() for p in out.iterdir()} == FILES
    text = capsys.readouterr().out
    assert "sha256" in text and "crc" in text


def test_the_old_interface_still_lists_whole_entries():
    data = fakediscs.make_patch(FILES)
    assert [e[1] for e in sotapatch.entries(data)] == list(FILES)
    assert sotapatch.read(data, sotapatch.entries(data)[1]) == FILES["readme.txt"]


def test_a_patch_cut_short_is_reported_and_not_extracted(tmp_path, capsys):
    data = fakediscs.make_patch(FILES)
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
    with pytest.raises(sotapatch.PatchError) as e:               # and the installer's reader says the same, as one message
        sotapatch.load(str(arc))
    assert "cards.dat: TRUNCATED" in str(e.value) and "not a whole archive" in str(e.value)


def test_a_patch_that_lost_only_its_end_is_reported():
    data = fakediscs.make_patch(FILES)
    end = data.rfind(b"PK\x05\x06")
    good, problems = sotapatch.report(data[:end])
    assert all(e["status"] == "ok" for e in good)
    assert len(problems) == 1 and "end-of-central-directory" in problems[0]


def test_a_damaged_entry_is_corrupt():
    data = bytearray(fakediscs.make_patch(FILES, zipfile.ZIP_STORED))
    at = data.find(b"hello world") + 20
    data[at] ^= 0xFF
    good, problems = sotapatch.report(bytes(data))
    assert any("CORRUPT" in p and "readme.txt" in p for p in problems)


def test_false_signatures_in_the_stub_are_not_entries():
    assert [e for e in sotapatch.scan(fakediscs.STUB) if e["status"] == "ok"] == []
    assert sotapatch.report(fakediscs.STUB)[0] == [] or all(e["status"] != "ok" for e in sotapatch.report(fakediscs.STUB)[0])


def test_a_file_that_is_not_a_patch_has_no_files_in_it(tmp_path):
    p = tmp_path / "x.exe"
    p.write_bytes(fakediscs.STUB)
    with pytest.raises(sotapatch.PatchError) as e:
        sotapatch.load(str(p))
    assert "no files in it" in str(e.value)
    with pytest.raises(sotapatch.PatchError) as e:
        sotapatch.load(str(tmp_path / "missing.exe"))
    assert "cannot read" in str(e.value)


def test_extraction_keeps_the_name_that_is_already_there_ignoring_case(tmp_path):
    arc = tmp_path / "patch.exe"
    arc.write_bytes(fakediscs.make_patch(FILES))
    out = tmp_path / "Program"
    out.mkdir()
    (out / "CARDS.DAT").write_bytes(b"old")
    (out / "Readme.TXT").write_bytes(b"old")
    assert run([str(arc), str(out)]) == 0
    names = sorted(p.name for p in out.iterdir())
    assert "CARDS.DAT" in names and "Readme.TXT" in names and "cards.dat" not in names and "readme.txt" not in names
    assert (out / "CARDS.DAT").read_bytes() == FILES["cards.dat"]


@needs_symlinks
def test_extraction_refuses_to_write_through_a_symbolic_link(tmp_path):
    arc = tmp_path / "patch.exe"
    arc.write_bytes(fakediscs.make_patch({"a.bin": b"data"}))
    target = tmp_path / "target.bin"
    target.write_bytes(b"precious")
    out = tmp_path / "out"
    out.mkdir()
    os.symlink(target, out / "a.bin")
    with pytest.raises(SystemExit):
        run([str(arc), str(out)])
    assert target.read_bytes() == b"precious"


# ---- an InstallShield 5 cabinet -----------------------------------------------------------------------------------------------------------------------------
CAB_FILES = {"Program/a.txt": b"hello " * 100, "Program/Sub/b.bin": bytes(range(256)) * 4, "Program/c.dat": b"z", "Readme.txt": b"top"}


@pytest.mark.parametrize("version,chunked", [(0x01005100, True), (0x01000004, False)])
def test_cabinet_layouts_extract(version, chunked):
    cab = iscab.Cab(io.BytesIO(fakediscs.make_cab(version, CAB_FILES, chunked)))
    assert cab.chunked == chunked
    got = {e[0].replace("\\", "/"): cab.read(e) for e in cab.files}
    assert got == CAB_FILES


def test_a_cabinet_read_with_the_wrong_layout_falls_back():
    files = {"Program/a.txt": b"hello " * 100}
    cab = iscab.Cab(io.BytesIO(fakediscs.make_cab(0x01000004, files, True)))       # chunked data under the version that says "one stream"
    assert cab.read(cab.files[0]) == files["Program/a.txt"]


def test_a_cabinet_that_inflates_to_the_wrong_size_is_an_error():
    cab = iscab.Cab(io.BytesIO(fakediscs.make_cab(0x01000004, {"Program/a.txt": b"abc" * 50}, False)))
    e = list(cab.files[0])
    e[1] += 1
    with pytest.raises(iscab.CabError):
        cab.read(tuple(e))


def test_a_cabinet_cut_short_says_so_where_it_is_cut():
    data = fakediscs.make_cab(0x01005100, CAB_FILES, True)
    cab = iscab.Cab(io.BytesIO(data[:-3]))                                          # the last file's data ends early: the table is whole, one file is not
    ok = [cab.read(e) for e in cab.files[:-1]]
    assert ok == [CAB_FILES[k.replace("\\", "/")] for k, *_ in cab.files[:-1]]
    with pytest.raises(iscab.CabError, match="cut short"):
        cab.read(cab.files[-1])
    with pytest.raises(iscab.CabError, match="cut short"):
        iscab.Cab(io.BytesIO(data[:0x300]))                                         # the file table is not there
    with pytest.raises(iscab.CabError, match="cut short"):
        iscab.Cab(io.BytesIO(data[:0x20]))                                          # not even the header
    with pytest.raises(iscab.CabError, match="not an InstallShield"):
        iscab.Cab(io.BytesIO(b"PK" + b"\0" * 100))


def test_a_cabinet_is_read_out_of_a_disc_image_or_a_folder(tmp_path):
    cab = fakediscs.make_cab(0x01005100, CAB_FILES, True)
    fakediscs.make_iso_tree(str(tmp_path / "d.iso"), {"Setup/data1.cab": cab, "Setup/other.txt": b"x"})
    for disc in (iso9660.open_disc(str(tmp_path / "d.iso")), None):
        if disc is None:
            (tmp_path / "folder" / "Setup").mkdir(parents=True)
            (tmp_path / "folder" / "Setup" / "DATA1.CAB").write_bytes(cab)
            disc = iso9660.open_disc(str(tmp_path / "folder"))
        entry = disc.find("Setup/data1.cab")
        with iscab.open_in_disc(disc, entry) as f:
            c = iscab.Cab(f)
            assert {e[0].replace("\\", "/"): c.read(e) for e in c.files} == CAB_FILES


# ---- the overlay -------------------------------------------------------------------------------------------------------------------------------------------
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
    assert overlay.main(["x", str(base), str(over), str(dest), "--only", "Program"]) == 0
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
    assert overlay.main(["x", str(base), str(over), str(dest)]) == 2


def test_place_keeps_the_spelling_that_is_there_and_says_what_it_did(tmp_path):
    (tmp_path / "Program" / "ShellArt").mkdir(parents=True)
    (tmp_path / "Program" / "CARDS.DAT").write_bytes(b"old")
    assert overlay.place(str(tmp_path), "Program\\cards.dat", b"new") == "replaced"
    assert overlay.place(str(tmp_path), "program/CARDS.dat", b"new") == "identical"
    assert overlay.place(str(tmp_path), "Program\\shellart\\Back.pic", b"x") == "added"
    assert overlay.place(str(tmp_path), "Readme.txt", b"top") == "added"
    assert sorted(os.listdir(tmp_path / "Program")) == ["CARDS.DAT", "ShellArt"] and os.listdir(tmp_path / "Program" / "ShellArt") == ["Back.pic"]
    assert (tmp_path / "Program" / "CARDS.DAT").read_bytes() == b"new"


@pytest.mark.parametrize("rel", ["../evil.txt", "Program/../../evil.txt", "/etc/evil.txt", "\\evil.txt", "C:\\evil.txt", "Program\\..\\..\\evil.txt", "a\0b", "", "."])
def test_place_refuses_a_path_that_could_lead_out(tmp_path, rel):
    dest = tmp_path / "game"
    dest.mkdir()
    with pytest.raises(overlay.OverlayError):
        overlay.place(str(dest), rel, b"x")
    assert os.listdir(dest) == [] and not (tmp_path / "evil.txt").exists()


@needs_symlinks
def test_place_does_not_write_through_a_symbolic_link(tmp_path):
    dest, outside = tmp_path / "game", tmp_path / "outside"
    (dest / "Program").mkdir(parents=True)
    outside.mkdir()
    os.symlink(outside, dest / "Program" / "Link")
    with pytest.raises(overlay.OverlayError, match="symbolic link"):
        overlay.place(str(dest), "Program/Link/evil.txt", b"x")
    (outside / "f").write_bytes(b"precious")
    os.symlink(outside / "f", dest / "Program" / "f")
    with pytest.raises(overlay.OverlayError, match="symbolic link"):
        overlay.place(str(dest), "Program/f", b"x")
    assert os.listdir(outside) == ["f"] and (outside / "f").read_bytes() == b"precious"


# ---- the discs and the patch --------------------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def world(tmp_path, monkeypatch):
    w = fakediscs.World(tmp_path / "src")
    w.register(monkeypatch)
    return w


def test_a_disc_is_told_from_the_other_by_what_is_on_it(world):
    import sotainstall
    first, second = iso9660.open_disc(world.iso1), iso9660.open_disc(world.iso2)
    assert sotainstall.disc_kind(first) == "first" and sotainstall.disc_kind(second) == "expansion"
    sotainstall.check_first_disc(first, "first.iso")
    sotainstall.check_expansion_disc(second, "second.iso")
    assert sotainstall.read_tag(second)["version"] == "2.0"


def test_the_expansion_disc_given_first_says_what_it_is_and_what_is_needed(world):
    import sotainstall
    with pytest.raises(sotainstall.SotaError) as e:
        sotainstall.check_first_disc(iso9660.open_disc(world.iso2), "MTG v2.00.iso")
    text = str(e.value)
    assert "MTG v2.00.iso is the Spells of the Ancients disc (version 2.0), not the original game's" in text
    assert "needs the original game's disc" in text and "--sota" in text and "--patch" in text


def test_the_first_disc_given_as_the_expansion_says_what_it_is(world):
    import sotainstall
    with pytest.raises(sotainstall.SotaError) as e:
        sotainstall.check_expansion_disc(iso9660.open_disc(world.iso1), "MTG v1.0.iso")
    assert "is the original game's disc (version 1.0), not the Spells of the Ancients disc" in str(e.value) and "Setup/data1.cab" in str(e.value)


def test_a_disc_that_is_neither_is_refused_by_both(tmp_path, world):
    import sotainstall
    fakediscs.make_iso_tree(str(tmp_path / "other.iso"), {"Docs/readme.txt": b"hi"}, label="OTHER")
    other = iso9660.open_disc(str(tmp_path / "other.iso"))
    with pytest.raises(sotainstall.SotaError, match="no Setup/data.z"):
        sotainstall.check_first_disc(other, "other.iso")
    with pytest.raises(sotainstall.SotaError, match="no Setup/data1.cab"):
        sotainstall.check_expansion_disc(other, "other.iso")


def test_an_expansion_disc_of_another_version_or_with_a_damaged_cabinet_is_refused(world, tmp_path):
    import sotainstall
    world.write(tag_version="1.5")
    with pytest.raises(sotainstall.SotaError, match="version 1.5"):
        sotainstall.check_expansion_disc(iso9660.open_disc(world.iso2), "d.iso")
    world.write()
    sotainstall.check_expansion_disc(iso9660.open_disc(world.iso2), "d.iso")
    damaged = bytearray(world.cab_bytes)
    damaged[-5] ^= 0xFF                                          # the same size, one byte different
    fakediscs.make_iso_tree(str(tmp_path / "bad.iso"), {"Setup/data1.cab": bytes(damaged), "Setup/_sys1.cab": world.sys_bytes, "Setup/_user1.cab": world.user_bytes,
                                                        "Setup/DATA.TAG": fakediscs.TAG % b"2.0"})
    with pytest.raises(sotainstall.SotaError, match="Setup/data1.cab has SHA-256"):
        sotainstall.check_expansion_disc(iso9660.open_disc(str(tmp_path / "bad.iso")), "bad.iso")
    fakediscs.make_iso_tree(str(tmp_path / "short.iso"), {"Setup/data1.cab": world.cab_bytes[:-100], "Setup/_sys1.cab": world.sys_bytes, "Setup/_user1.cab": world.user_bytes,
                                                         "Setup/DATA.TAG": fakediscs.TAG % b"2.0"})
    with pytest.raises(sotainstall.SotaError, match="cut short, damaged or another release"):
        sotainstall.check_expansion_disc(iso9660.open_disc(str(tmp_path / "short.iso")), "short.iso")
    fakediscs.make_iso_tree(str(tmp_path / "nouser.iso"), {"Setup/data1.cab": world.cab_bytes, "Setup/_sys1.cab": world.sys_bytes, "Setup/DATA.TAG": fakediscs.TAG % b"2.0"})
    with pytest.raises(sotainstall.SotaError, match="lacks Setup/_user1.cab"):
        sotainstall.check_expansion_disc(iso9660.open_disc(str(tmp_path / "nouser.iso")), "nouser.iso")


def test_the_patch_is_read_whole_and_has_the_six_files(world):
    import sotainstall
    got = sotainstall.check_patch(world.patch)
    assert [n for n, _ in got] == ["shandalar.exe", "readme.txt", "magic.exe", "FaceData.txt", "deckdll.dll", "cards.dat"]
    assert dict(got)["cards.dat"] == world.program215["CARDS.DAT"]


def test_a_patch_cut_short_says_how_long_the_whole_one_is(world, tmp_path):
    import sotainstall
    data = world.patch_bytes
    (tmp_path / "sotav215.exe").write_bytes(data[:data.find(b"PK\x01\x02") - 5])
    with pytest.raises(sotainstall.SotaError) as e:
        sotainstall.check_patch(str(tmp_path / "sotav215.exe"))
    text = str(e.value)
    assert "TRUNCATED" in text and "cut short" in text and "Get the patch again" in text and f"{len(world.patch_bytes):,}" in text


def test_a_patch_with_a_damaged_entry_is_refused(world, tmp_path):
    import sotainstall
    data = bytearray(fakediscs.make_patch(world.patch_files, zipfile.ZIP_STORED))
    at = data.find(b"2.15 magic.exe") + 5
    data[at] ^= 0xFF
    (tmp_path / "damaged.exe").write_bytes(bytes(data))
    with pytest.raises(sotainstall.SotaError, match="CORRUPT"):
        sotainstall.check_patch(str(tmp_path / "damaged.exe"))


def test_a_patch_that_is_another_patch_is_refused(world, tmp_path):
    import sotainstall
    (tmp_path / "other.exe").write_bytes(fakediscs.make_patch({"readme.txt": b"another patch", "other.dll": b"x"}))
    with pytest.raises(sotainstall.SotaError) as e:
        sotainstall.check_patch(str(tmp_path / "other.exe"))
    assert "is not the 2.15 patch" in str(e.value) and "lacks" in str(e.value) and "SOTAV215.EXE holds six files" in str(e.value)
    wrong = dict(world.patch_files, **{"shandalar.exe": b"a 2.16 shandalar"})
    (tmp_path / "wrong.exe").write_bytes(fakediscs.make_patch(wrong))
    with pytest.raises(sotainstall.SotaError, match="its shandalar.exe is not the one of Spells of the Ancients 2.15"):
        sotainstall.check_patch(str(tmp_path / "wrong.exe"))
    (tmp_path / "notapatch.exe").write_bytes(b"MZ" + b"\0" * 5000)
    with pytest.raises(sotainstall.SotaError, match="no files in it"):
        sotainstall.check_patch(str(tmp_path / "notapatch.exe"))


# ---- the folder -----------------------------------------------------------------------------------------------------------------------------------------
def install_first_game(world, tmp_path):
    """The first game as install.py leaves it: <tmp>/inst/Magic."""
    import install
    dest = tmp_path / "inst"
    disc = iso9660.open_disc(world.iso1)
    install.extract_archive(disc, str(dest), False)
    install.copy_media(disc, str(dest), False)
    return dest


def tree(root):
    return {os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/"): open(os.path.join(d, f), "rb").read() for d, _s, fs in os.walk(root) for f in fs}


def test_the_folder_is_the_first_game_with_the_cabinet_and_the_patch_over_it(world, tmp_path):
    import sotainstall
    dest = install_first_game(world, tmp_path)
    lines = []
    program = sotainstall.make_folder(str(tmp_path / "inst_sota"), str(dest / "Magic"), iso9660.open_disc(world.iso2), sotainstall.check_patch(world.patch), say=lines.append)
    got = tree(str(tmp_path / "inst_sota" / "Magic"))
    low = {k.lower(): v for k, v in got.items()}
    for name, data in world.program215.items():                                      # every program, library and data file is the 2.15 one
        assert low["program/" + name.lower()] == data, name
    assert low["program/cardart/forest.pic"] == b"a picture"                         # the first game's art stays
    assert low["program/shellart/back.pic"] == b"a new picture"                      # the expansion's new files are there
    assert low["program/decks/starter.dek"] == b"2.0 starter deck"                   # a file in both is the cabinet's
    assert low["program/duelsounds/shell_tooltime.wav"] == b"voice" * 20             # the cabinet's, not the disc's other recording
    assert low["program/sound/new.wav"] == b"a new sound" * 10                       # a CD-side file the first game lacked is added
    assert low["program/sound/locmus0.wav"] == b"music" * 50                         # and one it has is left alone
    assert low["readme.txt"] == b"2.0 readme at the top" and low["microprose.url"].startswith(b"[Internet")        # the cabinet's top-level files
    assert not any("ctl3d32" in k or "bbrd1" in k for k in low)                      # the original installer's own files are not installed
    names = [n.lower() for n in os.listdir(program)]
    assert names.count("cards.dat") == 1 and names.count("readme.txt") == 1 and names.count("deckdll.dll") == 1          # replaced, not doubled, whatever the spelling
    assert sorted(os.listdir(tmp_path / "inst_sota")) == ["Magic"]                   # nothing else is made
    text = "\n".join(lines)
    assert "Setup/data1.cab: " in text and "Setup/_sys1.cab: 2 files" in text and "2.15 patch: 6 files (6 replaced" in text and "all 15 files are the 2.15 ones" in text
    assert sotainstall.problems(program) == []


def test_running_it_again_gives_the_same_folder(world, tmp_path):
    import sotainstall
    dest = install_first_game(world, tmp_path)
    disc, patch = iso9660.open_disc(world.iso2), sotainstall.check_patch(world.patch)
    sotainstall.make_folder(str(tmp_path / "s"), str(dest / "Magic"), disc, patch)
    before = tree(str(tmp_path / "s"))
    (tmp_path / "s" / "Magic" / "Program" / "save.sve").write_bytes(b"a save made by playing")          # what the player added stays
    sotainstall.make_folder(str(tmp_path / "s"), str(dest / "Magic"), disc, patch)
    assert tree(str(tmp_path / "s")) == dict(before, **{"Magic/Program/save.sve": b"a save made by playing"})
    sotainstall.make_folder(str(tmp_path / "s"), str(dest / "Magic"), disc, patch, force=True)
    assert {k: v for k, v in tree(str(tmp_path / "s")).items() if not k.endswith("save.sve")} == before


def test_a_corrupted_program_is_named_and_the_folder_is_refused(world, tmp_path):
    import sotainstall
    dest = install_first_game(world, tmp_path)
    disc, patch = iso9660.open_disc(world.iso2), sotainstall.check_patch(world.patch)
    program = sotainstall.make_folder(str(tmp_path / "s"), str(dest / "Magic"), disc, patch)
    assert sotainstall.problems(program) == []
    path = os.path.join(program, "shandalar.exe")
    data = bytearray(open(path, "rb").read())
    data[10] ^= 0x01                                                                 # one bit
    open(path, "wb").write(bytes(data))
    assert sotainstall.problems(program) == ["shandalar.exe is not the 2.15 file (SHA-256 " + sotainstall.builds.file_build_id(path)[:16] + "... where 2.15's starts "
                                             + world.known()[3 + 0][2][:16] + ")"]
    open(path, "ab").write(b"x")                                                     # and a file of the wrong length
    assert "shandalar.exe is " in sotainstall.problems(program)[0] and "bytes where 2.15's is" in sotainstall.problems(program)[0]
    os.remove(os.path.join(program, "CdTools.dll"))
    assert "CdTools.dll is missing" in sotainstall.problems(program)
    with pytest.raises(sotainstall.SotaError) as e:                                  # making the folder again from the same sources repairs it
        bad_patch = [(n, d if n != "magic.exe" else b"X" * len(d)) for n, d in patch]
        sotainstall.make_folder(str(tmp_path / "t"), str(dest / "Magic"), disc, bad_patch)
    assert "not Spells of the Ancients 2.15" in str(e.value) and "magic.exe is not the 2.15 file" in str(e.value)
    sotainstall.make_folder(str(tmp_path / "s"), str(dest / "Magic"), disc, patch)
    assert sotainstall.problems(program) == []


def test_a_cabinet_with_a_path_out_of_the_folder_writes_nothing_outside(world, tmp_path):
    import sotainstall
    dest = install_first_game(world, tmp_path)
    evil = fakediscs.make_cab(0x01005100, {"Program/../../evil.txt": b"x", **{"Program/" + n: d for n, d in world.program20.items()}}, True)
    world.cab_bytes = evil
    fakediscs.make_iso_tree(str(tmp_path / "evil.iso"), {"Setup/data1.cab": evil, "Setup/_sys1.cab": world.sys_bytes, "Setup/_user1.cab": world.user_bytes,
                                                        "Setup/DATA.TAG": fakediscs.TAG % b"2.0"})
    import builds
    builds.SOTA_DISC["cabinets"]["data1.cab"] = (len(evil), fakediscs.sha(evil))
    disc = iso9660.open_disc(str(tmp_path / "evil.iso"))
    sotainstall.check_expansion_disc(disc, "evil.iso")
    with pytest.raises(sotainstall.SotaError, match="not a path inside the game's folder"):
        sotainstall.make_folder(str(tmp_path / "s"), str(dest / "Magic"), disc, sotainstall.check_patch(world.patch))
    assert not (tmp_path / "evil.txt").exists() and not (tmp_path / "s" / "evil.txt").exists()


@needs_symlinks
def test_the_folder_is_not_written_through_a_symbolic_link(world, tmp_path):
    import sotainstall
    dest = install_first_game(world, tmp_path)
    (tmp_path / "elsewhere").mkdir()
    os.symlink(tmp_path / "elsewhere", tmp_path / "link")
    with pytest.raises(sotainstall.SotaError, match="symbolic link"):
        sotainstall.make_folder(str(tmp_path / "link"), str(dest / "Magic"), iso9660.open_disc(world.iso2), sotainstall.check_patch(world.patch))
    assert os.listdir(tmp_path / "elsewhere") == []


def test_the_real_table_of_known_files_is_the_2_15_set():
    import builds
    known = {n.lower(): (sha, role) for b, n, sha, role in builds.KNOWN if b == "v2.15"}
    assert len(known) == 15 and set(builds.SIZES) == {s for s, _ in known.values()}              # every 2.15 file has a hash and a size
    assert {n.lower() for n in builds.SOTA_PATCH["files"]} <= set(known)                          # the patch's six are all known by hash
    assert [n for n, (_s, role) in known.items() if role == "lifted"] == [n.lower() for n in ("shandalar.exe", "FaceMaker.exe", "DECK.EXE", "deckdll.dll", "cardartlib.dll", "drawcardlib.dll",
                                                                                                "CdTools.dll", "STATWIN.DLL")]
    assert builds.SOTA_PATCH["size"] == 1207571 and set(builds.SOTA_DISC["cabinets"]) == {"data1.cab", "_sys1.cab", "_user1.cab"}


# ---- the whole command, with fakes ----------------------------------------------------------------------------------------------------------------------
class Recorder:
    """What install.main did after the files were made: the lifter and the module build are replaced by calls that write down their arguments."""

    def __init__(self):
        self.calls = []


@pytest.fixture
def command(world, tmp_path, monkeypatch, capsys):
    """install.main() on the fake discs, in a fake release folder (no Makefile: the modules are built by modbuild), with the lifter and the compiler replaced by recorders."""
    import install
    import liftrun
    import modbuild
    root = tmp_path / "release"
    (root / "tools").mkdir(parents=True)
    rec = Recorder()
    layout = install.Layout(str(root))
    monkeypatch.setattr(install, "ROOT", str(root))
    monkeypatch.setattr(install, "Layout", lambda: layout)
    monkeypatch.setattr(install, "ensure_python_deps", lambda layout, allow_pip=True, assume=None: [])
    monkeypatch.setattr(liftrun, "lift_all", lambda root, python, paths, **kw: rec.calls.append(("lift_all", kw.get("force"))))
    monkeypatch.setattr(liftrun, "lift_sota", lambda root, game, python, paths, **kw: rec.calls.append(("lift_sota", game, kw.get("force"))))

    class Compiler:
        def describe(self):
            return "a fake compiler"

    monkeypatch.setattr(modbuild, "find_compiler", lambda *a, **kw: Compiler())
    monkeypatch.setattr(modbuild, "build_modules", lambda programs, gen, port, native, objs, out, cc, **kw: rec.calls.append(("build", list(programs))) or {p: os.path.join(out, "game_%s.so" % p) for p in programs})
    monkeypatch.setattr(modbuild, "smoke_test", lambda run, module: (True, ""))
    monkeypatch.setattr(install, "link_install_folder", lambda dest: None)
    (root / "pentamoor-run").write_text("")              # a runtime beside the launchers: a release

    def run(*args):
        capsys.readouterr()
        install.main([str(a) for a in args], default_build=True)
        return capsys.readouterr().out

    run.rec, run.root, run.install = rec, root, install
    return run


def test_one_command_installs_both_games_and_builds_all_six_modules(world, command, tmp_path):
    out = command(world.iso1, "--sota", world.iso2, "--patch", world.patch, "--dest", tmp_path / "inst")
    sota = tmp_path / "inst_sota" / "Magic" / "Program"
    assert (tmp_path / "inst" / "Magic" / "Program" / "MAGIC.EXE").exists()
    want = {n.lower(): d for n, d in world.program215.items()}                                       # (the names keep the spelling the first game gave them)
    assert {n.lower(): open(os.path.join(sota, n), "rb").read() for n in os.listdir(sota) if n.lower() in want} == want
    # what it said, in the order it did it: the sources are checked first, then the first game, then the 2.15 folder, then the lifts and the build
    order = [out.index(s) for s in ("expansion disc: ", "patch: SOTAV215.EXE, 6 files", "disc: MTG v1.0", "game files: ", "programs: all 3 are build v1.0", "Spells of the Ancients 2.15 into ",
                                    "2.15 patch: 6 files", "all 15 files are the 2.15 ones", "Spells of the Ancients 2.15 installed (", "compiler: a fake compiler", "built. Play with:  ")]
    assert order == sorted(order)
    assert "Spells of the Ancients 2.15:  PENTAMOOR_SOTA=" in out and str(sota) in out and out.rstrip().endswith("sota")
    assert command.rec.calls == [("lift_all", False), ("lift_sota", str(sota), False), ("build", ["magic", "deck", "duel", "shandalar", "facemaker", "sotadeck"])]
    assert not any(p.name.lower() in ("software", "registry") for p in tmp_path.rglob("*"))                      # nothing like a registry is written


def test_the_first_game_alone_is_installed_and_built_as_before(world, command, tmp_path):
    out = command(world.iso1, "--dest", tmp_path / "inst")
    assert not (tmp_path / "inst_sota").exists()
    assert command.rec.calls == [("lift_all", False), ("build", ["magic", "deck", "duel"])]
    assert "Spells of the Ancients 2.15 too: add --sota" in out and "built. Play with:  " in out


def test_an_existing_2_15_folder_is_built_again_without_any_source(world, command, tmp_path):
    command(world.iso1, "--sota", world.iso2, "--patch", world.patch, "--dest", tmp_path / "inst")
    command.rec.calls.clear()
    out = command("--dest", tmp_path / "inst")                      # no disc, no patch: what is there is checked and built
    assert "not reading the disc again" in out and "is installed in" in out and "all files verified" in out
    assert [c[0] for c in command.rec.calls] == ["lift_all", "lift_sota", "build"] and command.rec.calls[-1][1][-3:] == ["shandalar", "facemaker", "sotadeck"]
    shutil_rm = tmp_path / "inst_sota" / "Magic" / "Program" / "shandalar.exe"
    shutil_rm.write_bytes(b"corrupted")                              # a corrupted copy is not built: the 1.0 modules are, and it says so by leaving 2.15 out
    command.rec.calls.clear()
    out = command("--dest", tmp_path / "inst")
    assert "Spells of the Ancients 2.15 is installed in" not in out and command.rec.calls == [("lift_all", False), ("build", ["magic", "deck", "duel"])]


def test_the_second_game_goes_in_the_folder_asked_for(world, command, tmp_path):
    out = command(world.iso1, "--sota", world.iso2, "--patch", world.patch, "--dest", tmp_path / "inst", "--sota-dest", tmp_path / "somewhere" / "sotagame")
    assert (tmp_path / "somewhere" / "sotagame" / "Magic" / "Program" / "shandalar.exe").exists() and not (tmp_path / "inst_sota").exists()
    assert str(tmp_path / "somewhere" / "sotagame" / "Magic" / "Program") in command.rec.calls[1][1]
    assert "PENTAMOOR_SOTA=" + str(tmp_path / "somewhere") in out


def refused(command, *args):
    with pytest.raises(SystemExit) as e:
        command(*args)
    return str(e.value)


def test_the_second_game_cannot_go_into_the_first_games_folder(world, command, tmp_path):
    for sota_dest in (tmp_path / "inst", tmp_path / "inst" / "inside", tmp_path):
        text = refused(command, world.iso1, "--sota", world.iso2, "--patch", world.patch, "--dest", tmp_path / "inst", "--sota-dest", sota_dest)
        assert "needs a folder of its own" in text
    assert not (tmp_path / "inst").exists() and command.rec.calls == []


def test_each_missing_source_is_named_and_nothing_is_written(world, command, tmp_path):
    inst = tmp_path / "inst"
    text = refused(command, world.iso1, "--sota", world.iso2, "--dest", inst)
    assert text.startswith("install: Spells of the Ancients 2.15 needs the patch as well as the expansion's disc") and "--patch is missing" in text and "SOTAV215.EXE" in text
    assert f'pentamoor-install {world.iso1} --sota {world.iso2} --patch "path/to/SOTAV215.EXE"'.replace(world.iso1, '"%s"' % world.iso1).replace(world.iso2, '"%s"' % world.iso2) in text
    text = refused(command, world.iso1, "--patch", world.patch, "--dest", inst)
    assert "the patch is given, but not the expansion's disc" in text and "--sota is missing" in text and "MTG v2.00.iso" in text
    text = refused(command, world.iso1, "--sota", tmp_path / "nothere.iso", "--patch", world.patch, "--dest", inst)
    assert "the expansion's disc (--sota)" in text and "does not exist" in text
    text = refused(command, world.iso1, "--sota", world.iso2, "--patch", tmp_path / "nothere.exe", "--dest", inst)
    assert "the patch (--patch)" in text and "does not exist" in text
    assert not inst.exists() and not (tmp_path / "inst_sota").exists() and command.rec.calls == []


def test_the_discs_in_the_wrong_places_stop_it_before_anything_is_written(world, command, tmp_path):
    inst = tmp_path / "inst"
    text = refused(command, world.iso2, "--sota", world.iso1, "--patch", world.patch, "--dest", inst)         # the expansion first
    assert "is the Spells of the Ancients disc (version 2.0), not the original game's" in text and "needs the original game's disc" in text
    text = refused(command, world.iso2, "--dest", inst)                                                        # the expansion alone, as a first game
    assert "not the original game's" in text and "--sota" in text
    text = refused(command, world.iso1, "--sota", world.iso1, "--patch", world.patch, "--dest", inst)         # the first game as the expansion
    assert "is the original game's disc (version 1.0), not the Spells of the Ancients disc" in text
    assert not inst.exists() and command.rec.calls == []


def test_a_cut_short_or_other_patch_stops_it_before_the_first_game_is_unpacked(world, command, tmp_path):
    inst = tmp_path / "inst"
    data = world.patch_bytes
    cut = tmp_path / "cut.exe"
    cut.write_bytes(data[:data.find(b"PK\x01\x02") - 5])
    text = refused(command, world.iso1, "--sota", world.iso2, "--patch", cut, "--dest", inst)
    assert "TRUNCATED" in text and "cut short" in text and "Get the patch again" in text
    other = tmp_path / "other.exe"
    other.write_bytes(fakediscs.make_patch({"readme.txt": b"another patch"}))
    text = refused(command, world.iso1, "--sota", world.iso2, "--patch", other, "--dest", inst)
    assert "is not the 2.15 patch" in text
    assert not inst.exists() and command.rec.calls == []


def test_a_first_game_that_is_not_the_retail_disc_is_not_built_over(world, command, tmp_path, monkeypatch):
    import builds
    inst = tmp_path / "inst"
    # the extracted game does not match the build the port knows: the 2.15 folder is not made from it
    other = [r for r in builds.KNOWN if not (r[0] == "v1.0" and r[1] == "MAGIC.EXE")] + [("v1.0", "MAGIC.EXE", "0" * 64, "lifted")]
    monkeypatch.setattr(builds, "KNOWN", other)
    monkeypatch.setattr(command.install, "FINGERPRINTS", builds.fingerprints("v1.0"))
    text = refused(command, world.iso1, "--sota", world.iso2, "--patch", world.patch, "--dest", inst)
    assert "not made from them" in text and not (tmp_path / "inst_sota").exists()


def test_the_checkout_builds_all_modules_with_one_make(world, tmp_path, monkeypatch, capsys):
    """In a checkout (a Makefile): the lifts run, then the one `make all`, which builds the six modules."""
    import install
    import liftrun
    root = tmp_path / "checkout"
    (root / "src" / "port").mkdir(parents=True)
    (root / "src" / "port" / "Makefile").write_text("")
    layout = install.Layout(str(root))
    calls = []
    monkeypatch.setattr(install, "ROOT", str(root))
    monkeypatch.setattr(install, "Layout", lambda: layout)
    monkeypatch.setattr(install, "ensure_python_deps", lambda layout, allow_pip=True, assume=None: [])
    monkeypatch.setattr(install, "link_install_folder", lambda dest: None)
    monkeypatch.setattr(liftrun, "lift_all", lambda *a, **kw: calls.append("lift_all"))
    monkeypatch.setattr(liftrun, "lift_sota", lambda root, game, *a, **kw: calls.append("lift_sota"))
    monkeypatch.setattr(install.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(install.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or types.SimpleNamespace(returncode=0))
    install.main([world.iso1, "--sota", world.iso2, "--patch", world.patch, "--dest", str(tmp_path / "inst"), "--build"])
    out = capsys.readouterr().out
    assert calls[:2] == ["lift_all", "lift_sota"] and calls[2][0] == "make" and calls[2][-1] == "all" and len(calls) == 3
    assert "game_shandalar, game_facemaker, game_sotadeck" in out


def test_check_says_whether_2_15_is_installed(world, command, tmp_path, capsys):
    import types as t
    install = command.install
    args = t.SimpleNamespace(compiler=None, sota_dest=None)
    assert install.check(install.Layout(), args) in (0, 1)
    assert "sota:   Spells of the Ancients 2.15 not installed" in capsys.readouterr().out
    args.sota_dest = str(tmp_path / "inst_sota")
    command(world.iso1, "--sota", world.iso2, "--patch", world.patch, "--dest", tmp_path / "inst")
    install.check(install.Layout(), args)
    assert "sota:   Spells of the Ancients 2.15 installed in " + str(tmp_path / "inst_sota" / "Magic" / "Program") in capsys.readouterr().out

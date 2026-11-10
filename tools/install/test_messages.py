"""What the installer says to a person who gave it the wrong thing, or whose machine cannot hold the install (docs/notes/rc2-audit.md): a message that says what the file is and what to do,
not a Python traceback.   python3 -m pytest tools/install/test_messages.py"""
import errno
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fakediscs  # noqa: E402
import iso9660  # noqa: E402
from test_install import make_iso  # noqa: E402
from test_sota import command, refused, world  # noqa: E402,F401  (fixtures)


def tell_size(path, sectors):
    """Make the image say it is `sectors` sectors long (the Primary Volume Descriptor's volume space size, as a real disc image has it)."""
    with open(path, "r+b") as f:
        f.seek(16 * 2048 + 80)
        f.write(struct.pack("<I", sectors) + struct.pack(">I", sectors))


# ---- files that are not a disc image ----------------------------------------------------------------------------------------------------------------------
def message_for(path):
    with pytest.raises(iso9660.IsoError) as e:
        iso9660.open_disc(str(path))
    return str(e.value)


def test_a_raw_mdf_is_told_how_to_convert_it(tmp_path):
    p = tmp_path / "MTG v1.0.mdf"
    p.write_bytes(b"\0" * 40000)
    text = message_for(p)
    assert "raw .mdf" in text and 'mdf2iso "MTG v1.0.mdf" "MTG v1.0.iso"' in text and "brew install mdf2iso" in text


def test_a_program_given_as_the_disc_is_named_a_program(tmp_path):
    p = tmp_path / "SOTAV215.EXE"
    p.write_bytes(b"MZ" + b"\0" * 40000)
    text = message_for(p)
    assert "SOTAV215.EXE is a Windows program" in text and "--patch" in text


def test_an_archive_given_as_the_disc_is_named_an_archive(tmp_path):
    for name, head in (("disc.zip", b"PK\x03\x04"), ("disc.iso", b"\x1f\x8b\x08\x00"), ("disc.rar", b"Rar!\x1a\x07")):
        p = tmp_path / name
        p.write_bytes(head + b"\0" * 40000)
        assert "compressed archive" in message_for(p) and "Unpack it" in message_for(p)


def test_any_other_file_says_what_an_iso_is(tmp_path):
    p = tmp_path / "notes.iso"
    p.write_bytes(b"this is not a disc\n" * 3000)
    text = message_for(p)
    assert "is not an ISO 9660 image" in text and ".bin/.cue" in text
    q = tmp_path / "empty.iso"
    q.write_bytes(b"")
    assert "is not an ISO 9660 image" in message_for(q)


# ---- a disc image that is cut short ------------------------------------------------------------------------------------------------------------------------
def test_a_cut_short_image_says_so_instead_of_failing_inside_the_archive(tmp_path):
    p = tmp_path / "MTG v1.0.iso"
    make_iso(str(p), {"data.z": b"Z" * 5000})
    size = os.path.getsize(p)
    tell_size(p, size // 2048 + 100)                                           # the image says it is 100 sectors longer than the file
    text = message_for(p)
    assert "is cut short" in text and f"{size:,}" in text and f"{size + 100 * 2048:,}" in text and "Get the disc image again" in text


def test_a_whole_image_and_one_that_does_not_say_its_size_are_read(tmp_path):
    p = tmp_path / "a.iso"
    make_iso(str(p), {"data.z": b"Z" * 5000})
    assert iso9660.open_disc(str(p)).find("data.z") is not None                # (no size in the descriptor: nothing to compare)
    tell_size(p, os.path.getsize(p) // 2048)
    assert iso9660.open_disc(str(p)).find("data.z") is not None                # the size it says is the size it is


# ---- a disc of something else ------------------------------------------------------------------------------------------------------------------------------
def test_another_installshield_disc_is_not_called_the_expansion(tmp_path):
    """Another game's disc that has a Setup/data1.cab (it is an InstallShield disc) but not the expansion's tag was told it was the Spells of the Ancients disc."""
    import sotainstall
    fakediscs.make_iso_tree(str(tmp_path / "other.iso"), {"Setup/data1.cab": b"x" * 100, "Autorun.exe": b"MZ"}, label="MAGIC")
    disc = iso9660.open_disc(str(tmp_path / "other.iso"))
    with pytest.raises(sotainstall.SotaError) as e:
        sotainstall.check_first_disc(disc, "Magic The Gathering 2010 Edition.iso")
    text = str(e.value)
    assert "Spells of the Ancients disc" not in text
    assert "does not look like the Magic: The Gathering disc, version 1.0" in text and "'MAGIC'" in text and "another game or another version" in text


def test_the_expansion_disc_is_still_told_as_such(world):
    import sotainstall
    with pytest.raises(sotainstall.SotaError, match="is the Spells of the Ancients disc"):
        sotainstall.check_first_disc(iso9660.open_disc(world.iso2), "MTG v2.00.iso")


# ---- a machine that cannot hold the install ----------------------------------------------------------------------------------------------------------------
def test_a_full_disk_and_a_folder_that_cannot_be_written_are_explained():
    import install
    full = install.os_error_message(OSError(errno.ENOSPC, "No space left on device", "/x/sources/installed/Magic/Program/MAGIC.EXE"))
    assert "the disk is full" in full and "/x/sources/installed" in full and "free space" in full and "run the same command again" in full
    ro = install.os_error_message(PermissionError(errno.EACCES, "Permission denied", "/Volumes/Pentamoor/sources"))
    assert "cannot write (/Volumes/Pentamoor/sources): permission denied" in ro and "home folder" in ro
    assert "cannot write (/Volumes/d): read-only file system" in install.os_error_message(OSError(errno.EROFS, "Read-only file system", "/Volumes/d"))
    other = install.os_error_message(OSError(errno.EIO, "Input/output error", "/x/disc.iso"))
    assert other == "Input/output error (/x/disc.iso)"


def test_an_oserror_in_the_middle_of_it_ends_with_a_message_not_a_traceback(monkeypatch):
    import install

    def boom(argv=None, default_build=False):
        raise OSError(errno.ENOSPC, "No space left on device", "/x/y")
    monkeypatch.setattr(install, "run", boom)
    with pytest.raises(SystemExit) as e:
        install.main([])
    assert str(e.value).startswith("install: the disk is full (/x/y)")


@pytest.mark.skipif(sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="needs a folder this user cannot write")
def test_a_folder_that_cannot_be_written_stops_it_before_the_disc_is_read(world, command, tmp_path):
    """A release unpacked where it cannot be written (a read-only disk, a system folder) was found out after the disc's archive had been read, with a traceback."""
    release = tmp_path / "release"
    os.chmod(release, 0o555)
    try:
        text = refused(command, world.iso1, "--dest", release / "sources" / "installed")
    finally:
        os.chmod(release, 0o755)
    assert text.startswith("install: cannot write") and str(release) in text and "home folder" in text
    assert command.rec.calls == []


# ---- an install that was stopped half way ------------------------------------------------------------------------------------------------------------------
def test_an_install_stopped_half_way_is_not_taken_for_a_whole_one(world, command, tmp_path):
    """MAGIC.EXE is one of the first files written. An install stopped after it (Ctrl-C, a full disk) was found 'already extracted' by the next run, which built from the part that was there."""
    inst = tmp_path / "inst"
    program = inst / "Magic" / "Program"
    program.mkdir(parents=True)
    (program / "MAGIC.EXE").write_bytes(b"MZ")
    with pytest.raises(SystemExit) as e:
        command("--dest", inst)                                                  # no disc given, and nobody to ask
    assert "no disc image given" in str(e.value)
    assert command.rec.calls == []


def test_the_disc_given_again_finishes_it_and_a_whole_install_is_then_taken_as_whole(world, command, tmp_path):
    inst = tmp_path / "inst"
    program = inst / "Magic" / "Program"
    program.mkdir(parents=True)
    (program / "MAGIC.EXE").write_bytes(b"MZ")
    out = command(world.iso1, "--dest", inst)
    assert "game files: " in out and (inst / "Magic" / ".pentamoor-extracted").exists()
    command.rec.calls.clear()
    out = command("--dest", inst)
    assert "not reading the disc again" in out and "only partly" not in out


def test_an_install_from_before_the_marker_is_whole_when_it_has_all_the_retail_files(tmp_path, capsys):
    import install
    program = tmp_path / "Magic" / "Program"
    program.mkdir(parents=True)
    for i in range(install.RETAIL_FILES - 1):
        (program / f"f{i}").write_bytes(b"")
    assert not install.extraction_complete(str(tmp_path))
    (program / "last").write_bytes(b"")
    assert install.extraction_complete(str(tmp_path))


# ---- no C compiler -----------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("system, hint", [("darwin", "xcode-select --install"), ("linux", "sudo apt install gcc"), ("windows", "MSYS2")])
def test_no_compiler_says_how_to_get_one_on_this_system(monkeypatch, tmp_path, system, hint):
    import modbuild
    monkeypatch.setattr(modbuild, "host_os", lambda: system)
    monkeypatch.setattr(modbuild.zigdl, "wheel_for", lambda: ("p", 92 << 20, "sha"))
    with pytest.raises(modbuild.BuildError) as e:                                   # the download refused
        modbuild.get_zig(str(tmp_path), True, lambda q: False, lambda m: None, None)
    assert "was not agreed to" in str(e.value) and hint in str(e.value) and "--yes" in str(e.value)
    with pytest.raises(modbuild.BuildError) as e:                                   # --no-download
        modbuild.get_zig(str(tmp_path), False, None, lambda m: None, None)
    assert "--no-download" in str(e.value) and hint in str(e.value)


def test_a_question_with_nobody_to_ask_says_so(monkeypatch, capsys):
    import install
    monkeypatch.setattr(sys, "stdin", None)
    assert install.ask_yes("Download the Zig compiler?") is False
    out = capsys.readouterr().out
    assert "Download the Zig compiler? -> no" in out and "no terminal to ask on" in out and "--yes" in out
    assert install.ask_yes("Download?", assume=True) is True and capsys.readouterr().out == ""

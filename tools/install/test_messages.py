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


# ---- a file that is not the patch --------------------------------------------------------------------------------------------------------------------------
def test_a_text_file_given_as_the_patch_is_not_said_to_be_cut_short(tmp_path):
    """The readme that comes with the patch (sotav215.txt, 2 KB) is smaller than the patch: it was called 'cut short'."""
    import sotainstall
    p = tmp_path / "sotav215.txt"
    p.write_bytes(b"Magic: The Gathering patch notes\r\n" * 60)
    with pytest.raises(sotainstall.SotaError) as e:
        sotainstall.check_patch(str(p))
    assert "cut short" not in str(e.value) and "--patch wants SOTAV215.EXE" in str(e.value)


def test_a_program_that_is_the_patch_cut_short_still_is(world, tmp_path):
    import sotainstall
    data = world.patch_bytes
    (tmp_path / "sotav215.exe").write_bytes(data[:data.find(b"PK\x01\x02") - 5])
    with pytest.raises(sotainstall.SotaError, match="cut short"):
        sotainstall.check_patch(str(tmp_path / "sotav215.exe"))


def test_the_expansion_disc_given_where_the_patch_goes_and_the_other_way_round(tmp_path, world):
    """--sota and --patch swapped: the patch is a program, not a disc image (and says which option it belongs to)."""
    import sotainstall
    with pytest.raises(iso9660.IsoError, match="Windows program"):
        iso9660.open_disc(world.patch)
    with pytest.raises(sotainstall.SotaError, match="no files"):
        sotainstall.check_patch(world.iso2)


# ---- a download that macOS has marked (quarantine) ---------------------------------------------------------------------------------------------------------
def release_folder(tmp_path):
    import install
    root = tmp_path / "rel"
    (root / "tools").mkdir(parents=True)
    (root / ("pentamoor-run" + install.EXE)).write_bytes(b"\xcf\xfa\xed\xfe")             # (pentamoor-run.exe on Windows, where this test runs with the platform faked)
    return install.Layout(str(root))


def test_the_quarantine_mark_on_the_runtime_is_found_and_explained(tmp_path, monkeypatch):
    import install
    layout = release_folder(tmp_path)

    class Done:
        def __init__(self, out):
            self.stdout = out

    def fails(*a, **kw):
        raise OSError("no ls")

    monkeypatch.setattr(sys, "platform", "darwin")
    marked = "-rwxr-xr-x@ 1 me  staff  1234 Nov  9 23:00 pentamoor-run\n\tcom.apple.quarantine\t  57 \n"
    clean = "-rwxr-xr-x  1 me  staff  1234 Nov  9 23:00 pentamoor-run\n"
    assert install.quarantined(layout, runner=lambda *a, **kw: Done(marked)) is True
    assert install.quarantined(layout, runner=lambda *a, **kw: Done(clean)) is False
    assert install.quarantined(layout, runner=fails) is False
    monkeypatch.setattr(sys, "platform", "linux")
    assert install.quarantined(layout, runner=lambda *a, **kw: Done(marked)) is False                 # only a Mac has the mark
    assert "xattr -dr com.apple.quarantine ." in install.QUARANTINE_MESSAGE and "not signed" in install.QUARANTINE_MESSAGE


@pytest.mark.skipif(sys.platform != "darwin", reason="com.apple.quarantine is a macOS attribute")
def test_the_installer_and_the_launcher_stop_on_a_marked_download_with_the_command_that_clears_it(tmp_path):
    import shutil
    import subprocess
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    rel = tmp_path / "rel"
    (rel / "tools" / "install").mkdir(parents=True)
    for name in os.listdir(os.path.join(root, "tools", "install")):
        if name.endswith(".py") and not name.startswith("test_"):
            shutil.copy(os.path.join(root, "tools", "install", name), rel / "tools" / "install" / name)
    shutil.copytree(os.path.join(root, "tools", "lift"), rel / "tools" / "lift", ignore=shutil.ignore_patterns("__pycache__", "test_*"))
    for name in ("pentamoor-install", "pentamoor"):
        shutil.copy(os.path.join(root, name), rel / name)
    (rel / "pentamoor-run").write_bytes(b"\xcf\xfa\xed\xfe")
    mark = ["xattr", "-w", "com.apple.quarantine", "0083;5f000000;Safari;", str(rel / "pentamoor-run")]
    if subprocess.run(mark, capture_output=True).returncode != 0:
        pytest.skip("cannot set the attribute here")
    r = subprocess.run([sys.executable, str(rel / "pentamoor-install"), "--check"], capture_output=True, text=True, cwd=rel, timeout=120)
    assert r.returncode == 1 and r.stderr.startswith("install: macOS has marked these files") and "xattr -dr com.apple.quarantine ." in r.stderr
    r = subprocess.run(["sh", str(rel / "pentamoor")], capture_output=True, text=True, cwd=rel, timeout=120, stdin=subprocess.DEVNULL)
    assert r.returncode == 1 and r.stderr.startswith("pentamoor: macOS has marked these files") and "xattr -dr com.apple.quarantine ." in r.stderr
    subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(rel)], check=True)                    # what the message says to do
    r = subprocess.run(["sh", str(rel / "pentamoor")], capture_output=True, text=True, cwd=rel, timeout=120, stdin=subprocess.DEVNULL)
    assert "macOS has marked" not in r.stderr and "the game is not installed" in r.stderr


# ---- the wrong file at the prompt ----------------------------------------------------------------------------------------------------------------------------
def test_a_wrong_file_typed_at_the_prompt_asks_again_instead_of_ending(world, command, tmp_path, monkeypatch, capsys):
    """Someone who drags the wrong file onto the terminal was sent back to the beginning (the launcher's Install it now? question); the prompt asks again."""
    import install

    class Terminal:
        def isatty(self):
            return True

    bad = tmp_path / "notes.iso"
    bad.write_bytes(b"not a disc\n" * 1000)
    answers = iter([str(bad), world.iso2, world.iso1])                         # a text file, the expansion's disc, then the right one
    monkeypatch.setattr(sys, "stdin", Terminal())
    monkeypatch.setattr(install, "ask_disc", lambda: next(answers))
    out = command("--dest", tmp_path / "inst")
    assert out.count("Try another file, or leave it empty to cancel.") == 2
    assert "is not an ISO 9660 image" in out and "is the Spells of the Ancients disc" in out
    assert "game files: " in out and (tmp_path / "inst" / "Magic" / ".pentamoor-extracted").exists()


def test_a_wrong_file_given_on_the_command_line_ends_it(world, command, tmp_path):
    bad = tmp_path / "notes.iso"
    bad.write_bytes(b"not a disc\n" * 1000)
    text = refused(command, bad, "--dest", tmp_path / "inst")
    assert "is not an ISO 9660 image" in text


# ---- little free disk space, Ctrl-C ------------------------------------------------------------------------------------------------------------------------
def test_too_little_free_space_is_said_at_the_start(tmp_path):
    import install
    mb = 1 << 20
    with pytest.raises(SystemExit) as e:
        install.check_space(str(tmp_path / "sources" / "installed"), False, free_bytes=300 * mb)
    text = str(e.value)
    assert text.startswith("install: there is not enough free disk space") and "650 MB" in text and "300 MB is free" in text and str(tmp_path) in text
    with pytest.raises(SystemExit) as e:
        install.check_space(str(tmp_path), True, free_bytes=900 * mb)
    assert "1150 MB (with Spells of the Ancients 2.15)" in str(e.value) and "900 MB is free" in str(e.value)
    install.check_space(str(tmp_path), False, free_bytes=700 * mb)                      # room enough: nothing said
    install.check_space(str(tmp_path), True, have_bytes=500 * mb, free_bytes=700 * mb)  # what an earlier install already holds does not need room again


def test_the_install_checks_the_space_before_it_reads_the_disc(world, command, tmp_path, monkeypatch):
    import install
    monkeypatch.setattr(install.shutil, "disk_usage", lambda p: type("U", (), {"free": 100 << 20})())
    text = refused(command, world.iso1, "--dest", tmp_path / "inst")
    assert "not enough free disk space" in text and "100 MB is free" in text
    assert not (tmp_path / "inst").exists() and command.rec.calls == []


def test_the_measured_sizes_are_what_the_messages_say():
    import install
    assert install.NEED_MB == {False: 650, True: 1150}
    assert "650 MB" in install.os_error_message(OSError(errno.ENOSPC, "No space left on device", "/x")) and "1150 MB" in install.os_error_message(OSError(errno.ENOSPC, "No space left", "/x"))


def test_ctrl_c_says_how_to_carry_on(monkeypatch):
    import install

    def stopped(argv=None, default_build=False):
        raise KeyboardInterrupt
    monkeypatch.setattr(install, "run", stopped)
    with pytest.raises(SystemExit) as e:
        install.main([])
    assert "install: stopped. Run the same command again to carry on" in str(e.value)


# ---- the launcher ------------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.skipif(sys.platform == "win32", reason="./pentamoor is a shell script")
def test_a_mistyped_iso_path_is_said_not_passed_on_to_the_game(tmp_path):
    import shutil
    import subprocess
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    shutil.copy(os.path.join(root, "pentamoor"), tmp_path / "pentamoor")
    r = subprocess.run(["sh", str(tmp_path / "pentamoor"), "MTG v1.0.iso"], capture_output=True, text=True, cwd=tmp_path, stdin=subprocess.DEVNULL)
    assert r.returncode == 1 and r.stderr.startswith("pentamoor: MTG v1.0.iso is not a file") and "drag the .iso file" in r.stderr
    assert "the game is not installed" not in r.stderr                                  # (it was: the name went on to the game as an argument)
    r = subprocess.run(["sh", str(tmp_path / "pentamoor")], capture_output=True, text=True, cwd=tmp_path, stdin=subprocess.DEVNULL)
    assert "the game is not installed" in r.stderr                                      # no argument: as before

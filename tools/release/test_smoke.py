"""Tests of the archive smoke test's own parts (smoke_archive.py, smoke_install.py): no game file, no archive, no network.   python3 -m pytest tools/release"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

import smoke_archive  # noqa: E402
import smoke_install  # noqa: E402


def test_the_stub_program_is_the_one_the_runtime_checks_name():
    assert hashlib.sha256(smoke_archive.make_stub_pe()).hexdigest() == smoke_archive.STUB_SHA


def test_the_stub_program_is_what_mkpe_writes(tmp_path):
    cc = shutil.which("cc") or shutil.which("gcc")
    if not cc:
        pytest.skip("no C compiler")
    mkpe = tmp_path / ("mkpe.exe" if os.name == "nt" else "mkpe")
    subprocess.run([cc, "-O1", "-o", str(mkpe), os.path.join(ROOT, "src", "port", "stubgame", "mkpe.c")], check=True)
    out = tmp_path / "stub.exe"
    subprocess.run([str(mkpe), str(out)], check=True)
    assert out.read_bytes() == smoke_archive.make_stub_pe()


def test_the_makefile_names_the_same_build():
    with open(os.path.join(ROOT, "src", "port", "Makefile"), encoding="utf-8") as f:
        assert smoke_archive.STUB_SHA in f.read()


def test_the_made_up_discs_are_made_without_pytest_and_the_table_holds_the_three_programs(tmp_path):
    files = smoke_install.make(str(tmp_path))
    for key in ("first", "expansion", "other", "text", "known", "patch"):
        assert os.path.getsize(files[key]) > 0
    with open(files["known"], encoding="utf-8") as f:
        rows = json.load(f)
    assert {r[1] for r in rows} == {"MAGIC.EXE", "DECK.EXE", "DECKDLL.DLL"} and all(r[0] == "v1.0" for r in rows)


def test_each_wrong_disc_waits_for_a_message_the_installer_can_say():
    """The text each wrong-disc case waits for is in the installer's or the readers' source, so a reworded message is noticed here and not first in CI."""
    text = ""
    for name in ("install.py", "sotainstall.py", "iso9660.py"):
        with open(os.path.join(ROOT, "tools", "install", name), encoding="utf-8") as f:
            text += f.read()
    for what, args, must in smoke_install.WRONG_DISCS:
        assert any(m in text for m in must.split("|")), f"{what}: none of '{must}' in the installer"


def test_the_batch_file_command_line_is_quoted_for_cmd(tmp_path):
    s = smoke_archive.Smoke("x.zip", str(tmp_path), False)
    s.root = r"C:\Program Files (x86)\Pentamoor"
    cmd = s.cmd_bat("pentamoor-install.bat", ["a b.iso", "--sota"])
    assert cmd == 'cmd.exe /d /s /c ""' + os.path.join(s.root, "pentamoor-install.bat") + '" "a b.iso" "--sota""'

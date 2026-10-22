"""Tests of the licence step of the 2.15 installer (licence.py, regstore.py, and the way install.py runs them), on made-up discs and a made-up writer: no game file, no disc, and no library
of the game is needed, and nothing here makes, reads or checks a real licence value (the fake writer stores a plainly made-up string).   python3 -m pytest tools/install

  flag word      by default the two bits the original installer set and the one more the game defines as "skip the disc check" (8, 22, 17); with --keep-cd-check only the two the
                 original installer set; never anything else
  the step       after the discs are verified, once, with the owner's own file checked by its hash; nothing is written when a disc is wrong, when the file is not the retail one, or
                 with --no-licence-value; --keep-cd-check with --no-licence-value (or without --sota) is refused before anything is read; --no-cd is gone
  the registry   the installer's file reader and writer, the install's own machine pair, and the file the runtime's C reader (src/port/regstore.c) reads
"""
import os
import random
import stat
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lift"))
import builds  # noqa: E402
import licence  # noqa: E402
import regstore  # noqa: E402
from test_sota import command, world, refused  # noqa: E402,F401


def bits(word):
    return {b for b in range(32) if word >> b & 1}


# ---- the flag word ------------------------------------------------------------------------------------------------------------------------------------------------
def test_the_default_flag_word_is_the_original_installers_two_bits_and_the_skip_of_the_disc_check():
    assert bits(licence.flag_word()) == {8, 17, 22} and licence.flag_word() == 0x420100
    assert licence.ORIGINAL_BITS == (8, 22) and licence.FLAG_NO_CD_CHECK == 17 and licence.DEFAULT_BITS == (8, 22, 17)
    assert licence.flag_word() == licence.flag_word(keep_cd_check=False)


def test_keep_cd_check_gives_only_the_bits_the_original_installer_set():
    assert bits(licence.flag_word(keep_cd_check=True)) == {8, 22} and licence.flag_word(keep_cd_check=True) == 0x400100
    assert licence.flag_word() == licence.flag_word(keep_cd_check=True) | 1 << 17
    for word in (licence.flag_word(), licence.flag_word(keep_cd_check=True)):
        assert not bits(word) & {11, 28}                        # the set-2 cards and the developer toggle are never asked for


# ---- the library ----------------------------------------------------------------------------------------------------------------------------------------------------
def test_the_library_is_found_in_whatever_case_the_folder_spells_it(tmp_path):
    prog = tmp_path / "Program"
    (prog / "DUELSOUNDS").mkdir(parents=True)
    assert licence.library_path(str(prog)) is None
    (prog / "DUELSOUNDS" / "MANABALL.WAV").write_bytes(b"x")
    assert licence.library_path(str(prog)) == str(prog / "DUELSOUNDS" / "MANABALL.WAV")


def test_only_the_retail_file_is_accepted(tmp_path):
    spec = builds.SOTA_LICENCE_LIBRARY
    assert spec["sha256"] == "03d06fc50a0bccb78356071dc8aa1401ba6dc059a113e523c8bb25ed30055264" and spec["size"] == 23040
    f = tmp_path / "Manaball.wav"
    with pytest.raises(licence.LicenceError, match="is not in the 2.15 install"):
        licence.verify_library(None)
    f.write_bytes(b"x" * 23040)
    with pytest.raises(licence.LicenceError, match="not the file the original installer used"):
        licence.verify_library(str(f))
    f.write_bytes(b"x" * 100)
    with pytest.raises(licence.LicenceError, match="is 100 bytes where the retail cabinet's Manaball.wav is 23,040"):
        licence.verify_library(str(f))


def test_the_overlay_is_where_the_launcher_keeps_the_saves(tmp_path):
    assert licence.overlay_dir("/r", {}) == os.path.join("/r", "port_overlay_sota")
    assert licence.overlay_dir("/r", {"PORT_OVERLAY": "mine"}) == os.path.join("/r", "mine")
    assert licence.overlay_dir("/r", {"PORT_OVERLAY": str(tmp_path)}) == str(tmp_path)
    assert licence.registry_file("/o") == os.path.join("/o", "registry.dat")


def test_the_request_names_the_export_the_word_and_a_quiet_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("PORT_CONTROL", "/x")
    monkeypatch.setenv("PORT_UNKNOWN_BUILD", "1")
    req = licence.Request("/rt/pentamoor-run", "/rt/game_senclib.so", "/p/DuelSounds/Manaball.wav", "/root", "/ov", "WriteProgramFlags", 0x400100)
    assert req.argv() == ["/rt/pentamoor-run", "-m", "/rt/game_senclib.so", "--call-export", "WriteProgramFlags=0x400100", "/p/DuelSounds/Manaball.wav", "/root"]
    env = req.env()
    assert env["PORT_HEADLESS"] == "1" and env["PORT_OVERLAY"] == "/ov" and env["SDL_VIDEODRIVER"] == "dummy"
    assert "PORT_CONTROL" not in env and "PORT_UNKNOWN_BUILD" not in env                  # a stray setting cannot turn the build check off for this


@pytest.mark.skipif(sys.platform == "win32", reason="the runtime stand-in is a shell script")
def test_the_real_writer_reads_what_the_runtime_prints(tmp_path):
    ok = tmp_path / "run-ok"
    ok.write_text('#!/bin/sh\necho "build: v2.15 Manaball.wav (sha256 000000000000)"\necho "export WriteProgramFlags returned 0"\n')
    bad = tmp_path / "run-bad"
    bad.write_text('#!/bin/sh\necho "pentamoor: nothing"\nexit 3\n')
    for p in (ok, bad):
        p.chmod(p.stat().st_mode | stat.S_IXUSR)
    mk = lambda rt: licence.Request(str(rt), "m", "l", str(tmp_path), str(tmp_path), "WriteProgramFlags", 1)          # noqa: E731
    assert licence.run_writer(mk(ok))[:2] == (0, 0)
    code, returned, out = licence.run_writer(mk(bad))
    assert code == 3 and returned is None and "nothing" in out
    assert licence.run_writer(mk(tmp_path / "missing"))[0] == -1


# ---- the registry file ----------------------------------------------------------------------------------------------------------------------------------------------
def test_the_registry_file_reads_and_writes_the_format_the_runtime_reads(tmp_path):
    path = str(tmp_path / "ov" / "registry.dat")
    s = regstore.Store(path)
    assert s.values == {} and not os.path.exists(path)
    s.put("HKLM\\SOFTWARE\\MicroProse\\Test Product", "Blob", regstore.REG_BINARY, bytes([0xde, 0xad, 0xbe, 0xef, 0, 1, 2, 3, 0xff, 0x10, 0x20, 0x30]))
    text = open(path, "rb").read().decode()
    assert text.startswith("# pentamoor registry 1\n")
    assert "HKLM\\SOFTWARE\\MicroProse\\Test Product\tBlob\t3\tdeadbeef00010203ff102030\n" in text            # the very line src/port/test_regstore.c expects of the C side
    again = regstore.Store(path)
    assert again.get("hklm\\software\\microprose\\test product", "BLOB") == (3, bytes.fromhex("deadbeef00010203ff102030"))


def test_the_registry_file_keeps_only_what_the_runtime_keeps(tmp_path):
    path = str(tmp_path / "registry.dat")
    s = regstore.Store(path)
    for key, name in (("HKLM\\SOFTWARE\\Other", "x"), (regstore.WINDOWS_KEY, "RegisteredOwner"), ("HKCU\\SOFTWARE\\Other", "x"), (regstore.MICROPROSE_KEY, "tab\tname")):
        with pytest.raises(regstore.RegError):
            s.put(key, name, 1, b"a")
    assert not os.path.exists(path)
    open(path, "w").write("# pentamoor registry 1\nHKLM\\SOFTWARE\\Other\tx\t3\t00\nnot a line\nHKLM\\SOFTWARE\\MicroProse\\a\tn\t3\tzz\nHKLM\\SOFTWARE\\MicroProse\\a\tn\t3\t0a\r\n")
    s = regstore.Store(path)
    assert list(s.values) == [("hklm\\software\\microprose\\a", "n")] and s.dropped == 3 and s.get(regstore.MICROPROSE_KEY + "\\a", "n") == (3, b"\x0a")


def test_a_registry_file_that_cannot_be_written_says_so(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    with pytest.raises(regstore.RegError, match="cannot write"):
        regstore.Store(str(blocker / "registry.dat")).put(regstore.MICROPROSE_KEY, "n", 1, b"a")


def test_each_install_makes_a_pair_of_its_own_and_keeps_it(tmp_path):
    a, b = str(tmp_path / "a.dat"), str(tmp_path / "b.dat")
    assert regstore.ensure_pair(a) is True and regstore.ensure_pair(b) is True
    pa, pb = regstore.Store(a), regstore.Store(b)
    ta, ia = pa.get(regstore.WINDOWS_KEY, regstore.INSTALL_TIME), pa.get(regstore.WINDOWS_KEY, regstore.PRODUCT_ID)
    tb, ib = pb.get(regstore.WINDOWS_KEY, regstore.INSTALL_TIME), pb.get(regstore.WINDOWS_KEY, regstore.PRODUCT_ID)
    assert ta[0] == regstore.REG_BINARY and len(ta[1]) == 4 and ia[0] == regstore.REG_SZ and ia[1].endswith(b"\0")
    assert (ta, ia) != (tb, ib)                                                   # two installs, two pairs
    import re
    assert re.fullmatch(rb"\d{5}-OEM-\d{7}-\d{5}\0", ia[1])                      # the shape of Windows 98's, which is not the fixed one the runtime falls back to
    assert ia[1] != b"54377-OEM-0013407-48562\0" and ta[1] != bytes([0x80, 0xEC, 0x91, 0x35])
    when = int.from_bytes(ta[1], "little")
    assert 896_000_000 < when < 978_400_000                                       # a date in 1998 to 2000
    assert regstore.ensure_pair(a) is False                                       # never replaced
    assert regstore.Store(a).get(regstore.WINDOWS_KEY, regstore.PRODUCT_ID) == ia


def test_a_pair_can_be_made_from_a_seed_for_the_tests():
    assert regstore.make_pair(random.Random(1)) == regstore.make_pair(random.Random(1)) != regstore.make_pair(random.Random(2))


# ---- the step, with a fake writer ---------------------------------------------------------------------------------------------------------------------------------
def stored(command, tmp_path):
    return regstore.Store(str(tmp_path / "overlay_sota" / "registry.dat"))


def licence_value(store):
    got = store.get(regstore.LICENCE_KEY, "SerialNumber")
    return got[1] if got else None


def test_the_default_install_writes_the_word_with_the_skip_of_the_disc_check_and_says_so_in_one_line(world, command, tmp_path):
    out = command(world.iso1, "--sota", world.iso2, "--patch", world.patch, "--dest", tmp_path / "inst")
    w = command.rec.writes[0]
    assert bits(w["word"]) == {8, 17, 22} and w["export"] == "WriteProgramFlags" and w["library"] == world.licence_library
    assert w["overlay"] == str(tmp_path / "overlay_sota") and w["pair"] is not None                  # the machine id existed before the writer ran
    said = [line for line in out.splitlines() if line.startswith("licence: writing")]
    assert len(said) == 1
    assert "writing the licence value the original Spells of the Ancients installer writes for an owner of the discs, and, because the discs were just verified, " in said[0]
    assert "\"skip the disc check\" flag, so this install does not ask for a disc later (--keep-cd-check keeps the check)" in said[0]
    store = stored(command, tmp_path)
    assert licence_value(store) == b"made-up:%x" % 0x420100 and regstore.has_pair(store)
    assert f"licence: written to {tmp_path / 'overlay_sota' / 'registry.dat'}" in out
    assert "made-up" not in out                                                                       # the value is never printed


def test_keep_cd_check_hands_over_only_the_original_bits_and_says_so_in_one_line(world, command, tmp_path):
    out = command(world.iso1, "--sota", world.iso2, "--patch", world.patch, "--dest", tmp_path / "inst", "--keep-cd-check")
    assert bits(command.rec.writes[0]["word"]) == {8, 22}
    said = [line for line in out.splitlines() if line.startswith("licence: writing")]
    assert len(said) == 1 and 'without the "skip the disc check" flag (--keep-cd-check): this install asks for a disc where the original did' in said[0]
    assert "because the discs were just verified" not in out
    assert licence_value(stored(command, tmp_path)) == b"made-up:%x" % 0x400100


def test_no_licence_value_writes_nothing_lifts_nothing_and_builds_no_module_for_it(world, command, tmp_path):
    out = command(world.iso1, "--sota", world.iso2, "--patch", world.patch, "--dest", tmp_path / "inst", "--no-licence-value")
    assert command.rec.writes == [] and "licence:" not in out
    assert [c[0] for c in command.rec.calls] == ["lift_all", "lift_sota", "build"] and "senclib" not in command.rec.calls[-1][1]
    assert not (tmp_path / "overlay_sota").exists()


def test_keep_cd_check_with_no_licence_value_is_refused_before_anything_is_read(world, command, tmp_path):
    text = refused(command, world.iso1, "--sota", world.iso2, "--patch", world.patch, "--dest", tmp_path / "inst", "--keep-cd-check", "--no-licence-value")
    assert "--keep-cd-check and --no-licence-value together make no sense" in text and "Give one of them" in text
    assert not (tmp_path / "inst").exists() and command.rec.calls == [] and command.rec.writes == []


@pytest.mark.parametrize("flag", ["--keep-cd-check", "--no-licence-value"])
def test_the_flags_need_the_expansion(world, command, tmp_path, flag):
    text = refused(command, world.iso1, "--dest", tmp_path / "inst", flag)
    assert "about Spells of the Ancients 2.15" in text and "--sota" in text
    assert not (tmp_path / "inst").exists() and command.rec.writes == []


def test_no_cd_is_gone_and_says_what_to_use(world, command, tmp_path):
    text = refused(command, world.iso1, "--sota", world.iso2, "--patch", world.patch, "--dest", tmp_path / "inst", "--no-cd")
    assert "--no-cd is gone: the 2.15 install skips the disc check by default; use --keep-cd-check to keep it" in text
    assert not (tmp_path / "inst").exists() and command.rec.calls == [] and command.rec.writes == []


def test_a_wrong_disc_or_patch_writes_nothing_and_leaves_no_registry_file(world, command, tmp_path):
    inst = tmp_path / "inst"
    refused(command, world.iso2, "--sota", world.iso1, "--patch", world.patch, "--dest", inst)                        # the discs the wrong way round
    cut = tmp_path / "cut.exe"
    cut.write_bytes(world.patch_bytes[:world.patch_bytes.find(b"PK\x01\x02") - 5])
    refused(command, world.iso1, "--sota", world.iso2, "--patch", cut, "--dest", inst)                                # a patch that is cut short
    assert command.rec.writes == [] and not (tmp_path / "overlay_sota").exists() and not inst.exists()


def test_a_library_that_is_not_the_retail_file_is_refused_and_nothing_is_written(world, command, tmp_path, monkeypatch):
    monkeypatch.setattr(builds, "SOTA_LICENCE_LIBRARY", dict(builds.SOTA_LICENCE_LIBRARY, sha256="0" * 64))        # the cabinet's file is not the one the table knows
    text = refused(command, world.iso1, "--sota", world.iso2, "--patch", world.patch, "--dest", tmp_path / "inst")
    assert "not the file the original installer used" in text and "so it is not run and the licence value is not written" in text
    assert "--no-licence-value" in text and "nothing was lifted or built yet" in text
    assert command.rec.writes == [] and not (tmp_path / "overlay_sota").exists()
    assert command.rec.calls == []                                                                                 # nothing was lifted or built, the library least of all


def test_a_writer_that_fails_or_leaves_no_value_is_reported_and_leaves_no_value(world, command, tmp_path):
    command.rec.writer_result = (3, None)
    text = refused(command, world.iso1, "--sota", world.iso2, "--patch", world.patch, "--dest", tmp_path / "inst")
    assert "did not write the licence value" in text and "status 3" in text
    assert licence_value(stored(command, tmp_path)) is None
    command.rec.writer_result = (0, 1)                                                                              # the export itself said no
    text = refused(command, world.iso1, "--sota", world.iso2, "--patch", world.patch, "--dest", tmp_path / "inst")
    assert "the export returned 1" in text and licence_value(stored(command, tmp_path)) is None


def test_the_runtime_or_module_missing_stops_the_step_before_it_asks_anything(world, tmp_path):
    prog = tmp_path / "Program" / "DuelSounds"
    prog.mkdir(parents=True)
    (prog / "Manaball.wav").write_bytes(world.licence_library)
    asked = []
    writer = lambda req: asked.append(req) or (0, 0, "")                                                           # noqa: E731
    with pytest.raises(licence.LicenceError, match="is not built"):
        licence.write_value(str(tmp_path / "Program"), str(tmp_path), str(tmp_path / "ov"), str(tmp_path / "run"), str(tmp_path / "mod"), writer=writer)
    (tmp_path / "mod").write_text("")
    with pytest.raises(licence.LicenceError, match="runtime"):
        licence.write_value(str(tmp_path / "Program"), str(tmp_path), str(tmp_path / "ov"), str(tmp_path / "run"), str(tmp_path / "mod"), writer=writer)
    assert asked == [] and not (tmp_path / "ov").exists()


def test_running_the_installer_again_keeps_the_pair_and_writes_the_same_word(world, command, tmp_path):
    command(world.iso1, "--sota", world.iso2, "--patch", world.patch, "--dest", tmp_path / "inst")
    first = stored(command, tmp_path)
    pair = (first.get(regstore.WINDOWS_KEY, regstore.INSTALL_TIME), first.get(regstore.WINDOWS_KEY, regstore.PRODUCT_ID))
    out = command(world.iso1, "--sota", world.iso2, "--patch", world.patch, "--dest", tmp_path / "inst")
    second = stored(command, tmp_path)
    assert (second.get(regstore.WINDOWS_KEY, regstore.INSTALL_TIME), second.get(regstore.WINDOWS_KEY, regstore.PRODUCT_ID)) == pair
    assert "made this install's own machine id" not in out                                                        # (the first run said that)
    assert len(command.rec.writes) == 2 and command.rec.writes[0]["word"] == command.rec.writes[1]["word"]
    assert len(second.values) == 3 and licence_value(second) == b"made-up:%x" % 0x420100
    command(world.iso1, "--sota", world.iso2, "--patch", world.patch, "--dest", tmp_path / "inst", "--keep-cd-check")        # asking to keep the check later changes the word, not the pair
    assert licence_value(stored(command, tmp_path)) == b"made-up:%x" % 0x400100
    command(world.iso1, "--sota", world.iso2, "--patch", world.patch, "--dest", tmp_path / "inst")                  # and asking for the default again takes it back
    assert licence_value(stored(command, tmp_path)) == b"made-up:%x" % 0x420100


def test_the_registry_file_is_in_the_overlay_the_launcher_uses(world, command, tmp_path, monkeypatch):
    monkeypatch.delenv("PORT_OVERLAY")
    command(world.iso1, "--sota", world.iso2, "--patch", world.patch, "--dest", tmp_path / "inst")
    assert os.path.isfile(os.path.join(command.root, "port_overlay_sota", "registry.dat"))

"""Tests of the Steam Deck tools, none of which needs Steam, a Deck or the game:

  * add-to-steam.py: the binary VDF writer against a hand-built shortcuts.vdf (what is read, what is written, byte for byte), the app id, Steam running, the command line on a
    fake Steam folder (backup, refusal while Steam runs, --remove, --dry-run);
  * progress.py: the installer's output (a real install log) as a percentage;
  * install-gui.sh: the sequence of dialogs and calls, with stand-ins for kdialog, qdbus and steam and a fake installer;
  * the Steam Input layout and the .desktop files: well formed, and what they say matches what the program reads.

    python3 -m pytest tools/steamdeck
"""
import importlib.util
import os
import re
import shlex
import shutil
import stat
import struct
import subprocess
import sys
import textwrap
import zlib

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


a2s = load("add_to_steam", "add-to-steam.py")
prog = load("progress", "progress.py")


# ---- a shortcuts.vdf built by hand, byte by byte ------------------------------------------------------------------------------------------------------------
def s(key, value):
    return b"\x01" + key + b"\x00" + value + b"\x00"


def i(key, value):
    return b"\x02" + key + b"\x00" + struct.pack("<I", value)


def d(key, body):
    return b"\x00" + key + b"\x00" + body + b"\x08"


FOO_ENTRY = (i(b"appid", 0xC0FFEE01) + s(b"AppName", b"Foo Game") + s(b"Exe", b'"/home/deck/foo/foo.sh"') + s(b"StartDir", b'"/home/deck/foo/"') + s(b"icon", b"")
             + s(b"ShortcutPath", b"") + s(b"LaunchOptions", b"--fullscreen") + i(b"IsHidden", 0) + i(b"AllowDesktopConfig", 1) + i(b"AllowOverlay", 1) + i(b"OpenVR", 0)
             + i(b"Devkit", 0) + s(b"DevkitGameID", b"") + i(b"DevkitOverrideAppID", 0) + i(b"LastPlayTime", 1700000000) + s(b"FlatpakAppID", b"")
             + d(b"tags", s(b"0", b"favorite") + s(b"1", b"installed")))
SAMPLE = d(b"shortcuts", d(b"0", FOO_ENTRY)) + b"\x08"        # the root list holds "shortcuts" and ends with its own 0x08


def test_sample_parses_and_round_trips():
    root = a2s.parse(SAMPLE)
    assert a2s.dump(root) == SAMPLE
    lst = a2s.shortcuts_list(root)
    assert [k for k, t, v in lst] == [b"0"]
    entry = lst[0][2]
    assert a2s._find(entry, "AppName") == b"Foo Game"
    assert a2s._find(entry, "exe") == b'"/home/deck/foo/foo.sh"'                      # keys are found in any case
    assert a2s.int_value(a2s._find(entry, "appid")) == 0xC0FFEE01
    assert a2s.int_value(a2s._find(entry, "LastPlayTime")) == 1700000000
    tags = a2s._find(entry, "tags")
    assert tags == [(b"0", a2s.T_STR, b"favorite"), (b"1", a2s.T_STR, b"installed")]


def test_app_id_is_the_crc_of_the_quoted_exe_and_the_name_with_the_top_bit():
    exe, name = '"/home/deck/pentamoor/pentamoor"', "Pentamoor"
    want = (zlib.crc32((exe + name).encode()) & 0xFFFFFFFF) | 0x80000000
    assert a2s.shortcut_appid(exe, name) == want
    assert a2s.shortcut_appid(exe, name) >= 0x80000000
    assert a2s.shortcut_appid(exe, name) != a2s.shortcut_appid(exe, "Other")
    # the 64-bit id Steam uses for artwork is this one in the top half with 0x02000000 below it
    assert ((want << 32) | 0x02000000) >> 32 == want


def expected_pentamoor(key, exe, start, appid, options=b""):
    """The bytes of the new entry, built here by hand (not by the writer)."""
    return d(key, i(b"appid", appid) + s(b"AppName", b"Pentamoor") + s(b"Exe", b'"' + exe + b'"') + s(b"StartDir", b'"' + start + b'"') + s(b"icon", b"")
             + s(b"ShortcutPath", b"") + s(b"LaunchOptions", options) + i(b"IsHidden", 0) + i(b"AllowDesktopConfig", 1) + i(b"AllowOverlay", 1) + i(b"OpenVR", 0)
             + i(b"Devkit", 0) + s(b"DevkitGameID", b"") + i(b"DevkitOverrideAppID", 0) + i(b"LastPlayTime", 0) + s(b"FlatpakAppID", b"")
             + d(b"tags", s(b"0", b"Pentamoor")))


def test_add_to_existing_file_appends_entry_1_and_keeps_the_rest_exactly():
    exe, start = "/home/deck/Games/pentamoor/pentamoor", "/home/deck/Games/pentamoor"
    new, status = a2s.add_shortcut(SAMPLE, exe, start)
    assert status == "added"
    appid = a2s.shortcut_appid('"%s"' % exe, "Pentamoor")
    want = d(b"shortcuts", d(b"0", FOO_ENTRY) + expected_pentamoor(b"1", exe.encode(), start.encode(), appid)) + b"\x08"
    assert new == want
    assert new.endswith(b"\x08\x08\x08\x08")                                          # tags, the entry, shortcuts, the root
    assert new.startswith(SAMPLE[:SAMPLE.index(b"\x00shortcuts\x00") + 1 + len(b"shortcuts") + 1 + len(d(b"0", FOO_ENTRY))])  # the existing entry is untouched
    assert a2s.dump(a2s.parse(new)) == new                                            # and it reads back


def test_launch_options_and_paths_with_spaces_and_unicode():
    exe, start = "/home/deck/My Games/Pentamoor é/pentamoor", "/home/deck/My Games/Pentamoor é"
    new, _ = a2s.add_shortcut(SAMPLE, exe, start, "PORT_RES=800x600 %command%")
    root = a2s.parse(new)
    entry = a2s.shortcuts_list(root)[1][2]
    assert a2s._find(entry, "Exe").decode("utf-8") == '"%s"' % exe
    assert a2s._find(entry, "StartDir").decode("utf-8") == '"%s"' % start
    assert a2s._find(entry, "LaunchOptions") == b"PORT_RES=800x600 %command%"


def test_a_new_file_and_a_second_run_changes_nothing():
    exe, start = "/x/pentamoor", "/x"
    new, status = a2s.add_shortcut(b"", exe, start)
    assert status == "added"
    appid = a2s.shortcut_appid('"/x/pentamoor"', "Pentamoor")
    assert new == d(b"shortcuts", expected_pentamoor(b"0", b"/x/pentamoor", b"/x", appid)) + b"\x08"
    again, status = a2s.add_shortcut(new, exe, start)
    assert status == "present" and again == new
    moved, status = a2s.add_shortcut(new, "/elsewhere/pentamoor", "/elsewhere")          # the same launcher name and title: still ours, not added twice
    assert status == "present"


def test_numbering_follows_the_highest_key():
    entry = lambda n: d(n, s(b"AppName", b"G" + n) + s(b"Exe", b'"/g"'))
    data = d(b"shortcuts", entry(b"0") + entry(b"4")) + b"\x08"
    new, _ = a2s.add_shortcut(data, "/p/pentamoor", "/p")
    assert [k for k, t, v in a2s.shortcuts_list(a2s.parse(new))] == [b"0", b"4", b"5"]


def test_file_without_a_shortcuts_list_gets_one():
    data = d(b"other", i(b"x", 1)) + b"\x08"
    new, status = a2s.add_shortcut(data, "/p/pentamoor", "/p")
    root = a2s.parse(new)
    assert status == "added" and [k for k, t, v in root] == [b"other", b"shortcuts"]


@pytest.mark.parametrize("bad", [
    SAMPLE[:-1],                                    # the root is not ended
    SAMPLE + b"\x00",                               # junk after the end
    b"\x09abc\x00",                                 # a type nobody knows
    d(b"shortcuts", b"\x01a\x00unended"),           # a string without its end
    d(b"shortcuts", b"\x02a\x00\x01\x02") + b"\x08",  # a number cut short
])
def test_unreadable_files_are_refused_not_rewritten(bad):
    with pytest.raises(a2s.VdfError):
        a2s.add_shortcut(bad, "/p/pentamoor", "/p")


def test_a_file_that_does_not_read_back_identically_is_refused():
    wide = b"\x05w\x00" + "hi".encode("utf-16-le") + b"\x00\x00"                      # a wide string reads and writes back the same, so this passes ...
    data = d(b"shortcuts", wide) + b"\x08"
    assert a2s.dump(a2s.parse(data)) == data
    # ... while a file whose bytes the writer would change is refused: fake the writer into a difference
    real = a2s.dump
    a2s.dump = lambda root: real(root) + b"!"
    try:
        with pytest.raises(a2s.VdfError):
            a2s.add_shortcut(SAMPLE, "/p/pentamoor", "/p")
    finally:
        a2s.dump = real


def test_other_value_types_survive_a_round_trip():
    body = (b"\x03f\x00" + struct.pack("<f", 1.5) + b"\x07u\x00" + struct.pack("<Q", 2 ** 40) + b"\x0al\x00" + struct.pack("<q", -5) + b"\x06c\x00\x01\x02\x03\x04")
    data = d(b"shortcuts", d(b"0", body + s(b"AppName", b"x") + s(b"Exe", b'"/x/y"'))) + b"\x08"
    new, _ = a2s.add_shortcut(data, "/p/pentamoor", "/p")
    assert new.startswith(data[:-3])
    assert a2s.dump(a2s.parse(new)) == new


def test_remove_takes_out_only_ours():
    exe, start = "/p/pentamoor", "/p"
    both, _ = a2s.add_shortcut(SAMPLE, exe, start)
    back, n = a2s.remove_shortcuts(both, exe)
    assert n == 1
    assert [k for k, t, v in a2s.shortcuts_list(a2s.parse(back))] == [b"0"]
    assert a2s.remove_shortcuts(SAMPLE, exe) == (SAMPLE, 0)


# ---- Steam's folder, and Steam running ---------------------------------------------------------------------------------------------------------------------
def make_steam(tmp_path, users=("12345",), vdf=SAMPLE):
    home = tmp_path / "home"
    steam = home / ".steam" / "steam"
    for u in users:
        (steam / "userdata" / u / "config").mkdir(parents=True)
        if vdf is not None:
            (steam / "userdata" / u / "config" / "shortcuts.vdf").write_bytes(vdf)
    (steam / "userdata" / "0").mkdir(parents=True, exist_ok=True)
    return home, steam


def test_finding_steam_and_the_user(tmp_path):
    home, steam = make_steam(tmp_path, users=("111", "222"))
    assert a2s.steam_roots(str(home)) == [str(steam)]
    assert a2s.steam_roots(str(tmp_path / "nowhere")) == []
    os.utime(steam / "userdata" / "111", (1000, 1000))
    os.utime(steam / "userdata" / "222", (2000, 2000))
    assert [n for n, p in a2s.user_dirs(str(steam))] == ["222", "111"]                  # most recent first; 0 is not a user
    (steam / "userdata" / "111" / "config" / "localconfig.vdf").write_text("x")          # a used account has this, and it decides
    assert a2s.user_dirs(str(steam))[0][0] == "111"


def test_steam_running_from_its_pid_file_and_the_process_list(tmp_path):
    proc = tmp_path / "proc"
    (proc / "100").mkdir(parents=True)
    (proc / "100" / "comm").write_text("steam\n")
    (proc / "200").mkdir()
    (proc / "200" / "comm").write_text("bash\n")
    pid = tmp_path / "steam.pid"
    pid.write_text("100\n")
    assert a2s.steam_running(str(pid), str(proc))                                       # the pid file names a live steam
    pid.write_text("200\n")
    assert a2s.steam_running(str(pid), str(proc))                                       # stale pid file, but a steam is in the list
    (proc / "100" / "comm").write_text("steamwebhelper\n")
    assert not a2s.steam_running(str(pid), str(proc))                                   # only a helper (exact "steam" for the scan)
    assert not a2s.steam_running(str(tmp_path / "none.pid"), str(tmp_path / "noproc"))


def run_a2s(args, home, extra_env=None):
    env = dict(os.environ, HOME=str(home))
    env.pop("XDG_DATA_HOME", None)
    env.update(extra_env or {})
    exe = home / "Pentamoor" / "pentamoor"
    exe.parent.mkdir(exist_ok=True)
    exe.write_text("#!/bin/sh\n")
    cmd = [sys.executable, os.path.join(HERE, "add-to-steam.py"), "--exe", str(exe)] + args
    return subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True), exe


def test_command_line_adds_with_a_backup_and_the_menu_entry(tmp_path):
    home, steam = make_steam(tmp_path)
    # a fake process list says Steam is not running: the program's own check looks at the real /proc, which has no steam here
    r, exe = run_a2s(["--steam-dir", str(steam), "--desktop-entry"], home)
    if "Steam is running" in r.stdout:
        pytest.skip("a real Steam is running on this machine")
    assert r.returncode == 0, r.stdout
    path = steam / "userdata" / "12345" / "config" / "shortcuts.vdf"
    backups = [p for p in os.listdir(path.parent) if ".pentamoor-backup-" in p]
    assert len(backups) == 1 and (path.parent / backups[0]).read_bytes() == SAMPLE        # the old file, kept
    root = a2s.parse(path.read_bytes())
    entry = a2s.shortcuts_list(root)[1][2]
    assert a2s._find(entry, "Exe").decode() == '"%s"' % exe
    assert a2s._find(entry, "StartDir").decode() == '"%s"' % exe.parent
    assert a2s._find(entry, "tags")[0][2] == b"Pentamoor"
    desktop = home / ".local" / "share" / "applications" / "pentamoor.desktop"
    text = desktop.read_text()
    assert "[Desktop Entry]" in text and 'Exec="%s"' % exe in text and "Name=Pentamoor" in text
    assert "Start Steam again" in r.stdout
    r2, _ = run_a2s(["--steam-dir", str(steam)], home)
    assert r2.returncode == 0 and "already in" in r2.stdout
    assert path.read_bytes() == a2s.add_shortcut(SAMPLE, str(exe), str(exe.parent))[0]    # a second run changed nothing
    r3, _ = run_a2s(["--steam-dir", str(steam), "--remove"], home)
    assert r3.returncode == 0 and "removed 1" in r3.stdout
    assert path.read_bytes() == SAMPLE


def test_refuses_while_steam_runs_unless_forced(tmp_path):
    home, steam = make_steam(tmp_path)
    fake = tmp_path / "fakeproc"
    (fake / "1234").mkdir(parents=True)
    (fake / "1234" / "comm").write_text("steam\n")
    sitecustomize = tmp_path / "sc"
    sitecustomize.mkdir()
    # run the program in-process with a process list that has a steam in it
    exe = home / "Pentamoor" / "pentamoor"
    exe.parent.mkdir()
    exe.write_text("x")
    real = a2s.steam_running
    a2s.steam_running = lambda pid_file=None, proc=str(fake): real(pid_file or str(tmp_path / "no.pid"), proc)
    try:
        before = (steam / "userdata" / "12345" / "config" / "shortcuts.vdf").read_bytes()
        assert a2s.main(["--exe", str(exe), "--steam-dir", str(steam)]) == 3
        assert (steam / "userdata" / "12345" / "config" / "shortcuts.vdf").read_bytes() == before
        assert a2s.main(["--exe", str(exe), "--steam-dir", str(steam), "--dry-run"]) == 0       # looking is allowed
        assert a2s.main(["--exe", str(exe), "--steam-dir", str(steam), "--force"]) == 0
        assert (steam / "userdata" / "12345" / "config" / "shortcuts.vdf").read_bytes() != before
        assert a2s.main(["--check-steam"]) == 3
    finally:
        a2s.steam_running = real


def test_unreadable_shortcuts_file_is_left_alone_and_the_manual_steps_are_printed(tmp_path):
    home, steam = make_steam(tmp_path, vdf=b"this is not a binary vdf file")
    r, exe = run_a2s(["--steam-dir", str(steam)], home)
    if "Steam is running" in r.stdout:
        pytest.skip("a real Steam is running on this machine")
    assert r.returncode == 1
    assert (steam / "userdata" / "12345" / "config" / "shortcuts.vdf").read_bytes() == b"this is not a binary vdf file"
    assert "Add a Non-Steam Game" in r.stdout and str(exe) in r.stdout
    assert not [p for p in os.listdir(steam / "userdata" / "12345" / "config") if "backup" in p or "tmp" in p]


def test_no_steam_folder_gives_the_manual_steps(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    r, exe = run_a2s([], home)
    assert r.returncode == 1 and "Steam's folder was not found" in r.stdout and "Add a Non-Steam Game" in r.stdout


def test_dry_run_changes_nothing(tmp_path):
    home, steam = make_steam(tmp_path)
    r, _ = run_a2s(["--steam-dir", str(steam), "--dry-run", "--desktop-entry", "--controller-template"], home)
    assert r.returncode == 0 and "dry run" in r.stdout
    assert (steam / "userdata" / "12345" / "config" / "shortcuts.vdf").read_bytes() == SAMPLE
    assert not (home / ".local").exists() and not (steam / "controller_base").exists()


def test_controller_template_is_copied(tmp_path):
    home, steam = make_steam(tmp_path)
    r, _ = run_a2s(["--steam-dir", str(steam), "--controller-template", "--dry-run"], home)
    dest = a2s.install_template(str(steam))
    assert dest == str(steam / "controller_base" / "templates" / "controller_neptune_pentamoor.vdf")
    assert open(dest).read() == open(os.path.join(HERE, "controller_neptune_pentamoor.vdf")).read()


# ---- progress.py -------------------------------------------------------------------------------------------------------------------------------------------
REAL_LOG = """\
disc: MTG v1.0
reading Setup/data.z (72 MB)
  100/967 files
  500/967 files
  900/967 files
game files: 967 written, 0 already there (47 s)
sound from the disc: 31 files (31 copied)
statwin from the disc: 68 files (68 copied)
programs: all seven match the retail disc (version 1.0)
installed into /home/deck/Games/pentamoor/sources/installed/Magic
downloading Zig 0.16.0 (95 MB) from PyPI: https://files.pythonhosted.org/x
  10%
  50%
  100%
unpacking Zig
compiler: /home/deck/Games/pentamoor/tools/local/ziglang/zig cc  (zig 0.16.0)
lifting the game's programs into C (a few minutes; the C is generated from your files and stays on your machine)
  [magic] gen_handlers.py sources/installed/Magic/Program/MAGIC.EXE sources/generated/lift_magic_all
  [deck] done in 0 s
      [deck] DECKDLL: 1013 functions lifted, 0 not
  [deck] done in 4 s
  [duel] done in 16 s
  [magic] done in 35 s
lifted magic, deck, duel in 39 s
compiling 13 files with 8 at a time, 96 MB of C (zig cc)
  [1/13]   0%  magic/modglue.c  (0 s)
  [7/13]   1%  deck/handlers_gen.c  (2 s)
  ... 25% done after 39 s; still compiling: handlers_gen.c (40 MB, 39 s), handlers_gen.c (31 MB, 39 s)
  [12/13]  58%  duel/handlers_gen.c  (56 s)
  [13/13] 100%  magic/handlers_gen.c  (1 min 10 s)
linking game_magic.so
linking game_deck.so
linking game_duel.so
  game_magic: loads in the runtime
  game_deck: loads in the runtime
  game_duel: loads in the runtime
removed sources/generated
removed sources/build
built. Play with:  ./pentamoor
"""


def feed_all(text):
    p = prog.Progress()
    seen = []
    for line in text.splitlines():
        r = p.feed(line)
        if r:
            seen.append(r)
    return seen


def test_progress_follows_a_real_install_and_never_goes_back():
    seen = feed_all(REAL_LOG)
    pcts = [p for p, t in seen]
    assert pcts == sorted(pcts)
    assert pcts[-1] == 100 and seen[-1][1] == "Done"
    assert any("Copying the game files (500 of 967)" in t for p, t in seen)
    assert any(t.startswith("Downloading the C compiler (50%)") for p, t in seen)
    assert any(t == "Compiling the game (12 of 13 files)" and 70 <= p <= 75 for p, t in seen)
    assert max(p for p, t in seen if t.startswith("Compiling")) <= 93
    assert [t for p, t in seen if p == 94] == ["Linking the game"]
    assert all(0 <= p <= 100 for p in pcts)


def test_progress_without_a_download_and_when_nothing_is_lifted():
    seen = feed_all("reading Setup/data.z (72 MB)\ngame files: 1 written\ncompiler: /usr/bin/cc\n  [magic] already lifted from these files; skipping\nall objects are up to date\nlinking game_magic.so\nbuilt. Play\n")
    assert [p for p, t in seen] == [2, 18, 32, 42, 93, 94, 100]


def test_progress_stdin_filter_writes_percent_bar_lines_and_a_log(tmp_path):
    log = tmp_path / "log.txt"
    r = subprocess.run([sys.executable, os.path.join(HERE, "progress.py"), "--log", str(log)], input=REAL_LOG, stdout=subprocess.PIPE, universal_newlines=True)
    lines = r.stdout.splitlines()
    assert lines[0] == "1|Reading the disc image" and lines[-1] == "100|Done"
    assert all(re.match(r"^\d{1,3}\|.+$", l) for l in lines)
    assert log.read_text() == REAL_LOG


# ---- install-gui.sh, with stand-ins for the dialogs ---------------------------------------------------------------------------------------------------------
STUB_KDIALOG = """#!/bin/sh
# records every call; answers like a person who says yes and picks $STUB_ISO
printf '%s\\n' "kdialog $(echo "$*" | tr '\\n' ' ')" >> "$STUB_LOG"
case "$1" in
  --title) shift 2 ;;
esac
case "$1" in
  --getopenfilename) printf '%s\\n' "$STUB_ISO" ;;
  --progressbar) echo "org.kde.kdialog-4242 /ProgressDialog" ;;
  --yesno) [ -f "$STUB_NO" ] && grep -q "$(echo "$2" | head -c 20)" "$STUB_NO" && exit 1; exit 0 ;;
  *) ;;
esac
exit 0
"""
STUB_QDBUS = """#!/bin/sh
echo "qdbus $*" >> "$STUB_LOG"
"""
STUB_STEAM = """#!/bin/sh
echo "steam $*" >> "$STUB_LOG"
"""
FAKE_INSTALL = """#!/usr/bin/env python3
import os, sys
root = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
open(os.path.join(root, "args.txt"), "w").write(" ".join(args))
if "--fail" in os.environ.get("STUB_MODE", ""):
    print("disc: x")
    print("install: this does not look like the Magic: The Gathering disc (no Setup/data.z)")
    sys.exit(1)
print("disc: MTG v1.0", flush=True)
print("reading Setup/data.z (72 MB)", flush=True)
print("  500/967 files", flush=True)
print("game files: 967 written, 0 already there (1 s)", flush=True)
print("compiler: cc", flush=True)
print("compiling 2 files with 2 at a time, 1 MB of C (cc)", flush=True)
print("  [1/2]  50%  magic/modglue.c  (0 s)", flush=True)
print("  [2/2] 100%  magic/handlers_gen.c  (1 s)", flush=True)
print("linking game_magic.so", flush=True)
open(os.path.join(root, "game_magic.so"), "w").write("module")
print("built. Play with:  ./pentamoor", flush=True)
"""

pytestmark_gui = pytest.mark.skipif(os.name == "nt" or not shutil.which("sh"), reason="a shell script")


def gui_fixture(tmp_path):
    root = tmp_path / "pentamoor"
    (root / "tools" / "steamdeck").mkdir(parents=True)
    (root / "tools" / "install").mkdir(parents=True)
    (root / "tools" / "install" / "install.py").write_text("")
    for name in ("install-gui.sh", "install-run.sh", "progress.py", "add-to-steam.py", "controller_neptune_pentamoor.vdf"):
        shutil.copy(os.path.join(HERE, name), root / "tools" / "steamdeck" / name)
    (root / "pentamoor").write_text("#!/bin/sh\n")
    (root / "pentamoor").chmod(0o755)
    (root / "pentamoor-install").write_text(FAKE_INSTALL)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for name, text in (("kdialog", STUB_KDIALOG), ("qdbus", STUB_QDBUS), ("steam", STUB_STEAM)):
        (stubs / name).write_text(text)
        (stubs / name).chmod(0o755)
    iso = tmp_path / "MTG v1.0.iso"
    iso.write_bytes(b"x")
    home, steam = make_steam(tmp_path)
    env = dict(os.environ, HOME=str(home), DISPLAY=":0", PATH=str(stubs) + os.pathsep + os.environ["PATH"], STUB_LOG=str(tmp_path / "calls.log"), STUB_ISO=str(iso),
               STUB_NO=str(tmp_path / "no.txt"), TMPDIR=str(tmp_path))
    env.pop("WAYLAND_DISPLAY", None)
    env.pop("XDG_DATA_HOME", None)
    return root, env, tmp_path / "calls.log", iso, steam


def calls(log):
    return log.read_text().splitlines() if log.exists() else []


@pytestmark_gui
def test_install_gui_whole_sequence_with_kdialog(tmp_path):
    root, env, log, iso, steam = gui_fixture(tmp_path)
    r = subprocess.run(["sh", str(root / "tools" / "steamdeck" / "install-gui.sh")], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=120)
    assert r.returncode == 0, r.stdout
    c = calls(log)
    dialogs = [re.search(r" (--(?:yesno|msgbox|error|getopenfilename|progressbar)) ", l).group(1) for l in c if l.startswith("kdialog")]
    # the intro question, the file picker, the progress bar, then (after the installer) "installed", "add to Steam?" and "added"
    assert dialogs == ["--yesno", "--getopenfilename", "--progressbar", "--msgbox", "--yesno", "--msgbox"], c
    assert "--getopenfilename %s " % (tmp_path / "home") in c[1]                                                          # the picker starts in the home folder (no Downloads here)
    bar = [l for l in c if l.startswith("qdbus")]
    assert any(l.startswith("qdbus org.kde.kdialog-4242 /ProgressDialog Set  value 100") for l in bar), bar                # the bar reached the end
    assert any("setLabelText Done" in l for l in bar)
    assert bar[-1] == "qdbus org.kde.kdialog-4242 /ProgressDialog close"
    assert c.index(bar[-1]) < c.index([l for l in c if "--msgbox" in l][0])                                              # the bar is closed before the result is shown
    assert (root / "args.txt").read_text() == f"--yes --clean {iso}"                                                  # the installer got the ISO, said yes to the compiler download, and cleaned up
    # Steam: the shortcut is in, with a backup, and the menu entry and the layout are there
    path = steam / "userdata" / "12345" / "config" / "shortcuts.vdf"
    entry = a2s.shortcuts_list(a2s.parse(path.read_bytes()))[1][2]
    assert a2s._find(entry, "Exe").decode() == '"%s"' % (root / "pentamoor")
    assert (tmp_path / "home" / ".local" / "share" / "applications" / "pentamoor.desktop").exists()
    assert (steam / "controller_base" / "templates" / "controller_neptune_pentamoor.vdf").exists()
    assert not any(l.startswith("steam") for l in c), "Steam was not running, so it must not be shut down or started"
    assert "pentamoor-rc" not in "".join(os.listdir(tmp_path))                                                         # the temporary status file is gone
    assert (root / "pentamoor-install.log").read_text().count("\n") >= 8                                                 # the installer's whole text is kept


@pytestmark_gui
def test_install_gui_cancelling_the_picker_does_nothing(tmp_path):
    root, env, log, iso, steam = gui_fixture(tmp_path)
    env["STUB_ISO"] = ""
    r = subprocess.run(["sh", str(root / "tools" / "steamdeck" / "install-gui.sh")], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=60)
    assert r.returncode == 0
    assert not (root / "args.txt").exists()
    assert not any("--progressbar" in l for l in calls(log))


@pytestmark_gui
def test_install_gui_declining_the_intro_does_nothing(tmp_path):
    root, env, log, iso, steam = gui_fixture(tmp_path)
    (tmp_path / "no.txt").write_text("Pentamoor is a nativ\n")
    r = subprocess.run(["sh", str(root / "tools" / "steamdeck" / "install-gui.sh")], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=60)
    assert r.returncode == 0 and not (root / "args.txt").exists()
    assert not any("--getopenfilename" in l for l in calls(log))


@pytestmark_gui
def test_install_gui_failure_shows_the_end_of_the_log_and_does_not_offer_steam(tmp_path):
    root, env, log, iso, steam = gui_fixture(tmp_path)
    env["STUB_MODE"] = "--fail"
    r = subprocess.run(["sh", str(root / "tools" / "steamdeck" / "install-gui.sh")], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=60)
    assert r.returncode == 1
    errors = [l for l in calls(log) if "--error" in l]
    assert len(errors) == 1 and "does not look like the Magic: The Gathering disc" in errors[0] and "exit status 1" in errors[0]
    assert not [l for l in calls(log) if "Add Pentamoor to Steam" in l]
    assert (steam / "userdata" / "12345" / "config" / "shortcuts.vdf").read_bytes() == SAMPLE


@pytestmark_gui
def test_install_gui_steam_running_asks_to_close_it(tmp_path):
    root, env, log, iso, steam = gui_fixture(tmp_path)
    # a steam that is running until it is told to shut down: the add-to-steam check looks at /proc, which the stand-in cannot fake, so use a pid file's process: this very test
    # process is not called steam either, so give add-to-steam.py a process list through a sitecustomize-free route: run only the --steam-only path with the check replaced
    script = root / "tools" / "steamdeck" / "add-to-steam.py"
    text = script.read_text().replace('def steam_running(pid_file=None, proc="/proc"):', 'def steam_running(pid_file=None, proc="/proc"):\n    return os.path.exists(os.environ["STUB_STEAM_UP"])\n\n\ndef _real_steam_running(pid_file=None, proc="/proc"):')
    script.write_text(text)
    up = tmp_path / "steam-up"
    up.write_text("1")
    env["STUB_STEAM_UP"] = str(up)
    # the stand-in `steam -shutdown` takes Steam down
    (tmp_path / "stubs" / "steam").write_text('#!/bin/sh\necho "steam $*" >> "$STUB_LOG"\n[ "$1" = "-shutdown" ] && rm -f "$STUB_STEAM_UP"\nexit 0\n')
    r = subprocess.run(["sh", str(root / "tools" / "steamdeck" / "install-gui.sh"), "--steam-only"], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=120)
    assert r.returncode == 0, r.stdout
    c = calls(log)
    assert [l for l in c if "Steam is running" in l], c
    assert "steam -shutdown" in c
    assert any("Start Steam again" in l for l in c)
    entry = a2s.shortcuts_list(a2s.parse((steam / "userdata" / "12345" / "config" / "shortcuts.vdf").read_bytes()))
    assert len(entry) == 2
    assert c.index("steam -shutdown") < [n for n, l in enumerate(c) if "added to Steam" in l][0]


@pytestmark_gui
def test_install_gui_without_dialogs_asks_on_the_terminal_path(tmp_path):
    root, env, log, iso, steam = gui_fixture(tmp_path)
    env.pop("DISPLAY")                                      # no display: no kdialog; the questions come as text on stdin
    r = subprocess.run(["sh", str(root / "tools" / "steamdeck" / "install-gui.sh")], env=env, input="y\n%s\ny\n" % iso, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=120)
    assert r.returncode == 0, r.stdout
    assert not os.path.exists(log)                         # kdialog was never called
    assert "Continue? [Y/n]" in r.stdout and "Pentamoor is installed" in r.stdout
    assert (root / "args.txt").read_text() == f"--yes --clean {iso}"


@pytestmark_gui
def test_install_gui_already_installed_goes_straight_to_steam(tmp_path):
    root, env, log, iso, steam = gui_fixture(tmp_path)
    (root / "sources" / "installed" / "Magic" / "Program").mkdir(parents=True)
    (root / "sources" / "installed" / "Magic" / "Program" / "MAGIC.EXE").write_text("x")
    (root / "game_magic.so").write_text("x")
    r = subprocess.run(["sh", str(root / "tools" / "steamdeck" / "install-gui.sh")], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=60)
    assert r.returncode == 0
    assert not (root / "args.txt").exists()
    assert any("already installed" in l for l in calls(log))


@pytestmark_gui
def test_install_gui_not_enough_disk_space_stops_before_asking(tmp_path):
    root, env, log, iso, steam = gui_fixture(tmp_path)
    (tmp_path / "stubs" / "df").write_text("#!/bin/sh\nprintf 'Filesystem 1024-blocks Used Available Capacity Mounted\\n/dev/x 100 90 10000 99%% /\\n'\n")
    (tmp_path / "stubs" / "df").chmod(0o755)
    r = subprocess.run(["sh", str(root / "tools" / "steamdeck" / "install-gui.sh")], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=60)
    assert r.returncode == 1
    errors = [l for l in calls(log) if "--error" in l]
    assert len(errors) == 1 and "not enough free disk space" in errors[0] and "9 MB is free" in errors[0]
    assert not any("--yesno" in l for l in calls(log))


@pytestmark_gui
def test_launcher_runs_the_window_installer_only_where_it_should(tmp_path):
    """./pentamoor with no game, no terminal and a display starts install-gui.sh; with a terminal, without a display, in Game mode, or without the Steam Deck files it does not."""
    root = tmp_path / "pentamoor"
    (root / "tools" / "steamdeck").mkdir(parents=True)
    for name in ("pentamoor", "pentamoor-install"):
        shutil.copy(os.path.join(ROOT, name), root / name)
    (root / "tools" / "steamdeck" / "install-gui.sh").write_text("#!/bin/sh\necho GUI-INSTALLER-STARTED\n")
    (root / "pentamoor-run").write_text("#!/bin/sh\n")
    (root / "pentamoor-run").chmod(0o755)
    base = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY", "GAMESCOPE_WAYLAND_DISPLAY", "PENTAMOOR_GAME", "PENTAMOOR_MODULE", "PENTAMOOR_RUN")}

    def run(extra, files=True):
        if not files:
            (root / "tools" / "steamdeck" / "install-gui.sh").rename(root / "tools" / "steamdeck" / "x.sh")
        try:
            return subprocess.run(["sh", str(root / "pentamoor")], env=dict(base, **extra), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=60)
        finally:
            if not files:
                (root / "tools" / "steamdeck" / "x.sh").rename(root / "tools" / "steamdeck" / "install-gui.sh")

    r = run({"DISPLAY": ":0"})
    assert "GUI-INSTALLER-STARTED" in r.stdout
    r = run({"WAYLAND_DISPLAY": "wayland-0"})
    assert "GUI-INSTALLER-STARTED" in r.stdout
    r = run({})
    assert "GUI-INSTALLER-STARTED" not in r.stdout and r.returncode == 1 and "pentamoor-install" in r.stdout
    r = run({"DISPLAY": ":0", "GAMESCOPE_WAYLAND_DISPLAY": "gamescope-0"})
    assert "GUI-INSTALLER-STARTED" not in r.stdout and r.returncode == 1
    r = run({"DISPLAY": ":0"}, files=False)
    assert "GUI-INSTALLER-STARTED" not in r.stdout and r.returncode == 1


# ---- the files that are not code ---------------------------------------------------------------------------------------------------------------------------
def parse_text_vdf(text):
    """A small parser for Valve's text VDF ('//' comments, quoted strings, braces): nested dicts, repeated keys become lists of pairs."""
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', re.sub(r"//[^\n]*", "", text))
    pos = 0

    def block():
        nonlocal pos
        pairs = []
        while pos < len(tokens):
            s_, brace = tokens[pos]
            if brace == "}":
                pos += 1
                return pairs
            assert brace == "", "unexpected brace"
            pos += 1
            s2, brace2 = tokens[pos]
            if brace2 == "{":
                pos += 1
                pairs.append((s_, block()))
            else:
                pairs.append((s_, s2))
                pos += 1
        return pairs
    top = block()
    assert pos == len(tokens)
    return top


def get_all(pairs, key):
    return [v for k, v in pairs if k == key]


def test_controller_template_is_well_formed_and_maps_the_gamepad():
    text = open(os.path.join(HERE, "controller_neptune_pentamoor.vdf")).read()
    assert text.count("{") == text.count("}")
    top = parse_text_vdf(text)
    assert [k for k, v in top] == ["controller_mappings"]
    m = top[0][1]
    assert get_all(m, "controller_type") == ["controller_neptune"]
    assert get_all(m, "version") == ["3"]
    groups = get_all(m, "group")
    ids = [get_all(g, "id")[0] for g in groups]
    assert ids == [str(n) for n in range(len(groups))]
    modes = {get_all(g, "id")[0]: get_all(g, "mode")[0] for g in groups}
    # every group is a source of the preset, and every source names a group
    preset = get_all(m, "preset")[0]
    sources = dict(get_all(preset, "group_source_bindings")[0])
    assert sorted(sources) == sorted(ids)
    assert all(v.endswith(" active") for v in sources.values())
    assert len(set(sources.values())) == len(sources)
    known_sources = {"button_diamond", "dpad", "joystick", "right_joystick", "left_trigger", "right_trigger", "switch", "left_trackpad", "right_trackpad"}
    assert {v.split()[0] for v in sources.values()} <= known_sources
    # what every input is bound to
    bound = {}
    for g in groups:
        for name, inp in get_all(g, "inputs")[0]:
            b = get_all(get_all(get_all(get_all(inp, "activators")[0], "Full_Press")[0], "bindings")[0], "binding")
            assert len(b) == 1
            bound[(get_all(g, "id")[0], name)] = b[0]
    allowed = re.compile(r"^(xinput_button (A|B|X|Y|DPAD_UP|DPAD_DOWN|DPAD_LEFT|DPAD_RIGHT|JOYSTICK_LEFT|JOYSTICK_RIGHT|TRIGGER_LEFT|TRIGGER_RIGHT|SHOULDER_LEFT|SHOULDER_RIGHT|START|SELECT)|mouse_button (LEFT|RIGHT))$")
    assert all(allowed.match(v) for v in bound.values()), bound
    values = list(bound.values())
    for want in ("A", "B", "X", "Y", "DPAD_UP", "DPAD_DOWN", "DPAD_LEFT", "DPAD_RIGHT", "SHOULDER_LEFT", "SHOULDER_RIGHT", "START", "SELECT", "TRIGGER_LEFT", "TRIGGER_RIGHT", "JOYSTICK_LEFT", "JOYSTICK_RIGHT"):
        assert values.count("xinput_button " + want) == 1, want                            # pad.c reads each of these once
    assert sorted(v for v in values if v.startswith("mouse_button")) == ["mouse_button LEFT", "mouse_button RIGHT"]
    assert {modes[g] for g, n in bound if modes[g] == "absolute_mouse"} == {"absolute_mouse"}
    # which stick and trigger is which
    for g in groups:
        settings = dict(get_all(g, "settings")[0]) if get_all(g, "settings") else {}
        mode = get_all(g, "mode")[0]
        if mode == "joystick_move":
            assert settings["output_joystick"] in ("1", "2")
        if mode == "trigger":
            assert settings["output_trigger"] in ("1", "2")
    sticks = sorted(dict(get_all(g, "settings")[0])["output_joystick"] for g in groups if get_all(g, "mode")[0] == "joystick_move")
    assert sticks == ["1", "2"]


def test_desktop_files_have_the_keys_and_start_the_installer_from_anywhere(tmp_path):
    names = {"Install Pentamoor.desktop": "", "Add Pentamoor to Steam.desktop": "--steam-only"}
    for fname, flag in names.items():
        path = os.path.join(HERE, "desktop", fname)
        text = open(path).read()
        entries = dict(l.split("=", 1) for l in text.splitlines() if "=" in l)
        assert text.startswith("[Desktop Entry]\n")
        assert entries["Type"] == "Application" and entries["Terminal"] == "false" and entries["Name"] and entries["Exec"] and entries["Icon"]
        # what a launcher does with Exec: split it into words (single quotes protect the shell text), put the file's path where %k is, run it with a fake installer in place
        folder = tmp_path / ("folder " + fname.split()[0])            # a folder name with a space in it
        (folder / "tools" / "steamdeck").mkdir(parents=True)
        out = folder / "ran.txt"
        script = folder / "tools" / "steamdeck" / "install-gui.sh"
        script.write_text('#!/bin/sh\nprintf "%%s\\n" "$0" "$@" > "%s"\n' % out)
        script.chmod(0o755)
        desktop = folder / fname
        shutil.copy(path, desktop)
        words = shlex.split(entries["Exec"])
        assert "%k" in words and not any(w in ("%f", "%F", "%u", "%U") for w in words)
        for location in (str(desktop), "file://" + str(desktop)):
            if out.exists():
                out.unlink()
            words2 = [location if w == "%k" else w for w in words]
            subprocess.run(words2, cwd=str(tmp_path), check=True, timeout=30)
            ran = out.read_text().splitlines()
            assert ran[0].endswith("tools/steamdeck/install-gui.sh") and ran[1:] == ([flag] if flag else [])


def test_the_scripts_are_executable_and_have_a_shebang():
    for name in ("install-gui.sh", "install-run.sh", "add-to-steam.py", "progress.py"):
        p = os.path.join(HERE, name)
        assert open(p).readline().startswith("#!"), name
        if os.name != "nt":
            assert os.stat(p).st_mode & stat.S_IXUSR, name + " is not executable (git update-index --chmod=+x)"


STUB_ZENITY = """#!/bin/sh
printf '%s\\n' "zenity $(echo "$*" | tr '\\n' ' ' | cut -c1-200)" >> "$STUB_LOG"
case "$1" in
  --file-selection) printf '%s\\n' "$STUB_ISO" ;;
  --progress) while IFS= read -r line; do printf '%s\\n' "progress: $line" >> "$STUB_LOG"; done ;;
esac
exit 0
"""


def tool_dir(tmp_path, extra=()):
    """A folder of links to just the programs the installer script needs, so that no kdialog (or a compiler) on this machine is found."""
    d = tmp_path / "tools-only"
    d.mkdir()
    for name in ("sh", "python3", "df", "awk", "mktemp", "tail", "head", "cat", "rm", "tr", "cut", "dirname", "sleep", "grep", "tee", "mkdir", "env", "date", "uname", "basename", "sed", "wc", "ls"):
        p = shutil.which(name)
        if p and name == "python3":
            p = sys.executable
        if p:
            os.symlink(p, d / name)
    for p in extra:
        os.symlink(p, d / os.path.basename(p))
    return d


@pytestmark_gui
def test_install_gui_with_zenity_when_there_is_no_kdialog(tmp_path):
    root, env, log, iso, steam = gui_fixture(tmp_path)
    (tmp_path / "stubs" / "kdialog").unlink()
    (tmp_path / "stubs" / "zenity").write_text(STUB_ZENITY)
    (tmp_path / "stubs" / "zenity").chmod(0o755)
    only = tool_dir(tmp_path)
    env["PATH"] = str(tmp_path / "stubs") + os.pathsep + str(only)
    r = subprocess.run([str(only / "sh"), str(root / "tools" / "steamdeck" / "install-gui.sh")], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True, timeout=120)
    assert r.returncode == 0, r.stdout
    c = calls(log)
    kinds = [re.search(r" (--(?:question|info|error|file-selection|progress)) ", l).group(1) for l in c if l.startswith("zenity")]
    assert kinds == ["--question", "--file-selection", "--progress", "--info", "--question", "--info"], c
    progress = [l for l in c if l.startswith("progress:")]
    assert "progress: # Reading the disc image" in progress and progress[-1] == "progress: 100" and "progress: # Done" in progress
    assert (root / "args.txt").read_text() == f"--yes --clean {iso}"
    assert not [l for l in c if l.startswith("qdbus")]

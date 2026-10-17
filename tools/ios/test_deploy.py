"""Tests for tools/ios/deploy.sh (deploy.py): the parsing of devicectl's JSON, the choice of device, team and bundle id, the commands it builds, the data stamp, and the whole flow against a fake
`xcrun`/`xcodebuild` that keeps a pretend app container in a folder. None of them needs Xcode, a device, a Simulator or the game; they run on Linux as well.

    python -m pytest tools/ios/test_deploy.py

What they cannot say is whether Apple's tools behave the way the fake does (the layout of `devicectl device copy to` for a folder, the JSON of a real iPad, signing): `deploy.sh --selftest` checks the
options against the real help on a Mac, and docs/notes/ios.md lists what only a real iPad can show.
"""
import io
import json
import os
import shutil
import stat
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import deploy as dp  # noqa: E402

DATA = os.path.join(HERE, "testdata")


def load(name):
    with open(os.path.join(DATA, name)) as f:
        return json.load(f)


def opts(*argv):
    return dp.make_parser().parse_args(list(argv))


# ---- names, teams, bundle ids ----

def test_bundle_id_from_user():
    assert dp.default_bundle_id("Ben") == "com.ben.pentamoor"
    assert dp.default_bundle_id("Mary Jane_O'Neil") == "com.mary-jane-o-neil.pentamoor"
    assert dp.default_bundle_id("") == "com.user.pentamoor"
    assert dp.valid_bundle_id("com.ben.pentamoor") and not dp.valid_bundle_id("pentamoor") and not dp.valid_bundle_id("com.be n.x") and not dp.valid_bundle_id("")


def test_team_from_subject():
    mac = "subject= /UID=ABCD1EFGH2/CN=Apple Development: Ben Example (9XYZ12345A)/OU=TEAM123456/O=Ben Example/C=US"
    ssl3 = "subject=UID=ABCD1EFGH2, CN=Apple Development: Ben Example (9XYZ12345A), OU=TEAM123456, O=Ben Example, C=US"
    assert dp.team_from_subject(mac) == "TEAM123456"           # the OU, not the (PERSONID) in the common name
    assert dp.team_from_subject(ssl3) == "TEAM123456"
    assert dp.team_from_subject("subject= /CN=Some Server/O=Example") is None
    assert dp.team_from_subject("subject= /CN=x/OU=short/O=y") is None
    assert dp.cn_from_subject(mac) == "Apple Development: Ben Example (9XYZ12345A)"
    assert dp.valid_team("ABCDE12345") and not dp.valid_team("My Team") and not dp.valid_team("abcde12345") and not dp.valid_team("ABCDE1234")


@pytest.mark.skipif(not shutil.which("openssl"), reason="openssl is needed to make a certificate")
def test_detect_team_reads_certificates(tmp_path):
    """The whole detection, with a fake `security` that prints real PEM certificates: one team is used, two are refused, an expired one does not count."""
    def cert(team, days):
        key, pem = tmp_path / ("k%s%d" % (team, days)), tmp_path / ("c%s%d.pem" % (team, days))
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(pem), "-days", str(days),
                        "-subj", "/UID=U%s/CN=Apple Development: T (PERSON1234)/OU=%s/O=T/C=US" % (team, team)], check=True, capture_output=True)
        return pem.read_text()
    live, other = cert("AAAAA11111", 30), cert("BBBBB22222", 30)

    def detect(*pems):
        bin_dir = tmp_path / ("bin%d" % len(pems) + str(hash(pems) % 1000))
        bin_dir.mkdir()
        (bin_dir / "pems.txt").write_text("".join(pems))
        sec = bin_dir / "security"
        sec.write_text("#!/bin/sh\n[ \"$1\" = find-certificate ] && [ \"$4\" = \"Apple Development\" ] && cat %s\nexit 0\n" % (bin_dir / "pems.txt"))
        sec.chmod(0o755)
        old = os.environ["PATH"]
        os.environ["PATH"] = str(bin_dir) + os.pathsep + old
        try:
            return dp.Deployer(opts("--team", "X"), root=str(tmp_path)).detect_team()
        finally:
            os.environ["PATH"] = old
    assert detect(live, live)[0] == "AAAAA11111"
    with pytest.raises(dp.Fail) as e:
        detect(live, other)
    assert "AAAAA11111" in str(e.value) and "BBBBB22222" in str(e.value) and "Membership" in e.value.hint
    with pytest.raises(dp.Fail) as e:
        detect()
    assert "no valid Apple Development certificate" in str(e.value)


# ---- devicectl's JSON ----

@pytest.fixture(params=["devices-ipad.json", "devices-ipad-properties.json"])
def devices(request):
    return dp.parse_devices(load(request.param))


def test_parse_both_json_shapes(devices):
    d = [x for x in devices if x.name == "Test iPad"][0]
    assert d.udid == "00008132-000A1B2C3D4E5F67" and d.identifier.startswith("11111111") and d.ref == d.udid
    assert d.is_ipad and not d.is_simulator and d.pairing == "paired" and d.link == "USB" and d.os_version == "26.0.1" and d.os_major() == 26
    assert d.marketing == "iPad Pro 13-inch (M5)" and d.product_type == "iPad17,4"
    assert d.developer_mode in ("enabled", "disabled")
    assert "Test iPad" in d.describe() and "iPadOS 26.0.1" in d.describe()


def test_parse_devices_details():
    devs = dp.parse_devices(load("devices-ipad.json"))
    assert [d.name for d in devs] == ["Test iPad", "Test iPhone", "Test Simulator iPad"]
    ipad, phone, sim = devs
    assert ipad.developer_mode == "enabled" and phone.link == "Wi-Fi" and not phone.is_ipad and sim.is_simulator and sim.is_ipad
    assert "test-ipad.coredevice.local" in ipad.keys()
    assert dp.parse_devices(load("devices-ipad-properties.json"))[0].developer_mode == "disabled"


def test_parse_devices_rejects_other_json():
    with pytest.raises(dp.Fail):
        dp.parse_devices({"result": {}})
    with pytest.raises(dp.Fail):
        dp.parse_devices([])


def test_pick_device():
    devs = dp.parse_devices(load("devices-ipad.json"))
    assert dp.pick_device(devs).name == "Test iPad"                      # the only real iPad: not the iPhone, not the Simulator
    for want in ("Test iPad", "test ipad", "00008132-000A1B2C3D4E5F67", "11111111-2222-3333-4444-555555555555", "TESTSERIAL01", "3894327198334758", "Test-iPad.coredevice.local", "test ipa"):
        assert dp.pick_device(devs, want).name == "Test iPad", want
    with pytest.raises(dp.Fail) as e:
        dp.pick_device(devs, "nosuch")
    assert "Test iPad" in e.value.hint and "Simulator" not in e.value.hint
    with pytest.raises(dp.Fail) as e:
        dp.pick_device(devs, "Test Simulator iPad")
    assert "--simulator" in e.value.hint
    with pytest.raises(dp.Fail) as e:
        dp.pick_device(devs, "Test")                                     # matches the iPad, the iPhone and the Simulator by name
    assert "matches 3" in str(e.value)
    with pytest.raises(dp.Fail) as e:
        dp.pick_device([d for d in devs if not d.is_ipad])
    assert "no iPad" in str(e.value) and "cable" in e.value.hint
    twin = dp.Device(json.loads(json.dumps(devs[0].raw).replace("Test iPad", "Other iPad").replace("00008132", "00008133").replace("11111111", "99999999")))
    with pytest.raises(dp.Fail) as e:
        dp.pick_device(devs + [twin])
    assert "2 iPads" in str(e.value) and "Other iPad" in e.value.hint and "--device" in e.value.hint


def test_device_problems():
    good = dp.parse_devices(load("devices-ipad.json"))[0]
    assert dp.device_problems(good) == []

    def changed(**kw):
        d = dp.Device(good.raw)
        for k, v in kw.items():
            setattr(d, k, v)
        return dp.device_problems(d)
    off = changed(developer_mode="disabled")
    assert off[0][0] == "error" and "Developer Mode > on" in off[0][2] and "Privacy & Security" in off[0][2]
    assert [p[0] for p in changed(developer_mode="")] == ["warn"]
    assert "not paired" in changed(pairing="unpaired")[0][1] and "Trust" in changed(pairing="unpaired")[0][2]
    assert "not reachable" in changed(tunnel="unavailable")[0][1]
    assert "needs 15" in changed(os_version="14.8")[0][1]
    assert "not an iPad" in dp.device_problems(dp.parse_devices(load("devices-ipad.json"))[1])[0][1]


def test_lock_state():
    assert dp.lock_state_locked({"result": {"passcodeRequired": True, "unlockedSinceBoot": True}}) is True
    assert dp.lock_state_locked({"result": {"passcodeRequired": False}}) is False
    assert dp.lock_state_locked({"result": {"something": 1}}) is None


def test_simulators():
    doc = {"devices": {"com.apple.CoreSimulator.SimRuntime.iOS-27-0": [
        {"udid": "A" * 8 + "-0000-0000-0000-000000000001", "name": "iPad Pro 13-inch (M5)", "state": "Booted", "isAvailable": True},
        {"udid": "A" * 8 + "-0000-0000-0000-000000000002", "name": "iPad Air", "state": "Shutdown", "isAvailable": True},
        {"udid": "A" * 8 + "-0000-0000-0000-000000000003", "name": "Gone", "state": "Shutdown", "isAvailable": False}],
        "com.apple.CoreSimulator.SimRuntime.iOS-26-5": [
        {"udid": "B" * 8 + "-0000-0000-0000-000000000001", "name": "iPad Pro 13-inch (M5)", "state": "Shutdown", "isAvailable": True}]}}
    sims = dp.parse_simulators(doc)
    assert len(sims) == 3 and sims[0][3] == "iOS-26-5"
    assert dp.pick_simulator(sims, "auto")[1] == "iPad Pro 13-inch (M5)" and dp.pick_simulator(sims, "auto")[2] == "Booted"
    assert dp.pick_simulator(sims, "iPad Air")[0].endswith("2")
    assert dp.pick_simulator(sims, "iPad Pro 13-inch (M5)")[2] == "Booted"         # two have the name: the booted one
    assert dp.pick_simulator(sims, ("B" * 8 + "-0000-0000-0000-000000000001").lower())[3] == "iOS-26-5"
    with pytest.raises(dp.Fail):
        dp.pick_simulator(sims, "nosuch")
    with pytest.raises(dp.Fail):
        dp.pick_simulator([s for s in sims if s[2] != "Booted"], "auto")


# ---- the game's data stamp ----

def make_game(root, extra=None):
    for rel, size in (("Program/MAGIC.EXE", 10), ("Program/DECK.EXE", 20), ("CardArt/a.pic", 30), ("README.TXT", 5)):
        p = os.path.join(root, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(b"x" * size)
    return root


def test_fingerprint(tmp_path):
    g = make_game(str(tmp_path / "Magic"))
    a = dp.fingerprint(g)
    assert a[1:] == (4, 65) and dp.fingerprint(g) == a
    open(os.path.join(g, ".DS_Store"), "w").write("junk")
    open(os.path.join(g, "Program", "._MAGIC.EXE"), "w").write("junk")
    assert dp.fingerprint(g) == a                                         # Finder's files do not count
    open(os.path.join(g, "CardArt", "a.pic"), "wb").write(b"yy")         # a changed size
    assert dp.fingerprint(g)[0] != a[0]
    os.remove(os.path.join(g, "README.TXT"))
    assert dp.fingerprint(g)[1] == 3
    assert dp.stamp_id(dp.make_stamp(a)) == a[0] and dp.stamp_id("not json") is None and dp.stamp_id("[]") is None


# ---- which game code ----

KIT = {"with_sources": False, "xcode": {"version": "27.0"}, "sdk": {"iphoneos": {"version": "27.0"}, "iphonesimulator": {"version": "27.0"}}}


def test_choose_libs():
    assert dp.choose_libs(None, "iphoneos", "27.0")[0] == "sources"
    assert dp.choose_libs(KIT, "iphoneos", "27.0")[0] == "prebuilt"
    assert dp.choose_libs(KIT, "iphoneos", "27.0")[2] is None
    mode, why, warn = dp.choose_libs(KIT, "iphoneos", "26.4")                  # another SDK, no lifted C in the kit: link anyway, say so
    assert mode == "prebuilt" and "26.4" in warn and "--with-sources" in warn
    full = dict(KIT, with_sources=True)
    assert dp.choose_libs(full, "iphoneos", "26.4")[0] == "sources"            # another SDK, lifted C there: compile it
    assert dp.choose_libs(full, "iphoneos", "27.0")[0] == "prebuilt"
    assert dp.choose_libs(full, "iphoneos", "27.0", rebuild=True)[0] == "sources"
    assert dp.choose_libs(full, "iphoneos", "26.4", prebuilt=True)[0] == "prebuilt"
    assert dp.choose_libs(full, "iphoneos", "27.0", have_prebuilt=False)[0] == "sources"
    with pytest.raises(dp.Fail):
        dp.choose_libs(KIT, "iphoneos", "27.0", rebuild=True)
    with pytest.raises(dp.Fail):
        dp.choose_libs(KIT, "iphoneos", "27.0", have_prebuilt=False)
    with pytest.raises(dp.Fail):
        dp.choose_libs(None, "iphoneos", "27.0", prebuilt=True)


# ---- what to say when something fails ----

@pytest.mark.parametrize("text,needle", [
    ("error: No Account for Team \"ABCDE12345\". Add a new account in Accounts settings", "Settings > Accounts"),
    ("error: No profiles for 'com.x.pentamoor' were found: Xcode couldn't find any iOS App Development provisioning profiles", "provisioning profile"),
    ("error: Failed Registering Bundle Identifier: The app identifier \"com.x\" cannot be registered to your development team", "--bundle-id"),
    ("Unable to launch com.x because it has an invalid code signature, inadequate entitlements or its profile has not been explicitly trusted by the user.", "VPN & Device Management"),
    ("ERROR: The device is locked. (com.apple.dt.CoreDeviceError error 1001)", "unlock"),
    ("xcodebuild: error: Unable to find a destination matching the provided destination specifier", "cable"),
    ("error: iOS 27.0 is not installed. Please download and install the platform", "Xcode is too old"),
    ("Developer Mode is disabled on the device", "Privacy & Security"),
    ("ld: warning: object file (x.o) was built for newer 'iOS' version (27.0) than being linked (26.4)", "--with-sources"),
    ("Signing for \"Pentamoor\" requires a development team", "--team"),
])
def test_explain(text, needle):
    assert any(needle in h for h in dp.explain(text)), dp.explain(text)


def test_error_lines_prefers_errors():
    out = "\n".join(["note: line %d" % i for i in range(300)] + ["/x/y.c:3:1: error: use of undeclared identifier 'foo'", "** BUILD FAILED **"])
    assert dp.error_lines(out) == ["/x/y.c:3:1: error: use of undeclared identifier 'foo'"]
    assert dp.error_lines("a\nb\n") == ["a", "b"]


# ---- the commands ----

def all_flags(argv):
    return [a for a in argv if a.startswith("-") and not a.startswith("--json") or a == "--json-output"]


def check_flags_known(argv):
    """Every option in a command is one TOOL_FLAGS lists for that tool (so that --selftest checks all of them)."""
    for tool, flags in dp.TOOL_FLAGS.items():
        if tuple(argv[:len(tool)]) == tool:
            break
    else:
        pytest.fail("no TOOL_FLAGS entry for %s" % argv[:4])
    used = [a for a in argv[len(tool):] if a.startswith("-") and not os.path.exists(a)]
    # (the values that follow options, such as paths, never start with a dash)
    for a in used:
        assert a in flags, "%s uses %s, which --selftest does not check" % (" ".join(tool), a)


def test_every_command_is_in_the_selftest_table():
    dev, b, app = "00008132-000A1B2C3D4E5F67", "com.x.pentamoor", "/p/Pentamoor.app"
    cmds = [dp.cmd_list_devices("/t/d.json"), dp.cmd_lock_state(dev, "/t/l.json"), dp.cmd_files(dev, b, "Documents", "/t/f.json"), dp.cmd_files(dev, b, "Documents", "/t/f.json", recurse=True),
            dp.cmd_install(dev, app), dp.cmd_copy_to(dev, b, "/m", "Documents/Magic"), dp.cmd_copy_from(dev, b, "Documents/pentamoor.log", "/t/log"),
            dp.cmd_launch(dev, b), dp.cmd_launch(dev, b, console=True),
            dp.cmd_build("/p/Pentamoor.xcodeproj", "/d", "platform=iOS,id=" + dev, "ABCDE12345", b),
            dp.cmd_build("/p/Pentamoor.xcodeproj", "/d", "platform=iOS Simulator,id=X", "", b, device=False),
            dp.cmd_sim_install("U", app), dp.cmd_sim_container("U", b), dp.cmd_sim_launch("U", b), dp.cmd_sim_launch("U", b, True), dp.cmd_sim_boot("U"), dp.cmd_sim_list()]
    for c in cmds:
        check_flags_known(c)


def test_command_shapes():
    dev, b = "UDID1", "com.x.pentamoor"
    c = dp.cmd_build("/p/P.xcodeproj", "/d", "platform=iOS,id=UDID1", "ABCDE12345", b)
    assert c[:5] == ["xcodebuild", "-project", "/p/P.xcodeproj", "-scheme", "Pentamoor"] and "-allowProvisioningUpdates" in c and "-allowProvisioningDeviceRegistration" in c
    assert c[-1] == "build"
    assert "DEVELOPMENT_TEAM=ABCDE12345" in c and "PRODUCT_BUNDLE_IDENTIFIER=com.x.pentamoor" in c and c[c.index("-destination") + 1] == "platform=iOS,id=UDID1"
    sim = dp.cmd_build("/p/P.xcodeproj", "/d", "platform=iOS Simulator,id=U", "", b, device=False)
    assert "-allowProvisioningUpdates" not in sim and not [a for a in sim if a.startswith("DEVELOPMENT_TEAM")]
    cp = dp.cmd_copy_to(dev, b, "/m/Magic", "Documents/Magic")
    assert cp[:6] == ["xcrun", "devicectl", "device", "copy", "to", "--device"] and cp[cp.index("--domain-type") + 1] == "appDataContainer" and cp[cp.index("--domain-identifier") + 1] == b
    assert dp.cmd_launch(dev, b)[-2:] == ["--terminate-existing", b] and dp.cmd_launch(dev, b, True)[-2:] == ["--console", b]
    assert dp.built_app_path("/d") == "/d/Build/Products/Release-iphoneos/Pentamoor.app" and dp.built_app_path("/d", False).endswith("Release-iphonesimulator/Pentamoor.app")
    g = dp.cmd_gen_project("/o", "ABCDE12345", b, True, "/kit/prebuilt")
    assert "--entitlements" in g and g[g.index("--prebuilt") + 1] == "/kit/prebuilt" and g[g.index("--team") + 1] == "ABCDE12345"


def test_selftest_flag_search():
    help_text = "  -d, --device <uuid>\n  -r, --recurse/--no-recurse  Recurse\n  -allowProvisioningUpdates   Allow\n  --json-output <p>"
    assert dp.flag_in_help("--device", help_text) and dp.flag_in_help("--no-recurse", help_text) and dp.flag_in_help("-allowProvisioningUpdates", help_text)
    assert not dp.flag_in_help("--dev", help_text) and not dp.flag_in_help("--source", help_text) and not dp.flag_in_help("-allowProvisioning", help_text)


# ---- arguments, and a dry run on a saved device list ----

def test_arguments():
    o = opts("--team", "ABCDE12345", "--dry-run", "--no-data", "--program", "duel")
    assert o.team == "ABCDE12345" and o.dry_run and o.no_data and o.program == "duel" and o.simulator is None
    assert opts("--simulator").simulator == "auto" and opts("--simulator", "UDID").simulator == "UDID"
    with pytest.raises(SystemExit):
        opts("--program", "other")
    assert dp.main(["--data-only", "--no-data"]) == 2
    assert dp.main(["--simulator", "--device", "x"]) == 2


def run_main(capsys, *argv):
    rc = dp.main(list(argv))
    cap = capsys.readouterr()
    return rc, cap.out, cap.err


def test_dry_run_prints_the_commands_and_changes_nothing(tmp_path, capsys):
    game = make_game(str(tmp_path / "Magic"))
    work = tmp_path / "work"
    rc, out, err = run_main(capsys, "--dry-run", "--device-json", os.path.join(DATA, "devices-ipad.json"), "--team", "ABCDE12345", "--bundle-id", "com.test.pentamoor", "--data", game,
                            "--work", str(work), "--program", "duel")
    assert rc == 0, err
    for needle in ("xcodebuild -project", "-destination platform=iOS,id=00008132-000A1B2C3D4E5F67", "DEVELOPMENT_TEAM=ABCDE12345", "PRODUCT_BUNDLE_IDENTIFIER=com.test.pentamoor", "-allowProvisioningUpdates",
                   "xcrun devicectl device install app --device 00008132-000A1B2C3D4E5F67", "xcrun devicectl device copy to --device 00008132-000A1B2C3D4E5F67", "--destination Documents/Magic",
                   "--domain-type appDataContainer --domain-identifier com.test.pentamoor", "--destination Documents/program.txt", "--destination Documents/pentamoor-data.stamp",
                   "xcrun devicectl device process launch --device 00008132-000A1B2C3D4E5F67 --terminate-existing com.test.pentamoor", "gen_xcodeproj.py", "Dry run done"):
        assert needle in out, needle
    assert "[1/8] prerequisites" in out and "[8/8] launch" in out
    assert not work.exists()                                                # nothing was written
    assert [l for l in out.splitlines() if l.startswith("+ ")] == []         # and nothing was run


def test_dry_run_variants(tmp_path, capsys):
    game = make_game(str(tmp_path / "Magic"))
    base = ["--dry-run", "--device-json", os.path.join(DATA, "devices-ipad.json"), "--team", "ABCDE12345", "--data", game, "--work", str(tmp_path / "w")]
    rc, out, _ = run_main(capsys, *base, "--no-data", "--no-launch")
    assert rc == 0 and "copy to" not in out and "process launch" not in out and "[6/6] install" in out
    rc, out, _ = run_main(capsys, *base, "--data-only")
    assert rc == 0 and "xcodebuild" not in out and "install app" not in out and "copy to" in out
    rc, out, _ = run_main(capsys, *base, "--logs")
    assert rc == 0 and "device copy from" in out and "Documents/pentamoor.log" in out and "xcodebuild" not in out
    rc, out, _ = run_main(capsys, *base, "--console")
    assert rc == 0 and "DEVICECTL_CHILD_PENTAMOOR_LOG=console" in out and "--console" in out
    rc, out, _ = run_main(capsys, *base, "--device", "Test iPad", "--no-build")
    assert rc == 0 and "xcodebuild" not in out and "install app" in out


def test_dry_run_stops_at_a_device_that_is_not_ready(tmp_path, capsys):
    rc, out, err = run_main(capsys, "--dry-run", "--device-json", os.path.join(DATA, "devices-ipad-properties.json"), "--team", "ABCDE12345", "--data", make_game(str(tmp_path / "Magic")))
    assert rc == 1 and "Developer Mode is off" in err and "Settings > Privacy & Security > Developer Mode" in err and "xcodebuild" not in out
    rc, out, err = run_main(capsys, "--dry-run", "--device-json", os.path.join(DATA, "devices-ipad.json"), "--data", make_game(str(tmp_path / "Magic")))
    assert rc == 1 and "--team is needed" in err
    rc, out, err = run_main(capsys, "--dry-run", "--device-json", os.path.join(DATA, "devices-ipad.json"), "--team", "My Team", "--data", make_game(str(tmp_path / "Magic")))
    assert rc == 1 and "10-character" in err
    rc, out, err = run_main(capsys, "--dry-run", "--device-json", os.path.join(DATA, "devices-ipad.json"), "--team", "ABCDE12345", "--data", str(tmp_path / "nothing"))
    assert rc == 1 and "MAGIC.EXE" in err and "--no-data" in err
    rc, out, err = run_main(capsys, "--list-devices", "--device-json", os.path.join(DATA, "devices-ipad.json"))
    assert rc == 0 and "Test iPad" in out and "Test iPhone" in out


def test_scripts_parse():
    subprocess.run(["sh", "-n", os.path.join(HERE, "deploy.sh")], check=True)
    r = subprocess.run([sys.executable, os.path.join(HERE, "deploy.py"), "--help"], capture_output=True, text=True)
    assert r.returncode == 0 and "--dry-run" in r.stdout and "--device-json" in r.stdout


def test_python_3_9_syntax():
    """/usr/bin/python3 on a Mac is 3.9: no match statements, no `X | Y` in annotations that run, no parenthesised with-items."""
    import ast
    for name in ("deploy.py", "gen_xcodeproj.py"):
        src = open(os.path.join(HERE, name)).read()
        ast.parse(src, feature_version=(3, 9))


# ---- the whole flow against a fake xcrun / xcodebuild ----

FAKE = r'''#!%(python)s
import json, os, shutil, sys
tool = os.path.basename(sys.argv[0])
a = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps([tool] + a) + "\n")
def opt(name):
    return a[a.index(name) + 1] if name in a else None
def at(path):
    return os.path.join(os.environ["FAKE_CONTAINER"], opt("--domain-identifier") or "none", path)
if tool == "xcodebuild":
    if a[:1] == ["-version"]:
        print("Xcode 27.0\nBuild version 27A266a"); sys.exit(0)
    if os.environ.get("FAKE_BUILD_FAIL"):
        print("note: Building workspace Pentamoor\nerror: No Account for Team \"TEAMID1234\". Add a new account in Accounts settings or verify that your accounts have valid credentials.\n"
              "error: No profiles for 'com.test.pentamoor' were found: Xcode couldn't find any iOS App Development provisioning profiles matching 'com.test.pentamoor'.\n** BUILD FAILED **")
        sys.exit(65)
    app = os.path.join(opt("-derivedDataPath"), "Build", "Products", "Release-iphoneos", "Pentamoor.app")
    os.makedirs(app, exist_ok=True)
    sys.exit(0)
if a[:1] == ["--sdk"]:
    print("27.0"); sys.exit(0)
if a[:1] == ["--find"]:
    print("/usr/bin/" + a[1]); sys.exit(0)
if a[:2] == ["devicectl", "--version"]:
    print("642.16"); sys.exit(0)
if a[:3] == ["devicectl", "list", "devices"]:
    shutil.copy(os.environ["FAKE_DEVICES"], opt("--json-output")); sys.exit(0)
if a[:4] == ["devicectl", "device", "info", "lockState"]:
    json.dump({"result": {"passcodeRequired": os.environ.get("FAKE_LOCKED") == "1"}}, open(opt("--json-output"), "w")); sys.exit(0)
if a[:4] == ["devicectl", "device", "info", "files"]:
    p = at(opt("--subdirectory"))
    if not os.path.isdir(p):
        print("ERROR: no such directory"); sys.exit(1)
    json.dump({"result": {"files": [{"name": n} for n in sorted(os.listdir(p))]}}, open(opt("--json-output"), "w")); sys.exit(0)
if a[:4] == ["devicectl", "device", "install", "app"]:
    sys.exit(0)
if a[:4] == ["devicectl", "device", "process", "launch"]:
    sys.exit(0)
if a[:4] == ["devicectl", "device", "copy", "to"]:
    src, dst = opt("--source"), at(opt("--destination"))
    if os.path.isdir(src):
        if os.environ.get("FAKE_COPY_MODE") == "parent":
            dst = os.path.join(dst, os.path.basename(src))
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
    sys.exit(0)
if a[:4] == ["devicectl", "device", "copy", "from"]:
    src, dst = at(opt("--source")), opt("--destination")
    if not os.path.exists(src):
        print("ERROR: the file does not exist"); sys.exit(1)
    if os.path.isdir(dst):
        dst = os.path.join(dst, os.path.basename(src))
    shutil.copyfile(src, dst)
    sys.exit(0)
print("fake xcrun: not handled: %%s" %% a); sys.exit(9)
'''


@pytest.fixture
def fake(tmp_path, monkeypatch):
    if not shutil.which("make"):
        pytest.skip("make is needed by the project generator")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("xcrun", "xcodebuild"):
        p = bin_dir / name
        p.write_text(FAKE % {"python": sys.executable})
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    kit = tmp_path / "kit"                                                  # a kit's top folder: manifest, prebuilt objects, SDL headers
    (kit / "prebuilt" / "iphoneos").mkdir(parents=True)
    (kit / "prebuilt" / "sdl-include").mkdir()
    for f in ("game_magic.o", "game_deck.o", "game_duel.o", "libSDL2.a"):
        (kit / "prebuilt" / "iphoneos" / f).write_bytes(b"\0")
    (kit / "prebuilt" / "sdl-include" / "SDL.h").write_text("")
    (kit / "kit-manifest.json").write_text(json.dumps(KIT))
    container = tmp_path / "container"
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("FAKE_LOG", str(log))
    monkeypatch.setenv("FAKE_CONTAINER", str(container))
    monkeypatch.setenv("FAKE_DEVICES", os.path.join(DATA, "devices-ipad.json"))
    monkeypatch.delenv("FAKE_LOCKED", raising=False)
    monkeypatch.delenv("FAKE_COPY_MODE", raising=False)
    monkeypatch.setattr(dp, "is_mac", lambda: True)
    game = make_game(str(tmp_path / "Magic"))

    class F(object):
        pass
    f = F()
    f.kit, f.container, f.game, f.tmp = kit, container, game, tmp_path

    def calls(*prefix):
        rows = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
        return [r for r in rows if r[:len(prefix)] == list(prefix)]

    def deploy(*argv):
        out = io.StringIO()
        d = dp.Deployer(opts("--team", "ABCDE12345", "--bundle-id", "com.test.pentamoor", "--data", game, "--work", str(tmp_path / "work"), *argv), root=str(kit), out=out)
        d.run()
        return out.getvalue()
    f.calls, f.deploy = calls, deploy
    return f


def app_dir(f):
    return f.container / "com.test.pentamoor" / "Documents"


def test_flow_first_deploy_then_skip(fake):
    out = fake.deploy()
    assert "[8/8] launch" in out and "Done." in out and "Untrusted Developer" in out
    d = app_dir(fake)
    assert (d / "Magic" / "Program" / "MAGIC.EXE").is_file() and (d / "pentamoor-data.stamp").is_file()
    assert not (d / "Magic" / "Magic").exists()
    assert "(verified)" in out and "copied 4 files" in out
    assert len(fake.calls("xcodebuild", "-project")) == 1
    assert fake.calls("xcrun", "devicectl", "device", "install", "app", "--device", "00008132-000A1B2C3D4E5F67")
    assert fake.calls("xcrun", "devicectl", "device", "process", "launch", "--device", "00008132-000A1B2C3D4E5F67", "--terminate-existing", "com.test.pentamoor")
    copies = len(fake.calls("xcrun", "devicectl", "device", "copy", "to"))
    out = fake.deploy()                                                      # again: a new build and the same data
    assert "already on the iPad" in out and "not copied" in out
    assert len(fake.calls("xcrun", "devicectl", "device", "copy", "to")) == copies
    assert len(fake.calls("xcodebuild", "-project")) == 2 and len(fake.calls("xcrun", "devicectl", "device", "install", "app")) == 2
    out = fake.deploy("--force-data")
    assert "copied 4 files" in out and len(fake.calls("xcrun", "devicectl", "device", "copy", "to")) > copies
    open(os.path.join(fake.game, "Program", "DECK.EXE"), "ab").write(b"more")     # the data changed: copied again
    assert "copied 4 files" in fake.deploy()
    shutil.rmtree(d / "Magic")                                               # the stamp is there but the game is not (deleted in Files)
    out = fake.deploy()
    assert "is gone" in out and (d / "Magic" / "Program" / "MAGIC.EXE").is_file()


def test_flow_when_devicectl_puts_a_folder_inside_the_destination(fake, monkeypatch):
    """`devicectl device copy to` may keep the folder's name inside the destination; the probe notices and the game still ends up at Documents/Magic."""
    monkeypatch.setenv("FAKE_COPY_MODE", "parent")
    out = fake.deploy()
    d = app_dir(fake)
    assert (d / "Magic" / "Program" / "MAGIC.EXE").is_file() and not (d / "Magic" / "Magic").exists() and "(verified)" in out
    dests = [c[c.index("--destination") + 1] for c in fake.calls("xcrun", "devicectl", "device", "copy", "to")]
    assert "Documents" in dests and "Documents/Magic" not in dests


def test_flow_program_and_logs(fake):
    fake.deploy("--program", "duel", "--no-launch")
    assert (app_dir(fake) / "program.txt").read_text() == "duel\n"
    (app_dir(fake) / "pentamoor.log").write_text("line one\nline two\n")
    out = fake.deploy("--logs", "--logs-out", str(fake.tmp / "got.log"))
    assert (fake.tmp / "got.log").read_text() == "line one\nline two\n" and "line two" in out


def test_flow_data_only_and_no_data(fake):
    out = fake.deploy("--data-only")
    assert (app_dir(fake) / "Magic" / "Program" / "MAGIC.EXE").is_file()
    assert not fake.calls("xcodebuild", "-project") and not fake.calls("xcrun", "devicectl", "device", "install", "app")
    fake.deploy("--no-data", "--no-launch")
    assert len(fake.calls("xcodebuild", "-project")) == 1 and "[7/7]" not in fake.deploy("--no-data", "--no-launch")


def test_flow_locked_device_stops(fake, monkeypatch):
    monkeypatch.setenv("FAKE_LOCKED", "1")
    with pytest.raises(dp.Fail) as e:
        fake.deploy()
    assert "locked" in str(e.value) and not fake.calls("xcodebuild", "-project")


def test_flow_no_ipad_connected(fake, monkeypatch):
    monkeypatch.setenv("FAKE_DEVICES", os.path.join(DATA, "devices-ipad-properties.json"))
    with pytest.raises(dp.Fail) as e:                                         # connected, but Developer Mode off
        fake.deploy()
    assert "Developer Mode" in str(e.value)
    assert not fake.calls("xcodebuild", "-project")


# ---- the per-user settings file ----

@pytest.fixture(autouse=True)
def no_real_settings(tmp_path, monkeypatch):
    """No test reads the settings or the team of whoever runs it."""
    monkeypatch.setenv("PENTAMOOR_IOS_CONFIG", str(tmp_path / "no-such-ios.env"))
    for k in dp.CONFIG_KEYS:
        monkeypatch.delenv(k, raising=False)


def test_parse_config():
    text = "# my settings\n\nPENTAMOOR_TEAM=TEAMID1234\nexport PENTAMOOR_BUNDLE_ID = \"com.me.pentamoor\"\nPENTAMOOR_DEVICE='My iPad'\nOTHER=1\nPENTAMOOR_TEAM_X=1\nnot a setting\n$(touch /tmp/x)=1\n"
    assert dp.parse_config(text) == {"PENTAMOOR_TEAM": "TEAMID1234", "PENTAMOOR_BUNDLE_ID": "com.me.pentamoor", "PENTAMOOR_DEVICE": "My iPad"}
    assert dp.parse_config("PENTAMOOR_TEAM=$(echo hi)\n") == {"PENTAMOOR_TEAM": "$(echo hi)"}          # nothing is evaluated
    assert dp.load_config("/nonexistent/ios.env") == {}
    assert dp.config_path({"PENTAMOOR_IOS_CONFIG": "/x/y.env"}) == "/x/y.env"
    assert dp.config_path({}).endswith(os.path.join(".config", "pentamoor", "ios.env"))


def test_setting_precedence(tmp_path, monkeypatch):
    cfg = tmp_path / "ios.env"
    cfg.write_text("PENTAMOOR_TEAM=FILETEAM12\nPENTAMOOR_BUNDLE_ID=com.file.pentamoor\n")
    monkeypatch.setenv("PENTAMOOR_IOS_CONFIG", str(cfg))
    d = dp.Deployer(opts(), root=str(tmp_path))
    assert d.setting("PENTAMOOR_TEAM", "") == ("FILETEAM12", "from %s" % cfg)                    # the file
    monkeypatch.setenv("PENTAMOOR_TEAM", "ENVTEAM123")
    assert d.setting("PENTAMOOR_TEAM", "") == ("ENVTEAM123", "from $PENTAMOOR_TEAM")             # beats the file
    assert d.setting("PENTAMOOR_TEAM", "CLITEAM123") == ("CLITEAM123", "from the command line")   # beats both
    assert d.setting("PENTAMOOR_DEVICE", "") == ("", "")


def test_dry_run_uses_the_settings_file(tmp_path, monkeypatch, capsys):
    cfg = tmp_path / "ios.env"
    cfg.write_text("PENTAMOOR_TEAM=FILETEAM12\nPENTAMOOR_BUNDLE_ID=com.file.pentamoor\nPENTAMOOR_DEVICE=Test iPad\n")
    monkeypatch.setenv("PENTAMOOR_IOS_CONFIG", str(cfg))
    game = make_game(str(tmp_path / "Magic"))
    rc, out, err = run_main(capsys, "--dry-run", "--device-json", os.path.join(DATA, "devices-ipad.json"), "--data", game)
    assert rc == 0, err
    assert "DEVELOPMENT_TEAM=FILETEAM12" in out and "PRODUCT_BUNDLE_IDENTIFIER=com.file.pentamoor" in out and "ios.env" in out
    rc, out, err = run_main(capsys, "--dry-run", "--device-json", os.path.join(DATA, "devices-ipad.json"), "--data", game, "--team", "CLITEAM123")
    assert "DEVELOPMENT_TEAM=CLITEAM123" in out and "FILETEAM12" not in out


@pytest.mark.skipif(not shutil.which("openssl"), reason="openssl is needed to make a certificate")
def test_developer_id_is_not_an_ios_signing_identity(tmp_path, monkeypatch):
    """A keychain with only a Developer ID certificate: no team is guessed from it; the message says what it is and suggests --team."""
    key, pem = tmp_path / "k", tmp_path / "c.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(pem), "-days", "30",
                    "-subj", "/UID=UUUU/CN=Developer ID Application: Someone (TEAMID1234)/OU=TEAMID1234/O=Someone/C=US"], check=True, capture_output=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sec = bin_dir / "security"
    sec.write_text("#!/bin/sh\n[ \"$1\" = find-certificate ] && case \"$4\" in \"Developer ID Application\") cat %s;; esac\nexit 0\n" % pem)
    sec.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ["PATH"])
    with pytest.raises(dp.Fail) as e:
        dp.Deployer(opts(), root=str(tmp_path)).detect_team()
    assert "Developer ID" in str(e.value) and "TEAMID1234" in str(e.value) and "cannot sign an app for a device" in str(e.value)
    assert "--team TEAMID1234" in e.value.hint and "Settings > Accounts" in e.value.hint


def test_flow_signing_failure_is_explained(fake, monkeypatch):
    monkeypatch.setenv("FAKE_BUILD_FAIL", "1")
    with pytest.raises(dp.Fail) as e:
        fake.deploy()
    assert "could not create a provisioning profile for team ABCDE12345" in str(e.value)
    assert "No Account for Team" in str(e.value) and "No profiles for" in str(e.value)       # the relevant xcodebuild lines
    assert "Xcode > Settings > Accounts" in e.value.hint and "re-run" in e.value.hint
    assert not fake.calls("xcrun", "devicectl", "device", "install", "app")

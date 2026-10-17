"""Tests for tools/ios: the Xcode project generator, the build script's flags and pins, the app's Info.plist. None of them needs the game, Xcode or a Simulator (plutil is used when it is there).

    python -m pytest tools/ios
"""
import os
import plistlib
import re
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import gen_xcodeproj as gx  # noqa: E402


def read(*p):
    with open(os.path.join(ROOT, *p)) as f:
        return f.read()


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    out = tmp_path_factory.mktemp("xcode")
    proj = gx.build("ABCDE12345", "org.example.pentamoor", False, str(out))
    return out, proj, read_file(os.path.join(proj, "project.pbxproj"))


def read_file(p):
    with open(p) as f:
        return f.read()


def test_sources_are_the_makefiles():
    srcs = gx.runtime_sources()
    assert len(srcs) == len(set(srcs))
    for s in srcs:
        assert os.path.isfile(os.path.join(ROOT, "src", "port", s)), s
    for needed in ("main.c", "ios_main.c", "iosboot.c", "touch.c", "front_sdl.c", "gamemod.c", "plat_posix.c"):
        assert needed in srcs
    for never in ("plat_win.c", "front_none.c", "stdout.c"):
        assert never not in srcs
    # no test and no generated file in the app
    assert not [s for s in srcs if s.startswith("test_") or s.endswith("_gen.c")]


def test_pbxproj_is_well_formed(project):
    out, proj, text = project
    assert text.startswith("// !$*UTF8*$!")
    assert text.count("{") == text.count("}")          # (the build step's script has unbalanced parentheses of its own: case patterns)
    defined = re.findall(r"^\t\t([0-9A-F]{24}) /\*.*\*/ = ", text, re.M)
    assert len(defined) == len(set(defined)), "an object id is defined twice"
    used = set(re.findall(r"(?:fileRef|target|targetProxy|buildConfigurationList|mainGroup|productRefGroup|productReference|remoteGlobalIDString|containerPortal|rootObject) = ([0-9A-F]{24})", text))
    assert used <= set(defined), "a reference to an object that is not there: %s" % (used - set(defined))
    if shutil.which("plutil"):
        subprocess.run(["plutil", "-lint", os.path.join(proj, "project.pbxproj")], check=True, capture_output=True)


def test_pbxproj_settings(project):
    out, proj, text = project
    for needle in ("PORT_IOS=1", "PORT_STATIC_MODULES=1", "PORT_STATIC_MAGIC=1", "PORT_STATIC_DECK=1", "PORT_STATIC_DUEL=1", "LIFT_BACKEND_FLAT4G=1", "IPHONEOS_DEPLOYMENT_TARGET = 15.0",
                   "TARGETED_DEVICE_FAMILY = 2", "ENABLE_USER_SCRIPT_SANDBOXING = NO", "org.example.pentamoor", "ABCDE12345", "build_ios.sh", "-platform_version", "game_magic.o", "game_deck.o",
                   "game_duel.o", "libSDL2.a", "GameLibs", "UIKit"):
        assert needle in text, needle
    assert "CODE_SIGN_ENTITLEMENTS" not in text                 # off unless asked for
    assert "plat_win.c" not in text and "_gen.c" not in text    # no game-derived source is in the project, only the objects the first step builds
    assert os.path.isfile(os.path.join(proj, "xcshareddata", "xcschemes", "Pentamoor.xcscheme"))


def test_entitlements_only_when_asked(tmp_path):
    proj = gx.build("", "org.example.x", True, str(tmp_path))
    text = read_file(os.path.join(proj, "project.pbxproj"))
    assert "CODE_SIGN_ENTITLEMENTS" in text and "Pentamoor.entitlements" in text
    assert "DevelopmentTeam" not in text
    ent = plistlib.loads(open(os.path.join(HERE, "Pentamoor.entitlements"), "rb").read())
    assert ent == {"com.apple.developer.kernel.extended-virtual-addressing": True, "com.apple.developer.kernel.increased-memory-limit": True}


def test_deterministic(tmp_path):
    a = gx.build("", "org.example.x", False, str(tmp_path / "a"))
    b = gx.build("", "org.example.x", False, str(tmp_path / "b"))
    ta, tb = read_file(os.path.join(a, "project.pbxproj")), read_file(os.path.join(b, "project.pbxproj"))
    assert ta.replace(str(tmp_path / "a"), "@") == tb.replace(str(tmp_path / "b"), "@")


def test_cli_refuses_a_name_for_a_team():
    r = subprocess.run([sys.executable, os.path.join(HERE, "gen_xcodeproj.py"), "--team", "My Team", "--out", "/nonexistent-should-not-be-made"], capture_output=True, text=True)
    assert r.returncode != 0 and "10-character" in (r.stderr + r.stdout)


def test_info_plist(tmp_path):
    p = tmp_path / "Info.plist"
    gx.info_plist(str(p))
    d = plistlib.loads(p.read_bytes())
    assert d["UIRequiresFullScreen"] is True
    assert d["UISupportedInterfaceOrientations"] == ["UIInterfaceOrientationLandscapeLeft", "UIInterfaceOrientationLandscapeRight"]
    assert d["UIFileSharingEnabled"] is True and d["LSSupportsOpeningDocumentsInPlace"] is True
    assert d["UIStatusBarHidden"] is True and d["UIApplicationSupportsIndirectInputEvents"] is True and d["GCSupportsControllerUserInteraction"] is True
    assert d["UILaunchScreen"] == {}                        # without it the app runs in a letterboxed compatibility size
    assert d["CFBundleIdentifier"] == "$(PRODUCT_BUNDLE_IDENTIFIER)" and d["CFBundleExecutable"] == "$(EXECUTABLE_NAME)"


def test_script_info_plist_template():
    """Info.plist.in as build_ios.sh fills it: every placeholder is one the script replaces."""
    body = read("tools", "ios", "Info.plist.in")
    script = read("tools", "ios", "build_ios.sh")
    for ph in set(re.findall(r"@([A-Z_]+)@", body)):
        assert "@%s@" % ph in script, ph
    text = '<?xml version="1.0"?><plist version="1.0"><dict>' + body.replace("@BUNDLE_ID@", "x.y").replace("@MIN@", "15.0").replace("@PLATFORM@", "iPhoneSimulator") + "</dict></plist>"
    assert plistlib.loads(text.encode())["MinimumOSVersion"] == "15.0"


def test_module_flags_are_the_makefiles():
    """What build_ios.sh compiles the lifted C with is what the Makefile's MODFLAGS says (plus -fno-common, and the entry point's name)."""
    mk = read("src", "port", "Makefile")
    m = re.search(r"^MODFLAGS = (-std=gnu99 -O1 -w \$\(EXTRA\) -fPIC -fvisibility=hidden .*)$", mk, re.M)
    assert m, "MODFLAGS (POSIX) not found"
    flags = [f for f in m.group(1).split() if not f.startswith("$(") and not f.startswith("-I")]
    sh = read("tools", "ios", "build_ios.sh")
    line = [l for l in sh.splitlines() if "-DLIFT_MODULE" in l and "$CC" in l]
    assert line, "the module compile line of build_ios.sh"
    for f in flags:
        assert f in line[0].split(), f


def test_sdl_pin_is_the_macos_one():
    def pin(name):
        t = read("tools", name)
        return re.search(r"^SDL_VERSION=(\S+)", t, re.M).group(1), re.search(r"^SDL_SHA256=(\S+)", t, re.M).group(1)
    assert pin("ios/build_ios.sh") == pin("release/build_macos.sh")


@pytest.mark.parametrize("script", ["build_ios.sh", "sim.sh"])
def test_scripts_parse(script):
    subprocess.run(["sh", "-n", os.path.join(HERE, script)], check=True)


def test_no_game_in_this_folder():
    """Nothing here is game data: small text files, scripts and no binary."""
    for f in os.listdir(HERE):
        p = os.path.join(HERE, f)
        if os.path.isfile(p):
            assert os.path.getsize(p) < 200_000, f
            with open(p, "rb") as fh:
                assert b"\0" not in fh.read(), f

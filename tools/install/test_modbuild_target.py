"""Tests of modbuild's --target: building the game modules for another system or processor than this machine's. No game files, no cross compiler and no network are needed: the
command lines, the names of the results and the choice of compiler are checked with stand-ins for the compiler.   python3 -m pytest tools/install"""
import os
import sys
import types

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

import modbuild  # noqa: E402
from test_release import FakeRun, fake_gen  # noqa: E402


def fake_host(monkeypatch, os_name, arch):
    monkeypatch.setattr(modbuild, "host_os", lambda: os_name)
    monkeypatch.setattr(modbuild, "host_arch", lambda: arch)


# ---- the targets ------------------------------------------------------------------------------------------------------------------------------------------
def test_targets_are_named_by_system_and_processor():
    assert set(modbuild.TARGETS) == {"windows-x86_64", "linux-x86_64", "linux-aarch64", "macos-arm64", "macos-x86_64"}
    for name, t in modbuild.TARGETS.items():
        assert t.name == name and t.os in ("windows", "linux", "darwin") and t.arch in ("x86_64", "aarch64")
        assert modbuild.module_ext(t.os) == {"windows": "dll", "linux": "so", "darwin": "dylib"}[t.os]
    assert modbuild.TARGETS["linux-x86_64"].zig == "x86_64-linux-gnu.2.35"                  # the glibc of the release runtime's build machine, not the newest
    assert modbuild.TARGETS["windows-x86_64"].zig == "x86_64-windows-gnu"
    assert modbuild.TARGETS["macos-arm64"].apple_arch == "arm64" and modbuild.TARGETS["macos-x86_64"].apple_arch == "x86_64"


def test_parse_target():
    assert modbuild.parse_target(None) is None and modbuild.parse_target("") is None
    assert modbuild.parse_target("windows-x86_64") is modbuild.TARGETS["windows-x86_64"]
    t = modbuild.parse_target("x86_64-windows-gnu")                                          # a Zig triple stands for its target, and Zig is told it as given
    assert (t.name, t.os, t.arch, t.zig) == ("windows-x86_64", "windows", "x86_64", "x86_64-windows-gnu")
    t = modbuild.parse_target("aarch64-macos")
    assert (t.name, t.os, t.arch, t.zig, t.apple_arch) == ("macos-arm64", "darwin", "aarch64", "aarch64-macos", "arm64")
    t = modbuild.parse_target("x86_64-linux-gnu.2.28")
    assert (t.name, t.os, t.zig) == ("linux-x86_64", "linux", "x86_64-linux-gnu.2.28")
    for bad in ("plan9-x86_64", "x86_64", "riscv64-linux-gnu", "amd64-solaris"):
        with pytest.raises(modbuild.BuildError) as e:
            modbuild.parse_target(bad)
        assert "unknown target" in str(e.value) and "windows-x86_64" in str(e.value)


def test_is_native(monkeypatch):
    fake_host(monkeypatch, "darwin", "aarch64")
    assert modbuild.TARGETS["macos-arm64"].is_native() and not modbuild.TARGETS["macos-x86_64"].is_native()
    assert not modbuild.TARGETS["linux-x86_64"].is_native() and not modbuild.TARGETS["windows-x86_64"].is_native()


# ---- the command lines ------------------------------------------------------------------------------------------------------------------------------------
def test_no_target_changes_nothing():
    """The native build's commands, with and without the new arguments left at their defaults."""
    for argv in (["gcc"], ["clang"], ["/z/zig", "cc"]):
        cc = modbuild.Compiler(argv)
        for os_name in ("linux", "darwin", "windows"):
            assert modbuild.compile_command(cc, "a.c", "a.o", "N", os_name) == modbuild.compile_command(cc, "a.c", "a.o", "N", os_name, None)
            assert modbuild.compile_command(cc, "a.c", "a.o", "N", os_name) == cc.argv + modbuild.compile_flags(cc.kind, "N", os_name) + ["-c", "-o", "a.o", "a.c"]
            assert modbuild.link_command(cc, ["a.o"], "m", os_name) == cc.argv + modbuild.link_flags(cc.kind, os_name) + ["-o", "m", "a.o", "-lm"]
    assert modbuild.target_args(modbuild.Compiler(["gcc"]), None) == []


def test_zig_is_told_the_target_for_the_compile_and_the_link():
    cc = modbuild.Compiler(["/z/zig", "cc"])
    win = modbuild.TARGETS["windows-x86_64"]
    cmd = modbuild.compile_command(cc, "a_gen.c", "a.o", "N", target=win)
    assert cmd[:4] == ["/z/zig", "cc", "-target", "x86_64-windows-gnu"] and "-fPIC" not in cmd and "-fvisibility=hidden" not in cmd      # a Windows image needs neither
    assert "-DLIFT_MODULE" in cmd and "-O1" in cmd and cmd[-4:] == ["-c", "-o", "a.o", "a_gen.c"]
    assert modbuild.link_command(cc, ["a.o", "b.o"], "m.dll", target=win) == ["/z/zig", "cc", "-target", "x86_64-windows-gnu", "-shared", "-o", "m.dll", "a.o", "b.o", "-lm"]
    lin = modbuild.compile_command(cc, "a_gen.c", "a.o", "N", target=modbuild.TARGETS["linux-x86_64"])
    assert lin[2:4] == ["-target", "x86_64-linux-gnu.2.35"] and "-fPIC" in lin and "-fvisibility=hidden" in lin
    mac = modbuild.link_command(cc, ["a.o"], "m.dylib", target=modbuild.TARGETS["macos-arm64"])
    assert mac[2:5] == ["-target", "aarch64-macos.11.0", "-dynamiclib"]
    # the target decides the flags, whatever target_os says
    assert modbuild.compile_command(cc, "a.c", "a.o", "N", "linux", win) == cmd[:-1] + ["a.c"]


def test_a_zig_native_target_is_still_told_its_target():
    """Zig is a cross compiler everywhere: for it even this machine's own target is spelled out (the glibc and macOS versions are part of the choice)."""
    cc = modbuild.Compiler(["/z/zig", "cc"])
    assert modbuild.target_args(cc, modbuild.TARGETS["linux-x86_64"]) == ["-target", "x86_64-linux-gnu.2.35"]


def test_apple_clang_builds_either_processor_of_a_mac(monkeypatch):
    fake_host(monkeypatch, "darwin", "aarch64")
    cc = modbuild.Compiler(["/usr/bin/clang"])
    intel = modbuild.TARGETS["macos-x86_64"]
    assert modbuild.target_args(cc, intel) == ["-arch", "x86_64", "-mmacosx-version-min=11.0"]
    assert modbuild.target_args(cc, modbuild.TARGETS["macos-arm64"]) == []                  # this machine's own: untouched, as a native build
    assert modbuild.compile_command(cc, "a.c", "a.o", "N", target=intel)[:4] == ["/usr/bin/clang", "-arch", "x86_64", "-mmacosx-version-min=11.0"]
    assert modbuild.link_command(cc, ["a.o"], "m.dylib", target=intel) == ["/usr/bin/clang", "-arch", "x86_64", "-mmacosx-version-min=11.0", "-dynamiclib", "-o", "m.dylib", "a.o", "-lm"]


def test_a_system_compiler_cannot_be_pointed_at_another_system(monkeypatch):
    fake_host(monkeypatch, "linux", "x86_64")
    with pytest.raises(modbuild.BuildError) as e:
        modbuild.target_args(modbuild.Compiler(["gcc"]), modbuild.TARGETS["windows-x86_64"])
    assert "needs Zig" in str(e.value)
    fake_host(monkeypatch, "darwin", "aarch64")
    with pytest.raises(modbuild.BuildError):
        modbuild.target_args(modbuild.Compiler(["/usr/bin/clang"]), modbuild.TARGETS["linux-x86_64"])
    fake_host(monkeypatch, "linux", "x86_64")
    assert modbuild.target_args(modbuild.Compiler(["gcc"]), modbuild.TARGETS["linux-x86_64"]) == []


# ---- the names of the results -----------------------------------------------------------------------------------------------------------------------------
def test_modules_are_named_for_the_target_not_the_machine(tmp_path, monkeypatch):
    fake_host(monkeypatch, "linux", "x86_64")
    gen, port, native = fake_gen(tmp_path)
    cc = modbuild.Compiler(["/z/zig", "cc"])
    expect = {"windows-x86_64": "game_deck.dll", "linux-x86_64": "game_deck.so", "macos-arm64": "game_deck.dylib", "macos-x86_64": "game_deck.dylib"}
    for name, file_name in expect.items():
        target = modbuild.TARGETS[name]
        p = modbuild.plan(["deck"], str(gen), str(port), str(native), str(tmp_path / "obj" / name), str(tmp_path / "out" / name), cc, target=target)["deck"]
        assert p["out"] == str(tmp_path / "out" / name / file_name)
        assert all(c[2][2:4] == ["-target", target.zig] for c in p["compile"])
        assert p["link"][2:4] == ["-target", target.zig] and p["link"][-1] == "-lm" and os.path.basename(p["link"][p["link"].index("-o") + 1]) == "game_deck.tmp" + os.path.splitext(file_name)[1]
        assert all(o.startswith(str(tmp_path / "obj" / name)) for o in p["objs"])          # each target's objects are kept apart from the others'
    # without a target the module is named for this machine, as before
    assert modbuild.plan(["deck"], str(gen), str(port), str(native), "o", "out", cc)["deck"]["out"] == os.path.join("out", "game_deck.so")


def test_build_modules_for_a_target(tmp_path, monkeypatch):
    fake_host(monkeypatch, "linux", "x86_64")
    gen, port, native = fake_gen(tmp_path)
    run, lines = FakeRun(), []
    cc = modbuild.Compiler(["/z/zig", "cc"])
    win = modbuild.TARGETS["windows-x86_64"]
    out = tmp_path / "out"
    made = modbuild.build_modules(["deck"], str(gen), str(port), str(native), str(tmp_path / "obj"), str(out), cc, jobs=1, say=lines.append, runner=run, target=win)
    assert made == {"deck": str(out / "game_deck.dll")} and os.path.exists(made["deck"])
    assert all(c[2:4] == ["-target", "x86_64-windows-gnu"] for c in run.commands) and len(run.commands) == 5            # four compiles and a link
    assert "linking game_deck.dll" in "\n".join(lines)


def test_the_import_library_zig_writes_for_a_dll_is_not_left_in_the_output(tmp_path, monkeypatch):
    fake_host(monkeypatch, "linux", "x86_64")
    gen, port, native = fake_gen(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "mine.lib").write_text("kept: it was there before")

    class LinkMakesLib(FakeRun):
        def __call__(self, cmd, env=None, timeout=None, cwd=None):
            r = super().__call__(cmd, env, timeout, cwd)
            if "-shared" in cmd:                                                             # Zig names the import library after the first object, beside the output
                (out / "handlers_gen.lib").write_text("x")
                (out / "game_deck.tmp.pdb").write_text("x")
            return r

    cc = modbuild.Compiler(["/z/zig", "cc"])
    modbuild.build_modules(["deck"], str(gen), str(port), str(native), str(tmp_path / "obj"), str(out), cc, jobs=1, say=lambda m: None, runner=LinkMakesLib(),
                           target=modbuild.TARGETS["windows-x86_64"])
    assert sorted(os.listdir(out)) == ["game_deck.dll", "mine.lib"]


# ---- choosing the compiler for a target -------------------------------------------------------------------------------------------------------------------
def test_native_target_is_find_compilers_choice(tmp_path, monkeypatch):
    fake_host(monkeypatch, "linux", "x86_64")
    seen = []

    def prober(cc, native_dir, target_os=None, timeout=0):
        seen.append(cc.argv)
        return True, "gcc 13"

    which = {"cc": "/bin/cc"}.get
    for target in (None, modbuild.TARGETS["linux-x86_64"]):
        cc = modbuild.find_target_compiler(target, str(tmp_path), str(tmp_path / "tools"), say=lambda m: None, which=which, prober=prober, tools_missing=lambda: False)
        assert cc.argv == ["/bin/cc"]
    assert seen == [["/bin/cc"], ["/bin/cc"]]


def test_another_system_is_built_with_zig(tmp_path, monkeypatch):
    fake_host(monkeypatch, "linux", "x86_64")
    tools = str(tmp_path / "tools")
    fetched, probed = [], []

    def fetch(tools_dir, say):
        fetched.append(tools_dir)
        os.makedirs(os.path.join(tools_dir, "ziglang"))
        with open(os.path.join(tools_dir, "ziglang", "zig.exe" if os.name == "nt" else "zig"), "w") as f:
            f.write("")

    def prober(cc, native_dir, target_os=None, timeout=0, target=None):
        probed.append((cc.kind, target.name))
        return True, "0.16.0"

    def find(target, **kw):
        return modbuild.find_target_compiler(target, str(tmp_path), tools, say=lambda m: None, which={"cc": "/bin/cc", "gcc": "/bin/gcc"}.get, prober=prober, fetch=fetch,
                                             tools_missing=lambda: False, **kw)

    with pytest.raises(modbuild.BuildError) as e:
        find(modbuild.TARGETS["windows-x86_64"], download=False)                             # the system's gcc is not even tried: it cannot build for Windows
    assert "switched off" in str(e.value) and not probed
    cc = find(modbuild.TARGETS["windows-x86_64"], ask=lambda q: True)
    assert cc.kind == "zig" and cc.version == "zig 0.16.0" and fetched == [tools] and probed == [("zig", "windows-x86_64")]
    assert cc.env["ZIG_GLOBAL_CACHE_DIR"].startswith(tools)
    assert find(modbuild.TARGETS["macos-arm64"], ask=lambda q: pytest.fail("Zig is there")).kind == "zig"           # the other target of Zig's, no second download
    assert fetched == [tools]
    assert find(modbuild.TARGETS["linux-aarch64"], explicit="zig").kind == "zig"


def test_a_mac_target_on_a_mac_uses_the_system_clang_before_zig(tmp_path, monkeypatch):
    fake_host(monkeypatch, "darwin", "aarch64")
    probed = []

    def prober(cc, native_dir, target_os=None, timeout=0, target=None):
        probed.append(cc.argv[0])
        return cc.argv[0] == "/usr/bin/clang", "Apple clang 17"

    def fetch(tools_dir, say):
        pytest.fail("no Zig is needed")

    cc = modbuild.find_target_compiler(modbuild.TARGETS["macos-x86_64"], str(tmp_path), str(tmp_path / "t"), say=lambda m: None,
                                       which={"cc": "/usr/bin/cc", "clang": "/usr/bin/clang"}.get, prober=prober, fetch=fetch, tools_missing=lambda: False)
    assert cc.argv == ["/usr/bin/clang"] and cc.version == "Apple clang 17" and probed == ["/usr/bin/cc", "/usr/bin/clang"]


def test_an_explicit_compiler_is_tried_for_the_target(tmp_path, monkeypatch):
    fake_host(monkeypatch, "linux", "x86_64")

    def prober(cc, native_dir, target_os=None, timeout=0, target=None):
        return cc.argv[0] == sys.executable, "ok" if cc.argv[0] == sys.executable else "no good"

    win = modbuild.TARGETS["windows-x86_64"]
    cc = modbuild.find_target_compiler(win, str(tmp_path), str(tmp_path / "t"), explicit=sys.executable, say=lambda m: None, prober=prober)
    assert cc.argv == [sys.executable]
    with pytest.raises(modbuild.BuildError) as e:
        modbuild.find_target_compiler(win, str(tmp_path), str(tmp_path / "t"), explicit="no-such-compiler-xyz", say=lambda m: None, prober=prober)
    assert "was not found" in str(e.value)
    with pytest.raises(modbuild.BuildError) as e:
        modbuild.find_target_compiler(win, str(tmp_path), str(tmp_path / "t"), explicit=os.path.realpath(os.__file__), say=lambda m: None, prober=prober)
    assert "cannot build a shared library for windows-x86_64" in str(e.value)


def test_probe_reports_a_compiler_that_cannot_reach_the_target(tmp_path, monkeypatch):
    fake_host(monkeypatch, "linux", "x86_64")
    ok, detail = modbuild.probe(modbuild.Compiler(["gcc"]), str(tmp_path), target=modbuild.TARGETS["windows-x86_64"])
    assert not ok and "needs Zig" in detail


# ---- the command line -------------------------------------------------------------------------------------------------------------------------------------
def test_command_line_lists_targets_and_refuses_an_unknown_one(capsys):
    lines = []
    assert modbuild.main(["--list-targets"], say=lines.append) == 0
    assert [l.split()[0] for l in lines] == list(modbuild.TARGETS)
    assert modbuild.main(["--target", "amiga-m68k"], say=lines.append) == 1
    assert "unknown target" in lines[-1]


def test_command_line_reports_a_compiler_that_does_not_work(tmp_path):
    lines = []
    assert modbuild.main(["--gen", str(tmp_path / "nothing"), "--programs", "deck", "--out", str(tmp_path / "out"), "--build-dir", str(tmp_path / "obj"),
                          "--compiler", sys.executable, "--target", "x86_64-windows-gnu"], say=lines.append) == 1
    assert "cannot build a shared library for windows-x86_64" in lines[-1]
    assert not os.path.exists(tmp_path / "out")


def test_command_line_builds_the_stub_module_natively(tmp_path):
    """The real command line on the small stub game of src/port/stubgame (no game files); needs a C compiler here."""
    port, native = os.path.join(ROOT, "src", "port"), os.path.join(ROOT, "src", "native")
    if not os.path.exists(os.path.join(port, "stubgame", "handlers_gen.c")):
        pytest.skip("no stub game in this folder")
    if not any(modbuild.probe(modbuild.Compiler([p]), native)[0] for p in modbuild.system_candidates()):
        pytest.skip("no working C compiler on the PATH")
    lines = []
    rc = modbuild.main(["--programs", "stubgame", "--gen", port, "--out", str(tmp_path / "out"), "--build-dir", str(tmp_path / "obj"), "--root", ROOT], say=lines.append)
    assert rc == 0, lines
    assert os.path.exists(tmp_path / "out" / f"game_stubgame.{modbuild.module_ext()}")


def test_strip_adds_the_linkers_s_flag_except_on_a_mac():
    cc = modbuild.Compiler(["/z/zig", "cc"])
    lin, mac = modbuild.TARGETS["linux-x86_64"], modbuild.TARGETS["macos-arm64"]
    assert modbuild.link_command(cc, ["a.o"], "m.so", target=lin, strip=True) == ["/z/zig", "cc", "-target", "x86_64-linux-gnu.2.35", "-shared", "-s", "-o", "m.so", "a.o", "-lm"]
    assert modbuild.link_command(cc, ["a.o"], "m.so", target=lin) == modbuild.link_command(cc, ["a.o"], "m.so", target=lin, strip=False)
    assert "-s" not in modbuild.link_command(cc, ["a.o"], "m.dylib", target=mac, strip=True)
    assert "-s" in modbuild.link_command(cc, ["a.o"], "m.dll", target=modbuild.TARGETS["windows-x86_64"], strip=True)
    gcc = modbuild.Compiler(["gcc"])
    assert modbuild.link_command(gcc, ["a.o"], "m.so", "linux") == ["gcc", "-shared", "-o", "m.so", "a.o", "-lm"]        # native, as ever
    assert modbuild.link_command(gcc, ["a.o"], "m.so", "linux", strip=True)[1:3] == ["-shared", "-s"]


def test_plan_passes_strip_to_the_link_only(tmp_path, monkeypatch):
    fake_host(monkeypatch, "linux", "x86_64")
    gen, port, native = fake_gen(tmp_path)
    cc = modbuild.Compiler(["/z/zig", "cc"])
    p = modbuild.plan(["deck"], str(gen), str(port), str(native), "o", "out", cc, target=modbuild.TARGETS["linux-x86_64"], strip=True)["deck"]
    assert "-s" in p["link"] and all("-s" not in c[2] for c in p["compile"])

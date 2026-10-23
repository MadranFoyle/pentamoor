"""Tests of the release machinery, with no game files: the compiler choice, the module build commands, Zig's download, the lifter's command lines, the archive layout and the launcher.
    python3 -m pytest tools/install"""
import hashlib
import os
import stat
import subprocess
import sys
import tarfile
import types
import zipfile

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools", "release"))

import liftrun  # noqa: E402
import manifest  # noqa: E402
import modbuild  # noqa: E402
import zigdl  # noqa: E402


# ---- the module build in Python (what a release does instead of make) -------------------------------------------------------------------------------------
def makefile_lines():
    path = os.path.join(ROOT, "src", "port", "Makefile")
    if not os.path.exists(path):
        pytest.skip("no Makefile in a release")
    with open(path) as f:
        return f.read().splitlines()


def test_module_flags_are_the_makefiles():
    lines = makefile_lines()
    mods = [l.split("=", 1)[1].split() for l in lines if l.startswith("MODFLAGS =")]
    assert len(mods) == 2                                                       # Windows first, then the others

    def clean(flags):
        return [f for f in flags if f not in ("$(EXTRA)", "-I../native")]
    assert modbuild.compile_flags("gcc", "NATIVE", "windows")[:-2] == clean(mods[0])
    assert modbuild.compile_flags("gcc", "NATIVE", "linux")[:-2] == clean(mods[1])
    assert modbuild.compile_flags("clang", "NATIVE", "darwin")[:-2] == clean(mods[1])
    assert modbuild.compile_flags("gcc", "NATIVE", "linux")[-2:] == ["-I", "NATIVE"]
    soflags = {l.split("=", 1)[1].strip() for l in lines if l.startswith("SOFLAGS =")}
    assert soflags == {"-shared -static-libgcc", "-dynamiclib", "-shared"}
    assert modbuild.link_flags("gcc", "windows") == ["-shared", "-static-libgcc"]
    assert modbuild.link_flags("gcc", "darwin") == ["-dynamiclib"]
    assert modbuild.link_flags("gcc", "linux") == ["-shared"]
    assert modbuild.link_flags("zig", "windows") == ["-shared"]                # Zig has no libgcc to leave out
    assert [l for l in lines if "$(CC) $$(SOFLAGS) -o $$@ $$(MODOBJS_$(1)) -lm" in l]       # the link line: flags, output, objects, -lm


def test_module_commands():
    cc = modbuild.Compiler(["/z/zig", "cc"])
    assert cc.kind == "zig"
    cmd = modbuild.compile_command(cc, "a_gen.c", "a.o", "N", "linux")
    assert cmd[:2] == ["/z/zig", "cc"] and cmd[-4:] == ["-c", "-o", "a.o", "a_gen.c"] and "-fPIC" in cmd and "-DLIFT_MODULE" in cmd and "-w" in cmd
    assert "-fPIC" not in modbuild.compile_command(cc, "a_gen.c", "a.o", "N", "windows")
    link = modbuild.link_command(modbuild.Compiler(["gcc"]), ["a.o", "b.o"], "game_magic.so", "linux")
    assert link == ["gcc", "-shared", "-o", "game_magic.so", "a.o", "b.o", "-lm"]
    assert modbuild.module_ext("darwin") == "dylib" and modbuild.module_ext("windows") == "dll" and modbuild.module_ext("linux") == "so"
    assert modbuild.compiler_kind(["clang-17"]) == "clang" and modbuild.compiler_kind(["x86_64-w64-mingw32-gcc"]) == "gcc"
    assert modbuild.compiler_kind(["python", "-m", "ziglang", "cc"]) == "zig"
    assert modbuild.split_command("zig cc") == ["zig", "cc"]


def fake_gen(base, with_modules=True):
    gen = base / "gen" / "lift_deck"
    gen.mkdir(parents=True)
    (gen / "handlers_gen.c").write_text("int a;\n" * 1000)
    (gen / "deckdll_gen.c").write_text("int b;\n")
    if with_modules:
        (gen / "modules_gen.c").write_text("int m;\n")
    (gen / "deck_spec.json").write_text("{}")
    port = base / "port"
    port.mkdir()
    (port / "modglue.c").write_text("int g;\n")
    (port / "modules_none.c").write_text("int n;\n")
    native = base / "native"
    native.mkdir()
    (native / "lift_rt.h").write_text("")
    (native / "lift_tables.h").write_text("")
    return base / "gen", port, native


def test_program_sources(tmp_path):
    gen, port, native = fake_gen(tmp_path)
    names = [os.path.basename(s) for s in modbuild.program_sources(str(gen / "lift_deck"), str(port))]
    assert names == ["deckdll_gen.c", "handlers_gen.c", "modules_gen.c", "modglue.c"]       # the *_gen.c files, then the glue; no modules_none.c: the lifter wrote the list
    other = tmp_path / "b"
    other.mkdir()
    gen, port, native = fake_gen(other, with_modules=False)
    names = [os.path.basename(s) for s in modbuild.program_sources(str(gen / "lift_deck"), str(port))]
    assert names[-2:] == ["modglue.c", "modules_none.c"]
    with pytest.raises(modbuild.BuildError):
        modbuild.program_sources(str(tmp_path / "nothing"), str(port))


class FakeRun:
    """A stand-in for the compiler: records the commands, makes the output file, and fails on a file name if told to."""

    def __init__(self, fail_on=None):
        self.commands, self.fail_on = [], fail_on

    def __call__(self, cmd, env=None, timeout=None, cwd=None):
        self.commands.append(cmd)
        if self.fail_on and any(self.fail_on in c for c in cmd):
            return types.SimpleNamespace(returncode=1, stdout="a.c:1: error: boom\n")
        if "-o" in cmd:
            with open(cmd[cmd.index("-o") + 1], "w") as f:
                f.write("x")
        return types.SimpleNamespace(returncode=0, stdout="")


def test_build_modules_compiles_then_links_and_reports_progress(tmp_path):
    gen, port, native = fake_gen(tmp_path)
    run, lines = FakeRun(), []
    cc = modbuild.Compiler(["cc"])
    args = (["deck"], str(gen), str(port), str(native), str(tmp_path / "obj"), str(tmp_path / "out"), cc)
    made = modbuild.build_modules(*args, jobs=1, say=lines.append, target_os="linux", runner=run)
    assert made == {"deck": str(tmp_path / "out" / "game_deck.so")} and os.path.exists(made["deck"]) and not os.path.exists(modbuild.tmp_name(made["deck"]))
    compiles = [c for c in run.commands if "-c" in c]
    assert len(compiles) == 4 and run.commands[-1][1] == "-shared" and run.commands[-1][-1] == "-lm"      # four compiles, then the link
    text = "\n".join(lines)
    assert "[4/4] 100%" in text and "[1/4]" in text and "linking game_deck.so" in text
    assert compiles[0][-1].endswith("handlers_gen.c")                                                    # the biggest file starts first
    # again: the objects are newer than their sources, so nothing is compiled; only the link runs
    run2, lines2 = FakeRun(), []
    modbuild.build_modules(*args, jobs=2, say=lines2.append, target_os="linux", runner=run2)
    assert len(run2.commands) == 1 and "up to date" in "\n".join(lines2)


def test_build_modules_reports_the_compiler_error(tmp_path):
    gen, port, native = fake_gen(tmp_path)
    with pytest.raises(modbuild.BuildError) as e:
        modbuild.build_modules(["deck"], str(gen), str(port), str(native), str(tmp_path / "obj"), str(tmp_path / "out"), modbuild.Compiler(["cc"]), jobs=1, say=lambda m: None,
                               target_os="linux", runner=FakeRun(fail_on="deckdll_gen.c"))
    assert "deckdll_gen.c failed" in str(e.value) and "boom" in str(e.value)
    assert not os.path.exists(tmp_path / "out" / "game_deck.so")


def test_stub_module_builds_and_exports_one_function(tmp_path):
    """The real thing, small: the stub module of src/port/stubgame compiled and linked by this installer's commands, then loaded. Needs a C compiler here."""
    import ctypes
    native, port = os.path.join(ROOT, "src", "native"), os.path.join(ROOT, "src", "port")
    if not os.path.exists(os.path.join(port, "stubgame", "handlers_gen.c")):
        pytest.skip("no stub game in this folder")
    cc = None
    for path in modbuild.system_candidates():
        c = modbuild.Compiler([path])
        if modbuild.probe(c, native)[0]:
            cc = c
            break
    if cc is None:
        pytest.skip("no working C compiler on the PATH")
    made = modbuild.build_modules(["stubgame"], port, port, native, str(tmp_path / "obj"), str(tmp_path / "out"), cc, jobs=2, say=lambda m: None)
    lib = ctypes.CDLL(made["stubgame"])
    assert hasattr(lib, "pentamoor_game_init")
    if os.name != "nt":
        assert not hasattr(lib, "lifted_stub_sum")                              # hidden: the module exports its one entry point only


def test_compiler_choice(tmp_path):
    native = str(tmp_path)
    tools = str(tmp_path / "tools")
    working = {"/bin/gcc", "/bin/clang"}

    def prober(cc, native_dir, target_os=None, timeout=0):
        return (cc.argv[0] in working or cc.kind == "zig"), "v1"

    def which(name):
        return {"cc": "/bin/cc", "gcc": "/bin/gcc", "clang": "/bin/clang"}.get(name)

    def find(**kw):
        kw.setdefault("tools_missing", lambda: False)
        return modbuild.find_compiler(native, tools, say=lambda m: None, which=which, prober=prober, **kw)

    assert find().argv == ["/bin/gcc"]                                          # /bin/cc does not work: the next one that does (gcc comes first on Windows, cc elsewhere)
    with pytest.raises(modbuild.BuildError):
        find(explicit="no-such-compiler-xyz")
    # nothing works: Zig is asked for, downloaded (here: a fake fetch that makes the folder), and used
    working.clear()
    asked, fetched = [], []

    def fetch(tools_dir, say):
        fetched.append(tools_dir)
        os.makedirs(os.path.join(tools_dir, "ziglang"))
        with open(os.path.join(tools_dir, "ziglang", "zig.exe" if os.name == "nt" else "zig"), "w") as f:
            f.write("")

    with pytest.raises(modbuild.BuildError) as e:
        find(download=False)
    assert "switched off" in str(e.value) and not fetched
    with pytest.raises(modbuild.BuildError):
        find(ask=lambda q: asked.append(q) or False, fetch=fetch)
    assert asked and "Zig" in asked[0] and not fetched
    cc = find(ask=lambda q: True, fetch=fetch)
    assert cc.kind == "zig" and cc.argv[1] == "cc" and cc.env["ZIG_GLOBAL_CACHE_DIR"].startswith(tools) and fetched == [tools]
    again = find(ask=lambda q: pytest.fail("Zig is there already; nothing to ask"), fetch=fetch)
    assert again.kind == "zig" and fetched == [tools]
    working.add("/bin/gcc")
    assert find().argv == ["/bin/gcc"]                                          # a working system compiler beats the Zig that is there
    assert find(explicit="zig").kind == "zig"


def test_macos_skips_the_stub_cc_when_the_command_line_tools_are_missing(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    paths = {"cc": "/usr/bin/cc", "gcc": "/usr/bin/gcc", "clang": "/opt/x/bin/clang"}
    assert modbuild.system_candidates(paths.get, lambda: True) == ["/opt/x/bin/clang"]
    assert modbuild.system_candidates(paths.get, lambda: False) == ["/usr/bin/cc", "/usr/bin/gcc", "/opt/x/bin/clang"]


# ---- Zig from PyPI ----------------------------------------------------------------------------------------------------------------------------------------
def test_zig_wheel_for_each_system():
    for system, machine in (("Darwin", "arm64"), ("Darwin", "x86_64"), ("Linux", "x86_64"), ("Linux", "aarch64"), ("Linux", "arm64"), ("Windows", "AMD64"), ("Windows", "ARM64")):
        url, size, digest = zigdl.wheel_for(system, machine)
        assert url.startswith("https://files.pythonhosted.org/packages/") and url.endswith(".whl") and len(digest) == 64 and size > 50_000_000
    assert "win_amd64" in zigdl.wheel_for("Windows", "AMD64")[0] and "macosx" in zigdl.wheel_for("Darwin", "arm64")[0] and "x86_64" in zigdl.wheel_for("Linux", "x86_64")[0]
    with pytest.raises(zigdl.ZigError):
        zigdl.wheel_for("Linux", "riscv64")
    assert all(zigdl.ZIG_VERSION in path for path, _, _ in zigdl.WHEELS.values())


def make_wheel(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)


def test_zig_download_is_checked_and_unpacked(tmp_path):
    wheel = tmp_path / "w.whl"
    exe = "ziglang/zig.exe" if os.name == "nt" else "ziglang/zig"
    make_wheel(str(wheel), {exe: b"#!/bin/sh\necho zig\n", "ziglang/lib/a.h": b"x", "ziglang-0.1.dist-info/RECORD": b"r"})
    want = hashlib.sha256(wheel.read_bytes()).hexdigest()
    said = []
    tools = tmp_path / "tools"
    got = zigdl.fetch(str(tools), said.append, url=wheel.as_uri(), sha256=want)
    assert got == zigdl.zig_binary(str(tools)) and os.path.exists(tools / "ziglang" / "lib" / "a.h") and not (tools / "ziglang-0.1.dist-info").exists()
    assert not os.path.exists(tools / "downloads" / "w.whl")
    if os.name != "nt":
        assert os.access(got, os.X_OK)
    assert zigdl.fetch(str(tools), said.append) == got                          # already there: nothing is fetched
    other = tmp_path / "tools2"                                                 # a wrong checksum: refused, and the file is removed
    with pytest.raises(zigdl.ZigError) as e:
        zigdl.fetch(str(other), said.append, url=wheel.as_uri(), sha256="0" * 64)
    assert "checksum" in str(e.value) and not (other / "downloads" / "w.whl").exists() and zigdl.zig_binary(str(other)) is None
    with pytest.raises(zigdl.ZigError):
        zigdl.fetch(str(other), said.append, url=(tmp_path / "missing.whl").as_uri(), sha256="0" * 64)


def test_zig_wheel_cannot_write_outside_the_folder(tmp_path):
    wheel = tmp_path / "evil.whl"
    make_wheel(str(wheel), {"ziglang/../../evil.txt": b"x"})
    with pytest.raises(zigdl.ZigError):
        zigdl.unpack(str(wheel), str(tmp_path / "tools"))
    assert not (tmp_path / "evil.txt").exists()


# ---- the lifter, run from Python --------------------------------------------------------------------------------------------------------------------------
def test_lift_steps_are_lift_all_sh():
    path = os.path.join(ROOT, "tools", "lift", "lift_all.sh")
    if not os.path.exists(path):
        pytest.skip("no lift_all.sh")
    variables, commands = {}, []
    with open(path) as f:
        script = f.read().splitlines()
    for line in script:
        line = line.strip()
        if line.startswith("$PY "):
            commands.append(line[4:])
        elif "=" in line and line.split("=")[0].isidentifier() and not line.startswith(("#", "set")):
            k, v = line.split("=", 1)
            variables[k] = v
    expanded = []
    for c in commands:
        for k in sorted(variables, key=len, reverse=True):
            c = c.replace("$" + k, variables[k])
        expanded.append(c.replace("tools/lift/", "", 1))
    steps = liftrun.lift_steps()
    flat = [f"{script} {' '.join(args)}" for prog in ("magic", "deck", "duel") for script, args in steps[prog]]
    assert flat == expanded


def test_the_2_15_lift_steps_name_each_program_its_libraries_and_their_bases(tmp_path):
    for n in ("Shandalar.EXE", "facemaker.exe", "DECK.EXE", "Magic.exe", "STATWIN.DLL", "DeckDll.dll", "cardartlib.dll", "DrawCardLib.dll", "CdTools.DLL"):     # the install's names are not in one case
        (tmp_path / n).write_bytes(b"MZ")
    steps = liftrun.sota_steps(str(tmp_path), "gen")
    assert list(steps) == ["shandalar", "facemaker", "sotadeck", "shell"]
    flat = {m: [(script, args) for script, args in chain] for m, chain in steps.items()}
    assert flat["shandalar"][0] == ("gen_handlers.py", ["--program", "shandalar", "--exe", str(tmp_path / "Shandalar.EXE"), "--out", "gen/lift_shandalar", "--all", "--no-handlers"])
    libs = [(os.path.basename(args[1]), args[3]) for script, args in flat["shandalar"][1:-1]]
    assert libs == [("STATWIN.DLL", "0x30000000"), ("DeckDll.dll", "0x32000000"), ("cardartlib.dll", "0x34000000"), ("DrawCardLib.dll", "0x36000000"), ("CdTools.DLL", "0x38000000")]
    assert flat["shandalar"][-1] == ("gen_dll.py", ["--finish", "--out", "gen/lift_shandalar"])
    assert flat["facemaker"] == [("gen_dll.py", ["--main", "--dll", str(tmp_path / "facemaker.exe"), "--out", "gen/lift_facemaker"])]       # no libraries: no module list
    assert [a[1] for _, a in flat["sotadeck"][1:-1]] == [str(tmp_path / n) for n in ("DeckDll.dll", "cardartlib.dll", "DrawCardLib.dll", "CdTools.DLL")]
    assert flat["shell"][0] == ("gen_dll.py", ["--main", "--dll", str(tmp_path / "Magic.exe"), "--out", "gen/lift_shell"])        # the Magic Shell: magic.exe with the libraries it loads (no STATWIN.DLL)
    assert [a[1] for _, a in flat["shell"][1:-1]] == [str(tmp_path / n) for n in ("DeckDll.dll", "cardartlib.dll", "DrawCardLib.dll", "CdTools.DLL")]
    assert modbuild.SOTA_PROGRAMS == {"shandalar": "lift_shandalar", "facemaker": "lift_facemaker", "sotadeck": "lift_sotadeck", "shell": "lift_shell"}     # the folders the lifter writes are the ones the build reads


def test_a_2_15_install_is_checked_file_by_file(tmp_path, capsys):
    import install_sota  # noqa: PLC0415
    assert install_sota.find_program_folder(str(tmp_path)) is None
    (tmp_path / "Program").mkdir()
    assert install_sota.find_program_folder(str(tmp_path)) is None                         # no shandalar.exe there
    (tmp_path / "Program" / "SHANDALAR.EXE").write_bytes(b"not the game")
    assert install_sota.find_program_folder(str(tmp_path)) == str(tmp_path / "Program")
    detected = install_sota.detect(str(tmp_path / "Program"))
    assert {n for n, bid, known in detected if bid is None} == set(install_sota.builds.fingerprints("v2.15")) - {"shandalar.exe"}
    assert [n for n, bid, known in detected if bid and not known] == ["shandalar.exe"]
    assert not install_sota.report(str(tmp_path / "Program"), detected)
    out = capsys.readouterr().out
    assert "shandalar.exe: unknown build" in out and "deckdll.dll: missing" in out and "This is not Spells of the Ancients 2.15" in out
    assert install_sota.main([str(tmp_path), "--check"]) == 1


def test_lifter_runs_in_a_child_that_needs_no_pythonpath(tmp_path):
    helper = tmp_path / "helper"
    helper.mkdir()
    (helper / "needed.py").write_text("VALUE = 41\n")
    script = tmp_path / "s.py"
    script.write_text("import sys, needed\nprint('ARGS', sys.argv[1:], needed.VALUE + 1, __name__)\n")
    cmd = liftrun.python_command(sys.executable, str(script), ["--out", "x y"], [str(helper)])
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    r = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert r.returncode == 0 and r.stdout.strip() == "ARGS ['--out', 'x y'] 42 __main__"


def test_lift_is_skipped_when_nothing_changed(tmp_path):
    for sub in ("tools/lift", "src/native", liftrun.GAME):
        (tmp_path / sub).mkdir(parents=True)
    (tmp_path / "tools/lift/x86lift.py").write_text("a")
    (tmp_path / "src/native/layout.c").write_text("l")
    (tmp_path / liftrun.GAME / "MAGIC.EXE").write_bytes(b"MZ1")
    stamp = liftrun.fingerprint(str(tmp_path))
    assert not liftrun.is_lifted(str(tmp_path), "magic", stamp)
    out = tmp_path / liftrun.GENERATED / "lift_magic_all"
    out.mkdir(parents=True)
    (out / "handlers_gen.c").write_text("")
    liftrun.write_stamp(str(tmp_path), "magic", stamp)
    assert liftrun.is_lifted(str(tmp_path), "magic", stamp) and not liftrun.is_lifted(str(tmp_path), "deck", stamp)
    (tmp_path / "tools/lift/x86lift.py").write_text("b")                       # the lifter changed: lift again
    assert liftrun.fingerprint(str(tmp_path)) != stamp
    (tmp_path / "tools/lift/x86lift.py").write_text("a")
    (tmp_path / liftrun.GAME / "MAGIC.EXE").write_bytes(b"MZ2")                # another game file: lift again
    assert not liftrun.is_lifted(str(tmp_path), "magic", liftrun.fingerprint(str(tmp_path)))


# ---- the installer's small helpers ------------------------------------------------------------------------------------------------------------------------
def test_pasted_and_dropped_file_names_are_cleaned():
    import install
    assert install.clean_path('  "D:\\Games\\MTG v1.0.iso"  ') == "D:\\Games\\MTG v1.0.iso"
    assert install.clean_path("'/Users/x/MTG v1.0.iso'") == "/Users/x/MTG v1.0.iso"
    if os.name != "nt":
        assert install.clean_path("/Users/x/MTG\\ v1.0.iso ") == "/Users/x/MTG v1.0.iso"
    assert install.clean_path("") == ""


def test_layout_tells_a_release_from_a_checkout(tmp_path):
    import install
    rel = install.Layout(str(tmp_path))
    assert rel.release and rel.out_dir.endswith(os.path.join("src", "port", "build"))      # no runtime beside the launchers yet
    (tmp_path / ("pentamoor-run" + install.EXE)).write_text("")
    assert rel.out_dir == str(tmp_path) and rel.runtime == str(tmp_path / ("pentamoor-run" + install.EXE))
    (tmp_path / "src" / "port").mkdir(parents=True)
    (tmp_path / "src" / "port" / "Makefile").write_text("")
    assert not install.Layout(str(tmp_path)).release


def test_the_repository_carries_everything_the_release_needs():
    assert manifest.missing(ROOT) == []
    files = manifest.release_files(ROOT)
    assert "tools/install/install.py" in files and "tools/lift/gen_handlers.py" in files and "src/native/lift_rt.h" in files
    assert not any(f.endswith(("test_install.py", "test_release.py", "test_lift.py")) or "__pycache__" in f for f in files)
    assert not any(f.startswith(("sources/", "src/port/build")) for f in files)


# ---- the release archive ----------------------------------------------------------------------------------------------------------------------------------
def build_archive(tmp_path, platform, version="9.9.9"):
    import package
    runtime = tmp_path / ("pentamoor-run.exe" if platform.startswith("windows") else "pentamoor-run")
    runtime.write_bytes(b"\x7fELF fake")
    os.chmod(runtime, 0o755)
    deps = tmp_path / "deps"
    (deps / "pefile").mkdir(parents=True)
    (deps / "pefile" / "__init__.py").write_text("")
    top = f"pentamoor-{version}-{platform}"
    stage = tmp_path / "stage" / top
    stage.mkdir(parents=True)
    package.stage_files(str(stage), platform, version, str(runtime), [], [], str(deps), False, False, False, say=lambda m: None)
    out = package.pack(str(stage), top, str(tmp_path / "dist" / package.archive_name(version, platform)), package.is_windows(platform))
    return out, top


def test_release_archive_layout_unix(tmp_path):
    import check_archive
    out, top = build_archive(tmp_path, "linux-x86_64")
    assert out.endswith("pentamoor-9.9.9-linux-x86_64.tar.gz")
    with tarfile.open(out) as t:
        names = {m.name[len(top) + 1:]: m for m in t.getmembers()}
    for need in ("pentamoor-run", "pentamoor", "pentamoor-install", "README.txt", "NOTICE.txt", "LICENSE", "VERSION", "SHA256SUMS", "tools/install/install.py", "tools/install/modbuild.py",
                 "tools/lift/gen_handlers.py", "tools/lift/x86lift.py", "tools/pydeps/pefile/__init__.py", "src/native/lift_rt.h", "src/native/lift_tables.h", "src/port/modglue.c",
                 "src/port/modules_none.c", "src/port/stubgame/handlers_gen.c", "tools/lift/fnscan.py", "tools/lift/import_signatures.py", "src/native/layout.c",
                 # Spells of the Ancients 2.15: the readers of the expansion's cabinets and of the patch, the folder maker, and the lifter's files for its programs
                 "tools/install/iscab.py", "tools/install/sotapatch.py", "tools/install/overlay.py", "tools/install/sotainstall.py", "tools/install/install_sota.py",
                 "tools/install/iso9660.py", "tools/install/datax.py", "tools/install/blast.py", "tools/lift/libsigs.py", "tools/lift/mastertable.py", "tools/lift/builds.py"):
        assert need in names, need
    assert not any(n.endswith(".bat") for n in names) and not any("test_" in n for n in names)
    assert names["pentamoor-run"].mode & 0o111 and names["pentamoor"].mode & 0o111 and names["pentamoor-install"].mode & 0o111
    root = check_archive.extract(out, str(tmp_path / "x"))
    files = check_archive.all_files(root)
    assert check_archive.check_sums(root, files) == [] and check_archive.forbidden(files) == []
    with open(os.path.join(root, "README.txt")) as f:
        readme = f.read()
    assert "Pentamoor 9.9.9 (linux-x86_64)" in readme and "./pentamoor" in readme and "pentamoor.bat" not in readme and "\n@" not in readme
    with open(os.path.join(root, "VERSION")) as f:
        assert f.read() == "9.9.9\n"


@pytest.mark.skipif(sys.platform == "win32", reason="the Steam Deck archive is a Linux one, and its checks run shell scripts")
def test_release_archive_layout_steamdeck(tmp_path):
    import check_archive
    out, top = build_archive(tmp_path, "steamdeck")
    assert out.endswith("pentamoor-9.9.9-steamdeck.tar.gz")
    with tarfile.open(out) as t:
        names = {m.name[len(top) + 1:]: m for m in t.getmembers()}
    for need in ("pentamoor-run", "pentamoor", "pentamoor-install", "Install Pentamoor.desktop", "Add Pentamoor to Steam.desktop", "tools/steamdeck/install-gui.sh",
                 "tools/steamdeck/install-run.sh", "tools/steamdeck/add-to-steam.py", "tools/steamdeck/progress.py", "tools/steamdeck/controller_neptune_pentamoor.vdf",
                 "tools/install/install.py", "tools/pydeps/pefile/__init__.py", "README.txt", "SHA256SUMS"):
        assert need in names, need
    assert not any(n.endswith(".bat") for n in names) and not any("test_" in n for n in names)
    assert not any(n.startswith("tools/steamdeck/desktop") for n in names)                     # the .desktop files are at the top, not twice
    for n in ("Install Pentamoor.desktop", "Add Pentamoor to Steam.desktop", "tools/steamdeck/install-gui.sh", "tools/steamdeck/add-to-steam.py", "pentamoor-run"):
        assert names[n].mode & 0o111, n + " is not executable"
    root = check_archive.extract(out, str(tmp_path / "x"))
    files = check_archive.all_files(root)
    assert check_archive.check_sums(root, files) == [] and check_archive.forbidden(files) == []
    with open(os.path.join(root, "README.txt")) as f:
        readme = f.read()
    assert "Pentamoor 9.9.9 (steamdeck)" in readme and "Install Pentamoor" in readme and "Gaming Mode" in readme and "\n@" not in readme
    assert "apt install" not in readme and "pacman -S" not in readme and "xattr" not in readme                # the lines of the other systems are not there
    env = dict(os.environ)
    env.pop("XDG_DATA_HOME", None)
    assert check_archive.check_steamdeck(root, sys.executable, env) == []                      # the files work from the unpacked folder (a fake Steam folder, no display)


def test_other_archives_do_not_carry_the_steam_deck_files(tmp_path):
    import manifest
    assert not any(f.startswith("tools/steamdeck") for f in manifest.release_files(ROOT))
    assert "tools/steamdeck/install-gui.sh" in manifest.steamdeck_files(ROOT)
    assert not any("test_" in f or "/desktop/" in f for f in manifest.steamdeck_files(ROOT))
    assert all(os.path.exists(os.path.join(ROOT, "tools", "steamdeck", "desktop", n)) for n in manifest.STEAMDECK_DESKTOP)
    out, top = build_archive(tmp_path, "linux-x86_64")
    with tarfile.open(out) as t:
        assert not any("steamdeck" in m.name or m.name.endswith(".desktop") for m in t.getmembers())


def test_release_archive_layout_windows(tmp_path):
    import check_archive
    out, top = build_archive(tmp_path, "windows-x86_64")
    assert out.endswith("pentamoor-9.9.9-windows-x86_64.zip")
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        bat = z.read(f"{top}/pentamoor.bat")
    for need in ("pentamoor-run.exe", "pentamoor.bat", "pentamoor-install.bat", "tools/install/install.py", "src/native/lift_rt.h", "SHA256SUMS", "README.txt"):
        assert f"{top}/{need}" in names, need
    assert f"{top}/pentamoor" not in names and f"{top}/pentamoor-install" not in names
    assert b"\r\n" in bat and b"\n" not in bat.replace(b"\r\n", b"")            # every line ends CRLF
    root = check_archive.extract(out, str(tmp_path / "x"))
    with open(os.path.join(root, "README.txt"), "rb") as f:
        assert b"pentamoor.bat" in f.read()
    assert check_archive.check_sums(root, check_archive.all_files(root)) == []


def test_archive_check_refuses_anything_made_from_the_game():
    import check_archive
    bad = ["sources/installed/Magic/Program/MAGIC.EXE", "tools/x/MAGIC.EXE", "game_magic.so", "game_deck.dll", "game_duel.dylib", "sources/generated/lift_deck/handlers_gen.c",
           "foo/deckdll_gen.c", "lift_magic_all/handler_spec.json", "MTG v1.0.iso", "DECKDLL.DLL",
           # Spells of the Ancients 2.15: its programs, libraries and data, the modules built from them, the patch, the cabinets and the disc
           "sources/installed_sota/Magic/Program/shandalar.exe", "x/FaceMaker.exe", "cardartlib.dll", "x/DrawCardLib.dll", "CdTools.dll", "Program/CARDS.DAT", "FaceData.txt",
           "game_shandalar.dylib", "game_facemaker.so", "game_sotadeck.dll", "game_shell.dylib", "SOTAV215.EXE", "sotav215.exe", "Setup/data1.cab", "_user1.cab", "MTG v2.00.iso",
           "sources/generated/lift_shandalar/handlers_gen.c", "lift_sotadeck/cardartlib_gen.c",
           # the licence step: the original installer's library (by its name in the cabinet and by its internal name), the module and the lifted C made from it, an install's registry file
           "Manaball.wav", "Program/DuelSounds/Manaball.wav", "x/MANABALL.WAV", "SencLib.dll", "game_senclib.so", "game_senclib.dylib", "game_senclib.dll", "sources/generated/lift_senclib/handlers_gen.c",
           "lift_senclib/manaball_spec.json", "port_overlay_sota/registry.dat", "registry.dat"]
    ok = ["src/port/stubgame/handlers_gen.c", "pentamoor-run", "SDL2.dll", "tools/local/ziglang/zig.exe", "python/python313.dll", "tools/pydeps/capstone/lib/libcapstone.so"]
    assert check_archive.forbidden(bad) == bad
    assert check_archive.forbidden(ok) == []


def test_archive_checksums_notice_a_changed_file(tmp_path):
    import check_archive
    out, top = build_archive(tmp_path, "linux-x86_64")
    root = check_archive.extract(out, str(tmp_path / "x"))
    with open(os.path.join(root, "VERSION"), "w") as f:
        f.write("changed\n")
    with open(os.path.join(root, "extra.txt"), "w") as f:
        f.write("new")
    problems = check_archive.check_sums(root, check_archive.all_files(root))
    assert any("VERSION" in p for p in problems) and any("extra.txt" in p for p in problems)


def test_readme_lines_are_chosen_by_platform():
    import package
    text = "all\n@windows win\n@unix unix\n@macos mac\n@linux lin\nend"
    assert package.filter_readme(text, "windows-x86_64").split() == ["all", "win", "end"]
    assert package.filter_readme(text, "macos-universal").split() == ["all", "unix", "mac", "end"]
    assert package.filter_readme(text, "linux-x86_64").split() == ["all", "unix", "lin", "end"]
    assert package.filter_readme(text + "\n@steamdeck deck", "steamdeck").split() == ["all", "unix", "end", "deck"]


# ---- the launcher in a release layout ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.skipif(sys.platform == "win32", reason="./pentamoor is a shell script")
def test_launcher_in_a_release_layout_and_with_a_dropped_iso(tmp_path):
    import shutil
    shutil.copy(os.path.join(ROOT, "pentamoor"), tmp_path / "pentamoor")
    run = tmp_path / "pentamoor-run"
    run.write_text('#!/bin/sh\necho "$@"\n')
    run.chmod(run.stat().st_mode | stat.S_IEXEC)
    ext = "dylib" if sys.platform == "darwin" else "so"
    # a stand-in installer: makes the game files and the modules, and records that it was called with the disc
    (tmp_path / "pentamoor-install").write_text(
        "import os, sys\nopen('installer-called', 'w').write(' '.join(sys.argv[1:]))\n"
        "os.makedirs('sources/installed/Magic/Program', exist_ok=True)\n"
        "for n in ('MAGIC.EXE', 'DECK.EXE', 'DUEL.EXE'): open('sources/installed/Magic/Program/' + n, 'w').close()\n"
        f"for p in ('magic', 'deck', 'duel'): open(f'game_{{p}}.{ext}', 'w').close()\n")

    def launch(*args):
        return subprocess.run(["sh", str(tmp_path / "pentamoor"), *args], capture_output=True, text=True, stdin=subprocess.DEVNULL)

    r = launch()                                    # no terminal: it does not ask, it says what to run
    assert r.returncode == 1 and "the game is not installed" in r.stderr and "./pentamoor-install" in r.stderr and not (tmp_path / "installer-called").exists()
    iso = tmp_path / "MTG v1.0.iso"
    iso.write_bytes(b"")
    r = launch(str(iso))                            # a disc image given (dropped on the launcher): install from it, then start the game
    assert (tmp_path / "installer-called").read_text() == str(iso)
    assert r.returncode == 0 and r.stdout.split() == ["-m", f"./game_magic.{ext}", "sources/installed/Magic/Program/MAGIC.EXE"], r.stderr
    assert launch("duel").stdout.split()[:2] == ["-m", f"./game_duel.{ext}"]


@pytest.mark.skipif(sys.platform == "win32", reason="./pentamoor is a shell script")
def test_launcher_runs_sota_from_its_own_folder_with_its_own_saves(tmp_path):
    import shutil
    shutil.copy(os.path.join(ROOT, "pentamoor"), tmp_path / "pentamoor")
    run = tmp_path / "pentamoor-run"
    run.write_text('#!/bin/sh\necho "overlay=$PORT_OVERLAY $@"\n')            # the stand-in shows what the runtime would be given
    run.chmod(run.stat().st_mode | stat.S_IEXEC)
    ext = "dylib" if sys.platform == "darwin" else "so"

    def launch(*args, **env):
        e = {k: v for k, v in os.environ.items() if not k.startswith(("PENTAMOOR_", "PORT_"))}
        e.update(env)
        return subprocess.run(["sh", str(tmp_path / "pentamoor"), *args], capture_output=True, text=True, stdin=subprocess.DEVNULL, env=e)

    r = launch("sota")                              # nothing installed: it says what is needed, and the one command that installs it
    assert r.returncode == 1 and "Spells of the Ancients 2.15 is not installed" in r.stderr and "--sota" in r.stderr and "--patch" in r.stderr and "SOTAV215.EXE" in r.stderr
    assert "python3 tools/install/install.py" in r.stderr and "--build" in r.stderr             # (a checkout: no ./pentamoor-install beside the launcher)
    (tmp_path / "pentamoor-install").write_text("")
    assert "./pentamoor-install " in launch("sota").stderr and "--build" not in launch("sota").stderr
    game = tmp_path / "sources" / "installed_sota" / "Magic" / "Program"        # where the installer puts it
    game.mkdir(parents=True)
    (game / "shandalar.exe").write_bytes(b"")
    r = launch("sota")
    assert r.returncode == 1 and "the game module is not built yet" in r.stderr and "--sota" in r.stderr
    (tmp_path / f"game_shandalar.{ext}").write_bytes(b"")
    r = launch("sota", "extra")                     # no environment variable set: the folder, the module and the saves' folder are the defaults
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["overlay=port_overlay_sota", "-m", f"./game_shandalar.{ext}", "sources/installed_sota/Magic/Program/shandalar.exe", "extra"]
    assert launch("shandalar").stdout.split()[0] == "overlay=port_overlay_sota"
    assert launch("sota", "shandalar", "x").stdout.split() == r.stdout.split()[:4] + ["x"]                           # `sota shandalar` is `sota`: the adventure, directly
    # `sota shell`: the Magic Shell, magic.exe of the same folder with its own module, the same saves; the module and the program are checked like the adventure's
    (game / "magic.exe").write_bytes(b"")
    r = launch("sota", "shell")
    assert r.returncode == 1 and "the game module is not built yet (./game_shell." in r.stderr
    (tmp_path / f"game_shell.{ext}").write_bytes(b"")
    r = launch("sota", "shell", "extra")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["overlay=port_overlay_sota", "-m", f"./game_shell.{ext}", "sources/installed_sota/Magic/Program/magic.exe", "extra"]
    (game / "magic.exe").unlink()
    assert launch("sota", "shell").returncode == 1 and "is not installed" in launch("sota", "shell").stderr
    (game / "magic.exe").write_bytes(b"")
    assert launch("sota", PORT_OVERLAY="mine").stdout.split()[0] == "overlay=mine"          # a choice of the player's wins
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "shandalar.exe").write_bytes(b"")
    assert launch("sota", PENTAMOOR_SOTA=str(other)).stdout.split()[3] == f"{other}/shandalar.exe"
    (tmp_path / "sources" / "installed" / "Magic" / "Program").mkdir(parents=True)
    for exe in ("MAGIC.EXE", "DECK.EXE", "DUEL.EXE"):                           # the first game keeps the runtime's own default, port_overlay: the launcher sets nothing for it
        (tmp_path / "sources" / "installed" / "Magic" / "Program" / exe).write_bytes(b"")
    for p in ("magic", "deck", "duel"):
        (tmp_path / f"game_{p}.{ext}").write_bytes(b"")
    assert launch().stdout.split()[0] == "overlay="

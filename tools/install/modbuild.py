"""
modbuild.py - choose a C compiler and build the game modules from the C the lifter wrote, with no `make`.

A game module (game_magic, game_deck, game_duel: .so, .dylib or .dll) is one shared library made from every *_gen.c the lifter wrote for a program, plus
src/port/modglue.c (and src/port/modules_none.c when the program has no DLLs). It needs plain C99, src/native/lift_rt.h and lift_tables.h, and libm: nothing of the runtime
or SDL. This file does what the module rules of src/port/Makefile do, in Python, so the same step runs on Windows without MSYS2, and in a release, which has no Makefile.
The flags are the Makefile's (MODFLAGS, SOFLAGS); tools/install/test_install.py checks the two agree.

Choosing the compiler (find_compiler): $PENTAMOOR_CC or --compiler if given; else the first of cc, gcc, clang on the PATH that really compiles and links a small
shared library here; else the Zig that is already in <root>/tools/local (the Windows release carries one); else Zig is downloaded there (zigdl.py).

Building for another system (--target, TARGETS): the same sources can be compiled for a system and a processor other than this machine's, with Zig as a cross compiler
(`zig cc -target x86_64-windows-gnu` makes a Windows DLL on a Mac), or with Apple's clang for either processor of a Mac. Nothing is run; the result is only a file to carry over.
    python3 tools/install/modbuild.py --target windows-x86_64 --out some/folder        (--gen: the lifter's output folder, default sources/generated)
A native build (no --target) is exactly what it always was.
"""
import concurrent.futures
import glob
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import time

import zigdl

# program -> the folder the lifter writes under sources/generated (tools/lift/lift_all.sh)
PROGRAMS = {"magic": "lift_magic_all", "deck": "lift_deck", "duel": "lift_duel"}
# the same for Spells of the Ancients 2.15 (tools/lift/builds.py SOTA_MODULES; tools/install/install_sota.py makes them): kept apart, as the installer builds all of PROGRAMS
SOTA_PROGRAMS = {"shandalar": "lift_shandalar", "facemaker": "lift_facemaker", "sotadeck": "lift_sotadeck"}
# the one library of the expansion's cabinet that the installer runs to write the licence value (tools/install/licence.py): built only when the installer lifted it
LICENCE_PROGRAMS = {"senclib": "lift_senclib"}
DEFINES = ["-DLIFT_BACKEND_FLAT4G", "-DLIFT_PREEMPT", "-DLIFT_MODULE"]
HEADERS = ("lift_rt.h", "lift_tables.h")


class BuildError(Exception):
    pass


def host_os():
    return {"darwin": "darwin", "win32": "windows", "cygwin": "windows", "msys": "windows"}.get(sys.platform, "linux")


def module_ext(target_os=None):
    return {"darwin": "dylib", "windows": "dll"}.get(target_os or host_os(), "so")


def host_arch():
    return TRIPLE_ARCH.get(platform.machine().lower(), platform.machine().lower())


class Target:
    """A system and processor to build for: name ('windows-x86_64'), os ('darwin', 'windows', 'linux': host_os()'s words), arch ('x86_64', 'aarch64'), the triple Zig is told
    (`zig cc -target`), and, for a Mac, the architecture name Apple's compiler is told (`-arch`) and the oldest macOS the module is made for."""

    def __init__(self, name, os_name, arch, zig, apple_arch=None, min_os=None):
        self.name, self.os, self.arch, self.zig, self.apple_arch, self.min_os = name, os_name, arch, zig, apple_arch, min_os

    def __repr__(self):
        return f"Target({self.name!r})"

    def is_native(self):
        """Is this the system and processor the script runs on?"""
        return self.os == host_os() and self.arch == host_arch()


# The glibc of the Linux targets is the one the project's release runtime is built against (the ubuntu-22.04 runner of .github/workflows/package.yml: glibc 2.35): a module made
# against an older glibc loads on newer ones, not the other way round. macOS 11 is the oldest the universal runtime supports.
TARGETS = {t.name: t for t in (
    Target("windows-x86_64", "windows", "x86_64", "x86_64-windows-gnu"),
    Target("linux-x86_64", "linux", "x86_64", "x86_64-linux-gnu.2.35"),
    Target("linux-aarch64", "linux", "aarch64", "aarch64-linux-gnu.2.35"),
    Target("macos-arm64", "darwin", "aarch64", "aarch64-macos.11.0", "arm64", "11.0"),
    Target("macos-x86_64", "darwin", "x86_64", "x86_64-macos.11.0", "x86_64", "11.0"),
)}
# Zig's own triples are accepted as well ('x86_64-windows-gnu', 'aarch64-macos'): they are read as the target they stand for
TRIPLE_OS = {"windows": "windows", "linux": "linux", "macos": "darwin", "darwin": "darwin"}
TRIPLE_ARCH = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}


def parse_target(text):
    """The Target a name or a Zig triple stands for: 'windows-x86_64', 'macos-arm64', 'x86_64-linux-gnu.2.35'. None for no text. Raises BuildError for one that is not known."""
    if not text:
        return None
    if text in TARGETS:
        return TARGETS[text]
    parts = text.split("-")
    if len(parts) >= 2 and parts[0] in TRIPLE_ARCH and parts[1].split(".")[0] in TRIPLE_OS:
        arch, os_name = TRIPLE_ARCH[parts[0]], TRIPLE_OS[parts[1].split(".")[0]]
        for t in TARGETS.values():
            if t.os == os_name and t.arch == arch:
                return Target(t.name, t.os, t.arch, text, t.apple_arch, t.min_os)        # the triple as given is what Zig is told
    raise BuildError(f"unknown target '{text}'; known: {', '.join(TARGETS)} (or a Zig triple such as x86_64-windows-gnu)")


def target_args(cc, target):
    """What to add to every compile and link command to make `cc` build for `target`: nothing for no target, or for this machine's own system and processor with a compiler of
    this machine (a native build is untouched). Zig takes -target; Apple's compiler on a Mac takes -arch and the oldest macOS; any other compiler cannot be pointed elsewhere."""
    if target is None or (target.is_native() and cc.kind != "zig"):
        return []
    if cc.kind == "zig":
        return ["-target", target.zig]
    if target.os == "darwin" and host_os() == "darwin":
        return ["-arch", target.apple_arch, f"-mmacosx-version-min={target.min_os}"]
    raise BuildError(f"{cc.argv[0]} cannot build for {target.name} from this machine; a cross build needs Zig (--compiler zig)")


class Compiler:
    """argv: the command that starts the compiler (['gcc'], ['/x/zig', 'cc']); kind: gcc, clang or zig; env: variables to add when it runs."""

    def __init__(self, argv, kind=None, env=None, version=""):
        self.argv = list(argv)
        self.kind = kind or compiler_kind(argv)
        self.env = dict(env or {})
        self.version = version

    def __repr__(self):
        return f"Compiler({self.argv!r}, {self.kind!r})"

    def describe(self):
        return " ".join(self.argv) + (f"  ({self.version})" if self.version else "")


def compiler_kind(argv):
    name = os.path.basename(argv[0]).lower()
    if name.startswith("zig") or "ziglang" in [os.path.basename(a).lower() for a in argv]:
        return "zig"
    if "clang" in name:
        return "clang"
    return "gcc"


def compile_flags(kind, native_dir, target_os=None):
    """What a module's C files are compiled with (Makefile: MODFLAGS). Windows has no -fPIC (every PE image is relocatable) and exports only what modglue.c marks dllexport."""
    flags = ["-std=gnu99", "-O1", "-w"]
    if (target_os or host_os()) != "windows":
        flags += ["-fPIC", "-fvisibility=hidden"]
    return flags + DEFINES + ["-I", native_dir]


def link_flags(kind, target_os=None):
    """The flags that make the objects a shared library (Makefile: SOFLAGS). -static-libgcc keeps a MinGW module from needing libgcc_s beside it; Zig has no libgcc to leave out."""
    target_os = target_os or host_os()
    if target_os == "darwin":
        return ["-dynamiclib"]
    if target_os == "windows" and kind != "zig":
        return ["-shared", "-static-libgcc"]
    return ["-shared"]


def compile_command(cc, src, obj, native_dir, target_os=None, target=None):
    if target is not None:
        target_os = target.os
    return cc.argv + target_args(cc, target) + compile_flags(cc.kind, native_dir, target_os) + ["-c", "-o", obj, src]


def link_command(cc, objs, out, target_os=None, target=None, strip=False):
    """`strip`: also drop the symbol table and debug information of the result (-s; not for a Mac, whose linker keeps only what the objects carry, and they carry none). Zig's Linux
    libraries are five times larger without it."""
    if target is not None:
        target_os = target.os
    extra = ["-s"] if strip and (target_os or host_os()) != "darwin" else []
    return cc.argv + target_args(cc, target) + link_flags(cc.kind, target_os) + extra + ["-o", out] + list(objs) + ["-lm"]


def program_sources(gen_dir, port_dir):
    """The C files of one module: every *_gen.c the lifter wrote, modglue.c, and the empty module list when the lifter wrote none (modules_gen.c is its list of DLLs)."""
    gens = sorted(glob.glob(os.path.join(gen_dir, "*_gen.c")))
    if not gens:
        raise BuildError(f"{gen_dir} holds no *_gen.c: lift the game first")
    srcs = gens + [os.path.join(port_dir, "modglue.c")]
    if not os.path.exists(os.path.join(gen_dir, "modules_gen.c")):
        srcs.append(os.path.join(port_dir, "modules_none.c"))
    return srcs


def split_command(text):
    """A compiler given as text ('gcc', 'zig cc', '"C:\\Program Files\\x\\gcc.exe"', 'cc -m64') as an argv."""
    if os.path.exists(text):
        return [text]
    return [a[1:-1] if len(a) > 1 and a[0] == a[-1] == '"' else a for a in shlex.split(text, posix=os.name != "nt")]


# ---- choosing the compiler --------------------------------------------------------------------------------------------------------------------------------
PROBE_C = """\
#include <stdint.h>
#include <math.h>
typedef char pointer_is_8_bytes[sizeof(void *) == 8 ? 1 : -1];
double pentamoor_probe(double x) { return floor(x) + 1.0; }
"""


def run_quiet(argv, env=None, timeout=None, cwd=None):
    full = dict(os.environ)
    full.update(env or {})
    return subprocess.run(argv, env=full, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", timeout=timeout)


def probe(cc, native_dir, target_os=None, timeout=600, target=None):
    """Does this compiler make a 64-bit shared library from C99 here (for `target`, if given)? Returns (ok, first line of its --version or the error). The first run of Zig builds its own caches."""
    target_os = target.os if target is not None else target_os or host_os()
    with tempfile.TemporaryDirectory(prefix="pentamoor-probe-") as d:
        src, obj, lib = (os.path.join(d, n) for n in ("probe.c", "probe.o", "probe." + module_ext(target_os)))
        with open(src, "w") as f:
            f.write(PROBE_C)
        try:
            version = run_quiet(cc.argv + ["--version"], cc.env, timeout=timeout)
            first = (version.stdout.strip().splitlines() or [""])[0] if version.returncode == 0 else ""
            for cmd in (compile_command(cc, src, obj, native_dir, target_os, target), link_command(cc, [obj], lib, target_os, target)):
                r = run_quiet(cmd, cc.env, timeout=timeout, cwd=d)
                if r.returncode != 0:
                    return False, (r.stdout.strip().splitlines() or ["failed"])[-1][:200]
        except (OSError, subprocess.TimeoutExpired, BuildError) as e:
            return False, str(e)
    return True, first


def xcode_tools_missing(which=shutil.which, runner=run_quiet):
    """macOS: /usr/bin/cc is a stub that asks to install the command line tools (a dialog, in a graphical session) when they are not there."""
    if sys.platform != "darwin" or not which("xcode-select"):
        return False
    try:
        return runner(["xcode-select", "-p"], timeout=30).returncode != 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def system_candidates(which=shutil.which, tools_missing=xcode_tools_missing):
    names = ["cc", "gcc", "clang"] if host_os() != "windows" else ["gcc", "cc", "clang"]
    skip_stub = tools_missing()
    found = []
    for n in names:
        path = which(n)
        if path and not (skip_stub and path.startswith("/usr/bin/")):
            found.append(path)
    return found


def local_zig(tools_dir):
    exe = zigdl.zig_binary(tools_dir)
    if not exe:
        return None
    cache = os.path.join(tools_dir, "zig-cache")
    return Compiler([exe, "cc"], "zig", {"ZIG_GLOBAL_CACHE_DIR": cache, "ZIG_LOCAL_CACHE_DIR": cache})


def get_zig(tools_dir, download, ask, say, fetch):
    """The Compiler for the Zig in tools_dir, downloading it first if it is not there (after `ask`)."""
    cc = local_zig(tools_dir)
    if cc is not None:
        return cc
    if not download:
        raise BuildError("no working C compiler (gcc, clang, cc) was found, and downloading Zig is switched off; install one, or run again allowing the download")
    try:
        _, size, _ = zigdl.wheel_for()
    except zigdl.ZigError as e:
        raise BuildError(str(e)) from e
    if ask and not ask(f"Download the Zig compiler (about {size // (1 << 20)} MB, from PyPI, checked against a known checksum) into {tools_dir}?"):
        raise BuildError("no C compiler: install gcc or clang (on Windows: MSYS2 or w64devkit), or let the installer download Zig (it asks; --yes answers for you)")
    try:
        fetch(tools_dir, say)
    except zigdl.ZigError as e:
        raise BuildError(f"{e}. Install gcc or clang instead, or run this again when online") from e
    return local_zig(tools_dir)


def find_compiler(native_dir, tools_dir, explicit=None, download=True, ask=None, say=print, which=shutil.which, prober=probe, fetch=zigdl.fetch, tools_missing=xcode_tools_missing):
    """The compiler to build the modules with (see the top of this file). `explicit`: a command, or "zig" for the Zig in tools_dir. `ask(question)` -> bool is asked before
    Zig is downloaded; no `ask` means yes. Raises BuildError with what to do when there is none."""
    explicit = explicit or os.environ.get("PENTAMOOR_CC")
    if explicit and explicit.strip().lower() == "zig":
        cc = get_zig(tools_dir, download, ask, say, fetch)
        ok, detail = prober(cc, native_dir)
        if not ok:
            raise BuildError(f"Zig ({' '.join(cc.argv)}) does not work here: {detail}")
        cc.version = "zig " + detail
        return cc
    if explicit:
        argv = split_command(explicit)
        if not shutil.which(argv[0]) and not os.path.exists(argv[0]):
            raise BuildError(f"the compiler '{explicit}' was not found")
        cc = Compiler(argv)
        ok, detail = prober(cc, native_dir)
        if not ok:
            raise BuildError(f"the compiler '{explicit}' cannot build a shared library here: {detail}")
        cc.version = detail
        return cc
    tried = []
    for path in system_candidates(which, tools_missing):
        cc = Compiler([path])
        ok, detail = prober(cc, native_dir)
        if ok:
            cc.version = detail
            return cc
        tried.append(f"{path}: {detail}")
    for t in tried:
        say(f"  not usable: {t}")
    if local_zig(tools_dir) is None:
        say("no working C compiler was found (gcc, clang or cc).")
    cc = get_zig(tools_dir, download, ask, say, fetch)
    ok, detail = prober(cc, native_dir)
    if not ok:
        raise BuildError(f"Zig ({' '.join(cc.argv)}) does not work here: {detail}")
    cc.version = "zig " + detail
    return cc


def find_target_compiler(target, native_dir, tools_dir, explicit=None, download=True, ask=None, say=print, which=shutil.which, prober=probe, fetch=zigdl.fetch,
                         tools_missing=xcode_tools_missing):
    """The compiler that builds the modules for `target` (a Target). For no target, or this machine's own, that is find_compiler's choice. For another system or processor:
    `explicit` if given ("zig" is the Zig in tools_dir), else, for a Mac target on a Mac, the system's clang (it builds either processor), else Zig, which is a cross compiler
    for all of them. Whatever is chosen is tried on a small library for that target first. Raises BuildError."""
    if target is None or target.is_native():
        return find_compiler(native_dir, tools_dir, explicit, download, ask, say, which, prober, fetch, tools_missing)
    explicit = explicit or os.environ.get("PENTAMOOR_CC")

    def tried(cc, label):
        ok, detail = prober(cc, native_dir, target=target)
        if not ok:
            raise BuildError(f"{label} cannot build a shared library for {target.name}: {detail}")
        cc.version = detail
        return cc

    if explicit and explicit.strip().lower() != "zig":
        argv = split_command(explicit)
        if not shutil.which(argv[0]) and not os.path.exists(argv[0]):
            raise BuildError(f"the compiler '{explicit}' was not found")
        return tried(Compiler(argv), explicit)
    if not explicit and target.os == "darwin" and host_os() == "darwin":
        for path in system_candidates(which, tools_missing):
            cc = Compiler([path])
            ok, detail = prober(cc, native_dir, target=target)
            if ok:
                cc.version = detail
                return cc
            say(f"  not usable for {target.name}: {path}: {detail}")
    cc = get_zig(tools_dir, download, ask, say, fetch)
    cc = tried(cc, f"Zig ({' '.join(cc.argv)})")
    cc.version = "zig " + cc.version
    return cc


# ---- building ---------------------------------------------------------------------------------------------------------------------------------------------
def newest(paths):
    return max((os.path.getmtime(p) for p in paths if os.path.exists(p)), default=0)


def tmp_name(path):
    """Where a module is linked before it is moved into place; the extension stays last (a Windows linker makes the .lib and .pdb names from it)."""
    root, ext = os.path.splitext(path)
    return root + ".tmp" + ext


def plan(programs, gen_root, port_dir, native_dir, build_dir, out_dir, cc, target_os=None, target=None, strip=False):
    """{program: {"srcs": [...], "objs": [...], "out": path, "compile": [(src, obj, argv)...], "link": argv}} for the programs that have lifted C. `target`: a Target to build for."""
    target_os = target.os if target is not None else target_os or host_os()
    headers = [os.path.join(native_dir, h) for h in HEADERS]
    result = {}
    for prog in programs:
        gen_dir = os.path.join(gen_root, PROGRAMS.get(prog) or SOTA_PROGRAMS.get(prog) or LICENCE_PROGRAMS.get(prog, prog))
        srcs = program_sources(gen_dir, port_dir)
        objs = [os.path.join(build_dir, prog, os.path.splitext(os.path.basename(s))[0] + ".o") for s in srcs]
        out = os.path.join(out_dir, f"game_{prog}.{module_ext(target_os)}")
        result[prog] = {
            "srcs": srcs, "objs": objs, "out": out, "headers": headers,
            "compile": [(s, o, compile_command(cc, s, o, native_dir, target_os, target)) for s, o in zip(srcs, objs)],
            "link": link_command(cc, objs, tmp_name(out), target_os, target, strip),
        }
    return result


def human(seconds):
    seconds = int(seconds)
    return f"{seconds // 60} min {seconds % 60:02d} s" if seconds >= 60 else f"{seconds} s"


def build_modules(programs, gen_root, port_dir, native_dir, build_dir, out_dir, cc, jobs=None, say=print, target_os=None, heartbeat=20.0, runner=run_quiet, target=None, strip=False):
    """Compile every file of every program in `programs` (up to `jobs` at once, the biggest first; a file whose object is newer than it and the headers is left alone), then link each
    module into out_dir/game_<program>.<ext>. Prints the file count and percent (by size of the C) as files finish, and a line every `heartbeat` seconds while a big one is running.
    Returns {program: path of the module}. `target`: a Target to cross-build for (give it a build_dir of its own: the objects of one target are not another's); `strip`: link without symbols and debug information."""
    jobs = jobs or max(1, min(os.cpu_count() or 1, 8))
    target_os = target.os if target is not None else target_os
    plans = plan(programs, gen_root, port_dir, native_dir, build_dir, out_dir, cc, target_os, target, strip)
    todo = []
    total = done_bytes = 0
    for prog, p in plans.items():
        stale_from = newest(p["headers"])
        for src, obj, cmd in p["compile"]:
            size = os.path.getsize(src)
            total += size
            if os.path.exists(obj) and os.path.getmtime(obj) >= max(os.path.getmtime(src), stale_from):
                done_bytes += size
            else:
                todo.append((size, prog, src, obj, cmd))
    nfiles = sum(len(p["compile"]) for p in plans.values())
    ndone = nfiles - len(todo)
    todo.sort(key=lambda t: -t[0])
    if not todo:
        say("all objects are up to date")
    else:
        say(f"compiling {len(todo)} files with {jobs} at a time, {sum(t[0] for t in todo) // (1 << 20)} MB of C ({cc.describe()})")
    started = {}

    def work(size, prog, src, obj, cmd):
        os.makedirs(os.path.dirname(obj), exist_ok=True)
        started[src] = time.time()
        r = runner(cmd, cc.env)
        if r.returncode != 0:
            if os.path.exists(obj):
                os.remove(obj)
            tail = "\n".join(r.stdout.strip().splitlines()[-25:])
            raise BuildError(f"compiling {os.path.basename(src)} failed (exit {r.returncode}):\n  {' '.join(cmd)}\n{tail}")
        return size

    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        pending = {pool.submit(work, *t): t for t in todo}
        last_say = time.time()
        try:
            while pending:
                finished, _ = concurrent.futures.wait(pending, timeout=heartbeat, return_when=concurrent.futures.FIRST_COMPLETED)
                for fut in finished:
                    size, prog, src, obj, cmd = pending.pop(fut)
                    fut.result()
                    ndone += 1
                    done_bytes += size
                    say(f"  [{ndone}/{nfiles}] {done_bytes * 100 // max(total, 1):3d}%  {prog}/{os.path.basename(src)}  ({human(time.time() - t0)})")
                    last_say = time.time()
                if not finished and time.time() - last_say >= heartbeat:
                    running = [os.path.basename(t[2]) + f" ({t[0] // (1 << 20)} MB, {human(time.time() - started[t[2]])})" for t in pending.values() if t[2] in started]
                    say(f"  ... {done_bytes * 100 // max(total, 1)}% done after {human(time.time() - t0)}; still compiling: {', '.join(running)}")
                    last_say = time.time()
        except BaseException:
            for fut in pending:
                fut.cancel()
            raise
    made = {}
    for prog, p in plans.items():
        say(f"linking game_{prog}.{module_ext(target_os)}")
        os.makedirs(os.path.dirname(p["out"]), exist_ok=True)
        before = set(os.listdir(os.path.dirname(p["out"])))
        r = runner(p["link"], cc.env)
        if r.returncode != 0:
            raise BuildError(f"linking {p['out']} failed (exit {r.returncode}):\n  {' '.join(p['link'])}\n" + "\n".join(r.stdout.strip().splitlines()[-25:]))
        os.replace(tmp_name(p["out"]), p["out"])
        if target is not None and target_os == "windows":      # a Windows link also writes an import library (Zig names it after the first object) and maybe a debug file: not part of the module
            for name in set(os.listdir(os.path.dirname(p["out"]))) - before:
                if name.lower().endswith((".lib", ".pdb")):
                    os.remove(os.path.join(os.path.dirname(p["out"]), name))
        made[prog] = p["out"]
    return made


def smoke_test(run, module, runner=run_quiet):
    """Start the runtime with the module on a program that is not there (no game files needed): the module loaded if the runtime gets as far as saying it cannot open the program.
    Returns (ok, the runtime's output)."""
    try:
        r = runner([run, "-m", module, "no-such-folder/Program/MAGIC.EXE"], {"PORT_HEADLESS": "1"}, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return ("cannot open no-such-folder/Program/MAGIC.EXE" in r.stdout), r.stdout.strip()


def self_test(cc, port_dir, native_dir, run, say=print, jobs=2):
    """Build the stub module that ships in src/port/stubgame (three hand-written functions in the lifter's style, no game) with this compiler and load it into the runtime:
    shows the compiler, the headers and the runtime work together before the 15 minutes of the real build. Returns (ok, output)."""
    with tempfile.TemporaryDirectory(prefix="pentamoor-selftest-") as d:
        made = build_modules(["stubgame"], port_dir, port_dir, native_dir, os.path.join(d, "obj"), os.path.join(d, "out"), cc, jobs, say)
        return smoke_test(run, made["stubgame"])


# ---- the command line: build the modules for this machine or, with --target, for another ---------------------------------------------------------------------
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def main(argv=None, say=print):
    import argparse
    ap = argparse.ArgumentParser(description="Compile the game modules from the C the lifter wrote (tools/lift), for this machine or, with --target, for another system or processor. "
                                             "Nothing is run, and nothing is changed outside --out and --build-dir.")
    ap.add_argument("--target", help=f"build for another system: {', '.join(TARGETS)} (or a Zig triple such as x86_64-windows-gnu); default: this machine, as the installer does")
    ap.add_argument("--out", help="where the game_<program>.<ext> files go (default: dist/modules/<target>)")
    ap.add_argument("--gen", help="the lifter's output folder, holding lift_magic_all, lift_deck and lift_duel (default: sources/generated)")
    ap.add_argument("--programs", nargs="+", default=list(PROGRAMS), help=f"which programs (default: {' '.join(PROGRAMS)})")
    ap.add_argument("--root", default=ROOT, help="the folder that holds src/port, src/native and tools/local (default: the one this file is in)")
    ap.add_argument("--build-dir", help="where the object files go (default: sources/build/<target>); a target needs one of its own")
    ap.add_argument("--compiler", help="the compiler: a command, or 'zig' for the one in tools/local (default: for a target, Zig, or Apple's clang for a Mac target on a Mac)")
    ap.add_argument("--tools", help="the folder that holds ziglang/, where Zig is downloaded if it is needed (default: tools/local)")
    ap.add_argument("--no-download", action="store_true", help="never download the Zig compiler")
    ap.add_argument("--jobs", "-j", type=int, help="how many C files to compile at once (default: the number of processors, at most 8)")
    ap.add_argument("--strip", action="store_true", help="link without symbols and debug information (a Zig-built Linux module is five times smaller)")
    ap.add_argument("--list-targets", action="store_true", help="print the known targets and exit")
    args = ap.parse_args(argv)
    if args.list_targets:
        for t in TARGETS.values():
            say(f"{t.name:16} zig -target {t.zig}")
        return 0
    try:
        target = parse_target(args.target)
        root = os.path.abspath(args.root)
        label = target.name if target else "native"
        port, native = os.path.join(root, "src", "port"), os.path.join(root, "src", "native")
        gen = os.path.abspath(args.gen or os.path.join(root, "sources", "generated"))
        out = os.path.abspath(args.out or os.path.join(root, "dist", "modules", label))
        build = os.path.abspath(args.build_dir or os.path.join(root, "sources", "build", label))
        cc = find_target_compiler(target, native, os.path.abspath(args.tools or os.path.join(root, "tools", "local")), args.compiler, download=not args.no_download, say=say)
        say(f"building for {label} with {cc.describe()}")
        made = build_modules(args.programs, gen, port, native, build, out, cc, jobs=args.jobs, say=say, target=target, strip=args.strip)
    except BuildError as e:
        say(f"modbuild: {e}")
        return 1
    for prog, path in made.items():
        say(f"{path}  {os.path.getsize(path)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

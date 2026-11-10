#!/usr/bin/env python3
"""
smoke_archive.py - try a release archive on a machine that did not build it, the way a user would, with no game files.

    python tools/release/smoke_archive.py dist/pentamoor-0.1.0-linux-x86_64.tar.gz [--work DIR] [--only no-sdl] [--keep]

check_archive.py (run by package.yml next to the build) looks inside an archive on the machine that built it. This is the other half, run by .github/workflows/archive-smoke.yml on a
fresh runner of each system that downloads the archive as a user does: it unpacks it with the system's own tools into a folder whose name has a space in it, and prints one line per
thing it tried (`[smoke] ok   <what>` or `[smoke] FAIL <what>`), then a summary; the exit status is 1 if any failed. It runs everything it can without the game:

  archive      unpacks (tar, or on Windows tar.exe for the .zip); the checksums of every file; nothing game-derived in it (check_archive.py's checks); how long the longest path is
  python       the archive's Python (Windows: python\\python.exe, the embedded one; elsewhere the system's python3) runs the installer's --check, imports pefile and capstone from
               the archive, and lifts three hand-assembled functions to C with the archive's lifter (smoke_inside.py)
  compiler     install.py --self-test with the compiler the installer finds on its own: on Windows with a PATH of only Windows' folders, so it must be the Zig in the archive; elsewhere
               the system's cc. Elsewhere also with no compiler on the PATH and --no-download: the message must say what to do (the Zig download is network and is not tried)
  runtime      the archive's pentamoor-run, with a stub game module built here by the installer's own build step and a tiny PE file made here (stub.exe, the same bytes as
               src/port/stubgame/mkpe.c writes): the module loads, a missing module and a file that is not a module are refused, the SDL window half starts on SDL's dummy
               drivers, the program runs through the PE loader and the file layer (exit status 7, HELLO.TXT of 24 bytes), and an unsupported build is refused (exit status 3)
  installer    smoke_install.py: wrong discs, and a made-up 1.0 disc installed with three modules built and loaded (Windows: pentamoor-install.bat and the embedded Python)
  launchers    pentamoor.bat / ./pentamoor with no game installed: the documented message and a non-zero exit status (Windows: through cmd.exe, also in a folder named
               "Program Files (x86)"); after the made-up install, the launcher reaches the runtime, which refuses the made-up program as an unsupported build
  steamdeck    the Steam Deck archive's own files (check_archive.check_steamdeck)

Not covered, and said so in the summary: the game itself (it needs the game's files), the Zig download (network), a process-spawn round trip of the runtime (docs/notes/ci.md).
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_archive  # noqa: E402
import check_tree  # noqa: E402
import smoke_install  # noqa: E402

WIN = os.name == "nt"
STUB_SHA = "a619942cb4f2a8284c233ba23f401a2fb0302dcfc84e469462a6be84ba871382"       # the build id of stub.exe: src/port/Makefile (check-build) and profile.c have it


def make_stub_pe():
    """The bytes src/port/stubgame/mkpe.c writes (the smallest PE32 the runtime loads: an import table of ExitProcess, CreateFileA, WriteFile and CloseHandle, one byte of code)."""
    img = bytearray(0x600)

    def put16(at, v):
        img[at] = v & 255
        img[at + 1] = (v >> 8) & 255

    def put32(at, v):
        put16(at, v & 0xFFFF)
        put16(at + 2, v >> 16)

    opt, sec, idata = 0x58, 0x138, 0x400
    img[0:2] = b"MZ"
    put32(0x3c, 0x40)
    img[0x40:0x44] = b"PE\0\0"
    put16(0x44, 0x14c)
    put16(0x46, 2)
    put16(0x54, 0xE0)
    put16(0x56, 0x0102)
    put16(opt, 0x10b)
    put32(opt + 4, 0x200)
    put32(opt + 8, 0x200)
    put32(opt + 16, 0x1000)
    put32(opt + 20, 0x1000)
    put32(opt + 24, 0x2000)
    put32(opt + 28, 0x400000)
    put32(opt + 32, 0x1000)
    put32(opt + 36, 0x200)
    put16(opt + 40, 4)
    put16(opt + 48, 4)
    put32(opt + 56, 0x3000)
    put32(opt + 60, 0x200)
    put16(opt + 68, 2)
    put32(opt + 72, 0x100000)
    put32(opt + 76, 0x1000)
    put32(opt + 80, 0x100000)
    put32(opt + 84, 0x1000)
    put32(opt + 92, 16)
    put32(opt + 104, 0x2000)
    put32(opt + 108, 0x28)
    img[sec:sec + 5] = b".text"
    put32(sec + 8, 0x10)
    put32(sec + 12, 0x1000)
    put32(sec + 16, 0x200)
    put32(sec + 20, 0x200)
    put32(sec + 36, 0x60000020)
    img[sec + 40:sec + 46] = b".idata"
    put32(sec + 48, 0x200)
    put32(sec + 52, 0x2000)
    put32(sec + 56, 0x200)
    put32(sec + 60, 0x400)
    put32(sec + 76, 0xC0000040)
    img[0x200] = 0xC3
    put32(idata + 0x00, 0x2080)
    put32(idata + 0x0c, 0x2060)
    put32(idata + 0x10, 0x2100)
    img[idata + 0x60:idata + 0x60 + 13] = b"KERNEL32.dll\0"
    for i, name in enumerate((b"ExitProcess", b"CreateFileA", b"WriteFile", b"CloseHandle")):
        entry = 0xA0 + 0x10 * i
        img[idata + entry + 2:idata + entry + 2 + len(name) + 1] = name + b"\0"
        put32(idata + 0x80 + 4 * i, 0x2000 + entry)
        put32(idata + 0x100 + 4 * i, 0x2000 + entry)
    return bytes(img)


class Smoke:
    def __init__(self, archive, work, keep):
        self.archive = os.path.abspath(archive)
        self.work = work
        self.keep = keep
        self.results = []
        self.root = None
        self.py = None
        self.module_ext = "dll" if WIN else "dylib" if sys.platform == "darwin" else "so"
        self.run_exe = None
        self.stub_module = None

    # ---- reporting ----
    def check(self, name, ok, detail=""):
        if ok:                                                           # (a passing line is one line; a failing one keeps everything it has)
            first = detail.strip().splitlines()[0] if detail.strip() else ""
            detail = first if len(first) <= 150 else first[:147] + "..."
        self.results.append((name, ok, detail))
        print(f"[smoke] {'ok  ' if ok else 'FAIL'} {name}" + (f": {detail}" if detail else ""), flush=True)
        if not ok and os.environ.get("GITHUB_ACTIONS"):
            print(f"::error title=smoke: {name}::{detail.strip().splitlines()[0] if detail.strip() else 'failed'}", flush=True)
        return ok

    def note(self, text):
        print(f"[smoke] note {text}", flush=True)

    def guarded(self, name, fn, *args):
        try:
            return fn(*args)
        except Exception as e:                                           # (a crash of the test itself is a failed line, not a lost run)
            import traceback
            self.check(name, False, f"the smoke test itself crashed: {type(e).__name__}: {e}\n{traceback.format_exc()[-1200:]}")
            return None

    # ---- running things as a user's machine would ----
    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("PORT_", "PENTAMOOR_")) and k not in ("PYTHONPATH", "PYTHONHOME", "SDL_VIDEODRIVER", "SDL_AUDIODRIVER")}
        if WIN:                                                          # a user's PATH has none of MSYS2's, MinGW's, Git's or the runner's Python folders
            system = os.environ.get("SystemRoot", r"C:\Windows")
            for k in [k for k in env if k.upper() == "PATH"]:
                del env[k]
            env["PATH"] = os.path.join(system, "System32") + os.pathsep + system
        for k in ("DISPLAY", "WAYLAND_DISPLAY", "GAMESCOPE_WAYLAND_DISPLAY"):
            env.pop(k, None)                                             # (the Steam Deck archive's launcher starts a window installer when there is a display)
        env.update(extra)
        return env

    def run(self, cmd, cwd=None, env=None, timeout=600, shell_string=False):
        t0 = time.time()
        try:
            r = subprocess.run(cmd, cwd=cwd or self.root, env=env or self.env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        except subprocess.TimeoutExpired as e:
            return 124, f"TIMED OUT after {timeout} s\n" + (e.stdout.decode("utf-8", "replace") if e.stdout else "")
        except OSError as e:
            return 127, f"could not start {cmd if isinstance(cmd, str) else cmd[0]}: {e}"
        out = r.stdout.decode("utf-8", "replace").replace("\r\n", "\n")
        if os.environ.get("SMOKE_VERBOSE"):
            print(f"      ({time.time() - t0:.1f} s) {cmd}\n{out}")
        return r.returncode, out

    def inside(self, args, timeout=600):
        """smoke_inside.py with the archive's Python, isolated (-I), from the archive's folder."""
        return self.run([self.py, "-I", os.path.join(HERE, "smoke_inside.py")] + args, timeout=timeout)

    def cmd_bat(self, script, args, root=None):
        """cmd.exe's command line for a batch file with arguments: the whole thing in one more pair of quotes (the /s rule), because a path with spaces or ( ) needs it."""
        root = root or self.root
        return 'cmd.exe /d /s /c ""' + os.path.join(root, script) + '" ' + " ".join(f'"{a}"' for a in args) + '"'

    def installer(self, args):
        if WIN:
            return self.run(self.cmd_bat("pentamoor-install.bat", args), timeout=1500)
        return self.run([os.path.join(self.root, "pentamoor-install")] + args, timeout=1500)

    def launcher(self, args, env=None, root=None):
        if WIN:
            return self.run(self.cmd_bat("pentamoor.bat", args, root), cwd=root, env=env, timeout=300)
        return self.run([os.path.join(root or self.root, "pentamoor")] + args, cwd=root, env=env, timeout=300)

    # ---- 1. the archive ----
    def unpack(self):
        dest = os.path.join(self.work, "Alice Smith", "Downloads")
        os.makedirs(dest)
        t0 = time.time()
        if self.archive.endswith(".zip"):
            tar = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")
            cmd = [tar if os.path.exists(tar) else "tar", "-xf", self.archive, "-C", dest]
        else:
            cmd = ["tar", "-xzf", self.archive, "-C", dest]
        code, out = self.run(cmd, cwd=dest, env=os.environ.copy(), timeout=900)
        tops = os.listdir(dest)
        self.check("archive: unpacked with the system's tar", code == 0 and len(tops) == 1, f"{cmd[0]} exit {code}, {tops}, {time.time() - t0:.0f} s" + ("" if code == 0 else f"\n{out[-600:]}"))
        if code != 0 or len(tops) != 1:
            return False
        self.root = os.path.join(dest, tops[0])
        files = check_archive.all_files(self.root)
        sums = check_archive.check_sums(self.root, files)
        self.check("archive: every file is in SHA256SUMS with the right checksum", not sums, f"{len(files)} files" + ("" if not sums else "; " + "; ".join(sums[:5])))
        bad = check_archive.forbidden(files)
        looks = check_tree.check_files(self.root, [f for f in files if not f.startswith(check_archive.THIRD_PARTY)])
        self.check("archive: nothing made from the game", not bad and not looks, "; ".join(bad[:5] + looks[:5]) if bad or looks else "no game file, game module, generated C or decompiler output")
        longest = max(files, key=len)
        user_path = len("C:\\Users\\Alice Smith\\Downloads\\") + len(os.path.basename(self.root)) + 1 + len(longest)
        self.check("archive: the longest path stays under Windows' 260 characters in a typical Downloads folder" if WIN else "archive: longest path",
                   user_path < 260 or not WIN, f"{len(longest)} characters inside the archive folder ({longest[-60:]}); {user_path} in C:\\Users\\Alice Smith\\Downloads")
        exe = "pentamoor-run" + (".exe" if WIN else "")
        self.run_exe = os.path.join(self.root, exe)
        self.check(f"archive: {exe} is there" + (" and executable" if not WIN else ""), os.path.isfile(self.run_exe) and (WIN or os.access(self.run_exe, os.X_OK)), "")
        if not WIN:
            nox = [n for n in ("pentamoor", "pentamoor-install") if not os.access(os.path.join(self.root, n), os.X_OK)]
            self.check("archive: the launchers are executable after tar", not nox, f"not executable: {nox}" if nox else "pentamoor, pentamoor-install")
        if sys.platform == "darwin":
            code, out = self.run(["lipo", "-archs", self.run_exe])
            want = ("arm64", "x86_64") if "universal" in os.path.basename(self.archive) else ()
            self.check("archive: the runtime's architectures" + (" (universal)" if want else ""), code == 0 and all(a in out for a in want), out.strip())
            code, out = self.run(["codesign", "-v", self.run_exe])
            self.check("archive: the runtime's ad hoc signature is valid", code == 0, out.strip()[:200])
        embedded = os.path.join(self.root, "python", "python.exe")
        self.py = embedded if os.path.exists(embedded) else shutil.which("python3") or sys.executable
        code, out = self.run([self.py, "-I", "-c", "import sys; print(sys.version.split()[0], sys.executable)"])
        self.check("python: the Python that runs the installer", code == 0, out.strip() + (" (the archive's own)" if self.py == embedded else " (the system's)"))
        return code == 0

    # ---- 2. python and the lifter ----
    def python_checks(self):
        code, out = self.run([self.py, "-I", os.path.join("tools", "install", "install.py"), "--check"])
        self.check("python: install.py --check finds the release complete", code == 0 and "files:  all there" in out, out.strip()[-500:] if code else "files all there, packages import")
        code, out = self.inside(["lift", self.root])
        self.check("python: pefile/capstone import from the archive, and its lifter lifts three functions to C", code == 0, out.strip()[-500:] if code else out.strip().splitlines()[-1])

    # ---- 3. the compiler ----
    def compiler_checks(self):
        cmd = [self.py, "-I", os.path.join("tools", "install", "install.py"), "--self-test", "--no-download", "--yes"]
        code, out = self.run(cmd, timeout=1500)
        line = next((l for l in out.splitlines() if l.startswith("compiler:")), "no 'compiler:' line")
        ok = code == 0 and "self-test: the stub module built and loaded in the runtime" in out
        if WIN:
            ok = ok and "ziglang" in line.replace("\\", "/") and os.path.join("tools", "local").replace("\\", "/") in line.replace("\\", "/")
        self.check("compiler: install.py --self-test with the compiler it finds" + (" (the Zig in the archive, nothing else on the PATH)" if WIN else ""), ok,
                   line + ("" if ok else f"\nexit {code}: {out.strip()[-900:]}"))
        if not WIN:
            empty = os.path.join(self.work, "empty-path")
            os.makedirs(empty, exist_ok=True)
            code, out = self.run(cmd, env=self.env(PATH=empty), timeout=300)
            self.check("compiler: with no compiler and --no-download the installer says what to do", code == 1 and "no working C compiler" in out and "downloading Zig is switched off" in out,
                       f"exit {code}; " + out.strip()[-300:])
            self.note("the Zig download (no compiler, network) is not tried here")

    # ---- 4. the runtime with a stub module and a made-up PE ----
    def runtime_checks(self):
        out_dir = os.path.join(self.work, "stub")
        code, out = self.inside(["build-stub", self.root, out_dir], timeout=900)
        module = os.path.join(out_dir, "game_stubgame." + self.module_ext)
        if not self.check("runtime: the stub game module is built by the installer's own build step", code == 0 and os.path.exists(module), out.strip()[-600:] if code else out.strip().splitlines()[-2] if out.strip() else ""):
            return
        self.stub_module = module
        game = os.path.join(self.work, "prog")
        os.makedirs(game, exist_ok=True)
        pe = make_stub_pe()
        self.check("runtime: stub.exe made here is the build the runtime's checks name", hashlib.sha256(pe).hexdigest() == STUB_SHA, hashlib.sha256(pe).hexdigest()[:16])
        stub_exe, other_exe = os.path.join(game, "stub.exe"), os.path.join(game, "other.exe")
        with open(stub_exe, "wb") as f:
            f.write(pe)
        with open(other_exe, "wb") as f:
            f.write(pe + b"x")
        run = self.run_exe
        headless = self.env(PORT_HEADLESS="1")
        nowhere = "no-such-folder/Program/MAGIC.EXE"
        code, out = self.run([run, "-m", module, nowhere], cwd=self.work, env=headless, timeout=120)
        self.check("runtime: loads the stub module and stops at the program that is not there", f"cannot open {nowhere}" in out, f"exit {code}; {out.strip()[-300:]}")
        code, out = self.run([run, "-m", os.path.join(out_dir, "nonexistent." + self.module_ext), "x.exe"], cwd=self.work, env=headless, timeout=120)
        self.check("runtime: refuses a module that is not there", "cannot load the game module" in out, f"exit {code}; {out.strip()[-300:]}")
        code, out = self.run([run, "-m", run, "x.exe"], cwd=self.work, env=headless, timeout=120)
        self.check("runtime: refuses a file that is not a module", "no pentamoor_game_init" in out or "cannot load the game module" in out, f"exit {code}; {out.strip()[-300:]}")
        sdl = self.env(SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
        code, out = self.run([run, "-m", module, nowhere], cwd=self.work, env=sdl, timeout=120)
        self.check("runtime: the SDL window half starts on SDL's dummy drivers", f"cannot open {nowhere}" in out and code == 2, f"exit {code}; {out.strip()[-300:]}")
        code, out = self.run([run, "-m", module, nowhere], cwd=self.work, env=dict(sdl, PORT_PAD_LOG="stderr"), timeout=120)
        self.check("runtime: SDL reports its video driver and joysticks", "video driver dummy" in out and "joystick(s) at start" in out, out.strip()[-300:])
        overlay = os.path.join(self.work, "prog_overlay")
        code, out = self.run([run, "-m", module, stub_exe, game], cwd=self.work, env=dict(headless, PORT_UNKNOWN_BUILD="1", PORT_OVERLAY=overlay), timeout=120)
        hello = os.path.join(overlay, "HELLO.TXT")
        data = open(hello, "rb").read() if os.path.exists(hello) else b""
        self.check("runtime: runs a PE program through the loader, the imports and the file layer", code == 7 and len(data) == 24 and b"hello from lifted code" in data,
                   f"exit {code} (7 expected), HELLO.TXT {len(data)} bytes (24 expected)" + ("" if code == 7 and len(data) == 24 else f"\n{out.strip()[-500:]}"))
        overlay2 = os.path.join(self.work, "build_overlay")
        code, out = self.run([run, "-m", module, stub_exe, game], cwd=self.work, env=dict(headless, PORT_OVERLAY=overlay2), timeout=120)
        self.check("runtime: refuses a build it does not know (exit 3) and does not run it", code == 3 and "which this version does not support" in out and not os.path.exists(os.path.join(overlay2, "HELLO.TXT")),
                   f"exit {code}; {out.strip()[-300:]}")
        code, out = self.run([run, "-m", module, other_exe, game], cwd=self.work, env=dict(headless, PORT_OVERLAY=overlay2), timeout=120)
        self.check("runtime: refuses a program that is not the one the module was made from (exit 3)", code == 3 and "but the game module was made from build a619942c" in out, f"exit {code}; {out.strip()[-300:]}")
        if sys.platform.startswith("linux"):
            code, out = self.run(["ldd", run])
            self.note("what the runtime needs (ldd): " + ", ".join(l.split("=>")[0].strip() for l in out.splitlines()))

    # ---- 5. the launchers ----
    def launcher_checks_empty(self):
        code, out = self.launcher([])
        if WIN:
            ok = code == 1 and "the game is not installed yet" in out and ("no disc image given" in out or "install: cancelled" in out)
            what = "the documented offer, then the installer asks for the disc and is cancelled (stdin is NUL)"
        else:
            ok = code == 1 and "pentamoor-install" in out and "is not installed" in out
            what = "the message that names pentamoor-install"
        self.check("launcher: no game installed (no terminal): prints the message and exits 1", ok, f"exit {code}; " + (what if ok else out.strip()[-500:]))
        code, out = self.launcher(["sota"])
        self.check("launcher: sota with no 2.15 install: says what it is built from, exits 1", code == 1 and "Spells of the Ancients 2.15 is not installed" in out, f"exit {code}; " + out.strip()[-300:])
        if WIN:
            self.launcher_in_parens()

    def launcher_in_parens(self):
        """The launcher and the installer's first step in a folder like C:\\Program Files (x86)\\...: only the files they need are copied there."""
        dest = os.path.join(self.work, "Program Files (x86)", "Pentamoor Smoke")
        os.makedirs(dest)
        for name in ("pentamoor.bat", "pentamoor-install.bat"):
            shutil.copyfile(os.path.join(self.root, name), os.path.join(dest, name))
        for sub in ("python", os.path.join("tools", "install"), os.path.join("tools", "lift")):
            shutil.copytree(os.path.join(self.root, sub), os.path.join(dest, sub))
        code, out = self.launcher([], root=dest)
        self.check("launcher: pentamoor.bat in 'Program Files (x86)\\...' prints the message and exits 1", code == 1 and "the game is not installed yet" in out and ("no disc image given" in out or "install: cancelled" in out),
                   f"exit {code}; " + out.strip()[-500:])
        code, out = self.run(self.cmd_bat("pentamoor-install.bat", ["--help"], dest), cwd=dest)
        self.check("launcher: pentamoor-install.bat --help in that folder", code == 0 and "--sota" in out, f"exit {code}; " + out.strip()[-300:])

    def launcher_checks_installed(self):
        """After the made-up install: the launcher goes all the way to the runtime, which refuses the made-up MAGIC.EXE (a build it does not know)."""
        env = self.env(PORT_HEADLESS="1", PORT_OVERLAY=os.path.join(self.work, "launch_overlay"), SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
        code, out = self.launcher([], env=env)
        self.check("launcher: with the made-up install it starts the runtime, which refuses the made-up program (exit 3)", code == 3 and "pentamoor: MAGIC.EXE is build" in out,
                   f"exit {code}; " + out.strip()[-500:])

    def no_sdl_checks(self):
        """Linux, on a runner without SDL2 (a fresh user's system): the runtime cannot start and the launcher says why."""
        code, out = self.run(["ldd", self.run_exe])
        if "libSDL2" not in out or "not found" not in out:
            self.note("this machine has SDL2 installed: the 'no SDL2' launcher message cannot be tried here")
            return
        code, out = self.run([self.run_exe, "--help"])
        self.check("no SDL2: the runtime's own failure is the loader's line", code != 0 and "libSDL2" in out, out.strip()[-200:])
        fake = os.path.join(self.work, "fakegame")
        os.makedirs(fake)
        open(os.path.join(fake, "MAGIC.EXE"), "wb").close()
        open(os.path.join(self.work, "game_fake.so"), "wb").close()
        code, out = self.launcher([], env=self.env(PENTAMOOR_GAME=fake, PENTAMOOR_MODULE=os.path.join(self.work, "game_fake.so")))
        self.check("no SDL2: ./pentamoor says SDL2 is not installed and how to install it", code == 1 and "SDL2 is not installed" in out and "libsdl2-2.0-0" in out, f"exit {code}; " + out.strip()[-300:])

    # ---- the Steam Deck archive ----
    def steamdeck_checks(self):
        if not os.path.isdir(os.path.join(self.root, "tools", "steamdeck")):
            return
        problems = check_archive.check_steamdeck(self.root, self.py, self.env())
        self.check("steamdeck: its scripts parse, add-to-steam.py writes a shortcut into a fake Steam folder, the installer's text mode asks its first question", not problems, "; ".join(problems))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("archive")
    ap.add_argument("--work", help="a new, empty folder to work in (default: a temporary one)")
    ap.add_argument("--only", choices=["no-sdl"], help="no-sdl: only unpack, and, on a Linux runner without SDL2, check what a user without it sees")
    ap.add_argument("--keep", action="store_true", help="leave the work folder")
    args = ap.parse_args()
    holder = None
    work = args.work
    if work:
        os.makedirs(work, exist_ok=True)
    else:
        holder = tempfile.mkdtemp(prefix="pentamoor-smoke-")
        work = holder
    s = Smoke(args.archive, work, args.keep)
    print(f"[smoke] archive {os.path.basename(args.archive)} on {sys.platform} {os.uname().machine if hasattr(os, 'uname') else os.environ.get('PROCESSOR_ARCHITECTURE', '')}, work folder {work}", flush=True)
    t0 = time.time()
    if s.guarded("archive", s.unpack):
        if args.only == "no-sdl":
            s.guarded("no SDL2", s.no_sdl_checks)
        else:
            s.guarded("python", s.python_checks)
            s.guarded("compiler", s.compiler_checks)
            s.guarded("runtime", s.runtime_checks)
            s.guarded("launcher", s.launcher_checks_empty)
            s.guarded("steamdeck", s.steamdeck_checks)                   # (before the installer: its window installer says "already installed" afterwards)
            s.guarded("installer", smoke_install.installer_phase, s)
            if os.path.exists(os.path.join(s.root, "game_magic." + s.module_ext)):
                s.guarded("launcher", s.launcher_checks_installed)
    failed = [r for r in s.results if not r[1]]
    print(f"\n[smoke] {len(s.results) - len(failed)} of {len(s.results)} checks passed in {time.time() - t0:.0f} s")
    for name, ok, detail in failed:
        print(f"[smoke] FAILED: {name}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"### {os.path.basename(args.archive)}: {len(s.results) - len(failed)} of {len(s.results)} checks passed\n\n")
            for name, ok, detail in s.results:
                f.write(f"- {'ok' if ok else '**FAIL**'} {name}\n")
            f.write("\n")
    if holder and not args.keep:
        shutil.rmtree(holder, ignore_errors=True)
    sys.exit(1 if failed or not s.results else 0)


if __name__ == "__main__":
    main()

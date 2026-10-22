#!/usr/bin/env python3
"""
check_archive.py - unpack a release archive somewhere new and check it, with no game files:

  * every file is in SHA256SUMS with the right checksum, and nothing else is there;
  * nothing made from the game, and no game module, is in it (no sources/, no *_gen.c but the hand-written stub, no MAGIC.EXE, no game_magic.so ...; and none of the licence step's
    files: the original installer's library Manaball.wav, the module made from it, an install's registry.dat), and nothing that looks like
    decompiler output (check_tree.py);
  * the installer finds the release complete (`install.py --check`) and imports pefile and capstone from the archive's own tools/pydeps, capstone's native library included;
  * `install.py --self-test` picks a compiler, builds the stub module with the archive's headers and loads it into the archive's own runtime (so the runtime starts, finds its
    libraries, and the module-building step works from this layout);
  * (Linux, macOS) the launcher, with no game installed and no terminal, refuses and says how to install.

    python tools/release/check_archive.py dist/pentamoor-0.1.0-linux-x86_64.tar.gz [--compiler zig]

Runs with the archive's own Python when it has one (Windows: python\\python.exe), else the Python it runs with.
"""
import argparse
import fnmatch
import hashlib
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_tree  # noqa: E402

FORBIDDEN_NAMES = {"magic.exe", "deck.exe", "duel.exe", "deckdll.dll", "statwin.dll", "magsnd.dll", "magvid.dll", "data.z",
                   # Spells of the Ancients 2.15 (the files of its install, and the patch and the cabinets it is made from)
                   "shandalar.exe", "facemaker.exe", "cardartlib.dll", "drawcardlib.dll", "cdtools.dll", "cards.dat", "facedata.txt", "data1.cab", "_sys1.cab", "_user1.cab", "sotav215.exe",
                   # the licence step (tools/install/licence.py): the original installer's own library from the expansion's cabinet, and the file an install keeps its registry values in
                   "manaball.wav", "senclib.dll", "registry.dat"}
FORBIDDEN_PATTERNS = ["*_gen.c", "*_spec.json", "game_magic.*", "game_deck.*", "game_duel.*", "game_shandalar.*", "game_facemaker.*", "game_sotadeck.*", "game_shell.*", "game_senclib.*", "*senclib*", "*.iso", "*.mdf", "*.mds", "*.sav", "*.cab"]
ALLOWED = {"src/port/stubgame/handlers_gen.c"}          # written by hand, not generated, not the game's


def extract(archive, dest):
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for n in z.namelist():
                target = os.path.realpath(os.path.join(dest, n))
                if not target.startswith(os.path.realpath(dest) + os.sep):
                    sys.exit(f"check_archive: {n} points outside the folder")
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            if hasattr(tarfile, "data_filter"):
                t.extractall(dest, filter="data")
            else:
                for m in t.getmembers():
                    if not os.path.realpath(os.path.join(dest, m.name)).startswith(os.path.realpath(dest) + os.sep):
                        sys.exit(f"check_archive: {m.name} points outside the folder")
                t.extractall(dest)
    tops = os.listdir(dest)
    if len(tops) != 1:
        sys.exit(f"check_archive: expected one folder in the archive, found {tops}")
    return os.path.join(dest, tops[0])


def all_files(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        for f in filenames:
            out.append(os.path.relpath(os.path.join(dirpath, f), root).replace(os.sep, "/"))
    return sorted(out)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def check_sums(root, files):
    problems = []
    listed = {}
    with open(os.path.join(root, "SHA256SUMS"), encoding="utf-8") as f:
        for line in f:
            digest, _, name = line.rstrip("\n").partition("  ")
            if name:
                listed[name] = digest
    for name, digest in listed.items():
        if not os.path.exists(os.path.join(root, name)):
            problems.append(f"SHA256SUMS lists {name}, which is not there")
        elif sha256_file(os.path.join(root, name)) != digest:
            problems.append(f"{name}: checksum differs from SHA256SUMS")
    for name in files:
        if name != "SHA256SUMS" and name not in listed:
            problems.append(f"{name} is not in SHA256SUMS")
    return problems


THIRD_PARTY = ("tools/local/ziglang/", "python/", "tools/pydeps/")       # carried as they are: only the game's own names are looked for in them


def forbidden(files):
    bad = []
    for n in files:
        if n in ALLOWED:
            continue
        parts = n.lower().split("/")
        base = parts[-1]
        modules = any(fnmatch.fnmatch(base, p) for p in ("game_magic.*", "game_deck.*", "game_duel.*", "game_shandalar.*", "game_facemaker.*", "game_sotadeck.*", "game_shell.*", "game_senclib.*"))
        if base in FORBIDDEN_NAMES or modules:
            bad.append(n)
        elif not n.startswith(THIRD_PARTY) and (parts[0] == "sources" or any(fnmatch.fnmatch(base, p) for p in FORBIDDEN_PATTERNS)):
            bad.append(n)
    return bad


def run(cmd, cwd, env=None, timeout=1800, input_text=None):
    r = subprocess.run(cmd, cwd=cwd, env=env, input=input_text, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", timeout=timeout)
    return r.returncode, r.stdout


STEAMDECK_FILES = ["tools/steamdeck/install-gui.sh", "tools/steamdeck/install-run.sh", "tools/steamdeck/add-to-steam.py", "tools/steamdeck/progress.py",
                   "tools/steamdeck/controller_neptune_pentamoor.vdf", "Install Pentamoor.desktop", "Add Pentamoor to Steam.desktop"]


def check_steamdeck(root, py, env):
    """The Steam Deck archive's own files: all there, the programs executable and well formed, the shortcut writer working on a fake Steam folder, the installer's text mode
    reaching its first question. Returns the problems."""
    problems = []
    for name in STEAMDECK_FILES:
        if not os.path.isfile(os.path.join(root, name)):
            problems.append(f"the Steam Deck archive lacks {name}")
    if problems:
        return problems
    for name in ("Install Pentamoor.desktop", "Add Pentamoor to Steam.desktop", "tools/steamdeck/install-gui.sh", "tools/steamdeck/add-to-steam.py"):
        if not os.access(os.path.join(root, name), os.X_OK):
            problems.append(f"{name} is not executable")
    for name in ("Install Pentamoor.desktop", "Add Pentamoor to Steam.desktop"):
        with open(os.path.join(root, name), encoding="utf-8") as f:
            text = f.read()
        if not text.startswith("[Desktop Entry]") or "install-gui.sh" not in text or "Terminal=false" not in text:
            problems.append(f"{name} is not the expected desktop entry")
    with open(os.path.join(root, "tools", "steamdeck", "controller_neptune_pentamoor.vdf"), encoding="utf-8") as f:
        vdf = f.read()
    if vdf.count("{") != vdf.count("}") or '"controller_type"\t\t"controller_neptune"' not in vdf:
        problems.append("the controller layout is not well formed")
    for name in ("install-gui.sh", "install-run.sh"):
        code, out = run(["sh", "-n", os.path.join(root, "tools", "steamdeck", name)], root, env)
        if code != 0:
            problems.append(f"{name} does not parse: {out.strip()}")
    # the shortcut writer, on a Steam folder made here: a user, an empty shortcuts.vdf, no Steam running
    import tempfile
    with tempfile.TemporaryDirectory(prefix="pentamoor-steam-") as home:
        steam = os.path.join(home, ".steam", "steam")
        os.makedirs(os.path.join(steam, "userdata", "4242", "config"))
        e = dict(env, HOME=home)
        e.pop("XDG_DATA_HOME", None)
        a2s = [py, "-I", os.path.join("tools", "steamdeck", "add-to-steam.py"), "--steam-dir", steam]
        code, out = run(a2s + ["--dry-run"], root, e)
        if code != 0 or "dry run" not in out:
            problems.append(f"add-to-steam.py --dry-run failed: {out.strip()}")
        code, out = run(a2s + ["--desktop-entry", "--controller-template"], root, e)
        print(out.strip())
        if code == 3:
            print("(Steam is running on this machine: the shortcut writer's refusal is the right answer, but it cannot be tried here)")
        elif code != 0:
            problems.append(f"add-to-steam.py failed: {out.strip()}")
        else:
            vdf_path = os.path.join(steam, "userdata", "4242", "config", "shortcuts.vdf")
            with open(vdf_path, "rb") as f:
                data = f.read()
            if not data.startswith(b"\x00shortcuts\x00") or not data.endswith(b"\x08\x08\x08\x08") or b"Pentamoor" not in data:
                problems.append("add-to-steam.py wrote a shortcuts.vdf that does not look right")
            for rel in (os.path.join(home, ".local", "share", "applications", "pentamoor.desktop"), os.path.join(steam, "controller_base", "templates", "controller_neptune_pentamoor.vdf")):
                if not os.path.exists(rel):
                    problems.append(f"add-to-steam.py did not make {rel}")
            code, out = run(a2s, root, e)
            if code != 0 or "already in" not in out:
                problems.append(f"add-to-steam.py run twice did not say it was already there: {out.strip()}")
    # the installer's text mode: no display, the first question answered no, nothing else happens
    e = dict(env)
    for k in ("DISPLAY", "WAYLAND_DISPLAY"):
        e.pop(k, None)
    code, out = run(["sh", os.path.join("tools", "steamdeck", "install-gui.sh")], root, e, timeout=60, input_text="n\n")
    if code != 0 or "Continue?" not in out:
        problems.append(f"install-gui.sh did not reach its first question: {out.strip()[-300:]}")
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("archive")
    ap.add_argument("--compiler", help="passed to --self-test (for example zig, to prove the Zig in the archive is the one used)")
    ap.add_argument("--static", action="store_true", help="only look at the files (checksums, nothing made from the game); run nothing")
    ap.add_argument("--keep", help="unpack into this (new, empty) folder and leave it there")
    args = ap.parse_args()
    problems = []
    holder = tempfile.TemporaryDirectory(prefix="pentamoor-check-") if not args.keep else None
    dest = args.keep or holder.name
    os.makedirs(dest, exist_ok=True)
    root = extract(os.path.abspath(args.archive), dest)
    files = all_files(root)
    print(f"{len(files)} files in {os.path.basename(root)}")
    problems += check_sums(root, files)
    bad = forbidden(files)
    problems += [f"game-derived or game file in the archive: {b}" for b in bad]
    problems += [f"in the archive, {m}" for m in check_tree.check_files(root, [f for f in files if not f.startswith(THIRD_PARTY)])]
    print(f"checksums and contents: {'ok' if not problems else 'PROBLEMS'}")
    if args.static:
        if problems:
            print("\nFAILED:\n  " + "\n  ".join(problems))
            sys.exit(1)
        print("archive ok (static)")
        return

    embedded = os.path.join(root, "python", "python.exe")
    py = embedded if os.path.exists(embedded) else sys.executable
    print(f"python: {py}")
    env = dict(os.environ)
    for k in ("PYTHONPATH", "PYTHONHOME"):
        env.pop(k, None)
    if os.name == "nt":                         # nothing of the build machine's: a user's PATH has none of MSYS2's or MinGW's folders
        system = os.environ.get("SystemRoot", r"C:\Windows")
        for k in [k for k in env if k.upper() == "PATH"]:
            del env[k]
        env["PATH"] = os.path.join(system, "System32") + os.pathsep + system
    code, out = run([py, "-I", os.path.join("tools", "install", "install.py"), "--check"], root, env)
    print(out)
    if code != 0:
        problems.append("install.py --check failed")
    probe = ("import sys; sys.path.insert(0, 'tools/pydeps'); import pefile, capstone; "
             "from capstone import Cs, CS_ARCH_X86, CS_MODE_32; "
             "print([i.mnemonic for i in Cs(CS_ARCH_X86, CS_MODE_32).disasm(b'\\x90\\xc3', 0)], pefile.__file__, capstone.__file__)")
    code, out = run([py, "-I", "-c", probe], root, env)
    print(out.strip())
    if code != 0 or "tools" not in out or "pydeps" not in out:
        problems.append("pefile and capstone do not import from the archive's tools/pydeps")
    cmd = [py, "-I", os.path.join("tools", "install", "install.py"), "--self-test", "--yes"]
    if args.compiler:
        cmd += ["--compiler", args.compiler]
    code, out = run(cmd, root, env)
    print(out)
    if code != 0 or "self-test: the stub module built and loaded" not in out:
        problems.append("install.py --self-test failed")
    if os.name != "nt" and os.path.exists(os.path.join(root, "pentamoor")):
        quiet = dict(env)                                    # a display would start the Steam Deck archive's window installer, which is not what is looked at here
        for k in ("DISPLAY", "WAYLAND_DISPLAY", "GAMESCOPE_WAYLAND_DISPLAY"):
            quiet.pop(k, None)
        code, out = run(["sh", "./pentamoor"], root, quiet, timeout=60, input_text="")
        print(out)
        if code != 1 or "pentamoor-install" not in out:
            problems.append("./pentamoor without the game should fail and name pentamoor-install")
    if os.path.isdir(os.path.join(root, "tools", "steamdeck")):
        problems += check_steamdeck(root, py, env)
    if holder:
        try:
            holder.cleanup()
        except OSError:
            pass
    if problems:
        print("\nFAILED:\n  " + "\n  ".join(problems))
        sys.exit(1)
    print("archive ok")


if __name__ == "__main__":
    main()

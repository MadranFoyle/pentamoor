#!/usr/bin/env python3
"""
package.py - lay out a release archive from a built runtime, and pack it.

    python tools/release/package.py --platform linux-x86_64 --version 0.1.0 --runtime src/port/build/pentamoor-run --out dist
    python tools/release/package.py --platform windows-x86_64 --version 0.1.0 --runtime src/port/build/pentamoor-run.exe --lib C:/msys64/mingw64/bin/SDL2.dll \\
        --license sdl2-LICENSE.txt --embed-python --bundle-zig --out dist
    python tools/release/package.py --platform steamdeck --version 0.1.0 --runtime src/port/build/pentamoor-run --fetch-pydeps --out dist     # the Linux x86-64 runtime, for the Steam Deck

The archive pentamoor-<version>-<platform>.zip (Windows) or .tar.gz (platform: windows-x86_64, linux-x86_64, macos-universal, steamdeck) holds one folder, pentamoor-<version>-<platform>/, with:

    pentamoor-run[.exe]            the runtime (no game-derived code in it)
    pentamoor, pentamoor-install   the launchers (Windows: pentamoor.bat, pentamoor-install.bat)
    SDL2.dll, python/              Windows: the SDL2 library and the embeddable Python that runs the installer (--lib, --embed-python)
    tools/steamdeck, Install Pentamoor.desktop, Add Pentamoor to Steam.desktop     the "steamdeck" archive only: the installer with windows, the Steam shortcut, the controller layout
    tools/install, tools/lift      the installer and the lifter (Python; it finds the game's functions in the game's own code), tools/pydeps: pefile and capstone for this platform
    tools/local/ziglang            Windows: the Zig compiler, so the game modules can be built on a machine with none (--bundle-zig)
    src/native, src/port           the headers and the glue files a game module is compiled with, and the stub module of --self-test
    README.txt, NOTICE.txt, LICENSE, VERSION, SHA256SUMS

and never anything made from the game: check_archive.py looks for that. Needs network only for --embed-python, --bundle-zig and --fetch-pydeps.
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "tools", "install"))

import manifest  # noqa: E402
import zigdl  # noqa: E402

PLATFORMS = ("windows-x86_64", "linux-x86_64", "macos-universal", "macos-arm64", "macos-x86_64", "steamdeck")
# the wheel tag pip is told to fetch pefile's and capstone's native part for (capstone is a ctypes wrapper of a C library: one wheel per platform, any Python 3)
PIP_PLATFORM = {
    "windows-x86_64": "win_amd64",
    "linux-x86_64": "manylinux2014_x86_64",
    "macos-universal": "macosx_10_9_universal2",
    "macos-arm64": "macosx_11_0_arm64",
    "macos-x86_64": "macosx_10_9_x86_64",
    "steamdeck": "manylinux2014_x86_64",           # the Linux x86-64 archive plus the Steam Deck's files
}
EMBED_PYTHON = ("https://www.python.org/ftp/python/3.13.9/python-3.13.9-embed-amd64.zip", "91d828c2da3a029b41699e918674a0cb379c02cf20dab9c501306885f837402a")
WINDOWS_ONLY = {"pentamoor.bat", "pentamoor-install.bat"}
UNIX_ONLY = {"pentamoor", "pentamoor-install"}
EXECUTABLE = {"pentamoor", "pentamoor-install", "pentamoor-run"}


def is_windows(platform):
    return platform.startswith("windows")


def archive_name(version, platform):
    return f"pentamoor-{version}-{platform}" + (".zip" if is_windows(platform) else ".tar.gz")


def filter_readme(text, platform):
    """Keep the lines for this platform: '@windows ', '@unix ', '@macos ', '@linux ' prefixes pick them; lines without a prefix stay."""
    tags = {"@windows"} if is_windows(platform) else {"@unix"} | ({"@macos"} if platform.startswith("macos") else {"@steamdeck"} if platform == "steamdeck" else {"@linux"})
    out = []
    for line in text.splitlines():
        if line.startswith("@"):
            tag, _, rest = line.partition(" ")
            if tag in tags:
                out.append(rest)
            elif tag in ("@windows", "@unix", "@macos", "@linux", "@steamdeck"):
                continue
            else:
                out.append(line)
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def copy_file(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)
    shutil.copymode(src, dst)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(url, sha256, dest):
    zigdl.download(url, dest, sha256)
    return dest


def stage_files(stage, platform, version, runtime, libs, licenses, pydeps, fetch_pydeps, embed_python, bundle_zig, say=print):
    """Build the folder `stage` the archive is made from."""
    win = is_windows(platform)
    skip = UNIX_ONLY if win else WINDOWS_ONLY
    missing = manifest.missing(ROOT)
    if missing:
        sys.exit(f"package: files missing from the repository: {', '.join(missing)}")
    for rel in manifest.release_files(ROOT):
        if rel in skip:
            continue
        copy_file(os.path.join(ROOT, rel), os.path.join(stage, rel))
    # the runtime
    if not os.path.isfile(runtime):
        sys.exit(f"package: the runtime {runtime} does not exist (make -C src/port runtime)")
    copy_file(runtime, os.path.join(stage, "pentamoor-run" + (".exe" if win else "")))
    if platform == "steamdeck":              # the installer with windows, the Steam shortcut and layout, and the two icons that start them from the file manager
        for rel in manifest.steamdeck_files(ROOT):
            copy_file(os.path.join(ROOT, rel), os.path.join(stage, rel))
        for name in manifest.STEAMDECK_DESKTOP:
            copy_file(os.path.join(ROOT, "tools", "steamdeck", "desktop", name), os.path.join(stage, name))
    for lib in libs:
        copy_file(lib, os.path.join(stage, os.path.basename(lib)))
    for lic in licenses:
        copy_file(lic, os.path.join(stage, "licenses", os.path.basename(lic)))
    # pefile and capstone for this platform (the lifter's imports): copied from a folder, or fetched with pip (--target, --platform: no other package, any Python 3)
    if pydeps:
        shutil.copytree(pydeps, os.path.join(stage, "tools", "pydeps"), ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "bin"))
    elif fetch_pydeps:
        target = os.path.join(stage, "tools", "pydeps")
        say(f"pip install pefile capstone for {PIP_PLATFORM[platform]}")
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "--only-binary=:all:", "--no-compile", "--platform", PIP_PLATFORM[platform],
                        "--target", target, "pefile", "capstone"], check=True)
        for dirpath, dirnames, _ in os.walk(target):
            for d in list(dirnames):
                if d == "__pycache__" or d == "bin":
                    shutil.rmtree(os.path.join(dirpath, d))
                    dirnames.remove(d)
    if embed_python:
        if not win:
            sys.exit("package: --embed-python is for the Windows archive")
        with tempfile.TemporaryDirectory() as d:
            say(f"downloading {EMBED_PYTHON[0]}")
            z = download(EMBED_PYTHON[0], EMBED_PYTHON[1], os.path.join(d, "python.zip"))
            with zipfile.ZipFile(z) as zf:
                zf.extractall(os.path.join(stage, "python"))
    if bundle_zig:
        zigdl.fetch(os.path.join(stage, "tools", "local"), say, system="windows" if win else None, machine="amd64" if win else None)
    # the texts
    with open(os.path.join(HERE, "README.release.txt")) as f:
        readme = filter_readme(f.read(), platform).replace("{version}", version).replace("{platform}", platform)
    write_text(os.path.join(stage, "README.txt"), readme, win)
    with open(os.path.join(HERE, "NOTICE.txt")) as f:
        write_text(os.path.join(stage, "NOTICE.txt"), f.read(), win)
    with open(os.path.join(HERE, "..", "..", "LICENSE")) as f:
        write_text(os.path.join(stage, "LICENSE"), f.read(), win)
    write_text(os.path.join(stage, "VERSION"), version + "\n", win)
    if win:
        for name in ("pentamoor.bat", "pentamoor-install.bat"):             # cmd.exe mis-reads labels in a file with LF-only lines
            p = os.path.join(stage, name)
            with open(p, "rb") as f:
                data = f.read().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            with open(p, "wb") as f:
                f.write(data)
    # SHA256SUMS of every file (not of itself)
    lines = []
    for dirpath, dirnames, filenames in os.walk(stage):
        dirnames.sort()
        for f in sorted(filenames):
            p = os.path.join(dirpath, f)
            lines.append(f"{sha256_file(p)}  {os.path.relpath(p, stage).replace(os.sep, '/')}")
    lines.sort(key=lambda l: l.split("  ", 1)[1])
    write_text(os.path.join(stage, "SHA256SUMS"), "\n".join(lines) + "\n", False)


def write_text(path, text, crlf):
    with open(path, "wb") as f:
        f.write((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))


def pack(stage, top, out_path, win):
    """The archive: the folder `top` holding the staged files, in a fixed order, with the programs executable. Returns out_path."""
    names = []
    for dirpath, dirnames, filenames in os.walk(stage):
        dirnames.sort()
        for f in sorted(filenames):
            names.append(os.path.relpath(os.path.join(dirpath, f), stage).replace(os.sep, "/"))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    if win:
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for n in names:
                info = zipfile.ZipInfo(f"{top}/{n}", date_time=(2000, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o755 << 16 if n.endswith((".exe", ".bat", ".dll", ".pyd")) else 0o644 << 16
                with open(os.path.join(stage, n), "rb") as f:
                    z.writestr(info, f.read())
    else:
        with tarfile.open(out_path, "w:gz", compresslevel=9) as t:
            for n in names:
                full = os.path.join(stage, n)
                info = t.gettarinfo(full, arcname=f"{top}/{n}")
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                info.mtime = 946684800
                executable = n in EXECUTABLE or os.access(full, os.X_OK)
                info.mode = 0o755 if executable else 0o644
                with open(full, "rb") as f:
                    t.addfile(info, f)
    return out_path


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--platform", required=True, choices=PLATFORMS)
    ap.add_argument("--version", required=True, help="for example 0.1.0 (the tag without its v)")
    ap.add_argument("--runtime", required=True, help="the built pentamoor-run (or pentamoor-run.exe)")
    ap.add_argument("--lib", action="append", default=[], help="a library to put beside the runtime (SDL2.dll on Windows); repeatable")
    ap.add_argument("--license", action="append", default=[], help="a licence text to put in licenses/; repeatable")
    ap.add_argument("--pydeps", help="a folder holding pefile and capstone for this platform (else --fetch-pydeps)")
    ap.add_argument("--fetch-pydeps", action="store_true", help="pip-install pefile and capstone for the platform into the archive's tools/pydeps")
    ap.add_argument("--embed-python", action="store_true", help="Windows: download the embeddable Python (checked against a checksum) into python/")
    ap.add_argument("--bundle-zig", action="store_true", help="Windows: put the Zig compiler into tools/local/ziglang (about 400 MB unpacked, 100 MB packed)")
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    args = ap.parse_args()
    top = f"pentamoor-{args.version}-{args.platform}"
    with tempfile.TemporaryDirectory(prefix="pentamoor-stage-") as tmp:
        stage = os.path.join(tmp, top)
        os.makedirs(stage)
        stage_files(stage, args.platform, args.version, args.runtime, args.lib, args.license, args.pydeps, args.fetch_pydeps, args.embed_python, args.bundle_zig)
        out = pack(stage, top, os.path.join(args.out, archive_name(args.version, args.platform)), is_windows(args.platform))
    print(f"{out}  {os.path.getsize(out) // 1024} KB  sha256 {sha256_file(out)}")


if __name__ == "__main__":
    main()

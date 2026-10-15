"""
zigdl.py - fetch the Zig compiler (`zig cc`, a C compiler that is one self-contained download) into a local folder, for machines that have no C compiler.

Zig is taken from the `ziglang` package on PyPI (PyPI's own wheel files, one per system), straight from files.pythonhosted.org with urllib: no pip is needed, so it works from a
Python that has none (the embeddable Python in the Windows release). Each wheel is checked against a SHA-256 written down here before anything in it is used. A wheel is a zip
file; its `ziglang/` folder (the `zig` program and its bundled C library headers) is unpacked into <tools folder>/ziglang.

Nothing of the game is involved. The pin is Zig 0.16.0 (0.17.0 was out less than two weeks when this was written and had no Windows wheel).
"""
import hashlib
import os
import platform
import stat
import sys
import urllib.request
import zipfile

ZIG_VERSION = "0.16.0"
_BASE = "https://files.pythonhosted.org/packages/"
# (system, machine) -> (path under files.pythonhosted.org/packages/, size in bytes, sha256). Machine names as platform.machine() says them, lower-cased.
WHEELS = {
    ("darwin", "arm64"): ("cd/59/012f0c2800f7428b87bb16c5c78db7ef806efed274491998155955c02558/ziglang-0.16.0-py3-none-macosx_12_0_arm64.whl",
                          97252633, "b61e5413c49508d9d62e5dcea543e3af491594154d74a00ff52f84ed508260cc"),
    ("darwin", "x86_64"): ("75/60/f924aa24b95a1ad347e845acc7ab6b5d062ae5b0b540d494654cd40d4e0b/ziglang-0.16.0-py3-none-macosx_12_0_x86_64.whl",
                           101228024, "18e14f6b25678d7b7c65708c82501ee6090fe39ed5c783477d56267af1fa5629"),
    ("linux", "x86_64"): ("3e/ed/7b79023aa27ceb5d461ecf761181e7c33c57bbc1a6256a39535d1c7083d2/"
                          "ziglang-0.16.0-py3-none-manylinux_2_12_x86_64.manylinux2010_x86_64.musllinux_1_1_x86_64.whl",
                          97941847, "9fcda73f62b851dd72a54b710ad40a209896db14cfb13649e62191243556342b"),
    ("linux", "aarch64"): ("7e/ed/d6663a5e52c504944d578b9e0bfcb7857f292803bcd09ebe0d10fe2b293d/"
                           "ziglang-0.16.0-py3-none-manylinux_2_17_aarch64.manylinux2014_aarch64.musllinux_1_1_aarch64.whl",
                           95008112, "e27d409812b11e0fb89ed0200cf2e55b6464d43f9461553104e4a4f9a94a1fd5"),
    ("windows", "amd64"): ("a6/3c/baff40b3fc8ab4e83530246a52e8f3a5186c3606562712dfb58483b04f79/ziglang-0.16.0-py3-none-win_amd64.whl",
                           98676957, "089a16a4eb5a2f45151993342f8fabad24ff1a0723dc146642895c29208a3939"),
    ("windows", "arm64"): ("f0/0b/bff28a4acc437cb7da705bffafd81fafbbd37a23144363cecc72becaef93/ziglang-0.16.0-py3-none-win_arm64.whl",
                           94347646, "e44a5271f7b72f7980017bb615823ed52e765f96b6482d93a2fd338cd53101bf"),
}


class ZigError(Exception):
    pass


def host_key(system=None, machine=None):
    """(system, machine) as WHEELS names them."""
    system = (system or platform.system()).lower()
    machine = (machine or platform.machine()).lower()
    machine = {"x64": "amd64", "x86-64": "amd64", "arm64e": "arm64"}.get(machine, machine)
    if system == "windows" and machine == "x86_64":
        machine = "amd64"
    if system != "windows" and machine == "amd64":
        machine = "x86_64"
    if system != "windows" and system != "darwin" and machine == "arm64":
        machine = "aarch64"
    return system, machine


def wheel_for(system=None, machine=None):
    """(url, size, sha256) of the wheel for this machine, or ZigError if there is none."""
    key = host_key(system, machine)
    if key not in WHEELS:
        raise ZigError(f"no Zig download is known for {key[0]} on {key[1]}; install gcc or clang instead")
    path, size, digest = WHEELS[key]
    return _BASE + path, size, digest


def zig_binary(tools_dir):
    """The zig program under <tools_dir>/ziglang, or None."""
    for exe in (("zig.exe", "zig") if os.name == "nt" else ("zig", "zig.exe")):         # the other name: a Windows archive being packed on another system
        path = os.path.join(tools_dir, "ziglang", exe)
        if os.path.isfile(path):
            return path
    return None


def download(url, dest, sha256, progress=None, chunk=1 << 20):
    """Fetch url into dest (a file:// URL works too) and check its SHA-256; the file is removed again if it does not match."""
    h = hashlib.sha256()
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                block = r.read(chunk)
                if not block:
                    break
                f.write(block)
                h.update(block)
                got += len(block)
                if progress:
                    progress(got, total)
    except OSError as e:                            # URLError, timeouts, a refused connection
        raise ZigError(f"could not download {url}: {e}") from e
    if h.hexdigest() != sha256:
        os.remove(dest)
        raise ZigError(f"the download from {url} does not match the checksum written down in zigdl.py (got {h.hexdigest()}); it was removed")
    return dest


def unpack(wheel, tools_dir):
    """Extract the ziglang/ folder of the wheel into tools_dir. Refuses a member that would land outside it."""
    base = os.path.realpath(tools_dir)
    with zipfile.ZipFile(wheel) as z:
        for info in z.infolist():
            if not info.filename.startswith("ziglang/"):
                continue
            target = os.path.realpath(os.path.join(base, info.filename))
            if target != base and not target.startswith(base + os.sep):
                raise ZigError(f"{wheel}: {info.filename} points outside the folder")
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(info) as src, open(target, "wb") as dst:
                while True:
                    block = src.read(1 << 20)
                    if not block:
                        break
                    dst.write(block)
            mode = (info.external_attr >> 16) & 0o777
            if mode & 0o111 and os.name != "nt":
                os.chmod(target, mode | stat.S_IRUSR | stat.S_IXUSR)
    exe = zig_binary(tools_dir)
    if exe is None:
        raise ZigError(f"{wheel} has no ziglang/zig program in it")
    if os.name != "nt":
        os.chmod(exe, os.stat(exe).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return exe


def fetch(tools_dir, say=print, system=None, machine=None, url=None, sha256=None):
    """Make <tools_dir>/ziglang if it is not there; returns the path of the zig program. `url` and `sha256` replace the PyPI wheel (tests)."""
    exe = zig_binary(tools_dir)
    if exe:
        return exe
    real_url, size, digest = wheel_for(system, machine)
    url = url or real_url
    digest = sha256 or digest
    wheel = os.path.join(tools_dir, "downloads", url.rsplit("/", 1)[-1])
    say(f"downloading Zig {ZIG_VERSION} ({size // (1 << 20)} MB) from PyPI: {url}")
    last = [-10]

    def progress(got, total):
        pct = got * 100 // total if total else 0
        if pct >= last[0] + 10:
            last[0] = pct
            say(f"  {pct}%")
    download(url, wheel, digest, progress)
    say("unpacking Zig")
    exe = unpack(wheel, tools_dir)
    os.remove(wheel)
    return exe


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else "tools/local"
    print(fetch(folder))

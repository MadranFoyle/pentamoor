#!/usr/bin/env python3
"""
Does the native program draw what the emulator draws? Runs both on the same game files and the same save folder and compares the screen.

    python3 src/port/compare_screen.py [SECONDS]        (needs the game in sources/installed, and the runtime and the game module built: make -C src/port all)

The emulator runs `winemu.run` for SECONDS virtual seconds (default 14) and the native program writes its screen after 8 real seconds; both
use a copy of sources/emu_overlay for what the game saves, so the menu is in the same state. Prints how many pixels differ.
"""
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    seconds = sys.argv[1] if len(sys.argv) > 1 else "14"
    exe = os.path.join(ROOT, "sources", "installed", "Magic", "Program", "MAGIC.EXE")
    build = os.path.join(ROOT, "src", "port", "build")
    port = os.path.join(build, "pentamoor-run" + (".exe" if sys.platform == "win32" else ""))
    ext = {"darwin": "dylib", "win32": "dll"}.get(sys.platform, "so")
    module = os.path.join(build, "game_magic." + ext)
    if not (os.path.exists(exe) and os.path.exists(port) and os.path.exists(module)):
        sys.exit("needs the installed game, src/port/build/pentamoor-run and src/port/build/game_magic." + ext + " (make -C src/port all)")
    work = tempfile.mkdtemp()
    for name in ("emu", "port"):
        shutil.copytree(os.path.join(ROOT, "sources", "emu_overlay"), os.path.join(work, name))
    subprocess.run([sys.executable, "-m", "winemu.run", "--accel", "--host-sound", "--seconds", seconds, "--shots", os.path.join(work, "shots")],
                   cwd=os.path.join(ROOT, "tools", "emu_spike"), env=dict(os.environ, EMU_OVERLAY=os.path.join(work, "emu")),
                   stdout=subprocess.DEVNULL, check=True)
    ppm = os.path.join(work, "native.ppm")
    proc = subprocess.Popen([port, "-m", module, exe], cwd=ROOT, env=dict(os.environ, PORT_OVERLAY=os.path.join(work, "port"), PORT_HEADLESS="1", PORT_SHOT=ppm, PORT_SHOT_AT="8",
                                                           PORT_STUB="1", PORT_RES="640x480"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        proc.wait(timeout=12)
    except subprocess.TimeoutExpired:
        proc.kill()
    a = np.asarray(Image.open(os.path.join(work, "shots", "screen.png")).convert("RGB")).astype(int)
    b = np.asarray(Image.open(ppm).convert("RGB")).astype(int)
    diff = np.abs(a - b).sum(2)
    print(f"{int((diff > 0).sum())} of {diff.size} pixels differ")
    shutil.rmtree(work)


if __name__ == "__main__":
    main()

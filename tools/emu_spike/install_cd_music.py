#!/usr/bin/env python3
"""
Copy the music from the game's CD into the emulator's overlay, where the emulated game finds it.

The game plays its music (`sound\\locmus0..19.wav`, the duel tunes, the castle themes) from the CD-ROM, which the retail install does not
copy. Give this the CD as a mounted folder or as the disc image, and it copies the CD's `Sound` folder to `sources/emu_overlay/Program/Sound`
(the folder is git-ignored; the installed copy is not touched):

    python3 install_cd_music.py                       # the .iso in sources/Magic_The_Gathering_ISO (macOS: mounted with hdiutil, read only)
    python3 install_cd_music.py /Volumes/MTG          # a mounted CD, or any folder that has a Sound folder
    python3 install_cd_music.py "MTG v1.0.iso"

The native program (src/port) finds the music the same way, in its overlay folder (`port_overlay` in the folder it is run from, or PORT_OVERLAY):

    python3 tools/emu_spike/install_cd_music.py --native            # to port_overlay/Program/Sound
    python3 tools/emu_spike/install_cd_music.py --to some/dir       # anywhere else (the folder that holds Program/Sound's contents)
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DEST = os.path.join(ROOT, "sources", "emu_overlay", "Program", "Sound")


def sound_dir(folder):
    for name in os.listdir(folder):
        if name.lower() == "sound" and os.path.isdir(os.path.join(folder, name)):
            return os.path.join(folder, name)
    return None


def native_dest():
    """port_overlay/Program/Sound, reusing the spelling of folders the program has made there (it writes PROGRAM, the game says Program)."""
    path = os.path.join(ROOT, "port_overlay")
    for part in ("Program", "Sound"):
        os.makedirs(path, exist_ok=True)
        same = [n for n in os.listdir(path) if n.lower() == part.lower()]
        path = os.path.join(path, same[0] if same else part)
    os.makedirs(path, exist_ok=True)
    return path


def copy_from(folder):
    src = sound_dir(folder)
    if src is None:
        sys.exit(f"{folder} has no Sound folder")
    os.makedirs(DEST, exist_ok=True)
    n = 0
    for f in sorted(os.listdir(src)):
        if f.lower().endswith(".wav"):
            shutil.copy2(os.path.join(src, f), os.path.join(DEST, f))
            n += 1
    print(f"copied {n} files to {DEST}")


def main():
    global DEST
    args = sys.argv[1:]
    if "--native" in args:
        args.remove("--native")
        DEST = native_dest()
    if "--to" in args:
        i = args.index("--to")
        DEST = os.path.abspath(args[i + 1])
        del args[i:i + 2]
    arg = args[0] if args else None
    if arg is None:
        found = glob.glob(os.path.join(ROOT, "sources", "Magic_The_Gathering_ISO", "*.iso"))
        if not found:
            sys.exit("no disc image in sources/Magic_The_Gathering_ISO: give the CD folder or the .iso as an argument")
        arg = found[0]
    if os.path.isdir(arg):
        copy_from(arg)
        return
    if sys.platform != "darwin":
        sys.exit("mount the image yourself (mount -o loop on Linux) and give the mounted folder")
    mount = tempfile.mkdtemp(prefix="mtgcd")
    subprocess.run(["hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", mount, arg], check=True, capture_output=True)
    try:
        copy_from(mount)
    finally:
        subprocess.run(["hdiutil", "detach", mount], capture_output=True)
        os.rmdir(mount)


if __name__ == "__main__":
    main()

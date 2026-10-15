#!/usr/bin/env python3
"""
add-to-steam.py - put Pentamoor in Steam as a non-Steam game, so it shows in the Library and in the Steam Deck's Game mode.

    python3 tools/steamdeck/add-to-steam.py                  # add the shortcut (Steam must not be running)
    python3 tools/steamdeck/add-to-steam.py --desktop-entry   # also: a Pentamoor entry in the application menu (Steam's "Add a Non-Steam Game" list shows it too)
    python3 tools/steamdeck/add-to-steam.py --controller-template   # also: copy the Steam Input layout into Steam's templates folder
    python3 tools/steamdeck/add-to-steam.py --remove          # take the shortcut out again
    python3 tools/steamdeck/add-to-steam.py --check-steam     # only say whether Steam is running (exit status 3 if it is)

What it does: Steam keeps the non-Steam games of each user in <steam>/userdata/<user id>/config/shortcuts.vdf, a binary file in Valve's "binary VDF" format
(a list of typed key/value pairs: 0x00 starts a nested list, 0x01 is a string, 0x02 a 32-bit number, 0x08 ends a list). This adds one entry for the `pentamoor`
launcher (Exe, StartDir, an app id Steam is happy with, the tag "Pentamoor") after a copy of the file is kept next to it. Nothing else in Steam is touched.

Steam writes shortcuts.vdf again when it quits, from what it has in memory, so a change made while Steam runs is lost; this refuses to run while Steam is running (--force
writes anyway). Steam has to be started again to see the new game (on a Deck, Game mode starts it: switching to desktop mode and back does it).

If the file is not one this program can read back byte for byte, it is left alone and the manual steps are printed instead (Steam: Games > Add a Non-Steam Game to My Library).
Exit status: 0 done, 1 failed (nothing changed), 2 bad arguments, 3 Steam is running.
"""
import argparse
import datetime
import os
import shutil
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
APP_NAME = "Pentamoor"
TAG = "Pentamoor"
TEMPLATE = "controller_neptune_pentamoor.vdf"

# ---- binary VDF -------------------------------------------------------------------------------------------------------------------------------------------
T_DICT, T_STR, T_INT, T_FLOAT, T_PTR, T_WSTR, T_COLOR, T_UINT64, T_END, T_INT64 = 0, 1, 2, 3, 4, 5, 6, 7, 8, 10
FOUR = (T_INT, T_FLOAT, T_PTR, T_COLOR)          # four bytes
EIGHT = (T_UINT64, T_INT64)                      # eight bytes


class VdfError(Exception):
    pass


def _cstring(data, i):
    j = data.find(b"\x00", i)
    if j < 0:
        raise VdfError("a string is not ended")
    return data[i:j], j + 1


def parse_dict(data, i=0, depth=0):
    """The pairs of one list, from data[i:] up to its 0x08: [(key, type, value)] with a nested list as value for T_DICT. Returns (pairs, index after the 0x08).
    Keys and strings stay bytes, so what is read is written back exactly. Numbers are kept as the raw bytes for the same reason (an int32 is read with int_value)."""
    if depth > 8:
        raise VdfError("lists nested too deep")
    pairs = []
    while True:
        if i >= len(data):
            raise VdfError("the file ends inside a list")
        t = data[i]
        i += 1
        if t == T_END:
            return pairs, i
        key, i = _cstring(data, i)
        if t == T_DICT:
            value, i = parse_dict(data, i, depth + 1)
        elif t == T_STR:
            value, i = _cstring(data, i)
        elif t in FOUR:
            value, i = data[i:i + 4], i + 4
        elif t in EIGHT:
            value, i = data[i:i + 8], i + 8
        elif t == T_WSTR:
            j = i
            while j + 1 < len(data) and data[j:j + 2] != b"\x00\x00":
                j += 2
            if j + 1 >= len(data):
                raise VdfError("a wide string is not ended")
            value, i = data[i:j], j + 2
        else:
            raise VdfError("unknown value type 0x%02x" % t)
        if t in FOUR and len(value) < 4 or t in EIGHT and len(value) < 8:
            raise VdfError("a number is cut short")
        pairs.append((key, t, value))


def parse(data):
    """A whole file: the root list. Anything after its end is an error."""
    pairs, end = parse_dict(data)
    if end != len(data):
        raise VdfError("%d bytes after the end of the file" % (len(data) - end))
    return pairs


def dump_dict(pairs):
    out = bytearray()
    for key, t, value in pairs:
        out.append(t)
        out += key + b"\x00"
        if t == T_DICT:
            out += dump_dict(value)
        elif t == T_STR:
            out += value + b"\x00"
        elif t == T_WSTR:
            out += value + b"\x00\x00"
        else:
            out += value
    out.append(T_END)
    return bytes(out)


def dump(pairs):
    return dump_dict(pairs)


def int_value(raw):
    return struct.unpack("<I", raw)[0]


def int_pair(key, number):
    return (key.encode(), T_INT, struct.pack("<I", number & 0xFFFFFFFF))


def str_pair(key, text):
    return (key.encode(), T_STR, text.encode("utf-8"))


# ---- a shortcut -------------------------------------------------------------------------------------------------------------------------------------------
def quote(path):
    return '"' + path + '"'


def shortcut_appid(exe, name):
    """The app id Steam gives a non-Steam shortcut: the CRC-32 of the quoted Exe and the AppName, with the top bit set (what Steam, and the tools that write this file, compute)."""
    return (zlib.crc32((exe + name).encode("utf-8")) & 0xFFFFFFFF) | 0x80000000


def make_entry(exe_path, start_dir, launch_options="", name=APP_NAME, tag=TAG, icon=""):
    """One shortcut, with the keys in the order Steam writes them. Exe and StartDir are quoted, as Steam does."""
    exe, start = quote(exe_path), quote(start_dir)
    return [
        int_pair("appid", shortcut_appid(exe, name)),
        str_pair("AppName", name),
        str_pair("Exe", exe),
        str_pair("StartDir", start),
        str_pair("icon", icon),
        str_pair("ShortcutPath", ""),
        str_pair("LaunchOptions", launch_options),
        int_pair("IsHidden", 0),
        int_pair("AllowDesktopConfig", 1),
        int_pair("AllowOverlay", 1),
        int_pair("OpenVR", 0),
        int_pair("Devkit", 0),
        str_pair("DevkitGameID", ""),
        int_pair("DevkitOverrideAppID", 0),
        int_pair("LastPlayTime", 0),
        str_pair("FlatpakAppID", ""),
        (b"tags", T_DICT, [(b"0", T_STR, tag.encode("utf-8"))]),
    ]


def _find(pairs, key):
    want = key.lower().encode()
    for k, t, v in pairs:
        if k.lower() == want:
            return v
    return None


def shortcuts_list(root):
    """The list of shortcuts inside the root: the T_DICT named 'shortcuts' (any case)."""
    for k, t, v in root:
        if k.lower() == b"shortcuts" and t == T_DICT:
            return v
    return None


def is_ours(entry, exe_path=None):
    """A shortcut that is Pentamoor's: named so, with a launcher called pentamoor (or this exact Exe)."""
    name = _find(entry, "AppName")
    exe = _find(entry, "Exe")
    if name is None or exe is None:
        return False
    exe_s = exe.decode("utf-8", "replace").strip('"')
    if exe_path is not None and exe_s == exe_path:
        return True
    return name.decode("utf-8", "replace") == APP_NAME and os.path.basename(exe_s) in ("pentamoor", "pentamoor.sh")


def add_shortcut(data, exe_path, start_dir, launch_options=""):
    """The file's bytes with Pentamoor added. data: the existing file's bytes (empty or None for a new file). Returns (new bytes, 'added' or 'present').
    Raises VdfError for a file that cannot be read back byte for byte (it is not rewritten)."""
    if data:
        root = parse(data)
        if dump(root) != data:
            raise VdfError("the file does not read back byte for byte")
        lst = shortcuts_list(root)
        if lst is None:
            root = root + [(b"shortcuts", T_DICT, [])]
            lst = root[-1][2]
    else:
        root = [(b"shortcuts", T_DICT, [])]
        lst = root[0][2]
    for k, t, v in lst:
        if t == T_DICT and is_ours(v, exe_path):
            return data, "present"
    numbers = [int(k) for k, t, v in lst if k.isdigit()]
    key = str(max(numbers) + 1 if numbers else 0).encode()
    lst.append((key, T_DICT, make_entry(exe_path, start_dir, launch_options)))
    return dump(root), "added"


def remove_shortcuts(data, exe_path=None):
    """The file's bytes without Pentamoor's shortcuts, and how many were taken out. The others keep their numbers' order (Steam renumbers on its next write)."""
    root = parse(data)
    if dump(root) != data:
        raise VdfError("the file does not read back byte for byte")
    lst = shortcuts_list(root)
    if lst is None:
        return data, 0
    keep = [(k, t, v) for k, t, v in lst if not (t == T_DICT and is_ours(v, exe_path))]
    n = len(lst) - len(keep)
    lst[:] = keep
    return (dump(root), n) if n else (data, 0)


# ---- finding Steam ----------------------------------------------------------------------------------------------------------------------------------------
def steam_roots(home=None):
    home = home or os.path.expanduser("~")
    cands = [os.path.join(home, ".steam", "steam"), os.path.join(home, ".local", "share", "Steam"),
             os.path.join(home, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam"),
             os.path.join(home, "Library", "Application Support", "Steam")]
    out = []
    for c in cands:
        if os.path.isdir(os.path.join(c, "userdata")) and os.path.realpath(c) not in [os.path.realpath(o) for o in out]:
            out.append(c)
    return out


def user_dirs(steam_root):
    """The signed-in users' folders under userdata (numbers; 0 is the anonymous one), most recently used first (by localconfig.vdf, else the folder)."""
    base = os.path.join(steam_root, "userdata")
    users = []
    for n in os.listdir(base) if os.path.isdir(base) else []:
        p = os.path.join(base, n)
        if n.isdigit() and n != "0" and os.path.isdir(p):
            probe = os.path.join(p, "config", "localconfig.vdf")
            users.append((os.path.getmtime(probe) if os.path.exists(probe) else os.path.getmtime(p), n, p))
    users.sort(reverse=True)
    return [(n, p) for _, n, p in users]


def steam_running(pid_file=None, proc="/proc"):
    """Is Steam running: its pid file names a live process called steam (Linux), or any process called steam is in /proc."""
    pid_file = pid_file or os.path.join(os.path.expanduser("~"), ".steam", "steam.pid")
    try:
        with open(pid_file) as f:
            pid = int(f.read().strip())
        comm = os.path.join(proc, str(pid), "comm")
        if os.path.exists(comm):
            with open(comm) as f:
                if f.read().strip().startswith("steam"):
                    return True
    except (OSError, ValueError):
        pass
    try:
        for n in os.listdir(proc):
            if n.isdigit():
                try:
                    with open(os.path.join(proc, n, "comm")) as f:
                        if f.read().strip() == "steam":
                            return True
                except OSError:
                    continue
    except OSError:
        pass
    return False


# ---- the other two things ---------------------------------------------------------------------------------------------------------------------------------
def desktop_entry_text(exe_path, start_dir):
    def esc(s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$") + '"'
    return ("[Desktop Entry]\nType=Application\nName=Pentamoor\nComment=Magic: The Gathering (Shandalar), a native port\n"
            f"Exec={esc(exe_path)}\nPath={start_dir}\nTerminal=false\nCategories=Game;\nIcon=applications-games\nStartupNotify=false\n")


def write_desktop_entry(exe_path, start_dir, home=None):
    home = home or os.path.expanduser("~")
    apps = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share"), "applications")
    os.makedirs(apps, exist_ok=True)
    path = os.path.join(apps, "pentamoor.desktop")
    with open(path, "w") as f:
        f.write(desktop_entry_text(exe_path, start_dir))
    os.chmod(path, 0o755)
    return path


def install_template(steam_root, source=None):
    source = source or os.path.join(HERE, TEMPLATE)
    dest_dir = os.path.join(steam_root, "controller_base", "templates")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, TEMPLATE)
    shutil.copyfile(source, dest)
    return dest


MANUAL = """To do it by hand instead:
  1. Open Steam (in desktop mode on a Steam Deck).
  2. Games > Add a Non-Steam Game to My Library... (the Pentamoor entry is in the list if you ran this with --desktop-entry; else "Browse...").
  3. Choose  {exe}  and press Add Selected Programs.
  4. Right-click Pentamoor in the Library > Properties: set "Start In" to  {start}
  5. Right-click Pentamoor > Properties > Controller (or the controller button in Game mode): choose the Gamepad layout (docs/notes/steamdeck.md).
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="Add Pentamoor to Steam as a non-Steam game (the top of this file says how).")
    ap.add_argument("--exe", default=os.path.join(ROOT, "pentamoor"), help="the launcher to add (default: pentamoor beside tools/)")
    ap.add_argument("--launch-options", default="", help="Steam's launch options for the shortcut (default: none)")
    ap.add_argument("--steam-dir", help="Steam's folder (default: ~/.steam/steam, ~/.local/share/Steam, the Flatpak's)")
    ap.add_argument("--user", help="the Steam user's number (a folder of userdata); default: the one used last")
    ap.add_argument("--force", action="store_true", help="write even while Steam is running (Steam then undoes it when it quits, unless it is restarted first)")
    ap.add_argument("--dry-run", action="store_true", help="say what would be done, change nothing")
    ap.add_argument("--remove", action="store_true", help="take Pentamoor's shortcut out of Steam instead")
    ap.add_argument("--desktop-entry", action="store_true", help="also write ~/.local/share/applications/pentamoor.desktop (the application menu, and Steam's own Add a Non-Steam Game list)")
    ap.add_argument("--controller-template", action="store_true", help="also copy the Steam Input layout into Steam's controller_base/templates (see docs/notes/steamdeck.md)")
    ap.add_argument("--check-steam", action="store_true", help="only report whether Steam is running; exit status 3 if it is")
    args = ap.parse_args(argv)

    if args.check_steam:
        running = steam_running()
        print("Steam is running" if running else "Steam is not running")
        return 3 if running else 0

    exe = os.path.abspath(args.exe)
    start = os.path.dirname(exe)
    manual = MANUAL.format(exe=exe, start=start)
    if not args.remove and not os.path.exists(exe):
        print(f"add-to-steam: {exe} is not there (run this from an unpacked Pentamoor folder, or give --exe).", file=sys.stderr)
        return 1
    roots = [args.steam_dir] if args.steam_dir else steam_roots()
    if not roots or not os.path.isdir(os.path.join(roots[0], "userdata")):
        print("add-to-steam: Steam's folder was not found (looked for ~/.steam/steam, ~/.local/share/Steam and the Flatpak's). Start Steam once and sign in, or give --steam-dir.", file=sys.stderr)
        print(manual)
        return 1
    steam_root = roots[0]
    users = user_dirs(steam_root)
    if args.user:
        users = [(n, p) for n, p in users if n == args.user]
    if not users:
        print(f"add-to-steam: no signed-in Steam user in {steam_root}/userdata{' (user ' + args.user + ')' if args.user else ''}. Sign in to Steam once.", file=sys.stderr)
        print(manual)
        return 1
    uid, udir = users[0]
    path = os.path.join(udir, "config", "shortcuts.vdf")
    if steam_running() and not args.force and not args.dry_run:
        print("add-to-steam: Steam is running. It writes shortcuts.vdf again when it quits, which would undo this. Close Steam first (Steam menu > Exit), run this again,\n"
              "then start Steam: the game is in the Library. (--force writes anyway; restart Steam before it quits by itself, or it is lost.)", file=sys.stderr)
        return 3
    if len(users) > 1:
        print(f"note: {len(users)} Steam users here; using {uid} (the one used last). --user N picks another.")

    data = b""
    if os.path.exists(path):
        with open(path, "rb") as f:
            data = f.read()
    try:
        if args.remove:
            new, n = remove_shortcuts(data, exe) if data else (data, 0)
            what = f"removed {n} shortcut(s)" if n else "no Pentamoor shortcut was there"
        else:
            new, status = add_shortcut(data, exe, start, args.launch_options)
            what = "Pentamoor is in " + path if status == "added" else "Pentamoor is already in " + path
    except VdfError as e:
        print(f"add-to-steam: {path}: {e}; not touching it.", file=sys.stderr)
        print(manual)
        return 1
    if args.dry_run:
        print(f"dry run: {what} (user {uid}); {len(data)} -> {len(new)} bytes")
    elif new != data:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if data:
            backup = path + ".pentamoor-backup-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(path, backup)
            print(f"kept a copy: {backup}")
        tmp = path + ".pentamoor-tmp"
        with open(tmp, "wb") as f:
            f.write(new)
        if os.path.exists(path):
            shutil.copymode(path, tmp)
        os.replace(tmp, path)
        print(what + f" (Steam user {uid})")
        if not args.remove:
            print("Start Steam again to see it (on a Steam Deck: switch to Gaming Mode). It is in the Library under All Games, tagged Pentamoor.")
    else:
        print(what)
    if args.desktop_entry and not args.remove and not args.dry_run:
        print("menu entry: " + write_desktop_entry(exe, start))
    if args.controller_template and not args.remove and not args.dry_run:
        try:
            print("controller layout: " + install_template(steam_root) + "\n  Steam > Controller settings > Browse Configs > Templates: 'Pentamoor' (docs/notes/steamdeck.md says what is and is not verified)")
        except OSError as e:
            print(f"controller layout: not copied ({e})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

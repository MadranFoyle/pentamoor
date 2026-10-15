"""Guest (Windows) paths to host paths. The guest sees C:\\Magic\\...; the host has the installed game
folder, plus a writable overlay so the emulated game can save without touching the installed copy."""
import os


def normalize(cwd, path):
    """Absolute guest path (backslashes, no trailing dot segments) from a possibly relative one."""
    p = path.replace("/", "\\")
    if len(p) >= 3 and p[1] == ":" and p[2] != "\\":                    # "C:name": relative to the current directory
        p = p[2:]
    if len(p) < 2 or p[1] != ":":
        p = (cwd.rstrip("\\") + "\\" + p) if not p.startswith("\\") else "C:" + p
    drive, rest = p[:2].upper(), p[2:]
    parts = []
    for seg in rest.split("\\"):
        if seg in ("", "."):
            continue
        if seg == "..":
            if parts:
                parts.pop()
            continue
        parts.append(seg)
    return drive + "\\" + "\\".join(parts)


def _find_ci(base, parts):
    """Resolve `parts` under `base`, case-insensitively. Returns (path, exists)."""
    cur = base
    for i, seg in enumerate(parts):
        try:
            names = os.listdir(cur)
        except OSError:
            return os.path.join(cur, *parts[i:]), False
        hit = next((n for n in names if n.lower() == seg.lower()), None)
        if hit is None:
            return os.path.join(cur, *parts[i:]), False
        cur = os.path.join(cur, hit)
    return cur, True


def host_path(game_root, overlay_root, cwd, guest, for_write=False):
    """(host path, exists). Guest C:\\Magic\\X maps to game_root/X. Reads prefer the overlay."""
    g = normalize(cwd, guest)
    parts = [s for s in g[3:].split("\\") if s]
    if parts and parts[0].lower() == "magic":
        parts = parts[1:]
    if for_write:
        p, _ = _find_ci(overlay_root, parts)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p, os.path.exists(p)
    p, ok = _find_ci(overlay_root, parts)
    if ok:
        return p, True
    return _find_ci(game_root, parts)

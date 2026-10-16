"""
manifest.py - which files of the repository a release carries, and which of them the installer cannot do without.

Used by tools/release/package.py (what to copy into the archive) and by `install.py --check` (is everything the lifter and the module build read there). The release is the
runtime, the launchers, and exactly what turns the user's own disc into a game module: the lifter, the installer, and the headers and glue the module is compiled with.
Nothing derived from the game is ever in it.
"""
import fnmatch
import os

# Single files, relative to the repository root (forward slashes).
LAUNCHERS = ["pentamoor", "pentamoor.bat", "pentamoor-install", "pentamoor-install.bat"]

# What the lifter reads besides the game (and its own files in tools/lift: the import signatures, the function scan): the addresses of the natively written functions.
LIFTER_DATA = [
    "src/native/layout.c",
]

# What a game module is compiled from besides the lifter's C (src/port/Makefile, module rules): the interface headers and the two glue files.
MODULE_SOURCES = [
    "src/native/lift_rt.h",
    "src/native/lift_tables.h",
    "src/port/modglue.c",
    "src/port/modules_none.c",
    "src/port/stubgame/handlers_gen.c",       # the hand-written stub module that `install.py --self-test` builds (not generated, not the game's)
]

# Folders copied whole, with the patterns left out (tests, caches, scripts that only the developers run).
TREES = {
    "tools/install": {"exclude": ["test_*.py", "__pycache__", "*.pyc"]},
    "tools/lift": {"exclude": ["test_*.py", "__pycache__", "*.pyc", "README.md", "compare_hosted.py", "coverage.py", "scan_diff.py"]},
}

# The Steam Deck archive (tools/release/package.py --platform steamdeck) carries these besides everything above: the installer with windows, the Steam shortcut writer, the
# controller layout (tools/steamdeck, without its tests and the two .desktop files), and the .desktop files at the top of the folder, where a double click finds them.
STEAMDECK_TREE = "tools/steamdeck"
STEAMDECK_EXCLUDE = ["test_*.py", "__pycache__", "*.pyc", "desktop"]
STEAMDECK_DESKTOP = ["Install Pentamoor.desktop", "Add Pentamoor to Steam.desktop"]

# Present in every release (the installer's --check looks for these).
REQUIRED = (["tools/install/install.py", "tools/install/modbuild.py", "tools/install/liftrun.py", "tools/install/zigdl.py", "tools/install/manifest.py",
             "tools/lift/gen_handlers.py", "tools/lift/gen_dll.py", "tools/lift/x86lift.py", "tools/lift/import_signatures.py", "tools/lift/fnscan.py", "tools/lift/builds.py"]
            + LIFTER_DATA + MODULE_SOURCES)


def excluded(name, patterns):
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def tree_files(root, rel):
    """The files of the folder `rel` (under root) that a release carries, as paths relative to root with forward slashes."""
    out = []
    spec = TREES[rel]
    for dirpath, dirnames, filenames in os.walk(os.path.join(root, rel)):
        dirnames[:] = sorted(d for d in dirnames if not excluded(d, spec["exclude"]))
        for f in sorted(filenames):
            if not excluded(f, spec["exclude"]):
                out.append(os.path.relpath(os.path.join(dirpath, f), root).replace(os.sep, "/"))
    return out


def steamdeck_files(root):
    """The files of tools/steamdeck that the Steam Deck archive carries, relative to the root with forward slashes."""
    TREES[STEAMDECK_TREE] = {"exclude": STEAMDECK_EXCLUDE}
    try:
        return tree_files(root, STEAMDECK_TREE)
    finally:
        del TREES[STEAMDECK_TREE]


def release_files(root):
    """Every file the release copies from the repository, relative to the root, sorted."""
    files = set(LAUNCHERS) | set(LIFTER_DATA) | set(MODULE_SOURCES)
    for rel in TREES:
        files.update(tree_files(root, rel))
    return sorted(files)


def missing(root):
    return [r for r in REQUIRED if not os.path.exists(os.path.join(root, r))]

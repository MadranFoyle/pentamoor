"""
builds.py - the builds of the game Pentamoor knows, and the build id that tells them apart.

A BUILD ID is the SHA-256 of a program's (or library's) file, as 64 lower-case hex digits. The whole file, not its code alone: the lifted C is made from the code, but the port's
hooks also read and write the program's data at fixed addresses, and any byte that differs (another compiler, a patch, a no-CD crack) can move them. It costs one pass over a file
of a megabyte, it needs no PE parsing, and anyone can compute it with `sha256sum`.

The lifter (gen_handlers.py, gen_dll.py) writes the id of the file it lifted into the generated C (`LIFT_BUILD_ID`, and a field of each library's record), the runtime computes the
id of the file it loads and refuses to run the lifted code on another one, and looks the id up in its table of profiles (src/port/profile.c: every address the port hard-codes,
per build). This file is the same list for the Python tools: the installer says which build it found (`install.py --check`). A test (tools/lift/test_lift.py) keeps it equal to
src/port/profile.c's table.

To add a build: add its files here and a row to src/port/profile.c (CONTRIBUTING.md, "Adding a build").
"""
import hashlib

# (build, file, sha256, role)
#   "lifted"  the port runs lifted code made from this file, and has a profile row for it
#   "host"    the port provides this library itself (src/port/sound.c, video.c): the file is never loaded, so there is nothing to check at run time
KNOWN = [
    ("v1.0", "MAGIC.EXE", "4dc592695b6ee390485f283feb2a248cd3f3f739749c2800ab3b1100ea03845c", "lifted"),
    ("v1.0", "DUEL.EXE", "7c4e618b4a8ab4330c71d2dd30637c522573c133d32c667c97924dc8edc2efed", "lifted"),
    ("v1.0", "DECK.EXE", "193f8abea01d4f2c03b769224b06eece6e263a18f13a5b4e2509ed25a01e3d90", "lifted"),
    ("v1.0", "DECKDLL.DLL", "a21f714bea465077c4fabe4a407ff7503b0ce5f9bb1a277826e74276e35c2c18", "lifted"),
    ("v1.0", "STATWIN.DLL", "95bd14de41e8fff84217cdf627a48392da5e7be9c3d064a68e04ed1455334bd7", "lifted"),
    ("v1.0", "MAGSND.DLL", "6f6d51cd2b8a5800b0b3c994e3ee8217f7b40ba2621f9738783387f3250a9882", "host"),
    ("v1.0", "MAGVID.DLL", "d2db1435ae96e9e41d77ded7a7b222969d44d5af642fa9968fe51768c1ce83a3", "host"),
]


def build_id(data):
    """The build id of a file's bytes."""
    return hashlib.sha256(data).hexdigest()


def file_build_id(path):
    """The build id of the file at `path`."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprints(build="v1.0"):
    """{file name: build id} of one build: what the installer checks the extracted game against."""
    return {name: sha for b, name, sha, _ in KNOWN if b == build}


def lifted_ids(build="v1.0"):
    """The ids of the files of a build that the port runs lifted code from (the rows of src/port/profile.c)."""
    return {sha for b, _, sha, kind in KNOWN if b == build and kind == "lifted"}


def name_of(file_name, bid):
    """'v1.0 MAGIC.EXE' for a known file, None for any other bytes (or for a known id under another file name)."""
    for b, name, sha, _ in KNOWN:
        if sha == bid and name.lower() == file_name.lower():
            return f"{b} {name}"
    return None


def describe(file_name, bid):
    """One line for a file: its name, the build it belongs to or 'unknown build', and the start of its id."""
    known = name_of(file_name, bid)
    return f"{file_name}: {known if known else 'unknown build'} (sha256 {bid[:12]})"

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
#   "kept"    a program or library of the install that the port does not run (magic.exe, the Magic Shell; the C runtime's DLL): the installer only checks it is the right file
#   "data"    a data file the patch replaces (CARDS.DAT, the readme, the portrait list): the installer only checks it is the right file
KNOWN = [
    ("v1.0", "MAGIC.EXE", "4dc592695b6ee390485f283feb2a248cd3f3f739749c2800ab3b1100ea03845c", "lifted"),
    ("v1.0", "DUEL.EXE", "7c4e618b4a8ab4330c71d2dd30637c522573c133d32c667c97924dc8edc2efed", "lifted"),
    ("v1.0", "DECK.EXE", "193f8abea01d4f2c03b769224b06eece6e263a18f13a5b4e2509ed25a01e3d90", "lifted"),
    ("v1.0", "DECKDLL.DLL", "a21f714bea465077c4fabe4a407ff7503b0ce5f9bb1a277826e74276e35c2c18", "lifted"),
    ("v1.0", "STATWIN.DLL", "95bd14de41e8fff84217cdf627a48392da5e7be9c3d064a68e04ed1455334bd7", "lifted"),
    ("v1.0", "MAGSND.DLL", "6f6d51cd2b8a5800b0b3c994e3ee8217f7b40ba2621f9738783387f3250a9882", "host"),
    ("v1.0", "MAGVID.DLL", "d2db1435ae96e9e41d77ded7a7b222969d44d5af642fa9968fe51768c1ce83a3", "host"),
    # Spells of the Ancients 2.15: the 2.0 install (the expansion's disc) with the six files of the 2.15 patch over it. A file the patch did not touch is 2.0's, byte for byte, so the
    # build is those files together. magic.exe (the "Magic Shell") and ManaLink 3.0 are not part of it. docs/notes/sota-comparison.md
    ("v2.15", "shandalar.exe", "e4e46718c451974756b66e7666ac0bf1cc9ebdbc5897eb04a87b8ea2a02353e7", "lifted"),
    ("v2.15", "FaceMaker.exe", "b4f3d19614dcd825da846d097baa3cd9badc0c9852492bc27a8ba62c1741a493", "lifted"),
    ("v2.15", "DECK.EXE", "c7ec116aecdcde9ab976cc97cba81482fc4219278f8042edf667456ede3dd8ef", "lifted"),
    ("v2.15", "deckdll.dll", "ce741d1f5547c143fd8494bbe09c26e918b892a3d9fc3c3761babb3c8268a667", "lifted"),
    ("v2.15", "cardartlib.dll", "689be4a86ca843e76057172543cfa3516d8ccbc2efb1699e7c7935b6dc3ead11", "lifted"),
    ("v2.15", "drawcardlib.dll", "c7747313d59b6fa48ec56b479dce9ed5d90f8a95fc47e93990c4369bbd2fa1f8", "lifted"),
    ("v2.15", "CdTools.dll", "0d0c2bfa87de02499f1f73f21f34824b1c2572f3e6ae0b5dca7ca343ddf1b77d", "lifted"),
    ("v2.15", "STATWIN.DLL", "c1ca59496afa786f22fcd97b94052b937910a613f9321399b4ef4dd5dec76940", "lifted"),
    ("v2.15", "MAGSND.DLL", "213b7dc2e1d0eed131d38485cba8004c1d7760f8ff0a94486b86bba5f3aeba9e", "host"),
    ("v2.15", "MAGVID.DLL", "b686bd43bb7f9ba040fc7416d8d74e59e27c3b5b1bbccd76bfc16c5505bcf90a", "host"),
    ("v2.15", "magic.exe", "e948affc1c1fe74c4a9709350d6c184b8cb01548e57a70b5751a479fa3d2bf65", "lifted"),
    ("v2.15", "MSVCRT.DLL", "3a4cb4631f9ecd6f3f6013bc0459fca2e305a0ad00dbf34cb46e6f52d96d9d62", "kept"),
    ("v2.15", "CARDS.DAT", "d7126faf7f17ef84b6ea2e9779bc8b79449c8190c2a4710a5af5c147b95c41a1", "data"),
    ("v2.15", "FaceData.txt", "3b362d357efc0aba6d29e88e4b750078aa11cf5ee838c34c989322266dc4600f", "data"),
    ("v2.15", "Readme.txt", "44e6c8e72a7521759d2a1c7274c6cd4a327a75b8d69db3fdc23f764d26f10b32", "data"),
]

# The size of each 2.15 file (a quick check before the hash, and what the installer says when a file is the wrong one): {sha256: bytes}. A build id is a hash of the whole file, so the
# size follows from it; this is only the second way to say it.
SIZES = {
    "e4e46718c451974756b66e7666ac0bf1cc9ebdbc5897eb04a87b8ea2a02353e7": 1740288,    # shandalar.exe
    "b4f3d19614dcd825da846d097baa3cd9badc0c9852492bc27a8ba62c1741a493": 76288,      # FaceMaker.exe
    "c7ec116aecdcde9ab976cc97cba81482fc4219278f8042edf667456ede3dd8ef": 16424,      # DECK.EXE
    "ce741d1f5547c143fd8494bbe09c26e918b892a3d9fc3c3761babb3c8268a667": 265216,     # deckdll.dll
    "689be4a86ca843e76057172543cfa3516d8ccbc2efb1699e7c7935b6dc3ead11": 139264,     # cardartlib.dll
    "c7747313d59b6fa48ec56b479dce9ed5d90f8a95fc47e93990c4369bbd2fa1f8": 178176,     # drawcardlib.dll
    "0d0c2bfa87de02499f1f73f21f34824b1c2572f3e6ae0b5dca7ca343ddf1b77d": 74752,      # CdTools.dll
    "c1ca59496afa786f22fcd97b94052b937910a613f9321399b4ef4dd5dec76940": 55808,      # STATWIN.DLL
    "213b7dc2e1d0eed131d38485cba8004c1d7760f8ff0a94486b86bba5f3aeba9e": 25088,      # MAGSND.DLL
    "b686bd43bb7f9ba040fc7416d8d74e59e27c3b5b1bbccd76bfc16c5505bcf90a": 45056,      # MAGVID.DLL
    "e948affc1c1fe74c4a9709350d6c184b8cb01548e57a70b5751a479fa3d2bf65": 1530368,    # magic.exe
    "3a4cb4631f9ecd6f3f6013bc0459fca2e305a0ad00dbf34cb46e6f52d96d9d62": 266240,     # MSVCRT.DLL
    "d7126faf7f17ef84b6ea2e9779bc8b79449c8190c2a4710a5af5c147b95c41a1": 339984,     # CARDS.DAT
    "3b362d357efc0aba6d29e88e4b750078aa11cf5ee838c34c989322266dc4600f": 208,        # FaceData.txt
    "44e6c8e72a7521759d2a1c7274c6cd4a327a75b8d69db3fdc23f764d26f10b32": 37224,      # Readme.txt (the patch's)
}

# What the Spells of the Ancients 2.15 installer reads (tools/install/sotainstall.py; docs/notes/sota-comparison.md, "The installer's format" and "Hashes"): facts about the retail files,
# no file is in the repository.
#   the expansion's disc: its DATA.TAG, and the three InstallShield cabinets (size, SHA-256); data1.cab holds the whole Program folder of 2.0
SOTA_DISC = {
    "tag_application": "Spells of the Ancients",
    "tag_version": "2.0",
    "cabinets": {
        "data1.cab": (55460517, "cb021ce69e08b56a0bbb3acfe392f0dad7ded5d22768643a113f3115eaa8732f"),
        "_sys1.cab": (205707, "8dfd7bd0e89fb33e1cfe147462409cf956cbc80b81b4889ad7f680f2584e1cab"),
        "_user1.cab": (2809978, "483e37b99d154024278ef549536629c02598784fe120cc48e356947477608fc0"),
    },
    # the folders the game reads from the CD: (folder on the disc, folder of the install's Program, the kind of file). The disc's Sound (31 WAV) and StatWin (68 AVI) are the first
    # disc's, file for file (the installer adds what is missing and never replaces). The disc's DuelSounds (16 WAV) are not listed: the cabinet carries them and six more (22 WAV), and
    # the installed game plays the cabinet's (the disc's Manaball.wav is another recording of the same size).
    "cd_folders": [("Sound", "Sound", ".wav"), ("StatWin", "Statwin", ".avi")],
}
#   the patch: a WinZip self-extractor (SOTAV215.EXE, "2.15, 19 November 1997"), six whole files that replace the 2.0 install's (a file name is found ignoring case: cards.dat is CARDS.DAT)
SOTA_PATCH = {
    "name": "SOTAV215.EXE",
    "size": 1207571,
    "sha256": "a428e981d1e920c05081a1c57f4eba0b4b75e9cda52f050cad3e33bc456b9c89",
    "files": ["shandalar.exe", "readme.txt", "magic.exe", "FaceData.txt", "deckdll.dll", "cards.dat"],
}

# The one library of the expansion's own cabinet that the original installer ran to write the licence value (docs/notes/sota-licence.md): installed as Program/DuelSounds/Manaball.wav, internal
# name SencLib.dll. Only the installer, after it has verified the owner's discs, lifts it (as a program of its own: the module `senclib`) and runs its export once with the runtime
# (tools/install/licence.py). A fact about the retail file, like the rest of this table: the file is not in the repository, and it is checked by this hash before it is lifted or run.
SOTA_LICENCE_LIBRARY = {
    "module": "senclib",
    "path": "DuelSounds/Manaball.wav",
    "file": "Manaball.wav",
    "program": "MANABALL",          # LIFT_PROGRAM: the lifter names a program after its file
    "sha256": "03d06fc50a0bccb78356071dc8aa1401ba6dc059a113e523c8bb25ed30055264",
    "size": 23040,
    "export": "WriteProgramFlags",
}

# A library is lifted for a base address (the lifted code holds absolute addresses and the loader maps the library there): the same in every program that loads it, and the same as
# `.base` in the build's rows of src/port/profile.c (a test keeps the two equal).
LIBRARY_BASES = {
    "v1.0": {"STATWIN.DLL": 0x30000000, "DECKDLL.DLL": 0x32000000},
    "v2.15": {"STATWIN.DLL": 0x30000000, "deckdll.dll": 0x32000000, "cardartlib.dll": 0x34000000, "drawcardlib.dll": 0x36000000, "CdTools.dll": 0x38000000},
}

# What is lifted from a 2.15 install, as modules (the lifter writes lift_<module>; the runtime loads game_<module>): module -> (the program, the libraries it loads).
#   shandalar  the game: overworld, towns, duels and the deck builder (in this process)
#   facemaker  the portrait editor the game starts when a colour is chosen
#   sotadeck   the stand-alone deck builder (DECK.EXE: a stub that starts the deck builder of deckdll.dll)
#   shell      the Magic Shell (magic.exe, class MAGICGAME_MagicShellClass): the first program a player starts; Gauntlet, Single Duel, Sealed Deck, the hall of records, and its own duels
SOTA_MODULES = {
    "shandalar": ("shandalar.exe", ["STATWIN.DLL", "deckdll.dll", "cardartlib.dll", "drawcardlib.dll", "CdTools.dll"]),
    "facemaker": ("FaceMaker.exe", []),
    "sotadeck": ("DECK.EXE", ["deckdll.dll", "cardartlib.dll", "drawcardlib.dll", "CdTools.dll"]),
    "shell": ("magic.exe", ["deckdll.dll", "cardartlib.dll", "drawcardlib.dll", "CdTools.dll"]),
}


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

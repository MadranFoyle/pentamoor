"""
sotainstall.py - make the Spells of the Ancients 2.15 folder from your own discs and patch, the way the original installers would, without Windows.

What Windows had after the expansion was installed and patched is the first game's folder (Spells of the Ancients still reads its pictures, sprites and sounds) with the expansion's
Program folder over it, and the patch's six files over that. This module makes that folder from:

  * the first game's folder, already installed by install.py (the retail disc, version 1.0);
  * the expansion's disc, "MTG v2.00.iso" (Spells of the Ancients 2.0): its InstallShield cabinet Setup/data1.cab holds the Program folder (335 files); _sys1.cab and _user1.cab hold the
    original installer's own helper files and billboard pictures, which the game does not read: they are checked to inflate and are not installed; the Sound, StatWin and DuelSounds
    folders the game reads from the CD are added where a file is missing or differs;
  * SOTAV215.EXE, the 2.15 patch: six whole files that replace the 2.0 ones (names compared ignoring case, as Windows does: cards.dat is CARDS.DAT).

Then every program, library and data file is checked against tools/lift/builds.py (SHA-256 and size): a folder that is not exactly 2.15 is reported file by file and refused.

Everything is checked BEFORE anything is written: the two discs are what they should be (a first disc that is the expansion's, or an expansion disc that is the first game's, is
named as such), the patch is whole (every CRC-32, its end record) and holds the six known files. Files are written only inside the target folder (overlay.place refuses a path that
leads out of it, and a symbolic link); nothing is written to the registry, which Windows' installers did, and nothing else on the machine changes.

A SotaError carries a message for the person who has the files: what was given, what is wrong with it, and what is needed.
"""
import hashlib
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "lift"))

import builds  # noqa: E402
import iscab  # noqa: E402
import overlay  # noqa: E402
import sotapatch  # noqa: E402

BUILD = "v2.15"
EXPANSION_DISC = "Setup/data1.cab"
FIRST_DISC = "Setup/data.z"
PATCH_HINT = 'pentamoor-install "MTG v1.0.iso" --sota "MTG v2.00.iso" --patch SOTAV215.EXE'


class SotaError(Exception):
    pass


def say_nothing(msg):
    pass


def kib(n):
    return f"{n:,}"


# ---- the sources ------------------------------------------------------------------------------------------------------------------------------------------
def read_tag(disc):
    """The [TagInfo] of an InstallShield disc's Setup/DATA.TAG as a dict ({} when there is none)."""
    entry = disc.find("Setup/DATA.TAG")
    if entry is None or entry.size > 4096:
        return {}
    out = {}
    for line in disc.read(entry).decode("latin-1").splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip().lower()] = v.strip().strip('"')
    return out


def disc_kind(disc):
    """What a disc image is: "first" (the original game, version 1.0: Setup/data.z), "expansion" (Spells of the Ancients: Setup/data1.cab) or None."""
    if disc.find(EXPANSION_DISC) is not None:
        return "expansion"
    if disc.find(FIRST_DISC) is not None:
        return "first"
    return None


def check_first_disc(disc, path):
    """The disc given as the first game's must be that. Raises SotaError, saying what it is instead and how the installer wants the discs."""
    kind = disc_kind(disc)
    if kind == "first":
        return
    if kind == "expansion":
        raise SotaError(f"{path} is the Spells of the Ancients disc (version {read_tag(disc).get('version', '2.0')}), not the original game's. The expansion is installed over the first game, "
                        f"so the installer needs the original game's disc (MTG v1.0, with Setup/data.z) first and this one after --sota, and the 2.15 patch:\n  {PATCH_HINT}")
    raise SotaError(f"{path} does not look like the Magic: The Gathering disc (no Setup/data.z). The installer needs a disc image of the retail CD, version 1.0"
                    + (f" (label {disc.label!r} was found)." if getattr(disc, "label", "") else "."))


def sha256_entry(disc, entry):
    h = hashlib.sha256()
    off = 0
    while off < entry.size:
        block = disc.read(entry, off, min(1 << 20, entry.size - off))
        if not block:
            break
        h.update(block)
        off += len(block)
    return h.hexdigest(), off


def check_expansion_disc(disc, path):
    """The disc given with --sota must be Spells of the Ancients 2.0, with its three cabinets as the retail disc has them. Raises SotaError. Returns the three cabinets' entries."""
    kind = disc_kind(disc)
    if kind == "first":
        raise SotaError(f"{path} is the original game's disc (version 1.0), not the Spells of the Ancients disc. --sota wants the expansion's disc: MTG v2.00, the one with "
                        f"Setup/data1.cab. The original game's disc goes first, then --sota and --patch:\n  {PATCH_HINT}")
    if kind is None:
        raise SotaError(f"{path} is not the Spells of the Ancients disc (it has no Setup/data1.cab). --sota wants a disc image of the expansion's CD, MTG v2.00 (Spells of the Ancients 2.0).")
    tag = read_tag(disc)
    if builds.SOTA_DISC["tag_application"].lower() not in tag.get("application", "").lower():
        raise SotaError(f"{path} has a Setup/data1.cab but its disc tag does not say Spells of the Ancients ({tag.get('application', 'no tag')!r}); --sota wants the expansion's CD, MTG v2.00.")
    if tag.get("version") != builds.SOTA_DISC["tag_version"]:
        raise SotaError(f"{path} is Spells of the Ancients version {tag.get('version', '?')}. Pentamoor builds 2.15 from the 2.0 disc (MTG v2.00) and the 2.15 patch SOTAV215.EXE.")
    cabinets = {}
    for name, (size, sha) in builds.SOTA_DISC["cabinets"].items():
        entry = disc.find("Setup/" + name)
        if entry is None:
            raise SotaError(f"{path} lacks Setup/{name}: the disc image is incomplete.")
        got, n = sha256_entry(disc, entry)
        if n != size or entry.size != size:
            raise SotaError(f"{path}: Setup/{name} is {kib(n)} bytes where the retail disc's is {kib(size)}: the disc image is cut short, damaged or another release.")
        if got != sha:
            raise SotaError(f"{path}: Setup/{name} has SHA-256 {got[:16]}... where the retail disc's has {sha[:16]}...: the disc image is damaged or another release "
                            "(the 2.15 files it should make are checked by their hashes, so only the retail 2.0 disc will do).")
        cabinets[name] = entry
    return cabinets


def check_patch(path):
    """Read SOTAV215.EXE completely and check it holds the six files of the 2.15 patch. Returns [(name, bytes)]; raises SotaError saying what is wrong with the file."""
    spec = builds.SOTA_PATCH
    try:
        entries = sotapatch.load(path)
    except sotapatch.PatchError as e:
        text = str(e)
        size = os.path.getsize(path) if os.path.exists(path) else 0
        hint = ""
        if size and size < spec["size"]:
            hint = f" The whole {spec['name']} is {kib(spec['size'])} bytes; this file is {kib(size)}: it was cut short (an incomplete download or copy). Get the patch again."
        elif "no files" in text:
            hint = f" --patch wants {spec['name']}, the Spells of the Ancients 2.15 patch (Magic: The Gathering, 19 November 1997)."
        raise SotaError(text + ("." if not text.endswith(".") else "") + hint)
    want = {n.lower(): n for n in spec["files"]}
    known = {name.lower(): sha for build, name, sha, _role in builds.KNOWN if build == BUILD}
    got = {}
    for name, data in entries:
        got[os.path.basename(name.replace("\\", "/")).lower()] = (name, data)
    missing = sorted(want[k] for k in want if k not in got)
    extra = sorted(got[k][0] for k in got if k not in want)
    if missing or extra:
        raise SotaError(f"{path} is not the 2.15 patch: it holds {', '.join(n for n, _ in entries)}"
                        + (f"; it lacks {', '.join(missing)}" if missing else "") + f". {spec['name']} holds six files: {', '.join(spec['files'])}.")
    for k, (name, data) in got.items():
        if builds.build_id(data) != known[k]:
            raise SotaError(f"{path}: its {name} is not the one of Spells of the Ancients 2.15 (SHA-256 {builds.build_id(data)[:16]}..., wanted {known[k][:16]}...): another version of the patch.")
    return [(want[k], got[k][1]) for k in want]


# ---- the folder -------------------------------------------------------------------------------------------------------------------------------------------
def program_dir(magic):
    """The Program folder of an install folder `magic`, in the spelling it has there (the first game's disc writes Program)."""
    for n in os.listdir(magic) if os.path.isdir(magic) else ():
        if n.lower() == "program":
            return os.path.join(magic, n)
    return os.path.join(magic, "Program")


def verify(program):
    """[(file name, problem or None)] for every file of the 2.15 build in a Program folder, by size and SHA-256 (tools/lift/builds.py)."""
    out = []
    for _b, name, sha, _role in [r for r in builds.KNOWN if r[0] == BUILD]:
        path = None
        for n in os.listdir(program) if os.path.isdir(program) else ():
            if n.lower() == name.lower():
                path = os.path.join(program, n)
                break
        if path is None:
            out.append((name, "is missing"))
            continue
        size = os.path.getsize(path)
        want = builds.SIZES.get(sha)
        if want is not None and size != want:
            out.append((name, f"is {kib(size)} bytes where 2.15's is {kib(want)}"))
        elif builds.file_build_id(path) != sha:
            out.append((name, f"is not the 2.15 file (SHA-256 {builds.file_build_id(path)[:16]}... where 2.15's starts {sha[:16]})"))
        else:
            out.append((name, None))
    return out


def problems(program):
    return [f"{n} {why}" for n, why in verify(program) if why]


def copy_first_game(src_magic, dst_magic, force, say):
    """The first game's folder (everything but nothing: the pictures, sprites and sounds Spells of the Ancients reads from it) copied to the new folder. Files already there with
    the right size are left alone."""
    made = skipped = nbytes = 0
    t0 = time.time()
    total = sum(len(f) for _d, _s, f in os.walk(src_magic))
    for d, dirs, files in os.walk(src_magic):
        dirs.sort()
        for f in sorted(files):
            src = os.path.join(d, f)
            rel = os.path.relpath(src, src_magic)
            if os.path.islink(src):
                continue
            dst = os.path.join(dst_magic, rel)
            if not force and os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src):
                skipped += 1
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
            nbytes += os.path.getsize(dst)
            made += 1
            if (made + skipped) % 300 == 0:
                say(f"  {made + skipped}/{total} files")
    say(f"first game's files: {made} copied ({nbytes // (1 << 20)} MB), {skipped} already there ({time.time() - t0:.0f} s)")
    return made


def count_results(results):
    out = {"added": 0, "replaced": 0, "identical": 0}
    for r in results:
        out[r] += 1
    return out


def extract_cabinet(disc, entry, magic, say, label):
    """Every file of the cabinet into the install folder `magic`: `Program\\x` is Program/x and a file with no folder is at the top, as the original installer put them. Returns the counts."""
    t0 = time.time()
    with iscab.open_in_disc(disc, entry) as f:
        cab = iscab.Cab(f)
        results = []
        for i, e in enumerate(cab.files, 1):
            try:
                results.append(overlay.place(magic, e[0], cab.read(e)))
            except (iscab.CabError, overlay.OverlayError) as err:
                raise SotaError(f"{label}: {err}")
            if i % 100 == 0:
                say(f"  {i}/{len(cab.files)} files")
    c = count_results(results)
    say(f"{label}: {len(results)} files ({c['added']} added, {c['replaced']} replaced, {c['identical']} the same as the first game's or already there) ({time.time() - t0:.0f} s)")
    return c


def check_setup_cabinet(disc, entry, label, say):
    """_sys1.cab and _user1.cab hold the original installer's own files (helper DLLs, billboard pictures): read to the end to see the cabinet is whole, not installed."""
    with iscab.open_in_disc(disc, entry) as f:
        cab = iscab.Cab(f)
        n = 0
        for e in cab.files:
            try:
                n += len(cab.read(e))
            except iscab.CabError as err:
                raise SotaError(f"{label}: {err}")
    say(f"{label}: {len(cab.files)} files ({n // 1024} KB) read and checked, not installed (they are the original installer's own files)")


def add_cd_files(disc, program, say):
    """The files the game reads from the CD (Sound, StatWin), taken from the expansion's disc where the folder lacks one; a file that is there is left alone. The first game's copy is
    the same file for file, so on a normal install this adds nothing."""
    for src, host, ext in builds.SOTA_DISC["cd_folders"]:
        entries = [e for e in disc.listdir(src) if not e.is_dir and e.name.lower().endswith(ext)]
        added = 0
        for e in entries:
            if not os.path.exists(overlay.resolve(program, f"{host}/{e.name}")):
                overlay.place(program, f"{host}/{e.name}", disc.read(e))
                added += 1
        say(f"{src.lower()} from the disc: {len(entries)} files ({added} added, the rest already there)")


def apply_patch(patch, program, say):
    results = [overlay.place(program, name, data) for name, data in patch]
    c = count_results(results)
    say(f"2.15 patch: {len(patch)} files ({c['replaced']} replaced, {c['added']} added, {c['identical']} the same)")


def make_folder(sota_dest, first_magic, disc, patch, force=False, say=say_nothing):
    """Make <sota_dest>/Magic from the first game's folder `first_magic` (<dest>/Magic of install.py), the expansion's `disc` (checked by check_expansion_disc) and the patch entries
    (from check_patch). Returns the new Program folder. Raises SotaError, naming the files, if what comes out is not exactly 2.15."""
    magic = os.path.join(sota_dest, "Magic")
    if os.path.islink(magic) or os.path.islink(sota_dest):
        raise SotaError(f"{sota_dest} (or its Magic folder) is a symbolic link; not writing through it. Give --sota-dest an ordinary folder.")
    os.makedirs(magic, exist_ok=True)
    copy_first_game(first_magic, magic, force, say)
    cabinets = {n: disc.find("Setup/" + n) for n in builds.SOTA_DISC["cabinets"]}
    say(f"reading Setup/data1.cab ({cabinets['data1.cab'].size // (1 << 20)} MB)")
    extract_cabinet(disc, cabinets["data1.cab"], magic, say, "Setup/data1.cab")
    for name in ("_sys1.cab", "_user1.cab"):
        check_setup_cabinet(disc, cabinets[name], "Setup/" + name, say)
    program = program_dir(magic)
    add_cd_files(disc, program, say)
    apply_patch(patch, program, say)
    bad = problems(program)
    if bad:
        raise SotaError("what came out is not Spells of the Ancients 2.15: " + "; ".join(bad) + ". Nothing is built from it.")
    say(f"programs: all {len(verify(program))} files are the 2.15 ones (size and SHA-256)")
    return program

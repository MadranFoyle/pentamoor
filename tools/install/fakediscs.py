"""
fakediscs.py - made-up discs, cabinets and patches for the installer's tests (not shipped in a release; no game file is used or needed).

  make_cab(version, files, chunked)   an InstallShield 5 cabinet in either layout of compressed data (what tools/install/iscab.py reads); names may use either slash
  make_patch(files)                   a WinZip-self-extractor-shaped file: a stub with false ZIP signatures, then a ZIP (what tools/install/sotapatch.py reads)
  make_iso_tree(path, files)          an ISO 9660 image with folders: {"Setup/data1.cab": bytes, ...} (names are upper-cased on the disc; the reader ignores case)
  World                               the whole story in miniature: a first game's disc and install, an expansion disc with a cabinet, a patch, and the table of known files
                                      (tools/lift/builds.py) re-pointed at them, so tools/install/install.py and sotainstall.py can be run end to end
"""
import hashlib
import io
import ntpath
import os
import struct
import zipfile
import zlib

STUB = b"MZ" + b"\0" * 60 + b"PK\x03\x04" + b"\xff" * 40 + b"PK\x03\x04\x14\0\0\0\x08\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\0\x03\0\0\0abc" + b"\0" * 100   # false signatures: junk fields, a name


def sha(data):
    return hashlib.sha256(data).hexdigest()


# ---- the patch ----------------------------------------------------------------------------------------------------------------------------------------------
def make_patch(files, method=zipfile.ZIP_DEFLATED):
    """A self-extractor-shaped file with the given {name: bytes}."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", method) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return STUB + buf.getvalue()


# ---- an InstallShield 5 cabinet -----------------------------------------------------------------------------------------------------------------------------
def raw_deflate(data):
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    return c.compress(data) + c.flush()


def make_cab(version, files, chunked):
    """The layout iscab.py documents: header, descriptor at 0x200, file table (directory names, strings, 0x2a-byte file descriptors), then the data."""
    files = {n.replace("/", "\\"): d for n, d in files.items()}
    dirs = sorted({ntpath.dirname(n) for n in files})
    strings = b""
    dir_off, name_off = [], {}
    n_entries = len(dirs) + len(files)
    pos = 4 * n_entries
    for d in dirs:
        dir_off.append(pos + len(strings))
        strings += d.encode() + b"\0"
    for n in files:
        name_off[n] = pos + len(strings)
        strings += ntpath.basename(n).encode() + b"\0"
    desc_start = pos + len(strings)
    table_size = desc_start + 0x2a * len(files)
    ft_off_in_desc = 0x40
    data_start = 0x200 + ft_off_in_desc + table_size
    blobs, data = [], b""
    for n, d in files.items():
        if chunked:
            raw = b"".join(struct.pack("<H", len(c)) + c for c in (raw_deflate(d[i:i + 100]) for i in range(0, max(len(d), 1), 100)))
        else:
            raw = raw_deflate(d)
        blobs.append((n, d, raw, data_start + len(data)))
        data += raw
    descs = b""
    for n, d, raw, off in blobs:
        e = bytearray(0x2a)
        struct.pack_into("<IIHII", e, 0, name_off[n], dirs.index(ntpath.dirname(n)), 4, len(d), len(raw))
        struct.pack_into("<I", e, 0x26, off)
        descs += bytes(e)
    table = b"".join(struct.pack("<I", o) for o in dir_off) + b"".join(struct.pack("<I", desc_start + 0x2a * i) for i in range(len(files))) + strings + descs
    assert len(table) == table_size
    desc = bytearray(ft_off_in_desc)
    struct.pack_into("<III", desc, 0x0c, ft_off_in_desc, 0, table_size)
    struct.pack_into("<I", desc, 0x1c, len(dirs))
    struct.pack_into("<I", desc, 0x28, len(files))
    head = bytearray(0x200)
    head[:4] = b"ISc("
    struct.pack_into("<I", head, 4, version)
    struct.pack_into("<II", head, 0x0c, 0x200, len(desc) + len(table))
    return bytes(head) + bytes(desc) + table + data


# ---- an ISO 9660 image with folders -------------------------------------------------------------------------------------------------------------------------
SECTOR = 2048


def make_iso_tree(path, files, label="TESTDISC"):
    """Write an ISO 9660 image to `path` holding {"Folder/file.ext": bytes}. Each folder must fit in one sector (a few dozen entries)."""
    tree = {}
    for rel, data in files.items():
        node = tree
        parts = rel.split("/")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = data
    dirs = []                                   # (tree node, path) in the order their sectors are placed

    def collect(node):
        dirs.append(node)
        for v in node.values():
            if isinstance(v, dict):
                collect(v)

    collect(tree)
    first_dir = 18
    dir_lba = {id(n): first_dir + i for i, n in enumerate(dirs)}
    next_lba = first_dir + len(dirs)
    file_lba = {}
    for n in dirs:
        for k, v in n.items():
            if not isinstance(v, dict):
                file_lba[(id(n), k)] = next_lba
                next_lba += max(1, (len(v) + SECTOR - 1) // SECTOR)
    image = bytearray(SECTOR * next_lba)

    def record(name, lba, size, is_dir):
        nb = name.encode("latin-1")
        rec = bytearray(33 + len(nb) + (len(nb) % 2 == 0))
        rec[0] = len(rec)
        struct.pack_into("<I", rec, 2, lba)
        struct.pack_into("<I", rec, 10, size)
        rec[25] = 2 if is_dir else 0
        rec[32] = len(nb)
        rec[33:33 + len(nb)] = nb
        return bytes(rec)

    for n in dirs:
        body = record("\0", dir_lba[id(n)], SECTOR, True) + record("\1", dir_lba[id(n)], SECTOR, True)
        for k, v in n.items():
            if isinstance(v, dict):
                body += record(k.upper(), dir_lba[id(v)], SECTOR, True)
            else:
                body += record(k.upper() + ";1", file_lba[(id(n), k)], len(v), False)
                image[file_lba[(id(n), k)] * SECTOR:file_lba[(id(n), k)] * SECTOR + len(v)] = v
        assert len(body) <= SECTOR, "a folder of the fake disc does not fit in one sector"
        image[dir_lba[id(n)] * SECTOR:dir_lba[id(n)] * SECTOR + len(body)] = body
    pvd = bytearray(SECTOR)
    pvd[0:7] = b"\x01CD001\x01"
    pvd[40:72] = label.encode().ljust(32)
    pvd[156:190] = record("\0", dir_lba[id(tree)], SECTOR, True)[:34].ljust(34, b"\0")
    image[16 * SECTOR:17 * SECTOR] = pvd
    term = bytearray(SECTOR)
    term[0:7] = b"\xffCD001\x01"
    image[17 * SECTOR:18 * SECTOR] = term
    with open(path, "wb") as f:
        f.write(image)


TAG = b'[TagInfo]\r\nCompany=MicroProse Software, Inc.\r\nApplication=Magic The Gathering "Spells of the Ancients"\r\nVersion=%s\r\nCategory=Games\r\n'


# ---- the whole story ----------------------------------------------------------------------------------------------------------------------------------------
class World:
    """A first game's disc and the files it installs, an expansion disc with a cabinet of the 2.0 Program folder, a patch of six files, and the 2.15 files that come out, in miniature.

    `register(monkeypatch)` points tools/lift/builds.py (the known files) and tools/install/install.py at them. Attributes: iso1, iso2 and patch (paths), program215 ({name: bytes} of
    what the finished Program folder must hold), first_files (the first game's, as installed), files20 (the cabinet's)."""

    PROGRAMS = ["shandalar.exe", "FaceMaker.exe", "DECK.EXE", "deckdll.dll", "cardartlib.dll", "drawcardlib.dll", "CdTools.dll", "STATWIN.DLL", "MAGSND.DLL", "MAGVID.DLL",
                "magic.exe", "MSVCRT.DLL", "CARDS.DAT", "FaceData.txt", "Readme.txt"]
    ROLES = {"magic.exe": "kept", "MSVCRT.DLL": "kept", "CARDS.DAT": "data", "FaceData.txt": "data", "Readme.txt": "data", "MAGSND.DLL": "host", "MAGVID.DLL": "host"}
    PATCHED = ["shandalar.exe", "Readme.txt", "magic.exe", "FaceData.txt", "deckdll.dll", "CARDS.DAT"]      # the six files of the patch (cards.dat and readme.txt in its own spelling)

    def __init__(self, root, cab_version=0x01005100, chunked=True):
        self.root = str(root)
        self.program215 = {n: (b"2.15 " + n.encode() + b"\n") * 7 for n in self.PROGRAMS}
        self.program20 = {n: (self.program215[n] if n not in self.PATCHED else b"2.0 " + n.encode() + b"\n") for n in self.PROGRAMS}
        # what the first game's disc installs (its own programs and the pictures SotA needs): (the archive's folder, {file: bytes}) in the archive's order
        self.first_layout = [("program", {"MAGIC.EXE": b"1.0 shell", "DECK.EXE": b"1.0 deck", "DECKDLL.DLL": b"1.0 deck library"}),
                             ("program\\CardArt", {"Forest.pic": b"a picture"}), ("program\\Decks", {"starter.dek": b"1.0 starter deck"}),
                             ("program\\Sound", {"LOCMUS0.WAV": b"music" * 50}), ("program\\Statwin", {"FIRE.AVI": b"movie" * 50})]
        self.first_files = {d.replace("\\", "/").replace("program", "Program", 1) + "/" + n: b for d, fs in self.first_layout for n, b in fs.items()}
        self.cab_files = {"Program/" + n: d for n, d in self.program20.items()}
        self.cab_files.update({"Program/Decks/starter.dek": b"2.0 starter deck", "Program/ShellArt/Back.pic": b"a new picture", "Program/DuelSounds/Shell_Tooltime.wav": b"voice" * 20,
                               "Readme.txt": b"2.0 readme at the top", "MicroProse.url": b"[InternetShortcut]\r\n"})
        self.patch_files = {("cards.dat" if n == "CARDS.DAT" else "readme.txt" if n == "Readme.txt" else n): self.program215[n] for n in self.PATCHED}
        self.cab_bytes = make_cab(cab_version, self.cab_files, chunked)
        self.sys_bytes = make_cab(cab_version, {"Ctl3d32.dll": b"a helper" * 30, "Corecomp.ini": b"[ini]"}, chunked)
        self.user_bytes = make_cab(cab_version, {"license.txt": b"text", "Bbrd1.bmp": b"B" * 400}, chunked)
        self.patch_bytes = make_patch(self.patch_files)
        self.iso1 = os.path.join(self.root, "MTG v1.0.iso")
        self.iso2 = os.path.join(self.root, "MTG v2.00.iso")
        self.patch = os.path.join(self.root, "SOTAV215.EXE")
        self.write()

    def write(self, tag_version="2.0"):
        os.makedirs(self.root, exist_ok=True)
        import test_install                                      # the first disc's archive is made by the installer's own tests' encoder
        listing = [(n, b) for _d, fs in self.first_layout for n, b in fs.items()]
        archive = test_install.make_archive([("README.TXT", b"read me"), ("x.url", b"[url]")] + listing, [(d, len(fs)) for d, fs in self.first_layout])
        make_iso_tree(self.iso1, {"Setup/data.z": archive, "Setup/SETUP.INS": b"script", "Sound/BOOM.WAV": b"boom" * 10}, label="MTG v1.0")
        make_iso_tree(self.iso2, {"Setup/data1.cab": self.cab_bytes, "Setup/_sys1.cab": self.sys_bytes, "Setup/_user1.cab": self.user_bytes, "Setup/DATA.TAG": TAG % tag_version.encode(),
                                  "Sound/NEW.WAV": b"a new sound" * 10, "Sound/LOCMUS0.WAV": b"music" * 50, "DuelSounds/Shell_Tooltime.wav": b"other voice" * 20}, label="MTG v2")
        with open(self.patch, "wb") as f:
            f.write(self.patch_bytes)

    def known(self):
        """The rows for builds.KNOWN: the first game's files (v1.0) and the 2.15 files."""
        rows = [("v1.0", n, sha(self.first_files["Program/" + n]), "lifted") for n in ("MAGIC.EXE", "DECK.EXE", "DECKDLL.DLL")]
        rows += [("v2.15", n, sha(self.program215[n]), self.ROLES.get(n, "lifted")) for n in self.PROGRAMS]
        return rows

    def register(self, monkeypatch):
        import builds
        import install
        import sotainstall
        rows = self.known()
        monkeypatch.setattr(builds, "KNOWN", rows)
        monkeypatch.setattr(builds, "SIZES", {sha(d): len(d) for d in self.program215.values()})
        monkeypatch.setattr(builds, "SOTA_DISC", dict(builds.SOTA_DISC, cabinets={"data1.cab": (len(self.cab_bytes), sha(self.cab_bytes)),
                                                                                 "_sys1.cab": (len(self.sys_bytes), sha(self.sys_bytes)),
                                                                                 "_user1.cab": (len(self.user_bytes), sha(self.user_bytes))},
                                                     cd_folders=[("Sound", "Sound", ".wav"), ("StatWin", "Statwin", ".avi")]))
        monkeypatch.setattr(builds, "SOTA_PATCH", dict(builds.SOTA_PATCH, size=len(self.patch_bytes), sha256=sha(self.patch_bytes), files=list(self.patch_files)))
        monkeypatch.setattr(install, "FINGERPRINTS", builds.fingerprints("v1.0"))
        return sotainstall

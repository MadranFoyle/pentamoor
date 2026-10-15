"""
iso9660.py - read files out of a CD image (a plain 2048-bytes-a-sector .iso) without mounting it, so it works the same on macOS, Linux and Windows.
Joliet names (long, mixed case) are used when the disc has them, else the ISO 9660 ones.
"""
import os
import struct

SECTOR = 2048


class IsoError(Exception):
    pass


class Entry:
    def __init__(self, name, lba, size, is_dir):
        self.name, self.lba, self.size, self.is_dir = name, lba, size, is_dir


class Iso:
    def __init__(self, path):
        self.path = path
        self.f = open(path, "rb")
        self.joliet = False
        root = None
        sector = 16
        while True:                                            # the volume descriptors
            self.f.seek(sector * SECTOR)
            vd = self.f.read(SECTOR)
            if len(vd) < SECTOR or vd[1:6] != b"CD001":
                break
            kind = vd[0]
            if kind == 1 and root is None:
                root = vd[156:190]
                self.label = vd[40:72].decode("ascii", "replace").strip()
            elif kind == 2 and vd[88:91] in (b"%/@", b"%/C", b"%/E"):
                root, self.joliet = vd[156:190], True
            elif kind == 255:
                break
            sector += 1
        if root is None:
            raise IsoError(f"{path} is not an ISO 9660 image (a raw .mdf is not: convert it first, see docs)")
        self.root = Entry("", struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0], True)

    def read_dir(self, entry):
        self.f.seek(entry.lba * SECTOR)
        data = self.f.read(entry.size)
        out, pos = [], 0
        while pos < len(data):
            n = data[pos]
            if n == 0:                                         # padding to the end of the sector
                pos = (pos // SECTOR + 1) * SECTOR
                continue
            lba, size = struct.unpack_from("<I", data, pos + 2)[0], struct.unpack_from("<I", data, pos + 10)[0]
            flags, nl = data[pos + 25], data[pos + 32]
            raw = data[pos + 33:pos + 33 + nl]
            pos += n
            if raw in (b"\x00", b"\x01"):
                continue
            name = raw.decode("utf-16-be" if self.joliet else "latin-1")
            if ";" in name:
                name = name.split(";")[0]
            if name.endswith(".") and len(name) > 1:
                name = name[:-1]
            out.append(Entry(name, lba, size, bool(flags & 2)))
        return out

    def find(self, path):
        """The entry for a path like 'Setup/data.z' (names compared without regard to case), or None."""
        cur = self.root
        for part in [p for p in path.replace("\\", "/").split("/") if p]:
            nxt = next((e for e in self.read_dir(cur) if e.name.lower() == part.lower()), None)
            if nxt is None:
                return None
            cur = nxt
        return cur

    def listdir(self, path):
        e = self.find(path)
        return self.read_dir(e) if e and e.is_dir else []

    def read(self, entry, offset=0, size=None):
        self.f.seek(entry.lba * SECTOR + offset)
        return self.f.read(entry.size - offset if size is None else size)

    def copy(self, entry, dest, chunk=1 << 20):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        self.f.seek(entry.lba * SECTOR)
        left = entry.size
        with open(dest, "wb") as out:
            while left > 0:
                buf = self.f.read(min(chunk, left))
                if not buf:
                    raise IsoError(f"{self.path} ends inside {entry.name}")
                out.write(buf)
                left -= len(buf)


class Folder:
    """The same few calls over a folder that already holds the disc's files (a mounted disc, or a copy of one)."""

    def __init__(self, path):
        self.path = path
        self.label = os.path.basename(os.path.normpath(path))

    def _real(self, path):
        cur = self.path
        for part in [p for p in path.replace("\\", "/").split("/") if p]:
            hit = next((n for n in os.listdir(cur) if n.lower() == part.lower()), None) if os.path.isdir(cur) else None
            if hit is None:
                return None
            cur = os.path.join(cur, hit)
        return cur

    def find(self, path):
        real = self._real(path)
        return None if real is None else Entry(os.path.basename(real), real, 0 if os.path.isdir(real) else os.path.getsize(real), os.path.isdir(real))

    def listdir(self, path):
        real = self._real(path)
        return [] if real is None or not os.path.isdir(real) else \
            [Entry(n, os.path.join(real, n), 0 if os.path.isdir(os.path.join(real, n)) else os.path.getsize(os.path.join(real, n)), os.path.isdir(os.path.join(real, n)))
             for n in sorted(os.listdir(real))]

    def read(self, entry, offset=0, size=None):
        with open(entry.lba, "rb") as f:
            f.seek(offset)
            return f.read(entry.size - offset if size is None else size)

    def copy(self, entry, dest, chunk=1 << 20):
        import shutil
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(entry.lba, dest)


def open_disc(path):
    return Folder(path) if os.path.isdir(path) else Iso(path)

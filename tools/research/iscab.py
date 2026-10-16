"""
iscab.py - list and extract the files in an InstallShield 5 cabinet ("ISc(" signature: data1.cab, _sys1.cab, _user1.cab), in plain Python.

This is what the disc of *Spells of the Ancients* 2.0 uses (the 1.0 disc has a single InstallShield 3 archive, see tools/install/datax.py). It is a research tool
and is not used by the installer. There is no separate data1.hdr on that disc: the header (directory names, file descriptors) is at the start of the cabinet itself.

Layout, as worked out from the 2.0 disc (little-endian):
  0x00  "ISc("   0x04 version (0x01005100: major version 5)   0x0c offset of the cabinet descriptor (0x200)   0x10 its size
  descriptor (at 0x200): +0x0c offset of the file table inside it, +0x14 its size, +0x1c number of directories, +0x28 number of files
  file table: (directories + files) u32 offsets, relative to the table's start; the first `directories` point at NUL-terminated directory
      names ("Program\\CardArt"), the others at file descriptors, 0x2a bytes each:
      +0x00 name offset (NUL-terminated string, relative to the table)  +0x04 directory index  +0x08 u16 flags (4 compressed, 2 obfuscated, 1 split, 8 an unused slot)
      +0x0a expanded size  +0x0e packed size  +0x12 u16 DOS attributes  +0x16 u16 DOS date  +0x1a u16 DOS time  +0x26 offset of the data in the cabinet
  data: for a compressed file, a run of chunks, each a u16 length and that many bytes of raw deflate (zlib without the header), each inflated on its own.
        (The obfuscated flag is set on every file but the bytes are plain deflate, the 1.0 reader of this flag in other tools applies to other versions.)
"""
import contextlib
import struct
import sys
import zlib

SIGNATURE = b"ISc("


class CabError(Exception):
    pass


class Cab:
    def __init__(self, f, size=None):
        """`f` is a file object (seekable) holding the cabinet."""
        self.f = f
        f.seek(0)
        head = f.read(0x30)
        if head[:4] != SIGNATURE:
            raise CabError("not an InstallShield cabinet (no 'ISc(' signature)")
        self.version = struct.unpack_from("<I", head, 4)[0]
        off, size = struct.unpack_from("<II", head, 0x0c)
        f.seek(off)
        desc = f.read(size)
        ft_off, _, ft_size = struct.unpack_from("<III", desc, 0x0c)
        self.ndirs, self.nfiles = struct.unpack_from("<I", desc, 0x1c)[0], struct.unpack_from("<I", desc, 0x28)[0]
        f.seek(off + ft_off)
        tbl = f.read(ft_size)
        offs = struct.unpack_from("<%dI" % (self.ndirs + self.nfiles), tbl, 0)

        def cstr(o):
            return tbl[o:tbl.index(b"\0", o)].decode("latin-1")

        self.dirs = [cstr(o) for o in offs[:self.ndirs]]
        self.files = []                                     # (path, expanded, packed, offset, flags, dos date, dos time)
        for o in offs[self.ndirs:]:
            name, di, flags, exp, packed, _attr, date, time = struct.unpack_from("<IIHIIHxxHxxH", tbl, o)
            if flags & 8:                                   # an unused slot (a few cabinets keep three of them)
                continue
            (data_off,) = struct.unpack_from("<I", tbl, o + 0x26)
            if di >= self.ndirs:
                raise CabError("file descriptor with directory %d of %d" % (di, self.ndirs))
            d = self.dirs[di]
            self.files.append(((d + "\\" if d else "") + cstr(name), exp, packed, data_off, flags, date, time))

    def read(self, entry):
        """The bytes of one file (an item of self.files)."""
        path, exp, packed, off, flags, _d, _t = entry
        if flags & 1:
            raise CabError(path + ": a file split over several cabinets")
        self.f.seek(off)
        raw = self.f.read(packed)
        if not flags & 4:
            return raw
        out, p = bytearray(), 0
        while p + 2 <= len(raw):
            (n,) = struct.unpack_from("<H", raw, p)
            out += zlib.decompress(raw[p + 2:p + 2 + n], -15)
            p += 2 + n
        if len(out) != exp:
            raise CabError("%s: %d bytes unpacked, %d expected" % (path, len(out), exp))
        return bytes(out)


class _InIso:
    """A seekable view of one file of a disc image, so a cabinet can be read from the .iso without copying it out first."""

    def __init__(self, iso, entry):
        self.iso, self.entry, self.pos = iso, entry, 0

    def seek(self, pos):
        self.pos = pos

    def read(self, n):
        data = self.iso.read(self.entry, self.pos, min(n, self.entry.size - self.pos))
        self.pos += len(data)
        return data


def open_cab(spec):
    """A file object for a path, or for 'disc.iso:Setup/data1.cab' (a file inside an image, read with tools/install/iso9660.py)."""
    import os
    if ":" in spec and spec.split(":")[0].lower().endswith(".iso"):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "install"))
        import iso9660
        iso, inner = spec.rsplit(":", 1)
        disc = iso9660.Iso(iso)
        entry = disc.find(inner)
        if entry is None:
            raise CabError(spec + ": not on the disc")
        return _InIso(disc, entry)
    return open(spec, "rb")


def main(argv):
    import os
    if len(argv) < 2:
        print("usage: iscab.py CABINET|DISC.iso:Setup/data1.cab [OUTDIR]   (lists the files; extracts them to OUTDIR when given)")
        return 2
    with contextlib.nullcontext(open_cab(argv[1])) as f:
        cab = Cab(f)
        for e in cab.files:
            print("%10d %10d  %s" % (e[1], e[2], e[0]))
            if len(argv) > 2:
                dest = os.path.join(argv[2], *e[0].split("\\"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as out:
                    out.write(cab.read(e))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

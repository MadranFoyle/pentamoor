"""
iscab.py - list and extract the files in an InstallShield 5 cabinet ("ISc(" signature: data1.cab, _sys1.cab, _user1.cab), in plain Python.

This is what the disc of *Spells of the Ancients* 2.0 uses (the 1.0 disc has a single InstallShield 3 archive, see tools/install/datax.py). The installer reads the
cabinets straight out of the disc image (tools/install/sotainstall.py; `python3 tools/install/iscab.py "MTG v2.00.iso:Setup/data1.cab" OUTDIR` does it by hand). There is no separate
data1.hdr on that disc: the header (directory names, file descriptors) is at the start of the cabinet itself.
A cabinet that is cut short, or whose tables point outside the file, is a CabError that says so (the file table is read whole before anything is trusted; a file's data is
checked to be all there before it is inflated, and to inflate to the announced size).

Layout, as worked out from the 2.0 disc (little-endian):
  0x00  "ISc("   0x04 version (0x01005100: major version 5)   0x0c offset of the cabinet descriptor (0x200)   0x10 its size
  descriptor (at 0x200): +0x0c offset of the file table inside it, +0x14 its size, +0x1c number of directories, +0x28 number of files
  file table: (directories + files) u32 offsets, relative to the table's start; the first `directories` point at NUL-terminated directory
      names ("Program\\CardArt"), the others at file descriptors, 0x2a bytes each:
      +0x00 name offset (NUL-terminated string, relative to the table)  +0x04 directory index  +0x08 u16 flags (4 compressed, 2 obfuscated, 1 split, 8 an unused slot)
      +0x0a expanded size  +0x0e packed size  +0x12 u16 DOS attributes  +0x16 u16 DOS date  +0x1a u16 DOS time  +0x26 offset of the data in the cabinet
  data: version 0x01005100 (the 2.0 disc): for a compressed file, a run of chunks, each a u16 length and that many bytes of raw deflate (zlib without the header), each
        inflated on its own. (The obfuscated flag is set on every file but the bytes are plain deflate, the 1.0 reader of this flag in other tools applies to other versions.)
        version 0x01000004 (the ManaLink 3.0 add-on, January 1998): the same descriptor and file table, but a compressed file is ONE raw deflate stream, with no chunk
        lengths and no obfuscation flag; the bytes of stored (incompressible) files are deflate "stored" blocks, so a packed size can exceed the expanded one by a few bytes.
        `read` picks the layout from the version (major digit of the low word: 5 = chunks) and falls back on the other when the size does not come out.
"""
import contextlib
import os
import struct
import sys
import zlib

SIGNATURE = b"ISc("


class CabError(Exception):
    pass


class Cab:
    def __init__(self, f, size=None):
        """`f` is a file object (seekable) holding the cabinet; `size`: its length when known (else found by seeking to the end), so a table that points past it is told apart from a short read."""
        self.f = f
        f.seek(0)
        head = f.read(0x30)
        if head[:4] != SIGNATURE:
            raise CabError("not an InstallShield cabinet (no 'ISc(' signature)")
        if len(head) < 0x30:
            raise CabError("cut short: the header is incomplete")
        self.version = struct.unpack_from("<I", head, 4)[0]
        self.size = size if size is not None else _length(f)
        try:
            off, dsize = struct.unpack_from("<II", head, 0x0c)
            f.seek(off)
            desc = f.read(dsize)
            if len(desc) < 0x2c:
                raise CabError("cut short: the descriptor at 0x%x is incomplete" % off)
            ft_off, _, ft_size = struct.unpack_from("<III", desc, 0x0c)
            self.ndirs, self.nfiles = struct.unpack_from("<I", desc, 0x1c)[0], struct.unpack_from("<I", desc, 0x28)[0]
            if off + ft_off + ft_size > self.size or ft_size < 4 * (self.ndirs + self.nfiles):
                raise CabError("cut short or damaged: the file table (%d bytes at 0x%x) does not fit in a cabinet of %d bytes" % (ft_size, off + ft_off, self.size))
            f.seek(off + ft_off)
            tbl = f.read(ft_size)
            if len(tbl) < ft_size:
                raise CabError("cut short: the file table is incomplete")
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
        except (struct.error, ValueError, IndexError) as e:
            raise CabError("damaged: the file table does not read (%s)" % e)

    def read(self, entry):
        """The bytes of one file (an item of self.files)."""
        path, exp, packed, off, flags, _d, _t = entry
        if flags & 1:
            raise CabError(path + ": a file split over several cabinets")
        self.f.seek(off)
        raw = self.f.read(packed)
        if len(raw) < packed:
            raise CabError("%s: cut short, %d of %d packed bytes are there" % (path, len(raw), packed))
        if not flags & 4:
            return raw
        # two layouts of a compressed file, by the cabinet's version (see the top of the file); the other is tried if the first fails
        order = (self._chunks, self._stream) if self.chunked else (self._stream, self._chunks)
        for i, method in enumerate(order):
            try:
                out = method(raw)
                if len(out) == exp:
                    return out
                err = "%d bytes unpacked, %d expected" % (len(out), exp)
            except zlib.error as e:
                err = str(e)
        raise CabError("%s: %s" % (path, err))

    @property
    def chunked(self):
        return (self.version >> 12) & 0xf >= 5

    @staticmethod
    def _chunks(raw):
        out, p = bytearray(), 0
        while p + 2 <= len(raw):
            (n,) = struct.unpack_from("<H", raw, p)
            out += zlib.decompress(raw[p + 2:p + 2 + n], -15)
            p += 2 + n
        return bytes(out)

    @staticmethod
    def _stream(raw):
        return zlib.decompressobj(-15).decompress(raw)


def _length(f):
    """The length of a seekable file object (an _InIso has its entry's size)."""
    if hasattr(f, "entry"):
        return f.entry.size
    here = f.tell()
    f.seek(0, os.SEEK_END)
    n = f.tell()
    f.seek(here)
    return n


class _InIso:
    """A seekable view of one file of a disc image, so a cabinet can be read from the .iso without copying it out first."""

    def __init__(self, iso, entry):
        self.iso, self.entry, self.pos = iso, entry, 0

    def seek(self, pos, whence=0):
        self.pos = pos if whence == 0 else self.entry.size + pos if whence == 2 else self.pos + pos

    def tell(self):
        return self.pos

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n):
        data = self.iso.read(self.entry, self.pos, min(n, self.entry.size - self.pos))
        self.pos += len(data)
        return data


def open_in_disc(disc, entry):
    """A seekable file object for one file of a disc (an .iso read by iso9660.Iso, or a folder with the disc's files) that a Cab can read."""
    if hasattr(disc, "f"):
        return _InIso(disc, entry)
    return open(entry.lba, "rb")                  # iso9660.Folder keeps the real path in .lba


def open_cab(spec):
    """A file object for a path, or for 'disc.iso:Setup/data1.cab' (a file inside an image, read with tools/install/iso9660.py)."""
    if ":" in spec and spec.split(":")[0].lower().endswith(".iso"):
        import iso9660
        iso, inner = spec.rsplit(":", 1)
        disc = iso9660.Iso(iso)
        entry = disc.find(inner)
        if entry is None:
            raise CabError(spec + ": not on the disc")
        return _InIso(disc, entry)
    return open(spec, "rb")


def main(argv):
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

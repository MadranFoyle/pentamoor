"""
datax.py - the files inside the game's InstallShield 3 archive (Setup/data.z on the disc).

Layout (worked out from the archive and checked against the installed game): a 0x8C655D13 signature, the length of the file at 0x12, and at 0x29 the offset of the
directory table. The table lists the directories ("program", "program\\SPR800", ...) with how many files each holds, in file order (u16 count, u16 record length,
u16 name length, the name, five zero bytes). After it come 19 bytes that end with the first file's size, packed size and offset, and then one record per file
(u32 0x20, u32 record length, two zero bytes, a name length byte, the name, padding), each ending in a 16-byte block with the size, packed size and offset of the
file that comes NEXT. The first two records (README.TXT, a shortcut) are not in any directory of the table. Each file's data sits at its offset, packed with PKWARE DCL (blast.py).
"""
import hashlib
import struct

from blast import BlastError, blast

SIGNATURE = 0x8C655D13


class DataZError(Exception):
    pass


def parse(d):
    """[(path, size, packed size, offset)] of every file in the archive, `path` with backslashes, from the directory it was listed under."""
    if len(d) < 0x40 or struct.unpack_from("<I", d, 0)[0] != SIGNATURE:
        raise DataZError("data.z is not an InstallShield 3 archive")
    tbl = struct.unpack_from("<I", d, 0x29)[0]
    pos = tbl + 11
    dirs = []
    while pos + 6 <= len(d):
        count, reclen, nl = struct.unpack_from("<HHH", d, pos)
        if reclen != nl + 11 or not 0 < nl < 100:
            break
        dirs.append((count, d[pos + 6:pos + 6 + nl].decode("latin-1")))
        pos += 6 + nl + 5
    total = sum(c for c, _ in dirs)
    size0, packed0, off0 = struct.unpack_from("<III", d, pos + 3)
    metas = [(size0, packed0, off0)]
    names = []
    p = pos + 19
    while p + 11 <= len(d) and struct.unpack_from("<I", d, p)[0] == 0x20:
        length = struct.unpack_from("<I", d, p + 4)[0]
        nl = d[p + 10]
        names.append(d[p + 11:p + 11 + nl].decode("latin-1"))
        if p + length - 4 <= len(d):                                      # (the last record has no next file)
            metas.append(struct.unpack_from("<III", d, p + length - 16))     # the NEXT file's
        p += length
    lead = len(names) - total                  # files the table does not list (README.TXT and a MicroProse.url shortcut, which the installer puts elsewhere) come first
    if lead < 0:
        raise DataZError(f"the directory says {total} files and the file records {len(names)}")
    out, k = [], lead
    for count, dirname in dirs:
        for _ in range(count):
            out.append((dirname + "\\" + names[k], *metas[k]))
            k += 1
    return out


def unpack(d, size, packed, offset):
    """One file's bytes."""
    raw = d[offset:offset + packed]
    if packed == size and not (len(raw) > 1 and raw[0] <= 1 and 4 <= raw[1] <= 6 and size > 2 and _looks_packed(raw, size)):
        return raw
    try:
        data = blast(raw, size)
    except BlastError:
        if packed == size:
            return raw
        raise
    if len(data) != size:
        raise DataZError(f"unpacked {len(data)} bytes where {size} were expected")
    return data


def _looks_packed(raw, size):
    try:
        return len(blast(raw, size)) == size
    except BlastError:
        return False


def sha256(b):
    return hashlib.sha256(b).hexdigest()

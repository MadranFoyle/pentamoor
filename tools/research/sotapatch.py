#!/usr/bin/env python3
"""
sotapatch.py - list and extract the files of a WinZip self-extractor (sotav215.exe, the Spells of the Ancients 2.15 patch) in plain Python.

    sotapatch.py PATCH.exe [OUTDIR]        lists the entries; extracts them to OUTDIR when given

The self-extractor is a Windows program followed by a ZIP archive, and the program contains byte pairs that look like ZIP signatures, so zipfile cannot open it. This reads the
local file headers itself: a header counts only if its fields make sense (a known compression method, a name of printable characters, sizes that fit in the file) and its data
inflates to the size it announces. Entries are stored (method 0) or raw deflate (method 8). Names are reduced to their last component, so nothing is written outside OUTDIR.
The patch holds whole replacement files, not deltas: version 2.15 is the 2.0 install with these files replaced.
"""
import os
import struct
import sys
import zlib

SIG = b"PK\x03\x04"


def entries(data):
    """[(offset, name, method, packed, size, date, time, data offset)] of every local file header in `data` that is valid."""
    out, pos = [], 0
    while True:
        pos = data.find(SIG, pos)
        if pos < 0:
            return out
        try:
            ver, flags, method, tm, dt, crc, packed, size, nlen, xlen = struct.unpack_from("<HHHHHIIIHH", data, pos + 4)
            raw_name = data[pos + 30:pos + 30 + nlen]
            start = pos + 30 + nlen + xlen
            ok = (ver < 64 and method in (0, 8) and 0 < nlen < 128 and all(32 <= c < 127 for c in raw_name) and not flags & 8 and start + packed <= len(data))
            if ok:
                body = data[start:start + packed]
                body = zlib.decompress(body, -15) if method == 8 else body
                ok = len(body) == size and zlib.crc32(body) & 0xFFFFFFFF == crc
        except (struct.error, zlib.error):
            ok = False
        if ok:
            out.append((pos, raw_name.decode("ascii"), method, packed, size, dt, tm, start))
            pos = start + packed
        else:
            pos += 4


def read(data, entry):
    pos, name, method, packed, size, dt, tm, start = entry
    body = data[start:start + packed]
    return zlib.decompress(body, -15) if method == 8 else body


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    with open(argv[1], "rb") as f:
        data = f.read()
    for e in entries(data):
        pos, name, method, packed, size, dt, tm, start = e
        print("%9d  %-20s method %d  %9d -> %9d  %04d-%02d-%02d" % (pos, name, method, packed, size, 1980 + (dt >> 9), (dt >> 5) & 15, dt & 31))
        if len(argv) > 2:
            dest = os.path.join(argv[2], os.path.basename(name.replace("\\", "/")))
            if os.path.islink(dest):
                raise SystemExit("refusing to write through a symbolic link: " + dest)
            os.makedirs(argv[2], exist_ok=True)
            with open(dest, "wb") as out:
                out.write(read(data, e))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

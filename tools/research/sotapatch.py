#!/usr/bin/env python3
"""
sotapatch.py - list, verify and extract the files of a WinZip self-extractor (sotav215.exe, the Spells of the Ancients 2.15 patch) in plain Python.

    sotapatch.py PATCH.exe [OUTDIR]        lists the entries with their CRC-32 and SHA-256; extracts them to OUTDIR when given and the archive is whole
                                           (a file already in OUTDIR that differs only in case is replaced under its own name, so OUTDIR can be a game folder)
    sotapatch.py --partial PATCH.exe OUTDIR  extracts the whole entries even if the archive is not
    sotapatch.py --check PATCH.exe         lists and verifies only; same exit status as below

The self-extractor is a Windows program followed by a ZIP archive, and the program contains byte pairs that look like ZIP signatures, so zipfile cannot open it. This reads the
local file headers itself: a header counts only if its fields make sense (a known compression method, a name of file-name characters, a size that is not absurd), and each entry
is then judged on its data:

    ok          the data is all there, inflates to the announced size and matches the announced CRC-32
    TRUNCATED   the header is sound but the file ends before the entry's data does (a cut-short download or copy)
    CORRUPT     the data is there but does not inflate, or inflates to another size, or fails the CRC-32

The archive's own table (the central directory at the end of the file, "PK\\x01\\x02" records and the "PK\\x05\\x06" end record) is read too when it survived: its entries are
compared with the local ones, and a file with no end record is reported as cut short even when every entry it holds is whole (an entry that is missing altogether can only
be seen this way). Entries are stored (method 0) or raw deflate (method 8). Names are reduced to their last component, so nothing is written outside OUTDIR.
The patch holds whole replacement files, not deltas: version 2.15 is the 2.0 install with these files replaced.

Exit status: 0 when every entry is ok and the archive's end record is there; 1 when anything is truncated, corrupt or missing (nothing is extracted unless --partial, and then bad ones
never are, and the report says which); 2 on a usage error.
"""
import hashlib
import os
import re
import struct
import sys
import zlib

SIG = b"PK\x03\x04"
CEN_SIG = b"PK\x01\x02"
END_SIG = b"PK\x05\x06"
NAME_OK = re.compile(rb"^[A-Za-z0-9_.\-+ ()\\/]+$")


def _header(data, pos):
    """The fields of a local file header at `pos` if they make sense, else None."""
    try:
        ver, flags, method, tm, dt, crc, packed, size, nlen, xlen = struct.unpack_from("<HHHHHIIIHH", data, pos + 4)
    except struct.error:
        return None
    raw_name = data[pos + 30:pos + 30 + nlen]
    if not (ver < 64 and method in (0, 8) and 0 < nlen < 128 and len(raw_name) == nlen and NAME_OK.match(raw_name) and b"." in raw_name and not flags & 8
            and packed < (1 << 31) and size < (1 << 31) and (method == 8 or packed == size)):
        return None
    return dict(pos=pos, name=raw_name.decode("ascii"), method=method, packed=packed, size=size, crc=crc, date=dt, time=tm, start=pos + 30 + nlen + xlen)


def scan(data):
    """Every sound-looking local header of `data` as a dict with a 'status' of 'ok', 'truncated' or 'corrupt' (and 'why' for the last two), in file order."""
    out, pos = [], 0
    while True:
        pos = data.find(SIG, pos)
        if pos < 0:
            return out
        h = _header(data, pos)
        if h is None:
            pos += 4
            continue
        body = data[h["start"]:h["start"] + h["packed"]]
        if len(body) < h["packed"]:
            h.update(status="truncated", why="%d of %d packed bytes present" % (len(body), h["packed"]), have=len(body))
            out.append(h)
            pos += 4
            continue
        try:
            plain = zlib.decompress(body, -15) if h["method"] == 8 else body
        except zlib.error as e:
            plain = None
            h.update(status="corrupt", why="does not inflate (%s)" % e)
        if plain is not None:
            if len(plain) != h["size"]:
                h.update(status="corrupt", why="inflates to %d bytes, %d announced" % (len(plain), h["size"]))
            elif zlib.crc32(plain) & 0xFFFFFFFF != h["crc"]:
                h.update(status="corrupt", why="CRC-32 %08x, %08x announced" % (zlib.crc32(plain) & 0xFFFFFFFF, h["crc"]))
            else:
                h.update(status="ok", why="")
        if h["status"] == "corrupt":
            # a corrupt header in the stub is far more likely a false signature than a damaged entry; only report it if it is a file-like name
            # that the central directory also names (see report()); otherwise skip it
            h["maybe_false"] = True
            out.append(h)
            pos += 4
        else:
            out.append(h)
            pos = h["start"] + h["packed"]


def central(data):
    """([(name, size, crc)] from the central directory, whether the end record is there). The end record must be the last thing in the file (up to its comment)."""
    end = data.rfind(END_SIG)
    names = []
    if end < 0 or end + 22 > len(data):
        return names, False
    (clen,) = struct.unpack_from("<H", data, end + 20)
    if end + 22 + clen != len(data):
        return names, False                                 # a false signature somewhere in the file, not the archive's end
    cen_size = struct.unpack_from("<I", data, end + 12)[0]
    p = end - cen_size                                      # the directory ends where the end record starts (offsets inside a self-extractor are not the file's)
    while p >= 0 and p + 46 <= end and data[p:p + 4] == CEN_SIG:
        flags, method, tm, dt, crc, packed, size, nlen, xlen, clen = struct.unpack_from("<HHHHIIIHHH", data, p + 8)
        names.append((data[p + 46:p + 46 + nlen].decode("latin-1"), size, crc))
        p += 46 + nlen + xlen + clen
    return names, True


def entries(data):
    """[(offset, name, method, packed, size, date, time, data offset)] of every local file header in `data` that is complete and valid (the old interface)."""
    return [(e["pos"], e["name"], e["method"], e["packed"], e["size"], e["date"], e["time"], e["start"]) for e in scan(data) if e["status"] == "ok"]


def read(data, entry):
    pos, name, method, packed, size, dt, tm, start = entry
    body = data[start:start + packed]
    return zlib.decompress(body, -15) if method == 8 else body


def report(data):
    """(entries, problems): the scan with false signatures dropped and a list of strings, one for each way the archive is not whole."""
    es = scan(data)
    cen, has_end = central(data)
    cen_names = {n.replace("\\", "/").split("/")[-1].lower() for n, _s, _c in cen}
    good = [e for e in es if e["status"] == "ok" or e["status"] == "truncated" or (e["status"] == "corrupt" and (not e.get("maybe_false") or e["name"].lower() in cen_names))]
    problems = []
    for e in good:
        if e["status"] != "ok":
            problems.append("%s: %s (%s)" % (e["name"], e["status"].upper(), e["why"]))
    if not has_end:
        problems.append("no end-of-central-directory record: the archive is cut short" + (" after the last entry listed" if good else ""))
    elif cen:
        have = {e["name"].lower() for e in good if e["status"] == "ok"}
        for n, _s, _c in cen:
            if n.replace("\\", "/").split("/")[-1].lower() not in have:
                problems.append("%s: listed in the archive's directory but no whole copy was found" % n)
    return good, problems




def destination(outdir, name):
    """Where an entry goes in `outdir`: the name of a file already there that differs only in case (the game's folder has CARDS.DAT, the patch says cards.dat), else the entry's own."""
    base = os.path.basename(name.replace("\\", "/"))
    if os.path.isdir(outdir):
        for have in os.listdir(outdir):
            if have.lower() == base.lower():
                return os.path.join(outdir, have)
    return os.path.join(outdir, base)


def main(argv):
    flags = [a for a in argv[1:] if a.startswith("--")]
    args = [a for a in argv[1:] if not a.startswith("--")]
    if not args or any(f not in ("--check", "--partial") for f in flags):
        print(__doc__)
        return 2
    with open(args[0], "rb") as f:
        data = f.read()
    outdir = args[1] if len(args) > 1 and "--check" not in flags else None
    good, problems = report(data)
    if problems and outdir and "--partial" not in flags:
        print("not extracting: the archive has problems (--partial extracts the entries that are whole)", file=sys.stderr)
        outdir = None
    print("%s  %d bytes  sha256 %s" % (os.path.basename(args[0]), len(data), hashlib.sha256(data).hexdigest()))
    for e in good:
        line = "%9d  %-16s method %d  %9d -> %9d  %04d-%02d-%02d  %s" % (e["pos"], e["name"], e["method"], e["packed"], e["size"], 1980 + (e["date"] >> 9), (e["date"] >> 5) & 15,
                                                                          e["date"] & 31, e["status"].upper() if e["status"] != "ok" else "ok")
        if e["status"] == "ok":
            body = data[e["start"]:e["start"] + e["packed"]]
            plain = zlib.decompress(body, -15) if e["method"] == 8 else body
            line += "  crc %08x  sha256 %s" % (e["crc"], hashlib.sha256(plain).hexdigest())
            if outdir:
                dest = destination(outdir, e["name"])
                if os.path.islink(dest):
                    raise SystemExit("refusing to write through a symbolic link: " + dest)
                os.makedirs(outdir, exist_ok=True)
                with open(dest, "wb") as out:
                    out.write(plain)
                line += "  -> " + os.path.basename(dest)
        print(line)
    for p in problems:
        print("PROBLEM: " + p, file=sys.stderr)
    if problems:
        print("%d problem(s): this is NOT a whole archive" % len(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

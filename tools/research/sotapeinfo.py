#!/usr/bin/env python3
"""
sotapeinfo.py - build identity of Windows programs and libraries: what a link leaves in the file (no game data is printed, only header fields and the shape of strings).

    sotapeinfo.py FILE...            one block per file: size, SHA-256, link time, machine/linker/OS versions, image base, entry point, sections with their sizes,
                                     the debug directory (kind, time, PDB path), the "Rich" header (the compiler and linker tools that made the objects: product id, build, count),
                                     the version-info resource, number of imports and exports, and the strings that name a build: source paths (X:\\dir\\file.c / .cpp / .h / .pdb),
                                     version-looking strings and "Copyright" lines
    sotapeinfo.py --table FILE...    one line per file: name, size, link date, SHA-256 (for the notes' hash tables)

Needs `pefile`. Read-only. A PE link time is whatever the linker wrote: some linkers (and the later "reproducible" ones) write a hash or nothing, so a date is evidence,
never proof; the Rich header's tool build numbers (a Microsoft linker, 1997: product ids 0x0001..0x0010) tell the toolchain in a way the date cannot.
"""
import datetime
import hashlib
import os
import re
import sys
import warnings

warnings.simplefilter("ignore")
import pefile  # noqa: E402

PATH_RE = re.compile(rb"[A-Za-z]:\\[\x21-\x7e]{3,120}?\.(?:c|cpp|cc|h|hpp|pdb|obj|lib|dll|exe)\b", re.I)
VER_RE = re.compile(rb"(?:[Vv]ersion|[Vv]er\.?|build|Build|BUILD)[ :=]*[0-9][0-9.,a-zA-Z_ -]{0,24}")
COPY_RE = re.compile(rb"Copyright[ \x21-\x7e]{0,80}", re.I)


def info(path, show_strings=True):
    with open(path, "rb") as f:
        data = f.read()
    pe = pefile.PE(data=data, fast_load=False)
    h, o = pe.FILE_HEADER, pe.OPTIONAL_HEADER
    stamp = datetime.datetime.fromtimestamp(h.TimeDateStamp, datetime.timezone.utc)
    out = {
        "file": os.path.basename(path), "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "linked": stamp.strftime("%Y-%m-%d %H:%M:%S"),
        "machine": hex(h.Machine), "dll": bool(h.Characteristics & 0x2000), "linker": "%d.%02d" % (o.MajorLinkerVersion, o.MinorLinkerVersion),
        "os": "%d.%d" % (o.MajorOperatingSystemVersion, o.MinorOperatingSystemVersion), "subsystem": "%d (%d.%d)" % (o.Subsystem, o.MajorSubsystemVersion, o.MinorSubsystemVersion),
        "image_base": hex(o.ImageBase), "entry": hex(o.ImageBase + o.AddressOfEntryPoint), "size_of_image": hex(o.SizeOfImage), "checksum": hex(o.CheckSum),
        "sections": [(s.Name.rstrip(b"\0").decode("latin-1"), hex(s.VirtualAddress), hex(s.Misc_VirtualSize), hex(s.SizeOfRawData)) for s in pe.sections],
        "imports": sum(len(d.imports) for d in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])),
        "import_dlls": [d.dll.decode("latin-1").lower() for d in getattr(pe, "DIRECTORY_ENTRY_IMPORT", [])],
        "exports": len(pe.DIRECTORY_ENTRY_EXPORT.symbols) if hasattr(pe, "DIRECTORY_ENTRY_EXPORT") else 0,
    }
    dbg = []
    for d in getattr(pe, "DIRECTORY_ENTRY_DEBUG", []):
        e = d.struct
        dbg.append((e.Type, datetime.datetime.fromtimestamp(e.TimeDateStamp, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), e.SizeOfData))
    out["debug"] = dbg
    rich = pe.parse_rich_header()
    out["rich"] = ([(v >> 16, v & 0xffff, c) for v, c in zip(rich["values"][0::2], rich["values"][1::2])] if rich else [])
    ver = []
    for fi in getattr(pe, "FileInfo", []) or []:
        for e in fi if isinstance(fi, list) else [fi]:
            if getattr(e, "Key", b"") == b"StringFileInfo":
                for st in e.StringTable:
                    ver += [(k.decode("latin-1"), v.decode("latin-1")) for k, v in st.entries.items()]
    out["version_info"] = ver
    if show_strings:
        out["paths"] = sorted({m.group(0).decode("latin-1") for m in PATH_RE.finditer(data)})
        out["versions"] = sorted({m.group(0).decode("latin-1").strip() for m in VER_RE.finditer(data)})[:20]
        out["copyright"] = sorted({m.group(0).decode("latin-1").strip() for m in COPY_RE.finditer(data)})[:6]
    return out


def main(argv):
    table = "--table" in argv
    files = [a for a in argv[1:] if not a.startswith("--")]
    if not files:
        print(__doc__)
        return 2
    for p in files:
        try:
            r = info(p, show_strings=not table)
        except pefile.PEFormatError as e:
            print("%s: not a PE file (%s)" % (p, e))
            continue
        if table:
            print("%-22s %9d  %s  %s" % (r["file"], r["size"], r["linked"][:10], r["sha256"]))
            continue
        print("== %s  %d bytes  sha256 %s" % (r["file"], r["size"], r["sha256"]))
        print("   linked %s UTC  machine %s %s  linker %s  OS %s  subsystem %s" % (r["linked"], r["machine"], "DLL" if r["dll"] else "EXE", r["linker"], r["os"], r["subsystem"]))
        print("   image base %s  entry %s  size of image %s  checksum %s" % (r["image_base"], r["entry"], r["size_of_image"], r["checksum"]))
        print("   sections: " + "  ".join("%s va %s vsize %s raw %s" % s for s in r["sections"]))
        print("   imports %d from %s; exports %d" % (r["imports"], ", ".join(r["import_dlls"]), r["exports"]))
        if r["debug"]:
            print("   debug directory: " + "; ".join("type %d at %s (%d bytes)" % d for d in r["debug"]))
        if r["rich"]:
            print("   rich header (product id, build, objects): " + " ".join("%d/%d/%d" % t for t in r["rich"]))
        if r["version_info"]:
            print("   version info: " + "; ".join("%s=%s" % kv for kv in r["version_info"]))
        for key in ("paths", "versions", "copyright"):
            if r.get(key):
                print("   %s: %s" % (key, " | ".join(r[key][:12]) + (" ..." if len(r[key]) > 12 else "")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

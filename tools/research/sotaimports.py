#!/usr/bin/env python3
"""
sotaimports.py - the Windows calls a build of the game imports, against what the port implements (src/port) and what the lifter knows the calling convention of
(tools/lift/import_signatures.py).

    sotaimports.py [--old PROGRAM.EXE ...] --new PROGRAM.EXE ... [--port src/port]

For each program: how many imports it has; which are new compared with the programs given as --old; which of them the port does not implement (a call of one stops the run
with "is not implemented", or with PORT_STUB=1 returns 0); which the lifter has no signature for (it refuses a function that calls one). The port finds an import by the
library's name as written in the executable, lower case, so the same function imported from MSVCRT.dll and from MSVCRTD.dll counts as two (`dll_alias` shows the effect).
A table entry is a line of the form {"kernel32.dll", "GetTickCount", fn} in a .c file of src/port, in the tables pe.c searches.
"""
import argparse
import os
import re
import sys

import pefile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lift"))
from import_signatures import signature  # noqa: E402

ENTRY = re.compile(r'\{\s*"([A-Za-z0-9_.]+\.dll|#?\w*)"\s*,\s*"([^"]+)"\s*,\s*[A-Za-z_0-9]+\s*\}')
# the tables pe.c searches (find_api); the host libraries (MAGSND.DLL, MAGVID.DLL) are separate tables and count as provided by name
TABLE_FILES = ("kernel32.c", "kernel32_rt.c", "winsys.c", "process.c", "crt.c", "stdio.c", "user32.c", "controls.c", "filedlg.c", "winhelp.c", "msgbox.c", "menus.c", "gdi.c", "gdi_blit.c", "gdi_text.c", "video.c")


def port_table(port):
    have = set()
    for name in TABLE_FILES:
        path = os.path.join(port, name)
        if not os.path.exists(path):
            continue
        for m in ENTRY.finditer(open(path, encoding="latin-1").read()):
            have.add((m.group(1).lower(), m.group(2)))
    return have


def imports_of(path):
    pe = pefile.PE(path)
    out = []
    for dll in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
        for imp in dll.imports:
            name = imp.name.decode() if imp.name else "#%d" % imp.ordinal
            out.append((dll.dll.decode().lower(), name))
    return out


def alias(dll):
    return "msvcrtd.dll" if dll == "msvcrt.dll" else dll


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--old", nargs="*", default=[])
    ap.add_argument("--new", nargs="+", required=True)
    ap.add_argument("--port", default=os.path.join(HERE, "..", "..", "src", "port"))
    ap.add_argument("--libs", nargs="*", default=[], help="libraries of the game that are lifted or provided by the host (their exports are not Windows calls): names, lower case")
    args = ap.parse_args()
    have = port_table(args.port)
    own = set(args.libs)
    known_old = set()
    for p in args.old:
        known_old.update(imports_of(p))
    print("the port's tables hold %d (library, function) entries" % len(have))
    for p in args.new:
        imps = [i for i in imports_of(p) if i[0] not in own]
        mine = [i for i in imports_of(p) if i[0] in own]
        new = [i for i in imps if i not in known_old and (alias(i[0]), i[1]) not in known_old]
        missing = [i for i in imps if i not in have]
        missing_alias = [i for i in imps if (alias(i[0]), i[1]) not in have]
        nosig = [i for i in imps if signature(*i) is None]
        print("\n%s: %d imports (%d from the game's own libraries: %s)" % (os.path.basename(p), len(imps), len(mine), ", ".join(sorted({d for d, _ in mine})) or "none"))
        print("   not in the port's tables as written: %d;  if msvcrt.dll were an alias of msvcrtd.dll: %d" % (len(missing), len(missing_alias)))
        print("   no lifter signature: %d: %s" % (len(nosig), ", ".join("%s!%s" % i for i in nosig)))
        if args.old:
            print("   not imported by any of the --old programs: %d" % len(new))
            print("      " + ", ".join("%s!%s" % i for i in sorted(new)))
        print("   missing even with the alias (%d): %s" % (len(missing_alias), ", ".join("%s!%s" % i for i in sorted(missing_alias))))


if __name__ == "__main__":
    main()

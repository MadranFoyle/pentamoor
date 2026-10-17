#!/usr/bin/env python3
"""
sotastrings.py - what strings a build has that another lacks, restricted to the technical ones that say how its programs fit together (no game text).

    sotastrings.py OLD.EXE NEW.EXE [--all]

Reads the printable ASCII strings (4 or more characters) of both files and prints, for the strings only the NEW file has (and, as a count, those only the OLD has), the ones of these kinds:
  switch    a command line switch ("/start3,1", "/MTGshell", "-MTG...")
  registry  a registry path or value ("Software\\MicroProse\\...", "SOFTWARE\\...")
  class     a window class or message name ("...Class", "WM_...", "MAGICGAME_...", "SHELLPAGE_...")
  file      a file name or path with a known extension (exe dll txt dat ini csv pic bmp wav avi tga lst scn cnt hlp)
  source    a source path of the build (X:\\...\\*.c)
  other     with --all: the rest of the new strings (this includes game text: the output is long)
Counts of every kind are always printed. A string is the same if the bytes are the same; a string a little changed is both an old-only and a new-only one.
"""
import re
import sys

KINDS = [
    ("switch", re.compile(r"^[ \"]?[/-][A-Za-z][A-Za-z0-9_,]{2,}( .*)?$|\s[/-][A-Za-z][A-Za-z0-9_]*[0-9,]+$")),
    ("registry", re.compile(r"(?i)^(software|system|hkey)[\\/]|\\MicroProse\\|CurrentVersion")),
    ("class", re.compile(r"^(WM_|MAGICGAME|SHELLPAGE|MAGICDECK|Shandalar\w*Class|\w+Class$|\w+_CLASS$|MSG_)")),
    ("source", re.compile(r"(?i)^[a-z]:\\.*\.(c|cpp|h|pdb)$")),
    ("file", re.compile(r"(?i)^[\w\\/.:%$ ~-]{2,80}\.(exe|dll|txt|dat|ini|csv|pic|bmp|wav|avi|tga|lst|scn|cnt|hlp|ttf|isu|url)$")),
]


def strings(path):
    with open(path, "rb") as f:
        data = f.read()
    return {m.group(0).decode("latin-1") for m in re.finditer(rb"[\x20-\x7e]{4,}", data)}


def kind(s):
    for name, rx in KINDS:
        if rx.search(s):
            return name
    return "other"


def main(argv):
    show_all = "--all" in argv
    args = [a for a in argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        print(__doc__)
        return 2
    old, new = strings(args[0]), strings(args[1])
    only_new, only_old = sorted(new - old), sorted(old - new)
    print("%d strings in %s, %d in %s; %d only in the new, %d only in the old" % (len(old), args[0].split("/")[-1], len(new), args[1].split("/")[-1], len(only_new), len(only_old)))
    for label, items in (("new", only_new), ("old", only_old)):
        by = {}
        for s in items:
            by.setdefault(kind(s), []).append(s)
        print("only in the %s, by kind: %s" % (label, ", ".join("%s %d" % (k, len(v)) for k, v in sorted(by.items()))))
        if label == "new":
            for k, v in sorted(by.items()):
                if k == "other" and not show_all:
                    continue
                for s in v[:60]:
                    print("   %-8s %s" % (k, s))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

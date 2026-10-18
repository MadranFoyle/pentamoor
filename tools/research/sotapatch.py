#!/usr/bin/env python3
"""sotapatch.py - moved to tools/install/sotapatch.py (the installer uses it); this is the same command: list, verify and extract the files of SOTAV215.EXE."""
import os
import runpy
import sys

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    target = os.path.join(here, "..", "install", "sotapatch.py")
    sys.path.insert(0, os.path.dirname(target))
    sys.argv[0] = target
    runpy.run_path(target, run_name="__main__")

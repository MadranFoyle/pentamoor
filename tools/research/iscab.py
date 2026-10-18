#!/usr/bin/env python3
"""iscab.py - moved to tools/install/iscab.py (the installer uses it); this is the same command: list and extract an InstallShield 5 cabinet, from a file or "DISC.iso:Setup/data1.cab"."""
import os
import runpy
import sys

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    target = os.path.join(here, "..", "install", "iscab.py")
    sys.path.insert(0, os.path.dirname(target))
    sys.argv[0] = target
    runpy.run_path(target, run_name="__main__")

#!/usr/bin/env python3
"""sotaoverlay.py - moved to tools/install/overlay.py (the installer uses it); this is the same command: copy one extracted install over another the way Windows does, ignoring case."""
import os
import runpy
import sys

if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    target = os.path.join(here, "..", "install", "overlay.py")
    sys.path.insert(0, os.path.dirname(target))
    sys.argv[0] = target
    runpy.run_path(target, run_name="__main__")

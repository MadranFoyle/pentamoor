#!/usr/bin/env python3
"""sim_drive: drive Pentamoor running in the iOS Simulator through its PORT_CONTROL pipe (docs/notes/ios.md).

The pipe is a FIFO in the app's tmp folder (tools/ios/sim.sh ctl-start makes it and launches the app with PORT_CONTROL pointing at it); the app's log is Documents/pentamoor.log. This
wraps tools/soak/pentamoor_ctl.py's Game, which knows the control steps and how to read the window tree back from the log, around that pipe and log instead of a process it starts.

    python3 tools/ios/sim_drive.py shot out.png            # the game's own 1024x768 picture (PIL needed for PNG; else .ppm)
    python3 tools/ios/sim_drive.py click 330 308           # a click at a picture pixel (the control pipe's, not a finger)
    python3 tools/ios/sim_drive.py raw "tdown 1 500 400"   # any control line: tdown/tmove/tup are fingers (touch.h), key, rdown, windows, ...

As a module:  from sim_drive import connect; g = connect(); g.click(x, y); g.shot("a.png")
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "soak"))
from pentamoor_ctl import Game  # noqa: E402

NAME = os.environ.get("SIM_NAME", "Pentamoor iPad Pro")
BUNDLE = os.environ.get("BUNDLE_ID", "org.pentamoor.app." + "".join(c if c.isalnum() else "-" for c in os.environ.get("USER", "user")).lower())


def udid():
    out = subprocess.run(["xcrun", "simctl", "list", "devices", "available"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if line.startswith("    " + NAME + " ("):
            return line.rsplit("(", 2)[1].rstrip(") ").split(")")[0]
    raise SystemExit("no simulator named %r: tools/ios/sim.sh setup" % NAME)


def container():
    return subprocess.run(["xcrun", "simctl", "get_app_container", udid(), BUNDLE, "data"], capture_output=True, text=True, check=True).stdout.strip()


def connect(res="1024x768"):
    c = container()
    g = Game(ROOT, res=res, workdir=os.path.join(c, "tmp"))
    g.ctl_path = os.path.join(c, "tmp", "control")
    g.log_path = os.path.join(c, "Documents", "pentamoor.log")
    g.attach(0)                      # the fifo; the process is the simulator's, so alive() is not asked
    g.alive = lambda: True
    return g


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    g = connect()
    cmd = argv[1]
    if cmd == "shot":
        g.shot(argv[2])
    elif cmd == "click":
        g.click(int(argv[2]), int(argv[3]))
    elif cmd == "raw":
        g.cmd(argv[2])
    else:
        g.cmd(" ".join(argv[1:]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

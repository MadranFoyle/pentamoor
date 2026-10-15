#!/usr/bin/env python3
"""
Tiny command-line driver for the running oracle VM (see oracle_launch.sh).

    oracle_ctl.py shot [name]              save a screenshot to sources/oracle/<name>.png
    oracle_ctl.py click X Y [wait_s]       move the pointer to guest pixel (X, Y), click, wait
    oracle_ctl.py move X Y                 move the pointer only (hover)
    oracle_ctl.py key QCODE [QCODE...]     press keys together (qcodes like ret, esc, f2, a)
    oracle_ctl.py wait SECONDS

Every command ends by saving a screenshot (default name "now") so you can look at the result.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from oracle_qemu import QMP

ORACLE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "sources", "oracle"))


def main(argv):
    q = QMP(os.path.join(ORACLE, "qmp.sock"))
    cmd, args = argv[0], argv[1:]
    name = "now"
    if cmd == "shot":
        name = args[0] if args else "now"
    elif cmd == "click":
        q.mouse_goto(int(args[0]), int(args[1]))
        q.click()
        time.sleep(float(args[2]) if len(args) > 2 else 4)
    elif cmd == "move":
        q.mouse_goto(int(args[0]), int(args[1]))
    elif cmd == "key":
        q.send_key(*args)
        time.sleep(1)
    elif cmd == "wait":
        time.sleep(float(args[0]))
    else:
        raise SystemExit(__doc__)
    path = os.path.abspath(os.path.join(ORACLE, name + ".png"))
    q.screendump(path)
    print(path)


if __name__ == "__main__":
    main(sys.argv[1:])

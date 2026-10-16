#!/usr/bin/env python3
"""
Tiny command-line driver for the running oracle VM (see oracle_launch.sh).

    oracle_ctl.py shot [name]              save a screenshot to sources/oracle/<name>.png
    oracle_ctl.py click X Y [wait_s]       move the pointer to guest pixel (X, Y), click, wait
    oracle_ctl.py hold X Y SECONDS         move the pointer, hold the left button for SECONDS, let go (a long press)
    oracle_ctl.py move X Y                 move the pointer only (hover)
    oracle_ctl.py key QCODE [QCODE...]     press keys together (qcodes like ret, esc, f2, a)
    oracle_ctl.py wait SECONDS
    oracle_ctl.py burst PREFIX N INTERVAL  N screenshots INTERVAL seconds apart: sources/oracle/PREFIX_000.png ... (a movie or an animation seen in time;
                                           the guest is slow, so a clip lasts many times its length)
    oracle_ctl.py monitor 'COMMAND'        a QEMU monitor command: 'savevm tag', 'loadvm tag', 'info block', 'cont' ... (a loadvm leaves the guest stopped on
                                           some runs: 'cont' starts it again)
    oracle_ctl.py status                   running, paused, debug (stopped by a debugger client that never continued it)

Every command ends by saving a screenshot (default name "now") so you can look at the result, except burst, monitor and status.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from oracle_qemu import QMP

ORACLE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "sources", "oracle"))


def main(argv):
    # connect by a relative path from inside the folder: a unix socket's path is limited to about 100 bytes, and a checkout in a deep folder exceeds it
    os.chdir(ORACLE)
    q = QMP("qmp.sock")
    try:
        cmd, args = argv[0], argv[1:]
        name = "now"
        if cmd == "shot":
            name = args[0] if args else "now"
        elif cmd == "click":
            q.mouse_goto(int(args[0]), int(args[1]))
            q.click()
            time.sleep(float(args[2]) if len(args) > 2 else 4)
        elif cmd == "hold":
            q.mouse_goto(int(args[0]), int(args[1]))
            q.mouse_button(True)
            time.sleep(float(args[2]))
            q.mouse_button(False)
            time.sleep(2)
        elif cmd == "move":
            q.mouse_goto(int(args[0]), int(args[1]))
        elif cmd == "key":
            q.send_key(*args)
            time.sleep(1)
        elif cmd == "wait":
            time.sleep(float(args[0]))
        elif cmd == "burst":
            prefix, n, interval = args[0], int(args[1]), float(args[2])
            t0 = time.time()
            for i in range(n):
                q.screendump(os.path.abspath("%s_%03d.png" % (prefix, i)))
                print(i, round(time.time() - t0, 2), flush=True)
                time.sleep(max(0.0, t0 + (i + 1) * interval - time.time()))
            return
        elif cmd == "monitor":
            print(q.cmd("human-monitor-command", **{"command-line": args[0]}))
            return
        elif cmd == "status":
            print(q.status())
            return
        else:
            raise SystemExit(__doc__)
        path = os.path.abspath(name + ".png")
        q.screendump(path)
        print(path)
    finally:
        q.close()


if __name__ == "__main__":
    main(sys.argv[1:])

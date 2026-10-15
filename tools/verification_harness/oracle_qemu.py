#!/usr/bin/env python3
"""
Clients for driving the QEMU-hosted Windows 98 oracle (see docs/ORACLE_VM.md).

- QMP: QEMU's JSON control channel. Used to send keystrokes and take screenshots.
- GDBRemote: a minimal GDB Remote Serial Protocol client for QEMU's gdbstub. Used to set
  breakpoints at addresses from the decompilation and to read registers and memory.

Both are deliberately small and dependency-free. Start the VM with oracle_launch.sh.

Notes on the gdbstub: QEMU pauses the guest when a debugger attaches, and software
breakpoints match on the virtual address (EIP) in whatever process is running. That is fine
for the game's fixed-address code (image base 0x00400000), but memory reads are interpreted
in the page tables of the process that is current when the guest is stopped.
"""

import json
import socket
import time

I386_REGS = ["eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi",
             "eip", "eflags", "cs", "ss", "ds", "es", "fs", "gs"]


class QMP:
    def __init__(self, path, timeout=30):
        self.events = []
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect(path)
        self.f = self.sock.makefile("rw", encoding="utf-8")
        self._read_obj()  # greeting
        self.cmd("qmp_capabilities")

    def _read_obj(self):
        line = self.f.readline()
        if not line:
            raise ConnectionError("QMP connection closed")
        return json.loads(line)

    def cmd(self, execute, **arguments):
        msg = {"execute": execute}
        if arguments:
            msg["arguments"] = arguments
        self.f.write(json.dumps(msg) + "\n")
        self.f.flush()
        while True:
            obj = self._read_obj()
            if "event" in obj:
                self.events.append(obj)
                continue
            if "error" in obj:
                raise RuntimeError(f"QMP {execute}: {obj['error']}")
            return obj.get("return")

    def close(self):
        # The buffered reader holds its own reference to the socket; closing only the socket
        # leaves the connection open, and QEMU serves one QMP client at a time, so the next
        # connection from this process would wait forever for its greeting.
        try:
            self.f.close()
        finally:
            self.sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def status(self):
        return self.cmd("query-status")["status"]

    def send_key(self, *qcodes, hold_ms=100):
        """Press and release the given qcodes together (e.g. "ret", or "alt","f4")."""
        keys = [{"type": "qcode", "data": q} for q in qcodes]
        self.cmd("send-key", keys=keys, **{"hold-time": hold_ms})

    def mouse_move_rel(self, dx, dy):
        events = []
        if dx:
            events.append({"type": "rel", "data": {"axis": "x", "value": int(dx)}})
        if dy:
            events.append({"type": "rel", "data": {"axis": "y", "value": int(dy)}})
        if events:
            self.cmd("input-send-event", events=events)

    def mouse_move(self, dx, dy, step=4, delay=0.004):
        """Relative move in small steps. The guest's PS/2 mouse driver applies pointer
        acceleration to large deltas, so keep steps small to make motion predictable."""
        while dx or dy:
            sx = max(-step, min(step, dx))
            sy = max(-step, min(step, dy))
            self.mouse_move_rel(sx, sy)
            dx -= sx
            dy -= sy
            time.sleep(delay)

    def mouse_goto(self, x, y):
        """Move the guest pointer to (x, y) in guest screen pixels. Measured on the Windows 98
        guest: steps of 2 counts map 1 count -> 1 pixel exactly, while steps >= 4 are doubled by
        pointer acceleration. Homing into the top-left corner first makes this absolute (+-1 px)."""
        self.mouse_move(-1400, -1400, step=8, delay=0.004)   # clamps at the corner
        time.sleep(0.5)
        # The guest drops mouse events that arrive faster than it services them (seen while the
        # game was busy loading), so pace the moves and give it time to settle.
        self.mouse_move(int(x), int(y), step=2, delay=0.012)
        time.sleep(0.4)

    def mouse_button(self, down, button="left"):
        self.cmd("input-send-event", events=[{"type": "btn", "data": {"button": button, "down": down}}])

    def click(self, button="left", hold_s=0.35):
        self.mouse_button(True, button)
        time.sleep(hold_s)
        self.mouse_button(False, button)

    def screendump(self, path, fmt="png"):
        self.cmd("screendump", filename=path, format=fmt)


def _checksum(payload: bytes) -> bytes:
    return b"%02x" % (sum(payload) & 0xFF)


class GDBRemote:
    def __init__(self, host="127.0.0.1", port=1234, timeout=30):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.buf = b""
        self.pending_stops = []   # stop notices that arrived while we expected a command reply

    def _send_packet(self, payload: bytes):
        self.sock.sendall(b"$" + payload + b"#" + _checksum(payload))

    def _recv_byte(self):
        if not self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("gdbstub closed the connection")
            self.buf = chunk
        b, self.buf = self.buf[:1], self.buf[1:]
        return b

    def _recv_packet(self):
        while self._recv_byte() != b"$":
            pass
        data = b""
        while True:
            c = self._recv_byte()
            if c == b"#":
                break
            data += c
        cs = self._recv_byte() + self._recv_byte()
        if cs != _checksum(data):
            self.sock.sendall(b"-")
            raise IOError("bad gdb packet checksum")
        self.sock.sendall(b"+")
        return data

    def request(self, payload: str) -> bytes:
        self._send_packet(payload.encode())
        reply = self._recv_packet()
        # When attaching to a running guest QEMU can interleave a stop notice ("T02...") before
        # the reply to our first command. Keep it for wait_stop() and read the real reply.
        while reply[:1] in (b"T", b"S") and payload[:1] not in ("?", "s", "c", "v"):
            self.pending_stops.append(reply)
            reply = self._recv_packet()
        return reply

    def read_registers(self):
        raw = bytes.fromhex(self.request("g").decode())
        return {name: int.from_bytes(raw[i * 4:i * 4 + 4], "little")
                for i, name in enumerate(I386_REGS) if i * 4 + 4 <= len(raw)}

    def read_memory(self, addr, length):
        out = b""
        while length > 0:
            n = min(length, 0x200)
            reply = self.request(f"m{addr:x},{n:x}")
            if reply.startswith(b"E"):
                raise IOError(f"read of 0x{addr:x} failed: {reply!r}")
            out += bytes.fromhex(reply.decode())
            addr += n
            length -= n
        return out

    def read_cstring(self, addr, limit=260):
        data = self.read_memory(addr, limit)
        return data.split(b"\0")[0]

    def set_breakpoint(self, addr):
        reply = self.request(f"Z0,{addr:x},1")
        if reply != b"OK":
            raise IOError(f"could not set breakpoint at 0x{addr:x}: {reply!r}")

    def clear_breakpoint(self, addr):
        self.request(f"z0,{addr:x},1")

    WATCH_KINDS = {"write": 2, "read": 3, "access": 4}

    def set_watchpoint(self, addr, length=4, kind="write"):
        """Stop the guest when it writes (or reads, or accesses) `length` bytes at `addr`."""
        reply = self.request(f"Z{self.WATCH_KINDS[kind]},{addr:x},{length:x}")
        if reply != b"OK":
            raise IOError(f"could not set {kind} watchpoint at 0x{addr:x}: {reply!r}")

    def clear_watchpoint(self, addr, length=4, kind="write"):
        self.request(f"z{self.WATCH_KINDS[kind]},{addr:x},{length:x}")

    @staticmethod
    def watch_address(stop_reply):
        """Address from a stop reply such as b'T05watch:0070100c;thread:01;', else None."""
        for kind in (b"watch:", b"rwatch:", b"awatch:"):
            i = stop_reply.find(kind)
            if i >= 0:
                return int(stop_reply[i + len(kind):].split(b";")[0], 16)
        return None

    def cont(self):
        """Resume the guest. Use wait_stop() to block until it stops again."""
        self.pending_stops.clear()   # stale notices (e.g. from attaching) no longer apply
        self._send_packet(b"c")

    def step(self):
        self.pending_stops.clear()   # a queued notice describes the stop we are leaving
        self._send_packet(b"s")
        return self.wait_stop()

    def resume(self, breakpoints=()):
        """Continue after a stop. If we are sitting on one of our own breakpoints, step past it
        first (remove, single-step, re-insert), because QEMU's stub re-triggers a breakpoint
        at the current PC immediately when asked to continue; real debuggers do this dance."""
        pc = self.read_registers()["eip"]
        if pc in breakpoints:
            self.clear_breakpoint(pc)
            self.step()
            self.set_breakpoint(pc)
        self.cont()

    def wait_stop(self, timeout=None):
        if self.pending_stops:
            return self.pending_stops.pop(0)
        old = self.sock.gettimeout()
        self.sock.settimeout(timeout)
        try:
            return self._recv_packet()
        finally:
            self.sock.settimeout(old)

    def interrupt(self):
        self.sock.sendall(b"\x03")
        return self.wait_stop(timeout=10)

    def close(self):
        self.sock.close()


def read_ppm(path):
    """Parse a binary P6 PPM (QEMU screendump format=ppm). Returns (width, height, rgb_bytes)."""
    with open(path, "rb") as f:
        data = f.read()
    fields, pos = [], 0
    while len(fields) < 4:
        while data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b"#":
            pos = data.index(b"\n", pos)
            continue
        end = pos
        while not data[end:end + 1].isspace():
            end += 1
        fields.append(data[pos:end])
        pos = end
    magic, w, h, _maxval = fields
    assert magic == b"P6", magic
    return int(w), int(h), data[pos + 1:]


def changed_pixels(a, b):
    """(x, y) of every pixel that differs between two same-size images from read_ppm."""
    (w, h, da), (w2, h2, db) = a, b
    assert (w, h) == (w2, h2)
    out = []
    for i in range(0, w * h * 3, 3):
        if da[i:i + 3] != db[i:i + 3]:
            p = i // 3
            out.append((p % w, p // w))
    return out


def clusters(points, gap=12):
    """Group points into clusters (single linkage on a coarse grid). Returns bounding boxes
    (x0, y0, x1, y1), largest first."""
    cells = {}
    for x, y in points:
        cells.setdefault((x // gap, y // gap), []).append((x, y))
    seen, boxes = set(), []
    for start in cells:
        if start in seen:
            continue
        stack, members = [start], []
        seen.add(start)
        while stack:
            cx, cy = stack.pop()
            members.extend(cells[(cx, cy)])
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    n = (cx + dx, cy + dy)
                    if n in cells and n not in seen:
                        seen.add(n)
                        stack.append(n)
        xs, ys = [m[0] for m in members], [m[1] for m in members]
        boxes.append((min(xs), min(ys), max(xs), max(ys)))
    return sorted(boxes, key=lambda b: -((b[2] - b[0] + 1) * (b[3] - b[1] + 1)))


if __name__ == "__main__":
    # Smoke test against a running oracle: python3 oracle_qemu.py <qmp.sock>
    import sys
    q = QMP(sys.argv[1])
    print("VM status:", q.status())

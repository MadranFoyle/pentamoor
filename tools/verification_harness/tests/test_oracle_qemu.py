import os
import socket
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from oracle_qemu import GDBRemote, QMP, _checksum


def fake_stub(sock, replies, seen):
    """Minimal gdbstub: reads '$payload#cs' packets, acks with '+', answers per `replies`
    (a dict payload-prefix -> reply bytes). Appends each payload to `seen` as it arrives."""
    buf = b""
    try:
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                return
            buf += chunk
            while b"$" in buf and b"#" in buf[buf.index(b"$"):] and len(buf) >= buf.index(b"#") + 3:
                start, end = buf.index(b"$"), buf.index(b"#")
                payload = buf[start + 1:end]
                buf = buf[end + 3:]
                seen.append(payload)
                sock.sendall(b"+")
                for prefix, reply in replies.items():
                    if payload.startswith(prefix):
                        sock.sendall(b"$" + reply + b"#" + _checksum(reply))
                        break
    except OSError:
        return


def make_client(replies):
    a, b = socket.socketpair()
    seen = []
    t = threading.Thread(target=fake_stub, args=(b, replies, seen), daemon=True)
    t.start()
    client = GDBRemote.__new__(GDBRemote)
    client.sock, client.buf, client.pending_stops = a, b"", []
    return client, seen, a, b


class TestQMPClose(unittest.TestCase):
    def test_close_really_closes_the_connection(self):
        import json, tempfile
        path = os.path.join(tempfile.mkdtemp(), "q.sock")
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); srv.bind(path); srv.listen(1)
        peer = {}

        def serve():
            c, _ = srv.accept(); f = c.makefile("rw")
            f.write(json.dumps({"QMP": {}}) + "\n"); f.flush()
            f.readline()                                   # qmp_capabilities
            f.write(json.dumps({"return": {}}) + "\n"); f.flush()
            peer["eof"] = f.readline() == ""               # becomes "" only when the client is gone
        t = threading.Thread(target=serve, daemon=True); t.start()
        q = QMP(path, timeout=5)
        q.close()
        t.join(3)
        self.assertTrue(peer.get("eof"), "server never saw the client disconnect")
        srv.close()


class TestGDBRemote(unittest.TestCase):
    def test_checksum(self):
        self.assertEqual(_checksum(b"OK"), b"9a")
        self.assertEqual(_checksum(b""), b"00")

    def test_read_registers_parses_i386_layout(self):
        regs = b"".join(v.to_bytes(4, "little").hex().encode() for v in range(1, 17))
        client, _, a, b = make_client({b"g": regs})
        r = client.read_registers()
        self.assertEqual(r["eax"], 1)
        self.assertEqual(r["esp"], 5)
        self.assertEqual(r["eip"], 9)
        self.assertEqual(r["gs"], 16)
        a.close(); b.close()

    def test_read_memory_and_cstring(self):
        client, seen, a, b = make_client({b"m": b"433a736f756e645c6b2e77617600ff"})
        self.assertEqual(client.read_cstring(0x1000, 15), b"C:sound\\k.wav")
        self.assertTrue(seen[0].startswith(b"m1000,"))
        a.close(); b.close()

    def test_breakpoint_ok_and_error(self):
        client, seen, a, b = make_client({b"Z0": b"OK"})
        client.set_breakpoint(0x474C7F)
        self.assertEqual(seen[0], b"Z0,474c7f,1")
        a.close(); b.close()
        client, _, a, b = make_client({b"Z0": b"E01"})
        with self.assertRaises(IOError):
            client.set_breakpoint(0x1)
        a.close(); b.close()

    def test_resume_steps_over_own_breakpoint(self):
        regs = (b"00" * 32) + (0x423B57).to_bytes(4, "little").hex().encode() + (b"00" * 28)
        client, seen, a, b = make_client({b"g": regs, b"z0": b"OK", b"s": b"T05", b"Z0": b"OK"})
        client.resume(breakpoints={0x423B57})
        a.shutdown(socket.SHUT_WR)
        # order: read regs, clear bp, single-step, re-insert bp, then continue
        deadline = threading.Event()
        deadline.wait(0.3)
        self.assertEqual(seen[:4], [b"g", b"z0,423b57,1", b"s", b"Z0,423b57,1"])
        self.assertEqual(seen[4], b"c")
        a.close(); b.close()

    def test_stop_notice_before_reply_is_not_an_error(self):
        a, b = socket.socketpair()
        client = GDBRemote.__new__(GDBRemote)
        client.sock, client.buf, client.pending_stops = a, b"", []

        def stub():
            b.recv(4096)                               # the Z0 request
            b.sendall(b"+")
            for reply in (b"T02thread:01;", b"OK"):    # notice first, then the real reply
                b.sendall(b"$" + reply + b"#" + _checksum(reply))
        threading.Thread(target=stub, daemon=True).start()
        client.set_breakpoint(0x474C7F)                # must not raise
        self.assertEqual(client.wait_stop(timeout=1), b"T02thread:01;")
        a.close(); b.close()

    def test_continue_discards_stale_stop_notice(self):
        client, seen, a, b = make_client({})
        client.pending_stops.append(b"T02thread:01;")
        client.cont()
        self.assertEqual(client.pending_stops, [])   # wait_stop must block for the NEXT stop
        a.close(); b.close()

    def test_watchpoint_packets_and_stop_parsing(self):
        client, seen, a, b = make_client({b"Z2": b"OK", b"z2": b"OK"})
        client.set_watchpoint(0x70100C)
        client.clear_watchpoint(0x70100C)
        self.assertEqual(seen[:2], [b"Z2,70100c,4", b"z2,70100c,4"])
        self.assertEqual(GDBRemote.watch_address(b"T05watch:0070100c;thread:01;"), 0x70100C)
        self.assertEqual(GDBRemote.watch_address(b"T05awatch:0068a660;"), 0x68A660)
        self.assertIsNone(GDBRemote.watch_address(b"T05thread:01;"))
        a.close(); b.close()

    def test_resume_does_not_step_when_not_on_breakpoint(self):
        regs = b"00" * 64
        client, seen, a, b = make_client({b"g": regs})
        client.resume(breakpoints={0x423B57})
        threading.Event().wait(0.3)
        self.assertEqual(seen, [b"g", b"c"])
        a.close(); b.close()


if __name__ == "__main__":
    unittest.main()

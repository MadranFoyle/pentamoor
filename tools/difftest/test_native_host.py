"""Tests for the native layer built as a shared library (src/native/native_host.c), without the emulator or any game data.
Run with: python3 -m pytest tools/difftest"""

import ctypes
import os
import shutil
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))

RD = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int)
WR = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
CALL = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int, ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32, ctypes.c_int,
                        ctypes.POINTER(ctypes.c_uint32))

SLOT = 0x006826C0          # DUEL.EXE slot table
MASTER = 0x004FF590        # master card table
SCAN_ORDER_PLAYER, SCAN_ORDER_SLOT = 0x00690320, 0x00681EE0
SCAN_EVENT, SCAN_DEPTH = 0x0068DD04, 0x0068EF48
MASTER_COUNT, QUERY_SAVED = 0x00665ED0, 0x005EF980


@pytest.fixture(scope="module")
def host(tmp_path_factory):
    cc = os.environ.get("CC") or "cc"
    if not shutil.which(cc) or not shutil.which("make"):
        pytest.skip("no C compiler or make")
    out = tmp_path_factory.mktemp("host")
    # without generated handlers: the library has the native functions only
    proc = subprocess.run(["make", "-C", HERE, "host", f"GEN={out}/none", f"BUILD={out}/build"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lib = ctypes.CDLL(str(out / "build" / "libnative_host.dylib"))
    lib.host_native_find.argtypes = [ctypes.c_char_p]
    lib.host_native_try.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
                                    ctypes.POINTER(ctypes.c_uint32)]
    lib.host_native_run.restype = ctypes.c_uint32
    lib.host_native_run.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32]
    lib.host_add_region.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
    # a flat region for everything the tests touch: 0x00400000 - 0x00800000
    base, size = 0x00400000, 0x00400000
    buf = (ctypes.c_uint8 * size)()
    calls = []

    def call(addr, nargs, args, sp, inplace, regs):
        calls.append((addr, [args[i] for i in range(nargs)]))
        return 7

    cbs = (RD(lambda c, a, s: 0), WR(lambda c, a, s, v: None), CALL(call))
    assert lib.host_init(b"DUEL", *cbs) == 0
    lib.host_add_region(base, size, ctypes.addressof(buf))

    class H:
        pass
    h = H()
    h.lib, h.buf, h.base, h.calls, h._keep = lib, buf, base, calls, cbs
    h.w32 = lambda a, v: ctypes.memmove(ctypes.addressof(buf) + a - base, v.to_bytes(4, "little"), 4)
    h.r32 = lambda a: int.from_bytes(bytes(buf[a - base:a - base + 4]), "little")
    return h


def run_try(h, name, *args):
    fid = h.lib.host_native_find(name.encode())
    arr = (ctypes.c_uint32 * max(len(args), 1))(*args)
    out = ctypes.c_uint32()
    status = h.lib.host_native_try(fid, arr, 0x00700000, None, ctypes.byref(out))
    return status, out.value


def test_pure_function_runs_without_a_thread(host):
    host.w32(SLOT + 0x5B20 + 4, 7)           # player 1 slot 0: card 7
    host.w32(SLOT + 0x5B20 + 0xC, 0x30882)   # flags: in play, untapped
    assert run_try(host, "Card_IsInPlay", 1, 0) == (0, 1)
    host.w32(SLOT + 0x5B20 + 4, 0xFFFFFFFF)  # empty slot
    assert run_try(host, "Card_IsInPlay", 1, 0) == (0, 0)
    assert host.calls == []


def test_a_call_out_stops_the_function_and_puts_its_writes_back(host):
    # one card in play whose handler the library cannot run (no generated code): the scan calls out for it
    host.w32(SLOT + 4, 5)
    host.w32(SLOT + 0xC, 2)
    host.w32(SLOT + 0x34, 0)
    host.w32(SCAN_ORDER_PLAYER, 0)
    host.w32(SCAN_ORDER_SLOT, 0)
    host.w32(SCAN_ORDER_PLAYER + 4, 0xFFFFFFFF)
    host.w32(MASTER_COUNT, 100)
    host.w32(MASTER + 5 * 0x34 + 0x10, 0x00401234)   # card 5's handler
    host.w32(SCAN_EVENT, 0x1111)
    host.w32(SCAN_DEPTH, 0)
    status, _ = run_try(host, "Magic_ScanCards", 0x15)
    assert status == 1                      # it had to call the handler: stopped
    assert host.r32(SCAN_EVENT) == 0x1111   # the scan had already stored the event: that is undone
    assert host.r32(SCAN_DEPTH) == 0
    assert host.calls == []                 # nothing was called: the call is made when the function is run again with a thread


def test_run_with_a_call_out_reaches_the_host(host):
    fid = host.lib.host_native_find(b"Magic_ScanCards")
    arr = (ctypes.c_uint32 * 1)(0x15)
    host.lib.host_native_run(fid, arr, 0x00700000)
    assert host.calls and host.calls[0][0] == 0x00401234 and host.calls[0][1][2] == 0x15

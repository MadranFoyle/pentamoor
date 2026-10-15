"""
native_host.py - host the native layer (src/native, built as a shared library by `make -C tools/difftest host`) inside the
emulator, so that the original program runs with some of its functions replaced by native C.

For every native function and, when the library was built with the generated handlers (tools/lift), every lifted card
handler, an intercept is put on the original's entry address (Machine.add_intercept). When the guest reaches it, the
function runs natively instead: its arguments are read off the guest's stack, it reads and writes the guest's memory
through callbacks (the native code addresses memory by the original's own addresses), and its result goes back in EAX.

Native code is plain C that calls the guest's functions that are not native yet by calling a callback. A callback cannot run
guest code from inside the emulator's hook, so a native call runs on its own thread and hands control back and forth
(NativeCall): when the C code calls out, the thread waits and the machine runs the guest function (a Cont, as an import
handler does), then wakes the thread with the result. Only one of the two runs at any moment, so nothing needs locking.
"""
import ctypes
import os
import queue
import struct
import sys
import threading
import time

from unicorn import UcError
from unicorn.x86_const import UC_X86_REG_EAX

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
DEFAULT_LIB = os.path.join(ROOT, "tools", "difftest", "build", "libnative_host.dylib")
MAGIC_LIB = os.path.join(ROOT, "tools", "difftest", "build_magic", "libnative_host.dylib")      # make -C tools/difftest host GEN=../../sources/generated/lift_magic BUILD=build_magic

RD = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int)
WR = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
CALL = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int, ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32,
                        ctypes.c_int, ctypes.POINTER(ctypes.c_uint32))

_current = threading.local()


# What the original's prologue leaves on the stack below the return address that the native function does not: the registers it
# saves (push ebp; push edi; push esi). Later code can read those words as uninitialised locals, and the original game does.
FRAME_RESIDUE = {"Crt_Memcpy": ("ebp", "edi", "esi"), "Crt_Memset": ("edi",)}


def exact_native_names(lib_path=None, shadow=False):
    """The native functions that count their original's instructions exactly (they add to native_cost_extra themselves), and with
    `shadow` those that have a lifted twin too (shadow mode keeps the twin's count). The others are charged an average."""
    lib = ctypes.CDLL(lib_path or os.environ.get("NATIVE_LIB") or DEFAULT_LIB)
    lib.host_native_name.restype = ctypes.c_char_p
    lib.host_native_name.argtypes = [ctypes.c_int]
    lib.host_native_self_charging.argtypes = [ctypes.c_int]
    lib.host_native_has_twin.argtypes = [ctypes.c_int]
    return [lib.host_native_name(i).decode() for i in range(lib.host_native_count())
            if lib.host_native_self_charging(i) or (shadow and lib.host_native_has_twin(i))]


class Worker(threading.Thread):
    """A thread that runs native calls one at a time. A call that is waiting for the guest keeps its worker, so a call made
    meanwhile (the guest function ran a native one) gets another."""

    def __init__(self, pool):
        super().__init__(daemon=True)
        self.pool, self.jobs = pool, queue.SimpleQueue()
        self.start()

    def run(self):
        while True:
            call, run = self.jobs.get()
            _current.call = call
            try:
                call.req.put(("done", run()))
            except BaseException as e:  # noqa: BLE001 - handed to the machine's thread
                call.req.put(("error", e))
            self.pool.append(self)


class Ledger:
    """What a replaced function owes the clock while it runs across guest calls: the instructions since the last settlement, which
    the guest's clock must include when the guest function it calls reads it (a loop that polls GetTickCount, sleeps, and so ends a slice)."""

    def __init__(self, host):
        self.host = host
        self.conts = 0
        self.rebase_to_now()

    def rebase_to_now(self):
        self.before = self.host._counters()
        self.inner = self.host.charged_total
        self.host.mark_clock_window()

    def settle(self):
        self.host.charge_since(self.before, self.inner, 1 if self.conts else 0)   # the trap the last guest call returned to counted one

    def rebase(self):       # after the guest call: what ran meanwhile (hosted functions it called) has paid for itself
        self.conts += 1
        self.rebase_to_now()

    def finish(self):
        self.host.charge_since(self.before, self.inner, 1 if self.conts else 0)


class NativeCall:
    """A native function running on a worker thread, which stops whenever it calls out to the guest."""
    pool = []

    def __init__(self, run):
        self.req, self.resp = queue.SimpleQueue(), queue.SimpleQueue()
        self.run = run

    def start(self):
        worker = self.pool.pop() if self.pool else Worker(self.pool)
        worker.jobs.put((self, self.run))
        return self.req.get()

    def resume(self, value):
        self.resp.put(value)
        return self.req.get()


class NativeHost:
    def __init__(self, machine, lib_path=None):
        self.m = machine
        path = lib_path or os.environ.get("NATIVE_LIB") or (MAGIC_LIB if machine.exe_guest_path.lower().endswith("\\magic.exe") else DEFAULT_LIB)
        if not os.path.exists(path):
            sys.exit(f"native library not found: {path} (make -C tools/difftest host)")
        self.lib = ctypes.CDLL(path)
        lib = self.lib
        lib.host_init.argtypes = [ctypes.c_char_p, RD, WR, CALL]
        lib.host_native_count.restype = ctypes.c_int
        lib.host_native_name.restype = ctypes.c_char_p
        lib.host_native_name.argtypes = [ctypes.c_int]
        lib.host_native_entry.restype = ctypes.c_uint32
        lib.host_native_entry.argtypes = [ctypes.c_int]
        lib.host_set_enabled.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_int]
        lib.host_native_nargs.argtypes = [ctypes.c_int]
        lib.host_native_ret_bits.argtypes = [ctypes.c_int]
        lib.host_native_self_charging.argtypes = [ctypes.c_int]
        lib.host_native_run.restype = ctypes.c_uint32
        lib.host_native_run.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32]
        lib.host_counters.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64)]
        lib.host_lifted_count.restype = ctypes.c_int
        lib.host_lifted_entry.restype = ctypes.c_uint32
        lib.host_lifted_entry.argtypes = [ctypes.c_int]
        lib.host_lifted_name.restype = ctypes.c_char_p
        lib.host_lifted_name.argtypes = [ctypes.c_int]
        lib.host_lifted_run.restype = ctypes.c_uint32
        lib.host_lifted_run.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
        lib.host_native_try.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
                                        ctypes.POINTER(ctypes.c_uint32)]
        lib.host_native_has_twin.argtypes = [ctypes.c_int]
        lib.host_set_shadow.argtypes = [ctypes.c_int]
        lib.host_shadow_stats.argtypes = [ctypes.POINTER(ctypes.c_uint64)] * 3
        lib.host_lifted_try.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)]
        self.escalated = {}   # name -> calls that had to be run again with a thread
        self.native_cost = None
        self.seconds = {"try": 0.0, "thread": 0.0}   # host time spent in each way of running a call (for tuning)
        self.replaced = set()   # entry addresses install() replaced
        self.shadow = False     # see shadow()
        self.last_conts = 0
        self.clock_modelled = False
        self.charged_total = 0.0
        self.native_cost = []
        self.thread_only = {int(x, 16) for x in os.environ.get("NATIVE_THREAD_ONLY", "501f50").split(",") if x}   # functions that call out too often to try first (the search driver)
        self.cost_mode = None   # None, "owed" or "burn": see load_costs
        self.faults = 0
        self.runs = {}   # name -> times run natively
        self.callers = {} if os.environ.get("HOST_CALLERS") else None   # HOST_CALLERS=1: (function, guest return address) -> calls

        def read(ctx, addr, size):
            try:
                return int.from_bytes(self.m.uc.mem_read(addr, size), "little")
            except UcError:
                self.faults += 1
                return 0

        def write(ctx, addr, size, value):
            try:
                self.m.uc.mem_write(addr, (value & ((1 << (8 * size)) - 1)).to_bytes(size, "little"))
            except UcError:
                self.faults += 1

        def call(addr, nargs, args, sp, inplace, regs):
            c = _current.call
            c.req.put(("call", addr, [args[i] for i in range(nargs)], sp, bool(inplace),
                       [regs[i] for i in range(7)] if regs else None))
            return c.resp.get()

        self._cb = (RD(read), WR(write), CALL(call))   # keep the callbacks alive
        program = b"MAGIC" if self.m.exe_guest_path.lower().endswith("\\magic.exe") else b"DUEL"      # the layout (addresses) of the program being run
        self.program = program.decode()
        if lib.host_init(program, *self._cb) != 0:
            sys.exit("native_host: host_init failed")
        lib.host_lifted_program.restype = ctypes.c_char_p
        lib.host_set_builtin_import.argtypes = [ctypes.c_uint32, ctypes.c_int]
        lib.host_set_rand_cell.argtypes = [ctypes.c_uint32]
        self.has_clock_cells = all(hasattr(lib, f) for f in ("host_set_clock_cells", "host_set_clock_model", "host_set_clock_window", "host_set_native_costs", "host_mark_charge"))      # (a library built before the clock builtins does not)
        if self.has_clock_cells:
            lib.host_set_clock_cells.argtypes = [ctypes.c_uint32] * 3
            lib.host_set_clock_model.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_double]
            lib.host_set_clock_window.argtypes = [ctypes.c_uint64]
            lib.host_set_native_costs.argtypes = [ctypes.POINTER(ctypes.c_double)]
        lib.host_builtin_calls.restype = ctypes.c_uint64
        lib.host_set_builtin_burn.argtypes = [ctypes.c_uint32]
        self._builtin_seen = 0
        lib.host_add_region.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
        from . import crt  # noqa: PLC0415
        cstate = crt._state(self.m)
        self.rand_cell = self.m.alloc(4)                       # the C runtime's rand seed, in guest memory so that C and Python share it
        self.m.w32(self.rand_cell, cstate["seed"])
        cstate["rand_cell"] = self.rand_cell
        for base, size, host, _buf in self.m.regions:   # the guest's memory is host memory: no callback per access
            lib.host_add_region(base, size, host)
        lib.host_set_rand_cell(self.rand_cell)
        lib.host_set_builtin_burn(int(os.environ.get("NATIVE_BUILTIN_BURN", "1")))
        if self.has_clock_cells:
            self.m.clock_cells = tuple(self.m.alloc(4) for _ in range(4))   # GetTickCount, the timer driver's count, its handle, how often they were published: guest memory C reads
            self.m.publish_clock()
            lib.host_set_clock_cells(*self.m.clock_cells)
        if self.program == "MAGIC" and not os.environ.get("NATIVE_NO_BUILTINS"):          # (NATIVE_NO_BUILTINS=1: they go out to the emulator, as in the original, so that an exact run can be compared call by call)
            # C runtime imports that lifted code runs in C (lift_bridge.c) rather than calling out
            for slot, (dll, name) in self.m.iat_names.items():
                kind = (dict(rand=1, memcpy=2, memset=3, strlen=6, strcpy=7, strcat=8, abs=9, strcmp=10).get(name)
                        if dll.lower() == "msvcrtd.dll" else None)
                if dll.lower() == "kernel32.dll" and self.has_clock_cells:
                    kind = {"GetTickCount": 4, "DeviceIoControl": 5}.get(name)
                if kind:
                    lib.host_set_builtin_import(slot, kind)
                    # the code reaches most of them through a one-instruction thunk (`jmp [slot]`) that it calls instead
                    jmp = b"\xff\x25" + struct.pack("<I", slot)
                    code = bytes(self.m.rd(0x401000, 0x11314c))
                    at = code.find(jmp)
                    while at >= 0:
                        lib.host_set_builtin_import(0x401000 + at, kind)
                        at = code.find(jmp, at + 1)

    # ---- what the original functions look like -----------------------------------------------------------------
    def _cleanup(self, entry):
        """Bytes the original function pops when it returns (`ret imm16`): 0 for a cdecl function."""
        sys.path.insert(0, os.path.join(ROOT, "tools", "lift"))
        from x86lift import Lifter, Unsupported  # noqa: PLC0415

        def getbytes(va, n):
            return bytes(self.m.uc.mem_read(va, min(n, 0x2000)))
        try:
            return Lifter().ret_cleanup(getbytes, entry, frozenset())
        except Unsupported:
            return 0

    def _run_in_thread(self, run, ledger=None):
        """A generator for Machine.add_intercept: run `run()` (a call into the library) with guest calls serviced. `ledger` (a
        Ledger) settles the instructions the replaced code has run before each guest call, so that what the guest reads from the clock
        in that call (and the slice it may end) is the original's."""
        call = NativeCall(run)
        msg = call.start()
        conts = 0   # the emulator counts the trap each guest call returns to as an instruction; the original has none
        outer = self.m.pin
        try:
            while msg[0] == "call":
                conts += 1
                self.m.pin = self.m.cur   # the C side's state (stack top, registers) is global: no other guest thread may run hosted code meanwhile
                target = msg[1]
                if target in self.m.iat_slots:   # lifted code that calls an import calls through its slot (`call [slot]`)
                    target = self.m.r32(target)
                if self.callers is not None:   # HOST_CALLERS=1: which guest functions the hosted code calls out to
                    k = ("callout", target)
                    self.callers[k] = self.callers.get(k, 0) + 1
                if ledger:
                    ledger.settle()
                r = yield self.m.call_guest(target, msg[2], sp=msg[3], inplace=msg[4], regs=msg[5])
                if ledger:
                    ledger.rebase()
                msg = call.resume(r)
        finally:
            self.m.pin = outer
        if msg[0] == "error":
            raise msg[1]
        self.last_conts = conts   # read by the caller at once, before anything else can run
        return msg[1]

    def _native(self, fid, name, nargs, bits):
        lib = self.lib
        from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EBX, UC_X86_REG_EBP, UC_X86_REG_ESI, UC_X86_REG_EDI  # noqa: PLC0415
        regnames = (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EBX, UC_X86_REG_EBP, UC_X86_REG_ESI, UC_X86_REG_EDI)
        entry = lib.host_native_entry(fid)

        def handler(m, esp):
            args = [m.r32(esp + 4 + 4 * i) for i in range(nargs)]
            arr = (ctypes.c_uint32 * max(nargs, 1))(*args)
            regs = (ctypes.c_uint32 * 7)(*(m.uc.reg_read(r) for r in regnames))
            self.runs[name] = self.runs.get(name, 0) + 1
            if self.callers is not None:
                k = (name, m.r32(esp))
                self.callers[k] = self.callers.get(k, 0) + 1
            out = ctypes.c_uint32()
            depth0 = m.r32(0x6FE3F8) if name == "Magic_ScanCards" and os.environ.get("SCAN_DEBUG") else 0
            if name == "Magic_ScanCards" and os.environ.get("SCAN_DEBUG"):
                ring = self.__dict__.setdefault("scan_ring", __import__("collections").deque(maxlen=60))
                ring.append(f"enter t{m.cur.tid} depth {depth0} event {args[0]:#x} esp {esp:#x} vt {m.vt:.3f}")
                if depth0 >= 8:
                    print("   [scan] depth about to pass 9; the last scan calls:\n      " + "\n      ".join(ring), flush=True)
                    print("   [scan] threads: " + "; ".join(f"t{t.tid} {t.state}" for t in m.threads), flush=True)
            charging = self.cost_mode is not None
            inner = self.charged_total if charging else 0.0
            t0 = time.perf_counter()
            before = self._counters() if charging else None
            done = lib.host_native_try(fid, arr, esp, regs, ctypes.byref(out)) == 0
            self.seconds["try"] += time.perf_counter() - t0
            twin = self.shadow and lib.host_native_has_twin(fid)
            if done:
                ret = out.value
            else:   # it needs the guest: put back what it wrote and run it again where it can wait for it
                self.escalated[name] = self.escalated.get(name, 0) + 1
                t0 = time.perf_counter()
                ledger = Ledger(self) if charging else None
                if twin:   # in shadow mode what runs is the original's machine code, not the native function
                    ret = yield from self._run_in_thread(lambda: lib.host_lifted_run(entry, esp, regs), ledger)
                    for r, v in zip(regnames[3:], regs[3:]):
                        m.uc.reg_write(r, v)
                else:
                    ret = yield from self._run_in_thread(lambda: lib.host_native_run(fid, arr, esp), ledger)
                self.seconds["thread"] += time.perf_counter() - t0
            if charging:
                if done:
                    self.charge_since(before, inner)
                else:
                    ledger.finish()
            self._sync_builtin_calls()
            if name == "Magic_ScanCards" and os.environ.get("SCAN_DEBUG"):   # SCAN_DEBUG=1: the scan depth must come back as it went in
                d1 = m.r32(0x6FE3F8)
                self.scan_ring.append(f"leave t{m.cur.tid} depth {depth0} -> {d1} {'tried' if done else 'thread'}")
                if d1 != depth0:
                    print(f"   [scan] depth {depth0} -> {d1} after event {args[0]:#x}, {'tried' if done else 'on a thread'}, t{m.cur.tid}", flush=True)
            if name in FRAME_RESIDUE and not twin and not (name == "Crt_Memset" and args[2] == 0):
                from unicorn.x86_const import UC_X86_REG_EBP, UC_X86_REG_EDI, UC_X86_REG_ESI  # noqa: PLC0415
                rn = {"ebp": UC_X86_REG_EBP, "edi": UC_X86_REG_EDI, "esi": UC_X86_REG_ESI}
                for k, reg in enumerate(FRAME_RESIDUE[name]):
                    m.w32(esp - 4 * (k + 1), m.uc.reg_read(rn[reg]))
            if bits == 0 and not twin:
                return m.uc.reg_read(UC_X86_REG_EAX)   # a void function: EAX is whatever it was
            return ret & 0xFF if bits == 8 else ret
        return handler

    def shadow_mode(self, check=False):
        """Run every native function that has a lifted twin both ways on every call and compare (native_host.c, shadow mode); what the
        guest keeps is the twin's result, so the run is the original's. Needs a library built with the twins (gen_handlers.py)."""
        self.shadow = True
        self.lib.host_set_shadow(2 if check else 1)

    def shadow_report(self):
        c = [ctypes.c_uint64() for _ in range(3)]
        self.lib.host_shadow_stats(*[ctypes.byref(x) for x in c])
        return c[0].value, c[1].value, c[2].value

    def log_calls(self, addrs, path, hosted=False, nargs=4):
        """Write the arguments and the result of every call of the functions at `addrs`, to compare a run on the original with
        a hosted one (`--native-log`): in the original they are seen by hooks; hosted, the handler of a replaced function
        writes the same line."""
        from unicorn import UC_HOOK_CODE  # noqa: PLC0415
        from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ESP  # noqa: PLC0415
        self.logf = open(path, "w", buffering=1)
        self.log_addrs = set(addrs)
        self.log_nargs = nargs
        # Calls made from inside a lifted function are not seen when hosted (the lifted code calls the lifted callee itself), so
        # they are left out of the original's log too: only calls from outside the lifted functions' own code.
        spec_path = os.environ.get("NATIVE_LOG_SPEC") or os.path.join(ROOT, "sources", "generated", "lift", "handler_spec.json")   # the lifted functions' extents (MAGIC: the spec of the library's generated code)
        extents = []
        if os.path.exists(spec_path):
            import json  # noqa: PLC0415
            extents = [(int(e["extent"][0], 16), int(e["extent"][1], 16)) for e in json.load(open(spec_path)) if e.get("lifted")]

        # The return of each call is caught with one trap, not a hook per call (Unicorn slows down with every hook added): the entry hook
        # swaps the return address for the trap and remembers the real one, per thread.
        from winemu.machine import STUB_BASE, STUB_SIZE  # noqa: PLC0415
        from unicorn.x86_const import UC_X86_REG_EIP  # noqa: PLC0415
        trap = STUB_BASE + STUB_SIZE - 0x700
        pending = {}

        def entry_hook(uc, address, size, user):
            if hosted and address in self.replaced:   # a replaced function logs from its own handler
                return
            esp = uc.reg_read(UC_X86_REG_ESP)
            ret = int.from_bytes(uc.mem_read(esp, 4), "little")
            if any(lo <= ret < hi for lo, hi in extents):
                return
            args = [int.from_bytes(uc.mem_read(esp + 4 + 4 * i, 4), "little") for i in range(self.log_nargs)]
            if os.environ.get("NATIVE_LOG_ENTRY"):
                self.logf.write("enter %08x %s from %08x vt %.6f\n" % (address, " ".join("%08x" % a for a in args), ret, self.m.vt))
            pending.setdefault(self.m.cur.tid, []).append((address, args, ret))
            uc.mem_write(esp, trap.to_bytes(4, "little"))

        def trap_hook(uc, address, size, user):
            stack = pending.get(self.m.cur.tid)
            if not stack:
                return
            addr, args, ret = stack.pop()
            self.log_line(addr, args, uc.reg_read(UC_X86_REG_EAX), ret)
            uc.reg_write(UC_X86_REG_EIP, ret)
        for a in addrs:
            self.m.uc.hook_add(UC_HOOK_CODE, entry_hook, begin=a, end=a)
        self.m.uc.hook_add(UC_HOOK_CODE, trap_hook, begin=trap, end=trap)

    def log_line(self, addr, args, ret, caller=None):
        self.logf.write("%08x %s -> %08x%s\n" % (addr, " ".join("%08x" % a for a in args), ret & 0xFFFFFFFF,
                                                   " from %08x" % caller if caller else ""))

    def _lifted(self, entry, name):
        lib = self.lib
        from unicorn.x86_const import UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EBX, UC_X86_REG_EBP, UC_X86_REG_ESI, UC_X86_REG_EDI  # noqa: PLC0415
        regnames = (UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EBX, UC_X86_REG_EBP, UC_X86_REG_ESI, UC_X86_REG_EDI)

        def handler(m, esp):
            self.runs[name] = self.runs.get(name, 0) + 1
            if self.callers is not None:
                k = (name, m.r32(esp))
                self.callers[k] = self.callers.get(k, 0) + 1
            # the function starts with the registers the guest has: what it pushes to save them is then what the original pushed
            regs = (ctypes.c_uint32 * 7)(*(m.uc.reg_read(r) for r in regnames))

            def restore_registers():
                # a call out to the original is made with the lifted code's registers (so that its saves are the original's);
                # the lifted code restores its own at its end, but the guest's must be put back too
                for r, v in zip(regnames[3:], regs[3:]):
                    m.uc.reg_write(r, v)
            if getattr(self, "log_addrs", None) and entry in self.log_addrs:
                args = [m.r32(esp + 4 + 4 * i) for i in range(self.log_nargs)]
                out0 = ctypes.c_uint32()
                if lib.host_lifted_try(entry, esp, regs, ctypes.byref(out0)) == 0:
                    self.log_line(entry, args, out0.value, m.r32(esp))
                    restore_registers()
                    return out0.value
            out = ctypes.c_uint32()
            charging = self.cost_mode is not None
            inner = self.charged_total if charging else 0.0
            before = self._counters() if charging else None
            if entry not in self.thread_only and lib.host_lifted_try(entry, esp, regs, ctypes.byref(out)) == 0:
                if charging:
                    self.charge_since(before, inner)
                self._sync_builtin_calls()
                return out.value        # no call went out to the guest, so the emulator's registers were never touched: nothing to put back
            self.escalated[name] = self.escalated.get(name, 0) + 1
            ledger = Ledger(self) if charging or self.clock_modelled else None
            ret = yield from self._run_in_thread(lambda: lib.host_lifted_run(entry, esp, regs), ledger)
            if ledger and charging:
                ledger.finish()
            restore_registers()
            self._sync_builtin_calls()
            return ret
        return handler

    # ---- virtual time ------------------------------------------------------------------------------------------
    # The machine charges the guest's clock for the guest's own instructions (a slice that runs to its limit costs the limit
    # divided by the speed of the emulated machine) and for the import calls it makes. A replaced function runs no guest
    # instructions, so without a charge time would pass more slowly for the guest, and a time-boxed search (the AI's) would
    # do several times the work in the same virtual seconds. The work is known: lifted code executes the original's
    # instructions one for one and counts them (lift_icount), and for each hand-written native function the original's
    # own instructions per call are measured by `calibrate` on the original. After each replaced call the instructions it
    # would have taken are owed to the machine (`Machine.owed`), which ends slices sooner and charges them.
    def calibrate(self, path):
        """Count, on the original, the instructions each native function executes in its own code per call (not those of the
        functions it calls), and write them to `path` when the run ends (`finish_calibration`)."""
        from unicorn import UC_HOOK_BLOCK, UC_HOOK_CODE  # noqa: PLC0415
        import bisect  # noqa: PLC0415
        sys.path.insert(0, os.path.join(ROOT, "tools", "lift"))
        from x86lift import Lifter  # noqa: PLC0415

        def getbytes(va, n):
            return bytes(self.m.uc.mem_read(va, min(n, 0x4000)))
        self.cal = {}
        self.cal_path = path
        for fid in range(self.lib.host_native_count()):
            name = self.lib.host_native_name(fid).decode()
            entry = self.lib.host_native_entry(fid)
            if not entry or self.lib.host_native_self_charging(fid):
                continue
            lifter = Lifter()
            lifter.strict_tables = False
            insns, _ = lifter.explore(getbytes, entry, frozenset(), window=0x3000)
            addrs = sorted(insns)
            rec = self.cal[name] = {"entries": 0, "instructions": 0}

            def on_entry(uc, address, size, user, rec=rec):
                rec["entries"] += 1

            def on_block(uc, address, size, user, rec=rec, addrs=addrs):
                rec["instructions"] += bisect.bisect_left(addrs, address + size) - bisect.bisect_left(addrs, address)
            self.m.uc.hook_add(UC_HOOK_CODE, on_entry, begin=entry, end=entry)
            self.m.uc.hook_add(UC_HOOK_BLOCK, on_block, begin=addrs[0], end=addrs[-1])
        return len(self.cal)

    def finish_calibration(self):
        import json  # noqa: PLC0415
        out = {n: (c["instructions"] / c["entries"] if c["entries"] else None) for n, c in self.cal.items()}
        json.dump({"instructions_per_call": out, "entries": {n: c["entries"] for n, c in self.cal.items()}},
                  open(self.cal_path, "w"), indent=1, sort_keys=True)
        return out

    def load_costs(self, path, exact=False):
        import json  # noqa: PLC0415
        table = json.load(open(path))["instructions_per_call"] if path else {}
        # a function that adds its own cost as it runs (native_cost_extra: a copy costs what its size makes it) is not charged per call
        self.native_cost = [0.0 if self.lib.host_native_self_charging(i)
                            else (table.get(self.lib.host_native_name(i).decode()) or 0.0) for i in range(self.lib.host_native_count())]
        self.cost_mode = "burn" if exact else "owed"
        self.m.charging = not exact   # "owed": slices are run in pieces; "burn": nothing special, the instructions really run
        self.charged_total = 0.0
        self.set_clock_model()

    def mark_clock_window(self):
        """Tell the C side where the clock stands: hosted code that polls it sees time pass once the work since now reaches what is left
        of the running slice (the original's slice would have ended there, and the clock with it)."""
        if self.has_clock_cells and self.clock_modelled:
            m = self.m
            self.lib.host_mark_charge()
            self.lib.host_set_clock_window(max(m.slice_limit - m.slice_exec - m.owed - m.burn, 0))

    def set_clock_model(self):
        """How hosted code that reads the clock sees it advance (lift_bridge.h): by charged work in a run that charges, by the real
        clock in a live one, not at all (the guest's own, between slices) when neither is known."""
        if not self.has_clock_cells:
            return
        mode = 1 if self.cost_mode or not self.m.state.get("clock") else 2
        self.lib.host_set_clock_model(self.m.clock_cells[3], mode, float(self.m.ips))
        n = self.lib.host_native_count()
        costs = (ctypes.c_double * n)(*(self.native_cost + [0.0] * n)[:n])
        self.lib.host_set_native_costs(costs)
        self.clock_modelled = True

    def _counters(self):
        n = self.lib.host_native_count()
        arr, ic = (ctypes.c_uint64 * n)(), ctypes.c_uint64()
        self.lib.host_counters(arr, ctypes.byref(ic))
        return list(arr), ic.value

    def charge_since(self, before, inner_before, conts=0):
        """Owe the machine what the original would have executed for the work done since `before`, except what calls made
        meanwhile (a guest function that ran a native one) already paid."""
        if self.cost_mode is None:
            return
        entries, ic = self._counters()
        total = float(ic - before[1]) + sum((e - b) * c for e, b, c in zip(entries, before[0], self.native_cost))
        own = max(total - (self.charged_total - inner_before), 0.0)
        self.charged_total += own
        if self.cost_mode == "burn":
            self.m.burn += max(int(own) - conts, 0)
        else:
            self.m.owed += int(own)

    def count_only(self):
        """Count how often the guest enters each function the native layer could replace, leaving the original running (to
        compare with a run that replaces them: the same calls should happen in the same virtual time)."""
        from unicorn import UC_HOOK_CODE  # noqa: PLC0415
        names = {}
        for fid in range(self.lib.host_native_count()):
            if self.lib.host_native_entry(fid):
                names[self.lib.host_native_entry(fid)] = self.lib.host_native_name(fid).decode()
        for i in range(self.lib.host_lifted_count()):
            names[self.lib.host_lifted_entry(i)] = self.lib.host_lifted_name(i).decode()

        def hit(uc, address, size, user):
            n = names[address]
            self.runs[n] = self.runs.get(n, 0) + 1
        mode = os.environ.get("COUNT_MODE", "count")
        for a, n in names.items():
            if mode == "natives" and not n.startswith(("Magic_", "Card_", "Ai_")):
                continue
            self.m.uc.hook_add(UC_HOOK_CODE, (lambda *x: None) if mode == "nop" else hit, begin=a, end=a)

    def _sync_builtin_calls(self):
        """Import calls that ran in C count as calls of the machine (it charges the clock for each)."""
        n = self.lib.host_builtin_calls()
        if n != self._builtin_seen:
            self.m.calls += n - self._builtin_seen
            self._builtin_seen = n

    def _lifted_fits(self, entry):
        """Whether a lifted function belongs to the program being run. The generated handlers are one program's machine code at its
        addresses: for MAGIC.EXE the library is built from `gen_handlers.py --program magic --no-handlers`, whose lifted functions are
        the native functions' twins, so a lifted function there must be a native function's entry (a library built for DUEL.EXE is
        refused rather than run on the wrong program)."""
        if self.program == "DUEL":
            return True
        if self.lib.host_lifted_program() == b"MAGIC":                         # a library generated from MAGIC.EXE: all of it is MAGIC's
            return True
        if not hasattr(self, "_native_entries"):
            self._native_entries = {self.lib.host_native_entry(f) for f in range(self.lib.host_native_count())} - {0}
        return entry in self._native_entries

    def install(self, only=None, skip=(), handlers=True):
        """Intercept the original's native functions (and lifted handlers). `only` (a set of names) restricts it."""
        count = 0
        # What this run does not replace is the original's: native and lifted code that calls it must go out to the guest
        for fid in range(self.lib.host_native_count()):
            name = self.lib.host_native_name(fid).decode()
            if ((only is not None and name not in only) or name in skip) and self.lib.host_native_entry(fid):
                self.lib.host_set_enabled(self.lib.host_native_entry(fid), 0, 0)
        for i in range(self.lib.host_lifted_count()):
            name = self.lib.host_lifted_name(i).decode()
            if (only is not None and name not in only) or name in skip or not handlers or not self._lifted_fits(self.lib.host_lifted_entry(i)):
                self.lib.host_set_enabled(self.lib.host_lifted_entry(i), 0, 1)
        for fid in range(self.lib.host_native_count()):
            name = self.lib.host_native_name(fid).decode()
            if (only is not None and name not in only) or name in skip:
                continue
            entry = self.lib.host_native_entry(fid)
            if not entry:   # the program has no such function
                continue
            self.replaced.add(entry)
            self.m.add_intercept(entry, self._native(fid, name, self.lib.host_native_nargs(fid),
                                                    self.lib.host_native_ret_bits(fid)), self._cleanup(entry))
            count += 1
        if handlers:
            for i in range(self.lib.host_lifted_count()):
                name = self.lib.host_lifted_name(i).decode()
                if (only is not None and name not in only) or name in skip:
                    continue
                entry = self.lib.host_lifted_entry(i)
                if not self._lifted_fits(entry):
                    continue
                if entry in self.replaced:   # a native function stands in for it (its lifted twin is for shadow mode)
                    continue
                self.replaced.add(entry)
                self.m.add_intercept(entry, self._lifted(entry, name), self._cleanup(entry))
                count += 1
        self.set_clock_model()
        return count

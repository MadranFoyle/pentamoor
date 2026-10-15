"""
The emulated machine: a Win32 process image running under Unicorn (x86-32), with every imported
function answered by Python.

How imports work: each import's IAT slot points at a 16-byte stub in a trap area. A code hook fires when
execution reaches a stub, looks up the Python handler, reads its arguments off the emulated stack, and
sets EAX, ESP and EIP as if the function had returned. Handlers registered with `@api(dll, name, argc)`
(stdcall) or `@crt(name)` (cdecl) live in the sibling modules.

Calling back into emulated code (a window procedure, a timer callback) from inside a handler is done
with a continuation, not a nested emulator run: the handler returns `m.call_guest(fn, args, then)`; the
machine lays a stack frame for `fn` under the current one whose return address is a trap, and when the
guest function returns to that trap `then(eax)` produces the result of the original import.
"""
import ctypes
import inspect
import itertools
import mmap
import os
import re
import collections
import struct
import time as _time
import zlib

import pefile
from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_PROT_ALL, UC_HOOK_CODE, UC_HOOK_MEM_UNMAPPED, UC_HOOK_MEM_WRITE, UcError
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_ESP, UC_X86_REG_EIP, UC_X86_REG_FS,
                               UC_X86_REG_GDTR, UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS,
                               UC_X86_REG_CS, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ESI,
                               UC_X86_REG_EDI, UC_X86_REG_ECX, UC_X86_REG_EDX)

STUB_BASE = 0x70000000
STUB_SIZE = 0x40000
EXIT_TRAP = STUB_BASE + STUB_SIZE - 0x900          # a thread function returns here: the thread is finished
CONT_TRAP = STUB_BASE + STUB_SIZE - 0x800           # guest functions called from a handler return here
# Where a replaced function spends the instructions its original would have run (`Machine.burn`): `jecxz done; loop $; done:
# jmp edx`. Outside the range the code hook watches, or each iteration would call into Python.
BURN_BASE = STUB_BASE + STUB_SIZE + 0x1000
STACK_TOP = 0x00300000
STACK_SIZE = 0x00200000
THREAD_STACK = 0x00100000
TEB = 0x7FFDE000
PEB = 0x7FFDF000
GDT = 0x7FFD0000
HEAP_BASE = 0x50000000
HEAP_SIZE = 0x1F000000                              # address space only; Unicorn commits lazily
DLL_BASE = 0x30000000                               # DLLs that cannot sit at their own base go here up


class ExitProcess(Exception):
    def __init__(self, code):
        self.code = code


_U32 = struct.Struct("<I").unpack_from
_P32 = struct.Struct("<I").pack_into
S32 = lambda v: v - 0x100000000 if v & 0x80000000 else v


def u32(v):
    return v & 0xFFFFFFFF


class Registry:
    """Handler tables shared by all modules: (dll, name) -> (function, argc or None for cdecl)."""
    def __init__(self):
        self.handlers = {}

    def api(self, dll, name, argc):
        def deco(fn):
            self.handlers[(dll.lower(), name)] = (fn, argc)
            return fn
        return deco

    def crt(self, name):
        def deco(fn):
            self.handlers[("msvcrtd.dll", name)] = (fn, None)
            return fn
        return deco


REG = Registry()
api, crt = REG.api, REG.crt


class Cont:
    """Returned by a handler that wants a guest function run before the import completes."""
    def __init__(self, fn, args, then=None, sp=None, inplace=False, regs=None):
        self.fn, self.args, self.then = fn, args, then or (lambda r: r)
        self.sp = sp   # the caller's stack pointer, if lower than the import's own: the new frame goes below it
        # inplace: the frame is already built (native_host.py: a lifted function's own): `sp` is its return address slot, the
        # arguments are above it. The call is made on that frame, with the registers `regs` (EAX, ECX, EDX, EBX, EBP, ESI, EDI).
        self.inplace, self.regs = inplace, regs


class Block:
    """Returned by a handler: this call cannot complete yet. The thread sleeps and retries the call when
    `ready()` is true (or, if there is no predicate, at time `until`, in seconds of host time)."""
    def __init__(self, ready=None, until=None):
        self.ready, self.until = ready, until


class GenBlock:
    """A generator handler that yielded a Block: the thread sleeps, then the generator is resumed."""
    def __init__(self, block, gen):
        self.block, self.gen = block, gen


class Thread:
    def __init__(self, tid, name):
        self.tid, self.name = tid, name
        self.ctx = None
        self.conts = []
        self.state = "ready"                          # ready | blocked | done
        self.wait = None                              # Block, while blocked
        self.teb = 0
        self.exit_code = 0
        self.one_shot = False
        self.slice = None                           # instructions per scheduling slice, if not the machine's
        self.gen = None                               # (gen, esp, ret, argc, addr) of a generator handler parked in a Block
        self.stack_base = 0
        self.stack_size = 0
        self.cont_regs = []
        self.proc_hook, self.proc_ring, self.proc_regs, self.proc_depth, self.proc_first = None, None, None, 0, None
        self.entry_regs = {}                          # EMU_REGCHECK: esp at an import call -> (name, ebp, ebx, esi, edi)
        self.retry = None                             # (stub address, esp) to resume a blocked call


class Heap:
    """First-fit allocator over the mapped HEAP block with exact-size reuse; blocks are 16-aligned."""
    def __init__(self, start, end):
        self.top, self.end = start, end
        self.sizes, self.free = {}, {}

    def alloc(self, n):
        n = max((n + 15) & ~15, 16)
        lst = self.free.get(n)
        if lst:
            a = lst.pop()
        else:
            a = self.top
            self.top += n
            if self.top > self.end:
                raise MemoryError("emulated heap exhausted")
        self.sizes[a] = n
        return a

    def release(self, a):
        n = self.sizes.pop(a, None)
        if n:
            self.free.setdefault(n, []).append(a)

    def size(self, a):
        return self.sizes.get(a, 0)


class Machine:
    def __init__(self, exe_path, game_root, overlay_root, log=print):
        self.log = log
        self.uc = Uc(UC_ARCH_X86, UC_MODE_32)
        if not os.environ.get("EMU_NO_FASTUC"):
            from .fastuc import speed_up  # noqa: PLC0415
            speed_up(self.uc)
        self.regions = []                           # (guest base, size, host address, buffer): see map_region
        self._last_region = None
        self.game_root = game_root                  # host directory that is "C:\\Magic" in the guest
        self.overlay_root = overlay_root            # writes land here, reads look here first
        self.cwd = "C:\\Magic\\Program"
        self.exe_guest_path = self.cwd + "\\" + os.path.basename(exe_path)
        self.map_region(STACK_TOP - STACK_SIZE, STACK_SIZE)
        self.map_region(TEB, 0x2000)
        self.map_region(GDT, 0x1000)
        self.map_region(HEAP_BASE, HEAP_SIZE)
        self.map_region(STUB_BASE, STUB_SIZE)
        self.map_region(BURN_BASE, 0x1000)
        self.uc.mem_write(BURN_BASE, b"\xe3\x02\xe2\xfe\xff\xe2")
        self.heap = Heap(HEAP_BASE + 0x1000, HEAP_BASE + HEAP_SIZE)
        self.stubs = {}                             # trap address -> (dll, name)
        self.handler_of = {}                        # trap address -> (fn, argc)
        self.unimplemented = {}                     # (dll, name) -> call count, for the report
        self.calls = 0
        self.trace_seen = {}
        self.trace_total = {}
        self.recent = collections.deque(maxlen=40)  # last few import calls, for crash reports
        self.counts = {}                            # (dll, name) -> times called
        self.threads = []
        self.pending_dll_inits = []
        self.cur = None
        self.pin = None                             # the thread running a hosted (native or lifted) function that has called out to the guest
        self.next_tid = 1
        self.slice = 200_000_000                    # effectively cooperative: a thread runs until it blocks (the game's
                                                    # static C runtime is not thread-safe and relies on that)
        self._regcheck = bool(os.environ.get("EMU_REGCHECK"))
        self._proctrace = {int(x, 16) for x in os.environ.get("EMU_PROCTRACE", "").split(",") if x}
        self.slice_t0 = 0.0                         # host time the running slice started (live.py)
        self.slices = 0                             # scheduling slices run so far
        self.yield_req = False                      # live.py: end the running slice at the next import call
        self.charging = False                       # native_host.py: slices are run in pieces so owed instructions count
        self.iat_names = {}                         # import table slot -> (dll, function name)
        self.iat_slots = set()                      # addresses of import table slots: `call [slot]` goes to what the slot holds
        self.call_hash_every = int(os.environ.get("EMU_CALL_HASH", "0"))
        self.call_hash = 0
        self.call_hash_noret = bool(os.environ.get("EMU_CALL_HASH_NORET"))
        d = os.environ.get("EMU_CALL_DETAIL")
        self.call_detail = tuple(int(x) for x in d.split(":")) if d else None
        self.owed = 0                               # instructions owed to the clock by native code run in this slice
        self.burn = 0                               # instructions the replaced function that is returning is to execute first
        self.CHUNK = 200_000
        self.intercepts = {}                        # guest address -> (replacement, bytes the original pops): add_intercept
        self.exit_hooks = []                        # called as a code hook when a thread function returns
        self.kill_hooks = []                        # called when a thread is ended from outside (a card handler run on demand)
        self.vt = 0.0                               # virtual time in seconds: the only clock the guest sees
        self.clock_cells = None                     # (GetTickCount value, timer driver's tick count, timer handle, publish count) in guest memory, kept current for hosted C code (native_host.py)
        self.slice_exec = 0                         # the running slice: instructions run so far (in chunks) and its limit, for hosted code that reads the clock
        self.slice_limit = 0
        self.ips = 100_000_000                      # instructions per virtual second (a fast late-90s PC)
        self.modules = {}                           # lower-case name -> dict(base, pe, path)
        self.next_stub = 0
        self.exit_code = None
        self.fake_handles = itertools.count(0xF001)
        self.state = {}                             # free-form per-module state
        self.trace = False
        self.trace_filter = None
        self.uc.mem_write(STUB_BASE, b"\x90" * STUB_SIZE)            # stray execution of a trap area is harmless
        self._setup_fs()
        self.main = self.load_module(exe_path, is_main=True)
        self.uc.hook_add(UC_HOOK_CODE, self._on_code, begin=STUB_BASE, end=STUB_BASE + STUB_SIZE)
        self.uc.hook_add(UC_HOOK_MEM_UNMAPPED, self._on_unmapped)

    def vnow(self):
        return self.vt

    def publish_clock(self):
        """Hosted C code reads the clock from guest memory instead of calling out (the same values kernel32's GetTickCount and the
        game's timer driver return); called wherever `vt` changes."""
        c = self.clock_cells
        if c:
            self.w32(c[0], (60000 + int(self.vt * 1000)) & 0xFFFFFFFF)
            self.w32(c[1], int(self.vt * 54050) & 0xFFFFFFFF)
            if len(c) > 3:
                self.w32(c[3], (self.r32(c[3]) + 1) & 0xFFFFFFFF)   # lets C tell a new publication from the old one

    # ---- memory helpers -------------------------------------------------------------------------
    # Guest memory is backed by host buffers (map_region), so reads and writes of data go straight to them: no call into Unicorn, no
    # allocation. Code is different: Unicorn caches translated blocks, and a write that did not go through it would not invalidate
    # them, so code (add_intercept, the loader) is written with uc.mem_write, never with wr.
    def _region(self, a, n):
        r = self._last_region
        if r is not None and r[0] <= a and a + n <= r[0] + r[1]:
            return r
        for r in self.regions:
            if r[0] <= a and a + n <= r[0] + r[1]:
                self._last_region = r
                return r
        return None

    def rd(self, a, n):
        r = self._region(a, n)
        if r is None:
            return bytes(self.uc.mem_read(a, n))
        o = a - r[0]
        return r[3][o:o + n]

    def wr(self, a, b):
        b = bytes(b)
        r = self._region(a, len(b))
        if r is None:
            self.uc.mem_write(a, b)
        else:
            o = a - r[0]
            r[3][o:o + len(b)] = b

    def r32(self, a):
        r = self._region(a, 4)
        if r is None:
            return struct.unpack("<I", bytes(self.uc.mem_read(a, 4)))[0]
        return _U32(r[3], a - r[0])[0]

    def w32(self, a, v):
        r = self._region(a, 4)
        if r is None:
            self.uc.mem_write(a, struct.pack("<I", u32(v)))
        else:
            _P32(r[3], a - r[0], v & 0xFFFFFFFF)

    def r16(self, a):
        return struct.unpack("<H", self.rd(a, 2))[0]

    def w16(self, a, v):
        self.wr(a, struct.pack("<H", v & 0xFFFF))

    def cstr(self, a, limit=65536):
        """A NUL-terminated string, read a page-bounded chunk at a time (one emulator read per chunk)."""
        if not a:
            return b""
        out = bytearray()
        while len(out) < limit:
            p = a + len(out)
            chunk = self.rd(p, min(4096 - (p & 4095), 256))
            z = chunk.find(b"\0")
            if z >= 0:
                out += chunk[:z]
                break
            out += chunk
        return bytes(out)

    def put_cstr(self, a, b):
        self.wr(a, bytes(b) + b"\0")

    def map_region(self, base, size):
        """Map guest memory backed by a host buffer we own, so that native code (native_host.py) can read and write
        the guest's memory directly instead of through a call per access."""
        buf = mmap.mmap(-1, size)
        host = ctypes.addressof(ctypes.c_char.from_buffer(buf))
        self.uc.mem_map_ptr(base, size, UC_PROT_ALL, host)
        self.regions.append((base, size, host, buf))

    def alloc_cstr(self, b):
        a = self.heap.alloc(len(b) + 1)
        self.put_cstr(a, b)
        return a

    def alloc(self, n, zero=True):
        a = self.heap.alloc(n)
        if zero:
            self.wr(a, b"\0" * n)
        return a

    # ---- set-up ---------------------------------------------------------------------------------
    def _setup_fs(self):
        def ent(base, limit, access, flags):
            return struct.pack("<HHBBBB", limit & 0xFFFF, base & 0xFFFF, (base >> 16) & 0xFF, access,
                               ((flags & 0xF) << 4) | ((limit >> 16) & 0xF), (base >> 24) & 0xFF)
        self.wr(GDT, ent(0, 0, 0, 0) + ent(0, 0xFFFFF, 0x9B, 0xC) + ent(0, 0xFFFFF, 0x93, 0xC)
                + ent(TEB, 0xFFF, 0x93, 0x4))
        self.uc.reg_write(UC_X86_REG_GDTR, (0, GDT, 0x1F, 0))
        self.uc.reg_write(UC_X86_REG_CS, 0x08)
        for r in (UC_X86_REG_DS, UC_X86_REG_ES, UC_X86_REG_SS):
            self.uc.reg_write(r, 0x10)
        self.uc.reg_write(UC_X86_REG_FS, 0x18)
        self.w32(TEB + 0x00, 0xFFFFFFFF)                            # SEH chain head
        self.w32(TEB + 0x04, STACK_TOP)
        self.w32(TEB + 0x08, STACK_TOP - STACK_SIZE)
        self.w32(TEB + 0x18, TEB)
        self.w32(TEB + 0x30, PEB)

    def load_module(self, path, is_main=False):
        """Map a PE (exe or dll) and bind its imports to stubs. Returns the module record."""
        pe = pefile.PE(path)
        size = (pe.OPTIONAL_HEADER.SizeOfImage + 0xFFF) & ~0xFFF
        base = pe.OPTIONAL_HEADER.ImageBase
        taken = any(m["base"] < base + size and base < m["base"] + m["size"] for m in self.modules.values())
        if taken or (not is_main and base < 0x00400000):
            base = self._free_dll_base(size)
        if base != pe.OPTIONAL_HEADER.ImageBase:
            pe.relocate_image(base)
        image = pe.get_memory_mapped_image()
        self.map_region(base, size)
        self.wr(base, image)
        mod = {"base": base, "size": size, "pe": pe, "path": path,
               "name": os.path.basename(path).lower()}
        self.modules[mod["name"]] = mod
        for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
            dll = entry.dll.decode().lower()
            real = self._load_game_dll(dll, path)
            for imp in entry.imports:
                name = imp.name.decode() if imp.name else f"#{imp.ordinal}"
                slot = imp.address - pe.OPTIONAL_HEADER.ImageBase + base
                self.iat_slots.add(slot)
                self.iat_names[slot] = (dll, name)
                target = real["exports"].get(name) if real else None
                self.w32(slot, target or self.stub_for(dll, name))
        mod["exports"] = {}
        if hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
            for sym in pe.DIRECTORY_ENTRY_EXPORT.symbols:
                key = sym.name.decode() if sym.name else f"#{sym.ordinal}"
                mod["exports"][key] = base + sym.address
                mod["exports"][f"#{sym.ordinal}"] = base + sym.address                  # a named export is also found by ordinal (GetProcAddress(h, 3))
        mod["entry"] = base + pe.OPTIONAL_HEADER.AddressOfEntryPoint
        return mod

    def _load_game_dll(self, dll, importer_path):
        """A DLL that ships with the game (DECKDLL, STATWIN, MAGSND, MAGVID) sits next to the importing program;
        map it for real. System DLLs are answered by handlers instead. Its DllMain runs before the program."""
        key = dll.lower()
        if key in self.modules:
            return self.modules[key]
        here = os.path.dirname(importer_path)
        cand = next((os.path.join(here, f) for f in os.listdir(here) if f.lower() == key), None)
        if not cand or key in ("msvcrtd.dll", "msvcrt.dll"):
            return None
        mod = self.load_module(cand)
        self.pending_dll_inits.append(mod)
        return mod

    def _free_dll_base(self, size):
        a = DLL_BASE
        for m in sorted(self.modules.values(), key=lambda m: m["base"]):
            if m["base"] + m["size"] > a and m["base"] < a + size and m["base"] >= DLL_BASE:
                a = (m["base"] + m["size"] + 0xFFFF) & ~0xFFFF
        return a

    def stub_for(self, dll, name):
        for a, key in self.stubs.items():
            if key == (dll, name):
                return a
        a = STUB_BASE + self.next_stub * 16
        self.next_stub += 1
        if self.next_stub * 16 >= STUB_SIZE - 0x100:
            raise MemoryError("stub area full")
        self.stubs[a] = (dll, name)
        return a

    # ---- threads ----------------------------------------------------------------------------------
    @property
    def conts(self):
        return self.cur.conts

    def _thread_teb(self, t, stack_top, stack_low):
        teb = self.alloc(0x1000)
        self.w32(teb + 0x00, 0xFFFFFFFF)
        self.w32(teb + 0x04, stack_top)
        self.w32(teb + 0x08, stack_low)
        self.w32(teb + 0x18, teb)
        self.w32(teb + 0x20, t.tid)                                # ClientId.UniqueThread
        self.w32(teb + 0x30, PEB)
        t.teb = teb

    def spawn(self, fn, args, name, one_shot=False, stack=THREAD_STACK):
        """Create a thread that will run `fn(*args)` (stdcall) and finish when it returns."""
        t = Thread(self.next_tid, name)
        self.next_tid += 1
        t.one_shot = one_shot
        base = self.alloc(stack, zero=False)
        t.stack_base = base
        t.stack_size = stack
        top = base + stack - 16
        self._thread_teb(t, top, base)
        sp = top
        for a in reversed(args):
            sp -= 4
            self.w32(sp, a)
        sp -= 4
        self.w32(sp, EXIT_TRAP)
        # build an initial context: take the current one and point it at the new thread
        keep = self.uc.context_save()
        self.uc.reg_write(UC_X86_REG_ESP, sp)
        self.uc.reg_write(UC_X86_REG_EIP, fn)
        for r in (UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI,
                  UC_X86_REG_EBP):
            self.uc.reg_write(r, 0)
        t.ctx = self.uc.context_save()
        self.uc.context_restore(keep)
        t.start_eip = fn
        self.threads.append(t)
        return t

    def exit_current_thread(self, code=0):
        self.cur.state, self.cur.exit_code = "done", code
        self.uc.emu_stop()

    def _set_fs(self, teb):
        ent = struct.pack("<HHBBBB", 0xFFF, teb & 0xFFFF, (teb >> 16) & 0xFF, 0x93, 0x40, (teb >> 24) & 0xFF)
        self.wr(GDT + 0x18, ent)
        self.uc.reg_write(UC_X86_REG_FS, 0x18)

    def _switch_to(self, t):
        self.cur = t
        self.uc.context_restore(t.ctx)
        self._set_fs(t.teb)

    def _on_own_stack(self, t):
        """True when ESP is inside the thread's own stack. The game's assembly (MPS_CODE: its picture decompressor) switches to a
        private stack and keeps the old ESP in a global, and its read callback is called from there: another thread running
        in the middle of that is how a thread came back on the wrong stack. Real Windows hides it behind coarse time slices;
        here such a thread is never scheduled away (it is the game's own cooperative assumption)."""
        esp = self.uc.reg_read(UC_X86_REG_ESP)
        if t.stack_base:
            return t.stack_base <= esp < t.stack_base + t.stack_size
        return STACK_TOP - STACK_SIZE <= esp <= STACK_TOP                   # the main thread

    def _start_proctrace(self):
        """EMU_PROCTRACE=ADDR[,ADDR]: while a guest function called from a handler runs, keep its last instructions (eip, ebp, esp);
        shown if it returns with different ebp/ebx/esi/edi."""
        import collections
        ring = collections.deque(maxlen=120)
        uc, t = self.uc, self.cur
        t.proc_ring = ring
        t.proc_first = None
        t.proc_regs = tuple(uc.reg_read(r) for r in (UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI))

        def cb(uc_, address, size, user):
            rec = (address, uc_.reg_read(UC_X86_REG_EBP), uc_.reg_read(UC_X86_REG_ESP), self.cur.tid)
            if not ring and t.proc_first is None:
                t.proc_first = rec
            ring.append(rec)
        t.proc_hook = uc.hook_add(UC_HOOK_CODE, cb, begin=0x400000, end=0x600000)
        uc.ctl_flush_tb()

    def _stop_proctrace(self):
        uc, t = self.uc, self.cur
        uc.hook_del(t.proc_hook)
        t.proc_hook = None
        uc.ctl_flush_tb()
        now = tuple(uc.reg_read(r) for r in (UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI))
        if now != t.proc_regs:
            self.log(f"   first instruction of the traced call: {t.proc_first and [hex(x) for x in t.proc_first]}; thread stack {t.stack_base:#x}+{t.stack_size:#x}")
            from capstone import Cs, CS_ARCH_X86, CS_MODE_32
            md = Cs(CS_ARCH_X86, CS_MODE_32)
            self.log(f"!! PROCTRACE t{t.tid}: ebp/ebx/esi/edi {[hex(x) for x in t.proc_regs]} -> {[hex(x) for x in now]}; the last instructions:")
            for a, ebp, esp, tid in list(t.proc_ring)[-70:]:
                try:
                    ins = next(md.disasm(bytes(uc.mem_read(a, 16)), a))
                    txt = f"{ins.mnemonic} {ins.op_str}"
                except Exception:                                # noqa: BLE001
                    txt = "?"
                self.log(f"     t{tid} {a:#010x} ebp={ebp:#010x} esp={esp:#010x}  {txt}")

    def _runnable(self, t, now):
        if t.state == "ready":
            return True
        if t.state == "blocked":
            w = t.wait
            if w is None:
                return True
            if w.ready is not None and w.ready():
                return True
            if w.until is not None and now >= w.until:
                return True
        return False

    # ---- the import dispatcher --------------------------------------------------------------------
    def args(self, n):
        esp = self.uc.reg_read(UC_X86_REG_ESP)
        return list(struct.unpack(f"<{n}I", self.rd(esp + 4, 4 * n))) if n else []

    def _block(self, blk, addr, esp):
        """Leave the CPU parked on the import's stub so the call is retried when the thread is woken."""
        self.uc.reg_write(UC_X86_REG_ESP, esp)
        self.uc.reg_write(UC_X86_REG_EIP, addr)
        self.cur.state, self.cur.wait = "blocked", blk
        self.cur.retry = (addr, esp)
        self.uc.emu_stop()

    def _on_code(self, uc, address, size, user):
        if address in self.intercepts:
            self._on_intercept(uc, address, size, user)
            return
        if address == CONT_TRAP:
            self._finish_cont()
            return
        if address == EXIT_TRAP:
            for hook in self.exit_hooks:   # Unicorn skips the remaining code hooks once this one stops the emulation
                hook(uc, address, size, user)
            self.cur.state = "done"
            self.cur.exit_code = uc.reg_read(UC_X86_REG_EAX)
            uc.emu_stop()
            return
        key = self.stubs.get(address)
        if key is None:
            return
        self.calls += 1
        esp = uc.reg_read(UC_X86_REG_ESP)
        ret = self.r32(esp)
        if self._regcheck:                                   # EMU_REGCHECK=1: callee-saved registers must survive an import call
            self.cur.entry_regs[esp] = (key[1], uc.reg_read(UC_X86_REG_EBP), uc.reg_read(UC_X86_REG_EBX),
                                        uc.reg_read(UC_X86_REG_ESI), uc.reg_read(UC_X86_REG_EDI))
        dll, name = key
        if self.call_hash_every:   # EMU_CALL_HASH=N: a running hash of the import calls, printed every N, to find where two runs part
            # EMU_CALL_HASH_NORET=1: without the return address (an import called from hosted lifted code returns to a trap, not the call site)
            self.call_hash = zlib.crc32(f"{self.cur.tid}{name}{'' if self.call_hash_noret else format(ret, 'x')}".encode(), self.call_hash)
            if self.calls % self.call_hash_every == 0:
                self.log(f"   [calls {self.calls}] {self.call_hash:08x} vt {self.vt:.6f}")
            if self.call_detail and self.call_detail[0] <= self.calls <= self.call_detail[1]:
                self.log(f"   [call {self.calls}] t{self.cur.tid} {name} <- 0x{ret:08x} vt {self.vt:.6f}")
        self.counts[key] = self.counts.get(key, 0) + 1
        self.recent.append((self.cur.tid, name, ret))
        h = REG.handlers.get(key)
        if h is None and dll.startswith("msvcrt"):
            h = REG.handlers.get(("msvcrtd.dll", name))
        if h is None:
            self.unimplemented[key] = self.unimplemented.get(key, 0) + 1
            argc = self.default_argc(dll, name)
            if argc is None and not dll.startswith("msvcrt"):
                self.log(f"!! unknown argument count for {dll}!{name}; stopping")
                uc.emu_stop()
                self.exit_code = -1
                self.stop = True
                return
            stub_val = (lambda m, a: next(self.fake_handles)) if re.match(
                r"(Create|Load|Register|Get(Stock|DC|DlgItem|Window)|Find|Select)", name) else (lambda m, a: 0)
            fn, argc = stub_val, argc
            if self.unimplemented[key] == 1:
                self.log(f"   (stub) {dll}!{name} -> 0, from 0x{ret:08x}")
        else:
            fn, argc = h
        cdecl = argc is None
        a = self.args(8) if cdecl else self.args(argc)
        if self.trace and (self.trace_filter is None or self.trace_filter(name)):
            self.log(f"{self.calls:6d} [t{self.cur.tid}] {dll}!{name}("
                     f"{', '.join(hex(x) for x in a[:argc if argc is not None else 4])}) <- 0x{ret:08x}")
        try:
            res = fn(self, a)
            if inspect.isgenerator(res):
                res = self._drive(res, None)
        except ExitProcess as e:
            self.exit_code = e.code
            self.stop = True
            uc.emu_stop()
            return
        self._apply(res, esp, ret, 0 if cdecl else argc, address)
        if self.yield_req and self.cur.state == "ready" and self._on_own_stack(self.cur):   # live (live.py): the ticker asked for the end of the slice
            self.yield_req = False
            uc.emu_stop()

    def add_intercept(self, addr, fn, cleanup=0):
        """Run `fn(machine, esp)` in place of the guest function that starts at `addr`. It returns the function's result,
        or is a generator that yields `call_guest(...)` to have guest functions run first (as an import handler does).
        `cleanup` is the bytes the original pops off the stack when it returns (a `ret imm16`).

        The function's first bytes are overwritten with a jump to a trap in the stub area, which the one code hook there
        already watches: a code hook of its own for every replaced function (hundreds) makes Unicorn several times slower."""
        trap = STUB_BASE + self.next_stub * 16
        self.next_stub += 1
        if self.next_stub * 16 >= STUB_SIZE - 0x100:
            raise RuntimeError("out of stub traps")
        self.intercepts[trap] = (fn, cleanup)
        self.uc.mem_write(addr, b"\xe9" + struct.pack("<I", (trap - (addr + 5)) & 0xFFFFFFFF))
        self.uc.ctl_remove_cache(addr, addr + 5)

    def _on_intercept(self, uc, address, size, user):
        ent = self.intercepts.get(address)
        if ent is None:
            return
        fn, cleanup = ent
        esp = uc.reg_read(UC_X86_REG_ESP)
        ret = self.r32(esp)
        res = fn(self, esp)
        if inspect.isgenerator(res):
            res = self._drive(res, None)
        self._apply(res, esp, ret, cleanup // 4, address)

    def default_argc(self, dll, name):
        table = self.state.get("argc_table", {})
        if name in table:
            return table[name]
        return None

    def _return(self, esp, ret, argc, val):
        uc = self.uc
        if self._regcheck:
            rec = self.cur.entry_regs.pop(esp, None)
            if rec:
                now = (uc.reg_read(UC_X86_REG_EBP), uc.reg_read(UC_X86_REG_EBX), uc.reg_read(UC_X86_REG_ESI), uc.reg_read(UC_X86_REG_EDI))
                if now != rec[1:]:
                    self.log(f"!! REGCHECK t{self.cur.tid} {self.cur.name}: {rec[0]} changed callee-saved registers "
                             f"ebp/ebx/esi/edi {[hex(x) for x in rec[1:]]} -> {[hex(x) for x in now]} (returning to {ret:#x})")
        uc.reg_write(UC_X86_REG_EAX, u32(val))
        uc.reg_write(UC_X86_REG_ESP, esp + 4 + 4 * argc)
        if self.burn > 4:
            # Run what the replaced function's original would have run, as real instructions, so that the emulator counts
            # them and the slice ends where the original's would have: the jump that replaced the function's first bytes
            # counted one, the trap it lands on (which the hook redirects, but the emulator counts) one more, `jecxz` and
            # the final `jmp edx` two more, `loop` the rest.
            uc.reg_write(UC_X86_REG_ECX, self.burn - 4)
            uc.reg_write(UC_X86_REG_EDX, ret)
            uc.reg_write(UC_X86_REG_EIP, BURN_BASE)
        else:
            uc.reg_write(UC_X86_REG_EIP, ret)
        self.burn = 0

    def call_guest(self, fn, args, then=lambda r: r, sp=None, inplace=False, regs=None):
        return Cont(fn, args, then, sp, inplace, regs)

    def _start_cont(self, c, esp, ret, argc, addr):
        uc = self.uc
        restore = None
        if c.inplace:
            sp = c.sp                                  # the lifted function's own frame: the return address slot is there
            restore = (sp, self.r32(sp))               # the original's call leaves its return address behind; so must this
        else:
            sp = (c.sp if c.sp else esp) - 4           # build the callee's frame below the import's own (or the caller's)
            for a in reversed(c.args):
                self.w32(sp, a)
                sp -= 4
        self.conts.append((c.then, esp, ret, argc, addr, restore))
        if self._regcheck:
            self.cur.cont_regs.append((c.fn, tuple(uc.reg_read(r) for r in (UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI)) if c.regs is None else None))
        self.w32(sp, CONT_TRAP)
        if self._proctrace and c.fn in self._proctrace and self.cur.proc_hook is None:
            self.cur.proc_depth = len(self.conts) - 1
            self._start_proctrace()
        if c.regs is not None:
            for reg, v in zip((UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EBX, UC_X86_REG_EBP,
                               UC_X86_REG_ESI, UC_X86_REG_EDI), c.regs):
                uc.reg_write(reg, v)
        uc.reg_write(UC_X86_REG_ESP, sp)
        if self.burn > 4:
            # a replaced function that calls out to the guest (a lifted loop that polls the clock or sleeps) first runs the
            # instructions its original ran before that call, so that the clock the guest function reads is the original's
            uc.reg_write(UC_X86_REG_ECX, self.burn - 4)
            uc.reg_write(UC_X86_REG_EDX, c.fn)
            uc.reg_write(UC_X86_REG_EIP, BURN_BASE)
            self.burn = 0
        else:
            uc.reg_write(UC_X86_REG_EIP, c.fn)

    def _finish_cont(self):
        then, esp, ret, argc, addr, restore = self.conts.pop()
        if self.cur.proc_hook is not None and len(self.conts) == self.cur.proc_depth:
            self._stop_proctrace()
        if self._regcheck and self.cur.cont_regs:
            fn, before = self.cur.cont_regs.pop()
            if before is not None:
                uc = self.uc
                now = tuple(uc.reg_read(r) for r in (UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ESI, UC_X86_REG_EDI))
                if now != before:
                    self.log(f"!! REGCHECK t{self.cur.tid} {self.cur.name}: the guest function at {fn:#x} called from a handler changed "
                             f"ebp/ebx/esi/edi {[hex(x) for x in before]} -> {[hex(x) for x in now]}")
        if restore:
            self.w32(*restore)
        r = self.uc.reg_read(UC_X86_REG_EAX)
        res = then(r)
        if inspect.isgenerator(res):
            res = self._drive(res, None)
        self._apply(res, esp, ret, argc, addr)

    def _apply(self, res, esp, ret, argc, addr):
        """Finish an import call from a handler's result: park (Block), wait mid-generator (GenBlock), run a
        guest function first (Cont), or return a value."""
        if isinstance(res, GenBlock):
            self.cur.state, self.cur.wait = "blocked", res.block
            self.cur.gen = (res.gen, esp, ret, argc, addr)
            self.uc.emu_stop()
        elif isinstance(res, Block):
            self._block(res, addr, esp)
        elif isinstance(res, Cont):
            self._start_cont(res, esp, ret, argc, addr)
        else:
            self._return(esp, ret, argc, res or 0)

    def _drive(self, gen, value):
        """Run a generator handler: each `yield Cont(...)` is a guest call whose eax is sent back in."""
        try:
            c = gen.send(value)
        except StopIteration as e:
            return e.value or 0
        if isinstance(c, Block):
            return GenBlock(c, gen)
        return Cont(c.fn, c.args, lambda r: self._drive(gen, r), c.sp, c.inplace, c.regs)

    def _on_unmapped(self, uc, access, address, size, value, user):
        eip = uc.reg_read(UC_X86_REG_EIP)
        self.log(f"!! unmapped access at 0x{address:08x} (size {size}, access {access}) from eip 0x{eip:08x}"
                 f" in thread {self.cur.tid if self.cur else '?'}")
        return False

    # ---- running ----------------------------------------------------------------------------------
    def run(self, entry=None):
        """Start the main thread and schedule all threads until the process exits."""
        uc = self.uc
        main = Thread(self.next_tid, "main")
        self.next_tid += 1
        self._thread_teb(main, STACK_TOP, STACK_TOP - STACK_SIZE)
        main.teb = TEB
        top = STACK_TOP - 0x100
        self.w32(top, EXIT_TRAP)
        uc.reg_write(UC_X86_REG_ESP, top)
        uc.reg_write(UC_X86_REG_EIP, entry or self.main["entry"])
        main.ctx = uc.context_save()
        inits = [self.spawn(mod["entry"], [mod["base"], 1, 0], f"DllMain({mod['name']})", one_shot=True, stack=0x40000)
                 for mod in self.pending_dll_inits]
        self.pending_dll_inits = []
        if inits:
            main.state, main.wait = "blocked", Block(ready=lambda: all(t.state == "done" for t in inits))
        self.threads.append(main)
        self.stop = False
        rr = 0
        try:
            while not self.stop:
                now = self.vt
                lim = self.state.get("virtual_limit")
                if lim is not None and self.vt > lim:
                    self.log("virtual time limit reached")
                    break
                if self.state.get("hard_stop") and _time.time() > self.state["hard_stop"]:
                    self.log("hard stop: time limit reached")
                    self.report_threads()
                    break
                hook = self.state.get("on_schedule")
                if hook:
                    hook(self)
                runnable = [t for t in self.threads if t.state != "done" and self._runnable(t, now)]
                if self.pin is not None and self.pin in runnable:       # hosted code is waiting for a guest call it made: its C state is global, so no other thread runs
                    runnable = [self.pin]
                if not runnable:
                    if all(t.state == "done" for t in self.threads):
                        break
                    # everyone is waiting: jump the virtual clock to the earliest deadline (no real sleeping)
                    wakes = [t.wait.until for t in self.threads if t.state == "blocked" and t.wait
                             and t.wait.until is not None]
                    nxt = self.state.get("next_host_event")
                    if nxt is not None:
                        wakes.append(nxt)
                    nv = max(self.vt + 0.0005, min(wakes)) if wakes else self.vt + 0.001
                    pace = self.state.get("pace")                 # live (live.py): wait for the real clock instead of jumping
                    self.vt = pace(self, nv) if pace else nv
                    self.publish_clock()
                    continue
                rr += 1
                self.slices += 1
                self.slice_t0 = _time.monotonic()
                t = runnable[rr % len(runnable)]
                t.state, t.wait = "ready", None
                calls0 = self.calls
                self._switch_to(t)
                if t.gen:
                    gen, esp, ret, argc, addr = t.gen
                    t.gen = None
                    self._apply(self._drive(gen, None), esp, ret, argc, addr)
                    if t.state == "blocked":                      # blocked again straight away
                        t.ctx = uc.context_save()
                        continue
                if t.retry:
                    uc.reg_write(UC_X86_REG_EIP, t.retry[0])
                    uc.reg_write(UC_X86_REG_ESP, t.retry[1])
                    t.retry = None
                limit = t.slice or self.slice
                ticked = self.state.get("ticker") and not t.slice
                executed, faulted = 0, False
                self.slice_exec, self.slice_limit = 0, limit
                while True:
                    pc = uc.reg_read(UC_X86_REG_EIP)
                    # With native code standing in for some of the original's (native_host.py), the instructions it would
                    # have run are owed to the clock: the slice is run in pieces so that it can end when the guest's own
                    # instructions plus the owed ones reach the limit, as the original's would have.
                    step = min(self.CHUNK, limit - executed) if self.charging else limit
                    try:
                        if ticked and not self.charging:        # live (live.py): no count, a ticker thread stops the slice:
                            uc.emu_start(pc, 0xFFFFFFFF)            # a count makes Unicorn call a hook on every instruction (35x slower)
                        else:
                            uc.emu_start(pc, 0xFFFFFFFF, count=step)
                    except UcError as e:
                        eip = uc.reg_read(UC_X86_REG_EIP)
                        if t.name == "inject":   # a card handler run on demand (winemu/run.py) faulted: that call ends, the run goes on
                            self.log(f"injected call faulted: {e} at eip 0x{eip:08x}")
                            t.state = "done"
                            for hook in self.kill_hooks:
                                hook()
                            faulted = True
                            break
                        self.log(f"emulation error: {e} at eip 0x{eip:08x} in thread {t.tid} ({t.name})")
                        self.dump_crash(eip)
                        self.exit_code = -2
                        faulted = None
                        break
                    if ticked and t.state == "ready" and not self.stop and not self._on_own_stack(t):
                        continue                                    # stopped on a private stack: run on until it is back
                    if self.charging and t.state == "ready" and not self.stop:
                        executed += step
                        self.slice_exec = executed
                        if executed + self.owed < limit:
                            continue
                    break
                if faulted:
                    continue
                if faulted is None:
                    break
                # charge virtual time: a full slice if it ran to the limit, little if it blocked, plus calls
                ran = (executed if self.charging else limit) if t.state == "ready" else 3000
                vt_before = self.vt
                self.vt += (ran + self.owed + 150 * (self.calls - calls0)) / self.ips
                self.owed = 0
                clock = self.state.get("clock")                   # live (live.py): the guest's clock is the real one
                if clock:
                    self.vt = clock(self, vt_before)
                self.publish_clock()
                if t.state == "ready":
                    t.ctx = uc.context_save()
                elif t.state == "blocked":
                    t.ctx = uc.context_save()
                if t.tid == main.tid and t.state == "done":
                    self.exit_code = t.exit_code
                    break
                for x in self.threads:
                    if x.state == "done" and x is not main and x.stack_base:
                        self.heap.release(x.stack_base)
                        self.heap.release(x.teb)
                        x.stack_base = 0
                self.threads = [x for x in self.threads if x.state != "done" or x is main]
        finally:
            pass
        return self.exit_code

    def flush_trace(self, sink=None):
        """Totals of every traced call (with its arguments) over the whole run."""
        out = sink or self.log
        if self.trace_total:
            out("   [trace totals] calls with identical arguments and caller:")
            for body, n in sorted(self.trace_total.items(), key=lambda kv: -kv[1])[:25]:
                out(f"      {n:7d}  {body}")
            self.trace_total = {}

    def add_trace(self, addr, label, nargs, strings=(), sink=None, ret=False, describe=None):
        """Log every entry to a guest function: virtual time, thread, its `nargs` stack arguments and the caller.
        `strings` lists argument positions that are C strings (shown as text). One hook per function, so it costs
        nothing when the function is not running. With `ret`, the return value (eax) is logged when the call comes
        back; `describe(args)` adds text to both lines (for example a card's name)."""
        sink = sink if sink is not None else self.log

        def hook(uc, address, size, user):
            esp = uc.reg_read(UC_X86_REG_ESP)
            args = [self.r32(esp + 4 + 4 * i) for i in range(nargs)]
            shown = []
            for i, a in enumerate(args):
                if i in strings:
                    try:
                        shown.append(repr(self.cstr(a, 60).decode("latin-1")))
                        continue
                    except Exception:
                        pass
                shown.append(f"0x{a:x}" if a > 0xFFFF else str(S32(a)))
            body = f"{label}({', '.join(shown)}) <- 0x{self.r32(esp):08x}"
            if describe:
                try:
                    body += "  " + describe(args)
                except Exception:
                    pass
            if ret:
                retaddr = self.r32(esp)
                pending.setdefault(retaddr, []).append((esp + 4, body))   # cdecl: esp is entry+4 after the return
                if retaddr not in ret_hooked:
                    ret_hooked.add(retaddr)
                    self.uc.hook_add(UC_HOOK_CODE, on_ret, begin=retaddr, end=retaddr)
            # A burst repeats the same few calls thousands of times in a few milliseconds (the spell-chain loop):
            # print each distinct call twice per 50 ms of virtual time, then only count the rest.
            key = (body, int(self.vt * 20))
            n = self.trace_seen.get(key, 0) + 1
            self.trace_seen[key] = n
            if len(self.trace_seen) > 5000:
                self.trace_seen = {k: v for k, v in self.trace_seen.items() if k[1] >= int(self.vt * 20) - 1}
            if n <= 2:
                sink(f"   [trace {self.vt:8.3f}s t{self.cur.tid if self.cur else 0}] {body}")
            elif n == 3:
                sink(f"   [trace {self.vt:8.3f}s ...] (further identical calls in this 50 ms are counted, not shown)")
            self.trace_total[body] = self.trace_total.get(body, 0) + 1
        pending, ret_hooked = {}, set()

        def on_ret(uc, address, size, user):
            esp = uc.reg_read(UC_X86_REG_ESP)
            calls = pending.get(address, [])
            for i in range(len(calls) - 1, -1, -1):
                if calls[i][0] == esp:
                    body = calls[i][1]
                    del calls[i]
                    sink(f"   [ret   {self.vt:8.3f}s] {body} = {S32(uc.reg_read(UC_X86_REG_EAX))}")
                    break

        self.uc.hook_add(UC_HOOK_CODE, hook, begin=addr, end=addr)

    def add_watch(self, addr, label, sink=None):
        """Log every write that changes the dword at `addr`: old and new value, the writing instruction's address and
        the return address of the function it is in (when it has a standard frame)."""
        sink = sink if sink is not None else self.log
        state = {"v": None}

        def hook(uc, access, address, size, value, user):
            old = self.r32(addr)
            sh = 8 * (address - addr)                            # merge a byte/word write into the dword
            mask = ((1 << (8 * size)) - 1) << sh if 0 <= sh < 32 else 0
            new = (old & ~mask & 0xFFFFFFFF) | ((value << sh) & mask)
            eip = uc.reg_read(UC_X86_REG_EIP)
            ebp = uc.reg_read(UC_X86_REG_EBP)
            try:
                caller = self.r32(ebp + 4)
            except Exception:
                caller = 0
            if new == old:
                return
            sink(f"   [watch {self.vt:8.3f}s] {label}: {old:#x} -> {new:#x} "
                 f"({size}-byte write at {address:#x}) eip=0x{eip:08x} caller=0x{caller:08x}")

        self.uc.hook_add(UC_HOOK_MEM_WRITE, hook, begin=addr, end=addr + 3)

    def report_threads(self):
        """Where every thread is (a spinning thread shows up as the same eip range on each report)."""
        for t in self.threads:
            if t.ctx is None:
                continue
            keep = self.uc.context_save()
            self.uc.context_restore(t.ctx)
            eip, esp, ebp = (self.uc.reg_read(r) for r in (UC_X86_REG_EIP, UC_X86_REG_ESP, UC_X86_REG_EBP))
            self.uc.context_restore(keep)
            chain = []
            try:
                for _ in range(6):
                    chain.append(self.r32(ebp + 4))
                    ebp = self.r32(ebp)
            except Exception:
                pass
            where = self.stubs.get(eip)
            self.log(f"   thread {t.tid} ({t.name}) {t.state}{' in ' + where[1] if where else ''}: eip=0x{eip:08x} esp=0x{esp:08x} callers "
                     + " ".join(f"0x{c:08x}" for c in chain))

    def dump_crash(self, eip):
        """Registers, the code around eip (disassembled if capstone is installed) and the return chain."""
        r = self.regs()
        self.log("   regs: " + " ".join(f"{k}={v:08x}" for k, v in r.items()))
        try:
            import capstone
            md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
            code = self.rd(eip - 24, 48)
            for ins in md.disasm(code, eip - 24):
                self.log(f"   {'=>' if ins.address == eip else '  '} {ins.address:08x}: {ins.mnemonic} {ins.op_str}")
        except Exception:
            pass
        ebp = r["ebp"]
        chain = []
        for _ in range(8):
            try:
                chain.append(self.r32(ebp + 4))
                ebp = self.r32(ebp)
            except Exception:
                break
        self.log("   caller chain (ebp): " + " ".join(f"0x{c:08x}" for c in chain))
        self.log("   last imports: " + " | ".join(f"t{t}:{n}<0x{r:x}" for t, n, r in list(self.recent)[-16:]))
        esp = r["esp"]
        try:
            self.log(f"   thread t{self.cur.tid} {self.cur.name}: {len(self.cur.conts)} guest calls pending, state {self.cur.state}; stack from esp:")
            for i in range(0, 0x60, 8):
                self.log(f"     {esp + 4 * i:08x}: " + " ".join(f"{self.r32(esp + 4 * (i + j)):08x}" for j in range(8)))
            self.log("   pending guest calls (resume esp, return address): " + ", ".join(f"({c[1]:#x},{c[2]:#x})" for c in self.cur.conts))
        except Exception:                                    # noqa: BLE001
            pass

    def regs(self):
        u = self.uc
        return {n: u.reg_read(r) for n, r in (("eax", UC_X86_REG_EAX), ("ebx", UC_X86_REG_EBX),
                ("ecx", UC_X86_REG_ECX), ("edx", UC_X86_REG_EDX), ("esi", UC_X86_REG_ESI),
                ("edi", UC_X86_REG_EDI), ("ebp", UC_X86_REG_EBP), ("esp", UC_X86_REG_ESP),
                ("eip", UC_X86_REG_EIP))}

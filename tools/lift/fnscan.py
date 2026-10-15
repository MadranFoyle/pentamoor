"""
fnscan.py - find the functions of a program from its own machine code.

The lifter needs to know where the functions of an executable start (a `jmp` to a function's entry is a tail call, a call target is a callee whose argument count and stack
clean-up are wanted), how long they are and how many arguments they take. There is no symbol table to read them from (the game's executables are stripped), so they are found
the way a disassembler finds them, from the code and nothing else:

1. the roots: the entry point, the functions a table of the program points at (the master card table's handlers), and any address the caller names;
2. what the code reaches: direct call targets, the target of a tail `jmp` to another function, addresses the code stores or pushes as constants, and addresses the data
   sections hold as pointers (callback and handler tables) when they start like a function does;
3. what nothing reaches (functions the program never calls): in the gaps between the code found so far, an address that starts a function the way the compiler writes one
   (`push ebp; mov ebp, esp`, or the first instruction after the int3 fill that pads the C runtime's functions) and that decodes as code.

Each function found is explored by the lifter's own recursive descent (x86lift.Lifter.explore), so its extent comes from its control flow. What comes back, per function:
its size (up to the next function), the argument count (what its frame reads and what its `ret imm16` pops), and the address-based name FUN_<address>.

    fnscan.py PROGRAM.EXE [--roots 0x401000,...]      print what was found
"""
import argparse
import re
import sys
from collections import defaultdict

from x86lift import Unsupported

PROLOGUE = b"\x55\x8b\xec"
# the first byte of a function the compiler padded: a prologue, or a first instruction that begins one (the same set gen_dll.py uses)
START_BYTES = frozenset((0x55, 0x53, 0x56, 0x57, 0x8B, 0x83, 0x81, 0xA1, 0x6A, 0x33, 0x31, 0xC3, 0xB8, 0x64, 0xFF, 0x68))
# what the explorer says when the bytes are not code at all; any other refusal is a real function the lifter cannot follow (an indirect jump, ...)
NOT_CODE = ("undecodable bytes", "control flow leaves the readable code", "is not in the image")


class Scan:
    def __init__(self, lifter, getbytes, code, data, gap_code=None):
        """`code`: the (lo, hi) ranges a function can be in; `data`: the ranges that can hold pointers to functions; `gap_code`: where the
        search for functions nothing reaches may look (default: `code`)."""
        self.lifter = lifter
        self.get = getbytes
        self.code = sorted(code)
        self.data = list(data)
        self.gap_code = sorted(gap_code if gap_code is not None else code)
        self.entries = set()
        self.parsed = {}                  # entry -> (instructions, tails) of the functions explored
        self.failed = {}                  # entry -> why the explorer gave up
        self.intrinsics = set()           # compiler helpers that take registers (replaced by inline code, never lifted)
        self.queue = []
        self.jumps = defaultdict(set)     # address -> entries whose code jumps there inside the function (they must be explored again if it becomes an entry)
        self.cov = {lo: bytearray(hi - lo) for lo, hi in self.code}      # bytes that are an instruction of a function found
        self.imm = set()                  # constants of the code found that point into code
        self.dead = set()                 # functions found only by the search for code nothing reaches
        self.data_pointers = None

    # ---- the ranges --------------------------------------------------------------------------------------------
    def in_code(self, a):
        return any(lo <= a < hi for lo, hi in self.code)

    def covered(self, a):
        for lo, hi in self.code:
            if lo <= a < hi:
                return bool(self.cov[lo][a - lo])
        return False

    def _mark(self, insns):
        for ia, i in insns.items():
            for lo, hi in self.code:
                if lo <= ia < hi:
                    self.cov[lo][ia - lo:ia - lo + i.size] = b"\x01" * min(i.size, hi - ia)
                    break

    # ---- adding functions --------------------------------------------------------------------------------------
    def add(self, a):
        """Make `a` a function (if it lies in code and is not one already); True if it was new."""
        if a in self.entries or not self.in_code(a):
            return False
        self.entries.add(a)
        if self.lifter.intrinsic(a, self.get):
            self.intrinsics.add(a)
            return True
        self.queue.append(a)
        for f in self.jumps.pop(a, ()):       # a function that jumped to `a` as inline code has `a` as a tail call now
            if f in self.parsed:
                del self.parsed[f]
                self.queue.append(f)
        return True

    def _explore(self, a):
        try:
            insns, tails = self.lifter.explore(self.get, a, self.entries)
        except Unsupported as e:
            self.failed[a] = str(e)
            if self.failed[a].startswith(NOT_CODE):
                return
            sweep = self._sweep(a)
            self._mark(sweep)
            for ia, i in sweep.items():          # what a function that cannot be lifted still calls is a function
                if i.mnemonic == "call" and i.operands and i.operands[0].type == 2:
                    self.add(i.operands[0].imm & 0xFFFFFFFF)
            return
        self.failed.pop(a, None)
        self.parsed[a] = (insns, tails)
        self._mark(insns)
        for ia, i in insns.items():
            if not i.operands:
                continue
            op = i.operands[0]
            if i.mnemonic == "call" and op.type == 2:
                self.add(op.imm & 0xFFFFFFFF)
            elif i.mnemonic == "jmp" and op.type == 2 and ia not in tails:
                self.jumps[op.imm & 0xFFFFFFFF].add(a)
            for o in i.operands:
                if o.type == 2 and self.in_code(o.imm & 0xFFFFFFFF):
                    self.imm.add(o.imm & 0xFFFFFFFF)
        for t in tails.values():
            self.add(t)

    def _sweep(self, a):
        """The instructions from `a` to its first `ret` or unconditional jump (what a function the explorer refused looks like)."""
        out = {}
        try:
            code = self.get(a, 0x2000)
        except Unsupported:
            return out
        for i in self.lifter.md.disasm(code, a):
            out[i.address] = i
            if i.mnemonic in ("ret", "jmp", "int3"):
                break
        return out

    def drain(self):
        while self.queue:
            a = self.queue.pop()
            if a in self.parsed or a in self.intrinsics:
                continue
            self._explore(a)

    # ---- pointers --------------------------------------------------------------------------------------------
    def _starts_like_a_function(self, t):
        try:
            b = self.get(t - 1, 7)
        except Unsupported:
            return False
        if b[1:3] == b"\xff\x25" and len(b) >= 7 and int.from_bytes(b[3:7], "little") in self.lifter.imports:
            return True         # the linker's stub for an import (`jmp [slot]`), which a program hands out as a function pointer
        return b[1:4] == PROLOGUE or (b[0] == 0xCC and b[1] != 0xCC and b[1] in START_BYTES)

    def _pointers_in_data(self):
        if self.data_pointers is None:
            found = set()
            for lo, hi in self.data:
                blob = self.get(lo, hi - lo)
                for off in range(0, len(blob) - 3, 4):
                    t = int.from_bytes(blob[off:off + 4], "little")
                    if self.in_code(t):
                        found.add(t)
            self.data_pointers = found
        return self.data_pointers

    def follow_pointers(self):
        """Constants of the code and pointers of the data that point at something that starts like a function and is not inside code found already."""
        new = False
        for t in sorted(self.imm | self._pointers_in_data()):
            if t in self.entries or self.covered(t) or not self._starts_like_a_function(t):
                continue
            new |= self.add(t)
        return new

    # ---- what nothing reaches --------------------------------------------------------------------------------
    def fill_gaps(self):
        """Functions in the code that nothing found so far reaches: at a prologue, or after the int3 fill, in bytes no function found covers."""
        new = False
        for lo, hi in self.gap_code:
            blob = self.get(lo, hi - lo)
            cands = set(m.start() for m in re.finditer(re.escape(PROLOGUE), blob))
            cands.update(m.start(1) for m in re.finditer(rb"\xcc{2,}([^\xcc])", blob) if m.group(1)[0] in START_BYTES)
            for off in sorted(cands):
                a = lo + off
                if a in self.entries or self.covered(a):
                    continue
                self.entries.add(a)
                self.queue.append(a)
                self.drain()
                if a in self.failed and self.failed[a].startswith(NOT_CODE):     # bytes that only look like a prologue
                    self.entries.discard(a)
                    del self.failed[a]
                    continue
                self.dead.add(a)
                new = True
        return new

    def run(self, roots):
        for r in roots:
            self.add(r)
        while True:
            self.drain()
            if self.follow_pointers():
                continue
            if self.fill_gaps():
                continue
            break
        return self.result()

    # ---- the answer ------------------------------------------------------------------------------------------
    def result(self):
        """{address: dict(name, nargs, size, dead)} for every function found (`dead`: nothing found reaches it)."""
        starts = sorted(self.entries)
        out = {}
        for k, a in enumerate(starts):
            end = next((hi for lo, hi in self.code if lo <= a < hi), a + 0x2000)
            if k + 1 < len(starts):
                end = min(end, starts[k + 1])
            size = max(1, min(end - a, 0x2000))
            if a in self.parsed:
                insns = self.parsed[a][0]
            elif a in self.intrinsics:
                insns = {}
            else:
                insns = {i.address: i for i in self.lifter.md.disasm(self.get(a, size), a)}
            pops = max((i.operands[0].imm for i in insns.values() if i.mnemonic == "ret" and i.operands), default=0)
            out[a] = dict(name="FUN_%08x" % a, nargs=max(self.lifter.stack_arguments(insns), pops // 4), size=size,
                         dead=a in self.dead)
        return out


def scan_pe(pe, lifter, getbytes, roots=()):
    """Find the functions of a PE program (see the module's docstring). `lifter.imports` must hold its imports already."""
    base = pe.OPTIONAL_HEADER.ImageBase
    code, data, gap = [], [], []
    for s in pe.sections:
        lo = base + s.VirtualAddress
        hi = lo + max(s.Misc_VirtualSize, s.SizeOfRawData)
        name = s.Name.rstrip(b"\0")
        if s.Characteristics & 0x20000000:
            code.append((lo, hi))
            gap.append((lo, hi))
        elif name == b"MPS_CODE":
            code.append((lo, hi))                  # the packer's own code: reached by calls, never searched for dead code
        if not s.Characteristics & 0x20000000 and name not in (b".reloc", b".idata", b".rsrc"):
            data.append((lo, hi))
    scan = Scan(lifter, getbytes, code, data, gap)
    return scan.run([base + pe.OPTIONAL_HEADER.AddressOfEntryPoint, *roots])


def scan_file(path, roots=()):
    """{address: dict(name, nargs, size, dead)} for the functions of the executable at `path` (what gen_handlers.py does first, for tools that only want the list)."""
    import pefile  # noqa: PLC0415
    from x86lift import Lifter  # noqa: PLC0415
    pe = pefile.PE(path)
    base = pe.OPTIONAL_HEADER.ImageBase
    sect = [(s.VirtualAddress + base, s.VirtualAddress + base + max(s.Misc_VirtualSize, s.SizeOfRawData)) for s in pe.sections]

    def getbytes(va, n):
        for lo, hi in sect:
            if lo <= va < hi:
                return pe.get_data(va - base, min(n, hi - va))
        raise Unsupported(f"0x{va:x} is not in the image")
    lifter = Lifter()
    for dll in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
        for imp in dll.imports:
            if imp.name:
                lifter.imports[imp.address] = imp.name.decode()
    return scan_pe(pe, lifter, getbytes, roots)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("exe")
    ap.add_argument("--roots", default="", help="more functions to start from: hex addresses, comma-separated")
    args = ap.parse_args()
    found = scan_file(args.exe, [int(x, 16) for x in args.roots.split(",") if x])
    for a in sorted(found):
        f = found[a]
        print(f"0x{a:08x} {f['name']} nargs={f['nargs']} size={f['size']}")
    print(f"{len(found)} functions", file=sys.stderr)


if __name__ == "__main__":
    main()

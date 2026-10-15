"""Where the guest spends its instructions: counts the instructions executed in each function of the original (the functions
tools/lift/fnscan.py finds in the program's own code), by block hooks, and writes a table when the run ends. With --native the replaced
functions run none, so what is left is what still runs as the original."""

import bisect
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(ROOT, "tools", "lift"))
from fnscan import scan_file  # noqa: E402


class Profile:
    def __init__(self, machine, gate=None):
        from unicorn import UC_HOOK_BLOCK  # noqa: PLC0415
        import capstone  # noqa: PLC0415
        self.m = machine
        exe = os.path.join(machine.game_root, "Program", os.path.basename(machine.exe_guest_path.replace("\\", "/")))   # the program being run
        funcs = sorted((a, f["name"], f["size"]) for a, f in scan_file(exe).items())
        self.starts = [f[0] for f in funcs]
        self.funcs = funcs
        self.insns = [0] * len(funcs)
        self.entries = [0] * len(funcs)
        self.blocks = {}
        self.gate = gate                    # address of a dword: instructions are also counted apart while it is non-zero
        self.gated = [0] * len(funcs)
        self.cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
        self.hook = machine.uc.hook_add(UC_HOOK_BLOCK, self._on_block, begin=self.starts[0], end=self.starts[-1] + 0x10000)

    def callers(self, address, nargs=3):
        """Also record, for each entry of the function at `address`, who called it and with which arguments."""
        from unicorn import UC_HOOK_CODE  # noqa: PLC0415
        from unicorn.x86_const import UC_X86_REG_ESP  # noqa: PLC0415
        seen = self.callers_seen = getattr(self, "callers_seen", {})
        table = seen[address] = {}

        def hit(uc, a, size, user):
            esp = uc.reg_read(UC_X86_REG_ESP)
            words = tuple(int.from_bytes(uc.mem_read(esp + 4 * k, 4), "little") for k in range(nargs + 1))
            key = (words[0],) + words[nargs:nargs + 1]            # return address and the last argument
            table[key] = table.get(key, 0) + 1
        self.m.uc.hook_add(UC_HOOK_CODE, hit, begin=address, end=address)

    def caller_report(self):
        out = []
        for a, table in getattr(self, "callers_seen", {}).items():
            out.append(f"callers of 0x{a:x}:")
            for (ret, last), n in sorted(table.items(), key=lambda kv: -kv[1])[:15]:
                i = bisect.bisect_right(self.starts, ret) - 1
                out.append(f"  {n:>8}  from 0x{ret:08x} in {self.funcs[i][1]} (0x{self.funcs[i][0]:x}), last argument 0x{last:x}")
        return "\n".join(out)

    def _on_block(self, uc, address, size, user):
        n = self.blocks.get(address)
        if n is None:
            n = self.blocks[address] = sum(1 for _ in self.cs.disasm(bytes(uc.mem_read(address, size)), address))
        i = bisect.bisect_right(self.starts, address) - 1
        if i >= 0:
            self.insns[i] += n
            if self.gate is not None and int.from_bytes(uc.mem_read(self.gate, 4), "little"):
                self.gated[i] += n
            if address == self.starts[i]:
                self.entries[i] += 1

    def report(self, top=40):
        lines = []
        for title, counts in (("in the original's functions", self.insns), ("while the gate is set", self.gated)):
            if counts is self.gated and self.gate is None:
                continue
            total = sum(counts)
            lines.append(f"guest instructions {title}: {total}")
            order = sorted(range(len(self.funcs)), key=lambda i: -counts[i])
            for i in order[:top]:
                if not counts[i]:
                    break
                a, name, size = self.funcs[i]
                e = self.entries[i]
                lines.append(f"{counts[i]:>12} {100 * counts[i] / total:5.1f}%  0x{a:08x} {name} ({size} bytes) entries {e}"
                             + (f" {counts[i] / e:.0f}/call" if e else ""))
        return "\n".join(lines)

    def dump(self, path):
        import json  # noqa: PLC0415
        json.dump([{"addr": a, "name": n, "size": s, "instructions": self.insns[i], "gated": self.gated[i], "entries": self.entries[i]}
                   for i, (a, n, s) in enumerate(self.funcs) if self.insns[i]], open(path, "w"), indent=1)

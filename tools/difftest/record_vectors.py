#!/usr/bin/env python3
"""
record_vectors.py - record difftest vectors from the original game running in tools/emu_spike's
emulator (this is the recorder docs/difftest's SPEC.md describes under "Recording vectors from the
original" and was previously "not implemented here").

For each sampled call of a native-implemented function it logs: the stack arguments, every byte the
function (or a callee) reads before writing it (memory_in), every byte it writes (memory_out,
exhaustive), the non-native calls it makes with their return value and writes (calls, replayed
verbatim by the harness), and its return value - one JSON file per call, in the format SPEC.md
defines. Calls are de-duplicated by a rough situation key (see `situation_key`) so a run yields a
few examples of each interesting case rather than thousands of near-identical ones.

Needs the user's own copy of the game (tools/emu_spike/README's sources/installed/...); nothing
recorded here is redistributed, only the numbers this script prints.

Usage:
    python3 record_vectors.py OUTDIR MAX_PER_SITUATION [emulator args...]

Example:
    python3 record_vectors.py tools/difftest/vectors/session1 2 \\
        --exe sources/installed/Magic/Program/DUEL.EXE --seconds 240 --script "..."

(--exe, --seconds and --script are tools/emu_spike/winemu/run.py's own options; see its --help and
docs/PORT_STRATEGY.md for a working script.)
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

S32 = lambda v: v - (1 << 32) if v & 0x80000000 else v  # noqa: E731


def load_layout(program):
    """Parse src/native/layout.c's LAYOUT_MAGIC/LAYOUT_DUEL, and engine.h's FN_*/CALLEE_* enum order,
    into {entry point address -> (native name, nargs)} and {callee address -> label}, so the
    recorder's tables cannot drift from what the native code actually calls (checked by
    test_difftest.py's test_record_vectors_tables_match_layout, which needs no emulator)."""
    layout_c = open(os.path.join(ROOT, "src", "native", "layout.c")).read()
    engine_h = open(os.path.join(ROOT, "src", "native", "engine.h")).read()
    m = re.search(r"const Layout LAYOUT_%s = \{(.*?)\n\};" % program, layout_c, re.S)
    block = m.group(1)

    def enum_order(typedef_name):
        # `[^{}]*` (not `.*?`) so this cannot skip past an earlier enum's own closing brace and swallow
        # two blocks into one match (there is more than one `typedef enum {` in this file).
        m = re.search(r"\{([^{}]*)\}\s*" + typedef_name + r";", engine_h, re.S)
        names = [ln.split(",")[0].split("/*")[0].strip() for ln in m.group(1).splitlines()
                 if ln.strip().startswith(("FN_", "CALLEE_"))]
        return [n for n in names if not n.endswith("_COUNT")]  # drop the FN_COUNT/CALLEE_COUNT sentinel

    entries = dict(re.findall(r"\[(FN_\w+)\]\s*=\s*(0x[0-9a-fA-F]+)", block))
    callees = dict(re.findall(r"\[(CALLEE_\w+)\]\s*=\s*(0x[0-9a-fA-F]+)", block))
    return entries, callees, enum_order("NativeFn"), enum_order("Callee")


# Native function name and argument count, in FN_* enum order (src/native/engine.h NATIVE_FUNCTIONS).
NATIVE_FUNCTIONS = [
    ("FN_QUERY_CARD_ATTRIBUTE", "Magic_QueryCardAttribute", 4),
    ("FN_IS_MANA_SOURCE", "Magic_IsManaSource", 2),
    ("FN_DROP_TOP_SPELL", "Magic_DropTopSpell", 0),
    ("FN_PUSH_SPELL_STACK", "Magic_PushSpellStack", 5),
    ("FN_CLEAR_SPELL_STACK", "Magic_ClearSpellStack", 0),
    ("FN_GET_COLOR_AND_TYPE_FLAGS", "Card_GetColorAndTypeFlags", 2),
    ("FN_PUSH_EVENT_CONTEXT", "Magic_PushEventContext", 0),
    ("FN_POP_EVENT_CONTEXT", "Magic_PopEventContext", 0),
    ("FN_CARD_IS_IN_PLAY", "Card_IsInPlay", 2),
    ("FN_COLOR_MASK_TO_INDEX", "Card_ColorMaskToColorIndex", 1),
    ("FN_REMAP_COLOR_INDEX_FF", "Card_RemapColorIndexFF", 3),
    ("FN_REMAP_COLOR_INDEX_F9", "Card_RemapColorIndexF9", 3),
    ("FN_AI_RECORD_CHOICE", "Ai_RecordChoice", 0),
    ("FN_AI_REPLAY_CHOICE", "Ai_ReplayChoice", 0),
    ("FN_AI_COMMIT_BEST_PLAN", "Ai_CommitBestPlan", 0),
    ("FN_AI_CLEAR_PLAN", "Ai_ClearPlan", 0),
    ("FN_AI_GET_PLAN_CURSOR", "Ai_GetPlanCursor", 0),
    ("FN_AI_PLAN_CURSOR_BACK", "Ai_PlanCursorBack", 0),
    ("FN_AI_PEEK_PLANNED_SLOT", "Ai_PeekPlannedSlot", 1),
    ("FN_AI_PEEK_PLANNED_CHOICE", "Ai_PeekPlannedChoice", 1),
    ("FN_AI_GET_LAND_COLOR_MASKS", "Ai_GetLandColorMasks", 2),
    ("FN_SCAN_CARDS", "Magic_ScanCards", 1),
    ("FN_CRT_MEMCPY", "Crt_Memcpy", 3),
    ("FN_AI_SAVE_GAME_STATE", "Ai_SaveGameState", 0),
    ("FN_AI_RESTORE_GAME_STATE", "Ai_RestoreGameState", 0),
    ("FN_AI_PUSH_BOARD_STATE", "Ai_PushBoardState", 0),
    ("FN_AI_POP_BOARD_STATE", "Ai_PopBoardState", 0),
    ("FN_AI_RESET_RANDOM_CURSOR", "Ai_ResetRandomCursor", 0),
    ("FN_AI_BEGIN_TRIAL", "Ai_BeginTrial", 0),
    ("FN_CRT_MEMSET", "Crt_Memset", 3),
    ("FN_AI_EVALUATE_BOARD", "Ai_EvaluateBoard", 1),
    ("FN_AI_PENALIZE_COUNTERATTACK", "Ai_PenalizeCounterattack", 2),
]
# Functions that return nothing: EAX on return is whatever was in the register, so the vector records 0
# (the harness does not compare a void function's return value).
VOID_FUNCTIONS = {"Magic_PushEventContext", "Magic_PopEventContext", "Ai_RecordChoice", "Ai_ReplayChoice",
                  "Ai_CommitBestPlan", "Ai_ClearPlan", "Ai_PlanCursorBack", "Ai_GetLandColorMasks",
                  "Magic_ScanCards", "Ai_SaveGameState", "Ai_RestoreGameState", "Ai_PushBoardState", "Ai_PopBoardState",
                  "Ai_ResetRandomCursor", "Ai_BeginTrial"}
# Callee label and argument count, in CALLEE_* enum order (src/native/card_query.c, spell_stack.c): the
# functions the native code still calls through the hook because they are not native yet.
CALLEES_INFO = [
    ("CALLEE_CARD_HANDLER", "card_handler", 3),
    ("CALLEE_SCAN_CHECK", "scan_check", 2),
    ("CALLEE_BROADCAST_CARD_EVENT", "Magic_BroadcastCardEvent", 3),
    ("CALLEE_COMBAT_DAMAGE_STEP", "combat_damage_step", 0),
    ("CALLEE_MARK_CARD", "mark_card", 3),
    ("CALLEE_AFTER_MARK", "after_mark", 0),
    ("CALLEE_FIND_FREE_SLOT", "find_free_slot", 2),
    ("CALLEE_AI_ATTACK_CHECK", "ai_attack_check", 6),
    ("CALLEE_AI_CARD_COST_CLASS", "ai_card_cost_class", 1),
    ("CALLEE_AI_PREROLL_RANDOM", "ai_preroll_random", 0),
]
# Callees with no fixed address (a card handler's address is read from the card's master record), so layout.c has no
# entry for them. They are recognised at the call instruction inside the native function instead (Recorder.handler_sites).
DYNAMIC_CALLEES = {"CALLEE_CARD_HANDLER"}
# Slot table base for the recorded program is read from layout.c at runtime (slot_base); the mode-flags
# dword the query function's caller reads a byte of (see PAD_DWORDS) is duel_mode_flags.
SLOT_PLAYER_STRIDE, SLOT_STRIDE = 0x5B20, 0x120


def regions(byte_map):
    """{addr: byte} -> [{'addr': '0x..', 'bytes': 'hex'}], merging contiguous runs."""
    out, cur = [], None
    for a in sorted(byte_map):
        if cur and a == cur[0] + len(cur[1]):
            cur[1].append(byte_map[a])
        else:
            cur = [a, bytearray([byte_map[a]])]
            out.append(cur)
    return [{"addr": "0x%08x" % a, "bytes": bytes(b).hex()} for a, b in out]


class Recorder:
    FRAME_BASELINE = 0x800   # bytes below ESP saved with a lifted handler's vector
    """Hooks every native function's entry in a running Machine and, for a sampled call, records its
    inputs/outputs as a vector. One Recorder per Machine; at most one call is being recorded at a
    time (a nested entry, through a callee, is not itself recorded)."""

    def __init__(self, m, outdir, max_per_situation, program, mode_flags_addr):
        self.m, self.uc, self.out, self.cap, self.program = m, m.uc, outdir, max_per_situation, program
        self.mode_flags_addr = mode_flags_addr
        self.count, self.rec, self.n = {}, None, 0
        entries, callees, _, _ = load_layout(program)
        self.funcs = {int(entries[fn], 16): (name, nargs) for fn, name, nargs in NATIVE_FUNCTIONS if fn in entries}
        self.callees = {int(callees[c], 16): (label, nargs) for c, label, nargs in CALLEES_INFO if c in callees}
        self.handler_sites = self.find_handler_sites(int(entries["FN_SCAN_CARDS"], 16), m.L_master_base + 0x10)
        # Ai_PenalizeCounterattack also calls a card's handler through the master table (two sites, for the power and toughness
        # bonuses of some cards)
        self.handler_sites.update(self.find_handler_sites(int(entries["FN_AI_PENALIZE_COUNTERATTACK"], 16), m.L_master_base + 0x10, 2400))
        # Lifted card handlers (tools/lift): each is a recordable function whose callees are exactly the calls its own
        # machine code makes (the spec lists them), so the vector holds every call out of the handler, native or not.
        self.handler_callees = {}
        self.no_return = set()   # lifted functions that leave EAX as the caller had it: the vector does not compare it
        self.debug_addr = int(os.environ["RECORD_DEBUG_ADDR"], 0) if os.environ.get("RECORD_DEBUG_ADDR") else None
        self.frame_sites = {}
        self.dump_ranges = [tuple(int(x, 0) for x in part.split(":")) for part in os.environ.get("RECORD_DUMP", "").split(",") if part]
        self.callee_alias = {}   # where a callee is hooked -> the address the vector reports it at
        spec = os.environ.get("RECORD_HANDLER_SPEC")
        if spec:
            for e in json.load(open(spec)):
                if e.get("lifted"):
                    addr = int(e["addr"], 16)
                    if e.get("returns_value") is False:
                        self.no_return.add(e["name"])
                    self.funcs[addr] = (e["name"], e.get("nargs", 3) if e.get("extra") else 3)
                    # An import is called through its slot in the import table: while a handler is injected the slot points
                    # at a stand-in (run.py), so the call is seen at the stand-in and reported as a call to the slot.
                    self.handler_callees[addr] = {int(c.get("stub") or c["addr"], 16): (c["name"], c["nargs"], c.get("cleanup", 0)) for c in e["calls"]}
                    self.callee_alias.update({int(c["stub"], 16): int(c["addr"], 16) for c in e["calls"] if c.get("stub")})
                    for site in e.get("dynamic_sites", []):   # a call through the master table inside the handler
                        site = int(site, 16)
                        self.handler_sites[site] = site + 7
        # With the lifted handlers part of the native layer, a native function that runs card handlers (the scan) has no
        # handler calls of its own to replay: the handlers run lifted, native functions they call run native, and what is
        # left to replay is every other function a handler can call. Nested handler calls are transparent, as nested
        # native calls are, so that is what the recording holds.
        self.lifted_handlers = bool(spec and os.environ.get("RECORD_LIFTED_HANDLERS"))
        if self.lifted_handlers:
            natives = {a for a in self.funcs if a not in self.handler_callees}
            union = {}
            for a, cs in self.handler_callees.items():
                union.update({k: v for k, v in cs.items() if k not in natives and k not in self.handler_callees})
            union.update({k: v for k, v in self.callees.items() if k not in natives and k not in self.handler_callees})
            for a in natives:
                self.handler_callees[a] = union
            # The scan's own handler calls are not callees now, but where the stack was when one was made is kept: a
            # lifted handler's uninitialised locals hold what the original's did, at the same addresses.
            self.frame_sites, self.handler_sites = self.handler_sites, {}
        self.all_natives = {a: v for a, v in self.funcs.items() if a not in self.handler_callees or self.lifted_handlers}
        if spec and os.environ.get("RECORD_ONLY_HANDLERS"):   # nothing but the lifted handlers: much faster
            self.funcs = {a: v for a, v in self.funcs.items() if a in self.handler_callees}
        if os.environ.get("RECORD_ONLY_NAMES"):   # e.g. Magic_ScanCards: record only these functions
            keep = set(os.environ["RECORD_ONLY_NAMES"].split(","))
            self.funcs = {a: v for a, v in self.funcs.items() if v[0] in keep}
        # The hooks that watch a call are installed once, here, and look at self.rec to see whether a call is being
        # recorded. Adding them at function entry (inside the entry hook) left the first stretch of the function
        # unwatched for a function that was starting on a new thread: reads of its arguments and locals went missing.
        # (A memory hook over the whole address space also makes Unicorn translate every block with memory-hook support.)
        self.uc.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, self.on_mem, begin=0, end=0xFFFFFFFF)
        watched = set(self.callees)
        for cs in self.handler_callees.values():
            watched.update(cs)
        for ca in watched:
            self.uc.hook_add(UC_HOOK_CODE, self.on_callee, begin=ca, end=ca)
        if os.environ.get("RECORD_NATIVE_TRACE"):   # every native function entered inside a recorded call, with its result
            for a in self.all_natives:
                if a not in self.handler_callees or self.lifted_handlers:
                    self.uc.hook_add(UC_HOOK_CODE, self.on_nested_native, begin=a, end=a)
        for site in self.handler_sites:
            self.uc.hook_add(UC_HOOK_CODE, self.on_handler_site, begin=site, end=site)
        for site in self.frame_sites:
            self.uc.hook_add(UC_HOOK_CODE, self.on_frame_site, begin=site, end=site)
        # Lifted code is checked on memory it reads below the stack pointer too (a local it reads before writing holds
        # whatever the stack held), so a recording made for the lifted handlers keeps those reads.
        self.frame_reads = bool(spec)
        self.m.kill_hooks.append(lambda: self.rec is not None and self.abandon())  # a thread ended without returning
        self.m.exit_hooks.append(self.on_return)   # a function started on its own thread returns to the thread-exit trap
        for addr in self.funcs:
            self.uc.hook_add(UC_HOOK_CODE, self.on_entry, begin=addr, end=addr)

    def find_handler_sites(self, entry, table, size=1024):
        """The `call dword ptr [reg*4 + table]` instructions in the scan (FF 14 85 imm32: how it calls a card's handler):
        {address of the call: address it returns to}. The scan is small, so its bytes are searched from the entry on."""
        code = bytes(self.uc.mem_read(entry, size))
        needle = b"\xff\x14\x85" + table.to_bytes(4, "little")
        sites, at = {}, code.find(needle)
        while at != -1:
            sites[entry + at] = entry + at + len(needle)
            at = code.find(needle, at + 1)
        assert sites, "no card-handler call found in the scan: the recorder cannot tell handler calls apart"
        return sites

    def situation_key(self, name, args):
        """A rough bucket so a run yields a few examples of each interesting case (a slot's flags, its
        card's colour and type, and whether the AI is thinking) rather than every one of a function's
        hundreds of thousands of calls. Not meant to be exhaustive, only to keep vector counts sane."""
        m = self.m
        if name in ("Magic_QueryCardAttribute", "Magic_IsManaSource", "Card_GetColorAndTypeFlags"):
            pl, sl = args[0], args[1]
            a = m.L_slot_base + pl * SLOT_PLAYER_STRIDE + sl * SLOT_STRIDE
            try:
                return (name, args[2] if name.startswith("Magic_Query") else 0, m.r32(a + 4),
                        m.r32(a + 0xC) & 2, m.r32(a + 0x3C) >> 24,
                        m.r32(m.L_event_depth) != 0, m.r32(m.L_is_ai_thinking))
            except Exception:
                return (name, "unreadable-slot")
        if name == "Magic_PushSpellStack":
            return (name, args[2], m.r32(m.L_is_ai_thinking), m.r32(m.L_spell_stack_count))
        if name == "Magic_DropTopSpell":
            return (name, m.r32(m.L_spell_stack_count))
        if name == "Card_IsInPlay":   # bucket by the flags the answer depends on, and by the answer itself
            try:
                a = m.L_slot_base + args[0] * SLOT_PLAYER_STRIDE + args[1] * SLOT_STRIDE
                return (name, m.r32(a + 4) == 0xFFFFFFFF, m.r32(a + 0xC) & 0xFF)
            except Exception:
                return (name, "unreadable-slot")
        if name in ("Card_ColorMaskToColorIndex",):
            return (name, args[0] & 0xFF)
        if name in ("Card_RemapColorIndexFF", "Card_RemapColorIndexF9"):
            return (name, args[2])
        if name in ("Magic_PushEventContext", "Magic_PopEventContext"):
            return (name, m.r32(m.L_event_context_depth))
        if name == "Crt_Memset":   # the size (exactly up to 64, then by magnitude), the alignment and whether the byte is zero
            dst, val, n = args
            return (name, n if n <= 64 else n.bit_length(), dst & 3, (val & 0xff) == 0)
        if name == "Crt_Memcpy":   # the size (exactly up to 64, then by magnitude), both alignments, and overlap
            dst, src, n = args
            return (name, n if n <= 64 else n.bit_length(), dst & 3, src & 3, dst > src and dst < src + n)
        if name.startswith("Ai_"):
            return self.ai_key(name, args)
        if name.startswith("Handler_"):   # one bucket per event: a handler does different things for different events
            if len(args) == 3:
                return (name, args[2])
            # a function that is not a card handler (tools/lift/ai_functions.txt): by whether the AI is thinking and by which
            # small values (players, slots, flags) its first arguments hold
            return (name, m.r32(m.L_is_ai_thinking), tuple(a if a < 4 else 4 for a in args[:4]))
        if name == "Magic_ScanCards":
            try:   # the event, how many cards are in the play order (0, 1, 2, 3 or more), and the nesting
                n = 0
                while n < 3 and m.r32(m.L_scan_order_player + 4 * n) != 0xFFFFFFFF:
                    n += 1
                return (name, args[0], n, m.r32(m.L_scan_depth))
            except Exception:
                return (name, "unreadable")
        return (name,)

    def ai_key(self, name, args):
        """Buckets for the AI plan functions: what decides their branches (the cursor, the first choice of each
        list, the thinking flag, the plan mode, the colour counts)."""
        m = self.m
        r = m.r32
        try:
            cursor = r(m.L_ai_cursor)
            thinking = r(m.L_is_ai_thinking) == 1
            trial0, best0 = r(m.L_ai_trial_choice) == 99, r(m.L_ai_best_choice) == 99
            here = r(m.L_ai_best_choice + 4 * cursor) if 0 <= cursor < 0x100 else None
            if name == "Ai_RecordChoice":
                return (name, r(m.L_ai_plan_mode), min(cursor, 2), cursor >= 0x100, trial0, best0)
            if name == "Ai_ReplayChoice":
                return (name, here == 99, min(cursor, 2), r(m.L_ai_plan_mode) != 0)
            if name == "Ai_CommitBestPlan":
                return (name, min(cursor, 3), best0)
            if name in ("Ai_PeekPlannedSlot", "Ai_PeekPlannedChoice"):
                return (name, thinking, args[0], here == 99)
            if name == "Ai_PlanCursorBack":
                return (name, min(cursor, 2))
            if name == "Ai_BeginTrial":
                return (name, thinking)
            if name in ("Ai_EvaluateBoard", "Ai_PenalizeCounterattack"):
                # who is evaluated, whether it is their turn, whether the search is running, and how many creatures there are
                counts = tuple(min(r(m.L_player_card_count + 4 * q), 3) for q in (0, 1))
                return (name, args[0], r(m.L_turn_player) == args[0], thinking, counts)
            if name == "Ai_GetPlanCursor":
                return (name, min(cursor, 3))
            if name == "Ai_GetLandColorMasks":
                bits = tuple(r(base + 4 * c) > 0 for base in (m.L_land_counts_x, m.L_land_counts_y) for c in range(1, 6))
                return (name, bits, args[0] == 0, args[1] == 0)
        except Exception:
            return (name, "unreadable")
        return (name,)

    def abandon(self):
        """Drop the recording in progress (its function never returned: a handler that blocked on a prompt, say)."""
        r, self.rec = self.rec, None
        print("   [recorder] abandoned %s (called at %.2fs, never returned)" % (r["name"], r["t"]), flush=True)
        for h in r["handles"]:
            try:
                self.uc.hook_del(h)
            except Exception:
                pass

    def on_entry(self, uc, address, size, user):
        if self.rec is not None:
            if self.m.vt - self.rec["t"] > 0.5:   # nothing legitimate takes half a virtual second
                self.abandon()
            else:
                return
        m = self.m
        esp = uc.reg_read(UC_X86_REG_ESP)
        name, nargs = self.funcs[address]
        args = [m.r32(esp + 4 + 4 * i) for i in range(nargs)]
        key = self.situation_key(name, args)
        if self.count.get(key, 0) >= self.cap:
            return
        self.count[key] = self.count.get(key, 0) + 1
        r = {"addr": address, "name": name, "args": args, "esp": esp, "ret": m.r32(esp),
             "callees": self.handler_callees.get(address, self.callees),
             "reads": {}, "writes": {}, "touched": set(), "calls": [], "depth": 0, "cur": None,
             "t": m.vt, "tid": m.cur.tid if m.cur else None, "handles": [], "lo": esp - 0x200000, "hi": esp + 4 + 4 * nargs}
        if self.mode_flags_addr is not None:
            # Superset padding: the query function's caller may re-check the mode-flags dword after a
            # recompute; the native code reads all 4 bytes where a given original call might read fewer.
            base = self.mode_flags_addr
            r["pad"] = {base + i: m.r32(base) >> (8 * i) & 0xFF for i in range(4)}
        else:
            r["pad"] = {}
        if self.frame_reads:
            # The stack below ESP as the call found it: a local the function reads before writing holds whatever was
            # there. Unicorn does not report every such read, so the frame is kept whole rather than found read by read.
            base = esp - self.FRAME_BASELINE
            r["pad"].update({base + i: b for i, b in enumerate(self.uc.mem_read(base, self.FRAME_BASELINE))})
        self.rec = r
        if self.debug_addr is not None and r["tid"] != 3:
            print("   [recorder] start %s tid %s esp %#x eip %#x" % (name, r["tid"], esp, uc.reg_read(UC_X86_REG_EIP)), flush=True)
        r["handles"].append(uc.hook_add(UC_HOOK_CODE, self.on_return, begin=r["ret"], end=r["ret"]))

    def on_mem(self, uc, access, address, size, value, user):
        r = self.rec
        if r is not None and self.m.vt - r["t"] > 0.5:
            self.abandon()   # a recording that never returns must not keep these hooks (and the slowdown) for the rest of the run
            return
        if r is None or self.foreign(r):
            return
        if self.debug_addr is not None and r["tid"] != 3 and self.m.cur.tid == r["tid"]:
            print("   [recorder] %s of %#x in %s thread %s eip %#x" % ("write" if access == UC_MEM_WRITE else "read", address, r["name"], r["tid"], uc.reg_read(UC_X86_REG_EIP)), flush=True)
        if self.debug_addr is not None and address <= self.debug_addr < address + size:
            print("   [recorder] %s of %#x (%d bytes) in %s, thread %s, depth %d" % ("write" if access == UC_MEM_WRITE else "read",
                  address, size, r["name"], self.m.cur.tid, r["depth"]), flush=True)
        in_frame = r["lo"] <= address < r["hi"]
        if in_frame and not self.frame_reads:
            return  # the caller's stack frame: native code keeps locals in C variables, not memory
        if access == UC_MEM_WRITE:
            data = (value & ((1 << (8 * size)) - 1)).to_bytes(size, "little")
            for i in range(size):
                a = address + i
                if self.frame_reads and r["depth"] == 0 and a not in r["touched"] and a not in r["reads"]:
                    # The hook runs before the store, so this is the byte's old value. Unicorn reports no read for the
                    # load half of a read-modify-write instruction (`add [mem], reg`), so for lifted code the old
                    # value of whatever is stored to is kept as input in case the instruction used it.
                    r["reads"][a] = self.uc.mem_read(a, 1)[0]
                if r["depth"]:
                    c = r["cur"]
                    # A callee's stores count unless they are its own stack; for lifted code the caller's locals (an
                    # output parameter points at one) count too, which are above the callee's arguments.
                    if not in_frame or (self.frame_reads and a >= c["esp"] + 4 + 4 * len(c["args"])):
                        c["writes"][a] = data[i]
                elif not in_frame:
                    r["writes"][a] = data[i]
                r["touched"].add(a)
        elif r["depth"] == 0:
            if in_frame and address >= r["esp"]:
                return  # the return address and the arguments: the harness provides these
            for i in range(size):
                a = address + i
                if a not in r["touched"] and a not in r["reads"]:
                    r["reads"][a] = self.uc.mem_read(a, 1)[0]

    def foreign(self, r):
        """True while another guest thread runs: its calls and memory accesses are not part of this recording."""
        return self.m.cur is None or self.m.cur.tid != r["tid"]

    def on_callee(self, uc, address, size, user):
        r = self.rec
        if r is None or r["depth"] != 0 or self.foreign(r):
            return
        esp = uc.reg_read(UC_X86_REG_ESP)
        if address not in r["callees"]:
            return   # watched for another function's recording
        name, nargs, *rest = r["callees"][address]
        c = {"callee": address, "name": name, "args": [self.m.r32(esp + 4 + 4 * i) for i in range(nargs)],
             "writes": {}, "ret": self.m.r32(esp), "esp": esp, "pops": rest[0] if rest else 0}   # `ret imm16` callees pop their own arguments
        r["cur"], r["depth"] = c, 1
        r["handles"].append(uc.hook_add(UC_HOOK_CODE, self.on_callee_return, begin=c["ret"], end=c["ret"]))

    def on_nested_native(self, uc, address, size, user):
        r = self.rec
        if r is None or self.foreign(r) or address == r["addr"]:
            return
        name, nargs = self.all_natives[address]
        esp = uc.reg_read(UC_X86_REG_ESP)
        entry = [name] + [S32(self.m.r32(esp + 4 + 4 * i)) for i in range(nargs)] + ["->"]
        r.setdefault("native_trace", []).append(entry)
        ret, handle = self.m.r32(esp), []

        def on_ret(uc2, a2, s2, u2):
            if uc2.reg_read(UC_X86_REG_ESP) == esp + 4 and entry[-1] == "->":   # the first return only
                entry.append(S32(uc2.reg_read(UC_X86_REG_EAX)))
        handle.append(uc.hook_add(UC_HOOK_CODE, on_ret, begin=ret, end=ret))
        r.setdefault("trace_handles", []).append(handle[0])

    def on_frame_site(self, uc, address, size, user):
        """About to run `call [eax*4 + table]` in the scan with lifted handlers: where the handler's frame will start."""
        r = self.rec
        if r is not None and r["depth"] == 0 and not self.foreign(r):
            esp = uc.reg_read(UC_X86_REG_ESP)
            r.setdefault("handler_esp", esp - 4)
            # which handler ran, for what, and how many calls had been made before it: to find where a lifted run diverges
            target = self.m.r32(self.m.L_master_base + 0x10 + 4 * uc.reg_read(UC_X86_REG_EAX))
            r.setdefault("handler_log", []).append(["0x%08x" % target] + [S32(self.m.r32(esp + 4 * i)) for i in range(3)] + [len(r["calls"])])
            if self.dump_ranges:   # memory as each handler starts, for lining up against a lifted run (tools/lift/scan_diff.py)
                r.setdefault("handler_dumps", []).append([bytes(self.uc.mem_read(a, n)).hex() for a, n in self.dump_ranges])

    def on_handler_site(self, uc, address, size, user):
        """About to execute `call [eax*4 + table]` for a card's handler: its address, and the three arguments already on
        the stack (player, slot, event), before the call pushes the return address."""
        r = self.rec
        if r is None or r["depth"] != 0 or self.foreign(r):
            return
        esp = uc.reg_read(UC_X86_REG_ESP)
        pointer = self.m.L_master_base + 0x10 + 4 * uc.reg_read(UC_X86_REG_EAX)
        target = self.m.r32(pointer)
        # The scan reads this function pointer (it is the call's own operand), but the call instruction runs after the
        # depth is switched to "inside a callee", where reads are not recorded: record the read here, as the scan's own.
        for i in range(4):
            if pointer + i not in r["touched"] and pointer + i not in r["reads"]:
                r["reads"][pointer + i] = self.uc.mem_read(pointer + i, 1)[0]
        c = {"callee": target, "name": "card_handler", "args": [self.m.r32(esp + 4 * i) for i in range(3)],
             "writes": {}, "ret": self.handler_sites[address], "esp": esp - 4}
        r["cur"], r["depth"] = c, 1
        r["handles"].append(uc.hook_add(UC_HOOK_CODE, self.on_callee_return, begin=c["ret"], end=c["ret"]))

    def on_callee_return(self, uc, address, size, user):
        r = self.rec
        if r is None or r["depth"] != 1 or r["cur"] is None or self.foreign(r) or uc.reg_read(UC_X86_REG_ESP) != r["cur"]["esp"] + 4 + r["cur"].get("pops", 0):
            return
        c = r["cur"]
        c["return"] = S32(uc.reg_read(UC_X86_REG_EAX))
        # What the callee left in memory, now: the function may change the same bytes again after the call returns, and the
        # replay must apply the callee's own values, not the final ones.
        c["final"] = {a: self.uc.mem_read(a, 1)[0] for a in c["writes"]}
        r["calls"].append(c)
        r["cur"], r["depth"] = None, 0

    def on_return(self, uc, address, size, user):
        r = self.rec
        if r is None or r["depth"] != 0 or self.foreign(r) or uc.reg_read(UC_X86_REG_ESP) != r["esp"] + 4:
            return
        for h in r["handles"]:
            try:
                uc.hook_del(h)
            except Exception:
                pass
        self.rec = None
        for h in r.get("trace_handles", []):
            try:
                uc.hook_del(h)
            except Exception:
                pass
        if self.debug_addr is not None and r["tid"] != 3:
            print("   [recorder] return %s tid %s reads %d" % (r["name"], r["tid"], len(r["reads"])), flush=True)
        eax = uc.reg_read(UC_X86_REG_EAX)
        out = {a: self.uc.mem_read(a, 1)[0] for a in r["writes"]}
        calls = [{"callee": "0x%08x" % self.callee_alias.get(c["callee"], c["callee"]), "name": c["name"], "args": [S32(x) for x in c["args"]],
                  "return": c["return"], "memory_writes": regions(c["final"])}
                 for c in r["calls"]]
        v = {"function": r["name"], "program": self.program, "address": "0x%08x" % r["addr"],
             "description": "recorded from %s at virtual %.3fs" % (self.program, r["t"]),
             "source": "tools/difftest/record_vectors.py (emulator recording)",
             "args": [S32(x) for x in r["args"]], "stack_pointer": r["esp"],
             "expected_return": 0 if r["name"] in VOID_FUNCTIONS or r["name"] in self.no_return else S32(eax),
             "memory_in": regions({**r["pad"], **r["reads"]}), "calls": calls,
             "memory_out_expected": regions(out), "memory_out_exhaustive": True}
        if r["name"] in self.no_return:
            v["return_bits"] = 0
        if self.lifted_handlers and not r["name"].startswith("Handler_"):
            v["lifted_handlers"] = True
            if "handler_esp" in r:
                v["handler_stack_pointer"] = r["handler_esp"]
            if "handler_log" in r:
                v["handler_log"] = r["handler_log"]
            if "handler_dumps" in r:
                v["handler_dumps"] = r["handler_dumps"]
            if "native_trace" in r:
                v["native_trace"] = r["native_trace"]
        self.n += 1
        json.dump(v, open(os.path.join(self.out, "%s_%04d.json" % (r["name"], self.n)), "w"), indent=1)


def main():
    # Imported here, not at module level, so load_layout() and the vector-format helpers above can be
    # unit-tested (test_difftest.py) without unicorn or the game files installed.
    global UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_WRITE, UC_X86_REG_EAX, UC_X86_REG_ESP, UC_X86_REG_EIP
    sys.path.insert(0, os.path.join(ROOT, "tools", "emu_spike"))
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_WRITE
    from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_EIP, UC_X86_REG_ESP
    from winemu import run as runmod

    outdir, cap = sys.argv[1], int(sys.argv[2])
    os.makedirs(outdir, exist_ok=True)
    program = "MAGIC" if "MAGIC.EXE" in " ".join(sys.argv) else "DUEL"

    orig_machine = runmod.Machine

    class RecordingMachine(orig_machine):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            layout_c = open(os.path.join(ROOT, "src", "native", "layout.c")).read()
            block = re.search(r"const Layout LAYOUT_%s = \{(.*?)\n\};" % program, layout_c, re.S).group(1)

            def addr(field):
                m = re.search(r"\.%s\s*=\s*(0x[0-9a-fA-F]+)" % field, block)
                return int(m.group(1), 16) if m else None

            self.L_slot_base = addr("slot_base")
            self.L_event_depth = addr("event_depth")
            self.L_is_ai_thinking = addr("is_ai_thinking")
            self.L_spell_stack_count = addr("spell_stack_count")
            self.L_event_context_depth = addr("event_context_depth")
            for field in ("ai_cursor", "ai_trial_choice", "ai_best_choice", "ai_plan_mode", "land_counts_x", "land_counts_y",
                          "scan_order_player", "scan_depth", "master_base", "player_card_count", "turn_player"):
                setattr(self, "L_" + field, addr(field))
            self.recorder = Recorder(self, outdir, cap, program, addr("duel_mode_flags"))

    runmod.Machine = RecordingMachine
    sys.argv = [sys.argv[0]] + sys.argv[3:]
    runmod.main()


if __name__ == "__main__":
    main()

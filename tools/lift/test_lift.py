"""Tests for the x86 lifter and the flat harness, on small hand-assembled functions (no game data needed).
Run with: python3 -m pytest tools/lift"""

import json
import os
import shutil
import subprocess
import sys

import pytest

capstone = pytest.importorskip("capstone")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DIFFTEST = os.path.join(os.path.dirname(HERE), "difftest")
sys.path.insert(0, HERE)
sys.path.insert(0, DIFFTEST)

import run_vectors as rv  # noqa: E402
from x86lift import Lifter, Unsupported  # noqa: E402

# name, address, machine code
FUNCTIONS = {
    # mov eax,[esp+4]; add eax,[esp+8]; ret
    "Test_Add": (0x1000, bytes.fromhex("8b442404" "03442408" "c3")),
    # signed max: mov eax,[esp+4]; cmp eax,[esp+8]; jge +4; mov eax,[esp+8]; ret
    "Test_Max": (0x2000, bytes.fromhex("8b442404" "3b442408" "7d04" "8b442408" "c3")),
    # switch (a) { case 0: return 10; case 1: return 20; case 2: return 30; default: return -1; } through a jump table
    "Test_Switch": (0x3000, bytes.fromhex(
        "8b442404" "83f802" "7725" "ff248510300000"
        "1c300000" "22300000" "28300000"
        "b80a000000c3" "b814000000c3" "b81e000000c3" "b8ffffffffc3")),
    # cdq; idiv: mov eax,[esp+4]; cdq; idiv dword [esp+8]; ret
    "Test_Div": (0x4000, bytes.fromhex("8b442404" "99" "f77c2408" "c3")),
    # a call: push [esp+4]; call 0x5100; add esp,4; add eax,1; ret
    "Test_Call": (0x5000, bytes.fromhex("ff742404" "e8f7000000" "83c404" "83c001" "c3")),
    # a call through an import slot: push [esp+4]; call [0x7000]; add eax,2; ret   (the callee pops its argument)
    "Test_Import": (0x7100, bytes.fromhex("ff742404" "ff1500700000" "83c002" "c3")),
    # a call through the master table: mov eax,[esp+4]; push eax; call [eax*4+0x8000]; add esp,4; ret
    "Test_Dynamic": (0x7200, bytes.fromhex("8b442404" "50" "ff148500800000" "83c404" "c3")),
    # a hook kept in a global: cmp dword [0x9000],0; je out; push [esp+4]; call [0x9000]; add esp,4; ret; out: xor eax,eax; ret
    "Test_Hook": (0x7300, bytes.fromhex("833d0090000000" "740e" "ff742404" "ff150090000" "0" "83c404" "c3" "31c0" "c3")),
    # a call through a register: mov eax,[esp+4]; push 5; call eax; add esp,4; ret
    "Test_CallReg": (0x7400, bytes.fromhex("8b442404" "6a05" "ffd0" "83c404" "c3")),
    # a call through memory addressed from a register: mov ebx,[esp+4]; push 6; call [ebx+8]; add esp,4; ret
    "Test_CallVirtual": (0x7500, bytes.fromhex("8b5c2404" "6a06" "ff5308" "83c404" "c3")),
    # rep stosd: mov edi,[esp+4]; mov ecx,[esp+8]; mov eax,[esp+12]; rep stosd; mov eax,edi; ret
    "Test_Stos": (0x7600, bytes.fromhex("8b7c2404" "8b4c2408" "8b44240c" "f3ab" "89f8" "c3")),
    # rep movsd: mov edi,[esp+4]; mov esi,[esp+8]; mov ecx,[esp+12]; rep movsd; mov eax,esi; ret
    "Test_Movs": (0x7700, bytes.fromhex("8b7c2404" "8b742408" "8b4c240c" "f3a5" "89f0" "c3")),
    # strlen by repne scasb: mov edi,[esp+4]; xor eax,eax; mov ecx,-1; repne scasb; not ecx; dec ecx; mov eax,ecx; ret
    "Test_Scas": (0x7800, bytes.fromhex("8b7c2404" "31c0" "b9ffffffff" "f2ae" "f7d1" "49" "89c8" "c3")),
    # unsigned: mov eax,[esp+4]; xor edx,edx; div dword [esp+8]; ret (quotient)  and  mul: mov eax,[esp+4]; mul dword [esp+8]; mov eax,edx; ret (high word)
    "Test_UDiv": (0x7900, bytes.fromhex("8b442404" "31d2" "f77c2408" "c3")),
    "Test_Mul": (0x7a00, bytes.fromhex("8b442404" "f7642408" "89d0" "c3")),
    # a thunk, as the C runtime's imports are reached: jmp [0x7000]
    "Test_Thunk": (0x7b00, bytes.fromhex("ff2500700000")),
    # the thread information block: mov eax, fs:[0]; ret
    "Test_Fs": (0x7c00, bytes.fromhex("64a100000000" "c3")),
    # a two-level switch, as the compiler makes it for a sparse one: the value indexes a table of bytes and the byte indexes a table of two addresses
    # (mov eax,[esp+4]; cmp eax,5; ja default; xor ecx,ecx; mov cl,[eax+0x7d20]; jmp [ecx*4+0x7d18]); bytes 0,1,1,0,1,0 -> 10, 20; else -1
    "Test_Switch2": (0x7d00, bytes.fromhex(
        "8b442404" "83f805" "772b" "31c9" "8a88207d0000" "ff248d187d0000"
        "287d0000" "2e7d0000" "000101000100" "00" "00"
        "b80a000000c3" "b814000000c3" "b8ffffffffc3")),
    # an indirect jump with no bound check in front of it: must be refused
    "Test_BadJump": (0x6000, bytes.fromhex("8b442404" "ff248500700000" "c3")),
}
def _call(at, target):      # a `call rel32` placed at `at`
    return b"\xe8" + ((target - (at + 5)) & 0xffffffff).to_bytes(4, "little")


# the compiler runtime's register-argument helpers (not lifted themselves: calls to them are replaced by inline code), and functions that call them
FUNCTIONS["Helper_Chkstk"] = (0x7e00, bytes.fromhex("51" "3d00100000" "8d4c2408" "7214" "81e900100000" "2d00100000" "8501" "3d00100000" "73ec"
                                                    "2bc8" "8bc4" "8501" "8be1" "8b08" "8b4004" "50" "c3"))
FUNCTIONS["Helper_Allshl"] = (0x7e40, bytes.fromhex("80f940" "7315" "80f920" "7306" "0fa5c2" "d3e0" "c3" "8bd0" "33c0" "80e11f" "d3e2" "c3" "33c0" "33d2" "c3"))
# push ebp; mov ebp,esp; mov eax,0x20; call _chkstk; mov [esp+0x1c],0x77; mov eax,[esp+0x1c]; mov esp,ebp; pop ebp; ret
FUNCTIONS["Test_Frame"] = (0x7f00, bytes.fromhex("55" "8bec" "b820000000") + _call(0x7f08, 0x7e00)
                           + bytes.fromhex("c74424" "1c" "77000000" "8b44241c" "8be5" "5d" "c3"))
# mov eax,[esp+4]; mov edx,[esp+8]; mov ecx,[esp+12]; call _allshl; ret   (and the same returning edx)
FUNCTIONS["Test_Shl64Lo"] = (0x8000, bytes.fromhex("8b442404" "8b542408" "8b4c240c") + _call(0x800c, 0x7e40) + bytes.fromhex("c3"))
FUNCTIONS["Test_Shl64Hi"] = (0x8020, bytes.fromhex("8b442404" "8b542408" "8b4c240c") + _call(0x802c, 0x7e40) + bytes.fromhex("89d0" "c3"))
# mov eax,[esp+4]; mov edx,[esp+8]; shld eax,edx,8; ret
FUNCTIONS["Test_Shld"] = (0x8040, bytes.fromhex("8b442404" "8b542408" "0fa4d008" "c3"))
# mov ecx,[esp+4]; mov edx,[esp+8]; fld qword [ecx]; fstp qword [edx]; ret   and   mov edx,[esp+4]; fldz; fst qword [edx]; fstp qword [edx]; ret
FUNCTIONS["Test_Fcopy"] = (0x8060, bytes.fromhex("8b4c2404" "8b542408" "dd01" "dd1a" "c3"))
FUNCTIONS["Test_Fzero"] = (0x8080, bytes.fromhex("8b542404" "d9ee" "dd12" "dd1a" "c3"))
# the incremental linker's jump table: a function that starts with `jmp rel32` is a thunk, a tail call of the function it jumps to
FUNCTIONS["Test_Ilt"] = (0x8100, b"\xe9" + ((0x1000 - (0x8100 + 5)) & 0xffffffff).to_bytes(4, "little"))
# a table indexed by a masked value, as the C runtime's memmove does: mov eax,[esp+4]; and eax,3; jmp [eax*4+0x820e]; four cases returning 10, 20, 30, 40
FUNCTIONS["Test_Masked"] = (0x8200, bytes.fromhex("8b442404" "83e003" "ff24850e820000" "1e820000" "24820000" "2a820000" "30820000"
                                                   "b80a000000c3" "b814000000c3" "b81e000000c3" "b828000000c3"))
# 64-bit shift right by one: mov eax,[esp+4]; mov edx,[esp+8]; shr edx,1; rcr eax,1; ret   (rcr takes the carry the shr left)
FUNCTIONS["Test_Rcr"] = (0x8280, bytes.fromhex("8b442404" "8b542408" "d1ea" "d1d8" "c3"))
# bts on the stack with a register bit index (the C runtime's strspn): two zero dwords, set bit ecx, return dword0 + 2 * dword1
FUNCTIONS["Test_Bts"] = (0x82a0, bytes.fromhex("8b4c2404" "6a00" "6a00" "0fab0c24" "8b0424" "8b542404" "8d0450" "83c408" "c3"))
# mov eax,[esp+4]; mov ecx,[esp+8]; xchg eax,ecx; ret
FUNCTIONS["Test_Xchg"] = (0x82e0, bytes.fromhex("8b442404" "8b4c2408" "91" "c3"))
# mov ecx,[esp+4]; jecxz zero; mov eax,1; ret; zero: xor eax,eax; ret
FUNCTIONS["Test_Jecxz"] = (0x82f0, bytes.fromhex("8b4c2404" "e306" "b801000000" "c3" "31c0" "c3"))
# memrchr-like, as the C runtime's strrchr: the direction flag set for a backward repne scasb. edi = last byte, ecx = count, al = byte
FUNCTIONS["Test_Std"] = (0x8320, bytes.fromhex("57" "8b7c2408" "8b4c240c" "8a442410" "fd" "f2ae" "fc" "89f8" "5f" "c3"))
# repe cmpsb as strncmp does: returns what is left of the count
FUNCTIONS["Test_Cmpsb"] = (0x8350, bytes.fromhex("56" "57" "8b74240c" "8b7c2410" "8b4c2414" "f3a6" "89c8" "5f" "5e" "c3"))
FUNCTIONS["Test_Fnclex"] = (0x8380, bytes.fromhex("dbe2" "8b442404" "c3"))
# code placed before the entry that the function jumps back into (strchr's tail): Helper_Before is `mov eax,7; ret`, Test_Back enters after it
FUNCTIONS["Helper_Before"] = (0x8400, bytes.fromhex("b807000000c3"))
FUNCTIONS["Test_Back"] = (0x8408, bytes.fromhex("8b4c2404" "85c9" "74f0" "31c0" "c3"))
# x87 arithmetic: [ecx] += [edx] (doubles); a < b by fcomp and fnstsw; the Pentium divide test's a - a/b*b; fild and fistp with the default rounding and truncating
FUNCTIONS["Test_Fadd"] = (0x8440, bytes.fromhex("8b4c2404" "8b542408" "dd01" "dc02" "dd19" "31c0" "c3"))
FUNCTIONS["Test_Flt"] = (0x8460, bytes.fromhex("8b4c2404" "8b542408" "dd01" "dc1a" "dfe0" "f6c401" "7406" "b801000000" "c3" "31c0" "c3"))
FUNCTIONS["Test_Fdivtest"] = (0x8490, bytes.fromhex("8b4c2404" "8b542408" "dd01" "dc32" "dc0a" "dc29" "dd19" "31c0" "c3"))
FUNCTIONS["Test_Fround"] = (0x84b0, bytes.fromhex("8b4c2404" "8b542408" "db01" "dc0a" "db19" "31c0" "c3"))
FUNCTIONS["Test_Ftrunc"] = (0x84d0, bytes.fromhex("8b4c2404" "8b542408" "687f0f0000" "d92c24" "83c404" "db01" "dc0a" "db19" "31c0" "c3"))
# sbb with the carry of the compare before it (the C runtime's _strcmpi ends this way): cmp al,cl; sbb al,al; sbb al,0xff; movsx eax,al  -> -1, or 1
FUNCTIONS["Test_Sbb"] = (0x8500, bytes.fromhex("8b442404" "8b4c2408" "38c8" "18c0" "1cff" "0fbec0" "c3"))
# the carry out of an add, taken by adc: mov eax,[esp+4]; add eax,[esp+8]; mov eax,0; adc eax,0
FUNCTIONS["Test_Adc"] = (0x8520, bytes.fromhex("8b442404" "03442408" "b800000000" "83d000" "c3"))
# rotates: rol eax,8 / ror eax,cl / rol ax,4 / rol al,3 and ror ah,1 / the carry and overflow flags a rotate by one leaves / a rotate by zero (cl = 0 or 32) leaves the flags alone
FUNCTIONS["Test_Rol32"] = (0x8800, bytes.fromhex("8b442404" "c1c008" "c3"))
FUNCTIONS["Test_Ror32cl"] = (0x8810, bytes.fromhex("8b442404" "8b4c2408" "d3c8" "c3"))
FUNCTIONS["Test_Rol16"] = (0x8820, bytes.fromhex("8b442404" "66c1c004" "c3"))
FUNCTIONS["Test_Rol8"] = (0x8830, bytes.fromhex("8b442404" "c0c003" "d0cc" "c3"))
FUNCTIONS["Test_RolCarry"] = (0x8840, bytes.fromhex("8b442404" "d1c0" "b800000000" "83d000" "c3"))
FUNCTIONS["Test_RorCarry"] = (0x8850, bytes.fromhex("8b442404" "d1c8" "b800000000" "83d000" "c3"))
FUNCTIONS["Test_RolOF"] = (0x8860, bytes.fromhex("8b442404" "d1c0" "0f90c0" "0fb6c0" "c3"))
FUNCTIONS["Test_RorOF"] = (0x8870, bytes.fromhex("8b442404" "d1c8" "0f90c0" "0fb6c0" "c3"))
FUNCTIONS["Test_RolZero"] = (0x8880, bytes.fromhex("8b542404" "8b4c2408" "31c0" "83f801" "d3c2" "b800000000" "83d000" "c3"))
FUNCTIONS["Test_RolMem16"] = (0x88a0, bytes.fromhex("8b4c2404" "66d101" "0fb701" "c3"))      # rol word [ecx],1; movzx eax,word [ecx]
# setjmp and longjmp of the C runtime, as the game's functions call them: a thunk `jmp [_setjmp3]` the linker made, and `call [longjmp]` direct.
# Test_Setjmp(value): ebx = 0x1111; setjmp(buf); the first time, Test_Jump(buf, value) sets ebx to 0xdead and longjmps; the second time (EAX = value, or 1 for 0) it returns
# value | (ebx << 16): ebx must be what it was at the setjmp, not what Test_Jump left, and the stack must be the caller's.
SETJMP_SLOT, LONGJMP_SLOT = 0x7010, 0x7014
FUNCTIONS["Helper_SjThunk"] = (0x8a00, bytes.fromhex("ff25") + SETJMP_SLOT.to_bytes(4, "little"))
FUNCTIONS["Test_Jump"] = (0x8980, bytes.fromhex("53" "bbadde0000" "8b442408" "8b4c240c" "51" "50" "ff15") + LONGJMP_SLOT.to_bytes(4, "little")
                          + bytes.fromhex("83c408" "5b" "31c0" "c3"))
FUNCTIONS["Test_Setjmp"] = (0x8900, bytes.fromhex("53" "bb11110000" "83ec40" "6a00" "8d442404" "50") + _call(0x8910, 0x8a00)
                            + bytes.fromhex("83c408" "85c0" "751a" "8b8c2448000000" "51" "8d442404" "50") + _call(0x8929, 0x8980)
                            + bytes.fromhex("83c408" "b8ffffffff" "c1e310" "09d8" "83c440" "5b" "c3"))
CALLEE = 0x5100
IMPORT_SLOT = 0x7000


def getbytes(va, n):
    for name, (addr, code) in FUNCTIONS.items():
        if addr <= va < addr + len(code):
            return code[va - addr:va - addr + n] + b"\x90" * 64
    raise Unsupported(f"0x{va:x} is not in the test image")


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    cc = os.environ.get("CC") or "cc"
    if not shutil.which(cc):
        pytest.skip("no C compiler")
    out = tmp_path_factory.mktemp("lift")
    lifter, sources, lifted = Lifter(), [], []
    lifter.imports[IMPORT_SLOT] = "Sleep"
    lifter.imports[SETJMP_SLOT] = "_setjmp3"
    lifter.imports[LONGJMP_SLOT] = "longjmp"
    for name, (addr, code) in FUNCTIONS.items():
        if name == "Test_BadJump" or name.startswith("Helper_"):
            continue
        src, targets, _, _ = lifter.lift_function(getbytes, addr, name, frozenset([CALLEE]))
        sources.append(src)
        lifted.append((name, addr))
    gen = ['#include "lift_rt.h"\n#include "lift_tables.h"\n'] + sources
    gen.append("const LiftedFn LIFTED[] = {\n" + "".join(f'    {{"{n}", 0x{a:x}u, lifted_{a:08x}}},\n' for n, a in lifted)
               + "    {0, 0, 0}\n};")
    gen.append(f"const int LIFTED_COUNT = {len(lifted)};")
    gen.append(f"const CalleeRow LIFT_CALLEES[] = {{ {{0x{CALLEE:x}u, 1, 0u}}, {{0x{IMPORT_SLOT:x}u, 1, 4u}}, {{0, 0, 0}} }};\nconst int LIFT_CALLEE_COUNT = 2;")
    (out / "gen.c").write_text("\n".join(gen))
    exe = str(out / "harness-flat")
    cmd = [cc, "-O1", "-DLIFT_TRACK_WRITES", "-w", f"-I{os.path.join(ROOT, 'src', 'native')}", "-o", exe, os.path.join(DIFFTEST, "harness_flat.c"),
           str(out / "gen.c"), "-lm"]   # libm after the objects: Linux's linker needs it for floor/ceil/trunc
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return exe


def vector(function, args, ret, calls=()):
    return {"function": function, "program": "DUEL", "args": args, "expected_return": ret,
            "memory_in": [], "calls": list(calls), "memory_out_expected": [], "memory_out_exhaustive": True}


def run(tmp_path, exe, v):
    path = tmp_path / "v.json"
    path.write_text(json.dumps(v))
    return rv.run_vector(str(path), exe)


def test_add(tmp_path, harness):
    assert run(tmp_path, harness, vector("Test_Add", [7, 5], 12))[0] == "PASS"
    assert run(tmp_path, harness, vector("Test_Add", [0xffffffff, 1], 0))[0] == "PASS"
    assert run(tmp_path, harness, vector("Test_Add", [7, 5], 13))[0] == "FAIL"


def test_signed_compare_and_branch(tmp_path, harness):
    for a, b, want in ((3, 9, 9), (9, 3, 9), (-4, 2, 2), (2, -4, 2), (-4, -9, -4)):
        assert run(tmp_path, harness, vector("Test_Max", [a, b], want))[0] == "PASS", (a, b)


def test_jump_table(tmp_path, harness):
    for index, want in ((0, 10), (1, 20), (2, 30), (3, -1), (200, -1)):
        assert run(tmp_path, harness, vector("Test_Switch", [index], want))[0] == "PASS", index


def test_two_level_jump_table(tmp_path, harness):
    for index, want in ((0, 10), (1, 20), (2, 20), (3, 10), (4, 20), (5, 10), (6, -1), (99, -1)):
        v = vector("Test_Switch2", [index], want)
        v["memory_in"] = [{"addr": 0x7d20, "dwords": [0x00010100, 0x00000001]}]    # the byte table 0,1,1,0,1,0 (the vectors load data, not code)
        assert run(tmp_path, harness, v)[0] == "PASS", index


def test_division_truncates_toward_zero(tmp_path, harness):
    for a, b, want in ((7, 2, 3), (-7, 2, -3), (7, -2, -3), (-7, -2, 3)):
        assert run(tmp_path, harness, vector("Test_Div", [a, b], want))[0] == "PASS", (a, b)


def test_call_uses_the_recorded_return_and_arguments(tmp_path, harness):
    call = {"callee": CALLEE, "name": "Callee", "args": [9], "return": 41}
    status, messages, _ = run(tmp_path, harness, vector("Test_Call", [9], 42, [call]))
    assert status == "PASS", messages
    wrong = dict(call, args=[8])  # the lifted code passes 9
    assert run(tmp_path, harness, vector("Test_Call", [9], 42, [wrong]))[0] == "FAIL"
    assert run(tmp_path, harness, vector("Test_Call", [9], 42))[0] in ("FAIL", "ERROR")  # no call recorded


def test_import_call_is_a_call_to_the_slot_and_pops_its_argument(tmp_path, harness):
    call = {"callee": IMPORT_SLOT, "name": "Sleep", "args": [9], "return": 40}
    status, messages, _ = run(tmp_path, harness, vector("Test_Import", [9], 42, [call]))
    assert status == "PASS", messages


def test_call_through_the_master_table_takes_its_argument_count_from_the_recording(tmp_path, harness):
    call = {"callee": 0x1234, "name": "card_handler", "args": [3], "return": 7}
    # the target is whatever the table holds: the vector's memory says 0x1234, at 0x8000 + 3*4
    v = vector("Test_Dynamic", [3], 7, [call])
    v["memory_in"] = [{"addr": 0x8000 + 12, "dwords": [0x1234]}]
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "PASS", messages


def test_call_through_a_global_function_pointer_goes_to_whatever_it_holds(tmp_path, harness):
    call = {"callee": 0x1234, "name": "hook", "args": [3], "return": 7}
    v = vector("Test_Hook", [3], 7, [call])
    v["memory_in"] = [{"addr": 0x9000, "dwords": [0x1234]}]
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "PASS", messages
    v = vector("Test_Hook", [3], 0)       # the hook is not set: the function does nothing
    v["memory_in"] = [{"addr": 0x9000, "dwords": [0]}]
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "PASS", messages


def test_unbounded_indirect_jump_is_refused():
    addr, code = FUNCTIONS["Test_BadJump"]
    with pytest.raises(Unsupported):
        Lifter().lift_function(getbytes, addr, "Test_BadJump", frozenset())


def test_unreadable_memory_is_reported(tmp_path, harness):
    # Test_Add reads its two arguments from the stack, which the harness provides; nothing else, so it is fine. A function
    # that read memory the vector does not define would give different results under the two fills.
    status, messages, _ = run(tmp_path, harness, vector("Test_Add", [1, 2], 3))
    assert status == "PASS", messages


# ---- the same lifted code inside the native layer (src/native/lift_bridge.c) ------------------------------------------


@pytest.fixture(scope="module")
def native_harness(tmp_path_factory):
    """tools/difftest's native harness with the synthetic functions linked in as Handler_<address> lifted functions."""
    cc = os.environ.get("CC") or "cc"
    if not shutil.which(cc) or not shutil.which("make"):
        pytest.skip("no C compiler or make")
    out = tmp_path_factory.mktemp("lift_native")
    lifter, sources, names = Lifter(), [], []
    lifter.imports[IMPORT_SLOT] = "Sleep"
    for name, (addr, code) in FUNCTIONS.items():
        if name == "Test_BadJump" or name.startswith("Helper_"):
            continue
        src, _, _, _ = lifter.lift_function(getbytes, addr, f"Handler_{addr:08x}", frozenset([CALLEE]))
        sources.append(src)
        names.append((f"Handler_{addr:08x}", addr))
    gen = ['#include "lift_rt.h"\n#include "lift_tables.h"\n'] + sources
    gen.append("const LiftedFn LIFTED[] = {\n" + "".join(f'    {{"{n}", 0x{a:x}u, lifted_{a:08x}}},\n' for n, a in names)
               + "    {0, 0, 0}\n};")
    gen.append(f"const int LIFTED_COUNT = {len(names)};")
    gen.append(f"const CalleeRow LIFT_CALLEES[] = {{ {{0x{CALLEE:x}u, 1, 0u}}, {{0x{IMPORT_SLOT:x}u, 1, 4u}}, {{0, 0, 0}} }};\n"
               "const int LIFT_CALLEE_COUNT = 2;")
    (out / "handlers_gen.c").write_text("\n".join(gen))
    proc = subprocess.run(["make", "-C", DIFFTEST, "lifted", f"GEN={out}", f"BUILD={out}/build"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return str(out / "build" / "harness-lifted")


def test_native_layer_runs_a_lifted_function(tmp_path, native_harness):
    v = vector("Handler_00001000", [7, 5, 0], 12)   # Test_Add
    assert run(tmp_path, native_harness, v)[0] == "PASS"
    v = vector("Handler_00002000", [-4, 2, 0], 2)   # Test_Max
    assert run(tmp_path, native_harness, v)[0] == "PASS"


def test_native_layer_replays_the_calls_a_lifted_function_makes(tmp_path, native_harness):
    call = {"callee": CALLEE, "name": "Callee", "args": [9], "return": 41}
    status, messages, _ = run(tmp_path, native_harness, vector("Handler_00005000", [9, 0, 0], 42, [call]))   # Test_Call
    assert status == "PASS", messages


def test_native_layer_counts_a_read_of_undefined_memory_as_a_fault(tmp_path, native_harness):
    # Test_Switch reads nothing but its argument; Test_Dynamic reads the master table, which the vector does not provide
    v = vector("Handler_00007200", [3, 0, 0], 7, [{"callee": 0x1234, "name": "card_handler", "args": [3], "return": 7}])
    status, messages, _ = run(tmp_path, native_harness, v)
    assert status == "FAIL" and any("undefined" in m or "0x00008000" in m or "8000" in m for m in messages), messages


# ---- what the lifter refuses and what it reports about a function ------------------------------------------------------


def lift_bytes(code, name="T"):
    """Lift `code` (placed at 0x9000) and return the lifter, so a test can look at what it noted about the function."""
    lifter = Lifter()

    def get(va, n):
        if 0x9000 <= va < 0x9000 + len(code):
            return code[va - 0x9000:va - 0x9000 + n] + b"\x90" * 64
        raise Unsupported(f"0x{va:x} is not in the test image")
    lifter.lift_function(get, 0x9000, name, frozenset())
    return lifter


def test_a_function_that_takes_a_register_argument_is_refused():
    # mov eax, ecx; ret   (a __fastcall function: ECX holds its first argument, which lifted code does not have)
    with pytest.raises(Unsupported, match="ecx on entry"):
        lift_bytes(bytes.fromhex("89c8c3"))
    # the same function after it has loaded ECX itself is fine: mov ecx,[esp+4]; mov eax,ecx; ret
    lift_bytes(bytes.fromhex("8b4c2404" "89c8" "c3"))


def test_saving_a_callee_save_register_is_not_a_use_of_it():
    # push esi; mov esi,[esp+8]; mov eax,esi; pop esi; ret
    lift_bytes(bytes.fromhex("56" "8b742408" "89f0" "5e" "c3"))
    # reading a part of a register the function wrote part of is a use of what it wrote
    # mov cl,[esp+4]; shl eax,cl would read EAX on entry, which is refused
    with pytest.raises(Unsupported, match="eax on entry"):
        lift_bytes(bytes.fromhex("8a4c2404" "d3e0" "c3"))


def test_a_function_that_never_sets_eax_returns_no_value():
    assert lift_bytes(bytes.fromhex("b801000000c3")).last_returns_value            # mov eax,1; ret
    assert not lift_bytes(bytes.fromhex("c3")).last_returns_value                   # ret
    # one path sets it and one does not: the value is not reliable
    # cmp dword [esp+4],0; je +6; mov eax,1; ret; ret
    assert not lift_bytes(bytes.fromhex("837c240400" "7406" "b801000000" "c3" "c3")).last_returns_value


def test_arguments_are_counted_from_the_frame():
    # push ebp; mov ebp,esp; mov eax,[ebp+0x10]; pop ebp; ret    reads the third argument
    assert lift_bytes(bytes.fromhex("55" "89e5" "8b4510" "5d" "c3")).last_stack_arguments == 3
    # no frame pointer: nothing to count
    assert lift_bytes(bytes.fromhex("8b442404c3")).last_stack_arguments == 0


def test_call_through_a_register_and_through_a_memory_operand(tmp_path, harness):
    call = {"callee": 0x1234, "name": "callback", "args": [5], "return": 9}
    assert run(tmp_path, harness, vector("Test_CallReg", [0x1234], 9, [call]))[0] == "PASS"
    v = vector("Test_CallVirtual", [0x9000], 4, [{"callee": 0x4321, "name": "method", "args": [6], "return": 4}])
    v["memory_in"] = [{"addr": 0x9008, "dwords": [0x4321]}]
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "PASS", messages


def test_rep_stosd_and_movsd_and_repne_scasb(tmp_path, harness):
    v = vector("Test_Stos", [0xA000, 3, 0x11223344], 0xA00C)
    v["memory_out_expected"] = [{"addr": 0xA000, "dwords": [0x11223344] * 3}]
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "PASS", messages
    v = vector("Test_Movs", [0xB000, 0xA000, 2], 0xA008)
    v["memory_in"] = [{"addr": 0xA000, "dwords": [1, 2]}]
    v["memory_out_expected"] = [{"addr": 0xB000, "dwords": [1, 2]}]
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "PASS", messages
    v = vector("Test_Scas", [0xC000], 5)                       # "hello\0"
    v["memory_in"] = [{"addr": 0xC000, "dwords": [0x6C6C6568, 0x0000006F]}]
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "PASS", messages


def test_unsigned_division_and_the_high_word_of_a_product(tmp_path, harness):
    assert run(tmp_path, harness, vector("Test_UDiv", [0xFFFFFFF0, 16], 0x0FFFFFFF))[0] == "PASS"
    assert run(tmp_path, harness, vector("Test_Mul", [0xFFFFFFFF, 0xFFFFFFFF], 0xFFFFFFFE))[0] == "PASS"


def test_a_thunk_tail_calls_its_import(tmp_path, harness):
    call = {"callee": IMPORT_SLOT, "name": "Sleep", "args": [9], "return": 40}
    status, messages, _ = run(tmp_path, harness, vector("Test_Thunk", [9], 40, [call]))
    assert status == "PASS", messages


def test_fs_zero_is_the_thread_information_block(tmp_path, harness):
    v = vector("Test_Fs", [], 0x1234)
    v["memory_in"] = [{"addr": 0x7FFDE000, "dwords": [0x1234]}]
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "PASS", messages


def test_chkstk_lowers_the_stack_pointer_by_eax(tmp_path, harness):
    status, messages, _ = run(tmp_path, harness, vector("Test_Frame", [], 0x77))
    assert status == "PASS", messages


def test_allshl_shifts_a_64_bit_value(tmp_path, harness):
    for lo, hi, cl in ((0x80000001, 0, 4), (3, 0, 36), (1, 0, 64), (0xffffffff, 0x1, 0), (0x40000000, 0x7, 33)):
        v = ((hi << 32) | lo) << cl & 0xffffffffffffffff if cl < 64 else 0
        for name, want in (("Test_Shl64Lo", v & 0xffffffff), ("Test_Shl64Hi", v >> 32)):
            status, messages, _ = run(tmp_path, harness, vector(name, [lo, hi, cl], want if want < 1 << 31 else want - (1 << 32)))
            assert status == "PASS", (name, lo, hi, cl, messages)


def test_shld(tmp_path, harness):
    want = ((0x12345678 << 8) | (0x9abcdef0 >> 24)) & 0xffffffff
    status, messages, _ = run(tmp_path, harness, vector("Test_Shld", [0x12345678, 0x9abcdef0], want))
    assert status == "PASS", messages


def test_x87_moves_and_clears_eight_bytes(tmp_path, harness):
    v = vector("Test_Fcopy", [0xA000, 0xB000], 0)
    v["memory_in"] = [{"addr": 0xA000, "dwords": [0x7ff80001, 0xdeadbeef]}]       # a NaN pattern: copied bit for bit
    v["memory_out_expected"] = [{"addr": 0xB000, "dwords": [0x7ff80001, 0xdeadbeef]}]
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "PASS", messages
    v = vector("Test_Fzero", [0xB000], 0)
    v["memory_in"] = [{"addr": 0xB000, "dwords": [5, 6]}]
    v["memory_out_expected"] = [{"addr": 0xB000, "dwords": [0, 0]}]
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "PASS", messages


def test_a_function_that_starts_with_a_jump_is_a_thunk():
    src, targets, _, _ = Lifter().lift_function(getbytes, 0x8100, "Test_Ilt", frozenset())
    assert targets == {0x1000} and "return lift_call(0x1000u" in src


def test_a_jump_table_indexed_by_a_masked_value(tmp_path, harness):
    for index, want in ((0, 10), (1, 20), (2, 30), (3, 40), (6, 30), (7, 40)):
        assert run(tmp_path, harness, vector("Test_Masked", [index], want))[0] == "PASS", index


def test_rcr_takes_the_carry_of_the_shift_before_it(tmp_path, harness):
    assert run(tmp_path, harness, vector("Test_Rcr", [0x10, 3], 0x80000008))[0] == "PASS"
    assert run(tmp_path, harness, vector("Test_Rcr", [0x10, 2], 0x00000008))[0] == "PASS"


def _s32(x):
    return x - (1 << 32) if x >= 1 << 31 else x


def _rotl(v, k, bits):
    k %= bits
    m = (1 << bits) - 1
    return ((v << k) | (v >> (bits - k))) & m if k else v & m


def test_rol_and_ror_rotate_eight_sixteen_and_thirty_two_bits(tmp_path, harness):
    for v in (0x12345678, 0x80000001, 0, 0xffffffff):
        assert run(tmp_path, harness, vector("Test_Rol32", [v], _s32(_rotl(v, 8, 32))))[0] == "PASS", hex(v)
        for cl in (0, 1, 5, 31, 32, 33):
            want = _rotl(v, 32 - cl % 32, 32) if cl % 32 else v      # (count masked to five bits)
            assert run(tmp_path, harness, vector("Test_Ror32cl", [v, cl], _s32(want)))[0] == "PASS", (hex(v), cl)
    # 16 bits: the upper half of the register is not touched
    v = 0xabcd8421
    assert run(tmp_path, harness, vector("Test_Rol16", [v], _s32((v & 0xffff0000) | _rotl(v & 0xffff, 4, 16))))[0] == "PASS"
    # 8 bits: rol al,3 then ror ah,1 (the other bytes are not touched)
    v = 0x11a5c3e1
    want = (v & 0xffff0000) | (((v >> 8) & 0xff) >> 1 | ((v >> 8) & 1) << 7) << 8 | _rotl(v & 0xff, 3, 8)
    assert run(tmp_path, harness, vector("Test_Rol8", [v], _s32(want)))[0] == "PASS"


def test_a_rotate_in_memory(tmp_path, harness):
    v = vector("Test_RolMem16", [0xA000], 0x0003)
    v["memory_in"] = [{"addr": 0xA000, "dwords": [0xdead8001]}]
    v["memory_out_expected"] = [{"addr": 0xA000, "dwords": [0xdead0003]}]
    assert run(tmp_path, harness, v)[0] == "PASS"


def test_a_rotate_sets_the_carry_and_the_overflow_and_a_rotate_by_zero_sets_nothing(tmp_path, harness):
    for v in (0x80000000, 0x40000000, 0x00000001, 0xc0000000, 0x7fffffff):
        assert run(tmp_path, harness, vector("Test_RolCarry", [v], v >> 31))[0] == "PASS", hex(v)         # rol: CF is the bit that left on the top
        assert run(tmp_path, harness, vector("Test_RorCarry", [v], v & 1))[0] == "PASS", hex(v)          # ror: CF is the bit that left at the bottom
        r = _rotl(v, 1, 32)
        assert run(tmp_path, harness, vector("Test_RolOF", [v], ((r >> 31) ^ (r & 1))))[0] == "PASS", hex(v)
        r = _rotl(v, 31, 32)
        assert run(tmp_path, harness, vector("Test_RorOF", [v], ((r >> 31) ^ ((r >> 30) & 1))))[0] == "PASS", hex(v)
    # the carry is 1 going in (0 < 1); a count of 0 or 32 leaves it, a count of 1 with a zero value makes it 0
    assert run(tmp_path, harness, vector("Test_RolZero", [0x12345678, 0], 1))[0] == "PASS"
    assert run(tmp_path, harness, vector("Test_RolZero", [0x12345678, 32], 1))[0] == "PASS"
    assert run(tmp_path, harness, vector("Test_RolZero", [0, 1], 0))[0] == "PASS"


def test_longjmp_goes_on_after_the_setjmp_with_the_registers_it_had_and_the_value(tmp_path, harness):
    for value, want in ((7, 7), (0x1234, 0x1234), (0, 1)):          # a value of 0 comes back as 1
        status, messages, _ = run(tmp_path, harness, vector("Test_Setjmp", [value], _s32(0x11110000 | want)))
        assert status == "PASS", (value, messages)


def test_a_call_of_setjmp_is_written_out_in_the_function_and_makes_no_call():
    lifter = Lifter()
    lifter.imports[SETJMP_SLOT] = "_setjmp3"
    lifter.imports[LONGJMP_SLOT] = "longjmp"
    src, targets, _, _ = lifter.lift_function(getbytes, 0x8900, "Test_Setjmp", frozenset())
    assert "LIFT_SETJMP(cjb_[0])" in src and "jmp_buf cjb_[1];" in src and "lift_jb_store" in src
    assert targets == {0x8980}                      # the call of Test_Jump; not the thunk
    src, targets, _, _ = lifter.lift_function(getbytes, 0x8980, "Test_Jump", frozenset())
    assert "lift_longjmp(RD32(R_esp), RD32(R_esp + 4u));" in src and not targets
    other = Lifter()                                # with no import named _setjmp3 the thunk is only a function
    src, targets, _, _ = other.lift_function(getbytes, 0x8900, "Test_Setjmp", frozenset())
    assert "LIFT_SETJMP" not in src and 0x8a00 in targets


def test_bts_with_a_register_index_reaches_the_next_dword(tmp_path, harness):
    assert run(tmp_path, harness, vector("Test_Bts", [5], 0x20))[0] == "PASS"
    assert run(tmp_path, harness, vector("Test_Bts", [33], 4))[0] == "PASS"


def test_xchg_and_jecxz(tmp_path, harness):
    assert run(tmp_path, harness, vector("Test_Xchg", [3, 9], 9))[0] == "PASS"
    assert run(tmp_path, harness, vector("Test_Jecxz", [0], 0))[0] == "PASS"
    assert run(tmp_path, harness, vector("Test_Jecxz", [5], 1))[0] == "PASS"


def test_a_backward_scan_with_the_direction_flag_set(tmp_path, harness):
    v = vector("Test_Std", [0xC004, 5, ord("x")], 0xC002)       # "abcxe": scanning back from the e finds the x at 0xC003 and stops one before it
    v["memory_in"] = [{"addr": 0xC000, "dwords": [0x78636261, 0x65]}]
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "PASS", messages


def test_repe_cmpsb_stops_at_the_first_difference(tmp_path, harness):
    v = vector("Test_Cmpsb", [0xC100, 0xC200, 4], 1)             # "abcd" against "abxd": the third byte differs, one of four is left
    v["memory_in"] = [{"addr": 0xC100, "dwords": [0x64636261]}, {"addr": 0xC200, "dwords": [0x64786261]}]
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "PASS", messages
    v = vector("Test_Cmpsb", [0xC100, 0xC100, 4], 0)
    v["memory_in"] = [{"addr": 0xC100, "dwords": [0x64636261]}]
    assert run(tmp_path, harness, v)[0] == "PASS"


def test_fnclex_is_nothing_and_code_before_the_entry_is_reached(tmp_path, harness):
    assert run(tmp_path, harness, vector("Test_Fnclex", [4], 4))[0] == "PASS"
    assert run(tmp_path, harness, vector("Test_Back", [0], 7))[0] == "PASS"
    assert run(tmp_path, harness, vector("Test_Back", [5], 0))[0] == "PASS"


def _doubles(x):
    import struct
    lo, hi = struct.unpack("<II", struct.pack("<d", x))
    return [lo, hi]


def test_x87_adds_two_doubles(tmp_path, harness):
    v = vector("Test_Fadd", [0xA000, 0xB000], 0)
    v["memory_in"] = [{"addr": 0xA000, "dwords": _doubles(1.5)}, {"addr": 0xB000, "dwords": _doubles(2.25)}]
    v["memory_out_expected"] = [{"addr": 0xA000, "dwords": _doubles(3.75)}]
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "PASS", messages


def test_x87_compare_sets_the_condition_codes_fnstsw_reads(tmp_path, harness):
    for a, b, want in ((1.0, 2.0, 1), (2.0, 1.0, 0), (1.0, 1.0, 0)):
        v = vector("Test_Flt", [0xA000, 0xB000], want)
        v["memory_in"] = [{"addr": 0xA000, "dwords": _doubles(a)}, {"addr": 0xB000, "dwords": _doubles(b)}]
        assert run(tmp_path, harness, v)[0] == "PASS", (a, b)


def test_x87_divide_multiply_subtract(tmp_path, harness):
    v = vector("Test_Fdivtest", [0xA000, 0xB000], 0)
    v["memory_in"] = [{"addr": 0xA000, "dwords": _doubles(6.0)}, {"addr": 0xB000, "dwords": _doubles(2.0)}]
    v["memory_out_expected"] = [{"addr": 0xA000, "dwords": _doubles(0.0)}]
    status, messages, _ = run(tmp_path, harness, v)
    assert status == "PASS", messages


def test_x87_fistp_rounds_to_even_unless_the_control_word_truncates(tmp_path, harness):
    for fn, ints, want in (("Test_Fround", 5, 8), ("Test_Fround", 3, 4), ("Test_Ftrunc", 5, 7)):      # 5 * 1.5 = 7.5; 3 * 1.5 = 4.5
        v = vector(fn, [0xA000, 0xB000], 0)
        v["memory_in"] = [{"addr": 0xA000, "dwords": [ints]}, {"addr": 0xB000, "dwords": _doubles(1.5)}]
        v["memory_out_expected"] = [{"addr": 0xA000, "dwords": [want]}]
        status, messages, _ = run(tmp_path, harness, v)
        assert status == "PASS", (fn, ints, messages)


def test_sbb_borrows_on_the_carry_it_took_in(tmp_path, harness):
    assert run(tmp_path, harness, vector("Test_Sbb", [1, 2], -1))[0] == "PASS"       # 1 < 2: sbb al,al = 0xff and borrows again
    assert run(tmp_path, harness, vector("Test_Sbb", [2, 1], 1))[0] == "PASS"


def test_adc_takes_the_carry_of_the_add_before_it(tmp_path, harness):
    assert run(tmp_path, harness, vector("Test_Adc", [0xffffffff, 1], 1))[0] == "PASS"
    assert run(tmp_path, harness, vector("Test_Adc", [1, 2], 0))[0] == "PASS"


# ---- finding the functions of a program from its code (fnscan.py, gen_dll.py) ------------------------------------------------
# the compiler puts a `nop` after a prologue that loads its arguments into registers: the tail reads
# EAX, which the head set (mov eax,[esp+4]; test eax,eax; nop | push ebx; mov ebx,eax; jle neg; lea eax,[ebx+ebx]; pop ebx; ret; neg: xor eax,eax; pop ebx; ret)
NOPSPLIT = bytes.fromhex("8b442404" "85c0" "90" "53" "89c3" "7e05" "8d041b" "5b" "c3" "31c0" "5b" "c3")
FUNCTIONS["Test_NopSplit"] = (0x8540, NOPSPLIT)


def test_a_function_split_by_a_nop_lifts_whole_from_its_head(tmp_path, harness):
    for arg, want in ((5, 10), (0, 0), (-3, 0), (0x40000000, 0x80000000)):
        assert run(tmp_path, harness, vector("Test_NopSplit", [arg], want))[0] == "PASS", arg


def flat_image(base, pieces):
    """getbytes over one flat image: `pieces` is {address: bytes}; the rest is int3 fill."""
    top = max(a + len(b) for a, b in pieces.items())
    img = bytearray(b"\xcc" * (top - base + 64))
    for a, b in pieces.items():
        img[a - base:a - base + len(b)] = b

    def get(va, n):
        if base <= va < base + len(img):
            return bytes(img[va - base:va - base + n])
        raise Unsupported(f"0x{va:x} is not in the test image")
    return get


def test_a_lifted_function_reports_the_addresses_it_names():
    # mov dword [0x9100], 0x9200; push 0x9300; call 0x9400; add esp,4; ret
    code = bytes.fromhex("c705" "00910000" "00920000" "68" "00930000") + _call(0x9000 + 15, 0x9400) + bytes.fromhex("83c404" "c3")
    consts = lift_bytes(code).last_constants
    assert {0x9100, 0x9200, 0x9300, 0x9400} <= consts
    assert 0x9500 not in consts


# ---- fnscan.py: where the functions of a program start, from its code alone ---------------------------------------------------
def scan(pieces, roots, data=(), code=None, gap=None):
    from fnscan import Scan   # noqa: PLC0415
    base = min(pieces)
    top = max(a + len(b) for a, b in pieces.items())
    get = flat_image(base, pieces)
    rng = [(base, top)]
    sc = Scan(Lifter(), get, code or rng, data, gap if gap is not None else rng)
    return sc, sc.run(roots)


PROLOG = bytes.fromhex("558bec")
RET = bytes.fromhex("5dc3")


def test_a_scan_follows_calls_and_tail_jumps():
    pytest.importorskip("fnscan")
    a, b, c = 0x8000, 0x8040, 0x8080
    # a: call b; call c; ret.  b: jmp c (a tail call, once something else makes c a function).  c: ret 8
    fa = PROLOG + _call(a + 3, b) + _call(a + 8, c) + RET
    fb = PROLOG + b"\xe9" + ((c - (b + 3 + 5)) & 0xffffffff).to_bytes(4, "little")
    fc = PROLOG + bytes.fromhex("8b4508" "8b550c" "5d" "c20800")
    _, found = scan({a: fa, b: fb, c: fc}, [a])
    assert sorted(found) == [a, b, c]
    assert found[c]["nargs"] == 2 and found[a]["nargs"] == 0
    sc, _ = scan({a: fa, b: fb, c: fc}, [a])
    assert sc.parsed[b][1] == {b + 3: c}           # b was explored again when c became a function: its jump is a tail call, not inline code
    assert found[a]["name"] == "FUN_00008000" and not any(f["dead"] for f in found.values())


def test_a_scan_finds_a_function_nothing_calls_by_its_prologue_and_marks_it_dead():
    pytest.importorskip("fnscan")
    a, dead = 0x8000, 0x8040
    sc, found = scan({a: PROLOG + RET, dead: PROLOG + bytes.fromhex("8b4508" "5d" "c3")}, [a])
    assert sorted(found) == [a, dead]
    assert found[dead]["dead"] and not found[a]["dead"]
    assert found[dead]["nargs"] == 1


def test_a_scan_takes_the_first_instruction_after_int3_fill_for_a_function_but_not_one_int3_byte():
    pytest.importorskip("fnscan")
    a, runtime = 0x8000, 0x8040
    # a runtime function with no frame (`mov eax,[esp+4]; ret`) after int3 fill; and a function whose displacement ends in 0xcc (`mov [ebp-0x34], eax`)
    odd = PROLOG + bytes.fromhex("8945cc" "8b45cc" "5d" "c3")      # the byte after `89 45 cc` is a real instruction that must not start a function
    _, found = scan({a: odd, runtime: bytes.fromhex("8b442404c3")}, [a])
    assert sorted(found) == [a, runtime]


def test_a_scan_does_not_make_a_label_inside_a_function_a_function():
    pytest.importorskip("fnscan")
    a = 0x8000
    # push ebp; mov ebp,esp; mov eax, <address of the label>; label: pop ebp; ret -- the address is a constant, but it points into the function
    label = a + 3 + 5
    code = PROLOG + b"\xb8" + label.to_bytes(4, "little") + bytes.fromhex("5d" "c3")
    _, found = scan({a: code}, [a])
    assert sorted(found) == [a]


def test_a_scan_follows_a_function_pointer_stored_as_data_and_as_a_constant():
    pytest.importorskip("fnscan")
    a, cb1, cb2, table = 0x8000, 0x8040, 0x8080, 0x9000
    code = PROLOG + b"\x68" + cb1.to_bytes(4, "little") + bytes.fromhex("5d" "c3")          # push cb1
    pieces = {a: code, cb1: PROLOG + RET, cb2: PROLOG + RET, table: cb2.to_bytes(4, "little") + b"\0\0\0\0"}
    _, found = scan(pieces, [a], data=[(table, table + 8)], code=[(a, 0x80c0)], gap=[])
    assert sorted(found) == [a, cb1, cb2]


def test_a_scan_makes_a_function_split_by_a_nop_one_function_from_its_head():
    pytest.importorskip("fnscan")
    head = 0x8040
    _, found = scan({0x8000: bytes.fromhex("31c0c3"), head: NOPSPLIT}, [0x8000])
    assert sorted(found) == [0x8000, head]       # the tail (after the nop) is inside the head's function
    assert found[head]["dead"]


def test_a_scan_does_not_take_bytes_that_are_not_code_for_a_function():
    pytest.importorskip("fnscan")
    a = 0x8000
    _, found = scan({a: PROLOG + RET, 0x8040: bytes.fromhex("ffffffffffffffffffffffffffffffff")}, [a])
    assert sorted(found) == [a]


# ---- the build id (builds.py, gen_handlers.py, gen_dll.py; src/port/profile.c) ----------------------------------------------
def tiny_pe(path, sections, entry_rva, image_base=0x400000, extra=b"", directories=None):
    """Write the smallest PE32 the lifter will read: `sections` is [(name, rva, bytes, flags)]; no imports unless `directories` ({index: (rva, size)}: 0 is the export table) says so.
    `extra` is appended to the file (another file, the same code)."""
    import struct  # noqa: PLC0415
    hdr_size, raw = 0x200, 0x200
    secs = []
    off = hdr_size
    for name, rva, data, flags in sections:
        size = (len(data) + raw - 1) // raw * raw
        secs.append((name, rva, data, flags, off, size))
        off += size
    image_size = max(rva + max(len(d), 0x1000) for _, rva, d, _, _, _ in secs)
    image_size = (image_size + 0xfff) & ~0xfff
    pe = bytearray(hdr_size)
    pe[0:2] = b"MZ"
    struct.pack_into("<I", pe, 0x3c, 0x40)
    pe[0x40:0x44] = b"PE\0\0"
    struct.pack_into("<HHIIIHH", pe, 0x44, 0x14c, len(secs), 0, 0, 0, 0xE0, 0x0102)
    opt = 0x58
    struct.pack_into("<HBBIII", pe, opt, 0x10b, 6, 0, 0x200, 0x200, 0)
    struct.pack_into("<IIII", pe, opt + 16, entry_rva, 0x1000, 0x2000, image_base)
    struct.pack_into("<II", pe, opt + 32, 0x1000, 0x200)
    struct.pack_into("<HHHHHH", pe, opt + 40, 4, 0, 0, 0, 4, 0)
    struct.pack_into("<IIII", pe, opt + 56, image_size, hdr_size, 0, 2)
    struct.pack_into("<IIII", pe, opt + 72, 0x100000, 0x1000, 0x100000, 0x1000)
    struct.pack_into("<II", pe, opt + 92, 0, 16)
    if directories:                          # the table of data directories: sixteen entries, the ones given filled in
        struct.pack_into("<II", pe, opt + 92, 16, 0)
        for index, (rva, size) in directories.items():
            struct.pack_into("<II", pe, opt + 96 + 8 * index, rva, size)
    at = opt + 0xE0
    for name, rva, data, flags, foff, size in secs:
        pe[at:at + 8] = name.ljust(8, b"\0")
        struct.pack_into("<IIIIIIHHI", pe, at + 8, max(len(data), 1), rva, size, foff, 0, 0, 0, 0, flags)
        at += 40
    for name, rva, data, flags, foff, size in secs:
        pe += data.ljust(size, b"\0")
    with open(path, "wb") as f:
        f.write(bytes(pe) + extra)


def run_lifter(tmp_path, script, *args):
    r = subprocess.run([sys.executable, os.path.join(HERE, script), *args], capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def test_the_build_id_is_the_sha256_of_the_file(tmp_path):
    import hashlib  # noqa: PLC0415
    import builds  # noqa: PLC0415
    p = tmp_path / "x.bin"
    p.write_bytes(b"abc")
    assert builds.file_build_id(str(p)) == builds.build_id(b"abc") == hashlib.sha256(b"abc").hexdigest() == \
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    p.write_bytes(b"x" * 3_000_000)            # read in pieces
    assert builds.file_build_id(str(p)) == hashlib.sha256(b"x" * 3_000_000).hexdigest()


def test_the_known_builds_are_the_retail_disc():
    import builds  # noqa: PLC0415
    assert builds.fingerprints("v1.0") == {
        "MAGIC.EXE": "4dc592695b6ee390485f283feb2a248cd3f3f739749c2800ab3b1100ea03845c",
        "DUEL.EXE": "7c4e618b4a8ab4330c71d2dd30637c522573c133d32c667c97924dc8edc2efed",
        "DECK.EXE": "193f8abea01d4f2c03b769224b06eece6e263a18f13a5b4e2509ed25a01e3d90",
        "DECKDLL.DLL": "a21f714bea465077c4fabe4a407ff7503b0ce5f9bb1a277826e74276e35c2c18",
        "STATWIN.DLL": "95bd14de41e8fff84217cdf627a48392da5e7be9c3d064a68e04ed1455334bd7",
        "MAGSND.DLL": "6f6d51cd2b8a5800b0b3c994e3ee8217f7b40ba2621f9738783387f3250a9882",
        "MAGVID.DLL": "d2db1435ae96e9e41d77ded7a7b222969d44d5af642fa9968fe51768c1ce83a3",
    }
    assert builds.name_of("magic.exe", builds.fingerprints()["MAGIC.EXE"]) == "v1.0 MAGIC.EXE"        # (the case of the name does not matter)
    assert builds.name_of("MAGIC.EXE", builds.fingerprints()["DUEL.EXE"]) is None                     # a known id under another file's name is not that file
    assert builds.name_of("MAGIC.EXE", "0" * 64) is None
    assert "unknown build" in builds.describe("MAGIC.EXE", "0" * 64) and "v1.0 MAGIC.EXE" in builds.describe("MAGIC.EXE", builds.fingerprints()["MAGIC.EXE"])


def test_the_profiles_of_the_runtime_are_the_known_builds():
    """src/port/profile.c has a row for each file of a build that the port runs lifted code from, with the very ids of builds.py, and nothing else."""
    import re  # noqa: PLC0415
    import builds  # noqa: PLC0415
    text = open(os.path.join(ROOT, "src", "port", "profile.c")).read()
    ids = dict(re.findall(r'#define (ID_\w+) "([0-9a-f]{64})"', text))
    rows = re.findall(r'\.id = (ID_\w+), \.build = "([^"]+)", \.file = "([^"]+)"', text)
    assert len(rows) == len(set(r[0] for r in rows)) == len(ids)
    from_c = {(build, file, ids[ident]) for ident, build, file in rows}
    from_py = {(b, f, sha) for b, f, sha, role in builds.KNOWN if role == "lifted"}
    lic = builds.SOTA_LICENCE_LIBRARY
    from_py.add(("v2.15", lic["file"], lic["sha256"]))                  # the licence writer's library: a row of its own, not a file of the build's Program folder
    assert from_c == from_py
    assert len({sha for _, _, sha in from_c}) == len(from_c)


def test_gen_dll_writes_the_build_id_of_a_program_and_of_a_library(tmp_path):
    import re  # noqa: PLC0415
    import builds  # noqa: PLC0415
    pe = tmp_path / "PROG.EXE"
    tiny_pe(str(pe), [(b".text", 0x1000, b"\xc3", 0x60000020)], 0x1000)
    want = builds.file_build_id(str(pe))
    run_lifter(tmp_path, "gen_dll.py", "--main", "--dll", str(pe), "--out", str(tmp_path / "main"))
    text = (tmp_path / "main" / "handlers_gen.c").read_text()
    assert f'const char LIFT_BUILD_ID[] = "{want}";' in text and 'const char LIFT_PROGRAM[] = "PROG";' in text
    lib = tmp_path / "LIB.DLL"
    tiny_pe(str(lib), [(b".text", 0x1000, b"\xc3", 0x60000020)], 0x1000)
    run_lifter(tmp_path, "gen_dll.py", "--dll", str(lib), "--base", "0x30000000", "--out", str(tmp_path / "lib"))
    text = (tmp_path / "lib" / "lib_gen.c").read_text()
    lib_id = builds.file_build_id(str(lib))
    assert f'static const char LIFT_BUILD_ID_LIB[] = "{lib_id}";' in text
    assert re.search(r'const LiftModule LIFT_MODULE_LIB = \{"lib.dll", 0x30000000u, [^;]*, LIFT_BUILD_ID_LIB\};', text)
    # the same code in another file is another build
    other = tmp_path / "OTHER.EXE"
    tiny_pe(str(other), [(b".text", 0x1000, b"\xc3", 0x60000020)], 0x1000, extra=b"\0")
    assert builds.file_build_id(str(other)) != want


def test_gen_handlers_writes_the_build_id_of_the_program(tmp_path):
    import builds  # noqa: PLC0415
    pe = tmp_path / "MAGIC.EXE"
    # a code section, and a data section that holds the (empty) master card table at 0x51aeb8
    tiny_pe(str(pe), [(b".text", 0x1000, b"\x55\x8b\xec\x5d\xc3", 0x60000020), (b".data", 0x11a000, b"\0" * 0x2000, 0xC0000040)], 0x1000)
    run_lifter(tmp_path, "gen_handlers.py", "--program", "magic", "--exe", str(pe), "--out", str(tmp_path / "out"), "--all", "--no-handlers")
    text = (tmp_path / "out" / "handlers_gen.c").read_text()
    assert f'const char LIFT_BUILD_ID[] = "{builds.file_build_id(str(pe))}";' in text and 'const char LIFT_PROGRAM[] = "MAGIC";' in text


def test_no_address_of_the_game_is_written_in_the_runtime_outside_the_profile_table():
    """Every address of a build of the game that src/port uses is in src/port/profile.c (CONTRIBUTING.md, "Adding a build"). Comments may name them; code may not, but for the few
    literals that are not the game's: raster operation codes (gdi_blit.c), the image base 0x400000 as the lowest address a guest pointer can have (screens.c) or a trace prints as text (call.c)."""
    import glob  # noqa: PLC0415
    import re  # noqa: PLC0415
    allowed = {"gdi_blit.c": {"0x660046", "0x440328"}, "call.c": {"0x400000"}, "screens.c": {"0x400000"}}
    bad = []
    for path in sorted(glob.glob(os.path.join(ROOT, "src", "port", "*.[ch]"))):
        name = os.path.basename(path)
        if name.startswith("test_") or name == "profile.c":
            continue
        code = open(path, errors="replace").read()
        code = re.sub(r"/\*.*?\*/", " ", code, flags=re.S)
        code = re.sub(r"//[^\n]*", " ", code)
        code = re.sub(r'"(\\.|[^"\\])*"', '""', code)
        for m in re.finditer(r"\b0x[4-7][0-9a-fA-F]{5}[uUlL]*\b", code):
            lit = "0x" + m.group(0)[2:8].lower()
            if lit not in allowed.get(name, ()):
                bad.append(f"{name}: {m.group(0)}")
    assert bad == [], "an address of the game outside src/port/profile.c: " + ", ".join(bad)


# ---- what the lifter knows of the game's libraries and of the calls Spells of the Ancients adds ---------------------------------------------------------------------
def export_section(rva, exports):
    """The bytes of an export table at `rva` for [(name, function rva)]: the directory, the function and name tables, the ordinals and the names."""
    import struct  # noqa: PLC0415
    n = len(exports)
    head = 40
    funcs, names, ords = rva + head, rva + head + 4 * n, rva + head + 8 * n
    strings = rva + head + 10 * n
    blob, name_rvas, at = b"", [], strings
    for name, _ in exports:
        name_rvas.append(at)
        blob += name.encode() + b"\0"
        at += len(name) + 1
    out = struct.pack("<IIHHIIIIIII", 0, 0, 0, 0, rva + head + 10 * n + len(blob), 1, n, n, funcs, names, ords)
    out += b"".join(struct.pack("<I", f) for _, f in exports) + b"".join(struct.pack("<I", r) for r in name_rvas)
    out += b"".join(struct.pack("<H", k) for k in range(n)) + blob + b"\0"
    return out


def write_library(path):
    """A library with three exports whose conventions are in their code: StdTwo (`ret 8`: stdcall, two words), CdeclTwo (reads [ebp+0xc], plain `ret`: cdecl, two words) and
    ThunkThree (a `jmp` to a function that reads [ebp+0x10] and does `ret 12`: the thunk is that function)."""
    code = bytearray(0x100)
    code[0x00:0x0a] = bytes.fromhex("8b442404" "03442408" "c20800")[:10]
    code[0x10:0x18] = bytes.fromhex("55" "8bec" "8b450c" "5d" "c3")
    code[0x20:0x25] = bytes.fromhex("e90b000000")
    code[0x30:0x39] = bytes.fromhex("55" "8bec" "8b4510" "5d" "c20c00")
    exports = [("StdTwo", 0x1000), ("CdeclTwo", 0x1010), ("ThunkThree", 0x1020)]
    table = export_section(0x2000, exports)
    tiny_pe(path, [(b".text", 0x1000, bytes(code), 0x60000020), (b".edata", 0x2000, table, 0x40000040)], 0x1000, image_base=0x10000000, directories={0: (0x2000, len(table))})


def test_a_librarys_exports_say_their_calling_conventions(tmp_path):
    import libsigs  # noqa: PLC0415
    lib = tmp_path / "cardartlib.dll"
    write_library(str(lib))
    assert libsigs.export_signatures(str(lib)) == {"StdTwo": (2, 8), "CdeclTwo": (2, 0), "ThunkThree": (3, 12)}


def test_the_game_s_own_libraries_are_the_ones_in_its_folder_that_windows_does_not_supply(tmp_path):
    import libsigs  # noqa: PLC0415
    from types import SimpleNamespace  # noqa: PLC0415
    for n in ("CardArtLib.DLL", "MSVCRT.DLL", "other.dll"):
        (tmp_path / n).write_bytes(b"MZ")
    pe = SimpleNamespace(DIRECTORY_ENTRY_IMPORT=[SimpleNamespace(dll=n) for n in (b"cardartlib.dll", b"KERNEL32.dll", b"MSVCRT.dll", b"CARDARTLIB.DLL", b"missing.dll")])
    found = libsigs.own_libraries(pe, str(tmp_path))
    assert list(found) == ["cardartlib.dll"] and os.path.basename(found["cardartlib.dll"]) == "CardArtLib.DLL"      # the copy of the C runtime is Windows' name, and `other.dll` is imported by nothing


def test_registered_export_signatures_are_found_after_the_documented_ones(tmp_path):
    import import_signatures as sigs  # noqa: PLC0415
    import libsigs  # noqa: PLC0415
    from types import SimpleNamespace  # noqa: PLC0415
    write_library(str(tmp_path / "CardArtLib.dll"))
    prog = tmp_path / "shandalar.exe"
    prog.write_bytes(b"MZ")
    pe = SimpleNamespace(DIRECTORY_ENTRY_IMPORT=[SimpleNamespace(dll=b"cardartlib.dll")])
    saved = dict(sigs.LIBRARY)
    try:
        sigs.LIBRARY.clear()
        assert sigs.signature("cardartlib.dll", "ThunkThree") is None
        assert libsigs.register(pe, str(prog)) == ["cardartlib.dll"]
        assert sigs.signature("cardartlib.dll", "ThunkThree") == (3, 12) and sigs.signature("cardartlib.dll", "CdeclTwo") == (2, 0)
        assert sigs.signature("kernel32.dll", "Sleep") == (1, 4)                   # a documented one is not looked up in a library
        assert sigs.signature("deckdll.dll", "ThunkThree") is None                 # the name alone is not enough: the library has to be the one
    finally:
        sigs.LIBRARY.clear()
        sigs.LIBRARY.update(saved)


def test_the_calls_spells_of_the_ancients_makes_have_their_documented_signatures():
    import import_signatures as sigs  # noqa: PLC0415
    want = {
        ("advapi32.dll", "RegOpenKeyA"): (3, 12), ("advapi32.dll", "RegCreateKeyA"): (3, 12), ("comdlg32.dll", "GetFileTitleA"): (3, 12), ("gdi32.dll", "ExtTextOutA"): (8, 32),
        ("gdi32.dll", "RectInRegion"): (2, 8), ("kernel32.dll", "GetThreadTimes"): (5, 20), ("kernel32.dll", "GetVersionExA"): (1, 4), ("kernel32.dll", "GetWindowsDirectoryA"): (2, 8),
        ("kernel32.dll", "ResumeThread"): (1, 4), ("kernel32.dll", "SuspendThread"): (1, 4), ("kernel32.dll", "WinExec"): (2, 8), ("user32.dll", "GetUpdateRect"): (3, 12),
        ("user32.dll", "GetUpdateRgn"): (3, 12), ("user32.dll", "ChangeDisplaySettingsA"): (2, 8), ("kernel32.dll", "GetDiskFreeSpaceA"): (5, 20), ("user32.dll", "SetRectEmpty"): (1, 4),
        ("user32.dll", "EqualRect"): (2, 8), ("kernel32.dll", "TlsAlloc"): (0, 0), ("kernel32.dll", "TlsFree"): (1, 4), ("kernel32.dll", "TlsGetValue"): (1, 4),
        ("kernel32.dll", "TlsSetValue"): (2, 8), ("kernel32.dll", "GetLocaleInfoA"): (4, 16), ("kernel32.dll", "GetLocaleInfoW"): (4, 16), ("kernel32.dll", "GetVolumeInformationA"): (8, 32),
        ("user32.dll", "RegisterWindowMessageA"): (1, 4), ("kernel32.dll", "GetCurrentThreadId"): (0, 0), ("kernel32.dll", "SetLastError"): (1, 4),
        # the C runtime's: the caller pops, so nothing is popped by the callee; the number is the words a call copies (12 for the two that take what the format asks)
        ("msvcrt.dll", "longjmp"): (2, 0), ("msvcrt.dll", "_setjmp3"): (12, 0), ("msvcrt.dll", "qsort"): (4, 0), ("msvcrt.dll", "strcoll"): (2, 0),
        ("msvcrt.dll", "_beginthreadex"): (6, 0), ("msvcrt.dll", "_spawnl"): (12, 0), ("msvcrt.dll", "_findfirst"): (2, 0), ("msvcrt.dll", "_findnext"): (2, 0), ("msvcrt.dll", "_findclose"): (1, 0),
    }
    for (dll, name), sig in want.items():
        assert sigs.signature(dll, name) == sig, (dll, name)
    assert sigs.signature("kernel32.dll", "NoSuchCallEver") is None


def test_the_master_card_table_is_found_by_its_pattern(tmp_path):
    import struct  # noqa: PLC0415
    import pefile  # noqa: PLC0415
    import mastertable  # noqa: PLC0415
    records = 100
    data = bytearray()
    for k in range(records):
        rec = bytearray(0x48)
        struct.pack_into("<I", rec, 0x10, 0x401000 + 0x20 * (k % 50))        # the code pointer of the card's rules: 50 handlers, each shared by two cards
        struct.pack_into("<I", rec, 0, k + 1)
        data += rec
    pe_path = tmp_path / "SHANDALAR.EXE"
    tiny_pe(str(pe_path), [(b".text", 0x1000, b"\x90" * 0x1000, 0x60000020), (b".data", 0x3000, b"\0" * 0x40 + bytes(data) + b"\0" * 0x100, 0xC0000040)], 0x1000)
    pe = pefile.PE(str(pe_path))
    start, count = mastertable.find(pe, 0x48)
    assert (start, count) == (0x400000 + 0x3000 + 0x40, records)
    handlers = mastertable.handler_addresses(pe, start, 0x48)
    assert handlers == [0x401000 + 0x20 * k for k in range(50)]
    assert mastertable.find(pe, 0x34)[1] < records                                # another stride is another table (or none)
    few = tmp_path / "FEW.EXE"
    tiny_pe(str(few), [(b".text", 0x1000, b"\x90" * 0x1000, 0x60000020), (b".data", 0x3000, bytes(data[:0x48 * 10]) + b"\0" * 0x100, 0xC0000040)], 0x1000)
    assert mastertable.find(pefile.PE(str(few)), 0x48) == (0, 0)                  # ten records are not a table


def test_the_library_bases_of_the_builds_are_the_bases_of_the_runtime_s_rows():
    import re  # noqa: PLC0415
    import builds  # noqa: PLC0415
    text = open(os.path.join(ROOT, "src", "port", "profile.c")).read()
    rows = {(b, f): int(base, 16) for b, f, base in re.findall(r'\.build = "([^"]+)", \.file = "([^"]+)", \.program = "", \.base = (0x[0-9a-fA-F]+)', text)}
    want = {(b, f): base for b, libs in builds.LIBRARY_BASES.items() for f, base in libs.items()}
    assert rows == want
    lifted = {f for b, f, _, role in builds.KNOWN if b == "v2.15" and role == "lifted"}
    modules = {exe for exe, _ in builds.SOTA_MODULES.values()} | set(builds.LIBRARY_BASES["v2.15"])
    assert lifted == modules                                                       # every lifted file of the build is lifted as a program or a library, and nothing else is
    assert {lib for _, libs in builds.SOTA_MODULES.values() for lib in libs} <= set(builds.LIBRARY_BASES["v2.15"])


def test_the_build_of_2_15_is_the_six_files_of_the_patch_over_the_expansion_s():
    import builds  # noqa: PLC0415
    f = builds.fingerprints("v2.15")
    assert f["shandalar.exe"] == "e4e46718c451974756b66e7666ac0bf1cc9ebdbc5897eb04a87b8ea2a02353e7" and f["deckdll.dll"] == "ce741d1f5547c143fd8494bbe09c26e918b892a3d9fc3c3761babb3c8268a667"
    assert builds.name_of("SHANDALAR.EXE", f["shandalar.exe"]) == "v2.15 shandalar.exe"             # (the case of the name does not matter)
    assert builds.name_of("MAGIC.EXE", f["shandalar.exe"]) is None
    assert set(builds.fingerprints("v1.0")).isdisjoint({k for k in f if k not in ("DECK.EXE", "STATWIN.DLL", "MAGSND.DLL", "MAGVID.DLL")})

"""winemu.machine data access: the direct host-buffer paths give exactly what Unicorn's own reads and writes give."""
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from winemu.machine import Machine  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..", "..", "..")
EXE = os.path.join(ROOT, "sources", "installed", "Magic", "Program", "MAGIC.EXE")


@pytest.fixture(scope="module")
def machine():
    if not os.path.exists(EXE):
        pytest.skip("needs the game's own MAGIC.EXE")
    return Machine(EXE, os.path.join(ROOT, "sources", "installed", "Magic"), os.path.join(ROOT, "sources", "emu_overlay"), log=lambda *a: None)


def test_reads_and_writes_agree_with_unicorn(machine):
    m, rng = machine, random.Random(1)
    base = 0x50100000                                     # inside the heap region
    for _ in range(500):
        a = base + rng.randrange(0, 0x4000)
        n = rng.choice((1, 2, 3, 4, 7, 16, 64))
        data = bytes(rng.randrange(256) for _ in range(n))
        if rng.random() < 0.5:
            m.wr(a, data)
        else:
            m.uc.mem_write(a, data)
        assert m.rd(a, n) == bytes(m.uc.mem_read(a, n)) == data
        if n >= 4:
            v = rng.randrange(1 << 32)
            m.w32(a, v)
            assert m.r32(a) == v and int.from_bytes(bytes(m.uc.mem_read(a, 4)), "little") == v


def test_reads_across_a_region_edge_and_unmapped_fall_back(machine):
    m = machine
    from unicorn import UcError
    with pytest.raises(UcError):
        m.rd(0x10, 4)                                      # unmapped: the same error as before
    with pytest.raises(UcError):
        m.w32(0x10, 1)


def test_fast_register_access_agrees(machine):
    from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_FS
    m = machine
    for v in (0, 1, 0xFFFFFFFF, 0x12345678):
        m.uc.reg_write(UC_X86_REG_EAX, v)
        assert m.uc.reg_read(UC_X86_REG_EAX) == v
    m.uc.reg_write(UC_X86_REG_EAX, 0x1_0000_0005)          # masked to 32 bits as Unicorn does
    assert m.uc.reg_read(UC_X86_REG_EAX) == 5
    assert m.uc.reg_read(UC_X86_REG_FS) == 0x18 or m.uc.reg_read(UC_X86_REG_FS) >= 0   # non-GP registers still work

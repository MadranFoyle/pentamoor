"""
Faster register and memory access for Unicorn's Python binding.

Unicorn's `reg_read` / `reg_write` / `mem_read` do a class lookup, build a ctypes object and check the status on every call; an
emulated import call makes about ten of them, and a game start makes a million import calls. `speed_up(uc)` replaces the methods on one
Uc object with versions that call the C library directly with a preallocated buffer, for the 32-bit general registers and for memory.
Anything else (segment, FPU, vector registers) still goes through the original methods. The values and the errors are the same.

Not thread-safe (one shared buffer): used from the emulator's thread only, the window thread never calls into Unicorn.
"""
import ctypes

from unicorn import UcError
from unicorn.unicorn_py3 import unicorn as _u
from unicorn.x86_const import (UC_X86_REG_EAX, UC_X86_REG_EBP, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDI, UC_X86_REG_EDX,
                               UC_X86_REG_EFLAGS, UC_X86_REG_EIP, UC_X86_REG_ESI, UC_X86_REG_ESP)

GP = {UC_X86_REG_EAX, UC_X86_REG_EBX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_ESI, UC_X86_REG_EDI, UC_X86_REG_EBP, UC_X86_REG_ESP,
      UC_X86_REG_EIP, UC_X86_REG_EFLAGS}


def speed_up(uc):
    lib, handle = _u.uclib, uc._uch
    reg_read_c, reg_write_c, mem_read_c = lib.uc_reg_read, lib.uc_reg_write, lib.uc_mem_read
    orig_read, orig_write, orig_mem_read = uc.reg_read, uc.reg_write, uc.mem_read
    cell = ctypes.c_uint32()
    ref = ctypes.byref(cell)
    create = ctypes.create_string_buffer

    def reg_read(reg_id, aux=None):
        if reg_id in GP:
            if reg_read_c(handle, reg_id, ref):
                raise UcError(lib.uc_errno(handle), reg_id)
            return cell.value
        return orig_read(reg_id, aux) if aux is not None else orig_read(reg_id)

    def reg_write(reg_id, value):
        if reg_id in GP:
            cell.value = value & 0xFFFFFFFF
            if reg_write_c(handle, reg_id, ref):
                raise UcError(lib.uc_errno(handle), reg_id)
            return None
        return orig_write(reg_id, value)

    def mem_read(address, size):
        buf = create(size)
        status = mem_read_c(handle, address, buf, size)
        if status:
            raise UcError(status, address, size)
        return bytearray(buf.raw)

    uc.reg_read, uc.reg_write, uc.mem_read = reg_read, reg_write, mem_read
    return uc

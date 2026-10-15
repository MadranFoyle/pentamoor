/*
 * crt.c - functions of the C runtime that DUEL.EXE carries as its own copy (it links the runtime statically).
 *
 * Crt_Memcpy (DUEL.EXE 0x004d99b0) is the Microsoft runtime's memcpy: it copies forwards, or backwards when the
 * destination lies inside the source, so it is a memmove. A second copy of the same code is at 0x004e97b0 (the jump
 * table inside is the only difference). MAGIC.EXE calls memcpy in the runtime DLL instead, which is not native here.
 */
#include "engine.h"

uint64_t native_cost_extra;

/* How many instructions the original's code executes for a call, counting what the emulator counts: one per instruction and one
 * per iteration of a `rep` plus one more when it ends. Followed branch by branch from the disassembly; the cost of 980 calls over
 * sizes 0 to 46656, every alignment and every overlap was measured in the emulator and matches. The one exception is a copy that
 * overlaps backwards from an unaligned end, longer than 12 bytes: its prologue uses EDX as the caller left it, which is taken
 * to be 0 here (the copied bytes do not depend on it, the count can differ by a few). */
uint64_t crt_memcpy_instructions(uint32_t dst, uint32_t src, uint32_t n)
{
    static const unsigned fwd_tail[4] = {5, 7, 7, 9};
    static const unsigned bwd_tail[4] = {6, 8, 8, 10};
    uint64_t c = 9; /* push ebp .. cmp edi,esi; jbe */
    int backward = 0;

    if (dst > src) {
        c += 4;
        backward = dst < src + n;
    }
    if (!backward) {
        c += 2; /* test edi,3; jne */
        if ((dst & 3) == 0)
            return c + 3 + (n >> 2) + 1 + 1 + fwd_tail[n & 3];
        c += 2; /* cmp ecx,12; jbe */
        if (n <= 12)
            return c + (n + 1) + 5;
        {
            uint32_t head = (0u - dst) & 3, rest = n - head;
            return c + 6 + (head + 1) + 3 + ((rest >> 2) + 1) + 1 + fwd_tail[rest & 3];
        }
    }
    c += 3 + 2; /* std; add; add; test edi,3; jne */
    if (((dst + n) & 3) == 0)
        return c + 5 + (n >> 2) + 1 + 1 + bwd_tail[n & 3];
    c += 4; /* dec; dec; cmp; jbe */
    if (n <= 12)
        return c + (n + 1) + 6;
    return c + 5 + 1 + 5 + ((n >> 2) + 1) + 1 + bwd_tail[n & 3];
}

/* The same for the runtime's memset (DUEL.EXE 0x004da190): bytes up to a dword boundary, `rep stosd`, the tail. */
uint64_t crt_memset_instructions(uint32_t dst, uint32_t n)
{
    uint64_t c = 10; /* up to the length test */
    uint32_t head, words, tail;

    if (n == 0)
        return 6;
    if (n < 4)
        return c + 4 * (uint64_t)n + 3;
    c += 3; /* neg; and; je */
    head = (0u - dst) & 3;
    if (head)
        c += 1 + 4 * (uint64_t)head;
    c += 6 + 4; /* the byte replicated through EAX; the word count */
    words = (n - head) >> 2;
    tail = (n - head) & 3;
    if (words)
        c += (uint64_t)words + 1 + 2; /* rep stosd; test; je */
    c += 4 * (uint64_t)tail + 3;
    return c;
}

uint32_t Native_Crt_Memset(Vm *vm, uint32_t dst, uint32_t value, uint32_t n)
{
    uint32_t i;

    NATIVE_ENTER(FN_CRT_MEMSET);
    native_cost_extra += crt_memset_instructions(dst, n);
    for (i = 0; i < n; i++)
        mem_wr8(vm->mem, dst + i, (uint8_t)value);
    return dst;
}

uint32_t Native_Crt_Memcpy(Vm *vm, uint32_t dst, uint32_t src, uint32_t n)
{
    NATIVE_ENTER(FN_CRT_MEMCPY);
    native_cost_extra += crt_memcpy_instructions(dst, src, n);
    mem_copy(vm->mem, dst, src, n);
    return dst;
}

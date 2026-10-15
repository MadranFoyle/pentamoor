/*
 * mem.h - a sparse memory image addressed by the original program's virtual addresses.
 *
 * Native replacements of game functions keep using the original global addresses (0x006a3f78,
 * the card-slot table at 0x006a5f30, ...), so a function's state can be loaded from a snapshot of
 * the original, and later from the emulated original itself, without translating any pointers.
 *
 * Memory is kept in 4 KiB pages created on first use. Every byte also has a "defined" bit: a byte
 * is defined once it has been loaded or written. Reading an undefined byte returns 0 and is recorded
 * as a fault, which tells a test that its snapshot is missing an input the function needs.
 *
 * All accessors are little-endian, like the original x86 code, whatever the host byte order.
 */
#ifndef NATIVE_MEM_H
#define NATIVE_MEM_H

#include <stddef.h>
#include <stdint.h>

#define MEM_MAX_FAULTS 32

typedef struct MemPage MemPage;

typedef struct Mem {
    MemPage *buckets[1024];
    uint32_t faults[MEM_MAX_FAULTS]; /* first undefined addresses read, in order */
    int fault_count;                 /* total undefined reads, may exceed MEM_MAX_FAULTS */
    void (*on_write)(void *ctx, uint32_t addr, size_t len); /* optional write observer */
    void *on_write_ctx;
    /* An external backend (the emulator hosting the native layer, native_host.c): when set, every access goes to it and
     * nothing is held here. All bytes count as defined. */
    uint32_t (*ext_read)(void *ctx, uint32_t addr, int size);
    void (*ext_write)(void *ctx, uint32_t addr, int size, uint32_t value);
    void *ext_ctx;
    /* Optional: copy `len` bytes inside the guest in one go (memmove semantics). Returns 0 when it cannot (the copy then goes
     * through ext_read/ext_write). */
    int (*ext_copy)(void *ctx, uint32_t dst, uint32_t src, uint32_t len);
} Mem;

void mem_init(Mem *m);
void mem_free(Mem *m);

/* Load bytes without counting them as writes (snapshot input). */
void mem_load(Mem *m, uint32_t addr, const uint8_t *src, size_t len);
int mem_is_defined(const Mem *m, uint32_t addr);

uint8_t mem_rd8(Mem *m, uint32_t addr);
uint16_t mem_rd16(Mem *m, uint32_t addr);
uint32_t mem_rd32(Mem *m, uint32_t addr);
void mem_wr8(Mem *m, uint32_t addr, uint8_t v);
void mem_wr16(Mem *m, uint32_t addr, uint16_t v);
void mem_wr32(Mem *m, uint32_t addr, uint32_t v);

/* memmove inside the image (the original calls the C runtime's memcpy). */
void mem_copy(Mem *m, uint32_t dst, uint32_t src, size_t len);

#endif

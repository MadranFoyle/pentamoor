/* guest.c - the guest's address space, a log, and the allocator. */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "plat.h"
#include "port.h"

uint8_t *G;

void port_log(const char *fmt, ...)
{
    va_list ap;

    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
}

void port_trace(const char *fmt, ...)
{
    static int on = -1;
    va_list ap;

    if (on < 0)
        on = getenv("PORT_TRACE") != NULL;
    if (!on)
        return;
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
}

void port_fatal(const char *fmt, ...)
{
    va_list ap;

    fprintf(stderr, "port: ");
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
    exit(2);
}

void guest_init(void)
{
    /* All of the 32-bit address space; pages are committed when first touched (plat.h). */
    plat_init();
    G = plat_guest_reserve();
    if (!G)
        port_fatal("cannot reserve the guest's address space");
}

void guest_write(uint32_t addr, const void *src, uint32_t len)
{
    memcpy(G + addr, src, len);
}

void guest_zero(uint32_t addr, uint32_t len)
{
    memset(G + addr, 0, len);
}

uint32_t guest_cstr_len(uint32_t addr)
{
    return (uint32_t)strlen((const char *)(G + addr));
}

/* ---- the heap: first fit over a reserved range, with a size header before each block ------------------------------------------------ */
#define HEAP_BASE 0x50000000u
#define HEAP_LIMIT 0x6F000000u

typedef struct { uint32_t addr, size, used; } Block;
static Block *blocks;
static int nblocks, capblocks;
static uint32_t heap_top = HEAP_BASE;

uint32_t heap_alloc(uint32_t size)
{
    int i;
    uint32_t n;

    /* More than the heap's whole range is a request that cannot be met, as the C library's and Windows' own allocators say (NULL, a failed HeapAlloc). Most often it is a negative size that
     * arrived unsigned (-48 is 0xffffffd0): rounded up to 16 it wrapped to 0 and became a block of 16 bytes, and for the sizes that did not wrap, heap_top + n wrapped round the end of the
     * 4 GiB address space, passed the limit test and moved heap_top backwards, so the next blocks overlapped the live ones. */
    if (size > HEAP_LIMIT - HEAP_BASE)
        return 0;
    n = (size + 15u) & ~15u;
    if (!n)
        n = 16;
    for (i = 0; i < nblocks; i++)
        if (!blocks[i].used && blocks[i].size >= n) {
            if (blocks[i].size >= n + 64) {        /* split off the rest */
                if (nblocks == capblocks) {
                    capblocks = capblocks ? capblocks * 2 : 1024;
                    blocks = realloc(blocks, (size_t)capblocks * sizeof(*blocks));
                }
                memmove(&blocks[i + 2], &blocks[i + 1], (size_t)(nblocks - i - 1) * sizeof(*blocks));
                blocks[i + 1] = (Block){blocks[i].addr + n, blocks[i].size - n, 0};
                blocks[i].size = n;
                nblocks++;
            }
            blocks[i].used = 1;
            return blocks[i].addr;
        }
    if (heap_top + n > HEAP_LIMIT)
        return 0;
    if (nblocks == capblocks) {
        capblocks = capblocks ? capblocks * 2 : 1024;
        blocks = realloc(blocks, (size_t)capblocks * sizeof(*blocks));
    }
    blocks[nblocks++] = (Block){heap_top, n, 1};
    heap_top += n;
    return blocks[nblocks - 1].addr;
}

static Block *find_block(uint32_t addr)
{
    int lo = 0, hi = nblocks - 1;

    while (lo <= hi) {          /* blocks are in address order */
        int mid = (lo + hi) / 2;

        if (blocks[mid].addr == addr)
            return &blocks[mid];
        if (blocks[mid].addr < addr)
            lo = mid + 1;
        else
            hi = mid - 1;
    }
    return NULL;
}

void heap_free(uint32_t addr)
{
    Block *b = find_block(addr);

    if (b)
        b->used = 0;
}

uint32_t heap_size(uint32_t addr)
{
    Block *b = find_block(addr);

    return b && b->used ? b->size : 0;
}

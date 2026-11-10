/* guest.c - the guest's address space, a log, and the allocator. */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

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
    uint8_t *mem;
    const char *delay = getenv("PORT_GUEST_DELAY_MS");

    plat_init();
    if (delay && atoi(delay) > 0)           /* a test aid: the guest's memory comes late, as it does on a loaded machine (the control-pipe check of the Makefile) */
        usleep((useconds_t)atoi(delay) * 1000u);
    /* All of the 32-bit address space; pages are committed when first touched (plat.h). */
    mem = plat_guest_reserve();

    if (!mem)
        port_fatal("cannot reserve the guest's address space");
    __atomic_store_n(&G, mem, __ATOMIC_RELEASE);        /* the window's thread reads it (guest_ready) while this one is starting */
}

int guest_ready(void)
{
    return __atomic_load_n(&G, __ATOMIC_ACQUIRE) != NULL;
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

static unsigned long long heap_allocs, heap_frees;
static long heap_log_s = -1;            /* PORT_HEAP_LOG=SECONDS: a line about the heap every SECONDS (0 or unset: only at the `heap` control command) */
static time_t heap_log_last;
volatile int heap_report_request;       /* the control command `heap` (front_sdl.c) asks; the game's own thread answers at its next allocation, since it owns the block table */
static void heap_report(FILE *out);

uint32_t heap_alloc(uint32_t size)
{
    int i;
    uint32_t n;

    if (heap_log_s < 0) {
        const char *e = getenv("PORT_HEAP_LOG");

        heap_log_s = e ? atol(e) : 0;
        heap_log_last = time(NULL);
    }
    if ((++heap_allocs & 255) == 0 || heap_report_request) {
        time_t now = time(NULL);

        if (heap_report_request || (heap_log_s > 0 && now - heap_log_last >= heap_log_s)) {
            heap_report_request = 0;
            heap_log_last = now;
            heap_report(stderr);
        }
    }

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

    heap_frees++;
    if (b)
        b->used = 0;
}

/* One line about the guest's heap: blocks in use and free (count and KiB), the largest free block, how far the heap has grown (heap_top: pages the guest has touched stay resident, a freed block's too),
 * and the blocks in use by size class. PORT_HEAP_LOG and the `heap` command print it; it is how the memory growth of a long duel was told to be the game's or the runtime's (docs/notes/memory.md). */
static void heap_report(FILE *out)
{
    static const uint32_t lim[] = {64, 256, 1024, 4096, 65536, 1u << 20};
    unsigned long long used_n = 0, used_b = 0, free_n = 0, free_b = 0, cls_n[8] = {0}, cls_b[8] = {0};
    uint32_t largest = 0;
    int i, c;

    for (i = 0; i < nblocks; i++) {
        if (blocks[i].used) {
            used_n++;
            used_b += blocks[i].size;
            for (c = 0; c < 6 && blocks[i].size > lim[c]; c++)
                ;
            cls_n[c]++;
            cls_b[c] += blocks[i].size;
        } else {
            free_n++;
            free_b += blocks[i].size;
            if (blocks[i].size > largest)
                largest = blocks[i].size;
        }
    }
    fprintf(out, "heap: top %llu KiB, in use %llu blocks %llu KiB, free %llu blocks %llu KiB (largest %u), %llu allocs %llu frees; in use by size: <=64 %llu/%lluK, <=256 %llu/%lluK, <=1K %llu/%lluK, <=4K %llu/%lluK, <=64K %llu/%lluK, <=1M %llu/%lluK, more %llu/%lluK\n",
            (unsigned long long)(heap_top - HEAP_BASE) >> 10, used_n, used_b >> 10, free_n, free_b >> 10, largest, heap_allocs, heap_frees,
            cls_n[0], cls_b[0] >> 10, cls_n[1], cls_b[1] >> 10, cls_n[2], cls_b[2] >> 10, cls_n[3], cls_b[3] >> 10, cls_n[4], cls_b[4] >> 10, cls_n[5], cls_b[5] >> 10, cls_n[6], cls_b[6] >> 10);
    fflush(out);
}

uint32_t heap_size(uint32_t addr)
{
    Block *b = find_block(addr);

    return b && b->used ? b->size : 0;
}

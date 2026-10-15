/*
 * mem.c - sparse memory image (see mem.h).
 */
#include "mem.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PAGE_BITS 12
#define PAGE_SIZE (1u << PAGE_BITS)
#define BUCKETS (sizeof(((Mem *)0)->buckets) / sizeof(((Mem *)0)->buckets[0]))

struct MemPage {
    uint32_t number; /* addr >> PAGE_BITS */
    MemPage *next;
    uint8_t data[PAGE_SIZE];
    uint8_t defined[PAGE_SIZE / 8];
};

void mem_init(Mem *m)
{
    memset(m, 0, sizeof(*m));
}

void mem_free(Mem *m)
{
    size_t i;
    for (i = 0; i < BUCKETS; i++) {
        MemPage *p = m->buckets[i];
        while (p) {
            MemPage *next = p->next;
            free(p);
            p = next;
        }
        m->buckets[i] = NULL;
    }
}

static MemPage *find_page(const Mem *m, uint32_t addr)
{
    uint32_t number = addr >> PAGE_BITS;
    MemPage *p = m->buckets[number % BUCKETS];
    while (p && p->number != number)
        p = p->next;
    return p;
}

static MemPage *get_page(Mem *m, uint32_t addr)
{
    MemPage *p = find_page(m, addr);
    if (!p) {
        uint32_t number = addr >> PAGE_BITS;
        p = calloc(1, sizeof(*p));
        if (!p) {
            fprintf(stderr, "mem: out of memory\n");
            exit(2);
        }
        p->number = number;
        p->next = m->buckets[number % BUCKETS];
        m->buckets[number % BUCKETS] = p;
    }
    return p;
}

static void put_byte(Mem *m, uint32_t addr, uint8_t v)
{
    MemPage *p = get_page(m, addr);
    uint32_t off = addr & (PAGE_SIZE - 1);
    p->data[off] = v;
    p->defined[off >> 3] |= (uint8_t)(1u << (off & 7));
}

static uint8_t get_byte(Mem *m, uint32_t addr)
{
    const MemPage *p = find_page(m, addr);
    uint32_t off = addr & (PAGE_SIZE - 1);
    if (!p || !(p->defined[off >> 3] & (1u << (off & 7)))) {
        if (m->fault_count < MEM_MAX_FAULTS)
            m->faults[m->fault_count] = addr;
        m->fault_count++;
        return 0;
    }
    return p->data[off];
}

int mem_is_defined(const Mem *m, uint32_t addr)
{
    if (m->ext_read)
        return 1;
    const MemPage *p = find_page(m, addr);
    uint32_t off = addr & (PAGE_SIZE - 1);
    return p && (p->defined[off >> 3] & (1u << (off & 7)));
}

void mem_load(Mem *m, uint32_t addr, const uint8_t *src, size_t len)
{
    size_t i;
    for (i = 0; i < len; i++) {
        if (m->ext_write)
            m->ext_write(m->ext_ctx, addr + (uint32_t)i, 1, src[i]);
        else
            put_byte(m, addr + (uint32_t)i, src[i]);
    }
}

static void written(Mem *m, uint32_t addr, size_t len)
{
    if (m->on_write)
        m->on_write(m->on_write_ctx, addr, len);
}

uint8_t mem_rd8(Mem *m, uint32_t addr)
{
    if (m->ext_read)
        return (uint8_t)m->ext_read(m->ext_ctx, addr, 1);
    return get_byte(m, addr);
}

uint16_t mem_rd16(Mem *m, uint32_t addr)
{
    if (m->ext_read)
        return (uint16_t)m->ext_read(m->ext_ctx, addr, 2);
    return (uint16_t)(get_byte(m, addr) | (get_byte(m, addr + 1) << 8));
}

uint32_t mem_rd32(Mem *m, uint32_t addr)
{
    if (m->ext_read)
        return m->ext_read(m->ext_ctx, addr, 4);
    return (uint32_t)get_byte(m, addr) | ((uint32_t)get_byte(m, addr + 1) << 8) |
           ((uint32_t)get_byte(m, addr + 2) << 16) | ((uint32_t)get_byte(m, addr + 3) << 24);
}

void mem_wr8(Mem *m, uint32_t addr, uint8_t v)
{
    if (m->ext_write) {
        m->ext_write(m->ext_ctx, addr, 1, v);
        return;
    }
    put_byte(m, addr, v);
    written(m, addr, 1);
}

void mem_wr16(Mem *m, uint32_t addr, uint16_t v)
{
    if (m->ext_write) {
        m->ext_write(m->ext_ctx, addr, 2, v);
        return;
    }
    put_byte(m, addr, (uint8_t)v);
    put_byte(m, addr + 1, (uint8_t)(v >> 8));
    written(m, addr, 2);
}

void mem_wr32(Mem *m, uint32_t addr, uint32_t v)
{
    if (m->ext_write) {
        m->ext_write(m->ext_ctx, addr, 4, v);
        return;
    }
    put_byte(m, addr, (uint8_t)v);
    put_byte(m, addr + 1, (uint8_t)(v >> 8));
    put_byte(m, addr + 2, (uint8_t)(v >> 16));
    put_byte(m, addr + 3, (uint8_t)(v >> 24));
    written(m, addr, 4);
}

void mem_copy(Mem *m, uint32_t dst, uint32_t src, size_t len)
{
    size_t i;
    uint8_t *tmp;
    if (m->ext_copy && len && m->ext_copy(m->ext_ctx, dst, src, (uint32_t)len)) {
        written(m, dst, len);
        return;
    }
    tmp = malloc(len ? len : 1);
    if (!tmp) {
        fprintf(stderr, "mem: out of memory\n");
        exit(2);
    }
    for (i = 0; i < len; i++)
        tmp[i] = mem_rd8(m, src + (uint32_t)i);
    for (i = 0; i < len; i++) {
        if (m->ext_write)
            m->ext_write(m->ext_ctx, dst + (uint32_t)i, 1, tmp[i]);
        else
            put_byte(m, dst + (uint32_t)i, tmp[i]);
    }
    free(tmp);
    written(m, dst, len);
}

/* pe.c - map a PE image into the guest's address space and build its imports. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "port.h"
#include "wm.h"

#define STUB_BASE 0x70000000u   /* the addresses the import table holds: one 16-byte slot per import, never executed */

typedef struct { uint32_t base, res_rva, exp_rva, exp_size; } LoadedImage;
static LoadedImage loaded[16];
static int nloaded;
static Import *imports;
static int nimports, capimports;

/* The file's bytes for an RVA (the file is read whole, the sections are not laid out in it): found through the section table. */
static const uint8_t *file_rva(const uint8_t *file, uint32_t nt, uint32_t rva)
{
    uint32_t nsec = (uint32_t)(file[nt + 6] | file[nt + 7] << 8), opt_size = (uint32_t)(file[nt + 20] | file[nt + 21] << 8), i;
    const uint8_t *sec = file + nt + 24 + opt_size;

    for (i = 0; i < nsec; i++, sec += 40) {
        uint32_t va = (uint32_t)(sec[12] | sec[13] << 8 | sec[14] << 16 | (uint32_t)sec[15] << 24);
        uint32_t rsize = (uint32_t)(sec[16] | sec[17] << 8 | sec[18] << 16 | (uint32_t)sec[19] << 24), roff = (uint32_t)(sec[20] | sec[21] << 8 | sec[22] << 16 | (uint32_t)sec[23] << 24);

        if (rva >= va && rva < va + rsize)
            return file + roff + (rva - va);
    }
    port_fatal("relocation data outside the file's sections (rva 0x%x)", rva);
}

static uint32_t le32(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static uint16_t le16(const uint8_t *p) { return (uint16_t)(p[0] | p[1] << 8); }

static void add_import(const char *dll, const char *name, uint32_t slot)
{
    Import *im;
    int i;
    const LiftImportSig *sig = NULL;
    uint32_t forward = module_import(dll, name);       /* an export of a library that was lifted: a call goes straight to its code */

    if (nimports == capimports) {
        capimports = capimports ? capimports * 2 : 512;
        imports = realloc(imports, (size_t)capimports * sizeof(*imports));
    }
    im = &imports[nimports];
    memset(im, 0, sizeof(*im));
    im->dll = strdup(dll);
    im->name = strdup(name);
    im->slot = slot;
    im->stub = STUB_BASE + 16u * (uint32_t)nimports;
    for (i = 0; i < lift_game->nsigs; i++)
        if (!strcmp(lift_game->sigs[i].name, name) && !strcmp(lift_game->sigs[i].dll, dll)) {
            sig = &lift_game->sigs[i];
            break;
        }
    for (i = 0; !sig && lift_game->modules[i]; i++) {
        int k;

        for (k = 0; k < lift_game->modules[i]->nsigs; k++)
            if (!strcmp(lift_game->modules[i]->sigs[k].name, name) && !strcmp(lift_game->modules[i]->sigs[k].dll, dll)) {
                sig = &lift_game->modules[i]->sigs[k];
                break;
            }
    }
    if (sig) {
        im->nargs = sig->nargs;
        im->cleanup = sig->cleanup;
    }
    {
        const WinApi *api = port_find_api(dll, name);

        im->fn = api ? api->fn : NULL;
    }
    im->forward = forward;
    WR32(slot, forward ? forward : im->stub);
    nimports++;
}

Import *import_by_slot_or_stub(uint32_t addr)
{
    if (addr >= STUB_BASE && addr < STUB_BASE + 16u * (uint32_t)nimports && !(addr & 15))
        return &imports[(addr - STUB_BASE) / 16];
    /* a call through the table names the slot: found through a hash of the slots (a program that measures every character it draws makes a hundred thousand such calls a second) */
    {
        static int *index_table, indexed, mask;
        int i;

        if (indexed != nimports) {
            int cap = 1;

            while (cap < nimports * 2 + 2)
                cap <<= 1;
            free(index_table);
            index_table = malloc((size_t)cap * sizeof(*index_table));
            memset(index_table, 0xff, (size_t)cap * sizeof(*index_table));
            mask = cap - 1;
            for (i = 0; i < nimports; i++) {
                int h = (int)((imports[i].slot >> 2) * 2654435761u >> 7) & mask;

                while (index_table[h] >= 0)
                    h = (h + 1) & mask;
                index_table[h] = i;
            }
            indexed = nimports;
        }
        for (i = (int)((addr >> 2) * 2654435761u >> 7) & mask; index_table[i] >= 0; i = (i + 1) & mask)
            if (imports[index_table[i]].slot == addr)
                return &imports[index_table[i]];
    }
    return NULL;
}

void imports_report(void)
{
    int i, n = 0;

    if (getenv("PORT_CALLS"))               /* every import the run called, and how often */
        for (i = 0; i < nimports; i++)
            if (imports[i].calls)
                fprintf(stderr, "    %8llu %s!%s%s\n", (unsigned long long)imports[i].calls, imports[i].dll, imports[i].name, imports[i].fn || imports[i].forward ? "" : "  (not implemented)");

    for (i = 0; i < nimports; i++)
        if (imports[i].calls && !imports[i].fn && !imports[i].forward)
            n++;
    if (!n)
        return;
    fprintf(stderr, "port: imports called that are not implemented yet (%d):\n", n);
    for (i = 0; i < nimports; i++)
        if (imports[i].calls && !imports[i].fn && !imports[i].forward)
            fprintf(stderr, "    %s!%s  x%llu\n", imports[i].dll, imports[i].name, (unsigned long long)imports[i].calls);
}

int pe_load(const char *path, Image *img) { return pe_load_module(path, 0, img); }

/* Map a PE file into the guest: at its own base (base == 0), or at `base`, applying the base relocations (a DLL the lifter made code for). */
int pe_load_module(const char *path, uint32_t want_base, Image *img)
{
    FILE *f = fopen(path, "rb");
    uint8_t *file;
    long len;
    uint32_t nt, base, nsec, i, opt_size, imp_rva, reloc_delta, reloc_rva, reloc_size;
    const uint8_t *opt, *sec;

    if (!f)
        return -1;
    fseek(f, 0, SEEK_END);
    len = ftell(f);
    fseek(f, 0, SEEK_SET);
    file = malloc((size_t)len);
    if (fread(file, 1, (size_t)len, f) != (size_t)len)
        port_fatal("cannot read %s", path);
    fclose(f);
    if (len < 0x200 || file[0] != 'M' || file[1] != 'Z')
        port_fatal("%s is not a PE file", path);
    nt = le32(file + 0x3c);
    if (memcmp(file + nt, "PE\0\0", 4))
        port_fatal("%s: no PE signature", path);
    nsec = le16(file + nt + 6);
    opt_size = le16(file + nt + 20);
    opt = file + nt + 24;
    base = le32(opt + 28);
    reloc_delta = want_base ? want_base - base : 0;
    reloc_rva = le32(opt + 136);
    reloc_size = le32(opt + 140);
    if (want_base)
        base = want_base;
    img->base = base;
    img->entry = base + le32(opt + 16);
    img->size = le32(opt + 56);
    img->path = path;
    imp_rva = le32(opt + 104);       /* data directory 1: imports */
    if (nloaded < 16)
        loaded[nloaded++] = (LoadedImage){base, le32(opt + 112), le32(opt + 96), le32(opt + 100)};   /* data directories 2 (resources) and 0 (exports) */
    sec = opt + opt_size;
    guest_write(base, file, le32(opt + 60));    /* the headers */
    for (i = 0; i < nsec; i++, sec += 40) {
        uint32_t va = base + le32(sec + 12), vsize = le32(sec + 8), rsize = le32(sec + 16), roff = le32(sec + 20);

        if (rsize > vsize && vsize)
            rsize = vsize;
        if (rsize)
            guest_write(va, file + roff, rsize);
    }
    /* Base relocations: blocks of 16-bit entries (type in the top four bits, offset in the rest), type 3 a 32-bit address to add the delta to. */
    if (reloc_delta && reloc_rva) {
        uint32_t at = 0;

        while (at + 8 <= reloc_size) {
            uint32_t page = le32(file_rva(file, nt, reloc_rva + at)), blk = le32(file_rva(file, nt, reloc_rva + at + 4)), k;

            if (blk < 8)
                break;
            for (k = 8; k + 2 <= blk; k += 2) {
                uint16_t e = le16(file_rva(file, nt, reloc_rva + at + k));

                if ((e >> 12) == 3)
                    WR32(base + page + (e & 0xFFF), RD32(base + page + (e & 0xFFF)) + reloc_delta);
            }
            at += blk;
        }
    }
    /* The imports: each descriptor names a DLL and two parallel arrays (names, and the table the loader fills). */
    if (imp_rva) {
        uint32_t d = base + imp_rva;

        for (; RD32(d + 12); d += 20) {
            const char *dll = (const char *)(G + base + RD32(d + 12));
            char lower[64];
            uint32_t names = base + (RD32(d) ? RD32(d) : RD32(d + 16)), slot = base + RD32(d + 16);
            size_t k;

            for (k = 0; dll[k] && k < sizeof(lower) - 1; k++)
                lower[k] = (char)((dll[k] >= 'A' && dll[k] <= 'Z') ? dll[k] + 32 : dll[k]);
            lower[k] = 0;
            for (; RD32(names); names += 4, slot += 4) {
                uint32_t thunk = RD32(names);

                if (thunk & 0x80000000u) {
                    char ord[16];

                    snprintf(ord, sizeof(ord), "#%u", thunk & 0xffffu);
                    add_import(lower, ord, slot);
                } else
                    add_import(lower, (const char *)(G + base + thunk + 2), slot);
            }
        }
    }
    free(file);
    return 0;
}

/* ---- exports ------------------------------------------------------------------------------------------------------------------ */
/* The address of an export of a mapped image, by name or as "#ordinal"; 0 if there is none. */
uint32_t pe_export(uint32_t hmod, const char *name)
{
    int i;

    for (i = 0; i < nloaded; i++)
        if (loaded[i].base == hmod && loaded[i].exp_rva) {
            uint32_t d = hmod + loaded[i].exp_rva, nfun = RD32(d + 20), nnames = RD32(d + 24), k;
            uint32_t funcs = hmod + RD32(d + 28), names = hmod + RD32(d + 32), ords = hmod + RD32(d + 36), first = RD32(d + 16);

            if (name[0] == '#') {
                uint32_t ord = (uint32_t)atoi(name + 1);

                return ord >= first && ord - first < nfun ? hmod + RD32(funcs + 4 * (ord - first)) : 0;
            }
            for (k = 0; k < nnames; k++)
                if (!strcmp((const char *)(G + hmod + RD32(names + 4 * k)), name))
                    return hmod + RD32(funcs + 4 * RD16(ords + 2 * k));
        }
    return 0;
}

/* ---- resources ---------------------------------------------------------------------------------------------------------------- */
static int name_matches(uint32_t res_dir, uint32_t entry_name, uint32_t want)
{
    if (want <= 0xFFFF)
        return !(entry_name & 0x80000000u) && entry_name == want;
    if (!(entry_name & 0x80000000u))
        return 0;
    {
        uint32_t at = res_dir + (entry_name & 0x7FFFFFFFu);
        uint32_t len = (uint32_t)(G[at] | G[at + 1] << 8), i;
        const char *w = (const char *)(G + want);

        if (strlen(w) != len)
            return 0;
        for (i = 0; i < len; i++) {
            char c = (char)G[at + 2 + 2 * i], d = w[i];

            if (c >= 'a' && c <= 'z')
                c -= 32;
            if (d >= 'a' && d <= 'z')
                d -= 32;
            if (c != d)
                return 0;
        }
    }
    return 1;
}

/* The directory entry of `want` (an id, or a name's address) in the resource directory at `dir`; returns its OffsetToData or 0xFFFFFFFF. */
static uint32_t res_lookup(uint32_t res_dir, uint32_t dir, uint32_t want, int any)
{
    uint32_t n = (uint32_t)(RD16(dir + 12) + RD16(dir + 14)), i;

    for (i = 0; i < n; i++) {
        uint32_t e = dir + 16 + 8 * i;

        if (any || name_matches(res_dir, RD32(e), want))
            return RD32(e + 4);
    }
    return 0xFFFFFFFFu;
}

int pe_find_resource(uint32_t hinst, uint32_t type, uint32_t name, uint32_t *addr, uint32_t *size)
{
    int i;

    for (i = 0; i < nloaded; i++)
        if (hinst == 0 || loaded[i].base == hinst) {
            uint32_t base = loaded[i].base, res_dir, off, leaf;

            if (!loaded[i].res_rva)
                return 0;
            res_dir = base + loaded[i].res_rva;
            off = res_lookup(res_dir, res_dir, type, 0);
            if (off == 0xFFFFFFFFu || !(off & 0x80000000u))
                return 0;
            off = res_lookup(res_dir, res_dir + (off & 0x7FFFFFFFu), name, 0);
            if (off == 0xFFFFFFFFu || !(off & 0x80000000u))
                return 0;
            off = res_lookup(res_dir, res_dir + (off & 0x7FFFFFFFu), 0, 1);          /* the first language */
            if (off == 0xFFFFFFFFu || (off & 0x80000000u))
                return 0;
            leaf = res_dir + off;
            *addr = base + RD32(leaf);
            *size = RD32(leaf + 4);
            return 1;
        }
    return 0;
}

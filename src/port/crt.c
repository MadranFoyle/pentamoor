/* crt.c - the C runtime (MSVCRTD.DLL) in C: start-up, memory, strings, numbers. The behaviour is the Python layer's (winemu/crt.py). */
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <time.h>

#include "port.h"
#include "process.h"
#include "sched.h"
#include "seed.h"

#define P(a) ((char *)(G + (a)))
#define U8(a) (*(uint8_t *)(G + (a)))

static uint32_t errno_cell, fmode_cell, commode_cell, argv_cell, argc_cell, environ_cell, acmdln_cell, mb_cur_max_cell, pctype_cell;
static uint32_t rand_seed = 1;
static int crt_ready;

static void crt_init(void)
{
    char line[700], *tok[16];
    uint32_t arr, strings;
    int n = 0, i;
    size_t len;

    if (crt_ready)
        return;
    crt_ready = 1;
    errno_cell = heap_alloc(4);
    fmode_cell = heap_alloc(4);
    commode_cell = heap_alloc(4);
    mb_cur_max_cell = heap_alloc(4);
    pctype_cell = heap_alloc(4);
    argv_cell = heap_alloc(4);
    argc_cell = heap_alloc(4);
    environ_cell = heap_alloc(4);
    acmdln_cell = heap_alloc(4);
    proc_program_path(line, sizeof(line));                    /* the program's path and the arguments the program that started it gave (process.h) */
    len = strlen(line);
    strings = heap_alloc((uint32_t)len + 1);
    strcpy(P(strings), line);
    for (i = 0; line[i] && n < 16;) {                         /* split on blanks, a quoted word as one */
        while (line[i] == ' ')
            i++;
        if (!line[i])
            break;
        if (line[i] == '"') {
            tok[n++] = line + ++i;
            while (line[i] && line[i] != '"')
                i++;
        } else {
            tok[n++] = line + i;
            while (line[i] && line[i] != ' ')
                i++;
        }
        if (line[i])
            line[i++] = 0;
    }
    arr = heap_alloc(4u * ((uint32_t)n + 1));
    for (i = 0; i < n; i++) {
        uint32_t s = heap_alloc((uint32_t)strlen(tok[i]) + 1);

        strcpy(P(s), tok[i]);
        WR32(arr + 4u * (uint32_t)i, s);
    }
    WR32(arr + 4u * (uint32_t)n, 0);
    WR32(argv_cell, arr);
    WR32(argc_cell, (uint32_t)n);
    WR32(environ_cell, heap_alloc(8));
    WR32(acmdln_cell, strings);
    WR32(mb_cur_max_cell, 1);
}

static uint32_t cell(uint32_t *c) { crt_init(); return *c; }

/* ---- start-up ---------------------------------------------------------------------------------------------------------------------- */
static uint32_t zero(const uint32_t *a) { (void)a; return 0; }
static uint32_t one(const uint32_t *a) { (void)a; return 1; }
static uint32_t controlfp(const uint32_t *a) { (void)a; return 0x9001F; }
static uint32_t p_fmode(const uint32_t *a) { (void)a; return cell(&fmode_cell); }
static uint32_t p_commode(const uint32_t *a) { (void)a; return cell(&commode_cell); }
static uint32_t p_argv(const uint32_t *a) { (void)a; return cell(&argv_cell); }
static uint32_t p_acmdln(const uint32_t *a) { (void)a; return cell(&acmdln_cell); }
static uint32_t p_mb_cur_max(const uint32_t *a) { (void)a; return cell(&mb_cur_max_cell); }
static uint32_t p_pctype(const uint32_t *a) { (void)a; return cell(&pctype_cell); }
static uint32_t crt_errno(const uint32_t *a) { (void)a; return cell(&errno_cell); }

static uint32_t getmainargs(const uint32_t *a)
{
    crt_init();
    WR32(a[0], RD32(argc_cell));
    WR32(a[1], RD32(argv_cell));
    WR32(a[2], RD32(environ_cell));
    return 0;
}

static uint32_t initterm(const uint32_t *a)
{
    uint32_t p;

    for (p = a[0]; p < a[1]; p += 4)
        if (RD32(p))
            guest_call(RD32(p), 0, NULL);
    return 0;
}

static uint32_t crt_exit(const uint32_t *a)
{
    fflush(NULL);
    exit((int)a[0]);
}

static uint32_t crt_assert(const uint32_t *a)
{
    port_fatal("assertion failed: %s %s line %u", P(a[0]), P(a[1]), a[2]);
}

static uint32_t crt_onexit(const uint32_t *a) { return a[0]; }

/* ---- memory ------------------------------------------------------------------------------------------------------------------------ */
static uint32_t crt_malloc(const uint32_t *a) { return heap_alloc(a[0]); }
static uint32_t crt_calloc(const uint32_t *a)
{
    uint64_t n = (uint64_t)a[0] * a[1];                      /* a product that does not fit in 32 bits is a request that cannot be met, not a small one */
    uint32_t p = n > 0xffffffffu ? 0 : heap_alloc((uint32_t)n);

    if (p)
        guest_zero(p, (uint32_t)n);
    return p;
}
static uint32_t crt_free(const uint32_t *a) { heap_free(a[0]); return 0; }
static uint32_t crt_free_dbg(const uint32_t *a) { heap_free(a[0]); return 0; }
static uint32_t crt_realloc(const uint32_t *a)
{
    uint32_t q = heap_alloc(a[1]), old = a[0] ? heap_size(a[0]) : 0;

    if (!q)
        return 0;                                            /* no room: NULL, and the old block stays as it was (it was copied to guest address 0 and freed) */
    if (a[0]) {
        memcpy(P(q), P(a[0]), old < a[1] ? old : a[1]);
        heap_free(a[0]);
    }
    return q;
}
static uint32_t crt_msize(const uint32_t *a) { return heap_size(a[0]); }
static uint32_t crt_expand(const uint32_t *a) { return a[1] <= heap_size(a[0]) ? a[0] : 0; }
/* A copy or a fill of 2 GiB or more is a negative length that reached the C runtime unsigned (the game's blit and scroll code makes a width as the view's width minus a distance and
 * does not look at the sign): in a 4 GiB address space it can only end in a fault, in the original (an access violation in MSVCRT) as here, where it was a bare SIGSEGV in the host's
 * memmove with nothing to say where from. Say what it was, and from where, and stop as the other fatal errors do (docs/notes/castle-dungeon-stats.md). */
static void crt_length_check(const char *fn, uint32_t n)
{
    if (n >= 0x80000000u)
        port_fatal("%s of %u bytes (%d as a signed number) called from the guest's 0x%08x: the game passed a negative size", fn, n, (int)n, RD32(port_sp));
}
static uint32_t crt_memcpy(const uint32_t *a) { crt_length_check("memcpy", a[2]); if (a[2]) memmove(P(a[0]), P(a[1]), a[2]); return a[0]; }
static uint32_t crt_memset(const uint32_t *a) { crt_length_check("memset", a[2]); if (a[2]) memset(P(a[0]), (int)(a[1] & 0xff), a[2]); return a[0]; }
static uint32_t crt_memcmp(const uint32_t *a)
{
    int c = memcmp(P(a[0]), P(a[1]), a[2]);

    return (uint32_t)((c > 0) - (c < 0));
}
static uint32_t crt_memchr(const uint32_t *a)
{
    const char *r = memchr(P(a[0]), (int)(a[1] & 0xff), a[2]);

    return r ? a[0] + (uint32_t)(r - P(a[0])) : 0;
}

/* ---- strings ----------------------------------------------------------------------------------------------------------------------- */
static uint32_t crt_strlen(const uint32_t *a) { return (uint32_t)strlen(P(a[0])); }
static uint32_t crt_strcpy(const uint32_t *a) { strcpy(P(a[0]), P(a[1])); return a[0]; }
static uint32_t crt_strcat(const uint32_t *a) { strcat(P(a[0]), P(a[1])); return a[0]; }
static uint32_t crt_strncpy(const uint32_t *a) { strncpy(P(a[0]), P(a[1]), a[2]); return a[0]; }
static uint32_t crt_strncat(const uint32_t *a) { strncat(P(a[0]), P(a[1]), a[2]); return a[0]; }
static uint32_t sign(int c) { return (uint32_t)((c > 0) - (c < 0)); }
static uint32_t crt_strcmp(const uint32_t *a) { return sign(strcmp(P(a[0]), P(a[1]))); }
static uint32_t crt_strncmp(const uint32_t *a) { return sign(strncmp(P(a[0]), P(a[1]), a[2])); }
static int ci_cmp(const char *x, const char *y, size_t n)
{
    for (; n; n--, x++, y++) {
        int cx = tolower((unsigned char)*x), cy = tolower((unsigned char)*y);

        if (cx != cy)
            return cx - cy;
        if (!cx)
            break;
    }
    return 0;
}
static uint32_t crt_stricmp(const uint32_t *a) { return sign(ci_cmp(P(a[0]), P(a[1]), (size_t)-1)); }
static uint32_t crt_strnicmp(const uint32_t *a) { return sign(ci_cmp(P(a[0]), P(a[1]), a[2])); }
static uint32_t crt_strchr(const uint32_t *a)
{
    const char *r = strchr(P(a[0]), (int)(a[1] & 0xff));

    return r ? a[0] + (uint32_t)(r - P(a[0])) : 0;
}
static uint32_t crt_strrchr(const uint32_t *a)
{
    const char *r = strrchr(P(a[0]), (int)(a[1] & 0xff));

    return r ? a[0] + (uint32_t)(r - P(a[0])) : 0;
}
static uint32_t crt_strspn(const uint32_t *a) { return (uint32_t)strspn(P(a[0]), P(a[1])); }
static uint32_t crt_strcspn(const uint32_t *a) { return (uint32_t)strcspn(P(a[0]), P(a[1])); }
static uint32_t crt_strlwr(const uint32_t *a)
{
    char *s;

    for (s = P(a[0]); *s; s++)
        *s = (char)tolower((unsigned char)*s);
    return a[0];
}
static uint32_t crt_tolower(const uint32_t *a) { return (a[0] >= 'A' && a[0] <= 'Z') ? a[0] + 32 : a[0]; }
static uint32_t crt_abs(const uint32_t *a) { int32_t v = (int32_t)a[0]; return (uint32_t)(v < 0 ? -v : v); }
static uint32_t crt_atoi(const uint32_t *a) { return (uint32_t)atoi(P(a[0])); }
static uint32_t crt_itoa(const uint32_t *a)
{
    int32_t v = (int32_t)a[0];
    uint32_t radix = a[2];
    char tmp[40];
    int n = 0, neg = v < 0 && radix == 10;
    uint32_t u = neg ? (uint32_t)-v : (uint32_t)v;

    if (u == 0)
        tmp[n++] = '0';
    while (u) {
        tmp[n++] = "0123456789abcdefghijklmnopqrstuvwxyz"[u % radix];
        u /= radix;
    }
    if (neg)
        tmp[n++] = '-';
    {
        char *d = P(a[1]);

        while (n)
            *d++ = tmp[--n];
        *d = 0;
    }
    return a[1];
}

/* ---- random numbers and the clock: the C runtime's own generator, so a seeded game repeats ------------------------------------------- */
/* PORT_SEED (seed.h): which part of the game asked for a number. The game's functions are a debug build's (push ebp, mov ebp esp), so the saved ebp links the frames and the word above it is a return
 * address: the key is made of the return addresses of the first three frames (the game's Random(n) and the two functions above it). A chain that stops looking like one ends there. */
static uint32_t rand_caller(void)
{
    uint32_t ebp = lift_out.ebp, key = 0;
    int depth;

    for (depth = 0; depth < 3 && ebp > 0x10000u && ebp < 0xf0000000u && (ebp & 3) == 0; depth++) {
        uint32_t next = RD32(ebp);

        key = key * 0x9e3779b1u + RD32(ebp + 4) + 1;
        if (next <= ebp)                                   /* the stack grows down: the caller's frame is above */
            break;
        ebp = next;
    }
    return key;
}
static uint32_t crt_rand(const uint32_t *a)
{
    (void)a;
    if (seed_active())
        return seed_rand(RD32(port_sp), rand_caller());
    rand_seed = rand_seed * 214013u + 2531011u;
    return (rand_seed >> 16) & 0x7fffu;
}
static uint32_t crt_srand(const uint32_t *a)
{
    if (seed_active()) {
        uint32_t site = RD32(port_sp), base = seed_srand(site);

        fprintf(stderr, "seed: srand(%u) from 0x%x: replaced, the streams start from 0x%08x\n", a[0], site, base);
        return 0;
    }
    rand_seed = a[0];
    return 0;
}
static uint32_t crt_clock(const uint32_t *a)
{
    uint32_t ms = (uint32_t)(port_now() * 1000.0);        /* milliseconds since the program started, by the wall clock (the host's clock() counts CPU time) */

    (void)a;
    return seed_active() ? seed_clock(ms) : ms;
}
static uint32_t crt_time(const uint32_t *a)
{
    uint32_t t = (uint32_t)time(NULL);

    if (a[0])
        WR32(a[0], t);
    return t;
}

/* ---- Spells of the Ancients: sorting, the collating order, character classes, and listing a folder ------------------------------------------------ */
/* qsort(base, count, width, compare): the comparison is the game's own function (cdecl, two element addresses, an int back), called through guest_call. A heap sort, in place in the
 * guest's array with a one element scratch block: the order of equal elements is not defined for qsort, and it needs no second array, which the comparison would have to be able to
 * see in the guest's memory. */
static void qsort_swap(uint8_t *x, uint8_t *y, uint32_t width)
{
    uint8_t tmp[256];

    while (width) {
        uint32_t n = width < sizeof(tmp) ? width : (uint32_t)sizeof(tmp);

        memcpy(tmp, x, n);
        memcpy(x, y, n);
        memcpy(y, tmp, n);
        x += n;
        y += n;
        width -= n;
    }
}

static int32_t qsort_compare(uint32_t cmp, uint32_t pa, uint32_t pb)
{
    uint32_t args[2] = {pa, pb};

    return (int32_t)guest_call(cmp, 2, args);
}

static void qsort_sift(uint32_t base, uint32_t width, uint32_t cmp, uint32_t root, uint32_t end)
{
    for (;;) {
        uint32_t child = 2 * root + 1, big = root;

        if (child >= end)
            return;
        if (qsort_compare(cmp, base + width * big, base + width * child) < 0)
            big = child;
        if (child + 1 < end && qsort_compare(cmp, base + width * big, base + width * (child + 1)) < 0)
            big = child + 1;
        if (big == root)
            return;
        qsort_swap((uint8_t *)P(base + width * root), (uint8_t *)P(base + width * big), width);
        root = big;
    }
}

static uint32_t crt_qsort(const uint32_t *a)
{
    uint32_t base = a[0], count = a[1], width = a[2], cmp = a[3], i;

    if (count < 2 || !width)
        return 0;
    for (i = count / 2; i-- > 0;)
        qsort_sift(base, width, cmp, i, count);
    for (i = count - 1; i > 0; i--) {
        qsort_swap((uint8_t *)P(base), (uint8_t *)P(base + width * i), width);
        qsort_sift(base, width, cmp, 0, i);
    }
    return 0;
}

/* strcoll in the "C" locale, the only one the game sets: the order of strcmp */
static uint32_t crt_strcoll(const uint32_t *a) { return sign(strcmp(P(a[0]), P(a[1]))); }

/* _isctype(c, mask): the class bits of the C locale for a character 0..255 (and EOF), masked; the bits are the C runtime's (ctype.h of Visual C++: _UPPER 1, _LOWER 2, _DIGIT 4,
 * _SPACE 8, _PUNCT 0x10, _CONTROL 0x20, _BLANK 0x40, _HEX 0x80; _ALPHA is 0x103). */
static uint32_t ctype_bits(int c)
{
    uint32_t b = 0;

    if (c < 0 || c > 127)
        return 0;
    if (c >= 'A' && c <= 'Z')
        b |= 0x1;
    if (c >= 'a' && c <= 'z')
        b |= 0x2;
    if (c >= '0' && c <= '9')
        b |= 0x4;
    if (c == ' ' || (c >= 9 && c <= 13))
        b |= 0x8;
    if (c > 32 && c < 127 && !isalnum(c))
        b |= 0x10;
    if (c < 32 || c == 127)
        b |= 0x20;
    if (c == ' ')
        b |= 0x40;
    if (isxdigit(c))
        b |= 0x80;
    return b;
}
static uint32_t crt_isctype(const uint32_t *a) { return ctype_bits((int32_t)a[0]) & a[1]; }

/* _findfirst(spec, &data), _findnext(handle, &data), _findclose(handle): the names in a folder that match a pattern ("art\*.pic"), compared without regard to case, in the order of the
 * names; the folder is the guest's (the installed one and the overlay together). struct _finddata_t: attrib, three times, size, name[260]. "." and ".." are listed where the pattern
 * takes them, as the file system of Windows does for every folder but the root. */
typedef struct FindEntry { char name[260]; int is_dir; } FindEntry;
typedef struct FindSearch { int used; FindEntry *entries; int n, next; char dir[260]; } FindSearch;
static FindSearch searches[16];

typedef struct FindCollect { FindEntry *e; int n, cap; char pattern[260]; } FindCollect;

static void find_lower(char *s) { for (; *s; s++) *s = (char)tolower((unsigned char)*s); }

static void find_add(FindCollect *c, const char *name, int is_dir)
{
    char lname[260], lpat[260];

    snprintf(lname, sizeof(lname), "%s", name);
    snprintf(lpat, sizeof(lpat), "%s", c->pattern);
    find_lower(lname);
    find_lower(lpat);
    if (!strcmp(lpat, "*.*"))
        strcpy(lpat, "*");                                      /* the DOS pattern for every name, one with no dot too */
    if (!port_glob(lpat, lname))
        return;
    if (c->n == c->cap) {
        c->cap = c->cap ? c->cap * 2 : 32;
        c->e = realloc(c->e, (size_t)c->cap * sizeof(*c->e));
    }
    snprintf(c->e[c->n].name, sizeof(c->e[c->n].name), "%s", name);
    c->e[c->n].is_dir = is_dir;
    c->n++;
}

static void find_cb(const char *name, int is_dir, void *ctx) { find_add(ctx, name, is_dir); }

static int find_cmp(const void *x, const void *y) { return strcasecmp(((const FindEntry *)x)->name, ((const FindEntry *)y)->name); }

static void find_fill(const FindSearch *s, const FindEntry *e, uint32_t out)
{
    char guest[600], host[1200];
    struct stat st;
    uint32_t size = 0, when = 0;

    snprintf(guest, sizeof(guest), "%s%s%s", s->dir, s->dir[0] ? "\\" : "", e->name);
    if (!e->is_dir && paths_host(guest, 0, host, sizeof(host)) && !stat(host, &st)) {
        size = (uint32_t)st.st_size;
        when = (uint32_t)st.st_mtime;
    }
    WR32(out, e->is_dir ? 0x10u : 0x20u);
    WR32(out + 4, when);
    WR32(out + 8, when);
    WR32(out + 12, when);
    WR32(out + 16, size);
    strncpy(P(out + 20), e->name, 259);
    P(out + 20)[259] = 0;
}

static void find_errno(uint32_t code) { WR32(cell(&errno_cell), code); }

/* Start a search: the slot of a new search with its first name still to be read (next 0), or -1 with `*err` the Windows error (2: no file matches, 4: too many searches). */
static int find_open(const char *spec_in, int *err)
{
    char spec[300], *sep, *q;
    FindCollect c = {0};
    int i, drive_root;

    snprintf(spec, sizeof(spec), "%s", spec_in);
    for (q = spec; *q; q++)
        if (*q == '/')
            *q = '\\';
    sep = strrchr(spec, '\\');
    for (i = 0; i < 16 && searches[i].used; i++)
        ;
    if (i == 16) {
        *err = 4;
        return -1;
    }
    memset(&searches[i], 0, sizeof(searches[i]));
    if (sep) {
        *sep = 0;
        snprintf(searches[i].dir, sizeof(searches[i].dir), "%s", spec);
        snprintf(c.pattern, sizeof(c.pattern), "%s", sep + 1);
    } else {
        snprintf(c.pattern, sizeof(c.pattern), "%s", spec);
    }
    drive_root = strlen(searches[i].dir) == 2 && searches[i].dir[1] == ':';
    paths_list(searches[i].dir[0] ? searches[i].dir : guest_cwd, find_cb, &c);
    if (!drive_root) {
        find_add(&c, ".", 1);
        find_add(&c, "..", 1);
    }
    if (c.n > 1)
        qsort(c.e, (size_t)c.n, sizeof(*c.e), find_cmp);
    if (!c.n) {
        free(c.e);
        *err = 2;
        return -1;
    }
    searches[i].used = 1;
    searches[i].entries = c.e;
    searches[i].n = c.n;
    searches[i].next = 0;
    return i;
}

static uint32_t crt_findfirst(const uint32_t *a)
{
    int err = 0, i = find_open(P(a[0]), &err);

    if (i < 0) {
        find_errno(err == 4 ? 24u : 2u);                        /* EMFILE, ENOENT */
        return 0xFFFFFFFFu;
    }
    find_fill(&searches[i], &searches[i].entries[0], a[1]);
    searches[i].next = 1;
    return (uint32_t)i;
}

static uint32_t crt_findnext(const uint32_t *a)
{
    FindSearch *s = a[0] < 16 && searches[a[0]].used ? &searches[a[0]] : NULL;

    if (!s || s->next >= s->n) {
        find_errno(2);
        return 0xFFFFFFFFu;
    }
    find_fill(s, &s->entries[s->next++], a[1]);
    return 0;
}

static uint32_t crt_findclose(const uint32_t *a)
{
    if (a[0] < 16 && searches[a[0]].used) {
        free(searches[a[0]].entries);
        searches[a[0]].used = 0;
        return 0;
    }
    return 0xFFFFFFFFu;
}

/* The same search for Windows itself: FindFirstFileA(pattern, &WIN32_FIND_DATAA) gives a handle (INVALID_HANDLE_VALUE, with the last error ERROR_FILE_NOT_FOUND, when no name matches),
 * FindNextFileA(handle, &data) the next name (FALSE and ERROR_NO_MORE_FILES at the end), FindClose(handle) ends the search. WIN32_FIND_DATAA: attributes, three FILETIMEs, size high and
 * low, two reserved dwords, cFileName[260], cAlternateFileName[14]; names come in order, "." and ".." where Windows lists them. */
#define FIND_HANDLE_BASE 0x7E900000u

static void win_find_fill(const FindSearch *s, const FindEntry *e, uint32_t out)
{
    char guest[600], host[1200];
    struct stat st;
    uint64_t when = 0;
    uint32_t size = 0;
    int k;

    snprintf(guest, sizeof(guest), "%s%s%s", s->dir, s->dir[0] ? "\\" : "", e->name);
    if (!e->is_dir && paths_host(guest, 0, host, sizeof(host)) && !stat(host, &st)) {
        size = (uint32_t)st.st_size;
        when = ((uint64_t)st.st_mtime + 11644473600ull) * 10000000ull;           /* FILETIME: 100 ns since 1601 */
    }
    guest_zero(out, 318);
    WR32(out, e->is_dir ? 0x10u : 0x20u);
    for (k = 0; k < 3; k++) {
        WR32(out + 4 + 8u * (uint32_t)k, (uint32_t)when);
        WR32(out + 8 + 8u * (uint32_t)k, (uint32_t)(when >> 32));
    }
    WR32(out + 32, size);                                                         /* (a file of 4 GB or more is not in a game's folder: the high dword stays 0) */
    strncpy(P(out + 44), e->name, 259);
    P(out + 44)[259] = 0;
}

static uint32_t win_find_first(const uint32_t *a)
{
    int err = 0, i = find_open(P(a[0]), &err);

    if (i < 0) {
        k32_set_last_error(err == 4 ? 4u : 2u);                 /* ERROR_TOO_MANY_OPEN_FILES, ERROR_FILE_NOT_FOUND */
        return 0xFFFFFFFFu;
    }
    win_find_fill(&searches[i], &searches[i].entries[0], a[1]);
    searches[i].next = 1;
    return FIND_HANDLE_BASE + (uint32_t)i;
}

static uint32_t win_find_next(const uint32_t *a)
{
    uint32_t i = a[0] - FIND_HANDLE_BASE;
    FindSearch *s = i < 16 && searches[i].used ? &searches[i] : NULL;

    if (!s) {
        k32_set_last_error(6);                                  /* ERROR_INVALID_HANDLE */
        return 0;
    }
    if (s->next >= s->n) {
        k32_set_last_error(18);                                 /* ERROR_NO_MORE_FILES */
        return 0;
    }
    win_find_fill(s, &s->entries[s->next++], a[1]);
    return 1;
}

static uint32_t win_find_close(const uint32_t *a)
{
    uint32_t i = a[0] - FIND_HANDLE_BASE;

    if (i < 16 && searches[i].used) {
        free(searches[i].entries);
        searches[i].used = 0;
        return 1;
    }
    k32_set_last_error(6);
    return 0;
}

/* _spawnl(mode, path, arg0, arg1, ..., NULL): start a program (process.h). _P_WAIT (0) returns its exit code, _P_NOWAIT (1, 3: the id is the handle) and _P_DETACH (4) return a handle at once,
 * _P_OVERLAY (2) is a start, a wait and the end of this program with the code. -1 and errno ENOENT for a program that cannot be started. */
static uint32_t crt_spawnl(const uint32_t *a)
{
    char line[600] = "";
    uint32_t mode = a[0], k;
    long id;
    int err, code;

    for (k = 2; k < 14 && a[k]; k++) {
        if (line[0])
            strncat(line, " ", sizeof(line) - strlen(line) - 1);
        strncat(line, P(a[k]), sizeof(line) - strlen(line) - 1);
    }
    err = proc_start(P(a[1]), line, &id);
    if (err) {
        WR32(cell(&errno_cell), err == 2 ? 2u : 12u);              /* ENOENT, ENOMEM */
        return 0xFFFFFFFFu;
    }
    if (mode == 0 || mode == 2) {
        code = proc_wait(id);
        if (mode == 2) {
            fflush(NULL);
            exit(code);
        }
        return (uint32_t)code;
    }
    return proc_handle_new(id);
}

const WinApi CRT_APIS[] = {
    {"msvcrtd.dll", "_spawnl", crt_spawnl},
    {"msvcrtd.dll", "qsort", crt_qsort}, {"msvcrtd.dll", "strcoll", crt_strcoll}, {"msvcrtd.dll", "_isctype", crt_isctype},
    {"kernel32.dll", "FindFirstFileA", win_find_first}, {"kernel32.dll", "FindNextFileA", win_find_next}, {"kernel32.dll", "FindClose", win_find_close},
    {"msvcrtd.dll", "_findfirst", crt_findfirst}, {"msvcrtd.dll", "_findnext", crt_findnext}, {"msvcrtd.dll", "_findclose", crt_findclose},
    {"msvcrtd.dll", "__set_app_type", zero}, {"msvcrtd.dll", "_controlfp", controlfp}, {"msvcrtd.dll", "__setusermatherr", zero},
    {"msvcrtd.dll", "_XcptFilter", zero}, {"msvcrtd.dll", "_except_handler3", one}, {"msvcrtd.dll", "__p__fmode", p_fmode},
    {"msvcrtd.dll", "__p__commode", p_commode}, {"msvcrtd.dll", "__p___argv", p_argv}, {"msvcrtd.dll", "__p__acmdln", p_acmdln},
    {"msvcrtd.dll", "__p___mb_cur_max", p_mb_cur_max}, {"msvcrtd.dll", "__p__pctype", p_pctype}, {"msvcrtd.dll", "_errno", crt_errno},
    {"msvcrtd.dll", "__getmainargs", getmainargs}, {"msvcrtd.dll", "_initterm", initterm}, {"msvcrtd.dll", "exit", crt_exit},
    {"msvcrtd.dll", "_exit", crt_exit}, {"msvcrtd.dll", "_onexit", crt_onexit}, {"msvcrtd.dll", "__dllonexit", crt_onexit},
    {"msvcrtd.dll", "_assert", crt_assert}, {"msvcrtd.dll", "malloc", crt_malloc}, {"msvcrtd.dll", "_malloc_dbg", crt_malloc},
    {"msvcrtd.dll", "calloc", crt_calloc}, {"msvcrtd.dll", "free", crt_free}, {"msvcrtd.dll", "_free_dbg", crt_free_dbg},
    {"msvcrtd.dll", "realloc", crt_realloc}, {"msvcrtd.dll", "??2@YAPAXI@Z", crt_malloc}, {"msvcrtd.dll", "??3@YAXPAX@Z", crt_free},
    {"msvcrtd.dll", "_msize", crt_msize}, {"msvcrtd.dll", "_expand", crt_expand}, {"msvcrtd.dll", "memcpy", crt_memcpy},
    {"msvcrtd.dll", "memmove", crt_memcpy}, {"msvcrtd.dll", "memset", crt_memset}, {"msvcrtd.dll", "memcmp", crt_memcmp},
    {"msvcrtd.dll", "memchr", crt_memchr}, {"msvcrtd.dll", "strlen", crt_strlen}, {"msvcrtd.dll", "strcpy", crt_strcpy},
    {"msvcrtd.dll", "strcat", crt_strcat}, {"msvcrtd.dll", "strncpy", crt_strncpy}, {"msvcrtd.dll", "strncat", crt_strncat},
    {"msvcrtd.dll", "strcmp", crt_strcmp}, {"msvcrtd.dll", "strncmp", crt_strncmp}, {"msvcrtd.dll", "_stricmp", crt_stricmp},
    {"msvcrtd.dll", "_strcmpi", crt_stricmp}, {"msvcrtd.dll", "_strnicmp", crt_strnicmp}, {"msvcrtd.dll", "strchr", crt_strchr},
    {"msvcrtd.dll", "strrchr", crt_strrchr}, {"msvcrtd.dll", "strspn", crt_strspn}, {"msvcrtd.dll", "strcspn", crt_strcspn},
    {"msvcrtd.dll", "_strlwr", crt_strlwr}, {"msvcrtd.dll", "tolower", crt_tolower}, {"msvcrtd.dll", "abs", crt_abs},
    {"msvcrtd.dll", "atoi", crt_atoi}, {"msvcrtd.dll", "_itoa", crt_itoa}, {"msvcrtd.dll", "rand", crt_rand},
    {"msvcrtd.dll", "srand", crt_srand}, {"msvcrtd.dll", "clock", crt_clock}, {"msvcrtd.dll", "time", crt_time},
    {0, 0, 0},
};

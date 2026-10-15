/* crt.c - the C runtime (MSVCRTD.DLL) in C: start-up, memory, strings, numbers. The behaviour is the Python layer's (winemu/crt.py). */
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "port.h"
#include "sched.h"

#define P(a) ((char *)(G + (a)))
#define U8(a) (*(uint8_t *)(G + (a)))

static uint32_t errno_cell, fmode_cell, commode_cell, argv_cell, argc_cell, environ_cell, acmdln_cell, mb_cur_max_cell, pctype_cell;
static uint32_t rand_seed = 1;
static int crt_ready;

static void crt_init(void)
{
    uint32_t arg0, arr;

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
    arg0 = heap_alloc(48);
    strcpy(P(arg0), "C:\\Magic\\Program\\MAGIC.EXE");
    arr = heap_alloc(8);
    WR32(arr, arg0);
    WR32(argv_cell, arr);
    WR32(argc_cell, 1);
    WR32(environ_cell, heap_alloc(8));
    WR32(acmdln_cell, arg0);
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
    WR32(a[0], 1);
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
    uint32_t p = heap_alloc(a[0] * a[1]);

    if (p)
        guest_zero(p, a[0] * a[1]);
    return p;
}
static uint32_t crt_free(const uint32_t *a) { heap_free(a[0]); return 0; }
static uint32_t crt_free_dbg(const uint32_t *a) { heap_free(a[0]); return 0; }
static uint32_t crt_realloc(const uint32_t *a)
{
    uint32_t q = heap_alloc(a[1]), old = a[0] ? heap_size(a[0]) : 0;

    if (a[0]) {
        memcpy(P(q), P(a[0]), old < a[1] ? old : a[1]);
        heap_free(a[0]);
    }
    return q;
}
static uint32_t crt_msize(const uint32_t *a) { return heap_size(a[0]); }
static uint32_t crt_expand(const uint32_t *a) { return a[1] <= heap_size(a[0]) ? a[0] : 0; }
static uint32_t crt_memcpy(const uint32_t *a) { if (a[2]) memmove(P(a[0]), P(a[1]), a[2]); return a[0]; }
static uint32_t crt_memset(const uint32_t *a) { if (a[2]) memset(P(a[0]), (int)(a[1] & 0xff), a[2]); return a[0]; }
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
static uint32_t crt_rand(const uint32_t *a)
{
    (void)a;
    rand_seed = rand_seed * 214013u + 2531011u;
    return (rand_seed >> 16) & 0x7fffu;
}
static uint32_t crt_srand(const uint32_t *a) { rand_seed = a[0]; return 0; }
static uint32_t crt_clock(const uint32_t *a)
{
    (void)a;
    return (uint32_t)(port_now() * 1000.0);        /* milliseconds since the program started, by the wall clock (the host's clock() counts CPU time) */
}
static uint32_t crt_time(const uint32_t *a)
{
    uint32_t t = (uint32_t)time(NULL);

    if (a[0])
        WR32(a[0], t);
    return t;
}

const WinApi CRT_APIS[] = {
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

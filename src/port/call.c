/* call.c - how lifted code reaches other functions: lifted ones directly, imports through the Win32 layer. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#if defined(__GLIBC__) || defined(__APPLE__)
#include <execinfo.h>
#define HAVE_BACKTRACE 1
#endif

#include "port.h"
#include "sched.h"

static void who_note(const char *name, uint32_t ret);
static int who_on;
static uint32_t trace_fn_addr;

/* What lifted code shares with the runtime, in one block (lift_rt.h): the game module is given a pointer to it. The part per guest thread is
 * swapped by the scheduler (sched.c). */
LiftState lift_state;
LiftThreadState lift_thread_initial(void)
{
    LiftThreadState t;

    memset(&t, 0, sizeof(t));
    t.ret_edx = 0xcdcdcdcdu;
    t.x87_cw = 0x27f;
    return t;
}
int port_trace_calls;          /* "calls on" in PORT_CONTROL: every call from one lifted function to another is printed with its caller (a few seconds of it show the engine's flow) */
int port_trace_imports;       /* "trace on" in PORT_CONTROL: every import call is printed with its first four arguments and its result */
__thread uint32_t port_sp;      /* the guest's stack pointer at the import call being served (the address of its return address) */

typedef struct { uint32_t entry; uint32_t (*fn)(uint32_t); uint32_t cleanup; } Target;
static Target *table;       /* open addressing, keyed by entry */
static uint32_t table_mask;

static uint32_t hash(uint32_t a) { return (a * 2654435761u) >> 7; }

void port_index_functions(void)
{
    int i;
    uint32_t cap = 1;

    int m, total = lift_game->nlifted;

    for (m = 0; lift_game->modules[m]; m++)
        total += lift_game->modules[m]->nlifted;
    while (cap < (uint32_t)total * 2)
        cap <<= 1;
    table = calloc(cap, sizeof(*table));
    table_mask = cap - 1;
    for (i = 0; i < lift_game->nlifted; i++) {
        uint32_t h = hash(lift_game->lifted[i].entry) & table_mask;

        while (table[h].entry)
            h = (h + 1) & table_mask;
        table[h].entry = lift_game->lifted[i].entry;
        table[h].fn = lift_game->lifted[i].fn;
    }
    for (i = 0; i < lift_game->nfunctions; i++) {
        uint32_t h = hash(lift_game->functions[i].addr) & table_mask;

        while (table[h].entry && table[h].entry != lift_game->functions[i].addr)
            h = (h + 1) & table_mask;
        if (table[h].entry)
            table[h].cleanup = lift_game->functions[i].cleanup;
    }
    for (m = 0; lift_game->modules[m]; m++) {          /* the DLLs' functions: at their own bases, so the addresses never meet the program's */
        const LiftModule *mod = lift_game->modules[m];

        for (i = 0; i < mod->nlifted; i++) {
            uint32_t h = hash(mod->lifted[i].entry) & table_mask;

            while (table[h].entry)
                h = (h + 1) & table_mask;
            table[h].entry = mod->lifted[i].entry;
            table[h].fn = mod->lifted[i].fn;
            table[h].cleanup = mod->functions[i].addr == mod->lifted[i].entry ? mod->functions[i].cleanup : 0;
        }
    }
}

static const Target *find(uint32_t entry)
{
    uint32_t h = hash(entry) & table_mask;

    while (table[h].entry) {
        if (table[h].entry == entry)
            return &table[h];
        h = (h + 1) & table_mask;
    }
    return NULL;
}

/* Functions the host provides at guest addresses (callbacks the Win32 layer hands out, replacement libraries, tests): found before the lifted ones. */
typedef struct HostFn { uint32_t addr; HostGuestFn fn; } HostFn;
static HostFn host_fns[256];
static int nhost_fns;

uint32_t port_host_function(HostGuestFn fn)
{
    uint32_t addr = 0x70100000u + 16u * (uint32_t)nhost_fns;

    if (nhost_fns == 256)
        port_fatal("too many host functions");
    host_fns[nhost_fns++] = (HostFn){addr, fn};
    return addr;
}

/* Replacements for guest code that cannot be lifted (lzw.c): found before anything else. */
typedef struct Override { uint32_t addr; HostGuestFn fn; int nargs; uint32_t cleanup; } Override;
static Override overrides[24];
static int noverrides;

/* A hook that runs before a lifted function (which then runs as usual): the host's place to wait or to look, without taking the function over. */
static struct { uint32_t addr; HostGuestFn fn; } prehooks[8];
static int nprehooks;

void port_prehook(uint32_t addr, HostGuestFn fn)
{
    if (nprehooks == 8)
        port_fatal("too many pre-call hooks");
    prehooks[nprehooks].addr = addr;
    prehooks[nprehooks++].fn = fn;
}

void port_override(uint32_t addr, HostGuestFn fn, int nargs, uint32_t cleanup)
{
    if (noverrides == 24)
        port_fatal("too many overrides");
    overrides[noverrides++] = (Override){addr, fn, nargs, cleanup};
}

void port_hooks_reset(void) { nprehooks = noverrides = 0; lzw_reset(); }       /* the tests, between one profile and the next */

/* What the hook installers (pace.c, screens.c, yesno.c, textfocus.c, lzw.c) put in: the tests check that a build's profile gives exactly its addresses, and an unknown build none. */
int port_hook_count(void) { return nprehooks + noverrides; }

int port_hook_at(int i, uint32_t *addr, int *is_override)
{
    if (i < 0 || i >= nprehooks + noverrides)
        return 0;
    *is_override = i >= nprehooks;
    *addr = i < nprehooks ? prehooks[i].addr : overrides[i - nprehooks].addr;
    return 1;
}

void lift_bad_jump(uint32_t from)
{
    port_fatal("a jump table was indexed out of range at 0x%08x", from);
}

uint32_t lift_call(uint32_t target, uint32_t argp, uint32_t *cleanup)
{
    const Target *t;
    Import *im;

    lift_ret_edx = 0xcdcdcdcdu;        /* a lifted callee's `ret` overwrites this; a host function leaves the poison value */
    {
        int h;

        for (h = 0; h < nprehooks; h++)
            if (prehooks[h].addr == target) {
                uint32_t args[4], saved = port_sp;
                int i;

                for (i = 0; i < 4; i++)
                    args[i] = RD32(argp + 4u * (uint32_t)i);
                port_sp = argp - 4u;
                prehooks[h].fn(args);
                port_sp = saved;
            }
    }

    if (target >= 0x70100000u && target < 0x70100000u + 16u * (uint32_t)nhost_fns) {
        uint32_t args[8];
        int i;

        for (i = 0; i < 8; i++)
            args[i] = RD32(argp + 4u * (uint32_t)i);
        *cleanup = 0;
        return host_fns[(target - 0x70100000u) / 16].fn(args);
    }
    {
        int k;

        for (k = 0; k < noverrides; k++)
            if (overrides[k].addr == target) {
                uint32_t args[8], saved = port_sp, r;
                int i;

                for (i = 0; i < 8; i++)
                    args[i] = RD32(argp + 4u * (uint32_t)i);
                *cleanup = overrides[k].cleanup;
                port_sp = argp - 4u;
                r = overrides[k].fn(args);
                port_sp = saved;
                return r;
            }
    }
    t = find(target);

    if (t) {
        if (trace_fn_addr && target == trace_fn_addr) {      /* PORT_TRACE_FN=0xADDR: each call's arguments, and the text they point to */
            int k;

            fprintf(stderr, "    [call] 0x%08x from 0x%08x (t=%.3f):", target, RD32(argp - 4u), port_now());
            for (k = 0; k < 4; k++) {
                uint32_t v = RD32(argp + 4u * (uint32_t)k);

                fprintf(stderr, " 0x%x", v);
                if (v > 0x400000u && v < 0x7f000000u && RD8(v) >= 32 && RD8(v) < 127)
                    fprintf(stderr, " \"%.60s\"", (const char *)(G + v));
            }
            fputc('\n', stderr);
        }
        if (port_trace_calls)
            fprintf(stderr, "    [fn] 0x%08x from 0x%08x\n", target, RD32(argp - 4u));
        if (who_on) {
            char nm[16];

            snprintf(nm, sizeof(nm), "0x%08x", target);
            who_note(nm, RD32(argp - 4u));
        }
        *cleanup = t->cleanup;
        lift_in = lift_out;
        if (trace_fn_addr && target == trace_fn_addr) {
            uint32_t r = t->fn(argp - 4u);

            fprintf(stderr, "    [call] 0x%08x returned 0x%x\n", target, r);
            return r;
        }
        return t->fn(argp - 4u);
    }
    im = import_by_slot_or_stub(target);
    if (im && im->forward) {                       /* `call [slot]` of an import that is a lifted library's export: that function */
        im->calls++;
        return lift_call(im->forward, argp, cleanup);
    }
    if (im) {
        uint32_t args[16];
        int i, n = im->nargs < 16 ? im->nargs : 16;

        uint32_t saved_sp = port_sp, r;

        im->calls++;
        if (who_on) who_note(im->name, RD32(argp - 4u));
        sched_note_call(im->name, RD32(argp - 4u));
        *cleanup = im->cleanup;
        if (!im->fn) {
            if (!getenv("PORT_STUB"))
                port_fatal("%s!%s is not implemented (called from the guest's 0x%08x)", im->dll, im->name, RD32(argp - 4u));
            if (im->calls == 1)
                port_log("stub %s!%s (called from 0x%08x)", im->dll, im->name, RD32(argp - 4u));
            return 0;
        }
        for (i = 0; i < n; i++)
            args[i] = RD32(argp + 4u * (uint32_t)i);
        port_sp = argp - 4u;            /* where a function that calls back into the guest builds its frame below */
        r = im->fn(args);
        port_sp = saved_sp;
        if (port_trace_imports)
            fprintf(stderr, "    [import] %s(0x%x, 0x%x, 0x%x, 0x%x) = 0x%x  from 0x%08x\n", im->name, n > 0 ? args[0] : 0, n > 1 ? args[1] : 0, n > 2 ? args[2] : 0,
                    n > 3 ? args[3] : 0, r, RD32(argp - 4u));
        return r;
    }
    port_fatal("a call to 0x%08x, which is neither a lifted function nor an import (called from 0x%08x)", target, RD32(argp - 4u));
}

#ifdef LIFT_TRACE
/* PORT_COV=file: at exit, the address of every lifted instruction that ran, in the order it first did. */
#define COV_BASE 0x400000u
#define COV_SIZE 0x120000u
static uint8_t cov_seen[COV_SIZE];
static uint32_t cov_order[COV_SIZE];
static uint32_t cov_n;

static void cov_report(void)
{
    const char *path = getenv("PORT_COV");
    FILE *f = path ? fopen(path, "w") : NULL;
    uint32_t i;

    if (!f)
        return;
    for (i = 0; i < cov_n; i++)
        fprintf(f, "%08x\n", cov_order[i]);
    fclose(f);
}

static uint32_t watch_lo = 1, watch_hi, watch_arm_pc, last_pc;

void lift_w(uint32_t a, uint32_t n, uint32_t v)
{
    static int count, parsed;

    if (!parsed) {
        const char *w = getenv("PORT_WATCH");
        unsigned lo, hi;

        parsed = 1;
        if (w && !strncmp(w, "pc:", 3))
            watch_arm_pc = (uint32_t)strtoul(w + 3, NULL, 16);
        else if (w && sscanf(w, "%x-%x", &lo, &hi) == 2) {
            watch_lo = lo;
            watch_hi = hi;
        }
    }
    if (watch_arm_pc && last_pc == watch_arm_pc) {
        watch_lo = a;
        watch_hi = a + n;
        watch_arm_pc = 0;
        fprintf(stderr, "    [watch] watching 0x%x..0x%x\n", watch_lo, watch_hi);
    }
    if (a + n > watch_lo && a < watch_hi && count++ < 60)
    {
        fprintf(stderr, "    [watch] write of %u bytes at 0x%x = 0x%x by the instruction at 0x%08x\n", n, a, v, last_pc);
#ifdef HAVE_BACKTRACE
        if (count == 3 || count == 4) {         /* who is on the C stack (where the C library has backtrace: not on Windows) */
            void *frames[24];
            int nf = backtrace(frames, 24);

            backtrace_symbols_fd(frames, nf, 2);
        }
#endif
    }
}

void lift_bad_ret(uint32_t fn, uint32_t entry_esp, uint32_t esp)
{
    static int n;

    if (n++ < 40)
        fprintf(stderr, "    [ret] function 0x%08x returns with esp 0x%x, entered at 0x%x (%+d)\n", fn, esp, entry_esp, (int)(esp - entry_esp));
}

void lift_trace(uint32_t a)
{
    last_pc = a;
    if (a - COV_BASE < COV_SIZE && !cov_seen[a - COV_BASE]) {
        if (!cov_n)
            atexit(cov_report);
        cov_seen[a - COV_BASE] = 1;
        cov_order[cov_n++] = a;
    }
}
#endif

/* PORT_WHO=GetDC,LineTo: at exit, which guest addresses called those imports and how often (a way to find the code that draws or measures). */
#define WHO_MAX 4096
static struct { char name[40]; uint32_t ret; unsigned long long n; } who[WHO_MAX];
static int nwho;
static const char *who_spec;

void who_report(void)
{
    int i;

    for (i = 0; i < nwho; i++)
        fprintf(stderr, "    [who] %s x%llu from 0x%08x\n", who[i].name, who[i].n, who[i].ret);
}

static void who_note(const char *name, uint32_t ret)
{
    int i;
    size_t len = strlen(name);
    const char *p;

    for (p = who_spec; (p = strstr(p, name)) != NULL; p += len)
        if ((p == who_spec || p[-1] == ',') && (p[len] == ',' || !p[len]))
            break;
    if (!p)
        return;
    if (getenv("PORT_WHO_LIVE"))
        fprintf(stderr, "    [who] %s from 0x%08x\n", name, ret);
    for (i = 0; i < nwho; i++)
        if (!strcmp(who[i].name, name) && who[i].ret == ret) {
            who[i].n++;
            return;
        }
    if (nwho < WHO_MAX) {
        snprintf(who[nwho].name, sizeof(who[nwho].name), "%s", name);
        who[nwho].ret = ret;
        who[nwho++].n = 1;
    }
}

void who_init(void)
{
    if (getenv("PORT_TRACE_FN"))
        trace_fn_addr = (uint32_t)strtoul(getenv("PORT_TRACE_FN"), NULL, 16);
    who_spec = getenv("PORT_WHO");
    nwho = 0;
    if (who_spec) {
        who_on = 1;
        atexit(who_report);
    }
}

/* Call a guest function from the Win32 layer (a callback: _initterm's constructors, a window procedure) with `nargs` stack arguments. */
uint32_t guest_call(uint32_t target, int nargs, const uint32_t *args)
{
    uint32_t sp = port_sp - 64u, saved = port_sp, cleanup = 0, r;
    int i;

    for (i = nargs - 1; i >= 0; i--) {
        sp -= 4;
        WR32(sp, args[i]);
    }
    sp -= 4;
    WR32(sp, 0);                       /* the return address: the lifted code does not look at it */
    memset(&lift_out, 0, sizeof(lift_out));
    port_sp = sp;
    r = lift_call(target, sp + 4u, &cleanup);
    port_sp = saved;
    return r;
}

/* The first call of a guest thread: its function with its arguments on a stack of its own. */
uint32_t guest_call_on(uint32_t stack_top, uint32_t target, int nargs, const uint32_t *args)
{
    uint32_t sp = stack_top, cleanup = 0;
    int i;

    for (i = nargs - 1; i >= 0; i--) {
        sp -= 4;
        WR32(sp, args[i]);
    }
    sp -= 4;
    WR32(sp, 0);
    memset(&lift_out, 0, sizeof(lift_out));
    port_sp = sp;
    return lift_call(target, sp + 4u, &cleanup);
}

/*
 * native_host.c - see native_host.h.
 */
#include "native_host.h"

#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "engine.h"
#ifdef HOST_LIFTED
#include "lift_bridge.h"
#endif

static Mem host_mem;
static Vm host_vm;
static HostCall host_call;
static uint32_t host_sp; /* where the guest's stack is, when no lifted code is tracking it */

#define MAX_REGIONS 32
static struct {
    uint32_t base, size;
    uint8_t *ptr;
} regions[MAX_REGIONS];
static int nregions;
static HostMemRead fallback_read;
static HostMemWrite fallback_write;

void host_add_region(uint32_t base, uint32_t size, void *ptr)
{
    if (nregions < MAX_REGIONS) {
        regions[nregions].base = base;
        regions[nregions].size = size;
        regions[nregions].ptr = ptr;
        nregions++;
    }
}

static uint8_t *locate(uint32_t addr, int size)
{
    int i;
    for (i = 0; i < nregions; i++)
        if (addr >= regions[i].base && (uint64_t)addr + (uint64_t)size <= (uint64_t)regions[i].base + regions[i].size)
            return regions[i].ptr + (addr - regions[i].base);
    return NULL;
}

/* host_native_try runs a call without a thread: a call out stops it (longjmp) and what it wrote is put back. */
static int trying;
static jmp_buf try_jb;
typedef struct {
    uint32_t addr;
    uint32_t old;
    int size;
    uint8_t *blob; /* the old bytes of a bulk write (size > 4), else NULL */
} Undo;
static Undo *undo;
static size_t nundo, capundo;

static Undo *push_undo(void)
{
    if (nundo == capundo) {
        capundo = capundo ? capundo * 2 : 4096;
        undo = realloc(undo, capundo * sizeof(*undo));
        if (!undo)
            abort();
    }
    undo[nundo].blob = NULL;
    return &undo[nundo++];
}

/* The counters a stopped call must give back (host_counters): it will be run again, and what the first attempt did is not work
 * the original did. */
typedef struct {
    uint64_t entries[FN_COUNT];
    uint64_t extra;
    uint64_t lifted;
} Counters;
static Counters counters_saved;

static void snap_counters(Counters *c)
{
    memcpy(c->entries, native_entries, sizeof(native_entries));
    c->extra = native_cost_extra;
#ifdef HOST_LIFTED
    {
        extern uint64_t lift_icount;
        c->lifted = lift_icount;
    }
#endif
}

static void put_counters(const Counters *c)
{
    memcpy(native_entries, c->entries, sizeof(native_entries));
    native_cost_extra = c->extra;
#ifdef HOST_LIFTED
    {
        extern uint64_t lift_icount;
        lift_icount = c->lifted;
    }
#endif
}

static void save_counters(void)
{
    snap_counters(&counters_saved);
}

static void restore_counters(void)
{
    put_counters(&counters_saved);
}

/* Shadow mode (host_set_shadow): the writes a call makes, as ranges, so that two runs of the same call can be compared. */
typedef struct {
    uint32_t addr, size;
} Range;
static Range *wlog;
static size_t nwlog, capwlog;
static int wlog_on;

static void log_write(uint32_t addr, uint32_t size)
{
    if (nwlog == capwlog) {
        capwlog = capwlog ? capwlog * 2 : 1024;
        wlog = realloc(wlog, capwlog * sizeof(*wlog));
        if (!wlog)
            abort();
    }
    wlog[nwlog].addr = addr;
    wlog[nwlog].size = size;
    nwlog++;
}

/* A call finished: what it wrote stays. */
static void drop_undo(void)
{
    while (nundo > 0)
        free(undo[--nundo].blob);
}

static uint32_t direct_read(void *ctx, uint32_t addr, int size)
{
    uint8_t *p = locate(addr, size);
    uint32_t v = 0;
    if (p) {
        memcpy(&v, p, (size_t)size);   /* little-endian host, like the guest */
        return v;
    }
    return fallback_read ? fallback_read(ctx, addr, size) : 0;
}

static void direct_write(void *ctx, uint32_t addr, int size, uint32_t value)
{
    uint8_t *p = locate(addr, size);
    if (p) {
        if (wlog_on)
            log_write(addr, (uint32_t)size);
        if (trying) {
            Undo *u = push_undo();
            u->addr = addr;
            u->size = size;
            u->old = 0;
            memcpy(&u->old, p, (size_t)size);
        }
        memcpy(p, &value, (size_t)size);
    } else if (fallback_write)
        fallback_write(ctx, addr, size, value);
}

/* A copy between two stretches of the guest's memory the host can reach: one memmove, with one undo entry. */
static int direct_copy(void *ctx, uint32_t dst, uint32_t src, uint32_t len)
{
    uint8_t *pd = locate(dst, (int)len), *ps = locate(src, (int)len);
    (void)ctx;
    if (!pd || !ps || len > 0x7fffffffu)
        return 0;
    if (wlog_on)
        log_write(dst, len);
    if (trying) {
        Undo *u = push_undo();
        u->addr = dst;
        u->size = (int)len;
        u->blob = malloc(len);
        if (!u->blob)
            abort();
        memcpy(u->blob, pd, len);
    }
    memmove(pd, ps, len);
    return 1;
}

static uint32_t current_sp(void)
{
#ifdef HOST_LIFTED
    return lift_get_stack();
#else
    return host_sp;
#endif
}

static uint32_t call_out(void *ctx, Callee callee, uint32_t addr, int nargs, const uint32_t *args)
{
    (void)ctx;
#ifdef HOST_LIFTED
    /* lift_inplace says the call comes from lifted code, which has built the frame; it is for this call only. Read it and clear
     * it before anything else: the guest function this call runs can run hosted code again (a native function, from the guest's own
     * call), and that code's call out must not find the flag still set. */
    int inplace = lift_inplace;
    lift_inplace = 0;
#endif
    if (trying)
        longjmp(try_jb, 1);
    (void)callee; /* the address says which function; the host does not need the enum */
#ifdef HOST_LIFTED
    {
        uint32_t regs[7];
        lift_call_regs(regs);
        return host_call(addr, nargs, args, current_sp(), inplace, inplace ? regs : NULL);
    }
#else
    return host_call(addr, nargs, args, current_sp(), 0, NULL);
#endif
}

int host_init(const char *program, HostMemRead rd, HostMemWrite wr, HostCall call)
{
    const Layout *layout = layout_for(program);

    if (!layout)
        return -1;
    mem_init(&host_mem);
    fallback_read = rd;
    fallback_write = wr;
    host_mem.ext_read = direct_read;
    host_mem.ext_write = direct_write;
    host_mem.ext_copy = direct_copy;
    host_vm.mem = &host_mem;
    host_vm.L = layout;
    host_vm.call = call_out;
    host_call = call;
#ifdef HOST_LIFTED
    lift_attach(&host_vm, LIFT_CALLS_NATIVE);
#endif
    return 0;
}

/* Put back what a stopped call wrote, newest first. */
static void roll_back(void)
{
    while (nundo > 0) {
        Undo *u = &undo[--nundo];
        uint8_t *p = locate(u->addr, u->size);
        if (p)
            memcpy(p, u->blob ? u->blob : (uint8_t *)&u->old, (size_t)u->size);
        free(u->blob);
    }
}

/* Work done since the last mark, in the original's instructions: lifted code's own, what the natives add as they run, and the calibrated
 * average for each native function entered (host_set_native_costs). Hosted code that polls the clock sees time pass by this much. */
static double native_costs[FN_COUNT];
static uint64_t mark_entries[FN_COUNT], mark_total;

void host_set_native_costs(const double *costs)
{
    memcpy(native_costs, costs, sizeof(native_costs));
}

static uint64_t total_instructions(void)
{
#ifdef HOST_LIFTED
    extern uint64_t lift_icount;
    return lift_icount + native_cost_extra;
#else
    return native_cost_extra;
#endif
}

void host_mark_charge(void)
{
    memcpy(mark_entries, native_entries, sizeof(native_entries));
    mark_total = total_instructions();
}

static uint64_t pending_charge(void)
{
    double s = 0.0;
    int f;

    for (f = 0; f < FN_COUNT; f++)
        s += (double)(native_entries[f] - mark_entries[f]) * native_costs[f];
    return total_instructions() - mark_total + (uint64_t)s;
}

void host_counters(uint64_t *entries, uint64_t *lifted_instructions)
{
    int i;
    for (i = 0; i < FN_COUNT; i++)
        entries[i] = native_entries[i];
#ifdef HOST_LIFTED
    {
        extern uint64_t lift_icount;
        *lifted_instructions = lift_icount + native_cost_extra;
    }
#else
    *lifted_instructions = native_cost_extra;
#endif
}

void host_set_enabled(uint32_t entry, int on, int lifted)
{
    int f;
    if (!lifted) {
        for (f = 0; f < FN_COUNT; f++)
            if (host_vm.L->entry[f] == entry)
                native_disabled[f] = !on;
        return;
    }
#ifdef HOST_LIFTED
    lift_set_enabled(entry, on);
#endif
}

int host_native_count(void)
{
    return FN_COUNT;
}

int host_native_find(const char *name)
{
    const NativeInfo *n = native_find(name);
    return n ? (int)n->id : -1;
}

/* ---- shadow mode ---------------------------------------------------------------------------------------------------------
 * A hand-written native function that has a lifted twin (the same function's machine code translated by tools/lift) is run
 * both ways on every call of the real game: the twin first, on the guest's own stack and registers, then the native function,
 * each under the undo log. Their return values and the bytes they wrote outside the stack frame are compared, the difference
 * is reported, and the twin's result is what the guest keeps: so a run in shadow mode is the original's own (the twin counts the
 * instructions the original ran, and leaves what it left on the stack), and every call the game makes is also a test of the
 * hand-written code, on far more states than recorded vectors reach. */
static int shadow_on;
static uint64_t shadow_compared, shadow_mismatches, shadow_unchecked;

void host_set_shadow(int on)
{
    shadow_on = on != 0;
    native_exact_only = on == 1;   /* 2: check only, lifted code may call any native function, the run is not the original's to the instruction */
}

void host_shadow_stats(uint64_t *compared, uint64_t *mismatches, uint64_t *unchecked)
{
    *compared = shadow_compared;
    *mismatches = shadow_mismatches;
    *unchecked = shadow_unchecked;
}

#ifdef HOST_LIFTED
typedef struct {
    Range *r;
    size_t n;
    uint8_t *bytes;
} Written;

static Written written_a, written_b;

static void capture(Written *w)
{
    size_t i, total = 0, at = 0;

    w->n = nwlog;
    w->r = malloc((nwlog ? nwlog : 1) * sizeof(Range));
    for (i = 0; i < nwlog; i++)
        total += wlog[i].size;
    w->bytes = malloc(total ? total : 1);
    if (!w->r || !w->bytes)
        abort();
    for (i = 0; i < nwlog; i++) {
        uint8_t *p = locate(wlog[i].addr, (int)wlog[i].size);
        w->r[i] = wlog[i];
        if (p)
            memcpy(w->bytes + at, p, wlog[i].size);
        else
            memset(w->bytes + at, 0, wlog[i].size);
        at += wlog[i].size;
    }
}

static void release(Written *w)
{
    free(w->r);
    free(w->bytes);
    w->r = NULL;
    w->bytes = NULL;
    w->n = 0;
}

/* The first byte at or above `floor` (the frame of the call is below it) where memory differs from what `w` captured. */
static int first_difference(const Written *w, uint32_t floor, uint32_t *where)
{
    size_t i, at = 0;
    for (i = 0; i < w->n; i++) {
        uint8_t *p = locate(w->r[i].addr, (int)w->r[i].size);
        uint32_t k;
        for (k = 0; p && k < w->r[i].size; k++)
            if (w->r[i].addr + k >= floor && p[k] != w->bytes[at + k]) {
                *where = w->r[i].addr + k;
                return 1;
            }
        at += w->r[i].size;
    }
    return 0;
}

static void apply(const Written *w)
{
    size_t i, at = 0;
    for (i = 0; i < w->n; i++) {
        uint8_t *p = locate(w->r[i].addr, (int)w->r[i].size);
        if (p)
            memcpy(p, w->bytes + at, w->r[i].size);
        at += w->r[i].size;
    }
}

static Counters counters_lifted;

static int shadow_try(int id, const uint32_t *args, uint32_t sp, const uint32_t *regs, uint32_t *ret)
{
    uint32_t entry = host_vm.L->entry[id], saved_sp = lift_get_stack(), where = 0, native_ret = 0;
    static uint32_t twin_ret;
    int bits = NATIVE_FUNCTIONS[id].ret_bits, differs = 0;

    lift_set_stack(sp);
    host_sp = sp;
    save_counters();
    drop_undo();
    trying = 1;
    nwlog = 0;
    wlog_on = 1;
    if (setjmp(try_jb)) {   /* the twin needs the guest: not shadowed, the caller runs it on a thread */
        trying = 0;
        wlog_on = 0;
        roll_back();
        restore_counters();
        lift_set_stack(saved_sp);
        shadow_unchecked++;
        return 1;
    }
    lift_run_at(&host_vm, entry, sp, regs, &twin_ret);
    trying = 0;
    wlog_on = 0;
    capture(&written_a);
    snap_counters(&counters_lifted);
    roll_back();                 /* back to the state the call found */

    trying = 1;
    nwlog = 0;
    wlog_on = 1;
    if (setjmp(try_jb)) {   /* the native function needs the guest: nothing to compare */
        trying = 0;
        wlog_on = 0;
        roll_back();
        put_counters(&counters_lifted);
        apply(&written_a);
        release(&written_a);
        lift_set_stack(saved_sp);
        shadow_unchecked++;
        *ret = twin_ret;
        return 0;
    }
    native_ret = NATIVE_FUNCTIONS[id].run(&host_vm, args);
    trying = 0;
    wlog_on = 0;
    if (bits && ((native_ret ^ twin_ret) & (bits == 8 ? 0xffu : 0xffffffffu))) {
        fprintf(stderr, "shadow: %s returned 0x%x, its machine code 0x%x\n", NATIVE_FUNCTIONS[id].name, native_ret, twin_ret);
        differs = 1;
    }
    if (first_difference(&written_a, sp, &where)) {
        fprintf(stderr, "shadow: %s: the machine code left a different byte at 0x%08x\n", NATIVE_FUNCTIONS[id].name, where);
        differs = 1;
    }
    capture(&written_b);
    roll_back();
    put_counters(&counters_lifted);
    apply(&written_a);
    if (first_difference(&written_b, sp, &where)) {
        fprintf(stderr, "shadow: %s wrote 0x%08x differently from its machine code\n", NATIVE_FUNCTIONS[id].name, where);
        differs = 1;
    }
    release(&written_a);
    release(&written_b);
    shadow_compared++;
    shadow_mismatches += (uint64_t)differs;
    lift_set_stack(saved_sp);
    *ret = twin_ret;
    return 0;
}
#endif

int host_native_has_twin(int id)
{
#ifdef HOST_LIFTED
    return lift_find((host_vm.L ? host_vm.L : &LAYOUT_DUEL)->entry[id]) != NULL;
#else
    (void)id;
    return 0;
#endif
}

int host_native_try(int id, const uint32_t *args, uint32_t sp, const uint32_t *regs, uint32_t *ret)
{
#ifdef HOST_LIFTED
    uint32_t saved_sp;
    if (shadow_on && lift_find(host_vm.L->entry[id]))
        return shadow_try(id, args, sp, regs, ret);
    saved_sp = lift_get_stack();
    lift_set_stack(sp);
#else
    (void)regs;
#endif
    host_sp = sp;
    drop_undo();
    trying = 1;
    save_counters();
    if (setjmp(try_jb)) {
        trying = 0;
        roll_back();
        restore_counters();
#ifdef HOST_LIFTED
        lift_set_stack(saved_sp);
#endif
        return 1;
    }
    *ret = NATIVE_FUNCTIONS[id].run(&host_vm, args);
    trying = 0;
    drop_undo();
#ifdef HOST_LIFTED
    lift_set_stack(saved_sp);
#endif
    return 0;
}

const char *host_native_name(int id)
{
    return NATIVE_FUNCTIONS[id].name;
}

uint32_t host_native_entry(int id)
{
    return host_vm.L->entry[id];
}

int host_native_nargs(int id)
{
    return NATIVE_FUNCTIONS[id].nargs;
}

int host_native_ret_bits(int id)
{
    return NATIVE_FUNCTIONS[id].ret_bits;
}

int host_native_self_charging(int id)
{
    return NATIVE_FUNCTIONS[id].self_charging;
}

uint32_t host_native_run(int id, const uint32_t *args, uint32_t sp)
{
#ifdef HOST_LIFTED
    lift_set_stack(sp); /* a native function that runs lifted code puts its frames below the guest's */
#endif
    host_sp = sp;
    return NATIVE_FUNCTIONS[id].run(&host_vm, args);
}

#ifdef HOST_LIFTED
int host_lifted_count(void)
{
    return LIFTED_COUNT;
}

const char *host_lifted_program(void)
{
    return LIFT_PROGRAM;
}

void host_set_builtin_import(uint32_t slot, int kind)
{
    lift_set_builtin_import(slot, kind);
}

void host_set_rand_cell(uint32_t addr)
{
    lift_set_rand_cell(addr);
}

void host_set_clock_cells(uint32_t ticks, uint32_t timer, uint32_t timer_handle)
{
    lift_set_clock_cells(ticks, timer, timer_handle);
}

void host_set_clock_model(uint32_t publish_count_cell, int mode, double instructions_per_second)
{
    lift_pending_hook = pending_charge;
    lift_set_clock_model(publish_count_cell, mode, instructions_per_second);
}

void host_set_clock_window(uint64_t remaining_instructions)
{
    lift_set_clock_window(remaining_instructions);
}

uint64_t host_builtin_calls(void)
{
    return lift_builtin_calls;
}

void host_set_builtin_burn(uint32_t n)
{
    lift_set_builtin_burn(n);
}

uint32_t host_lifted_entry(int index)
{
    return LIFTED[index].entry;
}

const char *host_lifted_name(int index)
{
    return LIFTED[index].name;
}

uint32_t host_lifted_run(uint32_t entry, uint32_t esp, const uint32_t *regs)
{
    uint32_t ret = 0;
    lift_run_at(&host_vm, entry, esp, regs, &ret);
    return ret;
}

int host_lifted_try(uint32_t entry, uint32_t esp, const uint32_t *regs, uint32_t *ret)
{
    uint32_t saved_sp = lift_get_stack();

    drop_undo();
    trying = 1;
    save_counters();
    if (setjmp(try_jb)) {
        trying = 0;
        roll_back();
        restore_counters();
        lift_set_stack(saved_sp);
        return 1;
    }
    lift_run_at(&host_vm, entry, esp, regs, ret);
    trying = 0;
    drop_undo();
    lift_set_stack(saved_sp);
    return 0;
}
#else
int host_lifted_count(void)
{
    return 0;
}

const char *host_lifted_program(void)
{
    return "";
}

void host_set_builtin_import(uint32_t slot, int kind)
{
    (void)slot;
    (void)kind;
}

void host_set_rand_cell(uint32_t addr)
{
    (void)addr;
}

void host_set_clock_cells(uint32_t ticks, uint32_t timer, uint32_t timer_handle)
{
    (void)ticks;
    (void)timer;
    (void)timer_handle;
}

void host_set_clock_model(uint32_t publish_count_cell, int mode, double instructions_per_second)
{
    (void)publish_count_cell;
    (void)mode;
    (void)instructions_per_second;
}

void host_set_clock_window(uint64_t remaining_instructions)
{
    (void)remaining_instructions;
}

uint64_t host_builtin_calls(void)
{
    return 0;
}

void host_set_builtin_burn(uint32_t n)
{
    (void)n;
}

uint32_t host_lifted_entry(int index)
{
    (void)index;
    return 0;
}

const char *host_lifted_name(int index)
{
    (void)index;
    return "";
}

uint32_t host_lifted_run(uint32_t entry, uint32_t esp, const uint32_t *regs)
{
    (void)entry;
    (void)esp;
    (void)regs;
    return 0;
}

int host_lifted_try(uint32_t entry, uint32_t esp, const uint32_t *regs, uint32_t *ret)
{
    (void)entry;
    (void)esp;
    (void)regs;
    *ret = 0;
    return 0;
}
#endif

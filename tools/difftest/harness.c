/*
 * harness.c - run one native function on one test vector.
 *
 * run_vectors.py turns a JSON vector (SPEC.md) into this line protocol on stdin:
 *
 *   program MAGIC|DUEL
 *   function <name>              one of NATIVE_FUNCTIONS in src/native/engine.c
 *   entry <addr>                 optional: must equal the layout's entry address
 *   arg <u32>                    one per argument, in order
 *   mem <addr> <hex bytes>       snapshot input
 *   call <addr> <ret> <nargs> <args...>   the next call the function is expected to make
 *   callmem <addr> <hex bytes>   memory the callee above writes before it returns
 *   read <addr> <len>            bytes to print after the run
 *   run
 *
 * and reads back:
 *
 *   retbits <8|32>
 *   ret <u32>
 *   call <n> <addr> <nargs> <args...>     every call made, in order
 *   written <addr> <hex bytes>            every write by the native code, with the final bytes
 *   fault <addr> / faults <total>         reads of memory the snapshot did not define
 *   read <addr> <hex bytes>
 *   error <text>                          unexpected call or bad input (exit status 3)
 *
 * Numbers may be decimal or 0x-prefixed hex. Comparing results is run_vectors.py's job.
 */
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "../../src/native/engine.h"
#ifdef NATIVE_LIFTED
#include "../../src/native/lift_bridge.h" /* + the generated handlers: `Handler_<address>` functions run lifted */
#endif

#define MAX_CALLS 8192
#define MAX_ARGS 32
#define MAX_READS 8192
#define MAX_WRITES 65536

typedef struct {
    uint32_t addr;
    uint8_t *bytes;
    size_t len;
} Blob;

typedef struct {
    uint32_t addr, ret;
    int nargs;
    uint32_t args[MAX_ARGS];
    Blob *writes;
    int nwrites;
} Mock;

typedef struct {
    Mem mem;
    Mock mocks[MAX_CALLS];
    int nmocks, next_mock;
    int ncalls;
    uint32_t reads[MAX_READS][2];
    int nreads;
    uint32_t writes[MAX_WRITES][2];
    int nwrites, writes_dropped;
    jmp_buf bail;
    uint32_t frame_lo, frame_hi; /* writes inside are the lifted code's own stack frame, not part of its result */
} Harness;

static Harness H;
#ifdef NATIVE_LIFTED
static uint32_t lifted_entry;
static NativeInfo lifted_info;
static int lifted_nargs = 3;   /* a lifted function that is not a card handler takes the arguments its vector has */
static int natives_only;       /* `natives`: the lifted function's native callees run native, everything else is replayed */
#endif

static void die(const char *msg, const char *detail)
{
    printf("error %s%s%s\n", msg, detail ? ": " : "", detail ? detail : "");
    exit(3);
}

static uint32_t parse_u32(const char *s)
{
    char *end;
    unsigned long v;
    if (!s)
        die("missing number", NULL);
    v = strtoul(s, &end, 0);
    if (*end)
        die("bad number", s);
    return (uint32_t)v;
}

static int hexval(int c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    if (c >= 'A' && c <= 'F')
        return c - 'A' + 10;
    return -1;
}

static uint8_t *parse_hex(const char *s, size_t *len)
{
    size_t n = s ? strlen(s) : 0, i;
    uint8_t *out;
    if (n == 0 || n % 2)
        die("bad hex bytes", s);
    out = malloc(n / 2);
    if (!out)
        die("out of memory", NULL);
    for (i = 0; i < n / 2; i++) {
        int hi = hexval(s[2 * i]), lo = hexval(s[2 * i + 1]);
        if (hi < 0 || lo < 0)
            die("bad hex bytes", s);
        out[i] = (uint8_t)(hi << 4 | lo);
    }
    *len = n / 2;
    return out;
}

static void on_write(void *ctx, uint32_t addr, size_t len)
{
    (void)ctx;
    if (H.frame_lo <= addr && addr < H.frame_hi)
        return;
    if (H.nwrites < MAX_WRITES) {
        H.writes[H.nwrites][0] = addr;
        H.writes[H.nwrites][1] = (uint32_t)len;
        H.nwrites++;
    } else {
        H.writes_dropped++;
    }
}

static uint32_t call_hook(void *ctx, Callee callee, uint32_t addr, int nargs, const uint32_t *args)
{
    Mock *mock;
    int i;
    (void)ctx;

    printf("call %d 0x%08x %d", H.ncalls, addr, nargs);
    for (i = 0; i < nargs; i++)
        printf(" 0x%08x", args[i]);
    printf("\n");
    H.ncalls++;

    if (H.next_mock >= H.nmocks) {
        printf("error unexpected call to 0x%08x (%s): the vector records no more calls\n", addr,
               callee_name(callee));
        longjmp(H.bail, 1);
    }
    mock = &H.mocks[H.next_mock++];
    if (mock->addr != addr) {
        printf("error call %d went to 0x%08x (%s) but the vector expects 0x%08x\n", H.ncalls - 1, addr,
               callee_name(callee), mock->addr);
        longjmp(H.bail, 1);
    }
    /* The callee's side effects, then its return value. They are not writes by the native code. */
    for (i = 0; i < mock->nwrites; i++)
        mem_load(&H.mem, mock->writes[i].addr, mock->writes[i].bytes, mock->writes[i].len);
    return mock->ret;
}

/* Run the function; returns 1 if a call went wrong and the run was abandoned. */
static int run_guarded(const NativeInfo *fn, Vm *vm, const uint32_t *args, uint32_t *ret)
{
    if (setjmp(H.bail))
        return 1;
#ifdef NATIVE_LIFTED
    if (fn == &lifted_info) {
        if (!lift_call_function(vm, lifted_entry, lifted_nargs, args, ret))
            die("no lifted function at", fn->name);
        return 0;
    }
#endif
    *ret = fn->run(vm, args);
    return 0;
}

int main(void)
{
    static char line[1 << 23];
    const Layout *layout = NULL;
    const NativeInfo *fn = NULL;
    uint32_t args[MAX_ARGS], entry = 0, ret = 0;
    int nargs = 0, have_entry = 0, ran = 0, bailed, i, have_stack_ptr = 0;
    uint32_t stack_ptr = 0;
    int use_lifted_handlers = 0, have_handler_esp = 0;
    uint32_t handler_esp = 0;
    (void)have_stack_ptr;
    (void)stack_ptr;
    Vm vm;

    mem_init(&H.mem);
    while (fgets(line, sizeof(line), stdin)) {
        char *cmd = strtok(line, " \t\r\n");
        if (!cmd || cmd[0] == '#')
            continue;
        if (strcmp(cmd, "program") == 0) {
            const char *p = strtok(NULL, " \t\r\n");
            layout = p ? layout_for(p) : NULL;
            if (!layout)
                die("unknown program", p);
        } else if (strcmp(cmd, "function") == 0) {
            const char *name = strtok(NULL, " \t\r\n");
            fn = name ? native_find(name) : NULL;
#ifdef NATIVE_LIFTED
            if (!fn && name && strncmp(name, "Handler_", 8) == 0) {
                int k;
                for (k = 0; k < LIFTED_COUNT; k++)
                    if (strcmp(LIFTED[k].name, name) == 0) {
                        lifted_info.name = LIFTED[k].name;
                        lifted_info.nargs = 3;
                        lifted_info.ret_bits = 32;
                        lifted_entry = LIFTED[k].entry;
                        fn = &lifted_info;
                    }
            }
#endif
            if (!fn)
                die("no native implementation of", name);
        } else if (strcmp(cmd, "handler_esp") == 0) {
            handler_esp = parse_u32(strtok(NULL, " \t\r\n"));
            have_handler_esp = 1;
        } else if (strcmp(cmd, "natives") == 0) {
#ifdef NATIVE_LIFTED
            natives_only = 1;
#endif
        } else if (strcmp(cmd, "lifted") == 0) {
            use_lifted_handlers = 1;
        } else if (strcmp(cmd, "esp") == 0) {
            stack_ptr = parse_u32(strtok(NULL, " \t\r\n")); /* the recorded stack pointer: for lifted handlers only */
            have_stack_ptr = 1;
        } else if (strcmp(cmd, "entry") == 0) {
            entry = parse_u32(strtok(NULL, " \t\r\n"));
            have_entry = 1;
        } else if (strcmp(cmd, "arg") == 0) {
            if (nargs >= MAX_ARGS)
                die("too many arguments", NULL);
            args[nargs++] = parse_u32(strtok(NULL, " \t\r\n"));
        } else if (strcmp(cmd, "mem") == 0) {
            uint32_t addr = parse_u32(strtok(NULL, " \t\r\n"));
            size_t len;
            uint8_t *bytes = parse_hex(strtok(NULL, " \t\r\n"), &len);
            mem_load(&H.mem, addr, bytes, len);
            free(bytes);
        } else if (strcmp(cmd, "call") == 0) {
            Mock *mock;
            if (H.nmocks >= MAX_CALLS)
                die("too many calls", NULL);
            mock = &H.mocks[H.nmocks++];
            memset(mock, 0, sizeof(*mock));
            mock->addr = parse_u32(strtok(NULL, " \t\r\n"));
            mock->ret = parse_u32(strtok(NULL, " \t\r\n"));
            mock->nargs = (int)parse_u32(strtok(NULL, " \t\r\n"));
            if (mock->nargs > MAX_ARGS)
                die("too many call arguments", NULL);
            for (i = 0; i < mock->nargs; i++)
                mock->args[i] = parse_u32(strtok(NULL, " \t\r\n"));
        } else if (strcmp(cmd, "callmem") == 0) {
            Mock *mock;
            Blob *b;
            if (H.nmocks == 0)
                die("callmem before any call", NULL);
            mock = &H.mocks[H.nmocks - 1];
            mock->writes = realloc(mock->writes, sizeof(Blob) * (size_t)(mock->nwrites + 1));
            if (!mock->writes)
                die("out of memory", NULL);
            b = &mock->writes[mock->nwrites++];
            b->addr = parse_u32(strtok(NULL, " \t\r\n"));
            b->bytes = parse_hex(strtok(NULL, " \t\r\n"), &b->len);
        } else if (strcmp(cmd, "read") == 0) {
            if (H.nreads >= MAX_READS)
                die("too many reads", NULL);
            H.reads[H.nreads][0] = parse_u32(strtok(NULL, " \t\r\n"));
            H.reads[H.nreads][1] = parse_u32(strtok(NULL, " \t\r\n"));
            H.nreads++;
        } else if (strcmp(cmd, "run") == 0) {
            ran = 1;
            break;
        } else {
            die("unknown command", cmd);
        }
    }
    if (!ran)
        die("no run command", NULL);
    if (!layout || !fn)
        die("program and function are required", NULL);
#ifdef NATIVE_LIFTED
    if (fn == &lifted_info)
        lifted_nargs = nargs;
#endif
    if (nargs != fn->nargs
#ifdef NATIVE_LIFTED
        && fn != &lifted_info
#endif
    ) {
        char detail[64];
        snprintf(detail, sizeof(detail), "%s takes %d, got %d", fn->name, fn->nargs, nargs);
        die("wrong argument count", detail);
    }
#ifdef NATIVE_LIFTED
    if (fn == &lifted_info) {
        if (have_entry && entry != lifted_entry) {
            char detail[96];
            snprintf(detail, sizeof(detail), "%s is at 0x%08x, the vector says 0x%08x", fn->name, lifted_entry, entry);
            die("entry address mismatch", detail);
        }
        have_entry = 0;
    }
#endif
    if (have_entry && entry != layout->entry[fn->id]) {
        char detail[96];
        snprintf(detail, sizeof(detail), "%s in %s is at 0x%08x, the vector says 0x%08x", fn->name,
                 layout->program, layout->entry[fn->id], entry);
        die("entry address mismatch", detail);
    }

    vm.mem = &H.mem;
    vm.L = layout;
    vm.call = call_hook;
    vm.call_ctx = &H;
#ifdef NATIVE_LIFTED
    if (fn == &lifted_info) {
        uint32_t top = have_stack_ptr ? stack_ptr + 4u * (uint32_t)(nargs + 1) : LIFT_STACK_TOP;
        lift_attach(&vm, natives_only ? LIFT_CALLS_NATIVES_ONLY : LIFT_CALLS_HOOK);
        lift_set_stack(top);
        H.frame_lo = top - 4u * (uint32_t)(nargs + 1) - 0x200000u;
        H.frame_hi = top;
    }
#endif
#ifdef NATIVE_LIFTED
    if (use_lifted_handlers) { /* the scan runs a card's handler as lifted code; what that calls runs native, or replays */
        /* with the recorded stack position, a handler's frame sits where the original's did (3 arguments and a return address) */
        uint32_t top = have_handler_esp ? handler_esp + 16u : LIFT_STACK_TOP;
        lift_attach(&vm, LIFT_CALLS_NATIVE);
        lift_set_stack(top);
        H.frame_lo = top - 0x200000u;
        H.frame_hi = top;
    }
#else
    (void)handler_esp;
    (void)have_handler_esp;
    if (use_lifted_handlers)
        die("this vector needs the lifted handlers: build the harness with `make lifted`", NULL);
#endif
    H.mem.on_write = on_write;
    printf("retbits %d\n", fn->ret_bits);
    fflush(stdout);

    {
        extern uint64_t lift_icount;
        uint64_t cost0 = native_cost_extra
#ifdef NATIVE_LIFTED
                         + lift_icount
#endif
            ;
        bailed = run_guarded(fn, &vm, args, &ret);
        printf("cost %llu\n", (unsigned long long)(native_cost_extra
#ifdef NATIVE_LIFTED
                                                     + lift_icount
#endif
                                                     - cost0));
    }
    H.mem.on_write = NULL;

    if (!bailed)
        printf("ret 0x%08x\n", ret);
    for (i = 0; i < H.nwrites; i++) {
        uint32_t k;
        printf("written 0x%08x ", H.writes[i][0]);
        for (k = 0; k < H.writes[i][1]; k++)
            printf("%02x", mem_rd8(&H.mem, H.writes[i][0] + k));
        printf("\n");
    }
    if (H.writes_dropped)
        printf("error %d writes not recorded (raise MAX_WRITES)\n", H.writes_dropped);
    for (i = 0; i < H.mem.fault_count && i < MEM_MAX_FAULTS; i++)
        printf("fault 0x%08x\n", H.mem.faults[i]);
    printf("faults %d\n", H.mem.fault_count);
    for (i = 0; i < H.nreads; i++) {
        uint32_t k;
        printf("read 0x%08x ", H.reads[i][0]);
        for (k = 0; k < H.reads[i][1]; k++) {
            uint32_t a = H.reads[i][0] + k;
            if (mem_is_defined(&H.mem, a))
                printf("%02x", mem_rd8(&H.mem, a));
            else
                printf("??");
        }
        printf("\n");
    }
    mem_free(&H.mem);
    return bailed ? 3 : 0;
}

/*
 * lift_rt.h - the runtime the lifted x86 code is compiled against (tools/lift/x86lift.py).
 *
 * Lifted code is a mechanical translation of a function's machine code: each instruction becomes C that works on
 * the same registers and the same memory, so there is nothing to guess about types or names. Registers are local
 * variables of the lifted function, memory is the guest address space (a flat array G addressed by the original
 * virtual addresses), and the stack is part of that memory. Flags are computed eagerly after each instruction that
 * sets them (the compiler removes the ones nothing reads). Calls out of the function go through lift_call, which
 * reads the arguments off the guest stack.
 *
 * Only what x86lift.py is able to emit is here: the 32-bit integer subset (no FPU, SSE, string instructions or
 * segment overrides). Anything else makes the lifter refuse the function.
 */
#ifndef LIFT_RT_H
#define LIFT_RT_H

#include <stdint.h>

/* The registers a function starts with are its caller's, which matters only for what it pushes to save them: that stays on
 * the stack below it for later code to read as an uninitialised local, and the original game does read such locals. The
 * code that enters a lifted function sets lift_in first (from the guest's registers when the host replaces the function, from
 * the caller's registers for a call between lifted functions); a lifted call sets lift_out to the registers at the call, which
 * the callee, lifted or not, is entered with. A build that does not care (the flat harness) leaves both zero. */
typedef struct {
    uint32_t eax, ecx, edx, ebx, ebp, esi, edi;
} LiftRegs;

/* What the standalone program (src/port) shares with lifted code, in one block, so lifted code reaches the runtime through a pointer and
 * not through symbols it would have to find by name in the executable (the game module is a separate library: src/port/gamemod.c).
 *   ret_edx: EDX as the callee returned it: a 64-bit result (the C runtime's divide and multiply helpers) comes back in EDX:EAX. A function
 *            that ends sets it, a host function leaves the poison value (lift_call).
 *   x87:     the x87 unit (a double returned in st(0) is the caller's to take): eight registers holding the raw bits of a double, the top
 *            of the stack (x87[xt] is st(0)), the control word and the status word's condition codes. Arithmetic is in double precision
 *            (the hardware's is extended: a result may differ in its last bits, which the game's own uses do not show).
 * `th` is per guest thread: the scheduler swaps it when the baton passes (only one guest thread runs at a time). */
typedef struct LiftThreadState {
    uint32_t ret_edx;
    uint32_t x87_cw, x87_sw;
    unsigned xt;
    uint64_t x87[8];
} LiftThreadState;

typedef struct LiftState {
    LiftRegs in, out;
    int32_t budget;                 /* back-edges left before the running guest thread must hand the baton on (LIFT_PREEMPT) */
    LiftThreadState th;
} LiftState;

/* The one table the runtime hands the game module (pentamoor_game_init): everything lifted code needs from it. Only ever append to it,
 * and raise LIFT_ABI when the meaning of a field changes. */
#define LIFT_ABI 2                                            /* 2: LiftGame and LiftModule carry the build id of the file they were lifted from (lift_tables.h) */
typedef struct LiftHost {
    uint32_t abi, size;                                       /* LIFT_ABI, sizeof(LiftHost) */
    uint8_t *guest;                                           /* the guest's 4 GB address space: a guest address is an offset */
    LiftState *state;
    uint32_t (*call)(uint32_t target, uint32_t argp, uint32_t *cleanup);   /* a call out of a lifted function: argp is the guest address of the first argument, the result is EAX */
    void (*preempt)(void);                                    /* pass the baton on (a back-edge ran the budget out) */
    void (*bad_jump)(uint32_t from);                          /* an indirect jump whose index fell outside its table */
    void (*trace)(uint32_t a);                                /* the coverage build (LIFT_TRACE) */
    void (*watch)(uint32_t a, uint32_t n, uint32_t v);
    void (*bad_ret)(uint32_t fn, uint32_t entry_esp, uint32_t esp);
} LiftHost;

#if defined(LIFT_BACKEND_FLAT4G) && defined(LIFT_MODULE)
#define LIFT_VIA_HOST 1
/* The game module's side: its own private copies of the pointers, set by pentamoor_game_init, so lifted code reads them PC-relative and no
 * symbol of the runtime is named. (Compile the module with -fvisibility=hidden: only pentamoor_game_init is exported.) */
extern uint8_t *lift_guest;
extern LiftState *lift_S;
extern const LiftHost *lift_host;
extern uint32_t (*lift_call_fn)(uint32_t target, uint32_t argp, uint32_t *cleanup);    /* host->call and host->preempt, copied: one load fewer per call */
extern void (*lift_preempt_fn)(void);
#define G lift_guest
#define lift_in (lift_S->in)
#define lift_out (lift_S->out)
#define lift_budget (lift_S->budget)
#define lift_ret_edx (lift_S->th.ret_edx)
#define lift_x87 (lift_S->th.x87)
#define lift_xt (lift_S->th.xt)
#define lift_x87_cw (lift_S->th.x87_cw)
#define lift_x87_sw (lift_S->th.x87_sw)
#define lift_call lift_call_fn
#define lift_preempt lift_preempt_fn
#define lift_bad_jump lift_host->bad_jump
#define lift_trace lift_host->trace
#define lift_w lift_host->watch
#define lift_bad_ret lift_host->bad_ret
#elif defined(LIFT_BACKEND_FLAT4G)
/* The runtime's side: the block is a plain global, and the old names are its fields. */
extern LiftState lift_state;
#define lift_in (lift_state.in)
#define lift_out (lift_state.out)
#define lift_budget (lift_state.budget)
#define lift_ret_edx (lift_state.th.ret_edx)
#define lift_x87 (lift_state.th.x87)
#define lift_xt (lift_state.th.xt)
#define lift_x87_cw (lift_state.th.x87_cw)
#define lift_x87_sw (lift_state.th.x87_sw)
#endif

/* Two ways to give the lifted code its memory:
 *   the flat harness (tools/difftest/harness_flat.c): the guest address space is an array G, indexed by lift_xl(address);
 *   the native layer (LIFT_BACKEND_MEM, src/native/lift_bridge.c): the sparse image of mem.h, so a lifted handler reads
 *   and writes the same memory the hand-written native functions do, and a read of a byte nothing defined is a fault. */
#ifdef LIFT_BACKEND_MEM
#include "mem.h"
extern Mem *lift_mem;
#else
extern uint8_t *G; /* the guest address space, indexed by lift_xl(virtual address) */
#endif

/* The flat harness records every write (a function that stores the value the memory already holds still wrote), and
 * a debug build (LIFT_UNDEF_CHECK) also reports reads of memory that neither the vector nor an earlier write defined. */
#ifdef LIFT_TRACK_WRITES
void lift_chk_write(uint32_t a, uint32_t n);
#define CHK_W(a, n) (lift_chk_write((uint32_t)(a), n), 0)
#else
#define CHK_W(a, n) 0
#endif
#ifdef LIFT_UNDEF_CHECK
void lift_chk_read(uint32_t a, uint32_t n);
#define CHK_R(a, n) (lift_chk_read((uint32_t)(a), n), 0)
#else
#define CHK_R(a, n) 0
#endif

/* Instruction coverage: the debug harness build (LIFT_COVERAGE) records which instructions the vectors executed. */
#ifdef LIFT_COVERAGE
void lift_cov(uint32_t a);
#define LIFT_COV(a) lift_cov(a)
#elif defined(LIFT_TRACE)
/* The standalone program's coverage build: which instructions ran, in first-execution order (src/port/call.c, PORT_COV=file). */
#ifndef LIFT_VIA_HOST
void lift_trace(uint32_t a);
#endif
#define LIFT_COV(a) lift_trace(a)
#elif defined(LIFT_COUNT)
/* The host build counts the instructions lifted code executes (they are the original's, one for one), to charge the guest's
 * clock for them. */
extern uint64_t lift_icount;
#define LIFT_COV(a) (lift_icount++)
#else
#define LIFT_COV(a) ((void)0)
#endif

#ifdef LIFT_BACKEND_MEM
#define RD8(a) mem_rd8(lift_mem, (uint32_t)(a))
#define RD16(a) mem_rd16(lift_mem, (uint32_t)(a))
#define RD32(a) mem_rd32(lift_mem, (uint32_t)(a))
#define WR8(a, v) mem_wr8(lift_mem, (uint32_t)(a), (uint8_t)(v))
#define WR16(a, v) mem_wr16(lift_mem, (uint32_t)(a), (uint16_t)(v))
#define WR32(a, v) mem_wr32(lift_mem, (uint32_t)(a), (uint32_t)(v))
#elif defined(LIFT_BACKEND_FLAT4G)
/* The standalone program (src/port): the whole 4 GB of the guest's address space is reserved at G, so a guest address is an offset. */
#ifndef LIFT_VIA_HOST
extern uint8_t *G;
#endif
#define RD8(a) (*(uint8_t *)(G + (uint32_t)(a)))
#define RD16(a) (*(uint16_t *)(G + (uint32_t)(a)))
#define RD32(a) (*(uint32_t *)(G + (uint32_t)(a)))
#ifdef LIFT_TRACE
/* The coverage build can watch a stretch of guest memory (PORT_WATCH=lo-hi, hex): every write to it is reported with the instruction that made it. */
#ifndef LIFT_VIA_HOST
void lift_w(uint32_t a, uint32_t n, uint32_t v);
#endif
#define LIFT_W(a, n, v) lift_w((uint32_t)(a), (n), (uint32_t)(v))
#define WR8(a, v) (LIFT_W(a, 1, v), *(uint8_t *)(G + (uint32_t)(a)) = (uint8_t)(v))
#define WR16(a, v) (LIFT_W(a, 2, v), *(uint16_t *)(G + (uint32_t)(a)) = (uint16_t)(v))
#define WR32(a, v) (LIFT_W(a, 4, v), *(uint32_t *)(G + (uint32_t)(a)) = (uint32_t)(v))
#else
#define WR8(a, v) (*(uint8_t *)(G + (uint32_t)(a)) = (uint8_t)(v))
#define WR16(a, v) (*(uint16_t *)(G + (uint32_t)(a)) = (uint16_t)(v))
#define WR32(a, v) (*(uint32_t *)(G + (uint32_t)(a)) = (uint32_t)(v))
#endif
#else
/* Where in G a guest address lives. The harness keeps the low 16 MB in place and folds the few high blocks a vector
 * touches (heap, a thread's stack) in behind them. */
uint32_t lift_xl(uint32_t a);

#define RD8(a) (CHK_R(a, 1), *(uint8_t *)(G + lift_xl((uint32_t)(a))))
#define RD16(a) (CHK_R(a, 2), *(uint16_t *)(G + lift_xl((uint32_t)(a))))
#define RD32(a) (CHK_R(a, 4), *(uint32_t *)(G + lift_xl((uint32_t)(a))))
#define WR8(a, v) (CHK_W(a, 1), *(uint8_t *)(G + lift_xl((uint32_t)(a))) = (uint8_t)(v))
#define WR16(a, v) (CHK_W(a, 2), *(uint16_t *)(G + lift_xl((uint32_t)(a))) = (uint16_t)(v))
#define WR32(a, v) (CHK_W(a, 4), *(uint32_t *)(G + lift_xl((uint32_t)(a))) = (uint32_t)(v))
#endif

/* A point where a long-running loop can be preempted: every backward jump. The standalone program (src/port, LIFT_PREEMPT) runs each
 * guest thread on a host thread and hands the baton on here once a thread has used up its budget; the other builds have no threads of
 * their own to switch. */
#ifdef LIFT_PREEMPT
#ifndef LIFT_BACKEND_FLAT4G
extern int32_t lift_budget;
#endif
#ifndef LIFT_VIA_HOST
void lift_preempt(void);
#endif
#define LIFT_BACKEDGE() do { if (--lift_budget < 0) lift_preempt(); } while (0)
#else
#define LIFT_BACKEDGE() ((void)0)
#endif

/* Where the thread information block is (what an `fs:` access is relative to); the host puts one there. */
#ifndef LIFT_FS_BASE
#define LIFT_FS_BASE 0x7FFDE000u
#endif

/* A function returns with ESP where it was entered (at the return address): the coverage build checks it, to find a callee whose argument cleanup
 * or frame the lifter got wrong (a later `push` then lands in the caller's locals). */
#ifdef LIFT_TRACE
#ifndef LIFT_VIA_HOST
void lift_bad_ret(uint32_t fn, uint32_t entry_esp, uint32_t esp);
#endif
#define LIFT_RET(fn) do { if (R_esp != esp) lift_bad_ret(fn, esp, R_esp); } while (0)
#else
#define LIFT_RET(fn) ((void)0)
#endif

/* Partial registers of a 32-bit register variable r. */
#define LO8(r) ((uint8_t)(r))
#define HI8(r) ((uint8_t)((r) >> 8))
#define LO16(r) ((uint16_t)(r))
#define SET_LO8(r, v) ((r) = ((r) & 0xffffff00u) | (uint8_t)(v))
#define SET_HI8(r, v) ((r) = ((r) & 0xffff00ffu) | ((uint32_t)(uint8_t)(v) << 8))
#define SET_LO16(r, v) ((r) = ((r) & 0xffff0000u) | (uint16_t)(v))

#define MASK(bits) ((bits) == 32 ? 0xffffffffu : ((1u << (bits)) - 1u))
#define SIGNBIT(x, bits) (((x) >> ((bits) - 1)) & 1u)

/* Flag updates: a, b are the operands and r the (masked) result of an operation on `bits` bits. */
#define FLAGS_ZS(r, bits) \
    do { ZF = ((r) & MASK(bits)) == 0; SF = SIGNBIT(r, bits); } while (0)
#define FLAGS_ADD(a, b, r, bits) \
    do { uint32_t m_ = MASK(bits); FLAGS_ZS(r, bits); CF = ((r) & m_) < ((a) & m_); \
         OF = SIGNBIT(~((a) ^ (b)) & ((a) ^ (r)), bits); } while (0)
#define FLAGS_SUB(a, b, r, bits) \
    do { uint32_t m_ = MASK(bits); FLAGS_ZS(r, bits); CF = ((a) & m_) < ((b) & m_); \
         OF = SIGNBIT(((a) ^ (b)) & ((a) ^ (r)), bits); } while (0)
/* add and subtract with the carry in: the carry out counts it (a + b + CF can wrap where a + b does not; a - b - CF borrows when a < b + CF) */
#define FLAGS_ADC(a, b, r, bits) \
    do { uint32_t m_ = MASK(bits); uint64_t w_ = (uint64_t)((a) & m_) + (uint64_t)((b) & m_) + CF; FLAGS_ZS(r, bits); \
         CF = (uint32_t)(w_ >> (bits)) & 1u; OF = SIGNBIT(~((a) ^ (b)) & ((a) ^ (r)), bits); } while (0)
#define FLAGS_SBB(a, b, r, bits) \
    do { uint32_t m_ = MASK(bits); uint32_t c_ = (uint64_t)((a) & m_) < (uint64_t)((b) & m_) + CF; FLAGS_ZS(r, bits); \
         CF = c_; OF = SIGNBIT(((a) ^ (b)) & ((a) ^ (r)), bits); } while (0)
#define FLAGS_LOGIC(r, bits) \
    do { FLAGS_ZS(r, bits); CF = 0; OF = 0; } while (0)

/* The same for the other builds (the flat harness, the native layer), which keep them as plain variables. */
#ifndef LIFT_BACKEND_FLAT4G
extern LiftRegs lift_in, lift_out;
extern __thread uint32_t lift_ret_edx;
#endif
#define LIFT_CALL_REGS() (lift_out = (LiftRegs){R_eax, R_ecx, R_edx, R_ebx, R_ebp, R_esi, R_edi})

/* The x87 unit, per guest thread (a double returned in st(0) is the caller's to take): eight registers holding the raw bits of a double, the top of the
 * stack (X87[XT] is st(0)), the control word and the status word's condition codes. Arithmetic is in double precision (the hardware's is extended: a result may
 * differ in its last bits, which the game's own uses do not show). */
#include <math.h>
#include <string.h>
#ifndef LIFT_BACKEND_FLAT4G
extern __thread uint64_t lift_x87[8];
extern __thread unsigned lift_xt;
extern __thread uint32_t lift_x87_cw, lift_x87_sw;
#endif
#define X87 lift_x87
#define XT lift_xt
static inline double x87_get(uint64_t b) { double d; memcpy(&d, &b, 8); return d; }
static inline uint64_t x87_put(double d) { uint64_t b; memcpy(&b, &d, 8); return b; }
static inline double x87_f32(uint32_t b) { float f; memcpy(&f, &b, 4); return (double)f; }
static inline uint32_t x87_f32_bits(double d) { float f = (float)d; uint32_t b; memcpy(&b, &f, 4); return b; }
#define ST(k) x87_get(X87[(XT + (unsigned)(k)) & 7u])
#define SET_ST(k, d) (X87[(XT + (unsigned)(k)) & 7u] = x87_put(d))
#define X87_PUSH_BITS(b) do { uint64_t pb_ = (b); XT = (XT + 7u) & 7u; X87[XT] = pb_; } while (0)
#define X87_PUSH(d) X87_PUSH_BITS(x87_put(d))
#define X87_POP() (XT = (XT + 1u) & 7u)
#define RD64(a) ((uint64_t)RD32(a) | ((uint64_t)RD32((uint32_t)(a) + 4u) << 32))
#define WR64(a, v) do { uint64_t w_ = (v); WR32(a, (uint32_t)w_); WR32((uint32_t)(a) + 4u, (uint32_t)(w_ >> 32)); } while (0)
/* what the control word's rounding field makes of d (fist, fistp) */
static inline int64_t x87_round(double d)
{
    switch ((lift_x87_cw >> 10) & 3u) {
    case 1: d = floor(d); break;
    case 2: d = ceil(d); break;
    case 3: d = trunc(d); break;
    default: d = nearbyint(d); break;
    }
    return (int64_t)d;
}
/* the condition codes C3, C2, C0 of a comparison of a with b */
static inline void x87_compare(double a, double b)
{
    lift_x87_sw = (lift_x87_sw & ~0x4500u) | (a != a || b != b ? 0x4500u : a > b ? 0u : a < b ? 0x100u : 0x4000u);
}

/* Calls out of a lifted function. `argp` is the guest address of the first argument (just above the return address that
 * the call pushed); the result is the callee's EAX. The generated module defines the table it consults. */
#ifndef LIFT_VIA_HOST
uint32_t lift_call(uint32_t target, uint32_t argp, uint32_t *cleanup);
#endif

/* An indirect jump whose index fell outside its table (the original's bound check should make this impossible). */
#ifndef LIFT_VIA_HOST
void lift_bad_jump(uint32_t from);
#endif

/* The game's setjmp and longjmp (_setjmp3 and longjmp of its C runtime). A lifted function that calls _setjmp3 (the lifter writes the call out as the code below, not as a call: x86lift.py,
 * setjmp_site) keeps a C jmp_buf of its own, and longjmp (longjmp_site) leaves the C stack by that buffer, so the function goes on in its own frame, with the registers of the
 * game's buffer. The guest's jmp_buf (a _JUMP_BUFFER of the Visual C++ runtime: Ebp, Ebx, Edi, Esi, Esp, Eip, then the exception registration, try level and three words the
 * runtime does not use) holds the registers as the real one does, and, in two of its unused words, a magic number and the address of the C buffer. longjmp of a buffer no lifted
 * setjmp filled stops the program (lift_bad_jump). */
#include <setjmp.h>
#ifdef _WIN32
#define LIFT_SETJMP(jb) setjmp(jb)
#else
#define LIFT_SETJMP(jb) _setjmp(jb)
#endif
#define LIFT_JB_MAGIC 0x4a4d4c50u
static inline void lift_jb_store(uint32_t buf, jmp_buf *jb, uint32_t ebp, uint32_t ebx, uint32_t edi, uint32_t esi, uint32_t esp, uint32_t eip)
{
    uint64_t p = (uint64_t)(uintptr_t)jb;

    WR32(buf, ebp);
    WR32(buf + 4u, ebx);
    WR32(buf + 8u, edi);
    WR32(buf + 12u, esi);
    WR32(buf + 16u, esp);                  /* what Esp is after the call returns: the caller's, with the arguments still on it */
    WR32(buf + 20u, eip);
    WR32(buf + 24u, 0xFFFFFFFFu);          /* no exception registration */
    WR32(buf + 28u, 0xFFFFFFFFu);          /* try level */
    WR32(buf + 32u, LIFT_JB_MAGIC);
    WR32(buf + 36u, (uint32_t)p);
    WR32(buf + 40u, (uint32_t)(p >> 32));
}
static inline void lift_longjmp(uint32_t buf, uint32_t value) __attribute__((noreturn));
static inline void lift_longjmp(uint32_t buf, uint32_t value)
{
    jmp_buf *jb;
    uint64_t p;

    if (RD32(buf + 32u) != LIFT_JB_MAGIC) {
        lift_bad_jump(buf);
        __builtin_trap();
    }
    p = (uint64_t)RD32(buf + 36u) | ((uint64_t)RD32(buf + 40u) << 32);
    jb = (jmp_buf *)(uintptr_t)p;
    longjmp(*jb, value ? (int)value : 1);          /* a value of 0 gives 1, as the C runtime's does */
}

/* Signed division of EDX:EAX by a 32-bit divisor, as IDIV does (the original faults on zero or overflow). */
static inline void lift_idiv32(uint32_t *eax, uint32_t *edx, uint32_t divisor)
{
    int64_t n = (int64_t)(((uint64_t)*edx << 32) | *eax);
    int64_t d = (int32_t)divisor;
    *eax = (uint32_t)(int32_t)(n / d);
    *edx = (uint32_t)(int32_t)(n % d);
}

/* Unsigned division of EDX:EAX by a 32-bit divisor, as DIV does, and the unsigned product MUL puts in EDX:EAX. */
static inline void lift_div32(uint32_t *eax, uint32_t *edx, uint32_t divisor)
{
    uint64_t n = ((uint64_t)*edx << 32) | *eax;
    *eax = (uint32_t)(n / divisor);
    *edx = (uint32_t)(n % divisor);
}

static inline void lift_mul32(uint32_t *eax, uint32_t *edx, uint32_t factor)
{
    uint64_t p = (uint64_t)*eax * factor;
    *eax = (uint32_t)p;
    *edx = (uint32_t)(p >> 32);
}

#endif

/*
 * lift_bridge.h - lifted card handlers (tools/lift) running inside the native layer.
 *
 * A lifted handler is the original's machine code translated to C over the same registers and memory
 * (lift_rt.h). Built with LIFT_BACKEND_MEM it reads and writes the sparse image (mem.h) the hand-written native
 * functions use, so the two layers share state and a read of memory nothing defined is a fault, as it is for them.
 *
 * The handlers are generated from the user's own executable (tools/lift/gen_handlers.py) and never committed, so this
 * file and lift_bridge.c are the only part of the layer in the repository: a build that has no generated code simply
 * does not link lift_bridge.c, and the layer behaves as before.
 *
 * Calls out of a lifted handler (lift_call in lift_rt.h) are routed by lift_attach's mode:
 *   LIFT_CALLS_HOOK    every call goes to the Vm's hook (the difftest harness replays recorded calls: handlers are
 *                      checked on their own, one at a time)
 *   LIFT_CALLS_NATIVE  a function that has a native implementation runs it, another lifted function runs lifted, and
 *                      anything else goes to the hook
 *   LIFT_CALLS_NATIVES_ONLY  a native function runs, everything else (lifted functions included) goes to the hook: the lifted
 *                      function is then run in the same surroundings as a native one (tools/difftest/check_costs.py)
 */
#ifndef NATIVE_LIFT_BRIDGE_H
#define NATIVE_LIFT_BRIDGE_H

#include "engine.h"
#include "lift_tables.h"

typedef enum { LIFT_CALLS_HOOK, LIFT_CALLS_NATIVE, LIFT_CALLS_NATIVES_ONLY } LiftCalls;

/* Make the Vm's memory and hook the ones lifted code uses, and install the card-handler dispatch of vm_call_at. */
void lift_attach(Vm *vm, LiftCalls mode);
void lift_detach(void);

/* Where the lifted code's stack lives while it runs (it needs memory for pushes and locals), and its current top. */
#define LIFT_STACK_TOP 0x7ff00000u
void lift_set_stack(uint32_t top);
uint32_t lift_get_stack(void);

/* Run the lifted function at `entry` on a frame already built at `esp`; 1 if there is such a function. */
int lift_run_at(Vm *vm, uint32_t entry, uint32_t esp, const uint32_t *regs, uint32_t *ret);
/* 1 while a lifted function's call goes out to the original (its frame is already built on the lifted stack), else 0: the
 * host calls the original in place then, instead of building a frame of its own below. */
extern int lift_inplace;
/* The registers at the lifted call being made (EAX, ECX, EDX, EBX, EBP, ESI, EDI). */
void lift_call_regs(uint32_t regs[7]);

/* The generated function that stands for the original at `entry`, or NULL. */
const LiftedFn *lift_find(uint32_t entry);
/* Stop (or resume) running the lifted function at `entry` from native and lifted code; calls to it go to the original. */
void lift_set_enabled(uint32_t entry, int on);

/* Run the lifted function at `entry` as a call with these cdecl/stdcall arguments; 1 if there is such a function. */
int lift_call_function(Vm *vm, uint32_t entry, int nargs, const uint32_t *args, uint32_t *ret);

/* C runtime imports the lifted code calls in C instead of out to the emulator (lift_bridge.c). */
enum { BUILTIN_RAND = 1, BUILTIN_MEMCPY = 2, BUILTIN_MEMSET = 3, BUILTIN_TICKS = 4, BUILTIN_TIMER_IOCTL = 5, BUILTIN_STRLEN = 6, BUILTIN_STRCPY = 7,
       BUILTIN_STRCAT = 8, BUILTIN_ABS = 9, BUILTIN_STRCMP = 10 };
void lift_set_builtin_import(uint32_t slot, int kind);
void lift_set_rand_cell(uint32_t addr);
void lift_set_clock_cells(uint32_t ticks, uint32_t timer, uint32_t timer_handle);
/* How hosted code sees the clock advance while it runs (a clock the guest only updates between slices would stand still for a
 * search that polls it): mode 1, charged: when the work done since lift_clock_window's mark reaches the slice's remainder the clock
 * jumps by that work (the original's slice would have ended there); mode 2, live: by the real time since the guest last published it. */
void lift_set_clock_model(uint32_t publish_count_cell, int mode, double instructions_per_second);
void lift_set_clock_window(uint64_t remaining_instructions);
extern uint64_t (*lift_pending_hook)(void);
void lift_set_builtin_burn(uint32_t n);
extern uint64_t lift_builtin_calls;

#endif

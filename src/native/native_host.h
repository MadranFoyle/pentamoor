/*
 * native_host.h - the native layer as a shared library, for a host that runs the original program in an emulator
 * (tools/emu_spike/winemu/native_host.py).
 *
 * The host gives the library the guest's memory (read and write callbacks) and a way to call a function of the guest
 * that is not native. It then asks the library to run a native function, or a lifted card handler, in place of the
 * original at the same address. Everything addresses guest memory by the original's own addresses, so nothing is
 * translated.
 */
#ifndef NATIVE_HOST_H
#define NATIVE_HOST_H

#include <stdint.h>

typedef uint32_t (*HostMemRead)(void *ctx, uint32_t addr, int size);
typedef void (*HostMemWrite)(void *ctx, uint32_t addr, int size, uint32_t value);
/* Call the guest's function at `addr` with these cdecl/stdcall arguments (the host builds the frame at `sp`, below it) and
 * return what it returned. With `inplace` the frame is already built (a lifted function's own, whose return address slot is
 * at `sp`, arguments above it): the host calls the function on it, with the registers `regs` (EAX, ECX, EDX, EBX, EBP, ESI,
 * EDI) if given, so that what the original leaves on the stack is what it left. The host may run guest code and, in doing so, call back into this library. */
typedef uint32_t (*HostCall)(uint32_t addr, int nargs, const uint32_t *args, uint32_t sp, int inplace, const uint32_t *regs);

int host_init(const char *program, HostMemRead rd, HostMemWrite wr, HostCall call);
/* Guest memory the library can reach directly: the guest range [base, base + size) is the host's memory at `ptr`. Accesses
 * outside every region go to the callbacks given to host_init. */
void host_add_region(uint32_t base, uint32_t size, void *ptr);

/* Native functions: ids 0.. in the order of engine.h, -1 when `name` is unknown. */
int host_native_count(void);
int host_native_find(const char *name);
const char *host_native_name(int id);
uint32_t host_native_entry(int id);
int host_native_nargs(int id);
int host_native_ret_bits(int id);
/* 1 if the function adds the instructions its original would have run to the cost counter itself (no per-call average to charge). */
int host_native_self_charging(int id);
uint32_t host_native_run(int id, const uint32_t *args, uint32_t sp);
/* The same, without giving the call a thread of its own: if the function needs to call out to the guest it is stopped, every
 * write it made is undone, and 1 is returned (run it again with host_native_run); 0 means it finished and `*ret` is its
 * result. Most calls never call out, and this is much cheaper. */
int host_native_try(int id, const uint32_t *args, uint32_t sp, const uint32_t *regs, uint32_t *ret);
/* Shadow mode: a native function that has a lifted twin is run both ways, compared, and the twin's result kept (see native_host.c).
 * `regs` (the guest's EAX, ECX, EDX, EBX, EBP, ESI, EDI) are what the twin starts with. */
void host_set_shadow(int on);
int host_native_has_twin(int id); /* 1 if the library has the function's lifted twin */
void host_shadow_stats(uint64_t *compared, uint64_t *mismatches, uint64_t *unchecked);

/* Lifted handlers (0 when the library was built without the generated code). */
int host_lifted_count(void);
uint32_t host_lifted_entry(int index);
const char *host_lifted_name(int index);
/* Run the lifted function at `entry` on the frame the guest has built at `esp`. */
/* `regs`: the guest's EAX, ECX, EDX, EBX, EBP, ESI, EDI as the function is entered, or NULL. */
uint32_t host_lifted_run(uint32_t entry, uint32_t esp, const uint32_t *regs);
int host_lifted_try(uint32_t entry, uint32_t esp, const uint32_t *regs, uint32_t *ret); /* see host_native_try */

/* A function (native or lifted, by its entry address) the host does not replace in this run: native and lifted code that calls it
 * goes out to the original instead of running its own version. Everything is enabled until this says otherwise. */
void host_set_enabled(uint32_t entry, int on, int lifted); /* lifted 0: the native function at `entry`, 1: its lifted twin or the lifted function */

/* Work done so far: how often each native function was entered (nested calls included), and how many instructions lifted
 * code executed. `entries` has host_native_count() numbers. */
void host_counters(uint64_t *entries, uint64_t *lifted_instructions);

#endif

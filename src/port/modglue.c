/* modglue.c - the game module's one entry point. Built into the game module only (a library made from the .c files of sources/generated/lift_<program>,
 * see the Makefile), never into the runtime. The module reaches the runtime through the LiftHost it is given here, and nothing else.
 * Plain C99 (the module may be built with another compiler than the runtime, for example `zig cc`). */
#define LIFT_BACKEND_FLAT4G 1
#define LIFT_MODULE 1
#include "lift_rt.h"
#include "lift_tables.h"

#ifdef _WIN32
#define PENTAMOOR_EXPORT __declspec(dllexport)
#elif defined(__GNUC__)
#define PENTAMOOR_EXPORT __attribute__((visibility("default")))
#else
#define PENTAMOOR_EXPORT
#endif

uint8_t *lift_guest;
LiftState *lift_S;
const LiftHost *lift_host;
uint32_t (*lift_call_fn)(uint32_t target, uint32_t argp, uint32_t *cleanup);
void (*lift_preempt_fn)(void);

PENTAMOOR_EXPORT const LiftGame *pentamoor_game_init(const LiftHost *host)
{
    static LiftGame g;

    if (!host || host->abi != LIFT_ABI || host->size < sizeof(LiftHost))
        return 0;
    lift_host = host;
    lift_guest = host->guest;
    lift_S = host->state;
    lift_call_fn = host->call;
    lift_preempt_fn = host->preempt;
    g.abi = LIFT_ABI;
    g.size = sizeof(g);
    g.program = LIFT_PROGRAM;
    g.lifted = LIFTED;
    g.nlifted = LIFTED_COUNT;
    g.functions = LIFT_FUNCTIONS;
    g.nfunctions = LIFT_FUNCTION_COUNT;
    g.sigs = LIFT_IMPORT_SIGS;
    g.nsigs = LIFT_IMPORT_SIG_COUNT;
    g.modules = LIFT_MODULES;
    return &g;
}

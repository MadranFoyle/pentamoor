/* The tables a generated handlers_gen.c defines and the harness reads (tools/lift/gen_handlers.py). */
#ifndef LIFT_TABLES_H
#define LIFT_TABLES_H

#include <stdint.h>

typedef struct LiftedFn {
    const char *name;
    uint32_t entry;                  /* where the original function starts */
    uint32_t (*fn)(uint32_t esp);    /* the lifted function: esp points at the return address, the arguments follow */
} LiftedFn;

typedef struct CalleeRow {
    uint32_t addr;
    int nargs;        /* stack arguments the call passes (what its frame reads and its `ret` pops: tools/lift/fnscan.py) */
    uint32_t cleanup; /* bytes the callee pops itself (a `ret imm16`), 0 for a cdecl function */
} CalleeRow;

extern const LiftedFn LIFTED[];
extern const int LIFTED_COUNT;
extern const char LIFT_PROGRAM[];  /* "DUEL" or "MAGIC": the program whose machine code the tables hold */
extern const char LIFT_BUILD_ID[]; /* the build id of that program's file: the SHA-256 of the bytes it was lifted from, 64 lower-case hex characters (tools/lift/builds.py) */
extern const CalleeRow LIFT_CALLEES[];
extern const int LIFT_CALLEE_COUNT;

/* Every lifted function's own row (its argument count, the bytes its `ret` pops), and the signature of every import of the program. */
typedef struct LiftImportSig {
    const char *dll, *name;
    int nargs;
    uint32_t cleanup;
} LiftImportSig;
extern const CalleeRow LIFT_FUNCTIONS[];
extern const int LIFT_FUNCTION_COUNT;
extern const LiftImportSig LIFT_IMPORT_SIGS[];
extern const int LIFT_IMPORT_SIG_COUNT;

/* A DLL lifted by tools/lift/gen_dll.py for one base address: its functions and the signatures of what it imports (tables are the module's own). */
typedef struct LiftModule {
    const char *name;                /* "statwin.dll" */
    uint32_t base, entry;            /* where it must be mapped, and its entry point (DllMain) at that base */
    const LiftedFn *lifted; int nlifted;
    const CalleeRow *functions; int nfunctions;
    const LiftImportSig *sigs; int nsigs;
    const char *build_id;            /* the build id of the DLL's file (as LIFT_BUILD_ID is the program's) */
} LiftModule;
extern const LiftModule *const LIFT_MODULES[];   /* ends with 0 */

/* What a game module hands the runtime: all of the above in one struct, returned by its one exported function
 *     const LiftGame *pentamoor_game_init(const LiftHost *host);        (src/port/modglue.c; LiftHost is in lift_rt.h)
 * The module keeps `host` and reaches the runtime only through it, and the runtime reads the tables only through the result: neither names a
 * symbol of the other. It returns 0 if the host's ABI is not the one it was built for. */
typedef struct LiftGame {
    uint32_t abi, size;                             /* LIFT_ABI, sizeof(LiftGame) */
    const char *program;                            /* LIFT_PROGRAM */
    const LiftedFn *lifted; int nlifted;            /* LIFTED */
    const CalleeRow *functions; int nfunctions;     /* LIFT_FUNCTIONS */
    const LiftImportSig *sigs; int nsigs;           /* LIFT_IMPORT_SIGS */
    const LiftModule *const *modules;               /* LIFT_MODULES */
    const char *build_id;                           /* LIFT_BUILD_ID */
} LiftGame;

#endif

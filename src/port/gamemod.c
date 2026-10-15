/* gamemod.c - load the game module: the library made from the lifted C (the only game-derived code), which holds the translated functions.
 *
 * The runtime and the module name nothing of each other's: the module exports one function, pentamoor_game_init, and is handed one LiftHost
 * (lift_rt.h: the guest's memory, the shared state block, the few runtime functions lifted code calls). It answers with a LiftGame (lift_tables.h:
 * the lifted functions and their signatures). Opening the library and finding that function are the two functions below
 * (plat.h: dlopen and dlsym, or LoadLibrary and GetProcAddress on Windows).
 *
 * The single-executable build (make static) links the module's objects into the executable; then there is no library to open and
 * PENTAMOOR_STATIC_GAME names the function directly. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "plat.h"
#include "port.h"

const LiftGame *lift_game;

#ifdef PENTAMOOR_STATIC_GAME
const LiftGame *pentamoor_game_init(const LiftHost *host);
static void *load_module(const char *path, char *err, size_t n) { (void)path; (void)err; (void)n; return (void *)1; }
static void *find_symbol(void *mod, const char *name) { (void)mod; (void)name; return (void *)pentamoor_game_init; }
#else
static void *load_module(const char *path, char *err, size_t n) { return plat_dlopen(path, err, n); }
static void *find_symbol(void *mod, const char *name) { return plat_dlsym(mod, name); }
#endif

void gamemod_load(const char *path)
{
    char err[512] = "";
    void *mod, *sym;
    static LiftHost host;          /* the module keeps the pointer */
    const LiftGame *g;
    const LiftGame *(*init)(const LiftHost *);

    if (!path)
        path = getenv("PENTAMOOR_MODULE");
#ifndef PENTAMOOR_STATIC_GAME
    if (!path || !*path)
        port_fatal("no game module: give -m path/to/game module (the library tools/install/install.py --build makes), or set PENTAMOOR_MODULE");
#endif
    mod = load_module(path, err, sizeof(err));
    if (!mod)
        port_fatal("cannot load the game module %s: %s", path, err);
    sym = find_symbol(mod, "pentamoor_game_init");
    if (!sym)
        port_fatal("%s is not a game module (no pentamoor_game_init)", path);
    memcpy(&init, &sym, sizeof(sym));

    memset(&host, 0, sizeof(host));
    host.abi = LIFT_ABI;
    host.size = sizeof(host);
    host.guest = G;
    host.state = &lift_state;
    host.call = lift_call;
    host.preempt = lift_preempt;
    host.bad_jump = lift_bad_jump;
#ifdef LIFT_TRACE
    host.trace = lift_trace;
    host.watch = lift_w;
    host.bad_ret = lift_bad_ret;
#endif
    g = init(&host);
    if (!g)
        port_fatal("%s was built for another runtime (host ABI %u)", path ? path : "the game module", (unsigned)LIFT_ABI);
    if (g->abi != LIFT_ABI || g->size != sizeof(LiftGame))
        port_fatal("%s: the game tables are of another version", path ? path : "the game module");
    lift_game = g;
}

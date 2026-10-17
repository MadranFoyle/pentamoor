/* gamemod.c - load the game module: the library made from the lifted C (the only game-derived code), which holds the translated functions.
 *
 * The runtime and the module name nothing of each other's: the module exports one function, pentamoor_game_init, and is handed one LiftHost
 * (lift_rt.h: the guest's memory, the shared state block, the few runtime functions lifted code calls). It answers with a LiftGame (lift_tables.h:
 * the lifted functions and their signatures). Opening the library and finding that function are the two functions below
 * (plat.h: dlopen and dlsym, or LoadLibrary and GetProcAddress on Windows).
 *
 * The single-executable build (make static) links the module's objects into the executable; then there is no library to open and
 * PENTAMOOR_STATIC_GAME names the function directly.
 *
 * iOS (PORT_STATIC_MODULES): an app cannot load code that is not signed into it, so the three programs' modules are linked into the app, each with its entry point renamed
 * (pentamoor_game_init_magic, _deck, _duel; tools/ios/build_ios.sh makes each one a single object whose other symbols are local, so they cannot collide), and "the module" is a name:
 * -m magic (or game_magic.dylib, or MAGIC.EXE: gamemod_static_pick takes the program out of it). */
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "plat.h"
#include "port.h"

const LiftGame *lift_game;

/* Which of `names` (lower case: "magic", "deck", "duel") a module or program is named by: "magic", "MAGIC.EXE", "game_deck.dylib", "/x/y/game_duel.so", "DUEL.EXE" ... Returns its index,
 * or -1. Pure: compiled in every build so that it is tested (test_module.c). */
int gamemod_static_pick(const char *spec, const char *const names[], int n)
{
    char base[64];
    const char *b;
    size_t len = 0;
    int i;

    if (!spec)
        return -1;
    b = plat_basename(spec);
    for (; *b && *b != '.' && len + 1 < sizeof(base); b++)
        base[len++] = (char)tolower((unsigned char)*b);
    base[len] = 0;
    if (!strncmp(base, "game_", 5))
        memmove(base, base + 5, strlen(base + 5) + 1);
    for (i = 0; i < n; i++)
        if (!strcmp(base, names[i]))
            return i;
    return -1;
}

#if defined(PORT_STATIC_MODULES)
typedef const LiftGame *(*GameInit)(const LiftHost *);
#ifdef PORT_STATIC_MAGIC
const LiftGame *pentamoor_game_init_magic(const LiftHost *host);
#endif
#ifdef PORT_STATIC_DECK
const LiftGame *pentamoor_game_init_deck(const LiftHost *host);
#endif
#ifdef PORT_STATIC_DUEL
const LiftGame *pentamoor_game_init_duel(const LiftHost *host);
#endif
typedef struct { const char *name; GameInit init; } StaticModule;
static const StaticModule static_modules[] = {
#ifdef PORT_STATIC_MAGIC
    {"magic", pentamoor_game_init_magic},
#endif
#ifdef PORT_STATIC_DECK
    {"deck", pentamoor_game_init_deck},
#endif
#ifdef PORT_STATIC_DUEL
    {"duel", pentamoor_game_init_duel},
#endif
    {NULL, NULL}
};

static void *load_module(const char *path, char *err, size_t n)
{
    const char *names[4];
    int i, count = 0;

    for (i = 0; static_modules[i].name; i++)
        names[count++] = static_modules[i].name;
    i = gamemod_static_pick(path, names, count);
    if (i < 0) {
        snprintf(err, n, "no game module named %s is linked into this program (it has %d)", path ? path : "(none)", count);
        return NULL;
    }
    return (void *)&static_modules[i];
}
static void *find_symbol(void *mod, const char *name)
{
    GameInit f = ((const StaticModule *)mod)->init;
    void *p;

    if (strcmp(name, "pentamoor_game_init"))
        return NULL;
    memcpy(&p, &f, sizeof(p));
    return p;
}
#elif defined(PENTAMOOR_STATIC_GAME)
const LiftGame *pentamoor_game_init(const LiftHost *host);
static void *load_module(const char *path, char *err, size_t n) { (void)path; (void)err; (void)n; return (void *)1; }
static void *find_symbol(void *mod, const char *name) { (void)mod; (void)name; return (void *)pentamoor_game_init; }
#else
static void *load_module(const char *path, char *err, size_t n) { return plat_dlopen(path, err, n); }
static void *find_symbol(void *mod, const char *name) { return plat_dlsym(mod, name); }
#endif

static char module_loaded_from[1100];
const char *gamemod_path(void) { return module_loaded_from; }

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
    snprintf(module_loaded_from, sizeof(module_loaded_from), "%s", path ? path : "");
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

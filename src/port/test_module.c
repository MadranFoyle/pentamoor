/* test_module.c - the runtime loads a game module and runs lifted code in it: the stub module (stubgame/, three functions written the way tools/lift writes them) is opened by
 * gamemod.c (dlopen, LoadLibrary), and its functions run against the guest's memory, call a host function, take the preemption budget and use the x87 stack, all
 * through the pointers the module is handed. No game file is needed.
 *   make -C src/port test          (builds build/game_stub.<so|dylib|dll> first)  */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "plat.h"
#include "port.h"
#include "sched.h"

static int failures, checks;
#define CHECK(c) do { checks++; if (!(c)) { failures++; printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

void port_index_functions(void);
int pe_find_resource(uint32_t hinst, uint32_t type, uint32_t name, uint32_t *addr, uint32_t *size) { (void)hinst; (void)type; (void)name; (void)addr; (void)size; return 0; }

#define ESP 0x002FFF00u

static int polls;
static void count_poll(void) { polls++; }

/* the host function the module calls: a * 10 + b */
static uint32_t ten_a_plus_b(const uint32_t *a) { return a[0] * 10 + a[1]; }

static const LiftedFn *find_fn(const char *name)
{
    int i;

    for (i = 0; i < lift_game->nlifted; i++)
        if (!strcmp(lift_game->lifted[i].name, name))
            return &lift_game->lifted[i];
    return NULL;
}

int main(int argc, char **argv)
{
    const char *path = argc > 1 ? argv[1] : "build/game_stub" PLAT_MODULE_SUFFIX;
    const LiftedFn *sum, *call, *x87;
    uint32_t i, expect = 0, r;
    double in[2] = {2.25, 0};

    guest_init();
    gamemod_load(path);
    sched_init();
    port_index_functions();
    CHECK(lift_game != NULL && !strcmp(lift_game->program, "STUB") && lift_game->nlifted == 4);
    sum = find_fn("stub_sum");
    call = find_fn("stub_call");
    x87 = find_fn("stub_x87");
    CHECK(sum && call && x87);
    if (!sum || !call || !x87)
        return 1;

    /* a lifted function reads the guest's memory (an address nothing has touched yet) and its loop's back-edges take the budget: the baton is offered when it runs out */
    for (i = 0; i < 1000; i++) {
        WR32(0x00600000u + 4 * i, 3 * i);
        expect += 3 * i;
    }
    WR32(ESP, 0);
    WR32(ESP + 4, 0x00600000u);
    WR32(ESP + 8, 1000);
    memset(&lift_in, 0, sizeof(lift_in));
    lift_budget = 100;
    sched_poll_hook = count_poll;
    r = sum->fn(ESP);
    sched_poll_hook = NULL;
    CHECK(r == expect);
    CHECK(polls == 1);                                                  /* the budget of 100 ran out once (then it is the scheduler's full one) */
    CHECK(lift_budget > 0);

    /* pace.c's pass of the button table starts with a fresh budget, so the window's thread cannot run in the middle of it (docs/notes/journal-done.md): the baton is offered when
     * fewer back-edges than asked for are left, and not otherwise */
    lift_budget = 50;
    sched_poll_hook = count_poll;
    polls = 0;
    CHECK(sched_yield_if_low(10) == 0 && polls == 0 && lift_budget == 50);
    CHECK(sched_yield_if_low(100) == 1 && polls == 1 && lift_budget > 100);
    CHECK(sched_yield_if_low(100) == 0 && polls == 1);
    sched_poll_hook = NULL;

    /* a call out of lifted code: through lift_call to a host function, its result back in EAX, the arguments in order, EDX left as the host function leaves it */
    {
        uint32_t fn = port_host_function(ten_a_plus_b);

        WR32(ESP, 0);
        WR32(ESP + 4, fn);
        WR32(ESP + 8, 4);
        WR32(ESP + 12, 2);
        memset(&lift_in, 0, sizeof(lift_in));
        r = call->fn(ESP);
        CHECK(r == 43);
        CHECK(RD32(0x00720000u) == 42);
        CHECK(lift_state.th.ret_edx == 0xcdcdcdcdu);
    }

    /* the x87 stack and the thread's state block are the runtime's (the module wrote through a pointer into it) */
    WR64(0x00800000u, 0);
    memcpy(G + 0x00800000u, in, sizeof(in));
    WR32(ESP, 0);
    WR32(ESP + 4, 0x00800000u);
    WR32(ESP + 8, 0x90000000u);                                         /* far from anything else: the module touches a page of its own */
    memset(&lift_in, 0, sizeof(lift_in));
    lift_xt = 0;
    r = x87->fn(ESP);
    {
        double out;

        memcpy(&out, G + 0x00800008u, sizeof(out));
        CHECK(out == 2.25 * 2 + 0.5);
    }
    CHECK(RD32(0x90000000u) == 0xC0DEu);
    CHECK(lift_state.th.ret_edx == 0x1234u);
    CHECK(lift_xt == 0);                                                /* pushed once, popped once */
    (void)r;

    /* the iOS build links the three programs' modules in and picks one by name (gamemod_static_pick): a module name, a program name or a path to either */
    {
        static const char *const names[] = {"magic", "deck", "duel"};

        CHECK(gamemod_static_pick("magic", names, 3) == 0);
        CHECK(gamemod_static_pick("MAGIC.EXE", names, 3) == 0);
        CHECK(gamemod_static_pick("game_deck.dylib", names, 3) == 1);
        CHECK(gamemod_static_pick("/a/b/Program/DUEL.EXE", names, 3) == 2);
        CHECK(gamemod_static_pick("build/game_duel.so", names, 3) == 2);
        CHECK(gamemod_static_pick("Deck", names, 3) == 1);
        CHECK(gamemod_static_pick("stub.exe", names, 3) == -1);
        CHECK(gamemod_static_pick("", names, 3) == -1);
        CHECK(gamemod_static_pick(NULL, names, 3) == -1);
        CHECK(gamemod_static_pick("magic", names, 0) == -1);
        CHECK(gamemod_static_pick("magical.exe", names, 3) == -1);
    }

    printf("test_module: %d checks, %d failed\n", checks, failures);
    return failures != 0;
}

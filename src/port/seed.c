/* seed.c - PORT_SEED (see seed.h): the C runtime's generator as many streams, one for each place in the game that asks for a number, all made from one seed. */
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "seed.h"

#define STREAMS 1024                    /* the places that ask: the game has a few dozen (a 2.15 world, a village, a duel: 60 in all) */

typedef struct {
    uint32_t site, caller, epoch, state;
    int used;
} Stream;

static int on, env_read;
static uint32_t user_seed;              /* N */
static uint32_t base;                   /* what the streams start from since the last srand */
static uint32_t epoch;                  /* counts srand calls: a stream that is older than this starts again from base */
static unsigned n_srand;
static Stream streams[STREAMS];
static Stream overflow;                 /* one shared stream for the places beyond STREAMS */
#define SITES 16                        /* the places that seed (the game has three) */
static uint32_t from_site[SITES], times[SITES];     /* ... and how many times each has */

/* murmur3's finaliser: every input bit moves every output bit */
static uint32_t mix(uint32_t x)
{
    x ^= x >> 16;
    x *= 0x85ebca6bu;
    x ^= x >> 13;
    x *= 0xc2b2ae35u;
    x ^= x >> 16;
    return x;
}

static uint32_t combine(uint32_t a, uint32_t b) { return mix(a * 0x9e3779b1u + mix(b) + 0x7f4a7c15u); }

int seed_parse(const char *text, uint32_t *out)
{
    char *end = NULL;
    unsigned long long v;

    if (!text || !*text || text[0] == '-' || text[0] == '+' || text[0] == ' ')
        return 0;
    errno = 0;
    v = strtoull(text, &end, 0);
    if (errno || !end || *end || v > 0xffffffffull)
        return 0;
    *out = (uint32_t)v;
    return 1;
}

void seed_set(int enable, uint32_t n)
{
    memset(streams, 0, sizeof(streams));
    memset(&overflow, 0, sizeof(overflow));
    memset(from_site, 0, sizeof(from_site));
    memset(times, 0, sizeof(times));
    on = enable;
    env_read = 1;
    user_seed = n;
    epoch = 1;                          /* a stream made before the first srand starts from the seed alone */
    n_srand = 0;
    base = combine(n, 0x5eedu);
}

void seed_init_from_env(void)
{
    const char *text;
    uint32_t n;

    if (env_read)
        return;
    env_read = 1;
    text = getenv("PORT_SEED");
    if (!text || !*text)
        return;
    if (!seed_parse(text, &n)) {
        fprintf(stderr, "PORT_SEED=%s is not a number (a decimal or 0x hexadecimal one, up to 32 bits): the run is not seeded\n", text);
        return;
    }
    seed_set(1, n);
    fprintf(stderr, "seed: PORT_SEED=%u: the game's chance and clock readings are repeatable (src/port/seed.h)\n", n);
}

void seed_reload_env(void)
{
    seed_set(0, 0);
    env_read = 0;
    seed_init_from_env();
}

int seed_active(void)
{
    seed_init_from_env();
    return on;
}

uint32_t seed_value(void) { return user_seed; }
unsigned seed_srand_calls(void) { return n_srand; }

uint32_t seed_srand(uint32_t site)
{
    uint32_t nth = 0;
    int i;

    seed_init_from_env();
    n_srand++;
    epoch++;
    for (i = 0; i < SITES; i++)                 /* the n-th time this place seeds: a second new game in one process is another world */
        if (times[i] && from_site[i] == site) {
            nth = ++times[i];
            break;
        } else if (!times[i]) {
            from_site[i] = site;
            nth = times[i] = 1;
            break;
        }
    base = combine(combine(user_seed, site), nth);
    return base;
}

static Stream *find_stream(uint32_t site, uint32_t caller)
{
    uint32_t h = combine(site, caller) % STREAMS;
    int i;

    for (i = 0; i < STREAMS; i++) {
        Stream *s = &streams[(h + (uint32_t)i) % STREAMS];

        if (!s->used) {
            s->used = 1;
            s->site = site;
            s->caller = caller;
            s->epoch = 0;                       /* never the current one (they count from 1): it starts from the seed on its first number */
            return s;
        }
        if (s->site == site && s->caller == caller)
            return s;
    }
    return &overflow;
}

uint32_t seed_rand(uint32_t site, uint32_t caller)
{
    Stream *s = find_stream(site, caller);

    if (s->epoch != epoch) {                    /* new, or the game has seeded since: start from this seed */
        s->epoch = epoch;
        s->state = combine(base, combine(site, caller));
    }
    s->state = s->state * 214013u + 2531011u;                  /* the C runtime's own generator */
    return (s->state >> 16) & 0x7fffu;
}

uint32_t seed_clock(uint32_t real_ms)
{
    seed_init_from_env();
    return (real_ms & ~0x7fu) | (combine(user_seed, 0xc10cu) & 0x7fu);
}

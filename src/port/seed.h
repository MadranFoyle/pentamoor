/* seed.h - PORT_SEED=N, a test aid: the game's random numbers and the clock readings that feed them become a function of N and of what the game itself does, so the same N gives the same
 * world, shops, decks and draws (docs/notes/controller.md, "A repeatable run"). Unset, none of this runs and the C runtime behaves exactly as before.
 *
 * What the game does with chance, found by counting the calls of Spells of the Ancients 2.15 runs (written down so the next reader need not): it seeds the C runtime's generator from the clock
 * at eight places (`srand(GetTickCount())` at the start of the process and at "Start New Game", where the world is made, and in the duel engine's set-up, which seeds from 67 times the low fifteen bits of a clock reading),
 * and everything else is `rand()` through one small function, `Random(n)`, which every part of the game calls. The world generator also starts its walk over the 128 places at `clock() & 0x7f`.
 * Two things make two runs differ even with the same seed: the clock readings, and the number of `rand()` calls that went before (the map draws a few hundred a second while it idles, so how long a
 * player or a script waited changes every number that comes after). So:
 *   - every `srand` is replaced, whatever its argument (they are all the clock in one form or another, and a form that looks like a number cannot be told from one that is a clock): the streams start
 *     again from a seed made of N, the place the call came from and how many times that place has seeded;
 *   - `rand()` has one stream for each place that asks (the return address of the call and of the function that made it, which is the game's `Random(n)` and its caller): what an idle screen
 *     draws cannot move what a shop or a deck draws;
 *   - `clock()` keeps counting milliseconds but its low seven bits are N's, so a program that reads them as chance reads N (and a wait of 60 ms lasts 60 to 188).
 * The tick count, `time()` and the other clocks are left as they are: pacing needs them to run. What is not made repeatable: anything the wall clock moves while the game runs on its own (the
 * wandering monsters walk by timers, the AI's animations), and what the person or the script does and when. */
#ifndef PORT_SEED_H
#define PORT_SEED_H

#include <stdint.h>

/* The text of PORT_SEED as a seed: a decimal or 0x-hexadecimal number up to 32 bits. 1 and *out set; 0 for anything else (empty, a sign, a word, trailing characters, too large). */
int seed_parse(const char *text, uint32_t *out);

/* Turn the aid on with seed n, or off (and forget everything); PORT_SEED is read once, by seed_init_from_env (the first rand, srand or clock call does it). */
void seed_set(int on, uint32_t n);
void seed_init_from_env(void);
void seed_reload_env(void);                 /* (the tests) read PORT_SEED again */
int seed_active(void);
uint32_t seed_value(void);

/* srand called from the guest at `site` (the return address): whatever its argument, the streams start again from a seed made of N, the place and how many times that place has seeded. Returns it. */
uint32_t seed_srand(uint32_t site);

/* rand() asked by `site` (the return address of the call) from a function that was called from `caller` (0: unknown): 0..32767 */
uint32_t seed_rand(uint32_t site, uint32_t caller);

/* The clock() reading for the real one: the same value with the low seven bits N's (within 127 ms of the real one, and it never goes back) */
uint32_t seed_clock(uint32_t real_ms);

/* how many srand calls the aid has seen (the tests) */
unsigned seed_srand_calls(void);

#endif

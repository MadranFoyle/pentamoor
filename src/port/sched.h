/*
 * sched.h - the guest's threads.
 *
 * Each guest thread runs on its own host thread (so lifted code keeps its C stack and its place in a window procedure when it
 * blocks), but only one runs at a time: a baton passes at the points where the original machine switched threads (a blocking call,
 * Sleep, a message wait) and, so that a thread spinning on a flag another sets cannot hold it for ever, every LIFT_BACKEDGE budget of
 * backward jumps in lifted code. The order is round robin over the threads that can run, so a run is repeatable apart from the clock.
 */
#ifndef PORT_SCHED_H
#define PORT_SCHED_H

#include <stdint.h>

typedef struct GThread GThread;

void sched_init(void);
GThread *sched_current(void);
uint32_t sched_tid(void);

/* Create a guest thread that calls the lifted/imported function at `entry` with one argument; returns its handle's thread. */
GThread *sched_spawn(uint32_t entry, uint32_t arg, int one_shot);
GThread *sched_spawn_args(uint32_t entry, int nargs, const uint32_t *args);
GThread *sched_spawn_timer(uint32_t cb, uint32_t id, uint32_t user);
uint32_t sched_thread_id(const GThread *t);
int sched_thread_done(const GThread *t);
uint32_t sched_thread_exit_code(const GThread *t);
GThread *sched_thread_by_id(uint32_t tid);
void sched_exit_current(uint32_t code);          /* ExitThread: does not return */

/* Block the calling thread until `ready(ctx)` is true (NULL: never) or `timeout` seconds have passed (< 0: no timeout). */
void sched_block(int (*ready)(void *), void *ctx, double timeout);
void sched_sleep(double seconds);
void sched_give_up(void);
/* Offer the baton now, and give the thread a full budget, if fewer than `min` back-edges are left of it: a place where the guest is about to run a stretch of code that must not be
 * preempted in the middle (pace.c: a screen's pass of the button table). Returns 1 if the baton was offered. */
int sched_yield_if_low(int32_t min);

/* The clock the guest sees: real time since the program started. now_ms is what GetTickCount returns. */
extern double port_clock_skew;
double port_now(void);
uint32_t port_now_ms(void);

/* Called when no thread can run: serve the host's events (the window, the keyboard) for up to `max_wait` seconds. */
extern void (*sched_idle_hook)(double max_wait);
/* Called whenever the baton is about to pass: due multimedia timers start their callbacks here. */
extern void (*sched_poll_hook)(void);

/* Per-thread state other modules keep (a thread's WM_QUIT, how long its message polls have been empty). */
int *sched_quit_flag(void);          /* 1 + exit code when PostQuitMessage was called on this thread, else 0 */
uint32_t *sched_quit_code(void);
int *sched_empty_polls(void);

#endif

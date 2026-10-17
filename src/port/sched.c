/* sched.c - guest threads on host threads with a baton (see sched.h). */
#include <errno.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "port.h"
#include "sched.h"

#define BUDGET 200000
#define STACK_BASE 0x08000000u
#define STACK_SIZE 0x00100000u
#define MAX_THREADS 256

enum { READY, BLOCKED, DONE };

struct GThread {
    int tid, state;
    pthread_t th;
    pthread_cond_t cv;
    int (*ready)(void *);
    void *ctx;
    double until;               /* wake at this port_now() (negative: no deadline) */
    uint32_t entry, arg, args[5], exit_code, stack_top;
    int nargs;
    int quit, empty_polls;
    uint32_t quit_code;
    int started;
    LiftThreadState lth;        /* this thread's x87 state and return EDX while another thread runs (lift_state.th is the running thread's) */
    int slot;                   /* which stack of the stack area it runs on (-1: the main thread has its own) */
};

static pthread_mutex_t big = PTHREAD_MUTEX_INITIALIZER;
static GThread *threads[MAX_THREADS];
static int nthreads;
static GThread *cur;
static int next_tid = 1;
static double t0;
void (*sched_idle_hook)(double max_wait);
void (*sched_poll_hook)(void);
static __thread GThread *self_thread;

static double mono(void)
{
    struct timespec ts;

    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

double port_clock_skew;     /* seconds added to the clock; the tests move time with it instead of sleeping, so a slow machine cannot overshoot a window */
double port_now(void) { return mono() - t0 + port_clock_skew; }
uint32_t port_now_ms(void) { return 60000u + (uint32_t)(port_now() * 1000.0); }

GThread *sched_current(void) { return cur; }
uint32_t sched_tid(void) { return (uint32_t)cur->tid; }
uint32_t sched_thread_id(const GThread *t) { return (uint32_t)t->tid; }
int sched_thread_done(const GThread *t) { return t->state == DONE; }
uint32_t sched_thread_exit_code(const GThread *t) { return t->exit_code; }
int *sched_quit_flag(void) { return &cur->quit; }
uint32_t *sched_quit_code(void) { return &cur->quit_code; }
int *sched_empty_polls(void) { return &cur->empty_polls; }

GThread *sched_thread_by_id(uint32_t tid)
{
    int i;

    for (i = 0; i < nthreads; i++)
        if ((uint32_t)threads[i]->tid == tid)
            return threads[i];
    return NULL;
}

static GThread *new_thread(void)
{
    GThread *t = calloc(1, sizeof(*t));
    int i;

    t->tid = next_tid++;
    pthread_cond_init(&t->cv, NULL);
    t->until = -1;
    t->lth = lift_thread_initial();
    for (i = 0; i < nthreads; i++)       /* reuse the slot of a finished thread (its record stays: a handle may still name it) */
        if (threads[i]->state == DONE && threads[i]->started == 2) {
            threads[i] = t;
            return t;
        }
    if (nthreads == MAX_THREADS)
        port_fatal("too many guest threads");
    threads[nthreads++] = t;
    return t;
}

void sched_init(void)
{
    t0 = mono();
    pthread_mutex_lock(&big);
    lift_budget = BUDGET;
    lift_state.th = lift_thread_initial();
    cur = new_thread();                  /* the main thread: the program's first host thread */
    cur->th = pthread_self();
    cur->started = 1;
    self_thread = cur;
}

/* The baton passes to `next`: the x87 state and the return EDX are per guest thread, and the lifted code (which may be a library of its own, so cannot
 * name a host thread-local) reads them from the one block lift_state.th, so the running thread's copy is swapped in here. */
static void set_cur(GThread *next)
{
    if (next != cur) {
        cur->lth = lift_state.th;
        lift_state.th = next->lth;
    }
    cur = next;
}

static int runnable(const GThread *t, double now)
{
    if (t->state == READY)
        return 1;
    if (t->state == DONE)
        return 0;
    if (t->ready && t->ready(t->ctx))
        return 1;
    return t->until >= 0 && now >= t->until;
}

/* Pass the baton to the next thread that can run (round robin after `me`); wait here until it comes back. Returns when `me` runs again. */
static void switch_from(GThread *me)
{
    for (;;) {
        double now = port_now(), wake = -1;
        int i, start = 0, idx = 0;
        GThread *next = NULL;

        if (sched_poll_hook)
            sched_poll_hook();
        for (i = 0; i < nthreads; i++)
            if (threads[i] == me)
                start = i;
        for (i = 1; i <= nthreads; i++) {
            GThread *t = threads[(start + i) % nthreads];

            if (runnable(t, now)) {
                next = t;
                break;
            }
        }
        (void)idx;
        if (next) {
            if (next->state == BLOCKED)
                next->state = READY;
            if (next == me) {
                cur = me;
                return;
            }
            set_cur(next);
            pthread_cond_signal(&next->cv);
            while (cur != me)
                pthread_cond_wait(&me->cv, &big);
            return;
        }
        /* Nobody can run: wait for the earliest deadline, serving the host's events meanwhile. */
        for (i = 0; i < nthreads; i++)
            if (threads[i]->state == BLOCKED && threads[i]->until >= 0 && (wake < 0 || threads[i]->until < wake))
                wake = threads[i]->until;
        {
            double wait = wake < 0 ? 0.005 : wake - now;

            if (wait > 0.005)
                wait = 0.005;
            if (wait < 0)
                wait = 0;
            if (sched_idle_hook)
                sched_idle_hook(wait);
            else if (wait > 0)
                usleep((useconds_t)(wait * 1e6));
        }
    }
}

void sched_block(int (*ready)(void *), void *ctx, double timeout)
{
    GThread *me = cur;

    me->state = BLOCKED;
    me->ready = ready;
    me->ctx = ctx;
    me->until = timeout < 0 ? -1 : port_now() + timeout;
    switch_from(me);
    me->state = READY;
    me->ready = NULL;
    me->until = -1;
}

void sched_sleep(double seconds) { sched_block(NULL, NULL, seconds); }

void sched_give_up(void)
{
    GThread *me = cur;

    me->state = READY;
    switch_from(me);
}

void lift_preempt(void)
{
    lift_budget = BUDGET;
    sched_give_up();
}

int sched_yield_if_low(int32_t min)
{
    if (lift_budget >= min)
        return 0;
    lift_preempt();
    return 1;
}

static void *thread_main(void *p)
{
    GThread *t = p;
    self_thread = t;
    pthread_mutex_lock(&big);
    while (cur != t)
        pthread_cond_wait(&t->cv, &big);
    t->exit_code = guest_call_on(t->stack_top, t->entry, t->nargs, t->args);
    sched_exit_current(t->exit_code);
    return NULL;
}

GThread *sched_spawn_args(uint32_t entry, int nargs, const uint32_t *args)
{
    GThread *t = new_thread();
    int slot, i, k;

    t->entry = entry;
    t->nargs = nargs;
    for (i = 0; i < nargs && i < 5; i++)
        t->args[i] = args[i];
    t->state = READY;
    /* the lowest stack no running thread is on (a thread that is done and gone leaves its stack free; timer callbacks come and go all the time,
     * so tid % 120 would hand a long-lived thread's stack to a new one) */
    for (slot = 0; slot < 120; slot++) {
        for (k = 0; k < nthreads; k++)
            if (threads[k] != t && threads[k]->slot == slot + 1 && !(threads[k]->state == DONE && threads[k]->started == 2))
                break;
        if (k == nthreads)
            break;
    }
    if (slot == 120)
        port_fatal("no free guest stack");
    t->slot = slot + 1;
    t->stack_top = STACK_BASE + (uint32_t)(slot + 1) * STACK_SIZE - 0x100;
    t->started = 1;
    pthread_create(&t->th, NULL, thread_main, t);
    return t;
}

GThread *sched_spawn(uint32_t entry, uint32_t arg, int one_shot)
{
    (void)one_shot;
    return sched_spawn_args(entry, 1, &arg);
}

/* A multimedia timer's callback: (id, 0, user, 0, 0). */
GThread *sched_spawn_timer(uint32_t cb, uint32_t id, uint32_t user)
{
    uint32_t args[5] = {id, 0, user, 0, 0};

    return sched_spawn_args(cb, 5, args);
}

void sched_exit_current(uint32_t code)
{
    GThread *me = cur;

    me->exit_code = code;
    me->state = DONE;
    if (me->tid == 1) {          /* the main thread ending ends the program */
        fflush(NULL);
        exit((int)code);
    }
    me->started = 2;
    /* hand the baton on for good */
    for (;;) {
        double now = port_now();
        int i;
        GThread *next = NULL;

        if (sched_poll_hook)
            sched_poll_hook();
        for (i = 0; i < nthreads; i++)
            if (runnable(threads[i], now)) {
                next = threads[i];
                break;
            }
        if (next) {
            if (next->state == BLOCKED)
                next->state = READY;
            set_cur(next);
            pthread_cond_signal(&next->cv);
            break;
        }
        if (sched_idle_hook)
            sched_idle_hook(0.005);
        else
            usleep(5000);
    }
    pthread_detach(me->th);
    pthread_mutex_unlock(&big);
    pthread_exit(NULL);
}

/* front.c - the guest half of the front end: the input queue, the hold on a pressed button, frames. */
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "front.h"
#include "gdi.h"
#include "gdi_int.h"
#include "navwm.h"
#include "sched.h"
#include "steamdeck.h"
#include "wm.h"
#include "yesno.h"

void compose_screen(uint8_t *rgb);

typedef struct {
    int type;                    /* 0 mouse, 1 key, 2 quit, 3 call, 4 character (WM_CHAR alone), 5 a D-pad press to navigate (kind: direction, x, y: the pointer) */
    int kind, x, y;
    uint32_t vk, sc;
    int down, ch, repeat;
    uint32_t call[5];            /* type 3: a guest function to start on a thread of its own: address, then up to four arguments */
    int ncall;
} Ev;

#define QCAP 1024
static Ev queue[QCAP];
static int qhead, qtail;
static pthread_mutex_t qlock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t qcond = PTHREAD_COND_INITIALIZER;

static uint8_t frame[SCREEN_MAX_W * SCREEN_MAX_H * 3];
static unsigned frame_n;
static pthread_mutex_t flock = PTHREAD_MUTEX_INITIALIZER;
static volatile int finished;

int front_finished(void) { return finished; }
void front_set_finished(void) { finished = 1; }

static void push(const Ev *e)
{
    pthread_mutex_lock(&qlock);
    if ((qtail + 1) % QCAP != qhead) {
        queue[qtail] = *e;
        qtail = (qtail + 1) % QCAP;
        pthread_cond_signal(&qcond);
    }
    pthread_mutex_unlock(&qlock);
}

void front_push_mouse(int kind, int x, int y)
{
    Ev e = {0};

    e.type = 0; e.kind = kind; e.x = x; e.y = y;
    push(&e);
}

void front_push_key(uint32_t vk, uint32_t scancode, int down, int ch, int repeat)
{
    Ev e = {0};

    e.type = 1; e.vk = vk; e.sc = scancode; e.down = down; e.ch = ch; e.repeat = repeat;
    push(&e);
}

void front_push_char(int ch)
{
    Ev e = {0};

    e.type = 4; e.ch = ch;
    push(&e);
}

void front_push_call(uint32_t addr, const uint32_t *args, int n)
{
    Ev e = {0};
    int i;

    e.type = 3; e.call[0] = addr; e.ncall = n > 4 ? 4 : n;
    for (i = 0; i < e.ncall; i++)
        e.call[1 + i] = args[i];
    push(&e);
}

void front_push_quit(void)
{
    Ev e = {0};

    e.type = 2;
    push(&e);
}

void front_push_nav(int dir, int x, int y)
{
    Ev e = {0};

    e.type = 5; e.kind = dir; e.x = x; e.y = y;
    push(&e);
}

/* the answer to the latest D-pad press, and whether there is anything to navigate */
static pthread_mutex_t nlock = PTHREAD_MUTEX_INITIALIZER;
static unsigned nav_n;
static int nav_kind, nav_x, nav_y, nav_dir;
static volatile int nav_ready;

int front_nav_ready(void) { return nav_ready; }

int front_nav_result(unsigned *seen, int *kind, int *x, int *y, int *dir)
{
    int got = 0;

    pthread_mutex_lock(&nlock);
    if (nav_n != *seen) {
        *seen = nav_n;
        *kind = nav_kind; *x = nav_x; *y = nav_y; *dir = nav_dir;
        got = 1;
    }
    pthread_mutex_unlock(&nlock);
    return got;
}

/* A D-pad press, on the guest side: the next target in the direction, read off the window tree (navwm.c); the window half moves the pointer there with an ordinary mouse move */
static void nav_serve(const Ev *e)
{
    static int pend, pend_fx, pend_fy, pend_tx, pend_ty;           /* the last move: asked from (fx, fy), answered (tx, ty), until the window half has put the pointer there */
    static uint32_t pend_t;
    int tx = 0, ty = 0, r, x = e->x, y = e->y;
    uint32_t now = port_now_ms();

    if (e->kind < 0) {
        navwm_dump(stderr, e->x, e->y);
        return;
    }
    if (pend && now - pend_t < 400 && x == pend_fx && y == pend_fy) {     /* a second press before the first move has reached the pointer: go on from where it is going */
        x = pend_tx;
        y = pend_ty;
    }
    r = navwm_pick(x, y, e->kind, &tx, &ty);
    if (r == NAV_NONE)
        return;
    if (r != NAV_SCROLL) {
        pend = 1; pend_fx = e->x; pend_fy = e->y; pend_tx = tx; pend_ty = ty; pend_t = now;
    }
    pthread_mutex_lock(&nlock);
    nav_n++;
    nav_kind = r == NAV_SCROLL ? NAVR_SCROLL : NAVR_MOVE;
    nav_x = tx; nav_y = ty; nav_dir = e->kind;
    pthread_mutex_unlock(&nlock);
}

int front_take_frame(uint8_t *rgb, unsigned *seen)
{
    int got = 0;

    pthread_mutex_lock(&flock);
    if (frame_n != *seen) {
        memcpy(rgb, frame, (size_t)screen_w * (size_t)screen_h * 3);
        *seen = frame_n;
        got = 1;
    }
    pthread_mutex_unlock(&flock);
    return got;
}

/* The window for a screen of sw x sh on a display whose usable area is usable_w x usable_h: the screen itself, or smaller with the same shape when it does not fit. */
void window_size_for(int sw, int sh, int usable_w, int usable_h, int *w, int *h)
{
    int max_w = usable_w - 16, max_h = usable_h - 56;            /* the frame, the title bar and a margin */
    double s;

    *w = sw;
    *h = sh;
    if (usable_w <= 0 || usable_h <= 0 || (*w <= max_w && *h <= max_h))
        return;
    s = (double)max_w / *w < (double)max_h / *h ? (double)max_w / *w : (double)max_h / *h;
    if (s < 0.25)
        s = 0.25;
    *w = (int)(*w * s);
    *h = (int)(*h * s);
}

/* How long a pressed button or key stays down before the next event is delivered. The game polls the state of the buttons and keys, and a press
 * and release delivered together would be missed by the thread that polls.
 *
 * A key, and a mouse button while no screen loop is looking at it (the map's loop reads the button once a frame, 60 ms), stays down HOLD_MS.
 * A button that the loops of the game's screens look at (the pre-call hook of 0x41f3ea, pace.c, calls front_ui_pass) ends as soon as one such
 * pass has seen it down (a click is one pass), and is held up to HOLD_MAX_MS while such a screen is running and has not seen it yet (a screen
 * that is busy loading must not lose the click). */
#define HOLD_MS 70
#define HOLD_MAX_MS 250                 /* the longest a button waits for a screen's loop to look at it */
#define UI_ACTIVE_MS 300                /* a screen's loop that passed this recently is running */

int front_hold_rule(uint32_t held_ms, int mouse, int seen, int ui_active)
{
    if (!mouse)
        return held_ms < HOLD_MS;
    if (seen)
        return 0;
    if (held_ms < HOLD_MS)
        return 1;
    return ui_active && held_ms < HOLD_MAX_MS;
}

/* Text input (steamdeck.h, text_wanted_rule): whether an edit control of the open dialog has the focus (looked at on every serve), and when the game's own name box last asked for a
 * key (textfocus.c). The window half asks front_text_wanted. */
static volatile int edit_focus;
static volatile uint32_t name_entry_ms;

void front_note_name_entry(void)
{
    uint32_t t = port_now_ms();

    name_entry_ms = t ? t : 1;
}

int front_text_wanted(void) { return text_wanted_rule(port_now_ms(), name_entry_ms, edit_focus); }

static int hold_on, hold_mouse;           /* a press is being held before the next event: of a mouse button or of a key */
static uint32_t hold_t0;                  /* when it was delivered */
static int press_down, press_seen;        /* a mouse button is down (as delivered), and a screen's loop has seen it down */
static uint32_t press_id, press_t0;       /* the press's number (counts up) and when it began */
static uint32_t ui_pass_t;                /* when a screen's loop last passed 0x41f3ea; 0: never */
static double next_frame, last_compose;
static int quits;
static double first_quit;

/* A pass of a screen's loop (0x41f3ea outside the map) is starting. *id: the number of the latest mouse press (0: none yet), *held_ms: how long it has been down
 * (0 if it is up); returns whether it is down. front_ui_saw: the pass has the button down, so the press has been seen and may end. */
int front_ui_pass(uint32_t *id, uint32_t *held_ms)
{
    uint32_t now = port_now_ms();

    ui_pass_t = now ? now : 1;
    *id = press_id;
    *held_ms = press_down ? now - press_t0 : 0;
    return press_down;
}

void front_ui_saw(void) { press_seen = 1; }

static void deliver(const Ev *e)
{
    if (e->type == 0) {
        int ans = yesno_mouse(e->kind);

        if (ans < 0)                                     /* the release of a press that answered a yes/no question (yesno.c) */
            return;
        if (ans) {                                       /* a press that answers one: the key the game is waiting for, in place of the click */
            front_push_key(ans == 'y' ? 0x59 : 0x4E, ans == 'y' ? 0x15 : 0x31, 1, ans, 0);
            front_push_key(ans == 'y' ? 0x59 : 0x4E, ans == 'y' ? 0x15 : 0x31, 0, -1, 0);
            return;
        }
        wm_inject_mouse(e->kind, e->x, e->y);
        if (e->kind == IN_DOWN || e->kind == IN_RDOWN) {
            hold_on = hold_mouse = press_down = 1;
            hold_t0 = press_t0 = port_now_ms();
            press_id++;
            press_seen = 0;
        } else if (e->kind == IN_UP || e->kind == IN_RUP) {
            press_down = 0;
        }
    } else if (e->type == 1) {
        wm_inject_key(e->vk, e->sc, e->down, e->ch, e->repeat);
        if (e->down && !e->repeat) {
            hold_on = 1;
            hold_mouse = 0;
            hold_t0 = port_now_ms();
        }
    } else if (e->type == 4) {
        wm_inject_char(e->ch);
    } else if (e->type == 3) {
        uint32_t args[4];
        int i;

        for (i = 0; i < e->ncall; i++)
            args[i] = e->call[1 + i] == 0xFFFFFFF0u ? wm_main_hwnd() : e->call[1 + i];       /* the placeholder for "the main window" */
        sched_spawn_args(e->call[0], e->ncall, args);
    } else if (e->type == 5) {
        nav_serve(e);
    } else {
        /* the window's close button: the game sees WM_CLOSE as it would from Windows; a second request ends the program at once */
        if (quits++ == 0 && wm_main_hwnd()) {
            first_quit = port_now();
            wm_post(wm_main_hwnd(), WM_CLOSE, 0, 0);
        } else {
            fflush(NULL);
            exit(0);
        }
    }
}

void front_serve(double max_wait)
{
    Ev e;
    int got = 0;
    double now;

    if (finished)
        return;
    edit_focus = wm_text_focus();
    if (max_wait > 0) {
        pthread_mutex_lock(&qlock);
        if (qhead == qtail) {
            struct timespec ts;

            clock_gettime(CLOCK_REALTIME, &ts);
            ts.tv_nsec += (long)(max_wait * 1e9);
            ts.tv_sec += ts.tv_nsec / 1000000000L;
            ts.tv_nsec %= 1000000000L;
            pthread_cond_timedwait(&qcond, &qlock, &ts);
        }
        pthread_mutex_unlock(&qlock);
    }
    for (;;) {
        if (hold_on) {
            uint32_t t = port_now_ms();

            if (front_hold_rule(t - hold_t0, hold_mouse, press_seen, ui_pass_t && t - ui_pass_t <= UI_ACTIVE_MS))
                break;
            hold_on = 0;
        }
        pthread_mutex_lock(&qlock);
        if (qhead == qtail) {
            pthread_mutex_unlock(&qlock);
            break;
        }
        e = queue[qhead];
        qhead = (qhead + 1) % QCAP;
        pthread_mutex_unlock(&qlock);
        deliver(&e);
        got = 1;
    }
    if (quits == 1 && port_now() - first_quit > 5.0) {     /* the game did not end by itself */
        fflush(NULL);
        exit(0);
    }
    now = port_now();
    if (now >= next_frame) {
        next_frame = now + 1.0 / 30;
        nav_ready = navwm_mode() != NAVWM_NONE;
        if (got || wm_dirty || frame_n == 0 || now - last_compose >= 0.25) {
            static uint8_t scratch[SCREEN_MAX_W * SCREEN_MAX_H * 3];

            wm_dirty = 0;
            compose_screen(scratch);
            last_compose = now;
            pthread_mutex_lock(&flock);
            memcpy(frame, scratch, (size_t)screen_w * (size_t)screen_h * 3);
            frame_n++;
            pthread_mutex_unlock(&flock);
        }
    }
}

static void pump(void) { front_serve(0); }

static void (*chained_poll)(void);

/* Whenever the baton is about to pass (so also every few milliseconds while a thread spins), the host's events are served as well. */
static void poll(void)
{
    if (chained_poll)
        chained_poll();
    front_serve(0);
}

void front_install(void)
{
    chained_poll = sched_poll_hook;
    sched_poll_hook = poll;
    sched_idle_hook = front_serve;
    wm_pump_hook = pump;
}

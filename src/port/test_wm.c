/* test_wm.c - the window manager's behaviour, with host functions standing in for the game's window procedures (no game needed).
 *   make -C src/port test */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <ctype.h>
#include <strings.h>
#include <sys/stat.h>
#include <unistd.h>

#include "front.h"
#include "gdi.h"
#include "gdi_int.h"
#include "navwm.h"
#include "plat.h"
#include "sched.h"
#include "test_util.h"
#include "wm.h"
#include "winhelp.h"

extern char guest_cwd[260];
int wm_dialog_count(void);
uint32_t wm_top_dialog(void);
void kernel32_init(void);
void port_index_functions(void);

#define WM_USER_TEST 0x400
static uint32_t dlg_template, dlg_size;
static int failures, checks;
#define CHECK(c) do { checks++; if (!(c)) { failures++; printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

static uint32_t cursor = 0x1000000u;          /* guest memory the test carves structures from */
static uint32_t scratch(uint32_t n) { uint32_t p = cursor; cursor += (n + 15) & ~15u; return p; }
static uint32_t cstr(const char *s) { uint32_t p = scratch((uint32_t)strlen(s) + 1); strcpy((char *)(G + p), s); return p; }

/* call an API by name, as the guest would */
static uint32_t api(const char *name, uint32_t *args)
{
    static const WinApi *const tables[] = {USER32_APIS, CONTROLS_APIS, FILEDLG_APIS, WINHELP_APIS, MENUS_APIS, NULL};
    int t;
    const WinApi *p;

    for (t = 0; tables[t]; t++)
        for (p = tables[t]; p->name; p++)
            if (!strcmp(p->name, name))
                return p->fn(args);
    printf("no API %s\n", name);
    failures++;
    return 0;
}
#define API(n, ...) api(n, (uint32_t[12]){__VA_ARGS__})

/* a window procedure that logs the messages it gets */
static char log_[4096];
static int nlog;
static uint32_t proc_result = 0;
static void note(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
static void note(const char *fmt, ...)
{
    va_list ap;

    va_start(ap, fmt);
    nlog += vsnprintf(log_ + nlog, sizeof(log_) - (size_t)nlog, fmt, ap);
    va_end(ap);
}
static uint32_t wndproc(const uint32_t *a)
{
    switch (a[1]) {
    case WM_NCCREATE: note("NCCREATE "); return 1;
    case WM_NCCALCSIZE: note("NCCALCSIZE "); return 0;
    case WM_CREATE: note("CREATE "); return 0;
    case WM_SHOWWINDOW: note("SHOW "); return 0;
    case WM_SIZE: note("SIZE(%u,%u) ", a[3] & 0xFFFF, a[3] >> 16); return 0;
    case WM_MOVE: note("MOVE(%u,%u) ", a[3] & 0xFFFF, a[3] >> 16); return 0;
    case WM_ACTIVATE: note("ACTIVATE "); return 0;
    case WM_ACTIVATEAPP: note("ACTIVATEAPP "); return 0;
    case WM_SETFOCUS: note("FOCUS "); return 0;
    case WM_LBUTTONDOWN: note("LDOWN(%u,%u) ", a[3] & 0xFFFF, a[3] >> 16); return 0;
    case WM_LBUTTONDBLCLK: note("DBL "); return 0;
    case WM_TIMER: note("TIMER(%u) ", a[2]); return 0;
    case WM_COMMAND: note("COMMAND(%u) ", a[2]); return 0;
    case WM_USER_TEST: note("USER(%u,%u) ", a[2], a[3]); return proc_result;
    default: return 0;
    }
}

static uint32_t register_class(const char *name, uint32_t proc, uint32_t cbwnd, uint32_t style)
{
    uint32_t wc = scratch(40);

    WR32(wc, style); WR32(wc + 4, proc); WR32(wc + 8, 0); WR32(wc + 12, cbwnd); WR32(wc + 16, 0x400000); WR32(wc + 20, 0); WR32(wc + 24, 0);
    WR32(wc + 28, 0); WR32(wc + 32, 0); WR32(wc + 36, cstr(name));
    return API("RegisterClassA", wc);
}

static uint32_t create(const char *cls, uint32_t style, int x, int y, int w, int h, uint32_t parent, uint32_t id)
{
    return API("CreateWindowExA", 0, cstr(cls), cstr("t"), style, (uint32_t)x, (uint32_t)y, (uint32_t)w, (uint32_t)h, parent, id, 0x400000, 0);
}

static int log_is(const char *want) { int ok = !strcmp(log_, want); if (!ok) printf("  log is [%s], wanted [%s]\n", log_, want); return ok; }
static void log_clear(void) { log_[0] = 0; nlog = 0; }

static uint32_t sender_hwnd, sender_result;
static int sender_done;
static uint32_t sender_thread(const uint32_t *a)
{
    (void)a;
    sender_result = API("SendMessageA", sender_hwnd, WM_USER_TEST, 7, 8);
    sender_done = 1;
    return 0;
}

static void test_creation_and_show(void)
{
    uint32_t proc = port_host_function(wndproc), top, child;

    CHECK(register_class("TestClass", proc, 8, 0) >= 0xC000);
    top = create("TestClass", WS_VISIBLE, 10, 20, 300, 200, 0, 0);
    CHECK(top != 0);
    CHECK(log_is("NCCREATE NCCALCSIZE CREATE SHOW ACTIVATEAPP ACTIVATE FOCUS SIZE(300,200) MOVE(10,20) "));
    log_clear();
    child = create("testclass", WS_CHILD, 5, 6, 50, 40, top, 99);        /* class names match without regard to case */
    CHECK(child != 0);
    CHECK(log_is("NCCREATE NCCALCSIZE CREATE SIZE(50,40) MOVE(5,6) "));
    CHECK(API("GetParent", child) == top);
    CHECK(API("GetDlgCtrlID", child) == 99);
    CHECK(API("IsWindowVisible", child) == 0);
    log_clear();
    API("ShowWindow", child, 1);
    CHECK(log_is("SHOW "));                                            /* a child gets no activation or size messages from ShowWindow */
    CHECK(API("IsWindowVisible", child) == 1);
    log_clear();
    API("ShowWindow", child, 5);
    CHECK(log_is(""));                                                 /* already visible: nothing to tell */
    API("ShowWindow", child, 0);
    CHECK(log_is("SHOW "));                                            /* hiding a visible window sends WM_SHOWWINDOW(0) as well */
    CHECK(API("IsWindowVisible", child) == 0);
    log_clear();
    API("ShowWindow", child, 0);
    CHECK(log_is(""));                                                 /* already hidden: nothing to tell */
}

static void test_geometry_and_state(void)
{
    uint32_t top = create("TestClass", 0, 100, 50, 200, 100, 0, 0), kid = create("TestClass", WS_CHILD, 10, 5, 30, 20, top, 1), rect = scratch(16), pt = scratch(8);

    API("GetWindowRect", kid, rect);
    CHECK(RD32(rect) == 110 && RD32(rect + 4) == 55 && RD32(rect + 8) == 140 && RD32(rect + 12) == 75);     /* screen coordinates */
    API("GetClientRect", kid, rect);
    CHECK(RD32(rect + 8) == 30 && RD32(rect + 12) == 20);
    WR32(pt, 3); WR32(pt + 4, 4);
    API("ClientToScreen", kid, pt);
    CHECK(RD32(pt) == 113 && RD32(pt + 4) == 59);
    API("ScreenToClient", kid, pt);
    CHECK(RD32(pt) == 3 && RD32(pt + 4) == 4);
    log_clear();
    API("MoveWindow", kid, 20, 5, 40, 20, 1);
    CHECK(log_is("SIZE(40,20) MOVE(20,5) "));
    /* the extra bytes the class asked for: byte offsets, as a long or a word */
    CHECK(API("SetWindowLongA", kid, 0, 0xDEADBEEF) == 0);
    CHECK(API("GetWindowLongA", kid, 0) == 0xDEADBEEF);
    CHECK(API("GetWindowWord", kid, 0) == 0xBEEF);
    CHECK(API("SetWindowLongA", kid, (uint32_t)-21, 0x1234) == 0 && API("GetWindowLongA", kid, (uint32_t)-21) == 0x1234);
    CHECK(API("GetWindowLongA", kid, 100) == 0);                       /* outside the extra bytes */
}

static void test_z_order(void)
{
    uint32_t top = create("TestClass", 0, 0, 0, 100, 100, 0, 0), a = create("TestClass", WS_CHILD, 0, 0, 10, 10, top, 1),
             b = create("TestClass", WS_CHILD, 0, 0, 10, 10, top, 2), c = create("TestClass", WS_CHILD, 0, 0, 10, 10, top, 3);

    CHECK(API("GetTopWindow", top) == c);
    CHECK(API("GetWindow", c, 2) == b && API("GetWindow", b, 2) == a && API("GetWindow", a, 2) == 0);          /* GW_HWNDNEXT goes down */
    API("BringWindowToTop", a);
    CHECK(API("GetTopWindow", top) == a);
    API("SetWindowPos", a, 1, 0, 0, 0, 0, 3);                         /* HWND_BOTTOM, SWP_NOSIZE | SWP_NOMOVE */
    CHECK(API("GetTopWindow", top) == c && API("GetWindow", a, 1) == a);
    API("SetWindowPos", c, b, 0, 0, 0, 0, 3);                         /* directly below b */
    CHECK(API("GetTopWindow", top) == b && API("GetWindow", b, 2) == c);
}

static void test_queue_and_dispatch(void)
{
    uint32_t top = create("TestClass", 0, 0, 0, 100, 100, 0, 0), msg = scratch(28);

    log_clear();
    API("PostMessageA", top, WM_USER_TEST, 1, 2);
    API("PostMessageA", top, WM_USER_TEST, 3, 4);
    CHECK(API("PeekMessageA", msg, 0, 0, 0, 0) == 1);                   /* no PM_REMOVE: it stays */
    CHECK(RD32(msg) == top && RD32(msg + 4) == WM_USER_TEST && RD32(msg + 8) == 1);
    CHECK(API("PeekMessageA", msg, 0, 0, 0, 1) == 1 && RD32(msg + 8) == 1);
    CHECK(API("GetMessageA", msg, 0, 0, 0) == 1 && RD32(msg + 8) == 3);
    API("DispatchMessageA", msg);
    CHECK(log_is("USER(3,4) "));
    /* a window invalid and visible gets a WM_PAINT from the pump, once */
    API("ShowWindow", top, 1);
    API("UpdateWindow", top);
    log_clear();
    API("InvalidateRect", top, 0, 1);
    {
        int paints = 0, i;

        for (i = 0; i < 40; i++)
            if (API("PeekMessageA", msg, 0, 0, 0, 1) && RD32(msg + 4) == WM_PAINT && RD32(msg) == top)
                paints++;
        CHECK(paints == 1);
    }
    /* no WM_PAINT for a window with an empty client area (the game's hidden opponent hand is zero-size card windows; their paint cached every art at 1x2 pixels); it paints once it has room */
    {
        uint32_t z = create("TestClass", WS_VISIBLE | WS_POPUP, 5, 5, 0, 0, 0, 0);
        int paints = 0, i;

        API("InvalidateRect", z, 0, 1);
        for (i = 0; i < 40; i++)
            if (API("PeekMessageA", msg, 0, 0, 0, 1) && RD32(msg + 4) == WM_PAINT && RD32(msg) == z)
                paints++;
        CHECK(paints == 0);
        API("UpdateWindow", z);
        API("MoveWindow", z, 5, 5, 30, 30, 0);
        API("InvalidateRect", z, 0, 1);
        for (i = 0; i < 40; i++)
            if (API("PeekMessageA", msg, 0, 0, 0, 1) && RD32(msg + 4) == WM_PAINT && RD32(msg) == z)
                paints++;
        CHECK(paints == 1);
    }
    /* PostQuitMessage makes the next GetMessage return 0 with WM_QUIT, once */
    API("PostQuitMessage", 5);
    CHECK(API("GetMessageA", msg, 0, 0, 0) == 0 && RD32(msg + 4) == WM_QUIT && RD32(msg + 8) == 5);
}

/* A window that draws in WM_ERASEBKGND and answers WM_PAINT without ever calling DefWindowProc (STATWIN.DLL's window: it was black). Windows
 * sends WM_ERASEBKGND ahead of the WM_PAINT that the pump hands out for a window marked for erasing, once, whatever the procedure then does. */
static uint32_t eraseproc(const uint32_t *a)
{
    if (a[1] == WM_ERASEBKGND)
        note("ERASE ");
    return a[1] == WM_NCCREATE;
}

static void test_erase_before_paint(void)
{
    uint32_t top, msg = scratch(28);
    int i, paints = 0;

    register_class("EraseClass", port_host_function(eraseproc), 0, 0);
    top = create("EraseClass", 0, 0, 0, 100, 100, 0, 0);
    log_clear();
    API("ShowWindow", top, 1);
    for (i = 0; i < 40; i++)
        if (API("PeekMessageA", msg, 0, 0, 0, 1) && RD32(msg + 4) == WM_PAINT && RD32(msg) == top)
            paints++;
    CHECK(paints == 1 && log_is("ERASE "));                         /* a window just shown is erased, then painted */
    log_clear();
    API("InvalidateRect", top, 0, 0);                                /* no erase asked for: only the paint */
    for (i = 0; i < 40; i++)
        if (API("PeekMessageA", msg, 0, 0, 0, 1) && RD32(msg + 4) == WM_PAINT && RD32(msg) == top)
            paints++;
    CHECK(paints == 2 && log_is(""));
    API("InvalidateRect", top, 0, 1);
    for (i = 0; i < 40; i++)
        if (API("PeekMessageA", msg, 0, 0, 0, 1) && RD32(msg + 4) == WM_PAINT && RD32(msg) == top)
            paints++;
    CHECK(paints == 3 && log_is("ERASE "));
}

/* "Sorcerer casts...": a child window whose WM_ERASEBKGND answers 1 without drawing (the BigCardChoice window; it draws its text in WM_PAINT) is see-through:
 * the parent's picture shows where the child drew nothing. A window that erases by drawing (even to black) is opaque. */
static uint32_t paint_idx(const uint32_t *a, uint8_t idx, int erase_draws)
{
    Window *w = wm_window(a[0]);
    Surface *sf = w ? (Surface *)w->surface : NULL;

    if (sf && a[1] == WM_ERASEBKGND) {
        if (erase_draws) {
            dc_of(a[2]);                                          /* what FillRect does first */
            memset(sf->idx, idx, (size_t)sf->w * (size_t)sf->h);
        }
        return 1;
    }
    if (sf && a[1] == WM_PAINT && idx) {
        sf->idx[5 * (size_t)sf->w + 5] = idx;                    /* "text": one pixel */
        sf->touched[5 * (size_t)sf->w + 5] = 1;
    }
    return a[1] == WM_NCCREATE;
}
static uint32_t parentproc(const uint32_t *a) { return paint_idx(a, 7, 1); }
static uint32_t ghostproc(const uint32_t *a) { return paint_idx(a, 9, 0); }
static uint32_t solidproc(const uint32_t *a) { return paint_idx(a, 0, 1); }

static void pump_paints(uint32_t hwnd)
{
    uint32_t msg = scratch(28);
    int i;

    for (i = 0; i < 40; i++)
        if (API("PeekMessageA", msg, 0, 0, 0, 1) && RD32(msg + 4) == WM_PAINT && RD32(msg) == hwnd)
            return;
}

static void test_see_through_child(void)
{
    uint32_t top, ghost, solid;
    uint8_t *rgb = malloc((size_t)640 * 480 * 3), under[3];
    Window *tw;
    int sw = screen_w, sh = screen_h;

    screen_w = 640; screen_h = 480;
    register_class("SeeParent", port_host_function(parentproc), 0, 0);
    register_class("SeeGhost", port_host_function(ghostproc), 0, 0);
    register_class("SeeSolid", port_host_function(solidproc), 0, 0);
    top = create("SeeParent", 0, 0, 0, 100, 100, 0, 0);
    ghost = create("SeeGhost", WS_CHILD, 10, 10, 20, 20, top, 1);
    solid = create("SeeSolid", WS_CHILD, 50, 10, 20, 20, top, 2);
    API("ShowWindow", top, 1);
    API("ShowWindow", ghost, 1);
    API("ShowWindow", solid, 1);
    tw = wm_window(top);
    CHECK(tw != NULL);
    API("InvalidateRect", ghost, 0, 1);
    API("InvalidateRect", solid, 0, 1);
    pump_paints(top); pump_paints(ghost); pump_paints(solid);
    API("SendMessageA", ghost, WM_PAINT, 0, 0);                    /* the pump only hands the message out: deliver it */
    CHECK(wm_window(ghost)->see_through == 1);                  /* answered "erased" and never touched its DC */
    CHECK(wm_window(solid)->see_through == 0);                     /* erased by drawing (black) */
    compose_screen(rgb);
    surface_rgb((Surface *)tw->surface, 0, 0, 1, 1, under);       /* the parent's colour (index 7) */
    {
        int ox = tw->x + tw->nc_l, oy = tw->y + tw->nc_t;
        const uint8_t *g_empty = rgb + 3 * ((size_t)(oy + 10 + 10) * 640 + (size_t)(ox + 10 + 10)), *g_text = rgb + 3 * ((size_t)(oy + 10 + 5) * 640 + (size_t)(ox + 10 + 5)),
                      *s_empty = rgb + 3 * ((size_t)(oy + 10 + 10) * 640 + (size_t)(ox + 50 + 10));

        CHECK(!memcmp(g_empty, under, 3));                         /* the parent shows through the ghost */
        CHECK(memcmp(g_text, under, 3) != 0);                      /* its one pixel of text is on top */
        CHECK(memcmp(s_empty, under, 3) != 0);                     /* the solid window covers the parent with black */
    }
    free(rgb);
    screen_w = sw; screen_h = sh;
}

static void test_timers(void)
{
    uint32_t top = create("TestClass", 0, 0, 0, 100, 100, 0, 0), msg = scratch(28);
    int i, ticks = 0;

    CHECK(API("SetTimer", top, 7, 5, 0) == 7);
    for (i = 0; i < 40 && !ticks; i++) {
        sched_sleep(0.002);
        if (API("PeekMessageA", msg, 0, 0, 0, 1) && RD32(msg + 4) == WM_TIMER && RD32(msg + 8) == 7)
            ticks++;
    }
    CHECK(ticks == 1);
    API("KillTimer", top, 7);
    sched_sleep(0.02);
    for (i = 0; i < 4; i++)
        CHECK(!(API("PeekMessageA", msg, 0, 0, 0, 1) && RD32(msg + 4) == WM_TIMER));
}

static void test_cross_thread_send(void)
{
    uint32_t top = create("TestClass", 0, 0, 0, 100, 100, 0, 0), msg = scratch(28);
    int i;

    log_clear();
    proc_result = 0x77;
    sender_hwnd = top;
    sender_done = 0;
    sched_spawn(port_host_function(sender_thread), 0, 0);
    for (i = 0; i < 200 && !sender_done; i++) {            /* the owner pumps; the sender waits for its reply */
        API("PeekMessageA", msg, 0, 0, 0, 1);
        sched_sleep(0.001);
    }
    CHECK(sender_done && sender_result == 0x77);
    CHECK(log_is("USER(7,8) "));
    proc_result = 0;
}

/* A thread that lives a long time and short ones that come and go (the game's timer callbacks) never share a stack. */
static volatile uint32_t long_sp, short_sp_clash, long_stop, shorts_run;

static uint32_t long_thread(const uint32_t *a)
{
    (void)a;
    long_sp = port_sp;
    while (!long_stop)
        sched_sleep(0.001);
    return 0;
}

static uint32_t short_thread(const uint32_t *a)
{
    (void)a;
    if ((port_sp >> 20) == (long_sp >> 20))
        short_sp_clash++;
    shorts_run++;
    return 0;
}

static void test_thread_stacks(void)
{
    int i;
    uint32_t short_fn = port_host_function(short_thread);

    sched_spawn(port_host_function(long_thread), 0, 0);
    while (!long_sp)
        sched_sleep(0.001);
    for (i = 0; i < 300; i++) {
        sched_spawn(short_fn, 0, 0);
        sched_sleep(0.0005);
    }
    for (i = 0; i < 100 && shorts_run < 300; i++)
        sched_sleep(0.005);
    CHECK(shorts_run == 300);
    CHECK(short_sp_clash == 0);
    long_stop = 1;
    sched_sleep(0.01);
}

/* The library the host provides in place of MAGSND.DLL: found by name or ordinal, cdecl, answers through the pointer. */
static void test_host_module(void)
{
    uint32_t h, state = scratch(4), args = scratch(16), cleanup = 0, f;

    sound_install();
    h = module_load("C:\\Magic\\Program\\MAGSND.DLL");
    CHECK(h != 0 && h == module_find("magsnd"));
    CHECK(module_proc(h, "NoSuchExport") == 0);
    f = module_proc(h, "#22");                                  /* GetSndState(id, *state) */
    CHECK(f != 0 && f == module_proc(h, "GetSndState"));
    WR32(state, 99);
    WR32(args, 5);
    WR32(args + 4, state);
    CHECK(lift_call(f, args, &cleanup) == 0);
    CHECK(RD32(state) == 0 && cleanup == 0);                   /* stopped; the caller pops the arguments */
    CHECK(module_load("nothing.dll") == 0);
}

/* PeekMessage's range of wanted messages: the game asks for a double click (0x203) only and must not be handed the button-up that is queued. */
static void test_message_range(void)
{
    uint32_t top = create("TestClass", WS_VISIBLE | WS_POPUP, 0, 0, 50, 50, 0, 0), msg = scratch(28);
    int i;

    for (i = 0; i < 20; i++)
        API("PeekMessageA", msg, 0, 0, 0, 1);                      /* the window's start-up messages */
    wm_post(top, WM_LBUTTONUP, 0, 5);
    CHECK(API("PeekMessageA", msg, top, 0x203, 0x203, 0) == 0);    /* not there: only a button-up is queued */
    CHECK(API("PeekMessageA", msg, top, 0x200, 0x202, 0) == 1 && RD32(msg + 4) == WM_LBUTTONUP);
    wm_post(top, WM_LBUTTONDBLCLK, 0, 5);
    CHECK(API("PeekMessageA", msg, top, 0x203, 0x203, 1) == 1 && RD32(msg + 4) == WM_LBUTTONDBLCLK);
    CHECK(API("PeekMessageA", msg, top, 0x203, 0x203, 1) == 0);
    CHECK(API("PeekMessageA", msg, top, 0, 0, 1) == 1 && RD32(msg + 4) == WM_LBUTTONUP);     /* no range: everything */
}

/* WindowFromPoint takes the point as two words and finds the child under it, not just the top-level window. */
static void test_window_from_point(void)
{
    uint32_t top = create("TestClass", WS_VISIBLE | WS_POPUP, 400, 300, 100, 100, 0, 0), kid = create("TestClass", WS_CHILD | WS_VISIBLE, 10, 10, 40, 40, top, 3);

    CHECK(API("WindowFromPoint", 420, 320) == kid);
    CHECK(API("WindowFromPoint", 480, 390) == top);
}

static void test_input(void)
{
    uint32_t top = create("TestClass", WS_VISIBLE | WS_POPUP, 0, 0, 200, 200, 0, 0), kid = create("TestClass", WS_CHILD | WS_VISIBLE, 50, 60, 40, 40, top, 1);
    uint32_t msg = scratch(28);
    int i, got = 0;

    log_clear();
    CHECK(wm_inject_mouse(IN_DOWN, 60, 70) == 1);              /* inside the child: client coordinates (10,10) */
    for (i = 0; i < 8 && !got; i++)
        if (API("PeekMessageA", msg, 0, 0, 0, 1) && RD32(msg + 4) == WM_LBUTTONDOWN) {
            CHECK(RD32(msg) == kid);
            CHECK(RD32(msg + 12) == (10u | (10u << 16)));
            got = 1;
        }
    CHECK(got);
    CHECK(API("GetKeyState", 1) != 0);
    wm_inject_mouse(IN_UP, 60, 70);
    CHECK(API("GetKeyState", 1) == 0);
    /* a second press at the same place within the double-click time is a double click for a class with CS_DBLCLKS */
    {
        uint32_t proc = port_host_function(wndproc), dbl, w;

        register_class("DblClass", proc, 0, 8);
        dbl = create("DblClass", WS_VISIBLE | WS_POPUP, 300, 300, 50, 50, 0, 0);
        w = dbl;
        wm_inject_mouse(IN_DOWN, 310, 310);
        wm_inject_mouse(IN_UP, 310, 310);
        wm_inject_mouse(IN_DOWN, 311, 310);
        got = 0;
        for (i = 0; i < 30; i++)
            if (API("PeekMessageA", msg, 0, 0, 0, 1) && RD32(msg + 4) == WM_LBUTTONDBLCLK && RD32(msg) == w)
                got = 1;
        CHECK(got);
    }
}

/* The front end's guest half: events queued from another thread arrive as input, a pressed button stays down for a while before the next
 * event, and a frame is published. */
static void test_front(void)
{
    uint32_t top = create("TestClass", WS_VISIBLE | WS_POPUP, 0, 0, 100, 100, 0, 0);
    uint8_t *rgb = malloc((size_t)640 * 480 * 3);
    unsigned seen = 0;

    (void)top;
    front_push_mouse(IN_DOWN, 20, 20);
    front_push_mouse(IN_UP, 20, 20);
    front_push_key(0x41, 0x1E, 1, 'a', 0);
    front_serve(0);
    CHECK(API("GetKeyState", 1) != 0);                     /* the press was delivered; the release waits */
    CHECK(wm_keys[0x41] == 0);
    usleep(100000);
    front_serve(0);
    CHECK(API("GetKeyState", 1) == 0);
    CHECK(wm_keys[0x41] == 1);
    front_push_key(0x41, 0x1E, 0, -1, 0);
    usleep(100000);
    front_serve(0);
    CHECK(wm_keys[0x41] == 0);
    CHECK(front_take_frame(rgb, &seen) == 1);              /* a frame was composed; no newer one yet */
    CHECK(front_take_frame(rgb, &seen) == 0);
    free(rgb);
}

/* The SDL window for a screen of the program's size: the screen itself when the display holds it, else smaller with the same shape (the mouse is mapped back by SDL's logical size). */
static void test_window_fit(void)
{
    int w, h, sw = screen_w, sh = screen_h;

    window_size_for(1024, 768, 2560, 1440, &w, &h);               /* a big display: the screen's size */
    CHECK(w == 1024 && h == 768);
    window_size_for(1024, 768, 1440, 877, &w, &h);                /* a 13" MacBook (1440x900 less the menu bar and Dock): 768 <= 877 - 56, fits as it is */
    CHECK(w == 1024 && h == 768);
    window_size_for(1024, 768, 1366, 728, &w, &h);                /* a 1366x768 laptop less a taskbar: 672 high at most, so smaller, 4:3 */
    CHECK(h <= 728 - 56 && w <= 1366 - 16 && w * 3 - h * 4 < 4 && h * 4 - w * 3 < 4);
    window_size_for(640, 480, 1366, 728, &w, &h);                 /* the original's size fits there */
    CHECK(w == 640 && h == 480);
    window_size_for(1024, 768, 800, 600, &w, &h);                 /* a tiny display: 4:3 of what is left, not below a quarter */
    CHECK(w <= 784 && h <= 544 && w >= 256 && h >= 192);
    window_size_for(1024, 768, 0, 0, &w, &h);                     /* the display is not known: the screen's size */
    CHECK(w == 1024 && h == 768);
    screen_set(1024, 768);                                        /* the sizes the game has layouts for are accepted, odd ones are not */
    CHECK(screen_w == 1024 && screen_h == 768);
    screen_set(800, 600);
    CHECK(screen_w == 800 && screen_h == 600);
    screen_set(300, 200);
    CHECK(screen_w == 800 && screen_h == 600);
    screen_set(sw, sh);
}

/* The hold on a mouse press: a click is one pass of a screen's loop. The press ends when a pass has seen it down, not after a fixed time. */
static void test_front_press(void)
{
    uint32_t top = create("TestClass", WS_VISIBLE | WS_POPUP, 0, 0, 100, 100, 0, 0), id, held;

    (void)top;
    /* the rule: a key waits 70 ms; a button no screen's loop looks at waits 70 ms; a seen button does not wait; a screen that is running but has not seen it waits up to 250 ms */
    CHECK(front_hold_rule(10, 0, 0, 0) == 1 && front_hold_rule(70, 0, 0, 1) == 0);
    CHECK(front_hold_rule(10, 1, 0, 0) == 1 && front_hold_rule(69, 1, 0, 0) == 1 && front_hold_rule(70, 1, 0, 0) == 0);
    CHECK(front_hold_rule(0, 1, 1, 1) == 0 && front_hold_rule(30, 1, 1, 0) == 0);
    CHECK(front_hold_rule(70, 1, 0, 1) == 1 && front_hold_rule(249, 1, 0, 1) == 1 && front_hold_rule(250, 1, 0, 1) == 0);
    /* a click (a press and release queued together): the release waits while no pass has seen the press, and comes at once when one has */
    usleep(100000);
    front_serve(0);                                        /* whatever an earlier test left */
    front_push_mouse(IN_DOWN, 20, 20);
    front_push_mouse(IN_UP, 20, 20);
    front_serve(0);
    CHECK(API("GetKeyState", 1) != 0);
    CHECK(front_ui_pass(&id, &held) == 1 && id > 0 && held < 70);      /* a pass of a screen's loop: the press is down, and a new one */
    front_serve(0);
    CHECK(API("GetKeyState", 1) != 0);                     /* seen by nobody yet: still held (a screen's loop is running, up to 250 ms) */
    front_ui_saw();
    front_serve(0);
    CHECK(API("GetKeyState", 1) == 0);                     /* a pass saw it: the release came at once, well before 70 ms */
    CHECK(front_ui_pass(&id, &held) == 0 && held == 0);    /* the press is over */
    front_push_mouse(IN_DOWN, 20, 20);                     /* the next press is a new one */
    front_serve(0);
    {
        uint32_t id2, held2;

        front_ui_pass(&id2, &held2);
        CHECK(id2 == id + 1);
    }
    front_push_mouse(IN_UP, 20, 20);
    usleep(300000);                                        /* nobody saw it: the release comes by itself */
    front_serve(0);
    CHECK(API("GetKeyState", 1) == 0);
}

static void test_controls(void)
{
    uint32_t top = create("TestClass", 0, 0, 0, 100, 100, 0, 0), list = create("LISTBOX", WS_CHILD | 0x2, 0, 0, 50, 50, top, 5), buf = scratch(32);

    CHECK(list != 0);
    CHECK(API("SendMessageA", list, 0x180, 0, cstr("pear")) == 0);          /* LB_ADDSTRING; the list is sorted (LBS_SORT) */
    CHECK(API("SendMessageA", list, 0x180, 0, cstr("apple")) == 0);
    CHECK(API("SendMessageA", list, 0x180, 0, cstr("zebra")) == 2);
    CHECK(API("SendMessageA", list, 0x18B, 0, 0) == 3);                     /* LB_GETCOUNT */
    API("SendMessageA", list, 0x189, 1, buf);                               /* LB_GETTEXT */
    CHECK(!strcmp((char *)(G + buf), "pear"));
    CHECK(API("SendMessageA", list, 0x186, 2, 0) == 2 && API("SendMessageA", list, 0x188, 0, 0) == 2);      /* SETCURSEL, GETCURSEL */
    CHECK(API("SendMessageA", list, 0x182, 0, 0) == 2);                      /* LB_DELETESTRING */
    CHECK(API("SendMessageA", list, 0x18F, (uint32_t)-1, cstr("ze")) == 1);  /* LB_FINDSTRING */
    API("SetScrollRange", top, 1, 0, 10, 1);
    CHECK(API("SetScrollPos", top, 1, 50, 1) == 0 && API("GetScrollPos", top, 1) == 10);         /* clamped to the range */
}

static void test_rects(void)
{
    uint32_t r = scratch(16), q = scratch(16), u = scratch(16);

    API("SetRect", r, 1, 2, 11, 12);
    API("OffsetRect", r, 10, 20);
    CHECK(RD32(r) == 11 && RD32(r + 4) == 22 && RD32(r + 8) == 21 && RD32(r + 12) == 32);
    API("InflateRect", r, 1, 1);
    CHECK(RD32(r) == 10 && RD32(r + 12) == 33);
    CHECK(API("PtInRect", r, 10, 21) == 1 && API("PtInRect", r, 22, 21) == 0);                 /* the right edge is outside */
    CHECK(API("IsRectEmpty", r) == 0);
    API("SetRect", q, 0, 0, 5, 5);
    API("UnionRect", u, r, q);
    CHECK(RD32(u) == 0 && RD32(u + 4) == 0 && RD32(u + 8) == 22 && RD32(u + 12) == 33);
    API("SetRect", q, 5, 5, 30, 30);
    CHECK(API("IntersectRect", u, r, q) == 1 && RD32(u) == 10 && RD32(u + 4) == 21 && RD32(u + 8) == 22 && RD32(u + 12) == 30);
    API("SetRect", q, 100, 100, 110, 110);
    CHECK(API("IntersectRect", u, r, q) == 0 && RD32(u) == 0 && RD32(u + 8) == 0);          /* no overlap: an empty result */
    CHECK(API("EqualRect", r, r) == 1 && API("EqualRect", r, q) == 0);
    API("SetRectEmpty", u);
    CHECK(API("IsRectEmpty", u) == 1);
    CHECK(API("GetSysColor", 15) == 0xC0C0C0 && API("GetSysColor", 13) == 0x800000 && API("GetSysColor", 99) == 0);   /* button face; highlight is navy (BGR) */
}

/* A key goes to the window with the keyboard focus (the last top-level window shown), not to the first top-level window: the duel's window pump
 * is on another thread than the first window's, and Esc/Enter in the prompt bar have to reach it. */
static void test_key_target(void)
{
    uint32_t w2, msg = scratch(28), got = 0;
    int i;

    w2 = create("TestClass", WS_VISIBLE, 0, 0, 100, 100, 0, 0);
    CHECK(w2 != 0);
    CHECK(wm_key_target() == w2);
    for (i = 0; i < 1000 && API("PeekMessageA", msg, 0, 0, 0, 1); i++)  /* what earlier tests left in the queue */
        ;
    wm_inject_key(0x1B, 0x01, 1, 0x1B, 0);
    for (i = 0; i < 400 && !got; i++)
        if (API("PeekMessageA", msg, 0, 0, 0, 1) && RD32(msg + 4) == WM_CHAR)
            got = RD32(msg);
    CHECK(got == w2);
    API("DestroyWindow", w2);
    CHECK(wm_key_target() != w2);                                        /* a destroyed focus window falls back to a top-level one */
}

/* ---- a dialog from a template, and a popup menu the host picks from ---------------------------------------------------------------- */
int wm_press_dialog_button(uint32_t id);
int wm_popup_open(void);

static uint32_t put16(uint32_t at, uint32_t v) { WR16(at, v); return at + 2; }
static uint32_t put32(uint32_t at, uint32_t v) { WR32(at, v); return at + 4; }
static uint32_t putwide(uint32_t at, const char *s) { do { at = put16(at, (uint8_t)*s); } while (*s++); return at; }

static int keydlg;      /* 1: the dialog under test has no OK or Cancel: Enter has to reach it as a character */

static uint32_t dlgproc(const uint32_t *a)
{
    if (keydlg) {
        if (a[1] == WM_INITDIALOG) {
            wm_inject_key(0x0D, 0x1C, 1, 0x0D, 0);
            return 1;
        }
        if (a[1] == WM_CHAR) {
            note("CHAR(%u) ", a[2]);
            API("EndDialog", a[0], 7);
            return 1;
        }
        return 0;
    }
    if (a[1] == WM_INITDIALOG) {
        note("INIT(first=%u) ", a[2]);
        {   /* the template's units are the font's: 100 x 80 dialog units, and a caption and a dialog frame take 3 pixels on each side, 22 above and 3 below */
            Window *d = wm_window(a[0]), *ok = wm_dlg_item(a[0], 1);
            int cw, ch, ox, oy, avg = 6, height = 13;

            ui_font_metrics("Tahoma", 8, 0, &height, NULL, &avg);
            wm_client_size(d, &cw, &ch);
            CHECK(cw == ui_dlu_x(100, avg) && ch == ui_dlu_y(80, height));
            CHECK(d->w == cw + 6 && d->h == ch + 22 + 3);
            CHECK(ok && ok->x == ui_dlu_x(10, avg) && ok->y == ui_dlu_y(20, height) && ok->w == ui_dlu_x(30, avg));
            wm_client_origin(d, &ox, &oy);
            CHECK(ox == d->x + 3 && oy == d->y + 22);
            /* DS_SETFONT: every control has the dialog's font (the game's own button painting asks WM_GETFONT for it), and it is the same one */
            CHECK(ok->hfont && API("SendMessageA", ok->hwnd, 0x31, 0, 0) == ok->hfont && d->hfont == ok->hfont);
        }
        {   /* the D-pad's targets in a dialog: its enabled push buttons (the list box has no rows), found in the window tree */
            NavTarget nt[16];
            int cur, n = navwm_collect(nt, 16, 0, 0, &cur), i, found = 0;
            Window *ok = wm_dlg_item(a[0], 1);
            int ox0, oy0, ox1, oy1;

            wm_abs_rect(ok, &ox0, &oy0, &ox1, &oy1);
            CHECK(navwm_mode() == NAVWM_DIALOG);
            for (i = 0; i < n; i++)
                found += nt[i].id == ok->hwnd && nt[i].kind == NAVK_BUTTON && nt[i].x0 == ox0 && nt[i].y0 == oy0 && nt[i].x1 == ox1 && nt[i].y1 == oy1;
            CHECK(found == 1);
        }
        wm_press_dialog_button(1);
        return 1;
    }
    if (a[1] == WM_COMMAND && a[2] == 1) {
        note("OK ");
        API("EndDialog", a[0], 42);
        return 1;
    }
    return 0;
}

/* The dialog base unit and the conversion of a template's numbers, as the real Windows 98 setup dialog of DUEL.EXE shows them (docs/notes/dialogs.md): its Benguiat
 * Bk BT 10 point font is 8 x 15 pixels per unit, the dialog 281 x 213 units is 562 x 399 pixels inside its one-pixel border, and its combo boxes at 82 and 139 units
 * down are 154 and 261 pixels down: units round to the nearest pixel, they do not truncate. */
static void test_dialog_units(void)
{
    int height = 0, avg = 0;

    CHECK(ui_dlu_x(281, 8) == 562 && ui_dlu_y(213, 15) == 399);
    CHECK(ui_dlu_y(82, 15) == 154 && ui_dlu_y(139, 15) == 261 && ui_dlu_y(83, 15) == 156 && ui_dlu_y(20, 15) == 38);
    CHECK(ui_dlu_x(73, 8) == 146 && ui_dlu_x(51, 6) == 77 && ui_dlu_x(50, 6) == 75 && ui_dlu_y(14, 13) == 23);   /* an OK button of 50 x 14 units in MS Sans Serif 8 is 75 x 23 */
    CHECK(ui_dlu_x(-3, 6) == -5 && ui_dlu_y(0, 13) == 0);
    /* a font's height in pixels is MulDiv(points, 96, 72): 10 points is 13 pixels, not 13.33 */
    CHECK(ui_pixel_size(8) == 11 && ui_pixel_size(10) == 13 && ui_pixel_size(12) == 16 && ui_pixel_size(16) == 21);
    /* MS Sans Serif at 8 points, which this machine has no file for: Windows 98's 6 x 13 */
    ui_font_metrics("MS Sans Serif", 8, 0, &height, NULL, &avg);
    CHECK(height == 13 && avg == 6);
}

/* A popup window's parent is its owner: its position is on the screen, not inside the owner's client area (the dialog opened over the game's window sat one pixel off). */
static void test_popup_position(void)
{
    uint32_t owner = create("TestClass", WS_VISIBLE, 7, 9, 300, 200, 0, 0), pop = create("TestClass", WS_POPUP | WS_VISIBLE, 40, 50, 100, 80, owner, 0),
             kid = create("TestClass", WS_CHILD | WS_VISIBLE, 3, 4, 10, 10, pop, 1), rect = scratch(16);

    API("GetWindowRect", pop, rect);
    CHECK(RD32(rect) == 40 && RD32(rect + 4) == 50);
    API("GetWindowRect", kid, rect);
    CHECK(RD32(rect) == 43 && RD32(rect + 4) == 54);
}

static void test_dialog(void)
{
    uint32_t t = scratch(256), o = t, r;

    o = put32(o, 0x80C80000u | 0x40);             /* style: with DS_SETFONT */
    o = put32(o, 0); o = put16(o, 2);              /* extended style, two controls */
    o = put16(o, 5); o = put16(o, 5); o = put16(o, 100); o = put16(o, 80);
    o = put16(o, 0); o = put16(o, 0);              /* no menu, default class */
    o = putwide(o, "Dlg");
    o = put16(o, 8); o = putwide(o, "Tahoma");        /* DS_SETFONT: size and face */
    o = (o + 3) & ~3u;
    o = put32(o, WS_CHILD | WS_VISIBLE | WS_TABSTOP); o = put32(o, 0);
    o = put16(o, 10); o = put16(o, 20); o = put16(o, 30); o = put16(o, 12); o = put16(o, 1);
    o = put16(o, 0xFFFF); o = put16(o, 0x0080); o = putwide(o, "OK"); o = put16(o, 0);
    o = (o + 3) & ~3u;
    o = put32(o, WS_CHILD | WS_VISIBLE); o = put32(o, 0);
    o = put16(o, 10); o = put16(o, 40); o = put16(o, 60); o = put16(o, 30); o = put16(o, 2);
    o = put16(o, 0xFFFF); o = put16(o, 0x0083); o = putwide(o, ""); o = put16(o, 0);
    dlg_template = t;
    dlg_size = o - t;
    log_clear();
    r = API("DialogBoxParamA", 0x400000, 101, 0, port_host_function(dlgproc), 0);
    CHECK(r == 42);
    CHECK(strstr(log_, "INIT(first=") == log_ && strstr(log_, ") OK ") != NULL);

    /* a dialog with neither an OK nor a Cancel control (the duel's "You won!" screen) gets the keys itself, as characters */
    t = scratch(128); o = t;
    o = put32(o, 0x80C80000u); o = put32(o, 0); o = put16(o, 1);
    o = put16(o, 5); o = put16(o, 5); o = put16(o, 100); o = put16(o, 80);
    o = put16(o, 0); o = put16(o, 0); o = putwide(o, "Keys");
    o = (o + 3) & ~3u;
    o = put32(o, WS_CHILD | WS_VISIBLE); o = put32(o, 0);
    o = put16(o, 10); o = put16(o, 20); o = put16(o, 30); o = put16(o, 12); o = put16(o, 50);
    o = put16(o, 0xFFFF); o = put16(o, 0x0082); o = putwide(o, "text"); o = put16(o, 0);
    dlg_template = t;
    dlg_size = o - t;
    keydlg = 1;
    log_clear();
    r = API("DialogBoxParamA", 0x400000, 102, 0, port_host_function(dlgproc), 0);
    keydlg = 0;
    CHECK(r == 7 && strstr(log_, "CHAR(13)") != NULL);
}


/* ---- the file dialogs (filedlg.c): a script of keys and clicks from a thread of its own, then what went into the OPENFILENAME ---- */
static const char *fd_script;
static int fd_script_done;

static Window *fd_item(uint32_t id) { return wm_dlg_item(wm_top_dialog(), id); }

static void fd_click(int x, int y)
{
    wm_inject_mouse(IN_MOVE, x, y);
    wm_inject_mouse(IN_DOWN, x, y);
    sched_sleep(0.02);
    wm_inject_mouse(IN_UP, x, y);
    sched_sleep(0.03);
}

static void fd_click_row(uint32_t list_id, int row, int twice)
{
    Window *l = fd_item(list_id);
    int x0, y0, x1, y1;

    wm_abs_rect(l, &x0, &y0, &x1, &y1);
    fd_click(x0 + 40, y0 + 2 + row * 16 + 8);
    if (twice)
        fd_click(x0 + 40, y0 + 2 + row * 16 + 8);
}

static uint32_t fd_driver(const uint32_t *a)
{
    const char *p = fd_script;
    int waited = 0;

    (void)a;
    while ((!wm_top_dialog() || !fd_item(0x480)) && waited++ < 2000)       /* until the dialog is up */
        sched_sleep(0.002);
    sched_sleep(0.05);
    while (*p) {
        char tok[64];
        size_t n = strcspn(p, " ");

        snprintf(tok, sizeof(tok), "%.*s", (int)n, p);
        p += n;
        while (*p == ' ')
            p++;
        if (tok[0] == 't') {                                                /* t:text: typed */
            const char *c;

            for (c = tok + 2; *c; c++) {
                wm_inject_key((uint32_t)toupper((unsigned char)*c), 0, 1, *c, 0);
                wm_inject_key((uint32_t)toupper((unsigned char)*c), 0, 0, -1, 0);
                sched_sleep(0.01);
            }
        } else if (tok[0] == 'e') {                                         /* e: a text field has the focus (the on-screen keyboard may show) */
            CHECK(wm_text_focus() == 1);
        } else if (tok[0] == 'c') {                                         /* c:HEX: a character with no key (Latin-1 text from an input method) */
            CHECK(wm_inject_char((int)strtoul(tok + 2, NULL, 16)) == 1);
        } else if (tok[0] == 'k') {                                         /* k:HEX: a virtual key */
            uint32_t vk = (uint32_t)strtoul(tok + 2, NULL, 16);

            wm_inject_key(vk, 0, 1, -1, 0);
            wm_inject_key(vk, 0, 0, -1, 0);
        } else if (tok[0] == 'r' || tok[0] == 'd') {                        /* r:N: click row N of the list; d:N: twice */
            fd_click_row(0x460, atoi(tok + 2), tok[0] == 'd');
        } else if (tok[0] == 'b') {                                         /* b:ID: click a control */
            Window *c = fd_item((uint32_t)strtoul(tok + 2, NULL, 16));
            int x0, y0, x1, y1;

            wm_abs_rect(c, &x0, &y0, &x1, &y1);
            fd_click((x0 + x1) / 2, y0 + 8);
        } else if (tok[0] == 'p') {                                         /* p:ID:N: open the drop-down of a combo box and click its row N */
            char *colon;
            uint32_t id = (uint32_t)strtoul(tok + 2, &colon, 16);
            Window *c = fd_item(id), *pop;
            int x0, y0, x1, y1, h;

            wm_abs_rect(c, &x0, &y0, &x1, &y1);
            fd_click(x0 + 20, y0 + 10);
            pop = fd_item(0x6F0);
            CHECK(pop && pop->visible);
            wm_abs_rect(pop, &x0, &y0, &x1, &y1);
            ui_font_metrics("MS Sans Serif", 8, 0, &h, NULL, NULL);
            fd_click(x0 + 20, y0 + 2 + atoi(colon + 1) * (h + 1) + 3);
        }
        sched_sleep(0.06);
    }
    fd_script_done = 1;
    return 0;
}

static char fd_title[64];
static int fd_ofn_offsets;

/* Open (or Save) with a script; returns the API's result, the path in lpstrFile in `path`. */
static uint32_t fd_run(int save, uint32_t flags, const char *initial_dir, const char *initial_file, const char *script, char *path, int *index)
{
    static const char filter[] = "Deck files (*.dck)\0*.dck\0All Files (*.*)\0*.*\0";
    int waits;
    uint32_t ofn = scratch(80), buf = scratch(260), title = scratch(32), f = scratch(sizeof(filter) + 4), r;

    memset(G + ofn, 0, 80);
    memcpy(G + f, filter, sizeof(filter));
    G[f + sizeof(filter)] = 0;
    WR32(ofn, 76);
    WR32(ofn + 12, f);
    WR32(ofn + 24, 1);
    strcpy((char *)G + buf, initial_file);
    WR32(ofn + 28, buf);
    WR32(ofn + 32, 260);
    WR32(ofn + 36, title);
    WR32(ofn + 40, 32);
    WR32(ofn + 44, initial_dir ? cstr(initial_dir) : 0);
    WR32(ofn + 52, flags);
    WR32(ofn + 60, cstr("*.dck"));                                                 /* as DUEL.EXE hands it over */
    fd_script = script;
    fd_script_done = 0;
    sched_spawn(port_host_function(fd_driver), 0, 0);
    r = API(save ? "GetSaveFileNameA" : "GetOpenFileNameA", ofn);
    for (waits = 0; !fd_script_done && waits < 500; waits++)                        /* the script's thread finishes its last pause */
        sched_sleep(0.004);
    CHECK(fd_script_done);
    CHECK(!wm_dialog_count());
    snprintf(path, 260, "%s", (char *)G + buf);
    snprintf(fd_title, sizeof(fd_title), "%s", (char *)G + title);
    *index = (int)RD32(ofn + 24);
    fd_ofn_offsets = (int)RD16(ofn + 56) | (int)RD16(ofn + 58) << 16;
    return r;
}

static void put_file(const char *root, const char *rel)
{
    char path[1200];
    FILE *f;

    snprintf(path, sizeof(path), "%s/%s", root, rel);
    f = fopen(path, "wb");
    if (f) {
        fputs("x", f);
        fclose(f);
    }
}

static void test_file_dialogs(void)
{
    char tmpl[300], root[400], over[400], path[300], sub[500];
    int idx;

    test_tmpdir(tmpl, sizeof(tmpl), "pentamoor_fdlg_");
    CHECK(tmpl[0] != 0);
    snprintf(root, sizeof(root), "%s/game", tmpl);
    snprintf(over, sizeof(over), "%s/overlay", tmpl);
    plat_mkdir(root);
    plat_mkdir(over);
    snprintf(sub, sizeof(sub), "%s/Decks", root);
    plat_mkdir(sub);
    snprintf(sub, sizeof(sub), "%s/Decks/sub", root);
    plat_mkdir(sub);
    put_file(root, "Decks/a.dck");
    put_file(root, "Decks/b.dck");
    put_file(root, "Decks/c.txt");
    paths_init(root, over);
    snprintf(guest_cwd, sizeof(guest_cwd), "C:\\Magic");

    /* a name typed, with the default extension added, the Return of the dialog manager */
    CHECK(fd_run(0, 0x1000, "C:\\Magic\\Decks", "", "t:a k:0D", path, &idx) == 1);
    CHECK(!strcmp(path, "C:\\Magic\\Decks\\a.dck") && idx == 1);
    CHECK((fd_ofn_offsets & 0xFFFF) == 15 && (fd_ofn_offsets >> 16) == 17 && !strcmp(fd_title, "a.dck"));

    /* an edit control of the open dialog is a text field (the on-screen keyboard is wanted); with the dialog gone it is not */
    CHECK(wm_text_focus() == 0);
    CHECK(fd_run(0, 0, "C:\\Magic\\Decks", "", "e t:ok k:0D", path, &idx) == 1 && !strcmp(path, "C:\\Magic\\Decks\\ok"));
    CHECK(wm_text_focus() == 0);
    /* a character with no key reaches the edit box once (e acute, U+00E9, between typed letters) */
    CHECK(fd_run(0, 0, "C:\\Magic\\Decks", "old.dck", "t:fr c:E9 t:sh k:0D", path, &idx) == 1 && !strcmp(path, "C:\\Magic\\Decks\\fr\xE9sh"));

    /* a name that is not there with FILEMUSTEXIST: the dialog stays; Esc cancels and leaves the buffer alone */
    CHECK(fd_run(0, 0x1000, "C:\\Magic\\Decks", "keep.dck", "t:zzz k:0D k:0D k:1B", path, &idx) == 0);
    CHECK(!strcmp(path, "keep.dck"));

    /* the offered name is selected: typing replaces it; without FILEMUSTEXIST a new name is accepted as typed */
    CHECK(fd_run(0, 0, "C:\\Magic\\Decks", "old.dck", "t:fresh k:0D", path, &idx) == 1);
    CHECK(!strcmp(path, "C:\\Magic\\Decks\\fresh"));

    /* a double click on a file; the list is the folders first, then the files that match: sub, a.dck, b.dck */
    CHECK(fd_run(0, 0x1000, "C:\\Magic\\Decks", "", "d:2", path, &idx) == 1 && !strcmp(path, "C:\\Magic\\Decks\\b.dck"));
    /* a click selects the file and puts its name in the box; Return takes it */
    CHECK(fd_run(0, 0x1000, "C:\\Magic\\Decks", "", "r:1 k:0D", path, &idx) == 1 && !strcmp(path, "C:\\Magic\\Decks\\a.dck"));
    /* the arrow keys move the selection: down, down, down (b.dck), up (a.dck) */
    CHECK(fd_run(0, 0x1000, "C:\\Magic\\Decks", "", "k:28 k:28 k:28 k:26 k:0D", path, &idx) == 1 && !strcmp(path, "C:\\Magic\\Decks\\a.dck"));

    /* "Files of type": the second filter shows c.txt too (sub, a, b, c) */
    CHECK(fd_run(0, 0x1000, "C:\\Magic\\Decks", "", "p:470:1 d:3", path, &idx) == 1 && !strcmp(path, "C:\\Magic\\Decks\\c.txt") && idx == 2);
    /* "Look in": the drop-down lists the folders down to the current one (C:\, Magic, Decks); Magic opens it, where Decks is the one folder shown */
    CHECK(fd_run(0, 0x1000, "C:\\Magic\\Decks", "", "p:471:1 d:0 d:1", path, &idx) == 1 && !strcmp(path, "C:\\Magic\\Decks\\a.dck"));
    /* Up one level, then a relative name */
    CHECK(fd_run(0, 0x1000, "C:\\Magic\\Decks", "", "b:472 t:Decks\\b.dck k:0D", path, &idx) == 1 && !strcmp(path, "C:\\Magic\\Decks\\b.dck"));
    /* a folder typed is entered, a pattern typed filters: *.txt shows c.txt (the folder first, so row 1) */
    CHECK(fd_run(0, 0x1000, "C:\\Magic", "", "t:Decks k:0D t:*.txt k:0D d:1", path, &idx) == 1 && !strcmp(path, "C:\\Magic\\Decks\\c.txt"));
    /* a folder that is not there falls back to the nearest one that is */
    CHECK(fd_run(0, 0x1000, "C:\\Magic\\Decks\\nope\\deeper", "", "t:a k:0D", path, &idx) == 1 && !strcmp(path, "C:\\Magic\\Decks\\a.dck"));

    /* Save: into a folder opened by a double click, the default extension added; no question without OFN_OVERWRITEPROMPT */
    CHECK(fd_run(1, 0, "C:\\Magic\\Decks", "", "d:0 t:new k:0D", path, &idx) == 1 && !strcmp(path, "C:\\Magic\\Decks\\sub\\new.dck"));
    CHECK(fd_run(1, 0, "C:\\Magic\\Decks", "", "t:a k:0D", path, &idx) == 1 && !strcmp(path, "C:\\Magic\\Decks\\a.dck"));
    /* with it: the first Return asks, Esc declines (the dialog stays), the next Return asks again, the one after answers Yes */
    CHECK(fd_run(1, 2, "C:\\Magic\\Decks", "", "t:a k:0D k:1B k:0D k:0D", path, &idx) == 1 && !strcmp(path, "C:\\Magic\\Decks\\a.dck"));
    /* a name that is free needs no answer; Esc twice (decline, then cancel) of an overwrite leaves nothing chosen */
    CHECK(fd_run(1, 2, "C:\\Magic\\Decks", "", "t:free k:0D", path, &idx) == 1 && !strcmp(path, "C:\\Magic\\Decks\\free.dck"));
    CHECK(fd_run(1, 2, "C:\\Magic\\Decks", "keep", "t:b k:0D k:1B k:1B", path, &idx) == 0 && !strcmp(path, "keep"));
    /* a path that does not exist is refused */
    CHECK(fd_run(1, 0, "C:\\Magic\\Decks", "", "t:nofolder\\x k:0D k:1B", path, &idx) == 0);

    test_rmtree(tmpl);
}

/* ---- WinHelpA (winhelp.c) and the About dialog's way of closing --------------------------------------------------------------------- */
static int wh_mode;             /* how the script closes the dialog: 0 the OK button is clicked, 1 Enter, 2 Esc, 3 the close box (WM_CLOSE) */
static int wh_done, wh_shown, wh_has_ok;
static char wh_text[400], wh_caption[64];

/* the first child of the open dialog of a class (STATIC, BUTTON) */
static Window *wh_child(uint32_t hdlg, const char *cname)
{
    int i, n = wm_window_count();

    for (i = 0; i < n; i++) {
        Window *c = wm_window_at_index(i);

        if (c && c->parent == hdlg && c->cname && !strcasecmp(c->cname, cname))
            return c;
    }
    return NULL;
}

static void wh_click_window(Window *c)
{
    int x0, y0, x1, y1;

    wm_abs_rect(c, &x0, &y0, &x1, &y1);
    fd_click((x0 + x1) / 2, (y0 + y1) / 2);
}

static uint32_t wh_driver(const uint32_t *a)
{
    int waited = 0;
    uint32_t hdlg;
    Window *d, *st, *ok;

    (void)a;
    while (!wm_top_dialog() && waited++ < 2000)
        sched_sleep(0.002);
    sched_sleep(0.05);
    hdlg = wm_top_dialog();
    d = wm_window(hdlg);
    st = wh_child(hdlg, "STATIC");
    ok = wm_dlg_item(hdlg, 1);
    wh_shown = d != NULL && st != NULL;
    wh_has_ok = ok != NULL;
    if (wh_shown) {
        snprintf(wh_text, sizeof(wh_text), "%s", st->title ? st->title : "");
        snprintf(wh_caption, sizeof(wh_caption), "%s", d->title ? d->title : "");
    }
    if (wh_mode == 0 && ok)
        wh_click_window(ok);
    else if (wh_mode == 1) {
        wm_inject_key(0x0D, 0x1C, 1, 0x0D, 0);
        wm_inject_key(0x0D, 0x1C, 0, -1, 0);
    } else if (wh_mode == 2) {
        wm_inject_key(0x1B, 0x01, 1, 0x1B, 0);
        wm_inject_key(0x1B, 0x01, 0, -1, 0);
    } else if (wh_mode == 3)
        wm_post(hdlg, WM_CLOSE, 0, 0);
    wh_done = 1;
    return 0;
}

/* WinHelpA with the given command, the dialog (if one comes) closed by `mode`; returns the API's result */
static uint32_t wh_run(uint32_t cmd, const char *file, int mode)
{
    uint32_t r;
    int waits;

    wh_mode = mode;
    wh_done = wh_shown = wh_has_ok = 0;
    wh_text[0] = wh_caption[0] = 0;
    sched_spawn(port_host_function(wh_driver), 0, 0);
    r = API("WinHelpA", 0, file ? cstr(file) : 0, cmd, 0x7e2);
    for (waits = 0; !wh_done && waits < 500; waits++)
        sched_sleep(0.004);
    CHECK(wh_done);
    CHECK(!wm_dialog_count());
    return r;
}

static uint32_t about_proc(const uint32_t *a)
{
    if (a[1] == WM_INITDIALOG)
        return 1;
    if (a[1] == WM_LBUTTONDOWN || a[1] == WM_CHAR || a[1] == WM_COMMAND) {      /* the game's About dialog ends on a click, a character or a command */
        note("END(%u) ", a[1]);
        API("EndDialog", a[0], 1);
        return 1;
    }
    return a[1] == WM_ERASEBKGND ? 1 : 0;
}

static void about_template(void)
{
    uint32_t t = scratch(512), o = t;
    int i;

    o = put32(o, 0x80000000u | 0x40); o = put32(o, 0); o = put16(o, 3);                /* a popup without caption or buttons, three statics */
    o = put16(o, 0); o = put16(o, 0); o = put16(o, 200); o = put16(o, 100);
    o = put16(o, 0); o = put16(o, 0); o = putwide(o, "");
    o = put16(o, 10); o = putwide(o, "Benguiat Bk BT");
    for (i = 0; i < 3; i++) {
        o = (o + 3) & ~3u;
        o = put32(o, 0x50020000u); o = put32(o, 0);
        o = put16(o, 17); o = put16(o, (uint32_t)(14 + 30 * i)); o = put16(o, 169); o = put16(o, 21); o = put16(o, 0xFFFF);
        o = put16(o, 0xFFFF); o = put16(o, 0x0082); o = putwide(o, "Copyright line"); o = put16(o, 0);
    }
    dlg_template = t;
    dlg_size = o - t;
}

static int about_closed_by;
static uint32_t about_driver(const uint32_t *a)
{
    int waited = 0;
    uint32_t hdlg;

    (void)a;
    while (!wm_top_dialog() && waited++ < 2000)
        sched_sleep(0.002);
    sched_sleep(0.05);
    hdlg = wm_top_dialog();
    CHECK(wh_child(hdlg, "BUTTON") == NULL);                      /* there is no OK button to press */
    if (about_closed_by == 0)
        wh_click_window(wh_child(hdlg, "STATIC"));                  /* a click on the text goes through to the dialog */
    else {
        wm_inject_key(0x20, 0x39, 1, ' ', 0);
        wm_inject_key(0x20, 0x39, 0, -1, 0);
    }
    wh_done = 1;
    return 0;
}

static void test_winhelp(void)
{
    char out[400], name[64];
    int waits, k;

    /* which commands show help: the context and contents and index, the keyword searches and pop-ups do; quitting and the setup commands do not */
    CHECK(winhelp_shows(HELP_CONTEXT) && winhelp_shows(HELP_INDEX) && winhelp_shows(HELP_FINDER) && winhelp_shows(HELP_KEY) && winhelp_shows(HELP_CONTEXTPOPUP));
    CHECK(!winhelp_shows(HELP_QUIT) && !winhelp_shows(HELP_SETINDEX) && !winhelp_shows(HELP_FORCEFILE) && !winhelp_shows(HELP_SETWINPOS) && !winhelp_shows(HELP_SETPOPUP_POS));
    /* the file name in the text is the help file's, however the path is spelled */
    winhelp_file_name("C:\\MAGIC\\PROGRAM\\duel.hlp", name, sizeof(name));
    CHECK(!strcmp(name, "duel.hlp"));
    winhelp_file_name("duel.hlp", name, sizeof(name));
    CHECK(!strcmp(name, "duel.hlp"));
    winhelp_file_name("/tmp/x/DUEL.HLP", name, sizeof(name));
    CHECK(!strcmp(name, "DUEL.HLP"));
    winhelp_file_name(NULL, name, sizeof(name));
    CHECK(name[0] == 0);
    CHECK(winhelp_text(HELP_CONTEXT, "C:\\MAGIC\\PROGRAM\\duel.hlp", out, sizeof(out)) == 1);
    CHECK(strstr(out, "not available") != NULL && strstr(out, "duel.hlp") != NULL && strstr(out, "\\") == NULL);
    CHECK(winhelp_text(HELP_INDEX, NULL, out, sizeof(out)) == 1 && strstr(out, "not available") != NULL && strstr(out, "()") == NULL);
    CHECK(winhelp_text(HELP_QUIT, "duel.hlp", out, sizeof(out)) == 0 && out[0] == 0);
    CHECK(winhelp_text(HELP_CONTEXT, "duel.hlp", out, 20) == 1 && strlen(out) < 20);             /* a small buffer is not overrun */

    /* WinHelpA closes quietly (the game calls it with HELP_QUIT when its palette window is destroyed): TRUE, and no dialog */
    CHECK(API("WinHelpA", 0, cstr("C:\\MAGIC\\PROGRAM\\duel.hlp"), HELP_QUIT, 0) == 1);
    CHECK(wm_dialog_count() == 0);
    CHECK(API("WinHelpA", 0, 0, HELP_QUIT, 0) == 1 && wm_dialog_count() == 0);      /* no file name at all */

    /* Help > Contents, a topic, the help finder: a dialog with the text over an OK button, closed by the button, Enter, Esc or the close box; TRUE every time */
    for (k = 0; k < 4; k++) {
        CHECK(wh_run(k == 1 ? HELP_INDEX : k == 2 ? HELP_FINDER : HELP_CONTEXT, "C:\\MAGIC\\PROGRAM\\duel.hlp", k) == 1);
        CHECK(wh_shown && wh_has_ok);
        CHECK(strstr(wh_text, "not available in this port") != NULL && strstr(wh_text, "duel.hlp") != NULL);
        CHECK(!strcmp(wh_caption, "Help"));
    }
    CHECK(wh_run(HELP_CONTEXT, NULL, 0) == 1 && wh_shown);                          /* the program passes no file: still answered */
    CHECK(wh_run(HELP_CONTEXTPOPUP, "C:\\x\\duel.hlp", 1) == 1 && wh_shown);

    /* the About dialog (the duel window's menu item "About...": template 247, three statics, no button): a click on its text, or a key, ends it */
    about_template();
    for (k = 0; k < 2; k++) {
        about_closed_by = k;
        wh_done = 0;
        log_clear();
        sched_spawn(port_host_function(about_driver), 0, 0);
        CHECK(API("DialogBoxParamA", 0x400000, 247, 0, port_host_function(about_proc), 0) == 1);
        for (waits = 0; !wh_done && waits < 500; waits++)
            sched_sleep(0.004);
        CHECK(wh_done && !wm_dialog_count());
        CHECK(strstr(log_, k == 0 ? "END(513)" : "END(258)") != NULL);                   /* WM_LBUTTONDOWN, then WM_CHAR */
    }
}

static int picker_done;
static uint32_t picker(const uint32_t *a)
{
    (void)a;
    while (!wm_popup_open())
        sched_sleep(0.001);
    wm_inject_mouse(IN_DOWN, 30, 45);                     /* the grey item: nothing happens */
    sched_sleep(0.003);
    CHECK(wm_popup_open());
    {   /* the D-pad in a menu: its enabled rows (the separator and the grey one are left out); down from the first goes to the third, up comes back, and there is nothing beyond */
        NavTarget nt[8];
        int cur, n = navwm_collect(nt, 8, 12, 14, &cur), tx = 0, ty = 0, r;

        CHECK(navwm_mode() == NAVWM_MENU && n == 2 && !strcmp(nt[0].label, "First") && !strcmp(nt[1].label, "Third") && nt[0].kind == NAVK_MENU);
        CHECK(cur == 0);
        r = navwm_pick(12, 14, NAV_DOWN, &tx, &ty);
        CHECK(r == 1 && tx >= nt[1].x0 && tx < nt[1].x1 && ty >= nt[1].y0 && ty < nt[1].y1);
        CHECK(navwm_pick(tx, ty, NAV_DOWN, &tx, &ty) == NAV_NONE);
        CHECK(navwm_pick(tx, ty, NAV_UP, &tx, &ty) == 0);
    }
    wm_inject_mouse(IN_MOVE, 30, 60);
    wm_inject_mouse(IN_DOWN, 30, 60);                     /* "Third" */
    picker_done = 1;
    return 0;
}

static void test_popup_menu(void)
{
    uint32_t menu = API("CreatePopupMenu"), top = create("TestClass", 0, 0, 0, 100, 100, 0, 0), r;

    API("AppendMenuA", menu, 0, 11, cstr("First"));
    API("AppendMenuA", menu, 0x800, 0, 0);                   /* a separator */
    API("AppendMenuA", menu, 1, 12, cstr("Grey"));           /* MF_GRAYED */
    API("AppendMenuA", menu, 0, 13, cstr("Third"));
    CHECK(API("GetMenuItemCount", menu) == 4);
    CHECK(API("EnableMenuItem", menu, 13, 1) == 0 && API("EnableMenuItem", menu, 13, 0) == 1);
    sched_spawn(port_host_function(picker), 0, 0);
    r = API("TrackPopupMenu", menu, 0x100, 10, 10, 0, top, 0);        /* TPM_RETURNCMD */
    CHECK(r == 13);
    CHECK(picker_done);
    CHECK(!wm_popup_open());
}

static void click_at(int x, int y)
{
    wm_inject_mouse(IN_MOVE, x, y);
    wm_inject_mouse(IN_DOWN, x, y);
    wm_inject_mouse(IN_UP, x, y);
}

static void test_auto_controls(void)
{
    uint32_t top = create("TestClass", WS_VISIBLE | WS_POPUP, 400, 200, 220, 200, 0, 0);
    uint32_t r1 = create("BUTTON", WS_CHILD | WS_VISIBLE | 0x20000u | 9, 10, 10, 80, 16, top, 11);       /* BS_AUTORADIOBUTTON; the first of a group has WS_GROUP */
    uint32_t r2 = create("BUTTON", WS_CHILD | WS_VISIBLE | 9, 10, 30, 80, 16, top, 12);
    uint32_t r3 = create("BUTTON", WS_CHILD | WS_VISIBLE | 0x20000u | 9, 10, 50, 80, 16, top, 13);       /* a second group */
    uint32_t cb = create("BUTTON", WS_CHILD | WS_VISIBLE | 3, 10, 70, 80, 16, top, 14);                  /* BS_AUTOCHECKBOX */
    uint32_t combo = create("COMBOBOX", WS_CHILD | WS_VISIBLE | 3, 100, 10, 100, 150, top, 15);          /* CBS_DROPDOWNLIST, 150 high with its list */
    int lx0, ly0, lx1, ly1, rowh, rows;
    Window *cw;

    wm_inject_mouse(IN_UP, 0, 0);                                            /* the menu test before this one leaves a release for the game to swallow */
    /* a click checks the radio button and only it in its group */
    API("SendMessageA", r1, 0xF1, 1, 0);                                     /* BM_SETCHECK */
    API("SendMessageA", r3, 0xF1, 1, 0);
    click_at(400 + 20, 200 + 38);
    CHECK(API("SendMessageA", r2, 0xF0, 0, 0) == 1 && API("SendMessageA", r1, 0xF0, 0, 0) == 0);
    CHECK(API("SendMessageA", r3, 0xF0, 0, 0) == 1);                         /* the other group is not touched */
    click_at(400 + 20, 200 + 38);
    CHECK(API("SendMessageA", r2, 0xF0, 0, 0) == 1);                         /* a radio button stays checked when clicked again */
    click_at(400 + 20, 200 + 78);
    CHECK(API("SendMessageA", cb, 0xF0, 0, 0) == 1);                         /* a check box flips */
    click_at(400 + 20, 200 + 78);
    CHECK(API("SendMessageA", cb, 0xF0, 0, 0) == 0);
    /* a disabled button takes no click */
    CHECK(API("EnableWindow", r1, 0) == 0);                                  /* it was enabled */
    click_at(400 + 20, 200 + 18);
    CHECK(API("SendMessageA", r1, 0xF0, 0, 0) == 0 && API("SendMessageA", r2, 0xF0, 0, 0) == 1);
    CHECK(API("EnableWindow", r1, 1) == 1);                                  /* it was disabled */
    click_at(400 + 20, 200 + 18);
    CHECK(API("SendMessageA", r1, 0xF0, 0, 0) == 1 && API("SendMessageA", r2, 0xF0, 0, 0) == 0);

    /* the combo box is its closed box; a click puts the list down, a click on a row chooses it and closes the list */
    cw = wm_window(combo);
    CHECK(cw && cw->h == COMBO_CLOSED_H && cw->drop_h == 150);
    API("SendMessageA", combo, 0x143, 0, cstr("one"));                         /* CB_ADDSTRING */
    API("SendMessageA", combo, 0x143, 0, cstr("two"));
    API("SendMessageA", combo, 0x143, 0, cstr("three"));
    API("SendMessageA", combo, 0x14E, 0, 0);                                   /* CB_SETCURSEL 0 */
    CHECK(wm_combo_open() == 0);
    click_at(400 + 120, 200 + 20);
    CHECK(wm_combo_open() == (int)combo);
    ui_combo_geometry(cw, &lx0, &ly0, &lx1, &ly1, &rowh, &rows);
    CHECK(rows == 3 && ly1 > ly0);
    {   /* the D-pad in the list that is down: its rows, one target each, in order; down goes row by row and stops at the last */
        NavTarget nt[8];
        int cur, n = navwm_collect(nt, 8, lx0 + 20, ly0 + 3, &cur), tx = 0, ty = 0;

        CHECK(navwm_mode() == NAVWM_COMBO && n == 3 && cur == 0 && nt[0].kind == NAVK_ROW && !strcmp(nt[2].label, "three"));
        CHECK(navwm_pick(lx0 + 20, ly0 + 3, NAV_DOWN, &tx, &ty) == 1 && ty >= nt[1].y0 && ty < nt[1].y1);
        CHECK(navwm_pick(tx, ty, NAV_DOWN, &tx, &ty) == 2 && navwm_pick(tx, ty, NAV_DOWN, &tx, &ty) == NAV_NONE);
    }
    wm_inject_mouse(IN_MOVE, lx0 + 20, ly0 + 1 + rowh * 2 + 2);
    CHECK(cw->hot == 2);                                                       /* the row under the pointer is lit */
    click_at(lx0 + 20, ly0 + 1 + rowh * 2 + 2);
    CHECK(wm_combo_open() == 0 && API("SendMessageA", combo, 0x147, 0, 0) == 2);       /* CB_GETCURSEL: "three" */
    click_at(400 + 120, 200 + 20);                                             /* down again: Up moves, Esc goes back to "three" */
    CHECK(wm_combo_open() == (int)combo);
    wm_inject_key(0x26, 0, 1, -1, 0);
    CHECK(API("SendMessageA", combo, 0x147, 0, 0) == 1);
    wm_inject_key(0x1B, 0, 1, -1, 0);
    CHECK(wm_combo_open() == 0 && API("SendMessageA", combo, 0x147, 0, 0) == 2);
    click_at(400 + 120, 200 + 20);                                             /* a click elsewhere closes it without a change */
    click_at(400 + 5, 200 + 190);
    CHECK(wm_combo_open() == 0 && API("SendMessageA", combo, 0x147, 0, 0) == 2);
    API("EnableWindow", combo, 0);
    click_at(400 + 120, 200 + 20);
    CHECK(wm_combo_open() == 0);                                               /* a disabled combo box does not drop */
}

/* The D-pad's targets in a duel (navwm.c): windows of the classes the game's duel makes, laid out as at 1024x768 (docs/notes/controller-nav.md). The hand's cards overlap (15 pixels
 * apart, 128 tall: only a strip of each shows, the last whole), the territories hold the in-play cards, the left column has the life total, the mana pool and the phase icons. */
static int nav_index(const NavTarget *t, int n, uint32_t id, int nth)
{
    int i;

    for (i = 0; i < n; i++)
        if (t[i].id == id && nth-- == 0)
            return i;
    return -1;
}

static void test_navwm_duel(void)
{
    static const char *const cls[] = {"MAGICGAME_MainClass", "MAGICGAME_TerritoryClass", "MAGICGAME_CardClass", "MAGICGAME_HandClass", "MAGICGAME_LifeClass", "MAGICGAME_PhaseDisplayClass",
                                      "MAGICGAME_ManaSummaryClass", "MAGIC_TellUserClass", "MAGICGAME_GraveyardClass"};
    uint32_t main_w, terr, oterr, hand, phase, mana, bar, done, grave, hc[4], mc[3], oc[2];
    NavTarget nt[NAV_MAXTARGETS];
    int sw = screen_w, sh = screen_h, n, cur, i, tx = 0, ty = 0, r;

    screen_w = 1024; screen_h = 768;
    for (i = 0; i < 9; i++)
        register_class(cls[i], port_host_function(wndproc), 0, 0);
    CHECK(navwm_mode() == NAVWM_NONE);
    main_w = create("MAGICGAME_MainClass", WS_VISIBLE | WS_POPUP, 0, 0, 1024, 768, 0, 0);
    terr = create("MAGICGAME_TerritoryClass", WS_CHILD | WS_VISIBLE, 299, 384, 726, 384, main_w, 121);
    oterr = create("MAGICGAME_TerritoryClass", WS_CHILD | WS_VISIBLE, 299, 0, 726, 384, main_w, 122);
    for (i = 0; i < 3; i++)
        mc[i] = create("MAGICGAME_CardClass", WS_CHILD | WS_VISIBLE, 10 + 133 * i, 10, 128, 128, terr, 1);
    for (i = 0; i < 2; i++)
        oc[i] = create("MAGICGAME_CardClass", WS_CHILD | WS_VISIBLE, 10 + 133 * i, 10, 128, 128, oterr, 1);
    hand = create("MAGICGAME_HandClass", WS_CHILD | WS_VISIBLE, 819, 460, 146, 270, main_w, 0);
    for (i = 0; i < 4; i++)
        hc[i] = create("MAGICGAME_CardClass", WS_CHILD | WS_VISIBLE, 9, 39 + 15 * i, 128, 128, hand, 1);
    (void)create("MAGICGAME_LifeClass", WS_CHILD | WS_VISIBLE, 1, 672, 128, 96, main_w, 102);
    grave = create("MAGICGAME_GraveyardClass", WS_CHILD, 65, 576, 64, 96, main_w, 110);               /* not shown: no target */
    phase = create("MAGICGAME_PhaseDisplayClass", WS_CHILD | WS_VISIBLE, 257, 0, 42, 768, main_w, 119);
    mana = create("MAGICGAME_ManaSummaryClass", WS_CHILD | WS_VISIBLE, 129, 576, 128, 192, main_w, 105);
    bar = create("MAGIC_TellUserClass", WS_POPUP | WS_VISIBLE, 299, 367, 528, 34, main_w, 0);
    done = create("BUTTON", WS_CHILD | WS_VISIBLE, 11, 4, 69, 26, bar, 2);
    (void)grave;
    CHECK(navwm_mode() == NAVWM_DUEL);

    n = navwm_collect(nt, NAV_MAXTARGETS, 0, 0, &cur);
    CHECK(n == 3 + 2 + 4 + 1 + 16 + 6 + 1);                                    /* cards, the life total, the phase icons of both sides, the pool's rows, the Done button */
    CHECK(cur == -1);
    for (i = 1; i < n; i++)
        CHECK(nt[i - 1].y0 < nt[i].y0 || (nt[i - 1].y0 == nt[i].y0 && nt[i - 1].x0 <= nt[i].x0));      /* top to bottom, left to right */
    /* the hand: a strip of each card, the last whole (no part of a card under another is a target) */
    for (i = 0; i < 4; i++) {
        int k = nav_index(nt, n, hc[i], 0);

        CHECK(k >= 0 && nt[k].x0 == 828 && nt[k].x1 == 956 && nt[k].y0 == 499 + 15 * i && nt[k].y1 == (i < 3 ? 514 + 15 * i : 544 + 128) && nt[k].kind == NAVK_CARD);
    }
    CHECK(nav_index(nt, n, grave, 0) < 0);
    {   /* the Done button: all of it, though the territory below overlaps its lower part (it is the bar's, and above) */
        int k = nav_index(nt, n, done, 0);

        CHECK(k >= 0 && nt[k].kind == NAVK_BUTTON && nt[k].x0 == 310 && nt[k].x1 == 379 && nt[k].y0 == 371 && nt[k].y1 == 397);
    }
    /* the phase column: eight icons a side, the player's the lower eight; the mana pool: six rows of 32 */
    CHECK(nav_index(nt, n, phase, 15) >= 0 && nav_index(nt, n, phase, 16) < 0 && nav_index(nt, n, mana, 5) >= 0 && nav_index(nt, n, mana, 6) < 0);
    {
        int k = nav_index(nt, n, phase, 8);                                    /* the player's first icon (after the opponent's eight, in order from the top) */

        CHECK(k >= 0 && nt[k].y0 == 436 && nt[k].y1 == 476 && nt[k].x0 == 257 && nt[k].x1 == 299 && nt[k].kind == NAVK_PHASE);
        k = nav_index(nt, n, mana, 3);
        CHECK(nt[k].y0 == 576 + 96 && nt[k].y1 == 576 + 128 && nt[k].kind == NAVK_MANA);
    }

    /* the user's examples */
    r = navwm_pick(892, 600, NAV_UP, &tx, &ty);                                /* the pointer on the last card of the hand (y 544..672): up goes up the hand */
    CHECK(r >= 0 && tx == 891 && ty == 536);                  /* the strip above: 529..544, its middle */
    r = navwm_pick(892, 536, NAV_UP, &tx, &ty);
    CHECK(r >= 0 && tx == 891 && ty == 521);
    r = navwm_pick(892, 506, NAV_LEFT, &tx, &ty);                              /* the top strip: left goes to your territory, its card in the row, the nearest */
    CHECK(r >= 0 && tx == 638 && ty == 461);                                   /* the third card (x 575..703; the prompt bar covers its top: 401..522) */
    r = navwm_pick(tx, ty, NAV_LEFT, &tx, &ty);
    CHECK(r >= 0 && tx == 505 && ty == 461);                                   /* scrolling along the row */
    r = navwm_pick(tx, ty, NAV_LEFT, &tx, &ty);
    CHECK(r >= 0 && tx == 372 && ty == 461);
    r = navwm_pick(tx, ty, NAV_UP, &tx, &ty);                                  /* up from your cards: the Done button between the territories, then the opponent's cards */
    CHECK(r >= 0 && nav_index(nt, n, done, 0) == r);
    r = navwm_pick(tx, ty, NAV_UP, &tx, &ty);
    CHECK(r >= 0 && tx == 372 && ty == 73);                                    /* the opponent's first card (x 309..437, y 10..138), in the Done button's column, not the phase icon beside it */
    r = navwm_pick(tx, ty, NAV_UP, &tx, &ty);
    CHECK(r == NAV_NONE);
    /* the pointer on the territory's empty part: it is on no target; the nearest in the direction */
    r = navwm_pick(700, 700, NAV_UP, &tx, &ty);
    CHECK(r >= 0 && ty == 461);
    navwm_collect(nt, NAV_MAXTARGETS, 892, 506, &cur);
    CHECK(cur == nav_index(nt, n, hc[0], 0));
    /* the pointer on the Done button's lower part (below the territory's top edge: another piece of the window's visible area) is on the button's target */
    navwm_collect(nt, NAV_MAXTARGETS, 340, 395, &cur);
    CHECK(cur == nav_index(nt, n, done, 0));

    {   /* in combat the attack's column covers the phase column: its seven icons replace the sixteen (one side, 40/760 of the height each) */
        uint32_t att;
        int m, k;

        register_class("MAGICGAME_AttackPhaseDisplayClass", port_host_function(wndproc), 0, 0);
        att = create("MAGICGAME_AttackPhaseDisplayClass", WS_CHILD | WS_VISIBLE, 257, 0, 42, 768, main_w, 120);
        m = navwm_collect(nt, NAV_MAXTARGETS, 0, 0, &cur);
        CHECK(m == n - 16 + 7 && nav_index(nt, m, phase, 0) < 0);
        k = nav_index(nt, m, att, 6);
        CHECK(k >= 0 && nt[k].y0 == 768 * 289 / 760 && nt[k].y1 == 768 * 289 / 760 + 768 * 40 / 760 && nav_index(nt, m, att, 7) < 0);
        API("DestroyWindow", att);
    }

    /* a duel that is not shown has no targets */
    API("ShowWindow", main_w, 0);
    CHECK(navwm_mode() == NAVWM_NONE && navwm_collect(nt, NAV_MAXTARGETS, 0, 0, &cur) == 0);
    API("ShowWindow", main_w, 1);
    CHECK(navwm_mode() == NAVWM_DUEL);
    API("DestroyWindow", main_w);
    CHECK(navwm_mode() == NAVWM_NONE);
    screen_w = sw; screen_h = sh;
}

int main(void)
{
    guest_init();
    sched_init();
    kernel32_init();
    port_index_functions();
    test_creation_and_show();
    test_geometry_and_state();
    test_z_order();
    test_queue_and_dispatch();
    test_erase_before_paint();
    test_see_through_child();
    test_timers();
    test_cross_thread_send();
    test_thread_stacks();
    test_host_module();
    test_message_range();
    test_window_from_point();
    test_input();
    test_front();
    test_front_press();
    test_window_fit();
    test_controls();
    test_rects();
    test_key_target();
    test_dialog_units();
    test_popup_position();
    test_dialog();
    test_popup_menu();
    test_file_dialogs();
    test_winhelp();
    test_auto_controls();
    test_navwm_duel();
    printf("%d checks, %d failed\n", checks, failures);
    return failures ? 1 : 0;
}

int pe_find_resource(uint32_t hinst, uint32_t type, uint32_t name, uint32_t *addr, uint32_t *size)
{
    (void)hinst; (void)name;
    if (type != 5 || !dlg_template)
        return 0;
    *addr = dlg_template;
    *size = dlg_size;
    return 1;
}

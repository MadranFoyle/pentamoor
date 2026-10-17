/* kernel32.c - kernel32, winmm's timers and the little advapi32/shell32 calls. Port of winemu/kernel32.py. */
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <unistd.h>

#include "gdi_int.h"
#include "plat.h"
#include "process.h"
#include "sched.h"
#include "wm.h"

#define P(a) ((char *)(G + (a)))
#define INVALID_HANDLE 0xFFFFFFFFu

/* ---- handles ------------------------------------------------------------------------------------------------------------------- */
enum { H_THREAD = 1, H_FILE, H_MAPPING, H_VXD, H_RESOURCE, H_REGKEY };
typedef struct Handle { int kind; int fd; GThread *thread; uint32_t a, b; char *name; } Handle;
static Handle *handles;
static int nhandles, caphandles;
#define H_BASE 0x100u

static uint32_t new_handle(Handle h)
{
    if (nhandles == caphandles) {
        caphandles = caphandles ? caphandles * 2 : 64;
        handles = realloc(handles, (size_t)caphandles * sizeof(*handles));
    }
    handles[nhandles] = h;
    return H_BASE + 4u * (uint32_t)nhandles++;
}

static Handle *get_handle(uint32_t h)
{
    uint32_t i;

    if (h < H_BASE || (h - H_BASE) % 4)
        return NULL;
    i = (h - H_BASE) / 4;
    return i < (uint32_t)nhandles && handles[i].kind ? &handles[i] : NULL;
}

/* The descriptor behind a file handle (the standard handles are 0x10..0x12: stdin, stdout, stderr), or -1. */
int k32_file_fd(uint32_t h)
{
    Handle *hd;

    if (h >= 0x10 && h <= 0x12)
        return (int)(h - 0x10);
    hd = get_handle(h);
    return hd && hd->kind == H_FILE ? hd->fd : -1;
}

static uint32_t last_error_code;
static uint32_t zero(const uint32_t *a) { (void)a; return 0; }
static uint32_t one(const uint32_t *a) { (void)a; return 1; }

/* ---- process and module ----------------------------------------------------------------------------------------------------------- */
static uint32_t GetVersion(const uint32_t *a) { (void)a; return 0x88AE0A04; }      /* Windows 98 SE: 4.10, build 2222, top bit set for Win9x */
static uint32_t GetCurrentProcess(const uint32_t *a) { (void)a; return 0xFFFFFFFFu; }
static uint32_t GetCurrentThread(const uint32_t *a) { (void)a; return 0xFFFFFFFEu; }
static uint32_t GetLastError(const uint32_t *a) { (void)a; return last_error_code; }
static uint32_t SetLastError(const uint32_t *a) { last_error_code = a[0]; return 0; }
static uint32_t GetTickCount(const uint32_t *a) { (void)a; return port_now_ms(); }
static uint32_t OutputDebugStringA(const uint32_t *a) { port_trace("[debug] %s", P(a[0])); return 0; }
static uint32_t lstrlenA(const uint32_t *a) { return (uint32_t)strlen(P(a[0])); }
static uint32_t GetCurrentThreadId(const uint32_t *a) { (void)a; return sched_tid(); }
static uint32_t GetModuleHandleA(const uint32_t *a);

extern Image main_image;

static uint32_t GetModuleHandleA(const uint32_t *a)
{
    uint32_t h;

    if (!a[0])
        return main_image.base;
    h = module_find(P(a[0]));
    port_trace("GetModuleHandleA(%s) -> 0x%x", P(a[0]), h);
    return h;
}

static uint32_t GetModuleFileNameA(const uint32_t *a)
{
    char path[300];
    const char *slash = plat_last_sep(main_image.path);
    size_t n, i;

    const char *dll = a[0] && a[0] != main_image.base ? module_file(a[0]) : NULL;

    snprintf(path, sizeof(path), "C:\\Magic\\Program\\%s", dll ? dll : slash ? slash + 1 : main_image.path);
    for (i = 0; path[i]; i++)
        if (path[i] >= 'a' && path[i] <= 'z')
            path[i] = (char)(path[i] - 32);
    n = strlen(path);

    if (a[2] == 0)
        return 0;
    if (n > a[2] - 1)
        n = a[2] - 1;
    memcpy(P(a[1]), path, n);
    P(a[1])[n] = 0;
    return (uint32_t)n;
}

static uint32_t GetCurrentDirectoryA(const uint32_t *a)
{
    size_t n = strlen(guest_cwd);

    if (a[0] > n)
        strcpy(P(a[1]), guest_cwd);
    return (uint32_t)n;
}

static uint32_t GetStartupInfoA(const uint32_t *a)
{
    guest_zero(a[0], 68);
    WR32(a[0], 68);
    WR32(a[0] + 44, 1);                  /* dwFlags: STARTF_USESHOWWINDOW */
    WR16(a[0] + 48, 1);                  /* SW_SHOWNORMAL */
    return 0;
}

static uint32_t GetDriveTypeA(const uint32_t *a) { (void)a; return 3; }

/* ---- critical sections: recursive locks, owned by guest threads ------------------------------------------------------------------- */
typedef struct CS { uint32_t addr, owner; int count; } CS;
static CS *css;
static int ncs, capcs;

static CS *cs_of(uint32_t addr)
{
    int i;

    for (i = 0; i < ncs; i++)
        if (css[i].addr == addr)
            return &css[i];
    if (ncs == capcs) {
        capcs = capcs ? capcs * 2 : 64;
        css = realloc(css, (size_t)capcs * sizeof(*css));
    }
    css[ncs] = (CS){addr, 0, 0};
    return &css[ncs++];
}

static uint32_t InitializeCriticalSection(const uint32_t *a) { *cs_of(a[0]) = (CS){a[0], 0, 0}; return 0; }
static int cs_free(void *p) { return cs_of((uint32_t)(uintptr_t)p)->owner == 0; }     /* by guest address: the table may move while a thread waits */

static uint32_t EnterCriticalSection(const uint32_t *a)
{
    CS *c = cs_of(a[0]);

    while (c->owner && c->owner != sched_tid()) {
        sched_block(cs_free, (void *)(uintptr_t)a[0], -1);
        c = cs_of(a[0]);                 /* another thread may have grown the table while this one waited */
    }
    c->owner = sched_tid();
    c->count++;
    return 0;
}

static uint32_t LeaveCriticalSection(const uint32_t *a)
{
    CS *c = cs_of(a[0]);

    if (c->owner == sched_tid() && --c->count <= 0) {
        c->owner = 0;
        c->count = 0;
    }
    return 0;
}

/* ---- threads and waiting ----------------------------------------------------------------------------------------------------------- */
static uint32_t CreateThread(const uint32_t *a)
{
    GThread *t = sched_spawn(a[2], a[3], 0);

    port_trace("CreateThread(start=0x%08x, arg=0x%08x) -> thread %u", a[2], a[3], sched_thread_id(t));
    if (a[5])
        WR32(a[5], sched_thread_id(t));
    return new_handle((Handle){H_THREAD, -1, t, a[2], a[3], NULL});
}

static uint32_t ExitThread(const uint32_t *a) { sched_exit_current(a[0]); return 0; }
static uint32_t GetThreadPriority(const uint32_t *a) { (void)a; return 0; }
static uint32_t GetPriorityClass(const uint32_t *a) { (void)a; return 0x20; }      /* NORMAL_PRIORITY_CLASS: STATWIN raises its own while a clip plays and sets it back (SetPriorityClass is the "one" below) */
static uint32_t DuplicateHandle(const uint32_t *a) { WR32(a[3], a[1]); return 1; }

static uint32_t GetExitCodeThread(const uint32_t *a)
{
    Handle *h = get_handle(a[0]);
    int done = h && h->kind == H_THREAD && sched_thread_done(h->thread);

    WR32(a[1], done ? sched_thread_exit_code(h->thread) : 259);        /* 259 = STILL_ACTIVE */
    return 1;
}

static uint32_t CloseHandle(const uint32_t *a)
{
    Handle *h = get_handle(a[0]);

    if (proc_handle_known(a[0]))
        proc_handle_close(a[0]);

    if (h) {
        if (h->kind == H_FILE && h->fd >= 0)
            close(h->fd);
        h->kind = 0;
    }
    return 1;
}

static int thread_done(void *p) { return sched_thread_done((GThread *)p); }

static uint32_t WaitForSingleObject(const uint32_t *a)
{
    Handle *h = get_handle(a[0]);

    if (proc_handle_known(a[0]))                              /* a program this one started (process.h) */
        return proc_handle_wait(a[0], a[1] == 0xFFFFFFFFu ? -1 : a[1] / 1000.0) ? 0 : 0x102;

    if (h && h->kind == H_THREAD) {
        GThread *t = h->thread;                                /* not h itself after the wait: another thread may grow the handle table meanwhile */

        if (sched_thread_done(t))
            return 0;
        if (a[1] == 0)
            return 0x102;                                      /* WAIT_TIMEOUT */
        sched_block(thread_done, t, a[1] == 0xFFFFFFFFu ? -1 : a[1] / 1000.0);
        return sched_thread_done(t) ? 0 : 0x102;
    }
    return 0;
}

static uint32_t Sleep(const uint32_t *a)
{
    sched_sleep(a[0] / 1000.0);
    return 0;
}

/* MPSTIME.VXD, the game's high-resolution timer: code 1 returns the version, code 2 a tick counter (the game divides differences by 0x151d / 100,
 * which gives milliseconds at 54,050 ticks a second). */
static uint32_t DeviceIoControl(const uint32_t *a)
{
    Handle *h = get_handle(a[0]);

    if (h && h->kind == H_VXD && a[4]) {
        if (a[1] == 1)
            WR32(a[4], 0x100);
        else if (a[1] == 2)
            WR32(a[4], (uint32_t)(port_now() * 54050.0));
        if (a[6])
            WR32(a[6], 4);
        return 1;
    }
    return 0;
}

/* ---- dynamic loading -------------------------------------------------------------------------------------------------------------- */
static uint32_t LoadLibraryA(const uint32_t *a) { return module_load(P(a[0])); }

static uint32_t GetProcAddress(const uint32_t *a)
{
    char ord[16];

    if (a[1] <= 0xFFFF) {                                /* an ordinal */
        snprintf(ord, sizeof(ord), "#%u", a[1]);
        return module_proc(a[0], ord);
    }
    return module_proc(a[0], P(a[1]));
}

/* ---- memory ------------------------------------------------------------------------------------------------------------------------ */
static uint32_t GlobalAlloc(const uint32_t *a)
{
    uint32_t p = heap_alloc(a[1]);

    if (p && (a[0] & 0x40))
        guest_zero(p, a[1]);
    return p;
}
static uint32_t identity(const uint32_t *a) { return a[0]; }
static uint32_t GlobalFree(const uint32_t *a) { heap_free(a[0]); return 0; }

/* ---- files ------------------------------------------------------------------------------------------------------------------------- */
static uint32_t CreateFileA(const uint32_t *a)
{
    const char *path = P(a[0]);
    uint32_t access = a[1], disp = a[4];
    int write = (access & 0x40000000u) != 0, exists, flags;
    char host[1200];
    struct stat st;

    if (!strncmp(path, "\\\\.\\", 4)) {                             /* a Windows 9x virtual device (VxD) */
        if (!strncasecmp(path + 4, "mpstime", 7))
            return new_handle((Handle){H_VXD, -1, NULL, 0, 0, NULL});
        port_log("CreateFileA(%s): unknown device", path);
        return INVALID_HANDLE;
    }
    if (!strncmp(path, "\\\\", 2))
        return INVALID_HANDLE;
    exists = paths_host(path, disp == 1 || disp == 2 ? 1 : (write || disp == 4) ? 2 : 0, host, sizeof(host));   /* CREATE_NEW/ALWAYS start from nothing; the rest write into what is there */
    if (!exists && (disp == 3 || disp == 5)) {                       /* OPEN_EXISTING / TRUNCATE_EXISTING */
        last_error_code = 2;
        return INVALID_HANDLE;
    }
    if (exists && !stat(host, &st) && S_ISDIR(st.st_mode) && !(a[5] & 0x02000000u)) {      /* a directory needs FILE_FLAG_BACKUP_SEMANTICS */
        last_error_code = 5;
        return INVALID_HANDLE;
    }
    flags = write ? O_RDWR : O_RDONLY;
    if (disp == 1 || disp == 2 || disp == 4)
        flags |= O_CREAT;
    if (disp == 2 || disp == 5)
        flags |= O_TRUNC;
    {
        int fd = open(host, flags | O_BINARY, 0666);

        if (fd < 0) {
            last_error_code = 2;
            return INVALID_HANDLE;
        }
        return new_handle((Handle){H_FILE, fd, NULL, 0, 0, strdup(host)});
    }
}

static uint32_t ReadFile(const uint32_t *a)
{
    Handle *h = get_handle(a[0]);
    ssize_t n;

    if (!h || h->kind != H_FILE)
        return 0;
    plat_guest_commit(a[1], a[2]);
    n = read(h->fd, G + a[1], a[2]);
    if (n < 0) {
        last_error_code = 5;
        return 0;
    }
    if (a[3])
        WR32(a[3], (uint32_t)n);
    return 1;
}

static uint32_t WriteFile(const uint32_t *a)
{
    int fd = k32_file_fd(a[0]);
    ssize_t n;

    if (fd < 0)
        return 0;
    plat_guest_commit(a[1], a[2]);
    n = write(fd, G + a[1], a[2]);
    if (n < 0) {
        last_error_code = 5;
        return 0;
    }
    if (a[3])
        WR32(a[3], (uint32_t)n);
    return 1;
}

/* DeleteFileA: only what the game wrote (the overlay) can go; the installed copy is never touched. */
static uint32_t DeleteFileA(const uint32_t *a)
{
    char host[1200];

    paths_host(P(a[0]), 1, host, sizeof(host));
    port_trace("DeleteFileA(%s) -> %s", P(a[0]), host);
    if (unlink(host) == 0)
        return 1;
    last_error_code = 2;
    return 0;
}

static uint32_t GetFileSize(const uint32_t *a)
{
    Handle *h = get_handle(a[0]);
    struct stat st;

    if (!h || h->kind != H_FILE || fstat(h->fd, &st))
        return INVALID_HANDLE;
    return (uint32_t)st.st_size;
}

/* CopyFileA(from, to, failIfExists): the destination is the overlay's. A file onto itself is refused (the original: a sharing violation) rather than
 * truncated before it is read. */
static uint32_t CopyFileA(const uint32_t *a)
{
    char src[1200], dst[1200];
    FILE *in, *out;
    char buf[8192];
    size_t n;
    int dst_exists;

    if (!paths_host(P(a[0]), 0, src, sizeof(src))) {
        last_error_code = 2;
        return 0;
    }
    dst_exists = paths_host(P(a[1]), 1, dst, sizeof(dst));
    port_trace("CopyFileA(%s, %s, %u) -> %s to %s", P(a[0]), P(a[1]), a[2], src, dst);
    if (a[2] && dst_exists) {
        last_error_code = 80;                       /* ERROR_FILE_EXISTS */
        return 0;
    }
    if (dst_exists && plat_same_file(src, dst)) {
        last_error_code = 32;
        return 0;
    }
    in = fopen(src, "rb");
    out = in ? fopen(dst, "wb") : NULL;
    if (!in || !out) {
        if (in)
            fclose(in);
        last_error_code = in ? 5 : 2;
        return 0;
    }
    while ((n = fread(buf, 1, sizeof(buf), in)) > 0)
        fwrite(buf, 1, n, out);
    fclose(in);
    fclose(out);
    return 1;
}

static uint32_t CreateFileMappingA(const uint32_t *a)
{
    /* anonymous (hFile == -1) shared memory by name, or a view of a file */
    static struct { char name[64]; uint32_t base; } named[16];
    static int nnamed;

    if (a[0] == INVALID_HANDLE) {
        uint32_t size = a[4], base = 0;
        int i;

        if (a[5])
            for (i = 0; i < nnamed; i++)
                if (!strcmp(named[i].name, P(a[5])))
                    base = named[i].base;
        if (!base) {
            base = heap_alloc(size);
            guest_zero(base, size);
            if (a[5] && nnamed < 16) {
                snprintf(named[nnamed].name, sizeof(named[nnamed].name), "%s", P(a[5]));
                named[nnamed++].base = base;
            }
        }
        return new_handle((Handle){H_MAPPING, -1, NULL, base, size, NULL});
    }
    {
        Handle *f = get_handle(a[0]);

        return f && f->kind == H_FILE ? new_handle((Handle){H_MAPPING, f->fd, NULL, 0, 0, NULL}) : 0;
    }
}

static uint32_t MapViewOfFile(const uint32_t *a)
{
    Handle *h = get_handle(a[0]);

    if (!h || h->kind != H_MAPPING)
        return 0;
    if (h->fd < 0)                                  /* an anonymous block: the view is the block itself */
        return h->a + a[3];
    {
        struct stat st;
        uint32_t p;

        fstat(h->fd, &st);
        p = heap_alloc((uint32_t)st.st_size);
        lseek(h->fd, 0, SEEK_SET);
        plat_guest_commit(p, (uint32_t)st.st_size);
        if (read(h->fd, G + p, (size_t)st.st_size) < 0)
            return 0;
        return p + a[3];
    }
}

/* ---- profile (ini) files ----------------------------------------------------------------------------------------------------------- */
/* The value of `key` in `[section]` of the guest file, or NULL. */
static char *ini_lookup(const char *file, const char *section, const char *key, char *out, size_t cap)
{
    char host[1200], line[512], cur[128] = "";
    FILE *f;
    int ok = paths_host(file, 0, host, sizeof(host));

    if (!ok || !(f = fopen(host, "r")))
        return NULL;
    while (fgets(line, sizeof(line), f)) {
        char *s = line, *e, *eq;

        while (*s == ' ' || *s == '\t')
            s++;
        e = s + strlen(s);
        while (e > s && (e[-1] == '\n' || e[-1] == '\r' || e[-1] == ' ' || e[-1] == '\t'))
            *--e = 0;
        if (*s == '[' && e > s && e[-1] == ']') {
            snprintf(cur, sizeof(cur), "%.*s", (int)(e - s - 2), s + 1);
        } else if ((eq = strchr(s, '=')) && !strcasecmp(cur, section)) {
            char *k = s, *kend = eq;

            while (kend > k && (kend[-1] == ' ' || kend[-1] == '\t'))
                kend--;
            *kend = 0;
            if (!strcasecmp(k, key)) {
                char *v = eq + 1;

                while (*v == ' ' || *v == '\t')
                    v++;
                snprintf(out, cap, "%s", v);
                fclose(f);
                return out;
            }
        }
    }
    fclose(f);
    return NULL;
}

static uint32_t GetPrivateProfileIntA(const uint32_t *a)
{
    char buf[128];
    char *v = ini_lookup(P(a[3]), P(a[0]), P(a[1]), buf, sizeof(buf));
    char *end;
    long n;

    if (!v)
        return a[2];
    n = strtol(v, &end, 10);
    return *end ? a[2] : (uint32_t)n;
}

static uint32_t GetPrivateProfileStringA(const uint32_t *a)
{
    char buf[512];
    const char *v = ini_lookup(P(a[5]), P(a[0]), P(a[1]), buf, sizeof(buf));
    size_t n;

    if (!v)
        v = P(a[2]);
    n = strlen(v);
    if (a[4] == 0)
        return 0;
    if (n > a[4] - 1)
        n = a[4] - 1;
    memcpy(P(a[3]), v, n);
    P(a[3])[n] = 0;
    return (uint32_t)n;
}

/* ---- resources --------------------------------------------------------------------------------------------------------------------- */
static uint32_t FindResourceA(const uint32_t *a)
{
    uint32_t addr, size;

    if (!pe_find_resource(a[0], a[2], a[1], &addr, &size))
        return 0;
    return new_handle((Handle){H_RESOURCE, -1, NULL, addr, size, NULL});
}

static uint32_t LockResource(const uint32_t *a)
{
    Handle *h = get_handle(a[0]);

    return h && h->kind == H_RESOURCE ? h->a : 0;
}

/* ---- winmm: multimedia timers run their callback on a short-lived thread, like the real timer thread does ------------------------------ */
typedef struct MmTimer { uint32_t id, delay, cb, user, next; int periodic, used; GThread *running; } MmTimer;
static MmTimer *mmt;
static int nmmt, capmmt;

static uint32_t timeSetEvent(const uint32_t *a)
{
    MmTimer *t;

    if (nmmt == capmmt) {
        capmmt = capmmt ? capmmt * 2 : 8;
        mmt = realloc(mmt, (size_t)capmmt * sizeof(*mmt));
    }
    t = &mmt[nmmt];
    *t = (MmTimer){(uint32_t)nmmt + 1, a[0] ? a[0] : 1, a[2], a[3], port_now_ms() + (a[0] ? a[0] : 1), (a[4] & 1) != 0, 1, NULL};
    port_trace("timeSetEvent(delay=%u, cb=0x%08x, %s) -> %u", a[0], a[2], t->periodic ? "periodic" : "one-shot", t->id);
    nmmt++;
    return t->id;
}

static uint32_t timeKillEvent(const uint32_t *a)
{
    if (a[0] >= 1 && a[0] <= (uint32_t)nmmt)
        mmt[a[0] - 1].used = 0;
    return 0;
}

/* PORT_SHOT=file.ppm PORT_SHOT_AT=seconds[,seconds...]: write the composed screen at those times (the first to FILE, the next to FILE.1, ...). */
static void maybe_shot(void)
{
    static double at[16];
    static int n, done, parsed;
    const char *file = getenv("PORT_SHOT");

    if (!file)
        return;
    if (!parsed) {
        char *spec = getenv("PORT_SHOT_AT") ? strdup(getenv("PORT_SHOT_AT")) : strdup("10"), *tok, *save;

        parsed = 1;
        for (tok = strtok_r(spec, ",", &save); tok && n < 16; tok = strtok_r(NULL, ",", &save))
            at[n++] = atof(tok);
        free(spec);
    }
    if (done < n && port_now() >= at[done]) {
        char path[1100];

        if (done)
            snprintf(path, sizeof(path), "%s.%d", file, done);
        else
            snprintf(path, sizeof(path), "%s", file);
        compose_write_ppm(path);
        port_log("screen written to %s at %.1f s", path, port_now());
        done++;
    }
}

static void poll_timers(void)
{
    uint32_t now = port_now_ms();
    int i;

    maybe_shot();

    for (i = 0; i < nmmt; i++) {
        MmTimer *t = &mmt[i];

        if (!t->used || t->next > now)
            continue;
        if (t->running && !sched_thread_done(t->running))
            continue;                                              /* the previous tick is still running: skip this one */
        {
            /* the callback takes (id, msg, user, dw1, dw2): spawn a thread that calls it */
            t->running = sched_spawn_timer(t->cb, t->id, t->user);
        }
        if (t->periodic)
            t->next = now + t->delay;
        else
            t->used = 0;
    }
}

void kernel32_init(void)
{
    sched_poll_hook = poll_timers;
}

static uint32_t timeBeginPeriod(const uint32_t *a) { (void)a; return 0; }

/* (the registry is winsys.c's: nothing is stored, a few values of Windows' own are answered) */
void k32_set_last_error(uint32_t code) { last_error_code = code; }

const WinApi KERNEL32_APIS[] = {
    {"kernel32.dll", "GetVersion", GetVersion}, {"kernel32.dll", "GetCurrentProcess", GetCurrentProcess},
    {"kernel32.dll", "GetCurrentThread", GetCurrentThread}, {"kernel32.dll", "GetLastError", GetLastError},
    {"kernel32.dll", "SetLastError", SetLastError}, {"kernel32.dll", "GetTickCount", GetTickCount},
    {"kernel32.dll", "OutputDebugStringA", OutputDebugStringA}, {"kernel32.dll", "lstrlenA", lstrlenA},
    {"kernel32.dll", "InitializeCriticalSection", InitializeCriticalSection}, {"kernel32.dll", "DeleteCriticalSection", zero},
    {"kernel32.dll", "EnterCriticalSection", EnterCriticalSection}, {"kernel32.dll", "LeaveCriticalSection", LeaveCriticalSection},
    {"kernel32.dll", "GetCurrentThreadId", GetCurrentThreadId}, {"kernel32.dll", "GetThreadPriority", GetThreadPriority},
    {"kernel32.dll", "SetThreadPriority", one}, {"kernel32.dll", "GetPriorityClass", GetPriorityClass}, {"kernel32.dll", "SetPriorityClass", one}, {"kernel32.dll", "DuplicateHandle", DuplicateHandle},
    {"kernel32.dll", "GetExitCodeThread", GetExitCodeThread}, {"kernel32.dll", "ExitThread", ExitThread},
    {"kernel32.dll", "CloseHandle", CloseHandle}, {"kernel32.dll", "WaitForSingleObject", WaitForSingleObject},
    {"kernel32.dll", "DeviceIoControl", DeviceIoControl}, {"kernel32.dll", "Sleep", Sleep},
    {"kernel32.dll", "GetModuleHandleA", GetModuleHandleA}, {"kernel32.dll", "GetModuleFileNameA", GetModuleFileNameA},
    {"kernel32.dll", "GetCurrentDirectoryA", GetCurrentDirectoryA}, {"kernel32.dll", "GetStartupInfoA", GetStartupInfoA},
    {"kernel32.dll", "GetDriveTypeA", GetDriveTypeA}, {"kernel32.dll", "LoadLibraryA", LoadLibraryA},
    {"kernel32.dll", "FreeLibrary", one}, {"kernel32.dll", "GetProcAddress", GetProcAddress}, {"kernel32.dll", "GlobalAlloc", GlobalAlloc},
    {"kernel32.dll", "GlobalLock", identity}, {"kernel32.dll", "GlobalUnlock", one}, {"kernel32.dll", "GlobalHandle", identity},
    {"kernel32.dll", "GlobalFree", GlobalFree}, {"kernel32.dll", "CreateFileA", CreateFileA}, {"kernel32.dll", "ReadFile", ReadFile}, {"kernel32.dll", "WriteFile", WriteFile}, {"kernel32.dll", "DeleteFileA", DeleteFileA},
    {"kernel32.dll", "GetFileSize", GetFileSize}, {"kernel32.dll", "CopyFileA", CopyFileA},
    {"kernel32.dll", "CreateFileMappingA", CreateFileMappingA}, {"kernel32.dll", "MapViewOfFile", MapViewOfFile},
    {"kernel32.dll", "UnmapViewOfFile", one}, {"kernel32.dll", "CreateThread", CreateThread},
    {"msvcrtd.dll", "_beginthreadex", CreateThread},         /* (security, stack size, start, argument, flags, &thread id): the arguments of CreateThread, and a handle back */
    {"kernel32.dll", "GetPrivateProfileIntA", GetPrivateProfileIntA}, {"kernel32.dll", "GetPrivateProfileStringA", GetPrivateProfileStringA},
    {"kernel32.dll", "FindResourceA", FindResourceA}, {"kernel32.dll", "LoadResource", identity}, {"kernel32.dll", "LockResource", LockResource},
    {"winmm.dll", "timeBeginPeriod", timeBeginPeriod}, {"winmm.dll", "timeEndPeriod", zero}, {"winmm.dll", "timeSetEvent", timeSetEvent},
    {"winmm.dll", "timeKillEvent", timeKillEvent},
    {"shell32.dll", "SHAppBarMessage", zero}, {"comctl32.dll", "#17", zero},
    {0, 0, 0},
};

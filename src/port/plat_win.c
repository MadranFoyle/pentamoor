/* plat_win.c - plat.h on Windows (MinGW-w64). The only file of the runtime that includes <windows.h>. (plat_posix.c is the other.) */
#ifdef _WIN32
#include <direct.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <windows.h>

#include "plat.h"

/* timeBeginPeriod / timeEndPeriod are winmm's; declared here so that <mmsystem.h> (and its pile of names) stays out. */
__declspec(dllimport) unsigned int __stdcall timeBeginPeriod(unsigned int ms);

void plat_init(void)
{
    static int done;

    if (done)
        return;
    done = 1;
    SetErrorMode(SEM_FAILCRITICALERRORS);       /* a missing library or an empty drive is an error code, not a dialog */
    timeBeginPeriod(1);                         /* Sleep(5) sleeps about 5 ms, not up to 16 */
}

/* ---- the guest's address space ------------------------------------------------------------------------------------------------------ */
/* The 4 GB are reserved (no memory is charged) and committed a megabyte at a time, by the exception handler below, the first time a page is touched: the
 * same as mmap(MAP_NORESERVE) on POSIX, where the first touch of a page gives a zero page. A committed page is zero, and committing a page again leaves it as it is,
 * so two threads that fault in the same megabyte at once do no harm. */
#define CHUNK_BITS 20
#define NCHUNKS (1u << (32 - CHUNK_BITS))

static uint8_t *guest_base;
static volatile uint8_t chunk_ok[NCHUNKS];

static int commit_chunk(uint32_t i)
{
    if (!chunk_ok[i]) {
        if (!VirtualAlloc(guest_base + ((size_t)i << CHUNK_BITS), (size_t)1 << CHUNK_BITS, MEM_COMMIT, PAGE_READWRITE))
            return 0;
        chunk_ok[i] = 1;
    }
    return 1;
}

static LONG CALLBACK guest_fault(EXCEPTION_POINTERS *ep)
{
    const EXCEPTION_RECORD *er = ep->ExceptionRecord;
    uintptr_t at;

    if (er->ExceptionCode != EXCEPTION_ACCESS_VIOLATION || er->NumberParameters < 2 || !guest_base)
        return EXCEPTION_CONTINUE_SEARCH;
    at = (uintptr_t)er->ExceptionInformation[1];
    if (at < (uintptr_t)guest_base || at - (uintptr_t)guest_base >= ((uint64_t)1 << 32))
        return EXCEPTION_CONTINUE_SEARCH;
    return commit_chunk((uint32_t)((at - (uintptr_t)guest_base) >> CHUNK_BITS)) ? EXCEPTION_CONTINUE_EXECUTION : EXCEPTION_CONTINUE_SEARCH;
}

uint8_t *plat_guest_reserve(void)
{
    void *p = VirtualAlloc(NULL, (size_t)1 << 32, MEM_RESERVE, PAGE_READWRITE);

    if (!p)
        return NULL;
    guest_base = p;
    if (!AddVectoredExceptionHandler(1, guest_fault))
        return NULL;
    return guest_base;
}

void plat_guest_commit(uint32_t addr, uint32_t len)
{
    uint64_t last;
    uint32_t i;

    if (!guest_base || !len)
        return;
    last = (uint64_t)addr + len - 1;
    if (last > 0xFFFFFFFFull)
        last = 0xFFFFFFFFull;
    for (i = addr >> CHUNK_BITS; i <= (uint32_t)(last >> CHUNK_BITS); i++)
        commit_chunk(i);
}

/* ---- the game module ------------------------------------------------------------------------------------------------------------------ */
void *plat_dlopen(const char *path, char *err, size_t n)
{
    char full[MAX_PATH * 2];
    HMODULE h;
    DWORD code, len = GetFullPathNameA(path, sizeof(full), full, NULL);

    if (!len || len >= sizeof(full))
        snprintf(full, sizeof(full), "%s", path);
    /* the module's own folder is searched for the libraries it needs (there are none beyond the system's, but a release may ship one) */
    h = LoadLibraryExA(full, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (!h) {
        char msg[300] = "";
        size_t k;

        code = GetLastError();
        FormatMessageA(FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS, NULL, code, 0, msg, sizeof(msg), NULL);
        for (k = strlen(msg); k > 0 && (msg[k - 1] == '\r' || msg[k - 1] == '\n' || msg[k - 1] == ' ' || msg[k - 1] == '.'); k--)
            msg[k - 1] = 0;
        snprintf(err, n, "%s (Windows error %lu)", msg[0] ? msg : "LoadLibrary failed", (unsigned long)code);
    }
    return h;
}

void *plat_dlsym(void *lib, const char *name)
{
    FARPROC p = GetProcAddress((HMODULE)lib, name);
    void *r;

    memcpy(&r, &p, sizeof(r));
    return r;
}

/* ---- small things ------------------------------------------------------------------------------------------------------------------- */
int plat_mkdir(const char *path) { return _mkdir(path); }
struct tm *plat_localtime(const time_t *t, struct tm *out) { return localtime_s(out, t) == 0 ? out : NULL; }
struct tm *plat_gmtime(const time_t *t, struct tm *out) { return gmtime_s(out, t) == 0 ? out : NULL; }

static int file_identity(const char *path, BY_HANDLE_FILE_INFORMATION *info)
{
    HANDLE h = CreateFileA(path, 0, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, NULL, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, NULL);
    BOOL ok;

    if (h == INVALID_HANDLE_VALUE)
        return 0;
    ok = GetFileInformationByHandle(h, info);
    CloseHandle(h);
    return ok;
}

int plat_same_file(const char *a, const char *b)
{
    BY_HANDLE_FILE_INFORMATION i1, i2;

    return file_identity(a, &i1) && file_identity(b, &i2) && i1.dwVolumeSerialNumber == i2.dwVolumeSerialNumber && i1.nFileIndexHigh == i2.nFileIndexHigh &&
           i1.nFileIndexLow == i2.nFileIndexLow;
}

int plat_is_executable(const char *path)
{
    DWORD a = GetFileAttributesA(path);

    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}

/* cmd.exe /c strips the first and last quote of a command line that begins with one: one more pair around it keeps the command's own. */
static char *wrap_command(const char *cmd)
{
    size_t n = strlen(cmd) + 3;
    char *wrapped = malloc(n);

    if (wrapped)
        snprintf(wrapped, n, "\"%s\"", cmd);
    return wrapped;
}

FILE *plat_popen_read(const char *cmd)
{
    char *wrapped = wrap_command(cmd);
    FILE *f;

    if (!wrapped)
        return NULL;
    f = _popen(wrapped, "rb");
    free(wrapped);
    return f;
}

int plat_system(const char *cmd)
{
    char *wrapped = wrap_command(cmd);
    int r;

    if (!wrapped)
        return -1;
    r = system(wrapped);
    free(wrapped);
    return r;
}

int plat_pclose(FILE *f) { return _pclose(f); }

/* ---- starting another program ------------------------------------------------------------------------------------------------------ */
int plat_self_path(char *out, size_t cap)
{
    DWORD n = GetModuleFileNameA(NULL, out, (DWORD)cap);

    return n > 0 && n < cap;
}

/* One argument as CreateProcess's command line wants it: in quotes when it is empty or holds a space or a quote (a quote inside is escaped). */
static size_t quote_arg(char *out, size_t cap, const char *arg)
{
    size_t n = 0;
    int quote = !*arg || strpbrk(arg, " \t\"") != NULL;

    if (quote && n + 1 < cap)
        out[n++] = '"';
    for (; *arg && n + 2 < cap; arg++) {
        if (*arg == '"')
            out[n++] = '\\';
        out[n++] = *arg;
    }
    if (quote && n + 1 < cap)
        out[n++] = '"';
    out[n] = 0;
    return n;
}

static HANDLE children[64];

int plat_spawn(const char *const *argv, const char *const *set, const char *const *unset, long *id)
{
    char cmd[8192], *block, *e, *w;
    size_t n = 0, size = 0, i, j;
    STARTUPINFOA si;
    PROCESS_INFORMATION pi;
    char *env = GetEnvironmentStringsA();
    int slot;

    for (slot = 0; slot < 64 && children[slot]; slot++)
        ;
    if (slot == 64 || !env)
        return -1;
    cmd[0] = 0;
    for (i = 0; argv[i] && n + 4 < sizeof(cmd); i++) {
        if (i)
            cmd[n++] = ' ';
        n += quote_arg(cmd + n, sizeof(cmd) - n, argv[i]);
    }
    for (e = env; *e; e += strlen(e) + 1)
        size += strlen(e) + 1;
    for (i = 0; set && set[i]; i++)
        size += strlen(set[i]) + 1;
    block = malloc(size + 2);
    if (!block) {
        FreeEnvironmentStringsA(env);
        return -1;
    }
    w = block;
    for (e = env; *e; e += strlen(e) + 1) {          /* this process's environment, less what is unset or replaced (a name is compared without regard to case, as Windows does) */
        int drop = 0;

        for (j = 0; unset && unset[j]; j++)
            if (!_strnicmp(e, unset[j], strlen(unset[j])) && e[strlen(unset[j])] == '=')
                drop = 1;
        for (j = 0; set && set[j]; j++) {
            const char *eq = strchr(set[j], '=');

            if (eq && !_strnicmp(e, set[j], (size_t)(eq - set[j])) && e[eq - set[j]] == '=')
                drop = 1;
        }
        if (!drop) {
            strcpy(w, e);
            w += strlen(e) + 1;
        }
    }
    for (i = 0; set && set[i]; i++) {
        strcpy(w, set[i]);
        w += strlen(set[i]) + 1;
    }
    *w = 0;
    FreeEnvironmentStringsA(env);
    memset(&si, 0, sizeof(si));
    si.cb = sizeof(si);
    fflush(NULL);
    if (!CreateProcessA(argv[0], cmd, NULL, NULL, FALSE, 0, block, NULL, &si, &pi)) {
        free(block);
        return -1;
    }
    free(block);
    CloseHandle(pi.hThread);
    children[slot] = pi.hProcess;
    *id = slot + 1;
    return 0;
}

int plat_child_state(long id, int *exit_code)
{
    DWORD code = 0;
    HANDLE h;

    if (id < 1 || id > 64 || !children[id - 1])
        return -1;
    h = children[id - 1];
    if (WaitForSingleObject(h, 0) != WAIT_OBJECT_0)
        return 0;
    GetExitCodeProcess(h, &code);
    CloseHandle(h);
    children[id - 1] = NULL;
    *exit_code = (int)code;
    return 1;
}

int plat_pid_alive(long pid)
{
    HANDLE h;
    int alive;

    if (pid <= 0)
        return 0;
    h = OpenProcess(SYNCHRONIZE, FALSE, (DWORD)pid);
    if (!h)
        return GetLastError() == ERROR_ACCESS_DENIED;
    alive = WaitForSingleObject(h, 0) == WAIT_TIMEOUT;
    CloseHandle(h);
    return alive;
}

int plat_make_control(const char *path)
{
    FILE *f = fopen(path, "ab");

    if (!f)
        return -1;
    fclose(f);
    return 0;
}
#endif

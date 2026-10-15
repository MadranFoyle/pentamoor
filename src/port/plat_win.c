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
#endif

/* kernel32_rt.c - the kernel32 calls a statically linked C runtime makes at start-up and for its heap (DECK.EXE and DUEL.EXE carry their own copy of the
 * runtime; MAGIC.EXE uses MSVCRTD.DLL), plus locale, time and a few file calls. Port of winemu/kernel32_rt.py. */
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "plat.h"
#include "port.h"
#include "process.h"

#define P(a) ((char *)(G + (uint32_t)(a)))

int k32_file_fd(uint32_t h);
extern Image main_image;

static uint32_t one(const uint32_t *a) { (void)a; return 1; }
static uint32_t zero(const uint32_t *a) { (void)a; return 0; }
static uint32_t first(const uint32_t *a) { return a[0]; }

/* ---- heap and virtual memory ----------------------------------------------------------------------------------------------------- */
static uint32_t HeapCreate(const uint32_t *a) { (void)a; return 0x7000u; }
static uint32_t HeapAlloc(const uint32_t *a)
{
    uint32_t p = heap_alloc(a[2]);

    if (p && (a[1] & 8))
        guest_zero(p, a[2]);
    return p;
}
static uint32_t HeapFree(const uint32_t *a) { heap_free(a[2]); return 1; }
static uint32_t HeapReAlloc(const uint32_t *a)                     /* HeapReAlloc(heap, flags, ptr, size) */
{
    uint32_t q = heap_alloc(a[3]), n;

    if (!q)
        return 0;
    if (a[1] & 8)
        guest_zero(q, a[3]);
    if (a[2]) {
        n = heap_size(a[2]);
        if (n > a[3])
            n = a[3];
        memcpy(G + q, G + a[2], n);
        heap_free(a[2]);
    }
    return q;
}
static uint32_t HeapSize(const uint32_t *a) { return heap_size(a[2]); }
static uint32_t VirtualAlloc(const uint32_t *a)                    /* VirtualAlloc(addr, size, type, protect): the heap's, rounded up to a page */
{
    uint32_t p = heap_alloc(a[1] + 4096);

    if (!p)
        return 0;
    guest_zero(p, a[1] + 4096);
    return (p + 4095) & ~4095u;
}

static uint32_t InterlockedIncrement(const uint32_t *a) { WR32(a[0], RD32(a[0]) + 1); return RD32(a[0]); }
static uint32_t InterlockedDecrement(const uint32_t *a) { WR32(a[0], RD32(a[0]) - 1); return RD32(a[0]); }

/* ---- process ----------------------------------------------------------------------------------------------------------------------- */
static uint32_t ExitProcess(const uint32_t *a) { fflush(NULL); exit((int)a[0]); }
static uint32_t TerminateProcess(const uint32_t *a) { fflush(NULL); exit((int)a[1]); }
static uint32_t GetStdHandle(const uint32_t *a) { return 0x10u + (a[0] > 0xFFFFFFF0u ? 0xFFFFFFFFu - a[0] : 0u); }       /* -10, -11, -12 */
static uint32_t GetFileType(const uint32_t *a)                    /* 1 disk file, 2 character device */
{
    return a[0] >= 0x10 && a[0] <= 0x12 ? 2 : k32_file_fd(a[0]) >= 0 ? 1 : 2;
}

static uint32_t cmdline, env;
static uint32_t GetCommandLineA(const uint32_t *a)
{
    (void)a;
    if (!cmdline) {
        char line[700];

        proc_command_line(line, sizeof(line));           /* the program's path and the arguments the program that started this one gave (process.h) */
        cmdline = heap_alloc((uint32_t)strlen(line) + 1);
        strcpy(P(cmdline), line);
    }
    return cmdline;
}
static uint32_t GetEnvironmentStrings(const uint32_t *a)           /* an empty block: a double terminator */
{
    (void)a;
    if (!env) {
        env = heap_alloc(16);
        guest_zero(env, 16);
    }
    return env;
}

static uint32_t SetCurrentDirectoryA(const uint32_t *a)
{
    char norm[300], host[1200];
    struct stat st;

    if (paths_host(P(a[0]), 0, host, sizeof(host)) && !stat(host, &st) && !S_ISDIR(st.st_mode)) {
        k32_set_last_error(267);                                /* ERROR_DIRECTORY: a file is not a place to stand (FaceMaker.exe passes its own path, and goes on where it was) */
        return 0;
    }
    paths_normalize(P(a[0]), norm, sizeof(norm));
    snprintf(guest_cwd, sizeof(guest_cwd), "%s", norm);
    return 1;
}
static uint32_t CreateDirectoryA(const uint32_t *a)
{
    char host[1200];

    paths_host(P(a[0]), 1, host, sizeof(host));
    paths_mkdirs(host);
    return 1;
}

/* ---- files ------------------------------------------------------------------------------------------------------------------------- */
static uint32_t SetFilePointer(const uint32_t *a)                  /* SetFilePointer(file, low, *high, method) */
{
    int fd = k32_file_fd(a[0]);
    off_t r;

    if (fd < 0)
        return 0xFFFFFFFFu;
    r = lseek(fd, (off_t)(int32_t)a[1], (int)a[3]);                   /* FILE_BEGIN/CURRENT/END are SEEK_SET/CUR/END */
    return r < 0 ? 0xFFFFFFFFu : (uint32_t)r;
}

/* ---- locale and strings -------------------------------------------------------------------------------------------------------- */
static uint32_t GetACP(const uint32_t *a) { (void)a; return 1252; }
static uint32_t GetOEMCP(const uint32_t *a) { (void)a; return 437; }
static uint32_t GetCPInfo(const uint32_t *a)
{
    guest_zero(a[1], 20);
    WR32(a[1], 1);                                                   /* MaxCharSize */
    G[a[1] + 4] = 0x3F;                                              /* the default character */
    return 1;
}

static int clamp3(int c) { return c < 0 ? 1 : c > 0 ? 3 : 2; }       /* CSTR_LESS_THAN, CSTR_GREATER_THAN, CSTR_EQUAL */
static uint32_t CompareStringA(const uint32_t *a)                  /* CompareStringA(locale, flags, s1, n1, s2, n2) */
{
    const char *x = P(a[2]), *y = P(a[4]);
    size_t nx = a[3] == 0xFFFFFFFFu ? strlen(x) : a[3], ny = a[5] == 0xFFFFFFFFu ? strlen(y) : a[5], n = nx < ny ? nx : ny, i;
    int c = 0;

    for (i = 0; i < n && !c; i++) {
        int p = (unsigned char)x[i], q = (unsigned char)y[i];

        if (a[1] & 1) { p = tolower(p); q = tolower(q); }
        c = p - q;
    }
    if (!c)
        c = nx < ny ? -1 : nx > ny;
    return (uint32_t)clamp3(c);
}

static uint32_t CompareStringW(const uint32_t *a)                  /* CompareStringW(locale, flags, s1, n1, s2, n2), UTF-16 units */
{
    uint32_t nx = a[3], ny = a[5], n, i;
    int c = 0;

    if (nx == 0xFFFFFFFFu)
        for (nx = 0; RD16(a[2] + 2 * nx); nx++) ;
    if (ny == 0xFFFFFFFFu)
        for (ny = 0; RD16(a[4] + 2 * ny); ny++) ;
    n = nx < ny ? nx : ny;
    for (i = 0; i < n && !c; i++) {
        int p = RD16(a[2] + 2 * i), q = RD16(a[4] + 2 * i);

        if (a[1] & 1) {
            if (p >= 'A' && p <= 'Z') p += 32;
            if (q >= 'A' && q <= 'Z') q += 32;
        }
        c = p - q;
    }
    if (!c)
        c = nx < ny ? -1 : nx > ny;
    return (uint32_t)clamp3(c);
}

static uint32_t LCMapStringA(const uint32_t *a)                    /* LCMapStringA(locale, flags, src, n, dest, size) */
{
    uint32_t n = a[3] == 0xFFFFFFFFu ? (uint32_t)strlen(P(a[2])) + 1 : a[3], i;

    for (i = 0; i < n && i < a[5]; i++) {
        int c = (unsigned char)G[a[2] + i];

        if (a[1] & 0x100) c = tolower(c);
        else if (a[1] & 0x200) c = toupper(c);
        G[a[4] + i] = (uint8_t)c;
    }
    return n;
}
static uint32_t LCMapStringW(const uint32_t *a)
{
    uint32_t n = a[3], i;

    if (n == 0xFFFFFFFFu)
        for (n = 0; RD16(a[2] + 2 * n); n++)
            ;
    if (a[3] == 0xFFFFFFFFu)
        n++;
    for (i = 0; i < n && i < a[5]; i++) {
        uint32_t c = RD16(a[2] + 2 * i);

        if (c < 128 && (a[1] & 0x100)) c = (uint32_t)tolower((int)c);
        else if (c < 128 && (a[1] & 0x200)) c = (uint32_t)toupper((int)c);
        WR16(a[4] + 2 * i, c);
    }
    return n;
}

static uint32_t MultiByteToWideChar(const uint32_t *a)             /* (codepage, flags, src, n, dest, size) */
{
    uint32_t n = a[3] == 0xFFFFFFFFu ? (uint32_t)strlen(P(a[2])) + 1 : a[3], i;

    if (a[5])
        for (i = 0; i < n && i < a[5]; i++)
            WR16(a[4] + 2 * i, G[a[2] + i]);
    return n;
}
static uint32_t WideCharToMultiByte(const uint32_t *a)             /* (codepage, flags, src, n, dest, size, default, *used) */
{
    uint32_t n = a[3], i;

    if (n == 0xFFFFFFFFu) {
        for (n = 0; RD16(a[2] + 2 * n); n++)
            ;
        n++;
    }
    if (a[5])
        for (i = 0; i < n && i < a[5]; i++)
            G[a[4] + i] = (uint8_t)RD16(a[2] + 2 * i);
    return n;
}

/* CT_CTYPE1 for a character of the C locale. */
static uint32_t ctype1(unsigned c)
{
    uint32_t f = 0;

    if (c > 255)
        return 0;
    if (isupper((int)c)) f |= 0x01;
    if (islower((int)c)) f |= 0x02;
    if (isdigit((int)c)) f |= 0x04;
    if (isspace((int)c)) f |= 0x08;
    if (ispunct((int)c)) f |= 0x10;
    if (iscntrl((int)c)) f |= 0x20;
    if (c == ' ' || c == '\t') f |= 0x40;
    if (isxdigit((int)c)) f |= 0x80;
    if (isalpha((int)c)) f |= 0x100;
    return f;
}
static uint32_t GetStringTypeW(const uint32_t *a)                  /* (type, src, n, out) */
{
    uint32_t i, n = a[2] == 0xFFFFFFFFu ? 0 : a[2];

    for (i = 0; i < n; i++)
        WR16(a[3] + 2 * i, ctype1(RD16(a[1] + 2 * i)));
    return 1;
}
static uint32_t GetStringTypeA(const uint32_t *a)                  /* (locale, type, src, n, out) */
{
    uint32_t i, n = a[3] == 0xFFFFFFFFu ? (uint32_t)strlen(P(a[2])) : a[3];

    for (i = 0; i < n; i++)
        WR16(a[4] + 2 * i, ctype1(G[a[2] + i]));
    return 1;
}

/* ---- time ---------------------------------------------------------------------------------------------------------------------- */
static void systemtime(uint32_t p, const struct tm *t)
{
    WR16(p, (uint32_t)t->tm_year + 1900); WR16(p + 2, (uint32_t)t->tm_mon + 1); WR16(p + 4, (uint32_t)t->tm_wday); WR16(p + 6, (uint32_t)t->tm_mday);
    WR16(p + 8, (uint32_t)t->tm_hour); WR16(p + 10, (uint32_t)t->tm_min); WR16(p + 12, (uint32_t)t->tm_sec); WR16(p + 14, 0);
}
static uint32_t GetLocalTime(const uint32_t *a) { time_t n = time(NULL); struct tm t; plat_localtime(&n, &t); systemtime(a[0], &t); return 0; }
static uint32_t GetSystemTime(const uint32_t *a) { time_t n = time(NULL); struct tm t; plat_gmtime(&n, &t); systemtime(a[0], &t); return 0; }
static uint32_t GetTimeZoneInformation(const uint32_t *a) { guest_zero(a[0], 172); return 0; }

/* GetDateFormatA(locale, flags, *systemtime, format, buffer, size): the date as "Mon dd, yyyy"-style text in the one format the game asks for; returns the length with its NUL
 * (or the length needed when size is 0). */
static uint32_t GetDateFormatA(const uint32_t *a)
{
    static const char *months[] = {"January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"};
    char text[80];
    uint32_t y = 2000, mo = 1, d = 1, n;

    if (a[2]) {
        y = RD16(a[2]); mo = RD16(a[2] + 2); d = RD16(a[2] + 6);
    } else {
        time_t now = time(NULL);
        struct tm t;

        plat_localtime(&now, &t);
        y = (uint32_t)t.tm_year + 1900; mo = (uint32_t)t.tm_mon + 1; d = (uint32_t)t.tm_mday;
    }
    snprintf(text, sizeof(text), "%s %u, %u", months[(mo ? mo - 1 : 0) % 12], d, y);
    n = (uint32_t)strlen(text) + 1;
    if (a[5] >= n && a[4])
        memcpy(P(a[4]), text, n);
    else if (a[5])
        return 0;
    return n;
}

const WinApi KERNEL32_RT_APIS[] = {
    {"kernel32.dll", "GetDateFormatA", GetDateFormatA},
    {"kernel32.dll", "HeapCreate", HeapCreate}, {"kernel32.dll", "HeapDestroy", one}, {"kernel32.dll", "HeapValidate", one}, {"kernel32.dll", "HeapFree", HeapFree},
    {"kernel32.dll", "HeapAlloc", HeapAlloc}, {"kernel32.dll", "HeapReAlloc", HeapReAlloc}, {"kernel32.dll", "HeapSize", HeapSize},
    {"kernel32.dll", "VirtualAlloc", VirtualAlloc}, {"kernel32.dll", "VirtualFree", one}, {"kernel32.dll", "IsBadReadPtr", zero}, {"kernel32.dll", "IsBadWritePtr", zero},
    {"kernel32.dll", "InterlockedIncrement", InterlockedIncrement}, {"kernel32.dll", "InterlockedDecrement", InterlockedDecrement},
    {"kernel32.dll", "ExitProcess", ExitProcess}, {"kernel32.dll", "TerminateProcess", TerminateProcess}, {"kernel32.dll", "UnhandledExceptionFilter", zero},
    {"kernel32.dll", "RtlUnwind", zero}, {"kernel32.dll", "DebugBreak", zero}, {"kernel32.dll", "SetConsoleCtrlHandler", one}, {"kernel32.dll", "SetHandleCount", first},
    {"kernel32.dll", "SetEnvironmentVariableA", one}, {"kernel32.dll", "GetStdHandle", GetStdHandle}, {"kernel32.dll", "SetStdHandle", one},
    {"kernel32.dll", "GetFileType", GetFileType}, {"kernel32.dll", "GetCommandLineA", GetCommandLineA}, {"kernel32.dll", "GetEnvironmentStrings", GetEnvironmentStrings},
    {"kernel32.dll", "GetEnvironmentStringsW", GetEnvironmentStrings}, {"kernel32.dll", "FreeEnvironmentStringsA", one}, {"kernel32.dll", "FreeEnvironmentStringsW", one},
    {"kernel32.dll", "SetCurrentDirectoryA", SetCurrentDirectoryA}, {"kernel32.dll", "CreateDirectoryA", CreateDirectoryA},
    {"kernel32.dll", "SetFilePointer", SetFilePointer}, {"kernel32.dll", "SetEndOfFile", one}, {"kernel32.dll", "FlushFileBuffers", one},
    {"kernel32.dll", "GetACP", GetACP}, {"kernel32.dll", "GetOEMCP", GetOEMCP}, {"kernel32.dll", "GetCPInfo", GetCPInfo}, {"kernel32.dll", "CompareStringA", CompareStringA}, {"kernel32.dll", "CompareStringW", CompareStringW},
    {"kernel32.dll", "LCMapStringA", LCMapStringA}, {"kernel32.dll", "LCMapStringW", LCMapStringW}, {"kernel32.dll", "MultiByteToWideChar", MultiByteToWideChar},
    {"kernel32.dll", "WideCharToMultiByte", WideCharToMultiByte}, {"kernel32.dll", "GetStringTypeW", GetStringTypeW}, {"kernel32.dll", "GetStringTypeA", GetStringTypeA},
    {"kernel32.dll", "GetLocalTime", GetLocalTime}, {"kernel32.dll", "GetSystemTime", GetSystemTime}, {"kernel32.dll", "GetTimeZoneInformation", GetTimeZoneInformation},
    {0, 0, 0},
};

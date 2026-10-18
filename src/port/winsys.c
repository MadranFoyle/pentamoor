/* winsys.c - what the game asks Windows about itself and its machine: the version, the Windows folder, the disks, the locale, a thread's own slots (TLS), error text, and the registry.
 *
 * None of these is part of the game; they are answers the Windows of the original machine gave, and the answers here are those of a plain Windows 98 Second Edition on a fixed disk
 * (kernel32.c's GetVersion says the same). Spells of the Ancients' programs and libraries ask more than 1.0's did: the C runtime they carry asks for the locale and keeps per-thread
 * data in TLS, the CD library asks about drives, and the game and its deck library read two values of Windows' own registry key at start (below). Each answer is a fixed one so a
 * run is the same on every machine.
 *
 * THE REGISTRY. Nothing is stored: a key is a path and a handle, a write goes nowhere (RegSetValueExA succeeds and the value is not kept, as before), a read of anything but the table
 * below is "not found", so a program falls back to its defaults. The table holds the values the game asks Windows for: shandalar.exe 2.15 and its deck library open
 * HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows\CurrentVersion at start and read the two values of Windows 98 that identify the installation (when it was installed, and the product
 * id); without them the program ends at once. They are made-up values of the same kind, the same on every run.
 * WHAT THEY ARE FOR (traced in milestone 3, docs/notes/sota-comparison.md "The licence value"): the game builds a machine id from them, and a second function reads a machine-bound
 * value "SerialNumber" (HKLM\SOFTWARE\MicroProse\Magic: The Gathering) that only makes sense together with that id; it gates the game's CD check and the cards of two sets. This file
 * answers the two Windows values so that the program starts, and nothing else: it does not make up a SerialNumber (a read of it is "not found") and it does not pretend to be a CD.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "port.h"
#include "sched.h"

#define P(a) ((char *)(G + (a)))
#define ERROR_FILE_NOT_FOUND 2
#define ERROR_INSUFFICIENT_BUFFER 122
#define ERROR_MORE_DATA 234

static uint32_t zero(const uint32_t *a) { (void)a; return 0; }

/* ---- the version and the folders --------------------------------------------------------------------------------------------------- */
/* OSVERSIONINFOA: size, major, minor, build (the high word is the version again on Windows 9x), platform (1 = Windows 9x), the service pack string. Windows 98 SE is 4.10.2222 A. */
static uint32_t GetVersionExA(const uint32_t *a)
{
    uint32_t size = RD32(a[0]);

    if (size < 20)
        return 0;
    WR32(a[0] + 4, 4);
    WR32(a[0] + 8, 10);
    WR32(a[0] + 12, 0x040A08AEu);
    WR32(a[0] + 16, 1);
    if (size >= 148) {
        guest_zero(a[0] + 20, 128);
        strcpy(P(a[0] + 20), " A");
    }
    return 1;
}

/* Copies `text` into a buffer of `size` bytes: its length without the NUL when it fits, else the size needed with the NUL (and the buffer untouched), as GetWindowsDirectoryA does. */
static uint32_t return_string(uint32_t buf, uint32_t size, const char *text)
{
    uint32_t n = (uint32_t)strlen(text);

    if (!buf || size < n + 1)
        return n + 1;
    memcpy(P(buf), text, n + 1);
    return n;
}

static uint32_t GetWindowsDirectoryA(const uint32_t *a) { return return_string(a[0], a[1], "C:\\WINDOWS"); }

/* Disks. The game is on the fixed disk C: with room to spare (16 KB clusters, 2 GB free of 4 GB: the most Windows 9x's old call reports). */
static uint32_t GetDiskFreeSpaceA(const uint32_t *a)
{
    if (a[1])
        WR32(a[1], 32);             /* sectors per cluster */
    if (a[2])
        WR32(a[2], 512);            /* bytes per sector */
    if (a[3])
        WR32(a[3], 0x20000);        /* free clusters */
    if (a[4])
        WR32(a[4], 0x40000);        /* clusters */
    return 1;
}

/* GetVolumeInformationA(root, label, label size, &serial, &max component, &flags, file system, file system size) of the fixed disk: no label, a FAT32 volume. */
static uint32_t GetVolumeInformationA(const uint32_t *a)
{
    if (a[1] && a[2])
        P(a[1])[0] = 0;
    if (a[3])
        WR32(a[3], 0x3F2A1C07u);
    if (a[4])
        WR32(a[4], 255);
    if (a[5])
        WR32(a[5], 0x6);            /* FS_CASE_IS_PRESERVED | FS_UNICODE_STORED_ON_DISK: a FAT32 volume of Windows 98 keeps the case of a name and ignores it when it compares */
    if (a[6] && a[7] >= 6)
        strcpy(P(a[6]), "FAT32");
    return 1;
}

/* ---- the locale: English (United States), as the C runtime of the game's libraries asks for it at start ---------------------------------- */
static const struct { uint32_t type; const char *text; } LOCALE[] = {
    {0x01, "0409"}, {0x02, "English (United States)"}, {0x03, "ENU"}, {0x04, "English"}, {0x05, "1"}, {0x06, "United States"}, {0x07, "USA"}, {0x08, "United States"},
    {0x09, "0409"}, {0x0A, "1"}, {0x0B, "437"}, {0x0C, ","}, {0x0D, "1"}, {0x0E, "."}, {0x0F, ","}, {0x10, "3;0"}, {0x11, "2"}, {0x12, "1"}, {0x13, "0123456789"},
    {0x14, "$"}, {0x15, "USD"}, {0x16, "."}, {0x17, ","}, {0x18, "3;0"}, {0x19, "2"}, {0x1A, "0"}, {0x1B, "0"}, {0x1C, "/"}, {0x1D, ":"}, {0x1E, "AM"}, {0x1F, "PM"},
    {0x1001, "English"}, {0x1002, "United States"}, {0x1004, "1252"}, {0x1005, "437"},
};

static const char *locale_text(uint32_t type)
{
    size_t i;

    type &= ~0x80000000u;               /* LOCALE_NOUSEROVERRIDE */
    for (i = 0; i < sizeof(LOCALE) / sizeof(LOCALE[0]); i++)
        if (LOCALE[i].type == type)
            return LOCALE[i].text;
    return NULL;
}

/* GetLocaleInfoA(locale, type, buffer, size): the length with the NUL; with a size of 0 only the length; 0 (and an error) for a type not known or a buffer too small. */
static uint32_t GetLocaleInfoA(const uint32_t *a)
{
    const char *t = locale_text(a[1]);
    uint32_t n;

    if (!t) {
        k32_set_last_error(87);                 /* ERROR_INVALID_PARAMETER */
        return 0;
    }
    n = (uint32_t)strlen(t) + 1;
    if (a[3] == 0)
        return n;
    if (a[3] < n) {
        k32_set_last_error(ERROR_INSUFFICIENT_BUFFER);
        return 0;
    }
    memcpy(P(a[2]), t, n);
    return n;
}

static uint32_t GetLocaleInfoW(const uint32_t *a)
{
    const char *t = locale_text(a[1]);
    uint32_t n, i;

    if (!t) {
        k32_set_last_error(87);
        return 0;
    }
    n = (uint32_t)strlen(t) + 1;
    if (a[3] == 0)
        return n;
    if (a[3] < n) {
        k32_set_last_error(ERROR_INSUFFICIENT_BUFFER);
        return 0;
    }
    for (i = 0; i < n; i++)
        WR16(a[2] + 2 * i, (uint8_t)t[i]);
    return n;
}

/* ---- thread local storage: a slot index, and a value for each (slot, guest thread) ----------------------------------------------------- */
#define TLS_SLOTS 64
static int tls_used[TLS_SLOTS];
static struct TlsValue { uint32_t slot, tid, value; } *tls_values;
static int ntls_values, captls_values;

static uint32_t TlsAlloc(const uint32_t *a)
{
    uint32_t i;

    (void)a;
    for (i = 0; i < TLS_SLOTS; i++)
        if (!tls_used[i]) {
            tls_used[i] = 1;
            return i;
        }
    return 0xFFFFFFFFu;
}

static uint32_t TlsFree(const uint32_t *a)
{
    int i, k = 0;

    if (a[0] >= TLS_SLOTS || !tls_used[a[0]])
        return 0;
    tls_used[a[0]] = 0;
    for (i = 0; i < ntls_values; i++)               /* the values of the slot go with it */
        if (tls_values[i].slot != a[0])
            tls_values[k++] = tls_values[i];
    ntls_values = k;
    return 1;
}

static uint32_t TlsSetValue(const uint32_t *a)
{
    uint32_t tid = sched_tid();
    int i;

    if (a[0] >= TLS_SLOTS || !tls_used[a[0]])
        return 0;
    for (i = 0; i < ntls_values; i++)
        if (tls_values[i].slot == a[0] && tls_values[i].tid == tid) {
            tls_values[i].value = a[1];
            return 1;
        }
    if (ntls_values == captls_values) {
        captls_values = captls_values ? captls_values * 2 : 32;
        tls_values = realloc(tls_values, (size_t)captls_values * sizeof(*tls_values));
    }
    tls_values[ntls_values++] = (struct TlsValue){a[0], tid, a[1]};
    return 1;
}

static uint32_t TlsGetValue(const uint32_t *a)
{
    uint32_t tid = sched_tid();
    int i;

    k32_set_last_error(0);
    if (a[0] >= TLS_SLOTS || !tls_used[a[0]])
        return 0;
    for (i = 0; i < ntls_values; i++)
        if (tls_values[i].slot == a[0] && tls_values[i].tid == tid)
            return tls_values[i].value;
    return 0;                                       /* a slot nothing has been put into is 0 in every thread */
}

/* ---- error text -------------------------------------------------------------------------------------------------------------------- */
/* FormatMessageA(flags, source, message id, language, buffer, size, arguments): the system's text for an error number (the ones a game meets), or the string given with
 * FORMAT_MESSAGE_FROM_STRING, with no inserts done. FORMAT_MESSAGE_ALLOCATE_BUFFER puts a block from the guest's heap at the address `buffer` names. Returns the length without the NUL, 0 on failure. */
static const char *system_message(uint32_t id)
{
    switch (id) {
    case 0: return "The operation completed successfully.";
    case 2: return "The system cannot find the file specified.";
    case 3: return "The system cannot find the path specified.";
    case 5: return "Access is denied.";
    case 6: return "The handle is invalid.";
    case 8: return "Not enough storage is available to process this command.";
    case 32: return "The process cannot access the file because it is being used by another process.";
    case 80: return "The file exists.";
    case 87: return "The parameter is incorrect.";
    case 122: return "The data area passed to a system call is too small.";
    case 234: return "More data is available.";
    default: return NULL;
    }
}

/* The inserts of a FORMAT_MESSAGE_FROM_STRING message (Spells of the Ancients 2.15 takes its texts from AdvStrings.txt with them: "%1 Village", "Trade %1 for %2", "%1!d! fine %2"):
 *   %1 .. %99  the n-th argument, as a string (a pointer); %1!fmt! with a printf conversion: %1!d!, %1!s!, %1!02x!, %1!c! (the argument is a 32-bit value)
 *   %0 ends the text (no more); %n a line break (CR LF), %r CR, %t tab, %% a percent sign, %. a period, %! an exclamation mark, %space a space
 * `args` is the address of the argument array (FORMAT_MESSAGE_ARGUMENT_ARRAY) or of a va_list (the dword it holds is the array's address). A message with no inserts comes out as it was. */
size_t winsys_format_message(char *out, size_t cap, const char *fmt, uint32_t args, int array)
{
    size_t n = 0;
    uint32_t base = args;

    if (args && !array)
        base = RD32(args);                          /* a va_list is a pointer to the arguments on the caller's stack */
#define PUT(c) do { if (n + 1 < cap) out[n] = (char)(c); n++; } while (0)
    while (*fmt) {
        char c = *fmt++;

        if (c != '%') {
            PUT(c);
            continue;
        }
        c = *fmt;
        if (c >= '1' && c <= '9') {
            unsigned idx = 0;
            char spec[24], text[400];
            const char *s;
            uint32_t v;
            int k = 0;

            while (*fmt >= '0' && *fmt <= '9' && idx < 100)
                idx = idx * 10 + (unsigned)(*fmt++ - '0');
            v = base ? RD32(base + 4 * (idx - 1)) : 0;
            strcpy(spec, "%s");
            if (*fmt == '!') {                      /* %1!d!: up to the next '!' is a printf conversion */
                const char *e = strchr(fmt + 1, '!');

                if (e && (size_t)(e - fmt) < sizeof(spec)) {
                    spec[0] = '%';
                    memcpy(spec + 1, fmt + 1, (size_t)(e - fmt - 1));
                    spec[e - fmt] = 0;
                    fmt = e + 1;
                }
            }
            k = (int)strlen(spec);
            switch (spec[k - 1]) {
            case 'd': case 'i': snprintf(text, sizeof(text), spec, (int)v); break;
            case 'u': case 'x': case 'X': case 'o': snprintf(text, sizeof(text), spec, v); break;
            case 'c': case 'C': snprintf(text, sizeof(text), "%c", (int)(v & 0xff)); break;
            default:                                /* a string: the argument is the address of its characters */
                s = v ? P(v) : "(null)";
                spec[k - 1] = 's';
                snprintf(text, sizeof(text), spec, s);
            }
            for (s = text; *s; s++)
                PUT(*s);
            continue;
        }
        fmt++;
        switch (c) {
        case 0: fmt--; PUT('%'); break;
        case '%': PUT('%'); break;
        case 'n': PUT('\r'); PUT('\n'); break;
        case 'r': PUT('\r'); break;
        case 't': PUT('\t'); break;
        case '.': PUT('.'); break;
        case '!': PUT('!'); break;
        case ' ': PUT(' '); break;
        case '0': goto done;
        default: PUT(c);
        }
    }
done:
    if (cap)
        out[n < cap ? n : cap - 1] = 0;
#undef PUT
    return n;
}

static uint32_t FormatMessageA(const uint32_t *a)
{
    uint32_t flags = a[0], n;
    char fallback[64], *formatted = NULL;
    const char *text;

    if (flags & 0x400) {                           /* FORMAT_MESSAGE_FROM_STRING */
        text = P(a[1]);
        if (!(flags & 0x200)) {                    /* no FORMAT_MESSAGE_IGNORE_INSERTS: do the inserts */
            size_t cap = 4096, len;

            formatted = malloc(cap);
            if (!formatted) {
                k32_set_last_error(8);
                return 0;
            }
            len = winsys_format_message(formatted, cap, text, a[6], (flags & 0x2000) != 0);
            if (len >= cap) {
                free(formatted);
                k32_set_last_error(ERROR_INSUFFICIENT_BUFFER);
                return 0;
            }
            text = formatted;
        }
    } else if (flags & 0x1000) {                     /* FORMAT_MESSAGE_FROM_SYSTEM */
        text = system_message(a[2]);
        if (!text) {
            snprintf(fallback, sizeof(fallback), "Unknown error (0x%x).", a[2]);
            text = fallback;
        }
    } else {
        k32_set_last_error(87);
        return 0;
    }
    n = (uint32_t)strlen(text);
    if (flags & 0x100) {                           /* FORMAT_MESSAGE_ALLOCATE_BUFFER: a[4] is the address of the pointer to set */
        uint32_t block = heap_alloc(n + 1);

        if (!block) {
            free(formatted);
            return 0;
        }
        memcpy(P(block), text, n + 1);
        WR32(a[4], block);
    } else if (a[5] < n + 1) {
        k32_set_last_error(ERROR_INSUFFICIENT_BUFFER);
        n = 0;
    } else
        memcpy(P(a[4]), text, n + 1);
    free(formatted);
    return n;
}

/* ---- threads: times, and the suspend count ------------------------------------------------------------------------------------------- */
/* GetThreadTimes(thread, &creation, &exit, &kernel, &user): FILETIMEs. The creation time is the program's start, the CPU times are the time since then (the scheduler runs one
 * thread at a time, so no more is known), the exit time is 0. */
static uint32_t GetThreadTimes(const uint32_t *a)
{
    uint64_t start = 116444736000000000ull + 10000000ull * 1000000000ull;     /* an arbitrary fixed date: the guest sees times relative to each other */
    uint64_t used = (uint64_t)(port_now() * 1e7);
    uint32_t k;

    for (k = 1; k <= 4; k++) {
        uint64_t v = k == 1 ? start : k == 2 ? 0 : k == 3 ? used / 4 : used / 2;

        if (a[k]) {
            WR32(a[k], (uint32_t)v);
            WR32(a[k] + 4, (uint32_t)(v >> 32));
        }
    }
    return 1;
}

/* A guest thread cannot be held and let go from outside (the scheduler passes a baton between threads that run on their own): SuspendThread and ResumeThread report a suspend
 * count of 0 and change nothing. A program that needs a thread to stand still would see it run. */
static uint32_t SuspendResumeThread(const uint32_t *a) { (void)a; return 0; }

/* ---- the registry ------------------------------------------------------------------------------------------------------------------- */
#define REG_SZ 1
#define REG_BINARY 3

static const char WINDOWS_KEY[] = "HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion";
static const uint8_t INSTALL_TIME[4] = {0x80, 0xEC, 0x91, 0x35};              /* FirstInstallDateTime: 0x3591EC80, seconds since 1970, 25 June 1998 */
static const char PRODUCT_ID[] = "54377-OEM-0013407-48562";                    /* ProductId: made up, in the form Windows 98's is */

static const struct RegValue { const char *key, *name; uint32_t type, len; const void *data; } REG_VALUES[] = {
    {WINDOWS_KEY, "FirstInstallDateTime", REG_BINARY, sizeof(INSTALL_TIME), INSTALL_TIME},
    {WINDOWS_KEY, "ProductId", REG_SZ, sizeof(PRODUCT_ID), PRODUCT_ID},
};

#define REG_ROOT_BASE 0x80000000u
#define REG_HANDLES 64
#define REG_HANDLE_BASE 0x7F000000u
static struct { int used; char path[300]; } regkeys[REG_HANDLES];

static const char *root_name(uint32_t h)
{
    switch (h) {
    case 0x80000000u: return "HKCR";
    case 0x80000001u: return "HKCU";
    case 0x80000002u: return "HKLM";
    case 0x80000003u: return "HKU";
    case 0x80000005u: return "HKCC";
    default: return NULL;
    }
}

/* The full path ("HKLM\SOFTWARE\...") of subkey `sub` below the key or root `h`; 0 if `h` is neither. */
static int reg_path(uint32_t h, const char *sub, char *out, size_t cap)
{
    const char *base;
    size_t n;

    if (root_name(h))
        base = root_name(h);
    else if (h >= REG_HANDLE_BASE && h < REG_HANDLE_BASE + 4 * REG_HANDLES && regkeys[(h - REG_HANDLE_BASE) / 4].used)
        base = regkeys[(h - REG_HANDLE_BASE) / 4].path;
    else
        return 0;
    snprintf(out, cap, "%s", base);
    n = strlen(out);
    while (*sub == '\\')
        sub++;
    if (*sub)
        snprintf(out + n, cap - n, "\\%s", sub);
    n = strlen(out);
    while (n > 0 && out[n - 1] == '\\')
        out[--n] = 0;
    return 1;
}

static uint32_t reg_new(const char *path)
{
    int i;

    for (i = 0; i < REG_HANDLES; i++)
        if (!regkeys[i].used) {
            regkeys[i].used = 1;
            snprintf(regkeys[i].path, sizeof(regkeys[i].path), "%s", path);
            return REG_HANDLE_BASE + 4u * (uint32_t)i;
        }
    return 0;
}

/* Is `path` a key the table knows, or one on the way to it (HKLM\SOFTWARE is a key because HKLM\SOFTWARE\Microsoft\... is)? */
static int reg_known(const char *path)
{
    size_t i, n = strlen(path);

    for (i = 0; i < sizeof(REG_VALUES) / sizeof(REG_VALUES[0]); i++)
        if (!strncasecmp(REG_VALUES[i].key, path, n) && (REG_VALUES[i].key[n] == 0 || REG_VALUES[i].key[n] == '\\'))
            return 1;
    return 0;
}

static uint32_t reg_open(uint32_t h, const char *sub, uint32_t out, int create)
{
    char path[300];
    uint32_t k;

    if (!reg_path(h, sub, path, sizeof(path)))
        return 6;                                   /* ERROR_INVALID_HANDLE */
    if (!create && !reg_known(path))
        return ERROR_FILE_NOT_FOUND;                /* the program falls back to its defaults */
    k = reg_new(path);
    if (!k)
        return 8;                                   /* ERROR_NOT_ENOUGH_MEMORY */
    if (out)
        WR32(out, k);
    return 0;
}

static uint32_t RegOpenKeyA(const uint32_t *a) { return reg_open(a[0], P(a[1]), a[2], 0); }
static uint32_t RegOpenKeyExA(const uint32_t *a) { return reg_open(a[0], P(a[1]), a[4], 0); }
static uint32_t RegCreateKeyA(const uint32_t *a) { return reg_open(a[0], P(a[1]), a[2], 1); }
static uint32_t RegCreateKeyExA(const uint32_t *a)
{
    uint32_t r = reg_open(a[0], P(a[1]), a[7], 1);

    if (!r && a[8])
        WR32(a[8], 1);                              /* REG_CREATED_NEW_KEY */
    return r;
}

static uint32_t RegCloseKey(const uint32_t *a)
{
    if (a[0] >= REG_HANDLE_BASE && a[0] < REG_HANDLE_BASE + 4 * REG_HANDLES)
        regkeys[(a[0] - REG_HANDLE_BASE) / 4].used = 0;
    return 0;                                       /* (closing a key twice, or one that was never opened, was never an error here) */
}

/* RegQueryValueExA(key, name, reserved, &type, data, &size): the value if the table has it; with no buffer only the type and the size; ERROR_MORE_DATA when it does not fit. */
static uint32_t RegQueryValueExA(const uint32_t *a)
{
    char path[300];
    size_t i;

    if (!reg_path(a[0], "", path, sizeof(path)))
        return 6;
    if (!a[1])
        return ERROR_FILE_NOT_FOUND;
    for (i = 0; i < sizeof(REG_VALUES) / sizeof(REG_VALUES[0]); i++) {
        const struct RegValue *v = &REG_VALUES[i];

        if (strcasecmp(v->key, path) || strcasecmp(v->name, P(a[1])))
            continue;
        if (a[3])
            WR32(a[3], v->type);
        if (a[4]) {
            if (!a[5])
                return 87;
            if (RD32(a[5]) < v->len) {
                WR32(a[5], v->len);
                return ERROR_MORE_DATA;
            }
            memcpy(P(a[4]), v->data, v->len);
        }
        if (a[5])
            WR32(a[5], v->len);
        return 0;
    }
    return ERROR_FILE_NOT_FOUND;
}

const WinApi WINSYS_APIS[] = {
    {"kernel32.dll", "GetVersionExA", GetVersionExA}, {"kernel32.dll", "GetWindowsDirectoryA", GetWindowsDirectoryA}, {"kernel32.dll", "GetDiskFreeSpaceA", GetDiskFreeSpaceA},
    {"kernel32.dll", "GetVolumeInformationA", GetVolumeInformationA}, {"kernel32.dll", "GetLocaleInfoA", GetLocaleInfoA}, {"kernel32.dll", "GetLocaleInfoW", GetLocaleInfoW},
    {"kernel32.dll", "TlsAlloc", TlsAlloc}, {"kernel32.dll", "TlsFree", TlsFree}, {"kernel32.dll", "TlsSetValue", TlsSetValue}, {"kernel32.dll", "TlsGetValue", TlsGetValue},
    {"kernel32.dll", "FormatMessageA", FormatMessageA}, {"kernel32.dll", "GetThreadTimes", GetThreadTimes},
    {"kernel32.dll", "SuspendThread", SuspendResumeThread}, {"kernel32.dll", "ResumeThread", SuspendResumeThread},
    {"advapi32.dll", "RegOpenKeyA", RegOpenKeyA}, {"advapi32.dll", "RegOpenKeyExA", RegOpenKeyExA}, {"advapi32.dll", "RegCreateKeyA", RegCreateKeyA},
    {"advapi32.dll", "RegCreateKeyExA", RegCreateKeyExA}, {"advapi32.dll", "RegQueryValueExA", RegQueryValueExA}, {"advapi32.dll", "RegCloseKey", RegCloseKey},
    {"advapi32.dll", "RegSetValueExA", zero}, {"advapi32.dll", "RegFlushKey", zero},
    {0, 0, 0},
};

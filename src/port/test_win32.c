/* test_win32.c - the Windows and C runtime calls that Spells of the Ancients' programs and libraries make and 1.0's did not (winsys.c, crt.c, filedlg.c), called by name as the guest
 * calls them: the version and the folders, the disks, the locale, thread local storage, error text, the registry, sorting with the game's own comparison, character classes, listing a
 * folder, GetFileTitleA, and that an import of msvcrt.dll finds what the tables hold under msvcrtd.dll. No game file is needed.
 *   make -C src/port test */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "plat.h"
#include "port.h"
#include "regstore.h"
#include "sched.h"
#include "test_util.h"

int pe_find_resource(uint32_t hinst, uint32_t type, uint32_t name, uint32_t *addr, uint32_t *size) { (void)hinst; (void)type; (void)name; (void)addr; (void)size; return 0; }

extern Image main_image;

static int failures, checks;
#define CHECK(c) do { checks++; if (!(c)) { failures++; printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

static uint32_t cursor = 0x01000000u;
static uint32_t scratch(uint32_t n) { uint32_t p = cursor; cursor += (n + 15) & ~15u; return p; }
static uint32_t cstr(const char *s) { uint32_t p = scratch((uint32_t)strlen(s) + 1); strcpy((char *)(G + p), s); return p; }
static const char *text(uint32_t p) { return (const char *)(G + p); }

static uint32_t call_api(const char *dll, const char *name, const uint32_t *args)
{
    const WinApi *a = port_find_api(dll, name);

    if (!a) {
        printf("no API %s!%s\n", dll, name);
        failures++;
        return 0;
    }
    return a->fn(args);
}
#define API(dll, name, ...) call_api(dll, name, (const uint32_t[16]){__VA_ARGS__})
#define K32(name, ...) API("kernel32.dll", name, __VA_ARGS__)
#define CRT(name, ...) API("msvcrt.dll", name, __VA_ARGS__)

#define HKLM 0x80000002u
#define WINDOWS_KEY "SOFTWARE\\Microsoft\\Windows\\CurrentVersion"

static void test_find_api(void)
{
    CHECK(port_find_api("msvcrt.dll", "qsort") == port_find_api("msvcrtd.dll", "qsort") && port_find_api("msvcrt.dll", "qsort") != NULL);      /* the release C runtime is the debug one's table */
    CHECK(port_find_api("msvcrt.dll", "NoSuchFunction") == NULL && port_find_api("kernel32.dll", "NoSuchFunction") == NULL);
    CHECK(port_find_api("kernel32.dll", "qsort") == NULL);                                  /* not another library's name */
    CHECK(port_find_api("msvcrtd.dll", "memcpy") != NULL && port_find_api("kernel32.dll", "TlsAlloc") != NULL && port_find_api("advapi32.dll", "RegOpenKeyA") != NULL);
}

static void test_version_and_folders(void)
{
    uint32_t v = scratch(160), buf = scratch(64), out[4], serial, comp, flags, fs = scratch(16), label = scratch(16);

    guest_zero(v, 160);
    WR32(v, 148);
    CHECK(K32("GetVersionExA", v) == 1);
    CHECK(RD32(v + 4) == 4 && RD32(v + 8) == 10 && RD32(v + 12) == 0x040A08AEu && RD32(v + 16) == 1 && !strcmp(text(v + 20), " A"));        /* Windows 98 SE: 4.10.2222 A */
    CHECK(K32("GetVersion") == 0x88AE0A04u);                                                 /* what GetVersion says is the same */
    WR32(v, 20);
    guest_zero(v + 20, 8);
    CHECK(K32("GetVersionExA", v) == 1 && RD32(v + 20) == 0);                                /* the old, short structure has no service pack string */
    WR32(v, 10);
    CHECK(K32("GetVersionExA", v) == 0);                                                     /* a structure too short to hold a version */

    CHECK(K32("GetWindowsDirectoryA", buf, 64) == 10 && !strcmp(text(buf), "C:\\WINDOWS"));
    WR8(buf, 'x');
    CHECK(K32("GetWindowsDirectoryA", buf, 5) == 11 && text(buf)[0] == 'x');                  /* too small: the size needed, with the NUL, and nothing written */

    out[0] = scratch(4); out[1] = scratch(4); out[2] = scratch(4); out[3] = scratch(4);
    CHECK(K32("GetDiskFreeSpaceA", cstr("C:\\"), out[0], out[1], out[2], out[3]) == 1);
    CHECK(RD32(out[0]) * RD32(out[1]) == 16384 && RD32(out[2]) == 0x20000u && RD32(out[3]) == 0x40000u);
    CHECK(K32("GetDiskFreeSpaceA", cstr("C:\\"), 0, 0, 0, 0) == 1);                           /* none of the answers asked for */

    serial = scratch(4); comp = scratch(4); flags = scratch(4);
    CHECK(K32("GetVolumeInformationA", cstr("C:\\"), label, 16, serial, comp, flags, fs, 16) == 1);
    CHECK(text(label)[0] == 0 && RD32(serial) != 0 && RD32(comp) == 255 && RD32(flags) == 6 && !strcmp(text(fs), "FAT32"));
    CHECK(K32("GetVolumeInformationA", cstr("C:\\"), 0, 0, 0, 0, 0, 0, 0) == 1);
}

static void test_locale(void)
{
    uint32_t buf = scratch(64), i;
    uint32_t last;

    CHECK(K32("GetLocaleInfoA", 0x409, 0x0E, buf, 8) == 2 && !strcmp(text(buf), "."));        /* LOCALE_SDECIMAL */
    CHECK(K32("GetLocaleInfoA", 0x409, 0x0F, buf, 8) == 2 && !strcmp(text(buf), ","));        /* LOCALE_STHOUSAND */
    CHECK(K32("GetLocaleInfoA", 0x409, 0x1004, buf, 8) == 5 && !strcmp(text(buf), "1252"));   /* the ANSI code page */
    CHECK(K32("GetLocaleInfoA", 0x409, 0x0E | 0x80000000u, buf, 8) == 2);                     /* (LOCALE_NOUSEROVERRIDE changes nothing) */
    CHECK(K32("GetLocaleInfoA", 0x409, 0x02, 0, 0) == 24);                                    /* with no buffer: the size that is needed, with the NUL */
    CHECK(K32("GetLocaleInfoA", 0x409, 0x02, buf, 5) == 0);                                   /* too small */
    last = K32("GetLastError");
    CHECK(last == 122);                                                                       /* ERROR_INSUFFICIENT_BUFFER */
    CHECK(K32("GetLocaleInfoA", 0x409, 0x7777, buf, 8) == 0 && K32("GetLastError") == 87);    /* a type that is not known: ERROR_INVALID_PARAMETER */
    guest_zero(buf, 64);
    CHECK(K32("GetLocaleInfoW", 0x409, 0x03, buf, 8) == 4);                                   /* "ENU": 16-bit characters */
    for (i = 0; i < 4; i++)
        CHECK(RD16(buf + 2 * i) == (uint16_t)"ENU"[i]);
    CHECK(K32("GetLocaleInfoW", 0x409, 0x03, buf, 3) == 0);
}

static void test_tls(void)
{
    uint32_t a = K32("TlsAlloc"), b = K32("TlsAlloc");

    CHECK(a != 0xFFFFFFFFu && b != 0xFFFFFFFFu && a != b);
    CHECK(K32("TlsGetValue", a) == 0 && K32("GetLastError") == 0);                           /* nothing put in yet: 0, and not an error */
    CHECK(K32("TlsSetValue", a, 0x11111111u) == 1 && K32("TlsSetValue", b, 0x22222222u) == 1);
    CHECK(K32("TlsGetValue", a) == 0x11111111u && K32("TlsGetValue", b) == 0x22222222u);
    CHECK(K32("TlsSetValue", a, 0x33333333u) == 1 && K32("TlsGetValue", a) == 0x33333333u);  /* replaced */
    CHECK(K32("TlsFree", a) == 1);
    CHECK(K32("TlsGetValue", a) == 0 && K32("TlsSetValue", a, 5) == 0 && K32("TlsFree", a) == 0);     /* a slot that is free holds nothing and takes nothing */
    CHECK(K32("TlsAlloc") == a && K32("TlsGetValue", a) == 0);                                /* the next one is that slot again, empty */
    CHECK(K32("TlsGetValue", b) == 0x22222222u);
    CHECK(K32("TlsGetValue", 1000) == 0 && K32("TlsSetValue", 1000, 1) == 0);                 /* outside the slots */
}

static void test_format_message(void)
{
    uint32_t buf = scratch(128), ptr = scratch(4), n;

    n = K32("FormatMessageA", 0x1000, 0, 2, 0, buf, 128, 0);                                  /* FROM_SYSTEM */
    CHECK(n == strlen("The system cannot find the file specified.") && !strcmp(text(buf), "The system cannot find the file specified."));
    n = K32("FormatMessageA", 0x1000, 0, 0x7654, 0, buf, 128, 0);
    CHECK(n > 0 && strstr(text(buf), "0x7654") != NULL);                                      /* an error nobody wrote a text for still gets one */
    CHECK(K32("FormatMessageA", 0x1000, 0, 2, 0, buf, 10, 0) == 0 && K32("GetLastError") == 122);         /* the buffer is too small */
    n = K32("FormatMessageA", 0x1000 | 0x100, 0, 5, 0, ptr, 0, 0);                            /* ALLOCATE_BUFFER */
    CHECK(n == strlen("Access is denied.") && RD32(ptr) != 0 && !strcmp(text(RD32(ptr)), "Access is denied."));
    CHECK(K32("FormatMessageA", 0x400, cstr("a string"), 0, 0, buf, 128, 0) == 8 && !strcmp(text(buf), "a string"));      /* FROM_STRING */
    CHECK(K32("FormatMessageA", 0, 0, 2, 0, buf, 128, 0) == 0);                               /* no source named */
    /* the inserts, as the game's wrapper (a va_list in its own frame) and an argument array give them */
    {
        uint32_t argv = scratch(32), ap = scratch(4);

        WR32(argv, cstr("Windlass")); WR32(argv + 4, cstr("Forge")); WR32(argv + 8, 15); WR32(argv + 12, 0xbeef);
        WR32(ap, argv);                                                                       /* the va_list: the address of the arguments */
        n = K32("FormatMessageA", 0x400, cstr("%1 Village"), 0, 0, buf, 128, ap);
        CHECK(n == strlen("Windlass Village") && !strcmp(text(buf), "Windlass Village"));
        n = K32("FormatMessageA", 0x400 | 0x2000, cstr("%2 of %1 (%3!d! gold, %4!04x!)"), 0, 0, buf, 128, argv);   /* an array, in any order, with printf conversions */
        CHECK(!strcmp(text(buf), "Forge of Windlass (15 gold, beef)") && n == strlen(text(buf)));
        n = K32("FormatMessageA", 0x400, cstr("100%% %1!s!!%n%2%0never"), 0, 0, buf, 128, ap);
        CHECK(!strcmp(text(buf), "100% Windlass!\r\nForge") && n == strlen(text(buf)));    /* %%, an explicit !s!, a line break, %0 ends it */
        n = K32("FormatMessageA", 0x400 | 0x200, cstr("%1 stays"), 0, 0, buf, 128, ap);      /* IGNORE_INSERTS */
        CHECK(!strcmp(text(buf), "%1 stays"));
        CHECK(K32("FormatMessageA", 0x400, cstr("%1 Village"), 0, 0, buf, 8, ap) == 0 && K32("GetLastError") == 122);      /* the result does not fit */
        n = K32("FormatMessageA", 0x400 | 0x100, cstr("%3!5d!|"), 0, 0, ptr, 0, ap);                                         /* ALLOCATE_BUFFER with inserts: argument 3 as a number */
        CHECK(RD32(ptr) != 0 && n == 6 && text(RD32(ptr))[5] == '|');
    }
}

static void test_thread_times(void)
{
    uint32_t t[4] = {scratch(8), scratch(8), scratch(8), scratch(8)};

    guest_zero(t[0], 8); guest_zero(t[1], 8); guest_zero(t[2], 8); guest_zero(t[3], 8);
    CHECK(K32("GetThreadTimes", 0xFFFFFFFEu, t[0], t[1], t[2], t[3]) == 1);
    CHECK((RD32(t[0]) | RD32(t[0] + 4)) != 0 && RD32(t[1]) == 0 && RD32(t[1] + 4) == 0);      /* a creation time, no exit time */
    CHECK(K32("GetThreadTimes", 0xFFFFFFFEu, 0, 0, 0, 0) == 1);
    CHECK(K32("SuspendThread", 0xFFFFFFFEu) == 0 && K32("ResumeThread", 0xFFFFFFFEu) == 0);   /* a suspend count of 0: nothing can be held */
}

static void test_registry(void)
{
    uint32_t key = scratch(4), key2 = scratch(4), type = scratch(4), size = scratch(4), data = scratch(64);

    /* the two values of Windows' own key that the game asks for at start */
    CHECK(API("advapi32.dll", "RegOpenKeyA", HKLM, cstr(WINDOWS_KEY), key) == 0 && RD32(key) != 0);
    WR32(size, 64);
    CHECK(API("advapi32.dll", "RegQueryValueExA", RD32(key), cstr("ProductId"), 0, type, data, size) == 0);
    CHECK(RD32(type) == 1 && RD32(size) == 24 && !strcmp(text(data), "54377-OEM-0013407-48562"));          /* REG_SZ, with the NUL */
    WR32(size, 64);
    CHECK(API("advapi32.dll", "RegQueryValueExA", RD32(key), cstr("FirstInstallDateTime"), 0, type, data, size) == 0);
    CHECK(RD32(type) == 3 && RD32(size) == 4 && RD32(data) == 0x3591EC80u);                                 /* REG_BINARY: four bytes */
    WR32(size, 64);
    CHECK(API("advapi32.dll", "RegQueryValueExA", RD32(key), cstr("productid"), 0, 0, data, size) == 0);     /* names are matched without regard to case */
    CHECK(API("advapi32.dll", "RegQueryValueExA", RD32(key), cstr("ProductId"), 0, type, 0, size) == 0 && RD32(size) == 24 && RD32(type) == 1);   /* no buffer: only the size */
    WR32(size, 5);
    CHECK(API("advapi32.dll", "RegQueryValueExA", RD32(key), cstr("ProductId"), 0, type, data, size) == 234 && RD32(size) == 24);       /* ERROR_MORE_DATA */
    CHECK(API("advapi32.dll", "RegQueryValueExA", RD32(key), cstr("NoSuchValue"), 0, type, data, size) == 2);                          /* not found: the program uses its default */
    CHECK(API("advapi32.dll", "RegQueryValueExA", RD32(key), 0, 0, type, data, size) == 2);                                           /* no default value */
    CHECK(API("advapi32.dll", "RegCloseKey", RD32(key)) == 0);
    CHECK(API("advapi32.dll", "RegQueryValueExA", RD32(key), cstr("ProductId"), 0, type, data, size) == 6);                            /* a closed key is not a key */
    CHECK(API("advapi32.dll", "RegCloseKey", RD32(key)) == 0);                                                                         /* (closing twice was never an error) */

    /* the same through the keys above it, and the Ex form */
    CHECK(API("advapi32.dll", "RegOpenKeyA", HKLM, cstr("SOFTWARE\\Microsoft"), key) == 0);
    CHECK(API("advapi32.dll", "RegOpenKeyA", RD32(key), cstr("Windows\\CurrentVersion"), key2) == 0);
    WR32(size, 64);
    CHECK(API("advapi32.dll", "RegQueryValueExA", RD32(key2), cstr("ProductId"), 0, type, data, size) == 0);
    CHECK(API("advapi32.dll", "RegQueryValueExA", RD32(key), cstr("ProductId"), 0, type, data, size) == 2);   /* the value belongs to the deeper key only */
    CHECK(API("advapi32.dll", "RegOpenKeyExA", HKLM, cstr(WINDOWS_KEY), 0, 0x20019, key2) == 0);
    API("advapi32.dll", "RegCloseKey", RD32(key));
    API("advapi32.dll", "RegCloseKey", RD32(key2));

    /* what is not in the table is not there: the programs fall back to their defaults, as they did when the registry had nothing at all (no store is open here: see test_registry_store) */
    CHECK(API("advapi32.dll", "RegOpenKeyA", HKLM, cstr("SOFTWARE\\MicroProse\\Magic: The Gathering"), key) == 2);
    CHECK(API("advapi32.dll", "RegOpenKeyA", 0x80000001u, cstr(WINDOWS_KEY), key) == 2);                 /* HKEY_CURRENT_USER has no such key */
    CHECK(API("advapi32.dll", "RegOpenKeyExA", HKLM, cstr("SOFTWARE\\MicroProse"), 0, 0x20019, key) == 2);
    CHECK(API("advapi32.dll", "RegOpenKeyA", 0x1234, cstr("x"), key) == 6);                              /* not a key or a root */

    /* a key that is made can be held, and written to (the write goes nowhere) */
    CHECK(API("advapi32.dll", "RegCreateKeyA", HKLM, cstr("SOFTWARE\\MicroProse\\Magic: The Gathering"), key) == 0 && RD32(key) != 0);
    CHECK(API("advapi32.dll", "RegSetValueExA", RD32(key), cstr("Path"), 0, 1, cstr("C:\\Magic"), 9) == 0);
    WR32(size, 64);
    CHECK(API("advapi32.dll", "RegQueryValueExA", RD32(key), cstr("Path"), 0, type, data, size) == 2);   /* not kept */
    API("advapi32.dll", "RegCloseKey", RD32(key));
    {
        uint32_t disposition = scratch(4);

        CHECK(API("advapi32.dll", "RegCreateKeyExA", HKLM, cstr("SOFTWARE\\MicroProse"), 0, 0, 0, 0xF003F, 0, key, disposition) == 0 && RD32(disposition) == 1);
        API("advapi32.dll", "RegCloseKey", RD32(key));
    }
}

/* With a file registry open (regstore.h; main.c opens one for a Spells of the Ancients run): the values under MicroProse and the two Windows values come from it and are kept in it;
 * everything else is as without one. All values here are made up. */
static void test_registry_store(void)
{
    char dir[600], path[700], file[3000];
    uint32_t key = scratch(4), type = scratch(4), size = scratch(4), data = scratch(64), blob = scratch(16);
    const uint8_t pair_time[4] = {0x11, 0x22, 0x33, 0x44};
    FILE *f;
    size_t n;

    test_tmpdir(dir, sizeof(dir), "win32reg_");
    snprintf(path, sizeof(path), "%s/registry.dat", dir);
    CHECK(regstore_open(path) == 0);

    /* an empty store changes nothing that was answered before: the fixed pair, MicroProse not found */
    CHECK(API("advapi32.dll", "RegOpenKeyA", HKLM, cstr(WINDOWS_KEY), key) == 0);
    WR32(size, 64);
    CHECK(API("advapi32.dll", "RegQueryValueExA", RD32(key), cstr("ProductId"), 0, type, data, size) == 0 && !strcmp(text(data), "54377-OEM-0013407-48562"));
    API("advapi32.dll", "RegCloseKey", RD32(key));
    CHECK(API("advapi32.dll", "RegOpenKeyA", HKLM, cstr("SOFTWARE\\MicroProse\\Magic: The Gathering"), key) == 2);

    /* this install's own pair (the installer makes one): answered from the store, a value at a time */
    CHECK(regstore_put(REGSTORE_WINDOWS_KEY, "FirstInstallDateTime", 3, pair_time, 4) == 0);
    CHECK(API("advapi32.dll", "RegOpenKeyA", HKLM, cstr(WINDOWS_KEY), key) == 0);
    WR32(size, 64);
    CHECK(API("advapi32.dll", "RegQueryValueExA", RD32(key), cstr("FirstInstallDateTime"), 0, type, data, size) == 0 && RD32(type) == 3 && RD32(size) == 4 && RD32(data) == 0x44332211u);
    WR32(size, 64);
    CHECK(API("advapi32.dll", "RegQueryValueExA", RD32(key), cstr("ProductId"), 0, type, data, size) == 0 && !strcmp(text(data), "54377-OEM-0013407-48562"));   /* the other one is still the fixed one */
    API("advapi32.dll", "RegCloseKey", RD32(key));

    /* a write under MicroProse is kept: a key that is made, a value that is set, read back, found by a plain open, and still there after the store is opened again */
    CHECK(API("advapi32.dll", "RegCreateKeyA", HKLM, cstr("SOFTWARE\\MicroProse\\Magic: The Gathering"), key) == 0);
    strcpy((char *)(G + blob), "0123456789ab");
    CHECK(API("advapi32.dll", "RegSetValueExA", RD32(key), cstr("Thing"), 0, 3, blob, 12) == 0);
    WR32(size, 64);
    CHECK(API("advapi32.dll", "RegQueryValueExA", RD32(key), cstr("thing"), 0, type, data, size) == 0 && RD32(type) == 3 && RD32(size) == 12 && !memcmp(G + data, "0123456789ab", 12));
    WR32(size, 4);
    CHECK(API("advapi32.dll", "RegQueryValueExA", RD32(key), cstr("Thing"), 0, type, data, size) == 234 && RD32(size) == 12);
    API("advapi32.dll", "RegCloseKey", RD32(key));
    CHECK(API("advapi32.dll", "RegOpenKeyA", HKLM, cstr("SOFTWARE\\MicroProse\\Magic: The Gathering"), key) == 0);
    API("advapi32.dll", "RegCloseKey", RD32(key));
    CHECK(API("advapi32.dll", "RegOpenKeyA", HKLM, cstr("SOFTWARE\\MicroProse"), key) == 0);                    /* on the way to a value */
    API("advapi32.dll", "RegCloseKey", RD32(key));
    CHECK(regstore_open(path) == 2);
    CHECK(API("advapi32.dll", "RegOpenKeyA", HKLM, cstr("SOFTWARE\\MicroProse\\Magic: The Gathering"), key) == 0);
    WR32(size, 64);
    CHECK(API("advapi32.dll", "RegQueryValueExA", RD32(key), cstr("Thing"), 0, type, data, size) == 0 && RD32(size) == 12);
    CHECK(API("advapi32.dll", "RegSetValueExA", RD32(key), cstr("Number"), 0, 4, blob, 4) == 0);
    CHECK(API("advapi32.dll", "RegSetValueExA", RD32(key), cstr("Bad"), 0, 3, 0, 4) == 87);                 /* a size and no data */
    API("advapi32.dll", "RegCloseKey", RD32(key));
    f = fopen(path, "rb");
    n = f ? fread(file, 1, sizeof(file) - 1, f) : 0;
    file[n] = 0;
    if (f)
        fclose(f);
    CHECK(strstr(file, "HKLM\\SOFTWARE\\MicroProse\\Magic: The Gathering\tThing\t3\t30313233343536373839" "6162\n") != NULL);
    CHECK(strstr(file, "\tNumber\t4\t30313233\n") != NULL);

    /* everything else is as before: a key can be made, a write succeeds and goes nowhere, it is not found afterwards; so are the other values of Windows' key */
    CHECK(API("advapi32.dll", "RegCreateKeyA", HKLM, cstr("SOFTWARE\\Elsewhere"), key) == 0);
    CHECK(API("advapi32.dll", "RegSetValueExA", RD32(key), cstr("Thing"), 0, 3, blob, 12) == 0);
    WR32(size, 64);
    CHECK(API("advapi32.dll", "RegQueryValueExA", RD32(key), cstr("Thing"), 0, type, data, size) == 2);
    API("advapi32.dll", "RegCloseKey", RD32(key));
    CHECK(API("advapi32.dll", "RegOpenKeyA", HKLM, cstr("SOFTWARE\\Elsewhere"), key) == 2);
    CHECK(API("advapi32.dll", "RegCreateKeyA", HKLM, cstr(WINDOWS_KEY), key) == 0);
    CHECK(API("advapi32.dll", "RegSetValueExA", RD32(key), cstr("Version"), 0, 1, cstr("x"), 2) == 0);
    WR32(size, 64);
    CHECK(API("advapi32.dll", "RegQueryValueExA", RD32(key), cstr("Version"), 0, type, data, size) == 2);
    API("advapi32.dll", "RegCloseKey", RD32(key));
    CHECK(API("advapi32.dll", "RegOpenKeyA", 0x80000001u, cstr("SOFTWARE\\MicroProse\\Magic: The Gathering"), key) == 2);   /* HKEY_CURRENT_USER is not HKLM */

    /* a store that cannot be written: the write is refused (access denied) and not kept */
    snprintf(path, sizeof(path), "%s/missing/registry.dat", dir);
    CHECK(regstore_open(path) == 0);
    CHECK(API("advapi32.dll", "RegCreateKeyA", HKLM, cstr("SOFTWARE\\MicroProse\\Magic: The Gathering"), key) == 0);
    CHECK(API("advapi32.dll", "RegSetValueExA", RD32(key), cstr("Thing"), 0, 3, blob, 12) == 5);
    API("advapi32.dll", "RegCloseKey", RD32(key));
    CHECK(API("advapi32.dll", "RegOpenKeyA", HKLM, cstr("SOFTWARE\\MicroProse\\Magic: The Gathering"), key) == 2);

    /* no store: the old behaviour exactly (a write succeeds and is not kept) */
    regstore_open(NULL);
    CHECK(API("advapi32.dll", "RegCreateKeyA", HKLM, cstr("SOFTWARE\\MicroProse\\Magic: The Gathering"), key) == 0);
    CHECK(API("advapi32.dll", "RegSetValueExA", RD32(key), cstr("Thing"), 0, 3, blob, 12) == 0);
    WR32(size, 64);
    CHECK(API("advapi32.dll", "RegQueryValueExA", RD32(key), cstr("Thing"), 0, type, data, size) == 2);
    API("advapi32.dll", "RegCloseKey", RD32(key));
    test_rmtree(dir);
}

/* the game's comparison function, as a host function the guest can call: two element addresses, the first dword compared as unsigned numbers */
static int compares;
static uint32_t cmp_dwords(const uint32_t *a)
{
    uint32_t x = RD32(a[0]), y = RD32(a[1]);

    compares++;
    return x < y ? 0xFFFFFFFFu : x > y ? 1u : 0u;
}

static void test_qsort(void)
{
    uint32_t cmp = port_host_function(cmp_dwords), arr = scratch(4 * 200), i, ok;
    uint32_t seed = 12345;

    for (i = 0; i < 200; i++) {
        seed = seed * 1103515245u + 12345u;
        WR32(arr + 4 * i, (seed >> 8) % 1000);
    }
    compares = 0;
    CRT("qsort", arr, 200, 4, cmp);
    for (ok = 1, i = 1; i < 200; i++)
        ok &= RD32(arr + 4 * (i - 1)) <= RD32(arr + 4 * i);
    CHECK(ok && compares > 200 && compares < 200 * 20);                                       /* sorted, in n log n comparisons and not n squared */
    CRT("qsort", arr, 200, 4, cmp);                                                           /* already sorted */
    for (ok = 1, i = 1; i < 200; i++)
        ok &= RD32(arr + 4 * (i - 1)) <= RD32(arr + 4 * i);
    CHECK(ok);
    for (i = 0; i < 200; i++)
        WR32(arr + 4 * i, 200 - i);                                                           /* the other way round */
    CRT("qsort", arr, 200, 4, cmp);
    for (ok = 1, i = 0; i < 200; i++)
        ok &= RD32(arr + 4 * i) == i + 1;
    CHECK(ok);

    /* elements of 12 bytes, the key first: each element moves whole, with what follows its key */
    {
        uint32_t recs = scratch(12 * 50);

        for (i = 0; i < 50; i++) {
            WR32(recs + 12 * i, (i * 37) % 50);
            WR32(recs + 12 * i + 4, 0xA0000000u + (i * 37) % 50);
            WR32(recs + 12 * i + 8, 0xB0000000u + (i * 37) % 50);
        }
        CRT("qsort", recs, 50, 12, cmp);
        for (ok = 1, i = 0; i < 50; i++)
            ok &= RD32(recs + 12 * i) == i && RD32(recs + 12 * i + 4) == 0xA0000000u + i && RD32(recs + 12 * i + 8) == 0xB0000000u + i;
        CHECK(ok);
    }
    /* big elements (the scratch block is 256 bytes: they are swapped in pieces) */
    {
        uint32_t big = scratch(600 * 3), k;

        for (i = 0; i < 3; i++) {
            WR32(big + 600 * i, 3 - i);
            for (k = 4; k < 600; k += 4)
                WR32(big + 600 * i + k, 0x1000u * (3 - i) + k);
        }
        CRT("qsort", big, 3, 600, cmp);
        for (ok = 1, i = 0; i < 3; i++) {
            ok &= RD32(big + 600 * i) == i + 1;
            for (k = 4; k < 600; k += 4)
                ok &= RD32(big + 600 * i + k) == 0x1000u * (i + 1) + k;
        }
        CHECK(ok);
    }
    compares = 0;
    CRT("qsort", arr, 0, 4, cmp);
    CRT("qsort", arr, 1, 4, cmp);
    CRT("qsort", arr, 5, 0, cmp);
    CHECK(compares == 0);                                                                     /* nothing to sort: the comparison is not called */
}

static void test_strings_and_classes(void)
{
    CHECK(CRT("strcoll", cstr("apple"), cstr("banana")) == 0xFFFFFFFFu && CRT("strcoll", cstr("b"), cstr("a")) == 1 && CRT("strcoll", cstr("same"), cstr("same")) == 0);
    CHECK((CRT("_isctype", 'A', 0x1) & 1) && !CRT("_isctype", 'a', 0x1) && (CRT("_isctype", 'a', 0x2) & 2));
    CHECK(CRT("_isctype", '5', 0x4) == 4 && CRT("_isctype", ' ', 0x8) == 8 && CRT("_isctype", '\t', 0x8) == 8 && CRT("_isctype", '!', 0x10) == 0x10);
    CHECK(CRT("_isctype", 0x7f, 0x20) == 0x20 && CRT("_isctype", 0x1, 0x20) == 0x20 && CRT("_isctype", ' ', 0x40) == 0x40 && !CRT("_isctype", '\t', 0x40));
    CHECK(CRT("_isctype", 'F', 0x80) == 0x80 && CRT("_isctype", 'f', 0x80) == 0x80 && CRT("_isctype", '9', 0x80) == 0x80 && !CRT("_isctype", 'G', 0x80));
    CHECK(CRT("_isctype", 'q', 0x103) != 0 && CRT("_isctype", 'Q', 0x103) != 0 && CRT("_isctype", '1', 0x103) == 0);                 /* _ALPHA */
    CHECK(CRT("_isctype", 0x80, 0xFFFF) == 0 && CRT("_isctype", 0xE9, 0xFFFF) == 0 && CRT("_isctype", 0xFFFFFFFFu, 0xFFFF) == 0 && CRT("_isctype", 300, 0xFFFF) == 0);   /* nothing outside ASCII in the C locale, EOF is none */
}

static void test_file_title(void)
{
    uint32_t buf = scratch(64);

    CHECK(API("comdlg32.dll", "GetFileTitleA", cstr("C:\\Magic\\Program\\Decks\\mydeck.dck"), buf, 64) == 0 && !strcmp(text(buf), "mydeck.dck"));
    CHECK(API("comdlg32.dll", "GetFileTitleA", cstr("a/b/c.txt"), buf, 64) == 0 && !strcmp(text(buf), "c.txt"));
    CHECK(API("comdlg32.dll", "GetFileTitleA", cstr("D:readme"), buf, 64) == 0 && !strcmp(text(buf), "readme"));
    CHECK(API("comdlg32.dll", "GetFileTitleA", cstr("plain"), buf, 64) == 0 && !strcmp(text(buf), "plain"));
    CHECK(API("comdlg32.dll", "GetFileTitleA", cstr("C:\\Magic\\Program\\file.txt"), buf, 5) == 9);               /* too small: the size needed, with the NUL */
    CHECK(API("comdlg32.dll", "GetFileTitleA", cstr("C:\\Magic\\"), buf, 64) == 0xFFFFFFFFu);                      /* a folder: no name */
    CHECK(API("comdlg32.dll", "GetFileTitleA", cstr(""), buf, 64) == 0xFFFFFFFFu && API("comdlg32.dll", "GetFileTitleA", cstr("C:\\x\\*.pic"), buf, 64) == 0xFFFFFFFFu);
}

static char root[600], over[600];

static void put(const char *dir, const char *rel, const char *body)
{
    char path[1300], *q;
    FILE *f;

    snprintf(path, sizeof(path), "%s/%s", dir, rel);
    for (q = path + strlen(dir) + 1; *q; q++)
        if (*q == '/') {
            *q = 0;
            plat_mkdir(path);
            *q = '/';
        }
    f = fopen(path, "wb");
    if (f) {
        fputs(body, f);
        fclose(f);
    }
}

static void test_find_files(void)
{
    uint32_t data = scratch(300), errno_cell, h, n = 0;
    char names[16][64];
    uint32_t attrs[16], sizes[16];

    put(root, "Program/Art/b.pic", "bb");
    put(root, "Program/Art/A.PIC", "a");
    put(root, "Program/Art/c.txt", "ccc");
    put(root, "Program/Art/sub/x.pic", "x");
    put(over, "Program/Art/d.pic", "dddd");                                                   /* the overlay's, in the same folder */
    paths_init(root, over);
    h = CRT("_findfirst", cstr("C:\\Magic\\Program\\Art\\*.pic"), data);
    CHECK(h != 0xFFFFFFFFu);
    while (h != 0xFFFFFFFFu) {
        snprintf(names[n], sizeof(names[n]), "%s", text(data + 20));
        attrs[n] = RD32(data);
        sizes[n] = RD32(data + 16);
        n++;
        if (CRT("_findnext", h, data) != 0)
            break;
    }
    CHECK(n == 3 && !strcmp(names[0], "A.PIC") && !strcmp(names[1], "b.pic") && !strcmp(names[2], "d.pic"));          /* in the order of the names, without regard to case, both folders */
    CHECK(attrs[0] == 0x20 && sizes[0] == 1 && sizes[1] == 2 && sizes[2] == 4);
    CHECK(CRT("_findnext", h, data) == 0xFFFFFFFFu);                                          /* no more */
    errno_cell = CRT("_errno");
    CHECK(RD32(errno_cell) == 2);                                                              /* ENOENT */
    CHECK(CRT("_findclose", h) == 0 && CRT("_findclose", h) == 0xFFFFFFFFu);

    h = CRT("_findfirst", cstr("C:\\Magic\\Program\\Art\\*.*"), data);                        /* "." and ".." where the pattern takes them, and a folder is a folder */
    n = 0;
    while (h != 0xFFFFFFFFu) {
        snprintf(names[n], sizeof(names[n]), "%s", text(data + 20));
        attrs[n++] = RD32(data);
        if (CRT("_findnext", h, data) != 0)
            break;
    }
    CHECK(n == 7 && !strcmp(names[0], ".") && !strcmp(names[1], "..") && attrs[0] == 0x10);
    {
        int sub = -1, i;

        for (i = 0; i < (int)n; i++)
            if (!strcmp(names[i], "sub"))
                sub = i;
        CHECK(sub >= 0 && attrs[sub] == 0x10);
    }
    CRT("_findclose", h);
    CHECK(CRT("_findfirst", cstr("C:\\Magic\\Program\\Art\\*.zzz"), data) == 0xFFFFFFFFu && RD32(CRT("_errno")) == 2);
    CHECK(CRT("_findfirst", cstr("C:\\Magic\\Program\\NoSuchFolder\\*.pic"), data) == 0xFFFFFFFFu);
    CHECK(CRT("_findfirst", cstr("C:\\Magic\\Program\\ART\\B.PIC"), data) != 0xFFFFFFFFu);      /* a name without a wildcard, in any case */
}

int main(void)
{
    char base[600];

    main_image.path = "/game/shandalar.exe";
    guest_init();
    sched_init();
    port_sp = 0x002FFF00u;                                                                    /* the stack a call into the guest (qsort's comparison) is made on */
    test_tmpdir(base, sizeof(base), "win32_");
    snprintf(root, sizeof(root), "%s/game", base);
    snprintf(over, sizeof(over), "%s/over", base);
    plat_mkdir(root);
    plat_mkdir(over);
    test_find_api();
    test_version_and_folders();
    test_locale();
    test_tls();
    test_format_message();
    test_thread_times();
    test_registry();
    test_registry_store();
    test_qsort();
    test_strings_and_classes();
    test_file_title();
    test_find_files();
    test_rmtree(base);
    printf("test_win32: %d checks, %d failed\n", checks, failures);
    return failures != 0;
}

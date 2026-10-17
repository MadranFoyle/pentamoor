/*
 * plat.h - what differs between the hosts the runtime builds on, in one place.
 *
 * The runtime is written to POSIX (Linux, macOS) and builds on Windows with MinGW-w64 (gcc, winpthreads, the UCRT or msvcrt C library: `make -C src/port` in an MSYS2
 * MINGW64 shell). Everything that is not the same on both goes through this header, and is implemented once in plat_posix.c or plat_win.c, so the other files
 * hold no `#ifdef _WIN32` beyond the few spots that are a different spelling of the same call (a signal handler, a path separator).
 *
 *   - the guest's 4 GB address space (mmap on POSIX; VirtualAlloc reserve, committed as it is touched, on Windows: plat_guest_reserve, plat_guest_commit)
 *   - the game module's library (dlopen / LoadLibrary: plat_dlopen, plat_dlsym)
 *   - mkdir, localtime_r, "is this the same file", "can this be run", popen with binary output, the null device, the PATH separator
 *   - O_BINARY (0 where files have no text mode): every open() of a game file passes it
 *   - iOS (PLAT_IOS): an app cannot start another program, so plat_popen_read and plat_system fail there; the game modules are linked into the app (gamemod.c, PORT_STATIC_MODULES)
 *
 * The header includes no <windows.h> (it defines names the runtime uses itself); only plat_win.c does.
 */
#ifndef PORT_PLAT_H
#define PORT_PLAT_H

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#include <sys/stat.h>
#include <sys/types.h>
#define PLAT_WINDOWS 1
#define PLAT_PATH_LIST ';'                  /* separates the directories of $PATH */
#define PLAT_IS_SEP(c) ((c) == '/' || (c) == '\\')          /* a directory separator in a host path (both on Windows) */
#define PLAT_NULL_DEVICE "NUL"
#define PLAT_EXE_SUFFIX ".exe"
#define PLAT_MODULE_SUFFIX ".dll"
#else
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#define PLAT_PATH_LIST ':'
#define PLAT_IS_SEP(c) ((c) == '/')
#define PLAT_NULL_DEVICE "/dev/null"
#define PLAT_EXE_SUFFIX ""
#ifdef __APPLE__
#include <TargetConditionals.h>
#if TARGET_OS_IPHONE
#define PLAT_IOS 1                          /* iOS and iPadOS: no process can be started (no popen, no system) and the game's modules are linked into the app (docs/notes/ios.md) */
#endif
#define PLAT_MODULE_SUFFIX ".dylib"
#else
#define PLAT_MODULE_SUFFIX ".so"
#endif
#ifndef O_BINARY
#define O_BINARY 0
#endif
#endif

/* One-time start-up of the host layer (Windows: a 1 ms timer resolution, so a Sleep of a few milliseconds is that and not 15). Safe to call twice. */
void plat_init(void);

/* The guest's address space: all of the 32-bit range, reserved at a base the host chooses (the guest's addresses are offsets from it). NULL if it cannot be had.
 * POSIX: the pages are there, zero, when first touched. Windows: the range is reserved and a page is committed (zero) the first time anything touches it, by an
 * exception handler, so the commit charge follows what the game uses and not 4 GB. */
uint8_t *plat_guest_reserve(void);
/* Make [addr, addr+len) of the guest's memory usable by the host's own system calls (read(), write(), fread() straight into or out of it). A plain memory access
 * needs no call (Windows: the handler does it), but a system call is handed the address and fails with an error instead of faulting. A no-op on POSIX. */
#ifdef _WIN32
void plat_guest_commit(uint32_t addr, uint32_t len);
#else
#define plat_guest_commit(addr, len) ((void)(addr), (void)(len))
#endif

/* The game module (a shared library): the path may be relative. plat_dlopen returns NULL and writes a message into err on failure. */
void *plat_dlopen(const char *path, char *err, size_t n);
void *plat_dlsym(void *lib, const char *name);

/* The last directory separator of a host path, or NULL; the file name after it. */
static inline char *plat_last_sep(const char *p)
{
    char *last = NULL;

    for (; *p; p++)
        if (PLAT_IS_SEP(*p))
            last = (char *)p;
    return last;
}
static inline const char *plat_basename(const char *p)
{
    const char *s = plat_last_sep(p);

    return s ? s + 1 : p;
}

int plat_mkdir(const char *path);                                      /* 0 on success, like mkdir(path, 0777) */
struct tm *plat_localtime(const time_t *t, struct tm *out);
struct tm *plat_gmtime(const time_t *t, struct tm *out);
int plat_same_file(const char *a, const char *b);                      /* both name the same file (the same inode on POSIX; the same full path, ignoring case, on Windows) */
int plat_is_executable(const char *path);                              /* a file that can be run (Windows: a file) */
FILE *plat_popen_read(const char *cmd);                                /* popen(cmd, "r") with binary output (a command of the platform's shell) */
int plat_pclose(FILE *f);
int plat_system(const char *cmd);                                      /* system(cmd) (a command of the platform's shell) */

#endif

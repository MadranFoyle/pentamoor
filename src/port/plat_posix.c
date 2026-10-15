/* plat_posix.c - plat.h on Linux and macOS. (plat_win.c is the other.) */
#ifndef _WIN32
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#include "plat.h"

void plat_init(void) {}

uint8_t *plat_guest_reserve(void)
{
    /* All of the 32-bit address space; pages are committed when first touched. */
    void *p = mmap(NULL, 1ull << 32, PROT_READ | PROT_WRITE, MAP_ANON | MAP_PRIVATE | MAP_NORESERVE, -1, 0);

    return p == MAP_FAILED ? NULL : p;
}

void *plat_dlopen(const char *path, char *err, size_t n)
{
    void *h = dlopen(path, RTLD_NOW | RTLD_LOCAL);

    if (!h) {
        const char *e = dlerror();

        snprintf(err, n, "%s", e ? e : "dlopen failed");
    }
    return h;
}

void *plat_dlsym(void *lib, const char *name) { return dlsym(lib, name); }

int plat_mkdir(const char *path) { return mkdir(path, 0777); }
struct tm *plat_localtime(const time_t *t, struct tm *out) { return localtime_r(t, out); }
struct tm *plat_gmtime(const time_t *t, struct tm *out) { return gmtime_r(t, out); }

int plat_same_file(const char *a, const char *b)
{
    struct stat s1, s2;

    return !stat(a, &s1) && !stat(b, &s2) && s1.st_dev == s2.st_dev && s1.st_ino == s2.st_ino;
}

int plat_is_executable(const char *path) { return access(path, X_OK) == 0; }
FILE *plat_popen_read(const char *cmd) { return popen(cmd, "r"); }
int plat_pclose(FILE *f) { return pclose(f); }
int plat_system(const char *cmd) { return system(cmd); }
#endif

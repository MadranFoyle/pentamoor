/* test_util.h - what the unit tests need of the host beyond plat.h: a scratch folder and its removal, the same on POSIX and Windows (no mkdtemp, no `rm -rf`). */
#ifndef PORT_TEST_UTIL_H
#define PORT_TEST_UTIL_H

#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "plat.h"

/* A new empty folder under the system's temporary one (/tmp; Windows: %TEMP%), named prefix + process id + a counter; out is "" if none could be made. */
static void test_tmpdir(char *out, size_t cap, const char *prefix)
{
    const char *base = "/tmp";
    int n;

#ifdef _WIN32
    base = getenv("TEMP") ? getenv("TEMP") : getenv("TMP") ? getenv("TMP") : ".";
#endif
    for (n = 0; n < 1000; n++) {
        snprintf(out, cap, "%s/%s%d_%d", base, prefix, (int)getpid(), n);
        if (plat_mkdir(out) == 0)
            return;
    }
    out[0] = 0;
}

/* rm -rf */
static void test_rmtree(const char *path)
{
    DIR *d = opendir(path);
    struct dirent *e;

    while (d && (e = readdir(d))) {
        char sub[1400];
        struct stat st;

        if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, ".."))
            continue;
        snprintf(sub, sizeof(sub), "%s/%s", path, e->d_name);
        if (stat(sub, &st) == 0 && S_ISDIR(st.st_mode))
            test_rmtree(sub);
        else
            unlink(sub);
    }
    if (d)
        closedir(d);
    rmdir(path);
}

#endif

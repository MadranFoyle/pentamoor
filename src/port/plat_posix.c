/* plat_posix.c - plat.h on Linux and macOS. (plat_win.c is the other.) */
#ifndef _WIN32
#include <dlfcn.h>
#include <errno.h>
#include <signal.h>
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
#ifdef PLAT_IOS
/* An iOS app cannot start another program (system() is not in its SDK, popen() fails in its sandbox). The only user is the ffmpeg pipe, which movie.c does not try there. */
FILE *plat_popen_read(const char *cmd) { (void)cmd; return NULL; }
int plat_pclose(FILE *f) { return f ? pclose(f) : -1; }
int plat_system(const char *cmd) { (void)cmd; return -1; }
#else
FILE *plat_popen_read(const char *cmd) { return popen(cmd, "r"); }
int plat_pclose(FILE *f) { return pclose(f); }
int plat_system(const char *cmd) { return system(cmd); }
#endif

/* ---- starting another program ------------------------------------------------------------------------------------------------------ */
#ifdef PLAT_IOS
int plat_self_path(char *out, size_t cap) { (void)out; (void)cap; return 0; }
int plat_spawn(const char *const *argv, const char *const *set, const char *const *unset, long *id) { (void)argv; (void)set; (void)unset; (void)id; return -1; }
int plat_child_state(long id, int *exit_code) { (void)id; (void)exit_code; return -1; }
int plat_pid_alive(long pid) { (void)pid; return 0; }
#else
#include <sys/wait.h>
#ifdef __APPLE__
#include <mach-o/dyld.h>
#endif
extern char **environ;

int plat_self_path(char *out, size_t cap)
{
#ifdef __APPLE__
    uint32_t n = (uint32_t)cap;
    char tmp[4096];

    if (_NSGetExecutablePath(out, &n) != 0)
        return 0;
    if (realpath(out, tmp)) {
        snprintf(out, cap, "%s", tmp);
    }
    return 1;
#else
    ssize_t n = readlink("/proc/self/exe", out, cap - 1);

    if (n <= 0)
        return 0;
    out[n] = 0;
    return 1;
#endif
}

static int env_is(const char *entry, const char *name, size_t n) { return !strncmp(entry, name, n) && entry[n] == '='; }

int plat_spawn(const char *const *argv, const char *const *set, const char *const *unset, long *id)
{
    size_t n = 0, k = 0, i, j;
    char **envp;
    pid_t pid;

    while (environ[n])
        n++;
    for (i = 0; set && set[i]; i++)
        n++;
    envp = calloc(n + 1, sizeof(*envp));
    if (!envp)
        return -1;
    for (i = 0; environ[i]; i++) {                 /* this process's environment, less what is unset or replaced */
        int drop = 0;

        for (j = 0; unset && unset[j]; j++)
            if (env_is(environ[i], unset[j], strlen(unset[j])))
                drop = 1;
        for (j = 0; set && set[j]; j++) {
            const char *eq = strchr(set[j], '=');

            if (eq && env_is(environ[i], set[j], (size_t)(eq - set[j])))
                drop = 1;
        }
        if (!drop)
            envp[k++] = environ[i];
    }
    for (i = 0; set && set[i]; i++)
        envp[k++] = (char *)set[i];
    envp[k] = NULL;
    fflush(NULL);                                  /* nothing the parent has buffered is written twice */
    pid = fork();
    if (pid < 0) {
        free(envp);
        return -1;
    }
    if (pid == 0) {
        execve(argv[0], (char *const *)argv, envp);
        _exit(127);
    }
    free(envp);
    *id = (long)pid;
    return 0;
}

int plat_child_state(long id, int *exit_code)
{
    int status = 0;
    pid_t r = waitpid((pid_t)id, &status, WNOHANG);

    if (r == 0)
        return 0;
    if (r < 0)
        return -1;
    *exit_code = WIFEXITED(status) ? WEXITSTATUS(status) : 128 + (WIFSIGNALED(status) ? WTERMSIG(status) : 0);
    return 1;
}
#endif

int plat_pid_alive(long pid)
{
    return pid > 0 && (kill((pid_t)pid, 0) == 0 || errno == EPERM);
}

int plat_make_control(const char *path)
{
    if (mkfifo(path, 0600) == 0 || errno == EEXIST)
        return 0;
    return -1;
}
#endif

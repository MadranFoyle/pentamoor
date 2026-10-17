/* process.c - the process model (see process.h): starting another program of the game as another copy of the runtime, and waiting for it. */
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "plat.h"
#include "port.h"
#include "process.h"
#include "sched.h"

extern Image main_image;
#define P(a) ((char *)(G + (a)))
#define DEFAULT_FOLDER "C:\\Magic\\Program"

/* ---- reading a command line ------------------------------------------------------------------------------------------------------ */
size_t proc_first_word(const char *line, char *word, size_t cap, const char **rest)
{
    size_t n = 0;

    while (*line == ' ' || *line == '\t')
        line++;
    if (*line == '"') {
        line++;
        while (*line && *line != '"') {
            if (n + 1 < cap)
                word[n++] = *line;
            line++;
        }
        if (*line == '"')
            line++;
    } else {
        while (*line && *line != ' ' && *line != '\t') {
            if (n + 1 < cap)
                word[n++] = *line;
            line++;
        }
    }
    if (cap)
        word[n] = 0;
    while (*line == ' ' || *line == '\t')
        line++;
    if (rest)
        *rest = line;
    return n;
}

int proc_plan(const BuildProfile *p, const char *application, const char *command_line, ProcPlan *plan)
{
    char word[300], name[300];
    const char *rest = "", *sep;
    size_t i, n;

    memset(plan, 0, sizeof(*plan));
    if (!p)
        return -1;
    n = proc_first_word(command_line ? command_line : "", word, sizeof(word), &rest);      /* the program's name as the program sees it, then its arguments */
    if (application && *application)
        snprintf(word, sizeof(word), "%s", application);
    else if (!n)
        return -1;
    sep = word;
    for (i = 0; word[i]; i++)
        if (word[i] == '\\' || word[i] == '/' || word[i] == ':')
            sep = word + i + 1;
    snprintf(name, sizeof(name), "%s", sep);
    if (!name[0])
        return -1;
    if (!strchr(name, '.'))
        strncat(name, ".exe", sizeof(name) - strlen(name) - 1);
    for (i = 0; name[i]; i++)
        name[i] = (char)tolower((unsigned char)name[i]);
    snprintf(plan->file, sizeof(plan->file), "%s", name);
    if (sep > word) {
        snprintf(plan->folder, sizeof(plan->folder), "%.*s", (int)(sep - word - 1), word);
    }
    snprintf(plan->args, sizeof(plan->args), "%s", rest);
    for (i = 0; i < PROFILE_MAX_PROGRAMS && p->programs[i].file; i++)
        if (!strcmp(p->programs[i].file, plan->file)) {
            plan->module = p->programs[i].module;
            return 0;
        }
    return -1;
}

/* ---- the new process's command line and environment ------------------------------------------------------------------------------ */
static char *put(ProcChild *c, size_t *at, const char *s)
{
    size_t n = strlen(s) + 1;
    char *p;

    if (*at + n > sizeof(c->buf))
        return c->buf + sizeof(c->buf) - 1;                 /* (no room: the empty string at the end; paths are a few hundred bytes and the buffer is 8 KB) */
    p = c->buf + *at;
    memcpy(p, s, n);
    *at += n;
    return p;
}

void proc_child(ProcChild *c, const ProcPlan *plan, const char *runtime, const char *module_dir, const char *host_exe, const char *root, const char *overlay, int width,
                int height, const char *control, const char *shm)
{
    size_t at = 0;
    char tmp[1400], stem[64];
    int ns = 0, nu = 0, na = 0;
    char *dot;

    memset(c, 0, sizeof(*c));
    c->argv[na++] = put(c, &at, runtime);
    c->argv[na++] = put(c, &at, "-m");
    snprintf(tmp, sizeof(tmp), "%s%s%s%s", module_dir, module_dir[0] ? "/" : "", plan->module, PLAT_MODULE_SUFFIX);
    c->argv[na++] = put(c, &at, tmp);
    c->argv[na++] = put(c, &at, host_exe);
    c->argv[na++] = put(c, &at, root);
    c->argv[na] = NULL;
    snprintf(tmp, sizeof(tmp), "PORT_OVERLAY=%s", overlay);
    c->set[ns++] = put(c, &at, tmp);
    snprintf(tmp, sizeof(tmp), "PORT_RES=%dx%d", width, height);
    c->set[ns++] = put(c, &at, tmp);
    snprintf(tmp, sizeof(tmp), "PORT_CMDLINE=%s", plan->args);
    c->set[ns++] = put(c, &at, tmp);
    if (control && *control) {
        snprintf(stem, sizeof(stem), "%s", plan->file);
        dot = strrchr(stem, '.');
        if (dot)
            *dot = 0;
        snprintf(tmp, sizeof(tmp), "PORT_CONTROL=%s.%s", control, stem);
        c->set[ns] = put(c, &at, tmp);
        c->control = c->set[ns++] + strlen("PORT_CONTROL=");
    }
    if (shm && *shm) {
        snprintf(tmp, sizeof(tmp), "PORT_SHM=%s", shm);
        c->set[ns++] = put(c, &at, tmp);
    }
    c->set[ns] = NULL;
    c->unset[nu++] = put(c, &at, "PORT_SCRIPT");
    c->unset[nu] = NULL;
}

/* ---- children ------------------------------------------------------------------------------------------------------------------- */
#define MAX_CHILDREN 16
static struct { long id; int used, done, code; } children[MAX_CHILDREN];

/* The folder the named memory is handed over in: the one this process was given ($PORT_SHM, if it was started by another program), else one it makes beside the saves and takes away
 * when it ends. */
static char shm_made[1200];
static const char *shm_dir;

static void shm_cleanup(void)
{
    if (shm_made[0])
        k32_shared_remove(shm_made);
}

static const char *shm_folder(void)
{
    const char *given = getenv("PORT_SHM");

    if (shm_dir)
        return shm_dir;
    if (given && *given)
        return shm_dir = given;
    snprintf(shm_made, sizeof(shm_made), "%s/shm-%ld", paths_overlay(), (long)getpid());
    paths_mkdirs(shm_made);
    atexit(shm_cleanup);
    return shm_dir = shm_made;
}

int proc_start(const char *application, const char *command_line, long *id)
{
    ProcPlan plan;
    ProcChild child;
    char guest[600], host[1200], runtime[1100], module_dir[1100], module[1200];
    const char *mod = gamemod_path(), *control = getenv("PORT_CONTROL");
    char *sep;
    FILE *f;
    int i;

    if (proc_plan(profile, application, command_line, &plan) != 0) {
        char word[300];

        proc_first_word(application && *application ? application : command_line ? command_line : "", word, sizeof(word), NULL);
        port_log("process: not started: %s is not a program the profile of this build (%s %s) names", word, profile->build, profile->file);
        return 2;                                                   /* ERROR_FILE_NOT_FOUND */
    }
    snprintf(guest, sizeof(guest), "%s\\%s", plan.folder[0] ? plan.folder : DEFAULT_FOLDER, plan.file);
    if (!paths_host(guest, 0, host, sizeof(host))) {
        port_log("process: not started: %s is not in the game folder", guest);
        return 2;
    }
    snprintf(module_dir, sizeof(module_dir), "%s", mod);
    sep = plat_last_sep(module_dir);
    if (sep)
        *sep = 0;
    else
        module_dir[0] = 0;
    snprintf(module, sizeof(module), "%s%s%s%s", module_dir, module_dir[0] ? "/" : "", plan.module, PLAT_MODULE_SUFFIX);
    f = fopen(module, "rb");
    if (!f) {
        port_log("process: not started: the game module %s for %s is not there (it is built with the others: tools/install)", module, plan.file);
        return 2;
    }
    fclose(f);
    if (!plat_self_path(runtime, sizeof(runtime))) {
        port_log("process: not started: the path of the runtime itself is not known");
        return 2;
    }
    k32_shared_flush(shm_folder());                          /* what this program has in its named memory is what the new one finds there */
    proc_child(&child, &plan, runtime, module_dir, host, paths_root(), paths_overlay(), screen_w, screen_h, control, shm_dir);
    if (child.control)
        plat_make_control(child.control);                        /* the pipe the child reads */
    for (i = 0; i < MAX_CHILDREN && children[i].used; i++)
        ;
    if (i == MAX_CHILDREN) {
        port_log("process: not started: too many programs started and not waited for");
        return 8;
    }
    if (plat_spawn(child.argv, child.set, child.unset, id) != 0) {
        port_log("process: %s could not be started", plan.file);
        return 5;
    }
    children[i].id = *id;
    children[i].used = 1;
    children[i].done = 0;
    port_log("process: started %s (module %s, id %ld)", plan.file, plan.module, *id);
    return 0;
}

int proc_done(long id, int *exit_code)
{
    int i, code = 0;

    for (i = 0; i < MAX_CHILDREN; i++)
        if (children[i].used && children[i].id == id) {
            if (!children[i].done) {
                int r = plat_child_state(id, &code);

                if (r == 0)
                    return 0;
                children[i].done = 1;
                children[i].code = r > 0 ? code : -1;
                if (shm_dir) {
                    k32_shared_reload(shm_dir);                  /* and what it left there is this program's again */
                    port_trace("process: child %ld ended with %d; named memory read back from %s", id, children[i].code, shm_dir);
                }
            }
            *exit_code = children[i].code;
            return 1;
        }
    *exit_code = -1;
    return 1;
}

static int child_ready(void *ctx)
{
    int code;

    return proc_done((long)(intptr_t)ctx, &code);
}

int proc_wait(long id)
{
    int code = -1;

    sched_block(child_ready, (void *)(intptr_t)id, -1);         /* the other guest threads, and the window, go on while it runs */
    proc_done(id, &code);
    return code;
}

/* ---- the arguments this process was started with --------------------------------------------------------------------------------- */
const char *proc_args(void)
{
    const char *e = getenv("PORT_CMDLINE");

    return e ? e : "";
}

void proc_command_line(char *out, size_t cap)
{
    const char *args = proc_args();
    size_t i;

    snprintf(out, cap, "C:\\Magic\\Program\\%s%s%s", plat_basename(main_image.path), *args ? " " : "", args);
    for (i = 0; out[i] && out[i] != ' '; i++)                    /* the program's name in upper case, as the installer's folder spells it */
        if (out[i] >= 'a' && out[i] <= 'z')
            out[i] = (char)(out[i] - 32);
}

/* ---- the guest's handles for children --------------------------------------------------------------------------------------------- */
#define HANDLE_BASE 0x7E800000u
static long handle_child[MAX_CHILDREN];
static int handle_used[MAX_CHILDREN];

uint32_t proc_handle_new(long id)
{
    int i;

    for (i = 0; i < MAX_CHILDREN; i++)
        if (!handle_used[i]) {
            handle_used[i] = 1;
            handle_child[i] = id;
            return HANDLE_BASE + 4u * (uint32_t)i;
        }
    return 0;
}

static int handle_slot(uint32_t h)
{
    if (h < HANDLE_BASE || h >= HANDLE_BASE + 4u * MAX_CHILDREN || (h - HANDLE_BASE) % 4)
        return -1;
    return handle_used[(h - HANDLE_BASE) / 4] ? (int)((h - HANDLE_BASE) / 4) : -1;
}

int proc_handle_known(uint32_t h) { return handle_slot(h) >= 0; }

int proc_handle_done(uint32_t h, int *exit_code)
{
    int s = handle_slot(h);

    return s >= 0 && proc_done(handle_child[s], exit_code);
}

int proc_handle_wait(uint32_t h, double timeout)
{
    int s = handle_slot(h);

    if (s < 0)
        return 1;
    sched_block(child_ready, (void *)(intptr_t)handle_child[s], timeout);
    return child_ready((void *)(intptr_t)handle_child[s]);
}

void proc_handle_close(uint32_t h)
{
    int s = handle_slot(h);

    if (s >= 0)
        handle_used[s] = 0;
}

/* ---- the calls --------------------------------------------------------------------------------------------------------------------- */
/* WinExec(command line, show): 33 on success (anything over 31 is), else the error number (2: no such program). The program runs on its own. */
static uint32_t WinExec(const uint32_t *a)
{
    long id;
    int err = proc_start(NULL, P(a[0]), &id);

    return err ? (uint32_t)err : 33;
}

/* CreateProcessA(application, command line, ..., &STARTUPINFO, &PROCESS_INFORMATION): a handle for the new program in hProcess (to wait on, to ask the exit code of) and the id. */
static uint32_t CreateProcessA(const uint32_t *a)
{
    long id;
    int err = proc_start(a[0] ? P(a[0]) : NULL, a[1] ? P(a[1]) : "", &id);
    uint32_t h;

    if (err) {
        k32_set_last_error((uint32_t)err);
        return 0;
    }
    h = proc_handle_new(id);
    if (a[9]) {
        WR32(a[9], h);                                 /* hProcess */
        WR32(a[9] + 4, h);                             /* hThread: the same handle: the program waits on the process */
        WR32(a[9] + 8, (uint32_t)id);                  /* dwProcessId */
        WR32(a[9] + 12, (uint32_t)id);                 /* dwThreadId */
    }
    return 1;
}

/* GetExitCodeProcess(process, &code): the code of a program that has ended, STILL_ACTIVE (259) for one that has not. */
static uint32_t GetExitCodeProcess(const uint32_t *a)
{
    int code = 0;

    if (!proc_handle_known(a[0]))
        return 0;
    WR32(a[1], proc_handle_done(a[0], &code) ? (uint32_t)code : 259u);
    return 1;
}

const WinApi PROCESS_APIS[] = {
    {"kernel32.dll", "WinExec", WinExec}, {"kernel32.dll", "CreateProcessA", CreateProcessA}, {"kernel32.dll", "GetExitCodeProcess", GetExitCodeProcess},
    {0, 0, 0},
};

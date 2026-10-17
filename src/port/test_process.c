/* test_process.c - the process model (process.c): reading a command line, looking a program up in a build's profile, the command line and environment of the process that is started,
 * and, on a host that can start a process, the whole of it with this test program standing in for the runtime: a program is started (_spawnl, CreateProcessA, WinExec), told its
 * arguments, handed the named memory of the one that started it, waited for, and its exit code and the memory it left are the parent's again. No game file is needed.
 *   make -C src/port test */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "plat.h"
#include "port.h"
#include "process.h"
#include "profile.h"
#include "sched.h"
#include "test_util.h"

#ifdef _WIN32                                                                              /* MinGW's C library has no setenv or unsetenv */
#define setenv(name, value, overwrite) _putenv_s((name), (value))
#define unsetenv(name) _putenv_s((name), "")
#endif

int pe_find_resource(uint32_t hinst, uint32_t type, uint32_t name, uint32_t *addr, uint32_t *size) { (void)hinst; (void)type; (void)name; (void)addr; (void)size; return 0; }
extern Image main_image;

static int failures, checks;
#define CHECK(c) do { checks++; if (!(c)) { failures++; printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

static uint32_t cursor = 0x01000000u;
static uint32_t scratch(uint32_t n) { uint32_t p = cursor; cursor += (n + 15) & ~15u; return p; }
static uint32_t cstr(const char *s) { uint32_t p = scratch((uint32_t)strlen(s) + 1); strcpy((char *)(G + p), s); return p; }

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
static uint32_t CRT_SPAWN(uint32_t mode, const char *path, const char *arg0, const char *arg1)     /* _spawnl(mode, path, arg0, arg1, NULL) */
{
    return API("msvcrt.dll", "_spawnl", mode, cstr(path), cstr(arg0), cstr(arg1), 0);
}

/* ---- the child: this program started with `-m MODULE EXE ROOT`, as the runtime is ----------------------------------------------------------------------- */
#ifndef _WIN32
#define SHM_SIZE 4096
static int child_main(int argc, char **argv)
{
    const char *cmd = getenv("PORT_CMDLINE"), *shm = getenv("PORT_SHM"), *res = getenv("PORT_RES"), *overlay = getenv("PORT_OVERLAY"), *control = getenv("PORT_CONTROL");
    char path[1300], seen[16] = "";
    FILE *f;
    int ok = argc == 5 && !strcmp(argv[1], "-m") && strstr(argv[2], "game_tchild") != NULL && strstr(argv[3], "child.exe") != NULL;

    ok = ok && cmd && !strcmp(cmd, "/S") && res && !strcmp(res, "800x600") && overlay && !strcmp(overlay, getenv("TEST_EXPECT_OVERLAY") ? getenv("TEST_EXPECT_OVERLAY") : "") && shm;
    ok = ok && getenv("PORT_SCRIPT") == NULL;                                                /* the parent's script is not the child's */
    ok = ok && (getenv("TEST_EXPECT_CONTROL") ? control && !strcmp(control, getenv("TEST_EXPECT_CONTROL")) : control == NULL);
    if (!shm)
        return 3;
    snprintf(path, sizeof(path), "%s/rpbips2", shm);
    f = fopen(path, "rb");
    if (f) {
        if (fread(seen, 1, 7, f) != 7)
            seen[0] = 0;
        fclose(f);
    }
    ok = ok && !strncmp(seen, "PARENT", 7);                                                   /* the parent's named memory was handed over before the start */
    f = fopen(path, "wb");                                                                    /* and what this one leaves is handed back (kernel32.c does it at exit) */
    if (f) {
        char block[SHM_SIZE];

        memset(block, 0, sizeof(block));
        strcpy(block, "CHILD");
        fwrite(block, 1, sizeof(block), f);
        fclose(f);
    }
    return ok ? 7 : 3;
}
#endif

/* ---- reading a command line ------------------------------------------------------------------------------------------------------------------------ */
static void test_first_word(void)
{
    char word[64];
    const char *rest;

    CHECK(proc_first_word("C:\\Magic\\Program\\FaceMaker.exe /S", word, sizeof(word), &rest) == 30 && !strcmp(word, "C:\\Magic\\Program\\FaceMaker.exe") && !strcmp(rest, "/S"));
    CHECK(proc_first_word("\"C:\\Program Files\\x y.exe\" a  b", word, sizeof(word), &rest) == 24 && !strcmp(word, "C:\\Program Files\\x y.exe") && !strcmp(rest, "a  b"));
    CHECK(proc_first_word("  prog   ", word, sizeof(word), &rest) == 4 && !strcmp(word, "prog") && !strcmp(rest, ""));
    CHECK(proc_first_word("", word, sizeof(word), &rest) == 0 && !strcmp(word, "") && !strcmp(rest, ""));
    CHECK(proc_first_word("abcdefghij k", word, 4, &rest) == 3 && !strcmp(word, "abc") && !strcmp(rest, "k"));               /* a word longer than the buffer is cut, and still skipped */
    CHECK(proc_first_word("tab\tseparated", word, sizeof(word), &rest) == 3 && !strcmp(rest, "separated"));
    CHECK(proc_first_word("\"unclosed quote", word, sizeof(word), &rest) == 14 && !strcmp(word, "unclosed quote"));
}

/* ---- the profile's list of programs ----------------------------------------------------------------------------------------------------------------- */
static const BuildProfile fake = {
    .id = "ff", .build = "v0", .file = "game.exe", .program = "GAME",
    .programs = {{"facemaker.exe", "game_facemaker"}, {"deck.exe", "game_sotadeck"}, {"child.exe", "game_tchild"}},
};
static const BuildProfile none = {.id = "ee", .build = "v0", .file = "x.exe", .program = "X"};

static void test_plan(void)
{
    ProcPlan plan;

    CHECK(proc_plan(&fake, NULL, "C:\\Magic\\Program\\Facemaker.exe /S", &plan) == 0);
    CHECK(!strcmp(plan.file, "facemaker.exe") && !strcmp(plan.folder, "C:\\Magic\\Program") && !strcmp(plan.module, "game_facemaker") && !strcmp(plan.args, "/S"));
    CHECK(proc_plan(&fake, "C:\\Magic\\Program\\Facemaker.exe", "C:\\Magic\\Program\\Facemaker.exe /S", &plan) == 0 && !strcmp(plan.args, "/S"));     /* _spawnl and CreateProcessA name the file, and the line starts with it */
    CHECK(proc_plan(&fake, "FACEMAKER.EXE", "x /S /Q", &plan) == 0 && !strcmp(plan.file, "facemaker.exe") && !strcmp(plan.folder, "") && !strcmp(plan.args, "/S /Q"));
    CHECK(proc_plan(&fake, NULL, "facemaker /S", &plan) == 0 && !strcmp(plan.file, "facemaker.exe"));                       /* WinExec and CreateProcess take a name with no extension for .exe */
    CHECK(proc_plan(&fake, NULL, "\"C:\\Program Files\\Magic\\DECK.EXE\" a b", &plan) == 0 && !strcmp(plan.module, "game_sotadeck") && !strcmp(plan.args, "a b"));
    CHECK(proc_plan(&fake, NULL, "C:\\Magic\\Program\\Magic.exe /start3,1", &plan) == -1 && plan.module == NULL);              /* a program the profile does not name */
    CHECK(proc_plan(&fake, NULL, "", &plan) == -1 && proc_plan(&fake, NULL, NULL, &plan) == -1);
    CHECK(proc_plan(&fake, "C:\\Magic\\", "", &plan) == -1);                                                                  /* a folder is not a program */
    CHECK(proc_plan(&none, NULL, "facemaker.exe /S", &plan) == -1 && proc_plan(NULL, NULL, "facemaker.exe", &plan) == -1);       /* a build with no programs starts none */
    {
        const BuildProfile *sh = profile_find("e4e46718c451974756b66e7666ac0bf1cc9ebdbc5897eb04a87b8ea2a02353e7");               /* the real row of shandalar.exe 2.15 */

        CHECK(sh && proc_plan(sh, NULL, "C:\\MAGIC\\PROGRAM\\Facemaker.exe /S", &plan) == 0 && !strcmp(plan.module, "game_facemaker") && !strcmp(plan.args, "/S"));
        CHECK(sh && proc_plan(sh, NULL, "Magic.exe /start3,1", &plan) == -1 && proc_plan(sh, NULL, "Write c:/dump.txt", &plan) == -1);
        CHECK(!profile_find("4dc592695b6ee390485f283feb2a248cd3f3f739749c2800ab3b1100ea03845c")->programs[0].file);               /* MAGIC.EXE 1.0 starts nothing */
    }
}

static int in_list(const char *const *list, const char *want)
{
    int i;

    for (i = 0; list[i]; i++)
        if (!strcmp(list[i], want))
            return 1;
    return 0;
}

static void test_child(void)
{
    ProcChild c;
    ProcPlan plan;
    char want[300];

    proc_plan(&fake, NULL, "C:\\Magic\\Program\\FaceMaker.exe /S", &plan);
    proc_child(&c, &plan, "/opt/pentamoor-run", "/opt/mods", "/g/Program/FaceMaker.exe", "/g", "/o", 800, 600, "/tmp/ctl", "/tmp/shm");
    snprintf(want, sizeof(want), "/opt/mods/game_facemaker%s", PLAT_MODULE_SUFFIX);
    CHECK(!strcmp(c.argv[0], "/opt/pentamoor-run") && !strcmp(c.argv[1], "-m") && !strcmp(c.argv[2], want) && !strcmp(c.argv[3], "/g/Program/FaceMaker.exe") && !strcmp(c.argv[4], "/g") && !c.argv[5]);
    CHECK(in_list(c.set, "PORT_OVERLAY=/o") && in_list(c.set, "PORT_RES=800x600") && in_list(c.set, "PORT_CMDLINE=/S") && in_list(c.set, "PORT_SHM=/tmp/shm"));
    CHECK(in_list(c.set, "PORT_CONTROL=/tmp/ctl.facemaker") && c.control && !strcmp(c.control, "/tmp/ctl.facemaker"));         /* a pipe of its own */
    CHECK(in_list(c.unset, "PORT_SCRIPT"));
    proc_child(&c, &plan, "run", "", "exe", "root", "ov", 640, 480, NULL, NULL);
    snprintf(want, sizeof(want), "game_facemaker%s", PLAT_MODULE_SUFFIX);
    CHECK(!strcmp(c.argv[2], want));                                                                                          /* a module in the current folder: no slash */
    CHECK(in_list(c.set, "PORT_RES=640x480") && !c.control && !in_list(c.set, "PORT_CONTROL=") && !in_list(c.set, "PORT_SHM="));
    {
        int i;

        for (i = 0; c.set[i]; i++)
            CHECK(strncmp(c.set[i], "PORT_CONTROL", 12) != 0 && strncmp(c.set[i], "PORT_SHM", 8) != 0);                     /* none named when there is none to pass */
    }
}

static void test_arguments_the_guest_sees(void)
{
    char line[200];

    main_image.path = "/x/y/shandalar.exe";
    unsetenv("PORT_CMDLINE");
    proc_command_line(line, sizeof(line));
    CHECK(!strcmp(line, "C:\\MAGIC\\PROGRAM\\SHANDALAR.EXE") && !strcmp(proc_args(), ""));            /* GetCommandLineA: a path in capitals */
    proc_program_path(line, sizeof(line));
    CHECK(!strcmp(line, "C:\\Magic\\Program\\shandalar.exe"));                                                 /* argv[0]: the file's name as it is spelled */
    setenv("PORT_CMDLINE", "/S", 1);
    proc_command_line(line, sizeof(line));
    CHECK(!strcmp(line, "C:\\MAGIC\\PROGRAM\\SHANDALAR.EXE /S") && !strcmp(proc_args(), "/S"));                                   /* the arguments as given */
    proc_program_path(line, sizeof(line));
    CHECK(!strcmp(line, "C:\\Magic\\Program\\shandalar.exe /S"));
    unsetenv("PORT_CMDLINE");
}

/* ---- starting a program for real, on a host that can (the "runtime" is this program: child_main) ---------------------------------------------------------------- */
#ifndef _WIN32
static char base[600], root[700], over[700];

static void put(const char *rel, const char *body)
{
    char path[1400], *q;
    FILE *f;

    snprintf(path, sizeof(path), "%s/%s", base, rel);
    for (q = path + strlen(base) + 1; *q; q++)
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

static uint32_t named_page(uint32_t *view, const char *content)
{
    uint32_t map = API("kernel32.dll", "CreateFileMappingA", 0xFFFFFFFFu, 0, 4, 0, SHM_SIZE, cstr("rpbips2"));

    *view = API("kernel32.dll", "MapViewOfFile", map, 2, 0, 0, 0);
    guest_zero(*view, SHM_SIZE);
    strcpy((char *)(G + *view), content);
    return map;
}

static void test_start_and_wait(void)
{
    char modpath[800], mod[800];
    long id = 0;
    int code = -1;
    uint32_t view, map, pi = scratch(16), code_out = scratch(4), r;

    snprintf(mod, sizeof(mod), "%s/mods/game_other%s", base, PLAT_MODULE_SUFFIX);
    snprintf(modpath, sizeof(modpath), "%s/mods/game_tchild%s", base, PLAT_MODULE_SUFFIX);
    put("game/Program/child.exe", "not a program of the game");
    put("mods/game_tchild" PLAT_MODULE_SUFFIX, "not a library");
    setenv("TEST_MODULE_PATH", mod, 1);
    snprintf(root, sizeof(root), "%s/game", base);
    snprintf(over, sizeof(over), "%s/over", base);
    plat_mkdir(over);
    paths_init(root, over);
    screen_set(800, 600);
    profile = &fake;
    setenv("TEST_EXPECT_OVERLAY", over, 1);
    setenv("PORT_SCRIPT", "a script of the parent", 1);
    unsetenv("PORT_CONTROL");
    unsetenv("TEST_EXPECT_CONTROL");
    unsetenv("PORT_SHM");

    /* refused: a program the profile does not name, one it names that is not in the game folder, a module that is not there */
    CHECK(proc_start(NULL, "C:\\Magic\\Program\\Magic.exe /start3,1", &id) == 2);
    CHECK(proc_start(NULL, "C:\\Magic\\Program\\Facemaker.exe /S", &id) == 2);                                                 /* named by the profile, but there is no such file */
    CHECK(proc_start(NULL, "C:\\Magic\\Program\\Deck.exe", &id) == 2);
    put("game/Program/Deck.exe", "x");
    CHECK(proc_start(NULL, "C:\\Magic\\Program\\Deck.exe", &id) == 2);                                                         /* the file is there, game_sotadeck is not */
    CHECK(CRT_SPAWN(0, "C:\\Magic\\Program\\Magic.exe", "C:\\Magic\\Program\\Magic.exe", "/start3,1") == 0xFFFFFFFFu && RD32(API("msvcrt.dll", "_errno")) == 2);
    CHECK(API("kernel32.dll", "WinExec", cstr("Write c:/dump.txt"), 1) == 2);                                                  /* WinExec: an error number below 32 */
    CHECK(API("kernel32.dll", "CreateProcessA", 0, cstr("Magic.exe /start3,1"), 0, 0, 0, 0, 0, 0, 0, pi) == 0 && API("kernel32.dll", "GetLastError") == 2);

    /* the child sees its arguments, the folders and the screen size of the parent, no script, and the parent's named memory; the parent gets its exit code and its memory back */
    map = named_page(&view, "PARENT");
    r = CRT_SPAWN(0, "C:\\Magic\\Program\\Child.exe", "C:\\Magic\\Program\\Child.exe", "/S");
    CHECK(r == 7);                                                                                                            /* _P_WAIT: the child's exit status */
    CHECK(!strcmp((char *)(G + view), "CHILD"));                                                                              /* what it left in the page is the parent's now */
    (void)map;

    guest_zero(view, SHM_SIZE);
    strcpy((char *)(G + view), "PARENT");
    CHECK(proc_start("C:\\Magic\\Program\\Child.exe", "C:\\Magic\\Program\\Child.exe /S", &id) == 0 && id > 0);
    CHECK(proc_wait(id) == 7 && proc_done(id, &code) == 1 && code == 7);
    CHECK(!strcmp((char *)(G + view), "CHILD"));

    /* CreateProcessA gives a handle to wait on and ask the exit code of */
    guest_zero(view, SHM_SIZE);
    strcpy((char *)(G + view), "PARENT");
    CHECK(API("kernel32.dll", "CreateProcessA", 0, cstr("C:\\Magic\\Program\\Child.exe /S"), 0, 0, 0, 0, 0, 0, 0, pi) == 1);
    {
        uint32_t h = RD32(pi);

        CHECK(h != 0 && RD32(pi + 8) != 0 && proc_handle_known(h));
        CHECK(API("kernel32.dll", "WaitForSingleObject", h, 0xFFFFFFFFu) == 0);
        CHECK(API("kernel32.dll", "GetExitCodeProcess", h, code_out) == 1 && RD32(code_out) == 7);
        CHECK(!strcmp((char *)(G + view), "CHILD"));
        CHECK(API("kernel32.dll", "CloseHandle", h) == 1 && !proc_handle_known(h));
        CHECK(API("kernel32.dll", "GetExitCodeProcess", h, code_out) == 0);                                                    /* a closed handle is no process */
    }

}

static void test_control_pipe_of_the_child(void)
{
    char ctl[800], want[900];
    long id = 0;
    uint32_t view;
    struct stat st;

    snprintf(ctl, sizeof(ctl), "%s/control", base);
    snprintf(want, sizeof(want), "%s.child", ctl);
    setenv("PORT_CONTROL", ctl, 1);
    setenv("TEST_EXPECT_CONTROL", want, 1);
    named_page(&view, "PARENT");
    CHECK(proc_start(NULL, "C:\\Magic\\Program\\Child.exe /S", &id) == 0);
    CHECK(proc_wait(id) == 7);
    CHECK(stat(want, &st) == 0 && S_ISFIFO(st.st_mode));                                                                       /* the pipe the child reads was made by the parent */
    unsetenv("PORT_CONTROL");
    unsetenv("TEST_EXPECT_CONTROL");
}

/* WinExec starts a program and does not wait: 33, the number that means it was started (anything over 31 does) */
static void test_winexec(void)
{
    uint32_t view;

    named_page(&view, "PARENT");
    CHECK(API("kernel32.dll", "WinExec", cstr("C:\\Magic\\Program\\Child.exe /S"), 1) == 33);
}
#endif

int main(int argc, char **argv)
{
#ifndef _WIN32
    if (argc > 2 && !strcmp(argv[1], "-m"))
        return child_main(argc, argv);
#endif
    (void)argc;
    (void)argv;
    guest_init();
    sched_init();
    port_sp = 0x002FFF00u;
    test_first_word();
    test_plan();
    test_child();
    test_arguments_the_guest_sees();
#ifndef _WIN32
    test_tmpdir(base, sizeof(base), "process_");
    plat_mkdir(base);
    test_start_and_wait();
    test_control_pipe_of_the_child();
    test_winexec();
    usleep(300000);                                                                          /* the program WinExec started finishes by itself */
    test_rmtree(base);
#else
    printf("(starting a process is not tested on Windows here)\n");
#endif
    printf("test_process: %d checks, %d failed\n", checks, failures);
    return failures != 0;
}

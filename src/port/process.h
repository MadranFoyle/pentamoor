/*
 * process.h - the process model: a program of the game starting another one (_spawnl, WinExec, CreateProcessA).
 *
 * The runtime runs one program per process with one game module (`pentamoor-run -m game_shandalar.so SHANDALAR.EXE`). Spells of the Ancients' shandalar.exe starts FaceMaker.exe, the
 * portrait editor, when a colour is chosen, and waits for it. So a program that asks to start another is answered by starting another copy of the runtime, for that program, with its
 * game module: the module is the one the active build's profile names for the file (profile.h, `programs`), in the folder of the running module. The new process gets the same game
 * folder, the same overlay (saves are shared), the same screen size, and the arguments the program was given (in $PORT_CMDLINE, which GetCommandLineA and the C runtime's argv
 * show it as); a copy of PORT_CONTROL, if one is set, is a pipe of its own (the same name and ".<file>"), and PORT_SCRIPT is not passed on. A program the profile does not name is
 * not started: the call fails as it did before there was a process model.
 *
 * What the original does that this does not: two programs there share one screen; here each has its own window (the parent's stays up, and idle, while it waits).
 */
#ifndef PORT_PROCESS_H
#define PORT_PROCESS_H

#include <stddef.h>
#include <stdint.h>

#include "profile.h"

/* What a command line asks for, once it is looked up in a profile. */
typedef struct ProcPlan {
    char file[64];              /* the program's file name, lower case, with ".exe" ("facemaker.exe") */
    char folder[260];           /* the folder part as given ("C:\Magic\Program"), or "" */
    const char *module;         /* the game module that runs it ("game_facemaker"), from the profile */
    char args[512];             /* the command line after the program's own name (what the program is given to read): the child's $PORT_CMDLINE */
} ProcPlan;

/* The first word of a command line (in quotes if it starts with one), and the rest of the line after the spaces that follow it. Returns the length of the word, which is not NUL-ended
 * into `word` beyond `cap`. */
size_t proc_first_word(const char *line, char *word, size_t cap, const char **rest);

/* Look the program up. `application` is the file to run if the call named one (CreateProcessA's first argument, _spawnl's path), else the first word of `command_line`. `command_line` is
 * what follows in the new program's own command line: its first word is the program's name as the program will see it, and the rest are the arguments. 0, or -1 if the profile does not
 * name the program (or there is no profile with programs). */
int proc_plan(const BuildProfile *p, const char *application, const char *command_line, ProcPlan *plan);

/* The runtime's command line and environment for a plan. All strings are written into `buf`; the arrays point into it. Pure: the caller gives every path. `control` is the parent's
 * PORT_CONTROL or NULL. */
typedef struct ProcChild {
    const char *argv[8];
    const char *set[8];
    const char *unset[4];
    const char *control;        /* the child's PORT_CONTROL (inside buf), or NULL when the parent has none */
    char buf[8192];
} ProcChild;
void proc_child(ProcChild *c, const ProcPlan *plan, const char *runtime, const char *module_dir, const char *host_exe, const char *root, const char *overlay, int width,
                int height, const char *control);

/* Start the program a command line names, as the active profile allows; 0 and an id in *id on success, else a Windows error number (2: no such program). */
int proc_start(const char *application, const char *command_line, long *id);
/* The state of a child: 1 and its exit code when it has ended, 0 while it runs. */
int proc_done(long id, int *exit_code);
/* Wait until the child ends (the other guest threads run meanwhile) and return its exit code. */
int proc_wait(long id);

/* The arguments this process was started with ($PORT_CMDLINE), or "" */
const char *proc_args(void);
/* The command line the guest sees: "C:\Magic\Program\NAME.EXE" and the arguments. */
void proc_command_line(char *out, size_t cap);

/* The guest's handles for children (CreateProcessA, _spawnl with P_NOWAIT): numbers apart from kernel32's. */
uint32_t proc_handle_new(long id);
int proc_handle_known(uint32_t h);
int proc_handle_done(uint32_t h, int *exit_code);
int proc_handle_wait(uint32_t h, double timeout);      /* 1 if the child ended within `timeout` seconds (< 0: for ever) */
void proc_handle_close(uint32_t h);

#endif

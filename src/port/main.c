/* main.c - run the lifted game: port MAGIC.EXE-path [game-dir]
 *
 * One other mode, for the installer: `pentamoor-run -m MODULE --call-export NAME[=ARG,ARG...] FILE.DLL [root]` maps the DLL the module was lifted from as if it were the program, runs
 * its DllMain (DLL_PROCESS_ATTACH), calls the export NAME once with the given numbers as its stack arguments, prints "export NAME returned N" and ends. Nothing in it is specific to any
 * library: it is how the installer runs the one export of the owner's own library that tools/install/licence.py needs (docs/notes/sota-licence.md). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "front.h"
#include "pad.h"
#include "plat.h"
#include "port.h"
#include "process.h"
#include "profile.h"
#include "regstore.h"
#include "sched.h"
#include "screens.h"

void port_index_functions(void);
void kernel32_init(void);
void who_init(void);
Image main_image;
static const char *module_path;     /* -m: the game module (gamemod.c) */
static const char *export_spec;     /* --call-export: "Name" or "Name=1,0x2" */

#define DEFAULT_RES_W 1024
#define DEFAULT_RES_H 768

#define STACK_TOP 0x00300000u
#define STACK_SIZE 0x00200000u

void port_run(const Image *img)
{
    uint32_t esp = STACK_TOP - 0x100;
    const LiftedFn *lf = NULL;
    int i;

    for (i = 0; i < lift_game->nlifted; i++)
        if (lift_game->lifted[i].entry == img->entry)
            lf = &lift_game->lifted[i];
    if (!lf)
        port_fatal("the entry point 0x%08x was not lifted", img->entry);
    module_attach();                    /* DllMain of the libraries the program imports, before its own code runs */
    WR32(esp, 0);                       /* the return address: the entry point never returns (it calls ExitProcess) */
    memset(&lift_in, 0, sizeof(lift_in));
    lf->fn(esp);
    port_log("the entry point returned");
}

/* --call-export: DllMain of the library mapped as the program, then one of its exports. Returns the process's exit status: 0 when the export ran, 4 when it is not there or the spec is bad. */
static int run_export(const Image *img, const char *spec)
{
    char name[96];
    uint32_t args[8], dll_args[3], addr, r;
    int n = 0;
    const char *eq = strchr(spec, '=');
    size_t len = eq ? (size_t)(eq - spec) : strlen(spec);

    if (!len || len >= sizeof(name)) {
        fprintf(stderr, "pentamoor: --call-export wants NAME or NAME=ARG,ARG (numbers)\n");
        return 4;
    }
    memcpy(name, spec, len);
    name[len] = 0;
    while (eq && *eq) {
        char *end;
        unsigned long v = strtoul(eq + 1, &end, 0);

        if (end == eq + 1 || n >= 8 || (*end && *end != ',')) {
            fprintf(stderr, "pentamoor: --call-export: the arguments are up to eight numbers separated by commas\n");
            return 4;
        }
        args[n++] = (uint32_t)v;
        eq = end;
    }
    port_sp = STACK_TOP - 0x100;
    dll_args[0] = img->base;
    dll_args[1] = 1;                            /* DLL_PROCESS_ATTACH */
    dll_args[2] = 0;
    guest_call(img->entry, 3, dll_args);
    addr = pe_export(img->base, name);
    if (!addr) {
        fprintf(stderr, "pentamoor: %s has no export %s\n", img->path, name);
        return 4;
    }
    r = guest_call(addr, n, args);
    printf("export %s returned %u\n", name, r);
    fflush(stdout);
    return 0;
}

typedef struct { int argc; char **argv; } Args;

/* pad.h's guard for the Back button: whether the title menu is the screen that is on */
static int title_guard(void) { return screens_kind(port_now()) == SCREEN_TITLE; }

static int game_main(void *p)
{
    Args *args = p;
    int argc = args->argc;
    char **argv = args->argv;
    Image img;

    guest_init();
    gamemod_load(module_path);          /* the lifted code's tables; needs the guest's memory (the module is told where it is) */
    profile_init(argv[1]);              /* which build the program is: the addresses every hook below uses (profile.h); an unsupported build ends here, with status 3 */
    sched_init();
    kernel32_init();
    who_init();
    if (getenv("PORT_TRACE_IMPORTS"))
        port_trace_imports = 1;                 /* every import call, printed, from the start (the control pipe's "trace on" comes too late for start-up) */
    atexit(imports_report);                  /* what the run needed that is not implemented yet */
    if (front_has_window())
        front_install();
    port_index_functions();
    lzw_install();
    pace_install();
    textfocus_install();
    screens_install();
    pad_set_back_guard(title_guard);            /* Back (Escape) leaves the game from the title menu with no question: there it has to be held (pad.h) */
    yesno_install();
    sound_install();
    video_install();
    {
        char root_buf[1100], *root = argc > 2 ? argv[2] : root_buf, overlay[1100];
        char cwd[1000];

        if (!getcwd(cwd, sizeof(cwd)))
            cwd[0] = 0;
        if (argc <= 2) {            /* the game folder is the one above the executable's own (C:\Magic\Program\MAGIC.EXE) */
            char *slash;

            snprintf(root_buf, sizeof(root_buf), "%s", argv[1]);
            slash = plat_last_sep(root_buf);
            if (slash) {
                *slash = 0;
                slash = plat_last_sep(root_buf);
                if (slash)
                    *slash = 0;
            } else
                snprintf(root_buf, sizeof(root_buf), "..");
        }
        snprintf(overlay, sizeof(overlay), "%s", paths_overlay_default());
        paths_init(root, overlay);
        if (!strcmp(profile->build, "v2.15")) {         /* Spells of the Ancients 2.15 keeps the few registry values it reads and writes in its overlay (regstore.h); 1.0 and an unknown build keep none */
            char reg[1200];

            snprintf(reg, sizeof(reg), "%s/registry.dat", overlay);
            regstore_open(reg);
            if (profile->programs[0].file && !export_spec && !getenv("PORT_NO_INSTANCE_LOCK")) {      /* a program of the game that finds another running does not start (process.h) */
                char msg[600];

                if (proc_instance_enter(overlay, profile->file, msg, sizeof(msg))) {
                    fprintf(stderr, "%s\n", msg);
                    fflush(NULL);
                    exit(0);
                }
            }
        }
    }
    if (pe_load(argv[1], &img) != 0)
        port_fatal("cannot open %s", argv[1]);
    main_image = img;
    if (export_spec)
        return run_export(&img, export_spec);
    if (screen_w != 640 || screen_h != 480)
        profile_write_screen_size(screen_w, screen_h);      /* the game's own layouts for 800x600 and 1024x768 follow from its two screen-size globals (0x522458, 0x52245c in MAGIC.EXE 1.0) */
    port_log("loaded %s at 0x%08x, entry 0x%08x", argv[1], img.base, img.entry);
    (void)STACK_SIZE;
    port_run(&img);
    return 0;
}

#ifdef PORT_IOS
/* iOS: SDL owns main() (it starts UIKit, then calls SDL_main); ios_main.c's SDL_main builds the arguments an app does not have and calls this */
#define main pentamoor_main
#endif
int main(int argc, char **argv)
{
    Args args = {argc, argv};

    if (argc > 2 && (!strcmp(argv[1], "-m") || !strcmp(argv[1], "--module"))) {     /* pentamoor-run -m game_magic.so MAGIC.EXE [root] */
        module_path = argv[2];
        args.argc = argc -= 2;
        args.argv = argv += 2;
        argv[0] = args.argv[-2];
    }
    if (argc > 2 && !strcmp(argv[1], "--call-export")) {                              /* ... -m MODULE --call-export NAME[=ARGS] FILE.DLL [root] */
        export_spec = argv[2];
        args.argc = argc -= 2;
        args.argv = argv += 2;
        argv[0] = args.argv[-2];
    }
    if (argc < 2) {
        fprintf(stderr, "usage: %s [-m game module] [--call-export NAME[=ARG,...]] path/to/Magic/Program/MAGIC.EXE [path/to/Magic]\n(PORT_HEADLESS=1: no window; the module may be named by $PENTAMOOR_MODULE instead of -m)\n", argv[0]);
        return 1;
    }
    screen_set(DEFAULT_RES_W, DEFAULT_RES_H);   /* the default screen: 1024x768 (docs/notes/resolution.md) */
    if (getenv("PORT_RES")) {               /* PORT_RES=640x480 (the original's size), 800x600, 1024x768: the screen's size; the game has layouts for these three */
        int w = 0, h = 0;

        if (sscanf(getenv("PORT_RES"), "%dx%d", &w, &h) == 2)
            screen_set(w, h);
    }
    return front_run(game_main, &args);
}

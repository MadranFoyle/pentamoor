/* main.c - run the lifted game: port MAGIC.EXE-path [game-dir] */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "front.h"
#include "plat.h"
#include "port.h"
#include "sched.h"

void port_index_functions(void);
void kernel32_init(void);
void who_init(void);
Image main_image;
static const char *module_path;     /* -m: the game module (gamemod.c) */

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

typedef struct { int argc; char **argv; } Args;

static int game_main(void *p)
{
    Args *args = p;
    int argc = args->argc;
    char **argv = args->argv;
    Image img;

    guest_init();
    gamemod_load(module_path);          /* the lifted code's tables; needs the guest's memory (the module is told where it is) */
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
        snprintf(overlay, sizeof(overlay), "%s", getenv("PORT_OVERLAY") ? getenv("PORT_OVERLAY") : "port_overlay");
        paths_init(root, overlay);
    }
    if (pe_load(argv[1], &img) != 0)
        port_fatal("cannot open %s", argv[1]);
    main_image = img;
    if (!strcmp(lift_game->program, "MAGIC") && (screen_w != 640 || screen_h != 480)) {
        WR32(0x522458, (uint32_t)screen_w);      /* g_DisplayScreenWidth and Height: the game's own layouts for 800x600 and 1024x768 follow from them */
        WR32(0x52245c, (uint32_t)screen_h);
    }
    port_log("loaded %s at 0x%08x, entry 0x%08x", argv[1], img.base, img.entry);
    (void)STACK_SIZE;
    port_run(&img);
    return 0;
}

int main(int argc, char **argv)
{
    Args args = {argc, argv};

    if (argc > 2 && (!strcmp(argv[1], "-m") || !strcmp(argv[1], "--module"))) {     /* pentamoor-run -m game_magic.so MAGIC.EXE [root] */
        module_path = argv[2];
        args.argc = argc -= 2;
        args.argv = argv += 2;
        argv[0] = args.argv[-2];
    }
    if (argc < 2) {
        fprintf(stderr, "usage: %s [-m game module] path/to/Magic/Program/MAGIC.EXE [path/to/Magic]\n(PORT_HEADLESS=1: no window; the module may be named by $PENTAMOOR_MODULE instead of -m)\n", argv[0]);
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

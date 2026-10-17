/* ios_main.c - the iOS app's entry: what ./pentamoor does on a desktop. Built only for iOS (PORT_IOS); docs/notes/ios.md.
 *
 * SDL's own main() (libSDL2.a, SDL_uikit_main.c) starts UIKit and then calls SDL_main on the main thread, which is this. An app has no command line and no working folder, so:
 *   - the game is looked for in the app's Documents folder, Documents/Magic/Program/MAGIC.EXE (iosboot.h); when it is not there a message says where to put it;
 *   - saves and settings go to Documents/port_overlay (PORT_OVERLAY, unless the environment already names one);
 *   - the program is MAGIC.EXE unless $PENTAMOOR_PROGRAM or Documents/program.txt says deck or duel;
 *   - the game's code is not a file: the module is linked in, picked by name (gamemod.c);
 *   - stderr goes to Documents/pentamoor.log (the Files app shows it; PENTAMOOR_LOG=console keeps it on the console instead, which `xcrun simctl launch --console` shows).
 */
#include <SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "iosboot.h"
#include "plat.h"

#undef main
int pentamoor_main(int argc, char **argv);          /* main.c's main() */

static void read_file(const char *path, char *out, size_t n)
{
    FILE *f = fopen(path, "r");
    size_t got = 0;

    out[0] = 0;
    if (!f)
        return;
    got = fread(out, 1, n - 1, f);
    out[got] = 0;
    fclose(f);
}

int SDL_main(int argc, char **argv)
{
    char docs[1100], file[1300], text[64], msg[1600];
    const char *log = getenv("PENTAMOOR_LOG");
    IosBoot b;
    char *args[8];

    (void)argc;
    (void)argv;
    ios_documents(getenv("HOME"), docs, sizeof(docs));
    snprintf(file, sizeof(file), "%s/program.txt", docs);
    read_file(file, text, sizeof(text));
    ios_boot_paths(docs, ios_program(getenv("PENTAMOOR_PROGRAM"), text), &b);

    if (!log || strcmp(log, "console")) {
        snprintf(file, sizeof(file), "%s/pentamoor.log", docs);
        if (!freopen(file, "w", stderr))
            fprintf(stdout, "pentamoor: cannot write %s\n", file);
        setvbuf(stderr, NULL, _IOLBF, 0);
    }
    fprintf(stderr, "pentamoor (iOS): program %s, game %s, saves %s\n", b.program, b.exe, b.overlay);

    if (access(b.exe, R_OK) != 0) {
        ios_missing_text(&b, msg, sizeof(msg));
        fprintf(stderr, "pentamoor: %s is missing\n", b.exe);
        SDL_ShowSimpleMessageBox(SDL_MESSAGEBOX_INFORMATION, "Pentamoor", msg, NULL);
        return 1;
    }
    plat_mkdir(b.overlay);
    setenv("PORT_OVERLAY", b.overlay, 0);               /* a launch that names its own folder (simctl: SIMCTL_CHILD_PORT_OVERLAY) keeps it */

    args[0] = (char *)"pentamoor";
    args[1] = (char *)"-m";
    args[2] = b.program;
    args[3] = b.exe;
    args[4] = b.root;
    args[5] = NULL;
    return pentamoor_main(5, args);
}

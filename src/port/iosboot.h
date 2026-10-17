/*
 * iosboot.h - what the iOS app decides before the game starts, as pure functions: no SDL, no game, so they are unit tested (test_ios.c). docs/notes/ios.md.
 *
 * The app has no command line. It looks for the game in its Documents folder (the folder the Files app and Finder file sharing show), in the same layout as an install:
 *
 *   Documents/Magic/Program/MAGIC.EXE   (and the rest of sources/installed/Magic)
 *   Documents/port_overlay/             saves, display.cfg: made by the game (the install is never written to)
 *   Documents/program.txt               optional: one word, magic (the default), deck or duel, for the program to run
 *
 * $PENTAMOOR_PROGRAM (xcrun simctl launch, with SIMCTL_CHILD_PENTAMOOR_PROGRAM) wins over program.txt.
 */
#ifndef PORT_IOSBOOT_H
#define PORT_IOSBOOT_H

#include <stddef.h>

typedef struct {
    char program[8];            /* "magic", "deck" or "duel": the module that is linked in (gamemod.c) */
    char exe_name[16];          /* MAGIC.EXE, DECK.EXE, DUEL.EXE */
    char exe[1200];             /* <docs>/Magic/Program/<exe_name> */
    char root[1100];            /* <docs>/Magic: the game folder */
    char overlay[1100];         /* <docs>/port_overlay: where the game writes */
} IosBoot;

/* The program to run: `env` ($PENTAMOOR_PROGRAM) if it names one, else the first word of `file_text` (program.txt), else "magic". Case does not matter; "MAGIC.EXE" and "duel.exe" are
 * understood as well. Anything else is ignored (the next source is tried). Never NULL. */
const char *ios_program(const char *env, const char *file_text);

/* The paths for `program` under the Documents folder `docs` (no trailing slash needed). */
void ios_boot_paths(const char *docs, const char *program, IosBoot *out);

/* The Documents folder of the app: `home` ($HOME, which is the app's data container on iOS and in the simulator) + "/Documents"; "." when there is no home. */
void ios_documents(const char *home, char *out, size_t n);

/* What to tell the player when `exe` is missing: where to put the game, and how. `out` gets a few lines of plain text. */
void ios_missing_text(const IosBoot *b, char *out, size_t n);

#endif

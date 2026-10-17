/*
 * profile.h - build profiles: which build of the game the lifted code was made from, and every address of that build the port hard-codes.
 *
 * The port hooks and overrides functions of the game at fixed addresses (the frame pacing, the D-pad's reading of the screens, the (Y/N) questions, the picture decompressor ...)
 * and writes the screen's size into two of its globals. Those addresses are those of one build of the game; in another build they name something else (in Spells of the Ancients
 * 2.x, the two globals are inside code: docs/notes/sota-comparison.md). So they are not in the sources of the hooks but in one table, here and in profile.c, one row per file of a
 * build, found by the BUILD ID: the SHA-256 of the file (tools/lift/builds.py). The lifter writes the id of the file it lifted into the module (LiftGame.build_id, LiftModule.build_id);
 * the runtime computes the id of the file it loads, refuses to run lifted code on a different one, and looks the id up in the table.
 *
 * An id that is in no row is an UNKNOWN BUILD: the runtime stops with exit status 3 and says so, or, with PORT_UNKNOWN_BUILD=1, goes on with PROFILE_NONE as the active profile, which
 * has no address in it: no hook, no override and no write is made (and the game usually cannot run, as the picture decompressor is one of the overrides). The code that installs a hook
 * reads `profile->...` and does nothing when its field is 0.
 *
 * Adding a build: CONTRIBUTING.md, "Adding a build".
 */
#ifndef PORT_PROFILE_H
#define PORT_PROFILE_H

#include <stddef.h>
#include <stdint.h>

#include "lift_tables.h"

typedef struct ProfRange { uint32_t lo, hi; } ProfRange;        /* the addresses lo <= a < hi: the code of one function or loop; {0, 0} holds none */

/* One copy of the picture decompressor (the MPS_CODE section, lzw.c). A program or library has one; header is 0 when this file has none. */
typedef struct ProfLzw {
    uint32_t header;        /* the entry that reads the picture file's records (and starts the decoder) */
    uint32_t read, read2;   /* the two entries of the decoder to a destination */
    uint32_t block;         /* the dictionary, the first byte of the state block (LZW_* below are offsets in it) */
    uint32_t in_ptr;        /* the input pointer */
    uint32_t in_end;        /* its end */
    uint32_t refill;        /* the refill callback (a function pointer, read from here) */
    uint32_t callback;      /* the function the header reader calls with the dictionary block */
} ProfLzw;

/* The state block of the decompressor, as offsets from its dictionary (`block`): the same in the three copies of the code the port knows (MAGIC.EXE, DUEL.EXE, DECKDLL.DLL). */
#define LZW_DICT 0x0u
#define LZW_SIZE_LO 0x4000u
#define LZW_SIZE_HI 0x4004u
#define LZW_PARAM 0x4008u
#define LZW_STACK_PTR 0x400cu
#define LZW_COUNT 0x4010u
#define LZW_REPEAT 0x4014u
#define LZW_BYTE 0x4015u
#define LZW_WIDTH 0x4016u
#define LZW_WIDTH_MAX 0x4017u
#define LZW_MASK 0x4018u
#define LZW_NEXT 0x401cu
#define LZW_BITS 0x4020u
#define LZW_BITFILL 0x4024u
#define LZW_NIBBLE 0x4025u
#define LZW_PREV 0x4026u
#define LZW_FIRST 0x402au
#define LZW_STACK_BASE 0x442bu

/* The overworld's frame rate (pace.c) */
typedef struct ProfPace {
    uint32_t tick_fn;       /* the function that returns and clears the 33 ms tick counter (overridden) */
    uint32_t ticks;         /* the tick counter */
    uint32_t frame_ret;     /* where the overworld loop's call of tick_fn returns to: the frame is paced there */
    ProfRange map_loop;     /* the overworld loop: the code that is the map, not a screen with buttons */
} ProfPace;

/* The button table of the game's screens, and the mouse (pace.c, screens.c) */
typedef struct ProfButtons {
    uint32_t pass;          /* the table's pass, called once a pass of every screen's loop (pre-call hook) */
    uint32_t mouse_var;     /* the game's mouse button state: 1 left, 2 right, 0 up */
    uint32_t snapshot;      /* the mouse snapshot every loop takes (pre-call hook) */
    uint32_t ctx_cur;       /* the current context */
    uint32_t ctx_count;     /* a dword per context: how many records */
    uint32_t ctx_ptrs;      /* the record pointers, 200 bytes per context */
    int32_t rec_x, rec_y, rec_w, rec_h, rec_handler, rec_type;      /* offsets in a record of the table */
} ProfButtons;

/* The text menu ("Will you...\n Duel a Sorceress.\n Pay 40 gold.") (screens.c) */
typedef struct ProfTextMenu {
    ProfRange loop;
    uint32_t left, top, right, line_h, first, count, mask;          /* globals */
} ProfTextMenu;

/* "Cards for Sale" (screens.c): the loop reads its boxes and their number from its locals (offsets from ebp) */
typedef struct ProfBuyCards {
    ProfRange loop;
    uint32_t ids;           /* the ids of the cards for sale (a global array) */
    int32_t count_ebp;      /* the number of cards: the local at ebp + count_ebp */
    int32_t boxes_ebp;      /* the first box: 16 bytes each */
} ProfBuyCards;

/* "Dungeon & Castle Clues" (screens.c) */
typedef struct ProfClues {
    ProfRange loop;
    int32_t count_ebp;      /* how many rows have a dungeon: the local at ebp + count_ebp */
} ProfClues;

/* The title menu (screens.c, main.c): its loop, the one screen where Escape leaves the game with no question */
typedef struct ProfTitle {
    ProfRange loop;
} ProfTitle;

/* The game's key queue, its (Y/N) questions and its text box (yesno.c, textfocus.c) */
#define PROFILE_MAX_SITES 4
typedef struct ProfKeys {
    uint32_t wait;          /* "wait for a key" (pre-call hook) */
    uint32_t pop;           /* pop a key from the game's key queue (pre-call hook) */
    uint32_t wait_loop_ret; /* where the poll inside the wait loop returns to */
    uint32_t sites[PROFILE_MAX_SITES]; int nsites;      /* the places a (Y/N) question calls `wait` from: the address the call returns to */
    ProfRange name_loop;    /* the new game's name box loop */
} ProfKeys;

/* The screen's size as the game's layouts read it (main.c): the program is told the size by writing it here */
typedef struct ProfDisplay { uint32_t width, height; } ProfDisplay;

/* The programs a program of the build may start (spawn.c: _spawnl, WinExec, CreateProcessA): the file name it asks for (lower case, no folder) and the game module (file name
 * without its extension, beside the running module) that runs that program. A program not in the list is not started: the call fails, as it did before the runtime had a process model. */
#define PROFILE_MAX_PROGRAMS 4
typedef struct ProfProgram { const char *file; const char *module; } ProfProgram;

/* One file of one build. */
typedef struct BuildProfile {
    const char *id;         /* the build id: SHA-256 of the file, 64 lower-case hex characters */
    const char *build;      /* "v1.0" */
    const char *file;       /* "MAGIC.EXE" */
    const char *program;    /* the program this file is: "MAGIC", "DUEL", "DECK" (LIFT_PROGRAM); "" for a library */
    uint32_t base;          /* a library: the address it is lifted for and mapped at; 0 for a program */
    int hooks_verified;     /* 1: the hook addresses below (pace, buttons, textmenu, buycards, clues, title, keys, display) were checked against the running game. 0: this build's hooks were
                             * never ported, so the row holds none of them and every hook stays off (a test keeps the two together). `lzw` is not a hook: the game cannot show a picture without it. */
    ProfProgram programs[PROFILE_MAX_PROGRAMS];     /* what this program may start; {NULL, NULL} ends the list */
    ProfLzw lzw;
    ProfPace pace;
    ProfButtons buttons;
    ProfTextMenu textmenu;
    ProfBuyCards buycards;
    ProfClues clues;
    ProfTitle title;
    ProfKeys keys;
    ProfDisplay display;
} BuildProfile;

/* The table (profile.c) */
size_t profile_count(void);
const BuildProfile *profile_table(void);                                            /* the rows, profile_count() of them */
const BuildProfile *profile_at(size_t i);
const BuildProfile *profile_find(const char *id);                                   /* by build id; NULL if no row has it */
const BuildProfile *profile_find_in(const BuildProfile *table, size_t n, const char *id);     /* the same in another table (the tests) */
void profile_name(const BuildProfile *p, char *out, size_t cap);                  /* "v1.0 MAGIC.EXE" */

/* The active profile: what every hook installer reads. Never NULL. PROFILE_NONE until profile_init, and after it for an unknown build run with PORT_UNKNOWN_BUILD=1. */
extern const BuildProfile PROFILE_NONE;
extern const BuildProfile *profile;
extern int profile_guest_writes;        /* how many words profile-keyed code has written into the guest's memory (the tests count; an unknown build must leave it at 0) */

/* SHA-256 */
void profile_sha256(const void *data, size_t n, char hex[65]);
int profile_file_id(const char *path, char hex[65]);        /* 0 if the file cannot be read */

/* The verdict on a module and the file it is to run: */
typedef enum {
    PROFILE_OK,             /* the module was lifted from this very file, and the table has a row for it */
    PROFILE_NO_MODULE_ID,   /* the module carries no build id (made by an older lifter) */
    PROFILE_NO_FILE,        /* the file could not be read */
    PROFILE_FILE_MISMATCH,  /* the module was lifted from another file than the one loaded */
    PROFILE_UNKNOWN         /* the table has no row for the build (or the row is for another kind of file) */
} ProfileVerdict;
/* `program` is the module's LIFT_PROGRAM, NULL for a library. file_id may be NULL (unreadable). *out is the row on PROFILE_OK, else NULL. */
ProfileVerdict profile_classify(const BuildProfile *table, size_t n, const char *program, const char *module_id, const char *file_id, const BuildProfile **out);
/* The text the runtime prints for a verdict other than OK (one line, no newline). `file` is the file's name, `file_id` and `module_id` as given to profile_classify. */
void profile_message(char *out, size_t cap, ProfileVerdict v, const char *file, const char *program, const char *file_id, const char *module_id);

/* At start: the loaded program `exe_path` against the game module (lift_game): sets `profile`. An unsupported build ends the process with exit status 3 and a message, unless
 * PORT_UNKNOWN_BUILD=1 is set, which prints a warning and leaves PROFILE_NONE. A file that cannot be read leaves PROFILE_NONE with no message (the loader says it cannot open it). */
void profile_init(const char *exe_path);
/* A library the program loads (modules.c, before it is mapped): the same check against the module's record, `host_path` being the library's file. Returns the library's row,
 * PROFILE_NONE for an unknown one under PORT_UNKNOWN_BUILD=1 or when the program's own profile is PROFILE_NONE; ends the process (status 3) as profile_init does. */
const BuildProfile *profile_check_library(const LiftModule *m, const char *host_path);
/* The screen size written into the game's own globals (800x600 and 1024x768 follow from them), if the profile says where; the number of words written. */
int profile_write_screen_size(int w, int h);
/* PORT_UNKNOWN_BUILD=1 */
int profile_allow_unknown(void);

#endif

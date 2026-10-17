/*
 * port.h - the standalone program: the lifted game (tools/lift, the whole of MAGIC.EXE) over a C Win32 layer, no emulator.
 *
 * The guest's 4 GB address space is reserved at G (lift_rt.h, LIFT_BACKEND_FLAT4G), so the lifted code, which works on the guest's own
 * addresses, runs unchanged and a Win32 function reads its arguments and the structures they point to from the same memory.
 */
#ifndef PORT_H
#define PORT_H

#include <stddef.h>
#include <stdint.h>

#include <stdlib.h>
#include <string.h>

#include "lift_rt.h"
#include "lift_tables.h"

/* A switch set in the environment: set, not empty and not "0" (PORT_HEADLESS=0 means off, like PORT_HEADLESS unset). */
static inline int port_env_on(const char *name)
{
    const char *v = getenv(name);

    return v && *v && strcmp(v, "0") != 0;
}

extern uint8_t *G;

/* A Win32 or C runtime function implemented in C: `a` holds its stack arguments (as many as its signature says). */
typedef uint32_t (*WinApiFn)(const uint32_t *a);

typedef struct WinApi {
    const char *dll;   /* lower case, as the PE names it: "kernel32.dll" */
    const char *name;
    WinApiFn fn;
} WinApi;

/* Every implemented function of a module, ending with {0}. */
extern const WinApi KERNEL32_APIS[], KERNEL32_RT_APIS[], CRT_APIS[], STDIO_APIS[], VIDEO_APIS[];

/* The imports of the loaded program: where the loader put each one, and what the function behind it is. */
typedef struct Import {
    const char *dll, *name;
    uint32_t slot;       /* the import address table entry */
    uint32_t stub;       /* the address the entry holds: a call through a register lands here */
    int nargs;
    uint32_t cleanup;    /* bytes the callee pops (stdcall) */
    WinApiFn fn;         /* NULL: not implemented yet */
    uint32_t forward;    /* not 0: the import is an export of a lifted library, at this address */
    uint64_t calls;
} Import;

typedef struct Image {
    uint32_t base, entry, size;
    const char *path;
} Image;

void port_fatal(const char *fmt, ...) __attribute__((noreturn, format(printf, 1, 2)));
void port_trace(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
void port_log(const char *fmt, ...) __attribute__((format(printf, 1, 2)));

/* guest memory */
void guest_init(void);
void guest_write(uint32_t addr, const void *src, uint32_t len);
void guest_zero(uint32_t addr, uint32_t len);
uint32_t guest_cstr_len(uint32_t addr);

/* the loader */
int pe_load(const char *path, Image *img);
int pe_load_module(const char *path, uint32_t base, Image *img);   /* a DLL at the base its lifted code was made for */
uint32_t pe_export(uint32_t hmod, const char *name);
Import *import_by_slot_or_stub(uint32_t addr);
void imports_report(void);

/* the guest's heap (HeapAlloc, malloc: one allocator over a reserved region) */
uint32_t heap_alloc(uint32_t size);
void heap_free(uint32_t addr);
uint32_t heap_size(uint32_t addr);

extern __thread uint32_t port_sp;

/* the game: the lifted code's tables, from the game module (gamemod.c) */
extern const LiftGame *lift_game;
void gamemod_load(const char *path);          /* path may be NULL: the module linked into the executable (the single-executable build), or $PENTAMOOR_MODULE */
int gamemod_static_pick(const char *spec, const char *const names[], int n);   /* which of the linked-in programs ("magic", "deck", "duel") a module or program name means: -1 if none (iOS, gamemod.c) */
LiftThreadState lift_thread_initial(void);

/* the screen's size: 640x480 as the retail game has it, or what PORT_RES asks for (screen_set); the buffers that hold a frame are sized for the largest */
extern int screen_w, screen_h;
#define SCREEN_W screen_w
#define SCREEN_H screen_h
#define SCREEN_MAX_W 1600
#define SCREEN_MAX_H 1200
void screen_set(int w, int h);
extern int port_trace_calls;
extern int port_trace_imports;
uint32_t guest_call_on(uint32_t stack_top, uint32_t target, int nargs, const uint32_t *args);
uint32_t guest_call(uint32_t target, int nargs, const uint32_t *args);

/* text and files */
int c_format(char *out, size_t cap, const char *fmt, uint32_t va);
void paths_init(const char *root, const char *overlay);
const char *paths_overlay_default(void);                       /* $PORT_OVERLAY or "port_overlay" */
void paths_normalize(const char *path, char *out, size_t cap);
int port_glob(const char *pattern, const char *name);                                       /* fnmatch(pattern, name, 0): * ? [set] (controls.c) */
void paths_mkdirs(const char *host);                                                  /* mkdir -p of a host path */
int paths_host(const char *guest, int for_write, char *out, size_t cap);        /* for_write: 0 read, 1 write from scratch, 2 write into what is there (copied up from the installed folder) */
void paths_list(const char *guest_dir, void (*fn)(const char *name, int is_dir, void *ctx), void *ctx);
extern char guest_cwd[260];

/* a function the host provides at a guest address: called with the first eight stack words */
typedef uint32_t (*HostGuestFn)(const uint32_t *args);
uint32_t port_host_function(HostGuestFn fn);
void port_override(uint32_t addr, HostGuestFn fn, int nargs, uint32_t cleanup);
void port_prehook(uint32_t addr, HostGuestFn fn);    /* runs before the lifted function at addr, which then runs as usual */
struct BuildProfile;
void lzw_install(void);          /* the program's own copy of the picture decompressor, if the active profile has one (lzw.c) */
void pace_install(void);         /* the overworld's frame rate (pace.c) */
int pace_map_active(void);       /* the overworld's loop has made a frame in the last third of a second (pace.c; the touch screen's mode) */
void textfocus_install(void);    /* when the game waits for typed text (textfocus.c) */
void screens_install(void);      /* which screen of the game is on, for the D-pad (screens.c) */
void yesno_install(void);        /* when the game asks a (Y/N) question (yesno.c) */
void lzw_install_library(const struct BuildProfile *lib, uint32_t base);     /* a library's copy, when it is mapped at `base` (modules.c) */
void port_hooks_reset(void);     /* forget them all (the tests) */
int port_hook_count(void);      /* how many pre-call hooks and overrides are installed (the tests; an unknown build must have none) */
int port_hook_at(int i, uint32_t *addr, int *is_override);      /* the i'th of them, pre-call hooks first, then overrides, in the order they were installed */

/* DLLs (modules.c): the game's libraries, lifted or provided by the host */
typedef struct HostExport { const char *name; int ordinal; HostGuestFn fn; } HostExport;     /* ends with {0} */
void module_register_host(const char *name, const HostExport *exports);
HostGuestFn video_host_fn(const char *name);                       /* video.c: a MAGVID.DLL export by name */
uint32_t module_find(const char *name);       /* the module handle of a library already loaded (0: none) */
uint32_t module_load(const char *name);       /* LoadLibraryA */
const char *module_file(uint32_t hmod);                 /* the file name of a loaded library, or NULL */
void module_attach(void);                                /* run DllMain of the libraries mapped for an import and not yet attached */
uint32_t module_import(const char *dll, const char *name);   /* the address of a lifted library's export, mapping the library; 0 if it is not one */
uint32_t module_proc(uint32_t hmod, const char *name);   /* GetProcAddress: a name, or "#ordinal" */
void sound_install(void);
void sound_mix(int16_t *out, int frames);        /* the audio device pulls from here: stereo, signed 16 bit, sound_rate() Hz */
void sound_set_device(int on);                   /* a device is pulling (else the sounds are consumed against the clock) */
int sound_rate(void);
int sound_stream_start(int16_t *pcm, uint32_t frames, uint32_t rate, int channels);   /* a movie's sound; the mixer owns pcm. -1: no free voice */
void sound_stream_stop(int id);
void video_install(void);

/* running */
void port_run(const Image *img);

#endif

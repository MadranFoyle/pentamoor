/*
 * display.h - how the game's picture is put on a window or a display, as pure functions: no SDL and no game, so they are unit tested (test_display.c).
 *
 *   - scaling modes (fit, integer, stretch) and the texture filters (nearest, linear, sharp): names, parsing, cycling;
 *   - the layout: where the sw x sh picture goes in an output of ow x oh pixels, and the pointer mapping back from window coordinates (points) to picture pixels;
 *   - the window it starts in: the largest whole-number multiple of the picture that fits the display, and the smallest the player may shrink it to;
 *   - display.cfg, the settings kept between runs in the overlay folder (parse, write, merge, the environment variables that override it);
 *   - the one-line message shown for a moment when a setting is cycled, and the controller combination that toggles full screen.
 *
 * Sizes are in pixels (the drawable: what the renderer reports) unless called points (what the window system calls the window's size; on a Retina Mac, or with a display
 * scaling factor of 200%, a point is two pixels, `dpi` below is pixels per point). The layout and the integer-scale decision always use pixels.
 * New code that needs the screen size takes it as a parameter (docs/ROADMAP.md): nothing here knows 1024x768.
 */
#ifndef PORT_DISPLAY_H
#define PORT_DISPLAY_H

#include <stddef.h>
#include <stdint.h>

/* ---- the modes ------------------------------------------------------------------------------------------------------------------------------------- */
typedef enum { SCALE_FIT = 0, SCALE_INTEGER, SCALE_STRETCH, SCALE_COUNT } ScaleMode;
typedef enum { FILTER_NEAREST = 0, FILTER_LINEAR, FILTER_SHARP, FILTER_COUNT } FilterMode;

#define DEFAULT_SCALE SCALE_FIT
#define DEFAULT_FILTER FILTER_SHARP

const char *scale_name(ScaleMode m);                                  /* "fit", "integer", "stretch" */
const char *filter_name(FilterMode f);                                /* "nearest", "linear", "sharp" */
int scale_parse(const char *s, ScaleMode *out);                       /* case-insensitive, surrounding blanks allowed; 1 on success, *out untouched otherwise */
int filter_parse(const char *s, FilterMode *out);
ScaleMode scale_cycle(ScaleMode m);                                   /* fit -> integer -> stretch -> fit */
FilterMode filter_cycle(FilterMode f);                                /* nearest -> linear -> sharp -> nearest */

/* ---- the layout ------------------------------------------------------------------------------------------------------------------------------------ */
typedef struct { int x, y, w, h; } DispRect;
typedef struct {
    DispRect dst;                  /* where the picture goes in the output, pixels */
    double sx, sy;                 /* the scale on each axis (equal except for stretch) */
    int whole;                     /* every picture pixel is a whole number of output pixels (square, no filtering needed) */
} DispView;

/* "fit" for a screen of sw x sh in an output of dw x dh: the 4:3 (or whatever shape) is kept, the largest size that fits. A whole-number scale keeps every pixel square and sharp but
 * leaves bars, so it is taken when it uses at least INT_SCALE_MIN percent of what the best fractional scale would: the Steam Deck (1024x768 in 1280x800: 1.04x fractional, 1x whole)
 * gets the whole one, a 1080p television (1.41x) the fractional one. *integer: 1 for the whole-number scale; *vw, *vh: the size the picture ends up (either may be NULL).
 * Returns the scale. (steamdeck.h's view_scale is this function.) */
#define INT_SCALE_MIN 90
double display_fit(int sw, int sh, int dw, int dh, int *integer, int *vw, int *vh);

/* Lay the sw x sh picture out in an ow x oh output:
 *   SCALE_FIT      display_fit, centred;
 *   SCALE_INTEGER  always the largest whole-number scale, centred, with bars (when even 1x does not fit, the fractional fit: the picture is never cut);
 *   SCALE_STRETCH  the whole output, whatever its shape.
 * An output of no size gives the picture at 1x at the origin. */
void display_layout(int sw, int sh, int ow, int oh, ScaleMode mode, DispView *v);

/* Pointer mapping. A mouse position arrives in window coordinates; the output is ow x oh pixels for a window of ww x wh of those units (points: SDL reports window sizes and, mostly, mouse positions in
 * points. But SDL's renderer, when one is attached to the window, turns the positions of mouse events into render pixels by itself, with or without a logical size (seen with SDL 2.32 on a Retina Mac): the
 * front end measures which it is, and passes the window's size in the unit the events are in, so ww == ow for events in pixels; front_sdl.c, "mouse units"). Returns 1 when the point is inside the
 * picture, else 0 (it is in a bar); *px, *py are the picture pixel either way (they lie outside 0..sw-1 / 0..sh-1 in a bar, as SDL's own logical-size mapping did). The point is
 * taken at the middle of its pixels. display_to_window is the inverse, for a picture pixel's middle (a test and script aid). */
int display_to_screen(const DispView *v, int sw, int sh, int ow, int oh, double ww, double wh, int wx, int wy, int *px, int *py);
void display_to_window(const DispView *v, int sw, int sh, int ow, int oh, double ww, double wh, int px, int py, int *wx, int *wy);

/* The prescale for the "sharp" filter: the picture is first enlarged by a whole number (nearest neighbour, no blur) to at least the size it will be shown at, then the final,
 * smaller step is linear. Returns the factor for one axis: ceil(dst/src), at least 1 and at most `cap`, and small enough that src*k stays within `max_dim` (0: no limit). */
int display_prescale(int src, int dst, int cap, int max_dim);

/* ---- the window ------------------------------------------------------------------------------------------------------------------------------------ */
/* The size the window starts at, in points: the largest whole-number multiple of the picture (in pixels: a Retina window of 1024x768 points holds 2048x1536 pixels, a 2x picture)
 * that fits 90% of the display's usable area, and never larger than the usable area. A display too small for even 1x gets the picture reduced to 90% of it, shape kept (a 1366x768
 * laptop with a taskbar: 874x655). dpi: pixels per point (1 when unknown). usable_w/h <= 0 (unknown) gives the picture's own size in points. */
void display_initial_window(int sw, int sh, int usable_w, int usable_h, double dpi, int *w, int *h);

/* The smallest window the player may shrink to, in points: the picture at 1x pixels (so 512x384 points on a Retina Mac), but never more than the window it started at (a display too
 * small for 1x lets the picture be smaller than itself). */
void display_min_window(int sw, int sh, double dpi, int start_w, int start_h, int *w, int *h);

/* A window of w x h points at (x, y) is worth restoring when at least `need` points of it (both ways) lie within one of the `n` display rectangles; else it is probably on a display
 * that is gone. */
int display_pos_ok(int x, int y, int w, int h, const DispRect *displays, int n, int need);

/* ---- the settings kept between runs ----------------------------------------------------------------------------------------------------------------- */
#define DISPLAY_CFG_NAME "display.cfg"
#define DISPLAY_WIN_MIN 160
#define DISPLAY_WIN_MAX 16384

/* What display.cfg holds. A has_ flag says the file gave that setting (a missing, corrupt or outdated file gives none and the defaults apply). */
typedef struct {
    int has_fullscreen, fullscreen;
    int has_scale;  ScaleMode scale;
    int has_filter; FilterMode filter;
    int has_window; int win_w, win_h;         /* the window's size in points, when it is not full screen */
    int has_pos;    int win_x, win_y;         /* its top-left corner */
} DisplayCfg;

void dcfg_init(DisplayCfg *c);
/* Parse the text of the file: "key=value" lines (blanks and a "#" line are ignored, keys and values in any case, CRLF fine). A bad value, an unknown key and a line that is not
 * "key=value" are skipped, the rest still counts. Returns the number of settings taken. */
int dcfg_parse(const char *text, DisplayCfg *c);
/* The file's text for the settings that are set (a comment on top, then one line each). Returns its length, or -1 if `cap` is too small. */
int dcfg_format(const DisplayCfg *c, char *buf, size_t cap);
/* The file in `dir` (the overlay folder; "" is the current folder): read it (returns how many settings it gave: 0 if there is none or it is unusable, *c is then the defaults), or write it (makes the folder if it is not
 * there; 1 on success, 0 if it could not be written). Nothing is ever written anywhere else. */
int dcfg_load(const char *dir, DisplayCfg *c);
int dcfg_save(const char *dir, const DisplayCfg *c);

/* The settings the run uses: the file's, then the Steam Deck's default (full screen), then the environment over all of it. env_* are the values of PORT_FULLSCREEN, PORT_SCALE,
 * PORT_FILTER, PORT_WINDOW (NULL when unset); a bad value is ignored and says so in `warn` (one line per problem, may be NULL). */
typedef struct {
    int fullscreen;
    ScaleMode scale;
    FilterMode filter;
    int has_window, win_w, win_h; int win_env;       /* the windowed size to use, in points, and whether PORT_WINDOW gave it */
    int has_pos, win_x, win_y;
} DisplaySettings;

void display_resolve(const DisplayCfg *file, const char *env_fullscreen, const char *env_scale, const char *env_filter, const char *env_window, int deck,
                     DisplaySettings *out, char *warn, size_t warncap);

/* The file to write at the end of a run: `file` as it was read, with what the player changed during the run (a setting that is not what the run started with: `start` against
 * `now`) and the window's windowed geometry (win_w/h/x/y of `now`; has_ says it is known). A setting that came from the environment and was not touched stays out of the file. */
void display_cfg_update(DisplayCfg *file, const DisplaySettings *start, const DisplaySettings *now);

/* ---- the keys and the pad ------------------------------------------------------------------------------------------------------------------------- */
typedef enum { DK_OTHER = 0, DK_RETURN, DK_F11 } DispKey;
typedef enum { DA_NONE = 0, DA_FULLSCREEN, DA_SCALE, DA_FILTER } DispAction;
/* What a key press does to the display: Alt+Enter and F11 toggle full screen, Ctrl+F11 cycles the scaling, Shift+F11 the filter. Anything else (a plain Enter, Alt+F11, Ctrl+Shift+F11,
 * Alt+Ctrl+Enter...) is the game's. The press that is acted on is not passed to the game. */
DispAction display_key_action(DispKey key, int alt, int ctrl, int shift);

/* The controller combination that toggles full screen: the two sticks pressed in (L3 and R3), held together for DISPLAY_COMBO_MS. Back+Start would be the obvious choice, but Back is
 * Escape and Start is Enter in the pad map (pad.c): pressing them in turn would cancel and then confirm whatever question the game had on the screen. Returns 1 once per hold. */
#define DISPLAY_COMBO_MS 1000
typedef struct { uint32_t since; int held, fired; } DispCombo;
int display_combo_step(DispCombo *c, int a_down, int b_down, uint32_t now_ms);

/* ---- the message ----------------------------------------------------------------------------------------------------------------------------------- */
#define DISPLAY_NOTICE_MS 1500
/* Show `text` (one line) from now_ms for DISPLAY_NOTICE_MS. Called from the window's thread; the compositor (compose.c) reads it on the guest's. */
void display_notice(const char *text, uint32_t now_ms);
/* The text to show at now_ms, copied into out (cap bytes); returns 1 if there is one. */
int display_notice_get(uint32_t now_ms, char *out, size_t cap);
/* "Scaling: integer, filter: sharp" */
void display_notice_text(ScaleMode s, FilterMode f, char *out, size_t cap);

#endif

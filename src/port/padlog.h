/* padlog.h - PORT_PAD_LOG: a time-stamped log of what the input does, to be sent with a bug report from a machine nobody else has (a Steam Deck in Game mode has no terminal, so the log
 * goes to a file as well as to stderr).
 *
 *   PORT_PAD_LOG=1          stderr, and the file pentamoor-input.log in the folder the program was started in (the game's own folder, started by ./pentamoor), emptied at each start
 *   PORT_PAD_LOG=PATH       stderr, and that file (a value with a slash or ending in .log is a path)
 *   PORT_PAD_LOG=stderr     stderr only (the soak scripts read it there)
 *   unset, 0, no, off       nothing
 *
 * What goes in: the controllers SDL found at start (and the joysticks it found but has no mapping for: a Steam Input "Desktop" layout shows the Deck as a keyboard and a mouse, not as a
 * pad), each controller button, a stick leaving or coming back to rest, the keyboard and mouse events SDL delivers (what a Steam Input layout that makes the pad a mouse and keyboard
 * sends), the window's focus changes, what the pad asked the game to do (clicks, keys, D-pad moves), the answers to the D-pad (a target, or nothing to move to), the mode the D-pad is in
 * (duel, dialog, menu, none ...) each time it changes, the game's own yes/no questions, and for each click and key the window it reached. The cursor's moves are thinned out (one a
 * quarter second). Every line starts with the time of day (UTC, to a millisecond) and "padlog:".
 *
 * Header-only on purpose: every file that logs includes this, and the switch is read once. */
#ifndef PORT_PADLOG_H
#define PORT_PADLOG_H

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <time.h>

/* The switch's value, as a pure decision (padlog_test in test_steamdeck.c): is the log on, and which file does it also go to (NULL: stderr only). */
static inline int padlog_enabled(const char *v)
{
    return v && *v && strcmp(v, "0") && strcasecmp(v, "no") && strcasecmp(v, "off") && strcasecmp(v, "false");
}

static inline const char *padlog_path_for(const char *v)
{
    if (!padlog_enabled(v) || !strcasecmp(v, "stderr") || !strcmp(v, "2"))
        return NULL;
    if (strchr(v, '/') || strchr(v, '\\') || (strlen(v) > 4 && !strcasecmp(v + strlen(v) - 4, ".log")))
        return v;
    return "pentamoor-input.log";
}

static inline int padlog_on(void)
{
    static int on = -1;

    if (on < 0)
        on = padlog_enabled(getenv("PORT_PAD_LOG"));
    return on;
}

/* The file the log is also written to, or NULL (stderr only). */
static inline const char *padlog_file(void) { return padlog_on() ? padlog_path_for(getenv("PORT_PAD_LOG")) : NULL; }

/* At start: the file begins empty. */
static inline void padlog_reset(void)
{
    const char *f = padlog_file();
    FILE *fp = f ? fopen(f, "w") : NULL;

    if (fp)
        fclose(fp);
}

#if defined(__GNUC__)
__attribute__((format(printf, 1, 2)))
#endif
static inline void padlog(const char *fmt, ...)
{
    struct timespec ts;
    char line[640];
    va_list ap;
    long sec;
    int n;
    const char *f;

    if (!padlog_on())
        return;
    clock_gettime(CLOCK_REALTIME, &ts);
    sec = (long)(ts.tv_sec % 86400);
    n = snprintf(line, sizeof(line), "%02ld:%02ld:%02ld.%03ld padlog: ", sec / 3600, sec / 60 % 60, sec % 60, ts.tv_nsec / 1000000L);
    va_start(ap, fmt);
    vsnprintf(line + n, sizeof(line) - (size_t)n - 1, fmt, ap);
    va_end(ap);
    strcat(line, "\n");
    fputs(line, stderr);
    if ((f = padlog_file()) != NULL) {                 /* opened for each line: a crash or a power-off loses nothing, and the events are a few a second */
        FILE *fp = fopen(f, "a");

        if (fp) {
            fputs(line, fp);
            fclose(fp);
        }
    }
}

#endif

/* steamdeck.c - see steamdeck.h. */
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "display.h"
#include "steamdeck.h"

static int ieq(const char *a, const char *b)
{
    for (; *a && *b; a++, b++)
        if (tolower((unsigned char)*a) != tolower((unsigned char)*b))
            return 0;
    return *a == *b;
}

/* does `line` (one line of os-release, without its newline) set `key` to a value that is `want` (ignoring quotes and case), or, when contains is set, one that has it in it? */
static int os_line_is(const char *line, size_t n, const char *key, const char *want, int contains)
{
    size_t kl = strlen(key), i, o = 0;
    char val[128];

    if (n <= kl || strncmp(line, key, kl) != 0 || line[kl] != '=')
        return 0;
    for (i = kl + 1; i < n && o + 1 < sizeof(val); i++)
        if (line[i] != '"' && line[i] != '\'')
            val[o++] = line[i];
    val[o] = 0;
    if (!contains)
        return ieq(val, want);
    for (i = 0; val[i]; i++) {
        size_t j = 0;

        while (want[j] && val[i + j] && tolower((unsigned char)val[i + j]) == tolower((unsigned char)want[j]))
            j++;
        if (!want[j])
            return 1;
    }
    return 0;
}

static int os_release_says_steamos(const char *text)
{
    const char *p = text;

    while (p && *p) {
        const char *nl = strchr(p, '\n');
        size_t n = nl ? (size_t)(nl - p) : strlen(p);

        if (os_line_is(p, n, "ID", "steamos", 0) || os_line_is(p, n, "NAME", "steamos", 1) || os_line_is(p, n, "VARIANT_ID", "steamdeck", 0))
            return 1;
        p = nl ? nl + 1 : NULL;
    }
    return 0;
}

/* "gamescope" as one of the colon-separated names of $XDG_CURRENT_DESKTOP, in any case */
static int desktop_is_gamescope(const char *d)
{
    while (d && *d) {
        size_t n = strcspn(d, ":");
        char name[16];
        size_t i;

        if (n == 9) {
            for (i = 0; i < n; i++)
                name[i] = (char)tolower((unsigned char)d[i]);
            name[n] = 0;
            if (!strcmp(name, "gamescope"))
                return 1;
        }
        d += n + (d[n] == ':');
    }
    return 0;
}

int deck_detect(const char *steamdeck_env, const char *os_release, const char *gamescope_wayland, const char *xdg_desktop)
{
    if (steamdeck_env && !strcmp(steamdeck_env, "1"))
        return 1;
    if (gamescope_wayland && *gamescope_wayland)
        return 1;
    if (desktop_is_gamescope(xdg_desktop))
        return 1;
    return os_release && os_release_says_steamos(os_release);
}

static int read_os_release(char *buf, size_t cap)
{
    static const char *const paths[] = {"/etc/os-release", "/usr/lib/os-release"};
    size_t i;

    for (i = 0; i < sizeof(paths) / sizeof(paths[0]); i++) {
        FILE *f = fopen(paths[i], "r");

        if (f) {
            size_t n = fread(buf, 1, cap - 1, f);

            fclose(f);
            buf[n] = 0;
            return 1;
        }
    }
    buf[0] = 0;
    return 0;
}

int deck_here(void)
{
    static int answer = -1;
    const char *force;
    char os[4096];

    if (answer >= 0)
        return answer;
    force = getenv("PORT_STEAMDECK");
    if (force && *force) {
        answer = strcmp(force, "0") != 0 && !ieq(force, "no") && !ieq(force, "off") && !ieq(force, "false");
        return answer;
    }
    read_os_release(os, sizeof(os));
    answer = deck_detect(getenv("SteamDeck"), os, getenv("GAMESCOPE_WAYLAND_DISPLAY"), getenv("XDG_CURRENT_DESKTOP"));
    return answer;
}

int fullscreen_wanted(const char *env, int deck)
{
    if (!env)
        return deck != 0;
    if (!*env || !strcmp(env, "0") || ieq(env, "no") || ieq(env, "off") || ieq(env, "false"))
        return 0;
    return 1;
}

double view_scale(int sw, int sh, int dw, int dh, int *integer, int *vw, int *vh)
{
    return display_fit(sw, sh, dw, dh, integer, vw, vh);        /* the rule is shared with the "fit" scaling mode of every window (display.c) */
}

int text_wanted_rule(uint32_t now_ms, uint32_t name_ms, int edit_focus)
{
    if (edit_focus)
        return 1;
    return name_ms != 0 && now_ms - name_ms < NAME_HOLD_MS;
}

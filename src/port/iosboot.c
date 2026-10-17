/* iosboot.c - see iosboot.h. Pure: compiled into the tests and into the iOS app. */
#include <ctype.h>
#include <stdio.h>
#include <string.h>

#include "iosboot.h"

/* "magic", "deck" or "duel" from the start of `s` (after blanks), or NULL: a word, with or without .EXE, in any case */
static const char *program_word(const char *s)
{
    static const char *const names[] = {"magic", "deck", "duel"};
    size_t i, k;

    if (!s)
        return NULL;
    while (*s && isspace((unsigned char)*s))
        s++;
    for (i = 0; i < 3; i++) {
        size_t n = strlen(names[i]);

        for (k = 0; k < n && s[k] && tolower((unsigned char)s[k]) == names[i][k]; k++)
            ;
        if (k != n)
            continue;
        s += n;
        if (!*s || isspace((unsigned char)*s))
            return names[i];
        if (s[0] == '.' && tolower((unsigned char)s[1]) == 'e' && tolower((unsigned char)s[2]) == 'x' && tolower((unsigned char)s[3]) == 'e' && (!s[4] || isspace((unsigned char)s[4])))
            return names[i];
    }
    return NULL;
}

const char *ios_program(const char *env, const char *file_text)
{
    const char *p = program_word(env);

    if (!p)
        p = program_word(file_text);
    return p ? p : "magic";
}

void ios_documents(const char *home, char *out, size_t n)
{
    if (home && *home)
        snprintf(out, n, "%s/Documents", home);
    else
        snprintf(out, n, ".");
}

void ios_boot_paths(const char *docs, const char *program, IosBoot *out)
{
    char dir[1100];
    size_t l, i;

    memset(out, 0, sizeof(*out));
    snprintf(dir, sizeof(dir), "%s", docs && *docs ? docs : ".");
    l = strlen(dir);
    while (l > 1 && dir[l - 1] == '/')
        dir[--l] = 0;
    snprintf(out->program, sizeof(out->program), "%s", program_word(program) ? program_word(program) : "magic");
    for (i = 0; out->program[i]; i++)
        out->exe_name[i] = (char)toupper((unsigned char)out->program[i]);
    snprintf(out->exe_name + i, sizeof(out->exe_name) - i, ".EXE");
    snprintf(out->root, sizeof(out->root), "%s/Magic", dir);
    snprintf(out->exe, sizeof(out->exe), "%s/Program/%s", out->root, out->exe_name);
    snprintf(out->overlay, sizeof(out->overlay), "%s/port_overlay", dir);
}

void ios_missing_text(const IosBoot *b, char *out, size_t n)
{
    snprintf(out, n,
             "The game is not in this app yet.\n\n"
             "Pentamoor runs your own copy of Magic: The Gathering (1997). Copy the folder Magic, the one that holds Program/%s, into this app's folder "
             "(Files app: On My iPad > Pentamoor, or Finder: the iPad > Files > Pentamoor), so that it is\n\n"
             "Pentamoor/Magic/Program/%s\n\n"
             "then open the app again. (Looked for %s)",
             b->exe_name, b->exe_name, b->exe);
}

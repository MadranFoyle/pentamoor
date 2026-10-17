/* paths.c - guest (Windows) paths to host paths. The guest sees C:\Magic\...; the host has the installed game folder and a writable overlay
 * for what the game saves, so the installed copy is never touched. Names are matched without regard to case, as the original's file
 * system did (the host's may not be: Linux). Where two names differ only in case (an overlay that has both PROGRAM and Program) every one
 * of them is looked in, the one spelled exactly as asked first; a name that has to be created takes its spelling from the installed
 * folder when that has the name (so the overlay mirrors it whatever case the game happens to use first), else as the game gave it. */
#include <dirent.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/stat.h>
#include <unistd.h>

#include "plat.h"
#include "port.h"

static char game_root[1024], overlay_root[1024];
char guest_cwd[260] = "C:\\Magic";

#define MAX_PARTS 64

/* The overlay folder the run will use: $PORT_OVERLAY, else port_overlay beside the working folder. Known before paths_init (the window half of the front end starts first and keeps
 * display.cfg there). */
const char *paths_overlay_default(void)
{
    const char *e = getenv("PORT_OVERLAY");

    return e && *e ? e : "port_overlay";
}

void paths_init(const char *root, const char *overlay)
{
    snprintf(game_root, sizeof(game_root), "%s", root);
    snprintf(overlay_root, sizeof(overlay_root), "%s", overlay);
}

/* An absolute guest path (backslashes, no dot segments, upper-case drive) from a possibly relative one. */
void paths_normalize(const char *path, char *out, size_t cap)
{
    char tmp[600], *seg, *save, *parts[MAX_PARTS];
    int np = 0, i;
    size_t o = 0;

    snprintf(tmp, sizeof(tmp), "%s", path);
    for (i = 0; tmp[i]; i++)
        if (tmp[i] == '/')
            tmp[i] = '\\';
    if (strlen(tmp) >= 3 && tmp[1] == ':' && tmp[2] != '\\')
        memmove(tmp, tmp + 2, strlen(tmp + 2) + 1);
    {
        char full[700];

        if (strlen(tmp) < 2 || tmp[1] != ':') {
            if (tmp[0] == '\\')
                snprintf(full, sizeof(full), "C:%s", tmp);
            else
                snprintf(full, sizeof(full), "%s\\%s", guest_cwd, tmp);
        } else
            snprintf(full, sizeof(full), "%s", tmp);
        snprintf(tmp, sizeof(tmp), "%s", full);
    }
    for (seg = strtok_r(tmp + 2, "\\", &save); seg; seg = strtok_r(NULL, "\\", &save)) {
        if (!strcmp(seg, "."))
            continue;
        if (!strcmp(seg, "..")) {
            if (np)
                np--;
            continue;
        }
        if (np < MAX_PARTS)
            parts[np++] = seg;
    }
    o += (size_t)snprintf(out, cap, "%c:", tmp[0] >= 'a' && tmp[0] <= 'z' ? tmp[0] - 32 : tmp[0]);
    if (!np && o + 2 < cap)
        o += (size_t)snprintf(out + o, cap - o, "\\");
    for (i = 0; i < np && o + 1 < cap; i++)
        o += (size_t)snprintf(out + o, cap - o, "\\%s", parts[i]);
}

/* The names in directory `dir` that are `name` without regard to case, the one spelled exactly like `name` first, the rest in name order
 * (readdir's order is not stable). Returns how many (at most `max`) went into `out`. */
static int ci_matches(const char *dir, const char *name, char out[][256], int max)
{
    DIR *d = opendir(dir);
    struct dirent *e;
    int n = 0, j, k;

    if (!d)
        return 0;
    while ((e = readdir(d)) && n < max)
        if (!strcasecmp(e->d_name, name) && strlen(e->d_name) < 256)
            strcpy(out[n++], e->d_name);
    closedir(d);
    for (j = 1; j < n; j++)                                  /* name order */
        for (k = j; k > 0 && strcmp(out[k - 1], out[k]) > 0; k--) {
            char t[256];

            strcpy(t, out[k - 1]);
            strcpy(out[k - 1], out[k]);
            strcpy(out[k], t);
        }
    for (j = 1; j < n; j++)                                  /* the exact spelling to the front */
        if (!strcmp(out[j], name)) {
            char t[256];

            strcpy(t, out[j]);
            for (k = j; k > 0; k--)
                strcpy(out[k], out[k - 1]);
            strcpy(out[0], t);
            break;
        }
    return n;
}

typedef struct { int depth; char path[1100]; } Best;

/* Does `parts` exist under `cur`, in any of the spellings? On success the host path goes to `out`. `best` keeps the deepest directory that
 * did exist, for a path that does not. */
static int walk(const char *cur, char **parts, int np, int i, Best *best, char *out, size_t cap)
{
    char names[8][256];
    int n, k;

    if (i == np) {
        snprintf(out, cap, "%s", cur);
        return 1;
    }
    if (i > best->depth) {
        best->depth = i;
        snprintf(best->path, sizeof(best->path), "%s", cur);
    }
    n = ci_matches(cur, parts[i], names, 8);
    for (k = 0; k < n; k++) {
        char next[1100];

        snprintf(next, sizeof(next), "%s/%s", cur, names[k]);
        if (walk(next, parts, np, i + 1, best, out, cap))
            return 1;
    }
    return 0;
}

/* Resolve `parts` under `base`; returns 1 if the whole path exists. If not, `out` is the deepest part that exists, then the rest as given
 * (`canon`, when set, supplies the spelling of names that have to be made). */
static int find_ci(const char *base, char **parts, int np, char **canon, char *out, size_t cap)
{
    Best best;
    int j;
    size_t o;

    best.depth = 0;
    snprintf(best.path, sizeof(best.path), "%s", base);
    if (walk(base, parts, np, 0, &best, out, cap))
        return 1;
    o = (size_t)snprintf(out, cap, "%s", best.path);
    for (j = best.depth; j < np && o < cap; j++)
        o += (size_t)snprintf(out + o, cap - o, "/%s", canon ? canon[j] : parts[j]);
    return 0;
}

/* The spelling of each name of `parts` in the installed folder (where it has the name), else as given: what a new overlay entry is called. */
static void canon_parts(char **parts, int np, char **canon, char store[][256])
{
    char cur[1100], names[8][256];
    int i, known = 1;

    snprintf(cur, sizeof(cur), "%s", game_root);
    for (i = 0; i < np; i++) {
        snprintf(store[i], 256, "%s", parts[i]);
        if (known && ci_matches(cur, parts[i], names, 8) > 0) {
            snprintf(store[i], 256, "%s", names[0]);
            snprintf(cur + strlen(cur), sizeof(cur) - strlen(cur), "/%s", names[0]);
        } else
            known = 0;
        canon[i] = store[i];
    }
}

static void make_dirs(char *path)                /* mkdir -p of every directory above the last component */
{
    char *q;

    for (q = path + 1; *q; q++)
        if (PLAT_IS_SEP(*q)) {
            char sep = *q;

            *q = 0;
            plat_mkdir(path);
            *q = sep;
        }
}

void paths_mkdirs(const char *host)                  /* mkdir -p, the last component too */
{
    char buf[1200];

    snprintf(buf, sizeof(buf), "%s", host);
    make_dirs(buf);
    plat_mkdir(buf);
}

/* The guest path as the names under the game folder (C:\Magic\X is the game folder's X); returns how many. `norm` is the storage. */
static int guest_parts(const char *guest, char *norm, size_t cap, char **parts)
{
    char *seg, *save;
    int np = 0;

    paths_normalize(guest, norm, cap);
    for (seg = strtok_r(norm + 3, "\\", &save); seg && np < MAX_PARTS; seg = strtok_r(NULL, "\\", &save))
        parts[np++] = seg;
    if (np && !strcasecmp(parts[0], "magic")) {
        memmove(parts, parts + 1, (size_t)(np - 1) * sizeof(*parts));
        np--;
    }
    return np;
}

static int copy_file(const char *from, const char *to)
{
    FILE *in = fopen(from, "rb"), *o;
    char buf[8192];
    size_t n;

    if (!in)
        return 0;
    o = fopen(to, "wb");
    if (!o) {
        fclose(in);
        return 0;
    }
    while ((n = fread(buf, 1, sizeof(buf), in)) > 0)
        fwrite(buf, 1, n, o);
    fclose(in);
    return fclose(o) == 0;
}

/* The host path of a guest path; returns whether it exists.
 *   for_write 0: for reading: the overlay's file if there is one, else the installed one.
 *   for_write 1: for writing a file from scratch: the overlay's path, its folders made.
 *   for_write 2: for writing into a file that may be there already (update, append): as 1, and an installed file is copied up first. */
int paths_host(const char *guest, int for_write, char *out, size_t cap)
{
    char norm[700], *parts[MAX_PARTS], *canon[MAX_PARTS], store[MAX_PARTS][256];
    int np = guest_parts(guest, norm, sizeof(norm), parts);

    if (for_write) {
        int ok;

        canon_parts(parts, np, canon, store);
        ok = find_ci(overlay_root, parts, np, canon, out, cap);
        make_dirs(out);
        if (!ok && for_write == 2) {
            char src[1100];

            if (find_ci(game_root, parts, np, NULL, src, sizeof(src)) && copy_file(src, out)) {
                port_trace("paths: %s copied up to %s", guest, out);
                ok = 1;
            }
        }
        port_trace("paths: %s -> %s (write%s, %s)", guest, out, for_write == 2 ? " in place" : "", ok ? "exists" : "new");
        return ok;
    }
    if (find_ci(overlay_root, parts, np, NULL, out, cap))
        return 1;
    {
        int ok = find_ci(game_root, parts, np, NULL, out, cap);

        port_trace("paths: %s -> %s (%s)", guest, out, ok ? "found" : "missing");
        return ok;
    }
}

/* The names in a guest folder, installed and overlay together (the overlay's entry wins where both have a name, compared without regard
 * to case): `fn` is called once for each, with the name as the host spells it and whether it is a folder. */
void paths_list(const char *guest_dir, void (*fn)(const char *name, int is_dir, void *ctx), void *ctx)
{
    char norm[700], *parts[MAX_PARTS];
    int np = guest_parts(guest_dir, norm, sizeof(norm), parts), pass;
    char **seen = NULL;
    int nseen = 0, capseen = 0;

    for (pass = 0; pass < 2; pass++) {                    /* overlay, then installed */
        /* every spelling of the folder that exists */
        char dirs[8][1100];
        int ndirs = 0, d;
        char (*stack)[1100] = malloc(8 * sizeof(*stack));
        int nstack = 1, s;

        snprintf(stack[0], 1100, "%s", pass ? game_root : overlay_root);
        for (s = 0; s < np; s++) {
            char (*next)[1100] = malloc(8 * sizeof(*next));
            int nn = 0, k;

            for (k = 0; k < nstack; k++) {
                char names[8][256];
                int n = ci_matches(stack[k], parts[s], names, 8), m;

                for (m = 0; m < n && nn < 8; m++)
                    snprintf(next[nn++], 1100, "%s/%s", stack[k], names[m]);
            }
            free(stack);
            stack = next;
            nstack = nn;
        }
        for (d = 0; d < nstack && ndirs < 8; d++)
            snprintf(dirs[ndirs++], 1100, "%s", stack[d]);
        free(stack);
        for (d = 0; d < ndirs; d++) {
            DIR *dir = opendir(dirs[d]);
            struct dirent *e;

            while (dir && (e = readdir(dir))) {
                char full[1400];
                struct stat st;
                int i, dup = 0;

                if (!strcmp(e->d_name, ".") || !strcmp(e->d_name, ".."))
                    continue;
                for (i = 0; i < nseen; i++)
                    if (!strcasecmp(seen[i], e->d_name)) {
                        dup = 1;
                        break;
                    }
                if (dup)
                    continue;
                snprintf(full, sizeof(full), "%s/%s", dirs[d], e->d_name);
                if (stat(full, &st) != 0)
                    continue;
                if (nseen == capseen) {
                    capseen = capseen ? capseen * 2 : 64;
                    seen = realloc(seen, (size_t)capseen * sizeof(*seen));
                }
                seen[nseen++] = strdup(e->d_name);
                fn(e->d_name, S_ISDIR(st.st_mode), ctx);
            }
            if (dir)
                closedir(dir);
        }
    }
    while (nseen > 0)
        free(seen[--nseen]);
    free(seen);
}

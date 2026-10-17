/* display_cfg.c - display.cfg on disk (the parsing and the text are in display.c). The file lives in the overlay folder, beside the saves, and nowhere else. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "display.h"
#include "plat.h"

static void cfg_path(const char *dir, char *out, size_t cap)
{
    if (!dir || !*dir)
        snprintf(out, cap, "%s", DISPLAY_CFG_NAME);
    else if (PLAT_IS_SEP(dir[strlen(dir) - 1]))
        snprintf(out, cap, "%s%s", dir, DISPLAY_CFG_NAME);
    else
        snprintf(out, cap, "%s/%s", dir, DISPLAY_CFG_NAME);
}

int dcfg_load(const char *dir, DisplayCfg *c)
{
    char path[1200], text[4096];
    FILE *f;
    size_t n;

    dcfg_init(c);
    cfg_path(dir, path, sizeof(path));
    f = fopen(path, "rb");
    if (!f)
        return 0;
    n = fread(text, 1, sizeof(text) - 1, f);                  /* a file of that size is not ours; what fits is read */
    fclose(f);
    text[n] = 0;
    if (memchr(text, 0, n))                                   /* binary junk */
        return 0;
    return dcfg_parse(text, c);
}

/* make `dir` and the folders above it that are missing (the overlay may not be there yet on a first run) */
static void make_dirs(const char *dir)
{
    char tmp[1100];
    size_t i, n = strlen(dir);

    if (!n || n >= sizeof(tmp))
        return;
    memcpy(tmp, dir, n + 1);
    for (i = 1; i < n; i++)
        if (PLAT_IS_SEP(tmp[i]) && !PLAT_IS_SEP(tmp[i - 1]) && tmp[i - 1] != ':') {
            char c = tmp[i];

            tmp[i] = 0;
            plat_mkdir(tmp);
            tmp[i] = c;
        }
    plat_mkdir(tmp);
}

int dcfg_save(const char *dir, const DisplayCfg *c)
{
    char path[1200], tmp[1210], text[1024];
    int n = dcfg_format(c, text, sizeof(text));
    FILE *f;

    if (n < 0)
        return 0;
    if (dir && *dir)
        make_dirs(dir);
    cfg_path(dir, path, sizeof(path));
    snprintf(tmp, sizeof(tmp), "%s.tmp", path);
    f = fopen(tmp, "wb");
    if (!f)
        return 0;
    if (fwrite(text, 1, (size_t)n, f) != (size_t)n) {
        fclose(f);
        remove(tmp);
        return 0;
    }
    if (fclose(f) != 0) {
        remove(tmp);
        return 0;
    }
#ifdef _WIN32
    remove(path);                                             /* rename does not replace there */
#endif
    if (rename(tmp, path) != 0) {
        remove(tmp);
        return 0;
    }
    return 1;
}

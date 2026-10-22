/* regstore.c - see regstore.h. Pure: no guest memory, no SDL, so it is tested on its own (test_regstore.c). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "regstore.h"

typedef struct { char key[300]; char name[100]; uint32_t type, len; uint8_t data[REGSTORE_MAX_DATA]; } Entry;

static Entry *entries;
static int nentries;
static char store_path[1100];
static int enabled;

static int ci_prefix(const char *s, const char *prefix)
{
    size_t n = strlen(prefix);

    return !strncasecmp(s, prefix, n) && (s[n] == 0 || s[n] == '\\');
}

int regstore_keeps(const char *key, const char *name)
{
    if (!key)
        return 0;
    if (ci_prefix(key, REGSTORE_MICROPROSE_KEY) || ci_prefix(key, REGSTORE_USER_KEY))
        return 1;
    if (!strcasecmp(key, REGSTORE_WINDOWS_KEY))
        return !name || !strcasecmp(name, "FirstInstallDateTime") || !strcasecmp(name, "ProductId");
    return 0;
}

static int clean_text(const char *s, size_t cap)
{
    size_t n = strlen(s);

    if (!n || n >= cap)
        return 0;
    for (; *s; s++)
        if (*s == '\t' || *s == '\n' || *s == '\r')
            return 0;
    return 1;
}

static Entry *find(const char *key, const char *name)
{
    int i;

    for (i = 0; i < nentries; i++)
        if (!strcasecmp(entries[i].key, key) && !strcasecmp(entries[i].name, name))
            return &entries[i];
    return NULL;
}

static int hexval(int c)
{
    return c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
}

/* one line of the file: 1 when it holds a value the store keeps (and it is now in the table), else 0 */
static int parse_line(char *line)
{
    char *key = line, *name, *type, *hex, *end;
    unsigned long t;
    size_t n, i;
    Entry *old;
    static Entry e;

    name = strchr(key, '\t');
    if (!name)
        return 0;
    *name++ = 0;
    type = strchr(name, '\t');
    if (!type)
        return 0;
    *type++ = 0;
    hex = strchr(type, '\t');
    if (!hex)
        return 0;
    *hex++ = 0;
    t = strtoul(type, &end, 10);
    if (*end || end == type || !clean_text(key, sizeof(e.key)) || !clean_text(name, sizeof(e.name)) || !regstore_keeps(key, name))
        return 0;
    n = strlen(hex);
    if (n % 2 || n / 2 > REGSTORE_MAX_DATA)
        return 0;
    memset(&e, 0, sizeof(e));
    for (i = 0; i < n / 2; i++) {
        int hi = hexval(hex[2 * i]), lo = hexval(hex[2 * i + 1]);

        if (hi < 0 || lo < 0)
            return 0;
        e.data[i] = (uint8_t)(hi << 4 | lo);
    }
    snprintf(e.key, sizeof(e.key), "%s", key);
    snprintf(e.name, sizeof(e.name), "%s", name);
    e.type = (uint32_t)t;
    e.len = (uint32_t)(n / 2);
    old = find(key, name);
    if (old) {
        *old = e;                       /* a later line replaces an earlier one */
        return 1;
    }
    if (nentries >= REGSTORE_MAX_VALUES)
        return 0;
    entries = realloc(entries, (size_t)(nentries + 1) * sizeof(*entries));
    entries[nentries++] = e;
    return 1;
}

int regstore_open(const char *path)
{
    FILE *f;
    char line[2 * REGSTORE_MAX_DATA + 600];
    int n = 0;

    free(entries);
    entries = NULL;
    nentries = 0;
    enabled = 0;
    store_path[0] = 0;
    if (!path || !*path)
        return 0;
    snprintf(store_path, sizeof(store_path), "%s", path);
    enabled = 1;
    f = fopen(path, "rb");
    if (!f)
        return 0;
    while (fgets(line, sizeof(line), f)) {
        size_t len = strlen(line);

        if (len && line[len - 1] != '\n' && !feof(f)) {         /* a line longer than any value can make: skip the rest of it */
            int c;

            while ((c = fgetc(f)) != EOF && c != '\n')
                ;
            continue;
        }
        while (len && (line[len - 1] == '\n' || line[len - 1] == '\r'))
            line[--len] = 0;
        if (!len || line[0] == '#')
            continue;
        n += parse_line(line);
    }
    fclose(f);
    return n;
}

int regstore_enabled(void) { return enabled; }
const char *regstore_path(void) { return store_path; }

int regstore_key_exists(const char *key)
{
    size_t n = strlen(key);
    int i;

    if (!enabled)
        return 0;
    for (i = 0; i < nentries; i++)
        if (!strncasecmp(entries[i].key, key, n) && (entries[i].key[n] == 0 || entries[i].key[n] == '\\'))
            return 1;
    return 0;
}

int regstore_get(const char *key, const char *name, uint32_t *type, const uint8_t **data, uint32_t *len)
{
    Entry *e = enabled && key && name ? find(key, name) : NULL;

    if (!e)
        return 0;
    *type = e->type;
    *data = e->data;
    *len = e->len;
    return 1;
}

static int save(void)
{
    char tmp[1110];
    FILE *f;
    int i;
    size_t k;

    snprintf(tmp, sizeof(tmp), "%s.tmp", store_path);
    f = fopen(tmp, "wb");
    if (!f)
        return -1;
    fputs("# pentamoor registry 1\n", f);
    for (i = 0; i < nentries; i++) {
        fprintf(f, "%s\t%s\t%u\t", entries[i].key, entries[i].name, entries[i].type);
        for (k = 0; k < entries[i].len; k++)
            fprintf(f, "%02x", entries[i].data[k]);
        fputc('\n', f);
    }
    if (fclose(f) != 0) {
        remove(tmp);
        return -1;
    }
    remove(store_path);                 /* (Windows' rename does not replace) */
    if (rename(tmp, store_path) != 0) {
        remove(tmp);
        return -1;
    }
    return 0;
}

int regstore_put(const char *key, const char *name, uint32_t type, const uint8_t *data, uint32_t len)
{
    Entry *e, old;
    int added = 0;

    if (!enabled || !key || !name || !regstore_keeps(key, name) || !clean_text(key, sizeof(e->key)) || !clean_text(name, sizeof(e->name)) || len > REGSTORE_MAX_DATA || (len && !data))
        return -1;
    e = find(key, name);
    if (e) {
        old = *e;
    } else {
        if (nentries >= REGSTORE_MAX_VALUES)
            return -1;
        entries = realloc(entries, (size_t)(nentries + 1) * sizeof(*entries));
        e = &entries[nentries++];
        memset(e, 0, sizeof(*e));
        memset(&old, 0, sizeof(old));
        snprintf(e->key, sizeof(e->key), "%s", key);
        snprintf(e->name, sizeof(e->name), "%s", name);
        added = 1;
    }
    e->type = type;
    e->len = len;
    if (len)
        memcpy(e->data, data, len);
    if (save() != 0) {
        if (added)
            nentries--;
        else
            *e = old;
        return -2;
    }
    return 0;
}

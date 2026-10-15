/* stdio.c - the C runtime's files, formatted I/O, the working directory and the clock. Port of the rest of winemu/crt.py.
 * A file opened for reading is read whole (in text mode with its line ends turned into \n and cut at a Ctrl-Z, as the original runtime
 * did); the guest's FILE is an opaque 32-byte block except for two fields the original's macros read: the flag word at +12 (feof tests
 * it) and the descriptor at +16. */
#include <ctype.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "plat.h"
#include "port.h"

#define P(a) ((char *)(G + (a)))
#define IOEOF 0x10

typedef struct File {
    uint32_t ptr;
    char *path;
    int text, writing, fd;
    uint8_t *data;
    size_t size, pos;
    long rawsize;
    FILE *host;
} File;

static File **files;
static int nfiles, capfiles;
static int next_fd = 3;
static int *fds;                       /* descriptors of _open: index fd -> host fd (-1 free) */
static int nfds;

static File *file_of(uint32_t ptr)
{
    int i;

    for (i = 0; i < nfiles; i++)
        if (files[i] && files[i]->ptr == ptr)
            return files[i];
    return NULL;
}

static void set_eof(uint32_t ptr, int on)
{
    uint32_t flag = RD32(ptr + 12);

    WR32(ptr + 12, on ? flag | IOEOF : flag & ~(uint32_t)IOEOF);
}

static uint32_t fopen_(const uint32_t *a)
{
    const char *path = P(a[0]), *mode = P(a[1]);
    int write = strpbrk(mode, "wa+") != NULL, binary = strchr(mode, 'b') != NULL;
    char host[1200];
    int exists = paths_host(path, !write ? 0 : (strchr(mode, 'w') && !strchr(mode, 'r')) ? 1 : 2, host, sizeof(host));
    File *f;
    uint32_t ptr;

    if (!write && !exists) {
        port_trace("fopen(%s, %s) -> not found", path, mode);
        return 0;
    }
    f = calloc(1, sizeof(*f));
    f->path = strdup(host);
    f->text = !binary;
    f->writing = write;
    if (strchr(mode, 'w'))
        f->host = fopen(host, "wb");
    else if (strchr(mode, 'a'))
        f->host = fopen(host, "ab");
    else {
        FILE *in = fopen(host, "rb");
        long len;

        if (!in) {
            free(f);
            return 0;
        }
        fseek(in, 0, SEEK_END);
        len = ftell(in);
        fseek(in, 0, SEEK_SET);
        f->data = malloc((size_t)len + 1);
        f->size = fread(f->data, 1, (size_t)len, in);
        f->rawsize = (long)f->size;
        fclose(in);
        if (f->text) {                                       /* CR LF to LF, and a Ctrl-Z ends the text */
            size_t i, o = 0;

            for (i = 0; i < f->size; i++) {
                if (f->data[i] == '\r' && i + 1 < f->size && f->data[i + 1] == '\n')
                    continue;
                if (f->data[i] == 0x1A)
                    break;
                f->data[o++] = f->data[i];
            }
            f->size = o;
        }
        if (strchr(mode, '+'))
            f->host = fopen(host, "r+b");
    }
    if ((strchr(mode, 'w') || strchr(mode, 'a')) && !f->host) {
        free(f);
        return 0;
    }
    ptr = heap_alloc(32);
    guest_zero(ptr, 32);
    f->ptr = ptr;
    f->fd = next_fd++;
    WR32(ptr + 16, (uint32_t)f->fd);
    if (nfiles == capfiles) {
        capfiles = capfiles ? capfiles * 2 : 32;
        files = realloc(files, (size_t)capfiles * sizeof(*files));
    }
    files[nfiles++] = f;
    port_trace("fopen(%s, %s) -> %s", path, mode, host);
    return ptr;
}

static uint32_t fclose_(const uint32_t *a)
{
    File *f = file_of(a[0]);
    int i;

    if (!f)
        return 0xFFFFFFFFu;
    if (f->host)
        fclose(f->host);
    for (i = 0; i < nfiles; i++)
        if (files[i] == f)
            files[i] = NULL;
    heap_free(a[0]);
    free(f->data);
    free(f->path);
    free(f);
    return 0;
}

static uint32_t write_file(uint32_t ptr, const char *data, size_t n)
{
    File *f = file_of(ptr);

    if (!f || !f->host)
        return (uint32_t)n;
    if (f->text) {
        size_t i;

        for (i = 0; i < n; i++) {
            if (data[i] == '\n')
                fputc('\r', f->host);
            fputc(data[i], f->host);
        }
    } else
        fwrite(data, 1, n, f->host);
    if (f->data)                                    /* a file opened for update: the position moves on over what was written */
        f->pos += n;
    return (uint32_t)n;
}

static uint32_t fwrite_(const uint32_t *a)
{
    write_file(a[3], P(a[0]), (size_t)a[1] * a[2]);
    return a[2];
}

static uint32_t fread_(const uint32_t *a)
{
    File *f = file_of(a[3]);
    size_t want = (size_t)a[1] * a[2], n;

    if (!f || !a[1])
        return 0;
    n = f->size - f->pos < want ? f->size - f->pos : want;
    memcpy(P(a[0]), f->data + f->pos, n);
    f->pos += n;
    if (n < want)
        set_eof(a[3], 1);
    return (uint32_t)(n / a[1]);
}

static uint32_t fgetc_(const uint32_t *a)
{
    File *f = file_of(a[0]);

    if (f && f->pos < f->size)
        return f->data[f->pos++];
    if (f)
        set_eof(a[0], 1);
    return 0xFFFFFFFFu;
}

static uint32_t fgets_(const uint32_t *a)
{
    File *f = file_of(a[2]);
    size_t limit = a[1] ? a[1] - 1 : 0, n = 0;

    if (!f)
        return 0;
    while (n < limit && f->pos < f->size) {
        char c = (char)f->data[f->pos++];

        P(a[0])[n++] = c;
        if (c == '\n')
            break;
    }
    if (n < limit && (n == 0 || P(a[0])[n - 1] != '\n'))
        set_eof(a[2], 1);             /* the read ran into the end of the file */
    if (!n)
        return 0;
    P(a[0])[n] = 0;
    return a[0];
}

static uint32_t fseek_(const uint32_t *a)
{
    File *f = file_of(a[0]);
    long base, off = (int32_t)a[1];

    if (!f)
        return 0xFFFFFFFFu;
    if (f->host && !f->data)                        /* written from scratch (w, a): the host file has the position */
        return fseek(f->host, off, a[2] == 0 ? SEEK_SET : a[2] == 1 ? SEEK_CUR : SEEK_END) ? 0xFFFFFFFFu : 0;
    base = a[2] == 0 ? 0 : a[2] == 1 ? (long)f->pos : (long)f->size;
    if (base + off < 0)
        return 0xFFFFFFFFu;
    f->pos = (size_t)(base + off);
    if (f->host) {                                  /* opened for update: what is written next goes where the position is in the file itself */
        long raw = (long)f->pos;

        if (f->text) {
            size_t i;

            for (i = 0; i < f->pos && i < f->size; i++)
                if (f->data[i] == '\n')
                    raw++;
        }
        fseek(f->host, raw, SEEK_SET);
    }
    set_eof(a[0], 0);
    return 0;
}

static uint32_t ftell_(const uint32_t *a)
{
    File *f = file_of(a[0]);

    if (f && f->host && !f->data)
        return (uint32_t)ftell(f->host);
    return f ? (uint32_t)f->pos : 0xFFFFFFFFu;
}
static uint32_t fileno_(const uint32_t *a) { return file_of(a[0]) ? RD32(a[0] + 16) : 0xFFFFFFFFu; }

static uint32_t filelength_(const uint32_t *a)
{
    struct stat st;
    int i;

    if ((int)a[0] < nfds && fds[a[0]] >= 0) {
        fstat(fds[a[0]], &st);
        return (uint32_t)st.st_size;
    }
    for (i = 0; i < nfiles; i++)
        if (files[i] && files[i]->fd == (int)a[0]) {
            if (files[i]->host)
                fflush(files[i]->host);
            return files[i]->rawsize ? (uint32_t)files[i]->rawsize : (stat(files[i]->path, &st) ? 0 : (uint32_t)st.st_size);
        }
    return 0;
}

/* ---- low-level descriptors ---------------------------------------------------------------------------------------------------- */
static int host_fd(uint32_t fd) { return (int)fd < nfds ? fds[fd] : -1; }

static uint32_t open_(const uint32_t *a)
{
    const char *path = P(a[0]);
    uint32_t flags = a[1];
    int rw = (int)(flags & 3), of, fd;
    char host[1200];
    int exists = paths_host(path, (rw == 0 && !(flags & 0x100)) ? 0 : (flags & 0x200) ? 1 : 2, host, sizeof(host));       /* writing: a truncated file starts from nothing, else it is what is there */

    if (!exists && !(flags & 0x100))
        return 0xFFFFFFFFu;
    of = rw == 0 ? O_RDONLY : rw == 1 ? O_WRONLY : O_RDWR;
    if (flags & 0x100)
        of |= O_CREAT;
    if (flags & 0x200)
        of |= O_TRUNC;
    if (flags & 8)
        of |= O_APPEND;
    fd = open(host, of | O_BINARY, 0666);
    if (fd < 0)
        return 0xFFFFFFFFu;
    {
        int g = next_fd++;

        if (g >= nfds) {
            int old = nfds, i;

            nfds = g + 16;
            fds = realloc(fds, (size_t)nfds * sizeof(*fds));
            for (i = old; i < nfds; i++)
                fds[i] = -1;
        }
        fds[g] = fd;
        return (uint32_t)g;
    }
}

static uint32_t close_(const uint32_t *a)
{
    int h = host_fd(a[0]);

    if (h < 0)
        return 0xFFFFFFFFu;
    close(h);
    fds[a[0]] = -1;
    return 0;
}
static uint32_t read_(const uint32_t *a)
{
    int h = host_fd(a[0]);
    ssize_t n;

    if (h < 0)
        return 0xFFFFFFFFu;
    plat_guest_commit(a[1], a[2]);
    n = read(h, G + a[1], a[2]);
    return n < 0 ? 0xFFFFFFFFu : (uint32_t)n;
}
static uint32_t write_(const uint32_t *a)
{
    int h = host_fd(a[0]);

    plat_guest_commit(a[1], a[2]);
    return h < 0 ? a[2] : (uint32_t)write(h, G + a[1], a[2]);
}
static uint32_t lseek_(const uint32_t *a)
{
    int h = host_fd(a[0]);

    return h < 0 ? 0xFFFFFFFFu : (uint32_t)lseek(h, (int32_t)a[1], (int)a[2]);
}
static uint32_t tell_(const uint32_t *a)
{
    int h = host_fd(a[0]);

    return h < 0 ? 0xFFFFFFFFu : (uint32_t)lseek(h, 0, SEEK_CUR);
}

static uint32_t chdir_(const uint32_t *a)
{
    char n[300];

    paths_normalize(P(a[0]), n, sizeof(n));
    port_trace("_chdir(%s) -> %s", P(a[0]), n);
    snprintf(guest_cwd, sizeof(guest_cwd), "%s", n);
    return 0;
}

static uint32_t getcwd_(const uint32_t *a)
{
    if (a[0]) {
        strcpy(P(a[0]), guest_cwd);
        return a[0];
    }
    {
        uint32_t p = heap_alloc((uint32_t)strlen(guest_cwd) + 1);

        strcpy(P(p), guest_cwd);
        return p;
    }
}

static uint32_t mkdir_(const uint32_t *a)
{
    char host[1200];

    paths_host(P(a[0]), 1, host, sizeof(host));
    plat_mkdir(host);
    return 0;
}

static uint32_t splitpath_(const uint32_t *a)
{
    const char *p = P(a[0]);
    char drive[8] = "", dir[300], name[300], ext[300];
    const char *rest = p, *slash, *dot;
    size_t cut;

    if (p[0] && p[1] == ':') {
        snprintf(drive, sizeof(drive), "%.2s", p);
        rest = p + 2;
    }
    slash = strrchr(rest, '\\');
    if (strrchr(rest, '/') > slash)
        slash = strrchr(rest, '/');
    cut = slash ? (size_t)(slash - rest) + 1 : 0;
    snprintf(dir, sizeof(dir), "%.*s", (int)cut, rest);
    dot = strrchr(rest + cut, '.');
    if (dot) {
        snprintf(name, sizeof(name), "%.*s", (int)(dot - (rest + cut)), rest + cut);
        snprintf(ext, sizeof(ext), "%s", dot);
    } else {
        snprintf(name, sizeof(name), "%s", rest + cut);
        ext[0] = 0;
    }
    if (a[1]) strcpy(P(a[1]), drive);
    if (a[2]) strcpy(P(a[2]), dir);
    if (a[3]) strcpy(P(a[3]), name);
    if (a[4]) strcpy(P(a[4]), ext);
    return 0;
}

/* bsearch calls the guest's comparison function. */
static uint32_t bsearch_(const uint32_t *a)
{
    uint32_t key = a[0], base = a[1], num = a[2], width = a[3], cmp = a[4], lo = 0, hi = num;

    while (lo < hi) {
        uint32_t mid = (lo + hi) / 2, elem = base + mid * width, args[2] = {key, elem};
        int32_t r = (int32_t)guest_call(cmp, 2, args);

        if (r == 0)
            return elem;
        if (r < 0)
            hi = mid;
        else
            lo = mid + 1;
    }
    return 0;
}

/* ---- formatted output and input -------------------------------------------------------------------------------------------------- */
static uint32_t sprintf_(const uint32_t *a)
{
    return (uint32_t)c_format(P(a[0]), 65536, P(a[1]), port_sp + 4 + 8);
}

static uint32_t vsnprintf_(const uint32_t *a)
{
    char *tmp = malloc(65536);
    int len = c_format(tmp, 65536, P(a[2]), a[3]);
    uint32_t n = a[1], r;

    if ((uint32_t)len < n) {
        memcpy(P(a[0]), tmp, (size_t)len + 1);
        r = (uint32_t)len;
    } else {
        memcpy(P(a[0]), tmp, n);
        r = (uint32_t)len == n ? n : 0xFFFFFFFFu;
    }
    free(tmp);
    return r;
}

static uint32_t fprintf_(const uint32_t *a)
{
    char *tmp = malloc(65536);
    int len = c_format(tmp, 65536, P(a[1]), port_sp + 4 + 8);
    uint32_t r = write_file(a[0], tmp, (size_t)len);

    free(tmp);
    return r;
}

static uint32_t ctime_(const uint32_t *a)
{
    static uint32_t buf;
    time_t t = (time_t)RD32(a[0]);
    char s[64];

    if (!buf)
        buf = heap_alloc(32);
    strftime(s, sizeof(s), "%a %b %d %H:%M:%S %Y\n", localtime(&t));
    strcpy(P(buf), s);
    return buf;
}

/* A minimal sscanf: %d %i %u %x %o %s %c %f %lf %[set] and literal matching. `n` is the stack word index of the first pointer. */
static int scan_text(const char *text, size_t len, const char *fmt, uint32_t ptrs, size_t *consumed)
{
    size_t i = 0;
    int items = 0, np = 0;
    const char *f = fmt;

    while (*f) {
        if (*f == '%') {
            int skip = 0, width = 0, lng = 0, shrt = 0;
            char conv;

            f++;
            if (*f == '*') { skip = 1; f++; }
            while (isdigit((unsigned char)*f))
                width = width * 10 + (*f++ - '0');
            while (*f == 'l' || *f == 'h' || *f == 'L') {
                if (*f == 'l')
                    lng = 1;
                if (*f == 'h')
                    shrt = 1;
                f++;
            }
            conv = *f++;
            if (conv == '%') {
                if (i >= len || text[i] != '%')
                    break;
                i++;
                continue;
            }
            if (conv != 'c' && conv != '[')
                while (i < len && isspace((unsigned char)text[i]))
                    i++;
            if (i >= len && conv != 'n') {
                *consumed = i;
                return items ? items : -1;
            }
            if (strchr("diuxXofeg", conv)) {
                char num[128];
                size_t k = 0;
                const char *start = text + i;
                char *end;

                while (k < sizeof(num) - 1 && i + k < len && (!width || (int)k < width) &&
                       (isalnum((unsigned char)start[k]) || start[k] == '+' || start[k] == '-' || start[k] == '.'))
                    k++;
                memcpy(num, start, k);
                num[k] = 0;
                if (strchr("fceg", conv) && conv != 'c') {
                    double v = strtod(num, &end);

                    if (end == num)
                        break;
                    i += (size_t)(end - num);
                    if (!skip) {
                        uint32_t p = RD32(ptrs + 4 * (uint32_t)np++);

                        if (lng)
                            memcpy(G + p, &v, 8);
                        else {
                            float fv = (float)v;

                            memcpy(G + p, &fv, 4);
                        }
                        items++;
                    }
                } else {
                    long v = strtol(num, &end, conv == 'x' || conv == 'X' ? 16 : conv == 'o' ? 8 : 10);

                    if (end == num)
                        break;
                    i += (size_t)(end - num);
                    if (!skip) {
                        uint32_t p = RD32(ptrs + 4 * (uint32_t)np++);

                        if (shrt)
                            WR16(p, (uint16_t)v);
                        else
                            WR32(p, (uint32_t)v);
                        items++;
                    }
                }
            } else if (conv == 's') {
                size_t k = i;

                while (k < len && !isspace((unsigned char)text[k]) && (!width || (int)(k - i) < width))
                    k++;
                if (!skip) {
                    uint32_t p = RD32(ptrs + 4 * (uint32_t)np++);

                    memcpy(G + p, text + i, k - i);
                    G[p + (k - i)] = 0;
                    items++;
                }
                i = k;
            } else if (conv == 'c') {
                size_t cnt = width ? (size_t)width : 1;

                if (!skip) {
                    uint32_t p = RD32(ptrs + 4 * (uint32_t)np++);

                    memcpy(G + p, text + i, cnt);
                    items++;
                }
                i += cnt;
            } else if (conv == '[') {
                const char *set = f;
                int neg = 0;
                size_t k = i;
                char allowed[256] = {0};
                const char *e;

                if (*f == '^') { neg = 1; f++; set = f; }
                if (*f == ']')
                    f++;
                while (*f && *f != ']')
                    f++;
                e = f;
                f++;
                {
                    const char *q = set;

                    while (q < e) {
                        if (q + 2 < e && q[1] == '-') {
                            int c;

                            for (c = (unsigned char)q[0]; c <= (unsigned char)q[2]; c++)
                                allowed[c] = 1;
                            q += 3;
                        } else
                            allowed[(unsigned char)*q++] = 1;
                    }
                }
                while (k < len && (allowed[(unsigned char)text[k]] != 0) != neg && (!width || (int)(k - i) < width))
                    k++;
                if (k == i)
                    break;
                if (!skip) {
                    uint32_t p = RD32(ptrs + 4 * (uint32_t)np++);

                    memcpy(G + p, text + i, k - i);
                    G[p + (k - i)] = 0;
                    items++;
                }
                i = k;
            } else
                break;
        } else if (isspace((unsigned char)*f)) {
            while (i < len && isspace((unsigned char)text[i]))
                i++;
            f++;
        } else {
            if (i >= len || text[i] != *f)
                break;
            i++;
            f++;
        }
    }
    *consumed = i;
    return items;
}

static uint32_t sscanf_(const uint32_t *a)
{
    size_t used;

    return (uint32_t)scan_text(P(a[0]), strlen(P(a[0])), P(a[1]), port_sp + 4 + 8, &used);
}

static uint32_t fscanf_(const uint32_t *a)
{
    File *f = file_of(a[0]);
    const char *fmt = P(a[1]);
    size_t used, start;
    int n;

    if (!f)
        return 0xFFFFFFFFu;
    start = f->pos;
    n = scan_text((const char *)f->data + start, f->size - start, fmt, port_sp + 4 + 8, &used);
    /* The file position moves past what was converted and no further, as the C runtime's does: the game reads a count with "%d" and
     * then calls fgets to take the rest of that line (PROMPTS.TXT, 0x424500). An earlier version moved to the next line, so every
     * prompt came back one line late: the prompt bar's Cancel/Done labels were "Done" and "", and a one-line prompt such as "Select
     * card to discard." was the blank line after it (an empty prompt hides the bar). */
    f->pos = start + used;
    return (uint32_t)n;
}

const WinApi STDIO_APIS[] = {
    {"msvcrtd.dll", "fopen", fopen_}, {"msvcrtd.dll", "fclose", fclose_}, {"msvcrtd.dll", "fwrite", fwrite_}, {"msvcrtd.dll", "fread", fread_},
    {"msvcrtd.dll", "fgetc", fgetc_}, {"msvcrtd.dll", "fgets", fgets_}, {"msvcrtd.dll", "fseek", fseek_}, {"msvcrtd.dll", "ftell", ftell_},
    {"msvcrtd.dll", "_fileno", fileno_}, {"msvcrtd.dll", "_filelength", filelength_}, {"msvcrtd.dll", "_open", open_},
    {"msvcrtd.dll", "_close", close_}, {"msvcrtd.dll", "_read", read_}, {"msvcrtd.dll", "_write", write_}, {"msvcrtd.dll", "_lseek", lseek_},
    {"msvcrtd.dll", "_tell", tell_}, {"msvcrtd.dll", "_chdir", chdir_}, {"msvcrtd.dll", "_getcwd", getcwd_}, {"msvcrtd.dll", "_mkdir", mkdir_},
    {"msvcrtd.dll", "_splitpath", splitpath_}, {"msvcrtd.dll", "bsearch", bsearch_}, {"msvcrtd.dll", "sprintf", sprintf_},
    {"msvcrtd.dll", "_vsnprintf", vsnprintf_}, {"msvcrtd.dll", "fprintf", fprintf_}, {"msvcrtd.dll", "ctime", ctime_},
    {"msvcrtd.dll", "sscanf", sscanf_}, {"msvcrtd.dll", "fscanf", fscanf_},
    {0, 0, 0},
};

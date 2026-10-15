/* cformat.c - printf formatting over the guest's argument words (the C runtime's sprintf and fprintf, user32's wsprintf). */
#include <ctype.h>
#include <stdio.h>
#include <string.h>

#include "port.h"

/* Format `fmt` into out (at most cap bytes, always terminated); the arguments are the guest words from `va` on. Returns the length. */
int c_format(char *out, size_t cap, const char *fmt, uint32_t va)
{
    size_t n = 0;
    const char *p;

#define PUT(c) do { if (n + 1 < cap) out[n] = (char)(c); n++; } while (0)
    for (p = fmt; *p; p++) {
        char spec[32], conv, buf[512];
        int k = 0, len = 0;
        int has_h = 0;

        if (*p != '%') {
            PUT(*p);
            continue;
        }
        spec[k++] = *p++;
        while (*p && strchr("-+ #0", *p) && k < 20)
            spec[k++] = *p++;
        if (*p == '*') {
            k += snprintf(spec + k, sizeof(spec) - (size_t)k, "%d", (int)RD32(va));
            va += 4;
            p++;
        }
        while (isdigit((unsigned char)*p) && k < 24)
            spec[k++] = *p++;
        if (*p == '.') {
            spec[k++] = *p++;
            if (*p == '*') {
                k += snprintf(spec + k, sizeof(spec) - (size_t)k, "%d", (int)RD32(va));
                va += 4;
                p++;
            }
            while (isdigit((unsigned char)*p) && k < 28)
                spec[k++] = *p++;
        }
        while (*p == 'h' || *p == 'l' || *p == 'L') {
            if (*p == 'h')
                has_h = 1;
            p++;
        }
        conv = *p;
        if (!conv)
            break;
        if (conv == '%') {
            PUT('%');
            continue;
        }
        switch (conv) {
        case 'd': case 'i': {
            int32_t v = (int32_t)RD32(va);

            va += 4;
            if (has_h)
                v = (int16_t)v;
            spec[k++] = 'd';
            spec[k] = 0;
            len = snprintf(buf, sizeof(buf), spec, v);
            break;
        }
        case 'o': case 'u': case 'x': case 'X': {
            uint32_t v = RD32(va);

            va += 4;
            if (has_h)
                v &= 0xFFFF;
            spec[k++] = conv;
            spec[k] = 0;
            len = snprintf(buf, sizeof(buf), spec, v);
            break;
        }
        case 'c':
            spec[k++] = 'c';
            spec[k] = 0;
            len = snprintf(buf, sizeof(buf), spec, (int)(RD32(va) & 0xFF));
            va += 4;
            break;
        case 's': {
            uint32_t ptr = RD32(va);
            const char *s = ptr ? (const char *)(G + ptr) : "(null)";

            va += 4;
            spec[k++] = 's';
            spec[k] = 0;
            len = snprintf(buf, sizeof(buf), spec, s);
            break;
        }
        case 'f': case 'e': case 'E': case 'g': case 'G': {
            double d;

            memcpy(&d, G + va, 8);
            va += 8;
            spec[k++] = conv;
            spec[k] = 0;
            len = snprintf(buf, sizeof(buf), spec, d);
            break;
        }
        case 'p':
            len = snprintf(buf, sizeof(buf), "%08X", RD32(va));
            va += 4;
            break;
        case 'n':
            va += 4;
            continue;
        default:
            continue;
        }
        if (len >= (int)sizeof(buf))
            len = (int)sizeof(buf) - 1;
        {
            int i;

            for (i = 0; i < len; i++)
                PUT(buf[i]);
        }
    }
    if (cap)
        out[n < cap ? n : cap - 1] = 0;
    return (int)n;
#undef PUT
}

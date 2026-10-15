/* textin.c - see textin.h. The table is the US layout, with the virtual-key and scan codes front_sdl.c's keymap gives the same keys. */
#include <string.h>

#include "textin.h"

typedef struct { char base, shifted; uint16_t vk, sc; } KeyDef;

/* letters are handled by arithmetic below; this is everything else */
static const KeyDef keys[] = {
    {'1', '!', '1', 0x02}, {'2', '@', '2', 0x03}, {'3', '#', '3', 0x04}, {'4', '$', '4', 0x05}, {'5', '%', '5', 0x06},
    {'6', '^', '6', 0x07}, {'7', '&', '7', 0x08}, {'8', '*', '8', 0x09}, {'9', '(', '9', 0x0A}, {'0', ')', '0', 0x0B},
    {'-', '_', 0xBD, 0x0C}, {'=', '+', 0xBB, 0x0D}, {'[', '{', 0xDB, 0x1A}, {']', '}', 0xDD, 0x1B}, {';', ':', 0xBA, 0x27},
    {'\'', '"', 0xDE, 0x28}, {'`', '~', 0xC0, 0x29}, {'\\', '|', 0xDC, 0x2B}, {',', '<', 0xBC, 0x33}, {'.', '>', 0xBE, 0x34},
    {'/', '?', 0xBF, 0x35}, {' ', ' ', 0x20, 0x39},
};

static const char *const letter_rows[3] = {"qwertyuiop", "asdfghjkl", "zxcvbnm"};
static const int letter_sc[3] = {0x10, 0x1E, 0x2C};

int textin_key_for_char(int ch, TextKey *k)
{
    size_t i;
    int r;

    if (ch >= 'a' && ch <= 'z') {
        for (r = 0; r < 3; r++) {
            const char *p = strchr(letter_rows[r], ch);

            if (p) {
                k->vk = (uint16_t)(ch - 'a' + 'A');
                k->sc = (uint16_t)(letter_sc[r] + (p - letter_rows[r]));
                k->shift = 0;
                return 1;
            }
        }
    }
    if (ch >= 'A' && ch <= 'Z') {
        if (!textin_key_for_char(ch - 'A' + 'a', k))
            return 0;
        k->shift = 1;
        return 1;
    }
    for (i = 0; i < sizeof(keys) / sizeof(keys[0]); i++) {
        if (ch == keys[i].base || (ch == keys[i].shifted && ch != ' ')) {
            k->vk = keys[i].vk;
            k->sc = keys[i].sc;
            k->shift = ch != keys[i].base;
            return 1;
        }
    }
    return 0;
}

int textin_char_for_key(int vk, int shift)
{
    size_t i;

    if (vk >= 'A' && vk <= 'Z')
        return shift ? vk : vk - 'A' + 'a';
    for (i = 0; i < sizeof(keys) / sizeof(keys[0]); i++)
        if (keys[i].vk == vk)
            return shift ? keys[i].shifted : keys[i].base;
    return -1;
}

int textin_attach(const char *utf8)
{
    unsigned char c;

    if (!utf8)
        return -1;
    c = (unsigned char)utf8[0];
    return c >= 32 && c < 127 && !utf8[1] ? c : -1;
}

/* the next code point of a UTF-8 string, advancing *p; bad bytes come out as 0xFFFD */
static unsigned next_cp(const unsigned char **p)
{
    const unsigned char *s = *p;
    unsigned c = *s, n, i;

    if (c < 0x80) {
        *p = s + 1;
        return c;
    }
    n = c >= 0xF0 ? 3 : c >= 0xE0 ? 2 : c >= 0xC0 ? 1 : 0;
    if (!n || c >= 0xF8) {
        *p = s + 1;
        return 0xFFFD;
    }
    c &= 0x3Fu >> n;
    for (i = 1; i <= n; i++) {
        if ((s[i] & 0xC0) != 0x80) {
            *p = s + i;
            return 0xFFFD;
        }
        c = (c << 6) | (s[i] & 0x3Fu);
    }
    *p = s + n + 1;
    return c;
}

static void add(TextOut *o, int type, int vk, int sc, int ch)
{
    TextAct *a = &o->act[o->n++];

    a->type = type;
    a->vk = (uint16_t)vk;
    a->sc = (uint16_t)sc;
    a->ch = ch;
}

void textin_type(const char *utf8, int shift_held, TextOut *out)
{
    const unsigned char *p = (const unsigned char *)utf8;

    while (p && *p && out->n + 4 <= TEXT_MAX_ACTS) {
        unsigned cp = next_cp(&p);
        TextKey k;

        if (cp < 0x80 && textin_key_for_char((int)cp, &k)) {
            int press = k.shift && !shift_held;

            if (press)
                add(out, TX_KEYDOWN, VK_SHIFT_CODE, SC_LSHIFT, -1);
            add(out, TX_KEYDOWN, k.vk, k.sc, (int)cp);
            add(out, TX_KEYUP, k.vk, k.sc, -1);
            if (press)
                add(out, TX_KEYUP, VK_SHIFT_CODE, SC_LSHIFT, -1);
        } else if (cp >= 0xA0 && cp <= 0xFF) {
            add(out, TX_CHAR, 0, 0, (int)cp);
        } else if (cp == '\t' || cp == '\r' || cp == '\n' || cp == 8) {
            int vk = cp == '\t' ? 9 : cp == 8 ? 8 : 13, sc = cp == '\t' ? 0x0F : cp == 8 ? 0x0E : 0x1C;

            add(out, TX_KEYDOWN, vk, sc, vk);
            add(out, TX_KEYUP, vk, sc, -1);
        }
    }
}

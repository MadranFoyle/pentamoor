/* profile.c - build profiles (see profile.h): the table of known builds with every address of the game the port hard-codes, the build id (SHA-256 of a file), and the check that
 * the module and the file agree and that the build is one the table has.
 *
 * ADDING A BUILD is adding rows to PROFILES below (one per file the port runs lifted code from) and the same ids to tools/lift/builds.py; CONTRIBUTING.md, "Adding a build". */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "port.h"
#include "profile.h"

/* ---- the table ------------------------------------------------------------------------------------------------------------------------------------------ */
/* Version 1.0, the retail disc: the build the port was made from. Where a field says 0 (or is left out) this file has nothing of that kind.
 *   MAGIC.EXE   the shell: the overworld, villages, shops, castles, the statistics. It is where all the hooks are.
 *   DUEL.EXE    the duel program (it carries its own copy of the picture decompressor)
 *   DECK.EXE    the deck builder program: no hooks
 *   DECKDLL.DLL the deck builder library, lifted for the base 0x32000000: its copy of the picture decompressor
 *   STATWIN.DLL the statistics window library, lifted for the base 0x30000000: no hooks
 * (MAGSND.DLL and MAGVID.DLL are not here: the port provides those libraries itself, sound.c and video.c, and never loads the files.) */
#define ID_V10_MAGIC "4dc592695b6ee390485f283feb2a248cd3f3f739749c2800ab3b1100ea03845c"
#define ID_V10_DUEL "7c4e618b4a8ab4330c71d2dd30637c522573c133d32c667c97924dc8edc2efed"
#define ID_V10_DECK "193f8abea01d4f2c03b769224b06eece6e263a18f13a5b4e2509ed25a01e3d90"
#define ID_V10_DECKDLL "a21f714bea465077c4fabe4a407ff7503b0ce5f9bb1a277826e74276e35c2c18"
#define ID_V10_STATWIN "95bd14de41e8fff84217cdf627a48392da5e7be9c3d064a68e04ed1455334bd7"

/* Spells of the Ancients 2.15 (the expansion's 2.0 install with the six files of the 2.15 patch over it; docs/notes/sota-comparison.md). Every address of 1.0 is different here, and
 * none of the port's hooks (frame pacing, the controller's reading of the screens, the (Y/N) questions, the name box) has been ported to it: the rows hold their picture decompressor
 * (`lzw`: the game cannot show a picture without it) and, for the game itself, the programs it starts, and nothing else. `.hooks_verified = 0` says so. The `lzw` values are the
 * decompressor's state in each copy of its code (tools/research/sotalzw.py reads them from the files: `block` is 1.0's dictionary block 0x532860 plus the delta it prints). The
 * libraries are lifted at the bases of tools/lift/builds.py (LIBRARY_BASES).
 *   shandalar.exe    the game: overworld, towns, duels, and the deck builder (deckdll.dll) in the same process
 *   FaceMaker.exe    the portrait editor it starts when a colour is chosen
 *   DECK.EXE         the stand-alone deck builder: a stub that starts the deck builder of deckdll.dll
 *   deckdll.dll, cardartlib.dll, drawcardlib.dll, CdTools.dll, STATWIN.DLL   the libraries; deckdll.dll and drawcardlib.dll carry a copy of the picture decompressor
 * (magic.exe, the "Magic Shell", is not a build the port runs. MAGSND.DLL and MAGVID.DLL are provided by the port itself, as in 1.0.) */
#define ID_V215_SHANDALAR "e4e46718c451974756b66e7666ac0bf1cc9ebdbc5897eb04a87b8ea2a02353e7"
#define ID_V215_FACEMAKER "b4f3d19614dcd825da846d097baa3cd9badc0c9852492bc27a8ba62c1741a493"
#define ID_V215_DECK "c7ec116aecdcde9ab976cc97cba81482fc4219278f8042edf667456ede3dd8ef"
#define ID_V215_DECKDLL "ce741d1f5547c143fd8494bbe09c26e918b892a3d9fc3c3761babb3c8268a667"
#define ID_V215_CARDARTLIB "689be4a86ca843e76057172543cfa3516d8ccbc2efb1699e7c7935b6dc3ead11"
#define ID_V215_DRAWCARDLIB "c7747313d59b6fa48ec56b479dce9ed5d90f8a95fc47e93990c4369bbd2fa1f8"
#define ID_V215_CDTOOLS "0d0c2bfa87de02499f1f73f21f34824b1c2572f3e6ae0b5dca7ca343ddf1b77d"
#define ID_V215_STATWIN "c1ca59496afa786f22fcd97b94052b937910a613f9321399b4ef4dd5dec76940"

static const BuildProfile PROFILES[] = {
    {
        .id = ID_V10_MAGIC, .build = "v1.0", .file = "MAGIC.EXE", .program = "MAGIC", .hooks_verified = HK_ALL,
        .lzw = {.header = 0x70d000, .read = 0x70d484, .read2 = 0x70d1fc, .block = 0x532860,
                .in_ptr = 0x706500, .in_end = 0x5327b0, .refill = 0x67f43c, .callback = 0x50e8b0},
        .pace = {.tick_fn = 0x5016f9, .ticks = 0x530da0, .frame_ret = 0x4e7873, .map_loop = {0x4e73a0, 0x4e7936}},
        .buttons = {.pass = 0x41f3ea, .mouse_var = 0x7039c4, .snapshot = 0x44b84b,
                    .ctx_cur = 0x519c24, .ctx_count = 0x67f780, .ctx_ptrs = 0x67f7d0,
                    .rec_x = 0x10, .rec_y = 0x14, .rec_w = 0x18, .rec_h = 0x1c, .rec_handler = 0x24, .rec_type = 0x40},
        .textmenu = {.loop = {0x489748, 0x489c9c},
                     .left = 0x539dec, .top = 0x539df0, .right = 0x676d44, .line_h = 0x527b30, .first = 0x676d50, .count = 0x676d40, .mask = 0x676d58},
        .buycards = {.loop = {0x509517, 0x509fd4}, .ids = 0x61e060, .count_ebp = -0xa8, .boxes_ebp = -0xa0},
        .clues = {.loop = {0x48f523, 0x49094c}, .count_ebp = -0x12d8},
        .title = {.loop = {0x47a2e6, 0x47a94c}},
        .keys = {.wait = 0x48ac2f, .pop = 0x4080b2, .wait_loop_ret = 0x48ac3d,
                 .sites = {0x509e4a, 0x4f156e, 0x45119d}, .nsites = 3, .name_loop = {0x47be64, 0x47c080}},
        .display = {.width = 0x522458, .height = 0x52245c},
    },
    {
        .id = ID_V10_DUEL, .build = "v1.0", .file = "DUEL.EXE", .program = "DUEL",
        .lzw = {.header = 0x6c5000, .read = 0x6c5484, .read2 = 0x6c51fc, .block = 0x4fb154,
                .in_ptr = 0x69453c, .in_end = 0x4f7918, .refill = 0x694740, .callback = 0x43d858},
    },
    {
        .id = ID_V10_DECK, .build = "v1.0", .file = "DECK.EXE", .program = "DECK",
    },
    {
        .id = ID_V10_DECKDLL, .build = "v1.0", .file = "DECKDLL.DLL", .program = "", .base = 0x32000000,
        .lzw = {.header = 0x32218000, .read = 0x32218484, .read2 = 0x322181fc, .block = 0x32046810,
                .in_ptr = 0x3213eefc, .in_end = 0x3204baec, .refill = 0x3213f170, .callback = 0x3200141f},
    },
    {
        .id = ID_V10_STATWIN, .build = "v1.0", .file = "STATWIN.DLL", .program = "", .base = 0x30000000,
    },
    {
        .id = ID_V215_SHANDALAR, .build = "v2.15", .file = "shandalar.exe", .program = "SHANDALAR", .hooks_verified = HK_DISPLAY | HK_PACE | HK_KEYS,
        .pace = {.tick_fn = 0x48a3a5, .ticks = 0x566f3c, .frame_ret = 0x438f85, .map_loop = {0x438a70, 0x439059}, .idle_fn = 0x4eab14, .idle_ms = 16},
        .buttons = {.pass = 0x4ba087, .mouse_var = 0x9199b0},
        .keys = {.wait = 0x4b84d7, .pop = 0x4a8ea2, .wait_loop_ret = 0x4b84e5, .sites = {0x4a3296}, .nsites = 1, .name_loop = {0x53aecd, 0x53b129}},
        .display = {.width = 0x57a7d0, .height = 0x57a7d4},
        .programs = {{"facemaker.exe", "game_facemaker"}, {"deck.exe", "game_sotadeck"}, {"shandalar.exe", "game_shandalar"}},
        .lzw = {.header = 0x91e000, .read = 0x91e484, .read2 = 0x91e1fc, .block = 0x582070,
                .in_ptr = 0x915cd0, .in_end = 0x581fc0, .refill = 0x726b1c, .callback = 0x55d9e0},
    },
    {
        .id = ID_V215_FACEMAKER, .build = "v2.15", .file = "FaceMaker.exe", .program = "FACEMAKER",
        .lzw = {.header = 0x428000, .read = 0x428484, .read2 = 0x4281fc, .block = 0x40d340,
                .in_ptr = 0x422110, .in_end = 0x40d294, .refill = 0x422320, .callback = 0x407720},
    },
    {
        .id = ID_V215_DECK, .build = "v2.15", .file = "DECK.EXE", .program = "DECK",
    },
    {
        .id = ID_V215_DECKDLL, .build = "v2.15", .file = "deckdll.dll", .program = "", .base = 0x32000000,
        .lzw = {.header = 0x321e9000, .read = 0x321e9484, .read2 = 0x321e91fc, .block = 0x3203505c,
                .in_ptr = 0x3210420c, .in_end = 0x3203955c, .refill = 0x32104410, .callback = 0x3202c598},
    },
    {
        .id = ID_V215_CARDARTLIB, .build = "v2.15", .file = "cardartlib.dll", .program = "", .base = 0x34000000,
    },
    {
        .id = ID_V215_DRAWCARDLIB, .build = "v2.15", .file = "drawcardlib.dll", .program = "", .base = 0x36000000,
        .lzw = {.header = 0x36155000, .read = 0x36155484, .read2 = 0x361551fc, .block = 0x36022104,
                .in_ptr = 0x3612548c, .in_end = 0x360220e8, .refill = 0x36125690, .callback = 0x36005915},
    },
    {
        .id = ID_V215_CDTOOLS, .build = "v2.15", .file = "CdTools.dll", .program = "", .base = 0x38000000,
    },
    {
        .id = ID_V215_STATWIN, .build = "v2.15", .file = "STATWIN.DLL", .program = "", .base = 0x30000000,
    },
};

size_t profile_count(void) { return sizeof(PROFILES) / sizeof(PROFILES[0]); }
const BuildProfile *profile_table(void) { return PROFILES; }
const BuildProfile *profile_at(size_t i) { return i < profile_count() ? &PROFILES[i] : NULL; }

/* No address anywhere: what an unknown build runs with. */
const BuildProfile PROFILE_NONE = {.id = "", .build = "unknown", .file = "", .program = ""};
const BuildProfile *profile = &PROFILE_NONE;
int profile_guest_writes;

const BuildProfile *profile_find_in(const BuildProfile *table, size_t n, const char *id)
{
    size_t i;

    if (!id || !*id)
        return NULL;
    for (i = 0; i < n; i++)
        if (!strcmp(table[i].id, id))
            return &table[i];
    return NULL;
}

const BuildProfile *profile_find(const char *id) { return profile_find_in(PROFILES, profile_count(), id); }

void profile_name(const BuildProfile *p, char *out, size_t cap) { snprintf(out, cap, "%s %s", p->build, p->file); }

/* ---- SHA-256 -------------------------------------------------------------------------------------------------------------------------------------------- */
typedef struct Sha { uint32_t h[8]; uint64_t len; uint8_t buf[64]; size_t fill; } Sha;

static const uint32_t K[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};

#define ROR(x, n) (((x) >> (n)) | ((x) << (32 - (n))))

static void sha_block(Sha *s, const uint8_t *p)
{
    uint32_t w[64], a, b, c, d, e, f, g, h;
    int i;

    for (i = 0; i < 16; i++)
        w[i] = (uint32_t)p[4 * i] << 24 | (uint32_t)p[4 * i + 1] << 16 | (uint32_t)p[4 * i + 2] << 8 | (uint32_t)p[4 * i + 3];
    for (i = 16; i < 64; i++) {
        uint32_t s0 = ROR(w[i - 15], 7) ^ ROR(w[i - 15], 18) ^ (w[i - 15] >> 3), s1 = ROR(w[i - 2], 17) ^ ROR(w[i - 2], 19) ^ (w[i - 2] >> 10);

        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    a = s->h[0]; b = s->h[1]; c = s->h[2]; d = s->h[3]; e = s->h[4]; f = s->h[5]; g = s->h[6]; h = s->h[7];
    for (i = 0; i < 64; i++) {
        uint32_t t1 = h + (ROR(e, 6) ^ ROR(e, 11) ^ ROR(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i];
        uint32_t t2 = (ROR(a, 2) ^ ROR(a, 13) ^ ROR(a, 22)) + ((a & b) ^ (a & c) ^ (b & c));

        h = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    s->h[0] += a; s->h[1] += b; s->h[2] += c; s->h[3] += d; s->h[4] += e; s->h[5] += f; s->h[6] += g; s->h[7] += h;
}

static void sha_init(Sha *s)
{
    static const uint32_t init[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};

    memcpy(s->h, init, sizeof(init));
    s->len = 0;
    s->fill = 0;
}

static void sha_update(Sha *s, const uint8_t *p, size_t n)
{
    s->len += n;
    while (n) {
        size_t take = 64 - s->fill;

        if (take > n)
            take = n;
        memcpy(s->buf + s->fill, p, take);
        s->fill += take;
        p += take;
        n -= take;
        if (s->fill == 64) {
            sha_block(s, s->buf);
            s->fill = 0;
        }
    }
}

static void sha_final(Sha *s, char hex[65])
{
    static const char digit[] = "0123456789abcdef";
    uint64_t bits = s->len * 8;
    uint8_t pad = 0x80;
    int i;

    sha_update(s, &pad, 1);
    pad = 0;
    while (s->fill != 56)
        sha_update(s, &pad, 1);
    for (i = 7; i >= 0; i--) {
        uint8_t b = (uint8_t)(bits >> (8 * i));

        sha_update(s, &b, 1);
    }
    for (i = 0; i < 32; i++) {
        uint8_t b = (uint8_t)(s->h[i / 4] >> (24 - 8 * (i % 4)));

        hex[2 * i] = digit[b >> 4];
        hex[2 * i + 1] = digit[b & 15];
    }
    hex[64] = 0;
}

void profile_sha256(const void *data, size_t n, char hex[65])
{
    Sha s;

    sha_init(&s);
    sha_update(&s, data, n);
    sha_final(&s, hex);
}

int profile_file_id(const char *path, char hex[65])
{
    FILE *f = fopen(path, "rb");
    uint8_t buf[65536];
    size_t n;
    Sha s;

    if (!f)
        return 0;
    sha_init(&s);
    while ((n = fread(buf, 1, sizeof(buf), f)) > 0)
        sha_update(&s, buf, n);
    if (ferror(f)) {
        fclose(f);
        return 0;
    }
    fclose(f);
    sha_final(&s, hex);
    return 1;
}

/* ---- the verdict ---------------------------------------------------------------------------------------------------------------------------------------- */
ProfileVerdict profile_classify(const BuildProfile *table, size_t n, const char *program, const char *module_id, const char *file_id, const BuildProfile **out)
{
    const BuildProfile *p;

    *out = NULL;
    if (!module_id || strlen(module_id) != 64)
        return PROFILE_NO_MODULE_ID;
    if (!file_id)
        return PROFILE_NO_FILE;
    if (strcmp(module_id, file_id))
        return PROFILE_FILE_MISMATCH;
    p = profile_find_in(table, n, module_id);
    if (!p || strcmp(p->program, program ? program : ""))
        return PROFILE_UNKNOWN;
    *out = p;
    return PROFILE_OK;
}

static const char *base_name(const char *path)
{
    const char *b = path, *p;

    for (p = path; *p; p++)
        if (*p == '/' || *p == '\\' || *p == ':')
            b = p + 1;
    return b;
}

static int same_name(const char *a, const char *b)
{
    for (; *a && *b; a++, b++) {
        int x = *a >= 'A' && *a <= 'Z' ? *a + 32 : *a, y = *b >= 'A' && *b <= 'Z' ? *b + 32 : *b;

        if (x != y)
            return 0;
    }
    return !*a && !*b;
}

/* "v1.0 MAGIC.EXE, v1.0 DUEL.EXE": the rows for this kind of file (the program's name, or a library's file name); every row if there is none */
static void supported_list(char *out, size_t cap, const char *program, const char *file)
{
    size_t i, len;
    int pass;

    for (pass = 0; pass < 2; pass++) {
        out[0] = 0;
        len = 0;
        for (i = 0; i < profile_count(); i++) {
            const BuildProfile *p = &PROFILES[i];
            int match = pass == 1 || (program ? !strcmp(p->program, program) : (!p->program[0] && same_name(p->file, file)));
            char name[64];

            if (!match)
                continue;
            profile_name(p, name, sizeof(name));
            if (len + strlen(name) + 3 >= cap)
                break;
            len += (size_t)snprintf(out + len, cap - len, "%s%s", len ? ", " : "", name);
        }
        if (out[0])
            return;
    }
}

void profile_message(char *out, size_t cap, ProfileVerdict v, const char *file, const char *program, const char *file_id, const char *module_id)
{
    char list[512];

    out[0] = 0;
    switch (v) {
    case PROFILE_UNKNOWN:
    case PROFILE_NO_MODULE_ID:
        supported_list(list, sizeof(list), program, file);
        snprintf(out, cap, "pentamoor: %s is build %s, which this version does not support (supported: %s)%s", file, file_id ? file_id : "?", list,
                 v == PROFILE_NO_MODULE_ID ? " -- and the game module carries no build id (an older lifter made it), so it cannot be matched to any build" : "");
        break;
    case PROFILE_FILE_MISMATCH:
        snprintf(out, cap, "pentamoor: %s is build %s, but the game module was made from build %s: run the installer again to lift it from this file", file, file_id ? file_id : "?",
                 module_id ? module_id : "?");
        break;
    case PROFILE_NO_FILE:
        snprintf(out, cap, "pentamoor: cannot read %s to check which build it is", file);
        break;
    case PROFILE_OK:
        break;
    }
}

int profile_allow_unknown(void)
{
    const char *v = getenv("PORT_UNKNOWN_BUILD");

    return v && *v && strcmp(v, "0");
}

/* Stop (status 3), or with PORT_UNKNOWN_BUILD=1 say what is off and go on. `library`: the file is one of the program's libraries, not the program. */
static void unsupported(const char *msg, int library)
{
    if (profile_allow_unknown()) {
        if (library)
            fprintf(stderr, "%s\npentamoor: warning: PORT_UNKNOWN_BUILD=1 is set, so the library is used anyway, with no address-keyed override of its own "
                    "(its picture decompressor is one: it will probably stop at its first picture)\n", msg);
        else
            fprintf(stderr, "%s\npentamoor: warning: PORT_UNKNOWN_BUILD=1 is set, so the game starts anyway with every address-keyed hook, override and write turned off "
                    "(the picture decompressor is one of them: the game will probably stop at its first picture)\n", msg);
        return;
    }
    fprintf(stderr, "%s\npentamoor: PORT_UNKNOWN_BUILD=1 starts it anyway with every address-keyed hook, override and write turned off (for research; it will probably stop at the first picture)\n", msg);
    exit(3);
}

void profile_init(const char *exe_path)
{
    char fid[65], msg[1024];
    const BuildProfile *p = NULL;
    ProfileVerdict v;

    profile = &PROFILE_NONE;
    if (!profile_file_id(exe_path, fid))
        return;                                 /* the loader says it cannot open the file, with its own message and status */
    v = profile_classify(PROFILES, profile_count(), lift_game->program, lift_game->build_id, fid, &p);
    if (v == PROFILE_OK) {
        char name[64];

        profile = p;
        profile_name(p, name, sizeof(name));
        port_log("build: %s (sha256 %.12s)", name, fid);
        return;
    }
    profile_message(msg, sizeof(msg), v, base_name(exe_path), lift_game->program, fid, lift_game->build_id);
    unsupported(msg, 0);
}

const BuildProfile *profile_check_library(const LiftModule *m, const char *host_path)
{
    char fid[65], msg[1024];
    const BuildProfile *p = NULL;
    ProfileVerdict v;

    if (!profile_file_id(host_path, fid))
        return &PROFILE_NONE;                   /* the loader reports a file that is not there */
    v = profile_classify(PROFILES, profile_count(), NULL, m->build_id, fid, &p);
    if (v == PROFILE_OK && p->base != m->base)
        v = PROFILE_UNKNOWN;                    /* a row for this file, but for another base than the module was lifted for */
    if (v != PROFILE_OK) {
        profile_message(msg, sizeof(msg), v, base_name(host_path), NULL, fid, m->build_id);
        unsupported(msg, 1);
        return &PROFILE_NONE;
    }
    return profile == &PROFILE_NONE ? &PROFILE_NONE : p;
}

/* ---- the one write ------------------------------------------------------------------------------------------------------------------------------------- */
int profile_write_screen_size(int w, int h)
{
    if (!profile->display.width || !profile->display.height)
        return 0;
    WR32(profile->display.width, (uint32_t)w);
    WR32(profile->display.height, (uint32_t)h);
    profile_guest_writes += 2;
    return 2;
}

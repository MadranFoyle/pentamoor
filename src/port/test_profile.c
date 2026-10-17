/* test_profile.c - build profiles (profile.c): SHA-256, the table with every address of the 1.0 build (each compared with the literal the sources used before the table existed, so a typo
 * cannot slip in), the choice of a profile by build id, the refusal of an unknown build, what the hook installers do under a profile (the addresses they hook; none under PROFILE_NONE),
 * and a fake second profile that is selected and used in place of the first. No game file is needed.
 *   make -C src/port test */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "plat.h"
#include "port.h"
#include "profile.h"
#include "screens.h"
#include "test_util.h"
#include "yesno.h"

static int failures, checks;
#define CHECK(c) do { checks++; if (!(c)) { failures++; printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

int pe_find_resource(uint32_t hinst, uint32_t type, uint32_t name, uint32_t *addr, uint32_t *size) { (void)hinst; (void)type; (void)name; (void)addr; (void)size; return 0; }

#define ID_MAGIC "4dc592695b6ee390485f283feb2a248cd3f3f739749c2800ab3b1100ea03845c"
#define ID_DUEL "7c4e618b4a8ab4330c71d2dd30637c522573c133d32c667c97924dc8edc2efed"
#define ID_DECK "193f8abea01d4f2c03b769224b06eece6e263a18f13a5b4e2509ed25a01e3d90"
#define ID_DECKDLL "a21f714bea465077c4fabe4a407ff7503b0ce5f9bb1a277826e74276e35c2c18"
#define ID_STATWIN "95bd14de41e8fff84217cdf627a48392da5e7be9c3d064a68e04ed1455334bd7"
#define ID_MAGSND "6f6d51cd2b8a5800b0b3c994e3ee8217f7b40ba2621f9738783387f3250a9882"
/* Spells of the Ancients 2.15 */
#define ID_S_SHANDALAR "e4e46718c451974756b66e7666ac0bf1cc9ebdbc5897eb04a87b8ea2a02353e7"
#define ID_S_FACEMAKER "b4f3d19614dcd825da846d097baa3cd9badc0c9852492bc27a8ba62c1741a493"
#define ID_S_DECK "c7ec116aecdcde9ab976cc97cba81482fc4219278f8042edf667456ede3dd8ef"
#define ID_S_DECKDLL "ce741d1f5547c143fd8494bbe09c26e918b892a3d9fc3c3761babb3c8268a667"
#define ID_S_CARDARTLIB "689be4a86ca843e76057172543cfa3516d8ccbc2efb1699e7c7935b6dc3ead11"
#define ID_S_DRAWCARDLIB "c7747313d59b6fa48ec56b479dce9ed5d90f8a95fc47e93990c4369bbd2fa1f8"
#define ID_S_CDTOOLS "0d0c2bfa87de02499f1f73f21f34824b1c2572f3e6ae0b5dca7ca343ddf1b77d"
#define ID_S_STATWIN "c1ca59496afa786f22fcd97b94052b937910a613f9321399b4ef4dd5dec76940"

static int hex_ok(const char *s)
{
    size_t i;

    if (strlen(s) != 64)
        return 0;
    for (i = 0; i < 64; i++)
        if (!((s[i] >= '0' && s[i] <= '9') || (s[i] >= 'a' && s[i] <= 'f')))
            return 0;
    return 1;
}

static void test_sha256(void)
{
    char hex[65], file_hex[65], dir[300], path[400];
    char *big = malloc(1000000);
    size_t i;
    FILE *f;

    profile_sha256("", 0, hex);
    CHECK(!strcmp(hex, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"));
    profile_sha256("abc", 3, hex);
    CHECK(!strcmp(hex, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"));
    profile_sha256("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq", 56, hex);              /* two blocks */
    CHECK(!strcmp(hex, "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"));
    memset(big, 'a', 1000000);
    profile_sha256(big, 1000000, hex);
    CHECK(!strcmp(hex, "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0"));
    /* the lengths around a block: 55 bytes fit one block with the padding, 56 and 64 need a second */
    {
        static const struct { size_t n; const char *want; } v[] = {
            {55, "9f4390f8d30c2dd92ec9f095b65e2b9ae9b0a925a5258e241c9f1e910f734318"},
            {56, "b35439a4ac6f0948b6d6f9e3c6af0f5f590ce20f1bde7090ef7970686ec6738a"},
            {64, "ffe054fe7ae0cb6dc65c3af9b61d5209f439851db43d0ba5997337df154668eb"},
        };
        size_t k;

        for (k = 0; k < sizeof(v) / sizeof(v[0]); k++) {
            profile_sha256(big, v[k].n, hex);
            CHECK(!strcmp(hex, v[k].want));
        }
    }
    /* a file is hashed the same way, in pieces */
    test_tmpdir(dir, sizeof(dir), "profile_");
    CHECK(dir[0]);
    snprintf(path, sizeof(path), "%s/f.bin", dir);
    f = fopen(path, "wb");
    for (i = 0; i < 3; i++)
        fwrite(big, 1, 100000, f);
    fclose(f);
    profile_sha256(big, 100000, hex);       /* (not the file's) */
    CHECK(profile_file_id(path, file_hex));
    {
        char *three = malloc(300000);

        for (i = 0; i < 3; i++)
            memcpy(three + i * 100000, big, 100000);
        profile_sha256(three, 300000, hex);
        free(three);
    }
    CHECK(!strcmp(hex, file_hex));
    CHECK(!profile_file_id("/no/such/folder/file.exe", file_hex));
    test_rmtree(dir);
    free(big);
}

/* The 1.0 build as the sources had it before the table: one literal for each field. A typo in profile.c fails here. */
static void test_v10_values(void)
{
    const BuildProfile *m = profile_find(ID_MAGIC), *d = profile_find(ID_DUEL), *k = profile_find(ID_DECK), *dd = profile_find(ID_DECKDLL), *sw = profile_find(ID_STATWIN);
    char name[64];

    CHECK(profile_count() == 13);                /* five rows of 1.0, eight of Spells of the Ancients 2.15 (test_v215_values) */
    CHECK(m && d && k && dd && sw);
    if (!m || !d || !k || !dd || !sw)
        return;
    profile_name(m, name, sizeof(name));
    CHECK(!strcmp(name, "v1.0 MAGIC.EXE") && !strcmp(m->program, "MAGIC") && !m->base);
    profile_name(d, name, sizeof(name));
    CHECK(!strcmp(name, "v1.0 DUEL.EXE") && !strcmp(d->program, "DUEL"));
    profile_name(k, name, sizeof(name));
    CHECK(!strcmp(name, "v1.0 DECK.EXE") && !strcmp(k->program, "DECK"));
    profile_name(dd, name, sizeof(name));
    CHECK(!strcmp(name, "v1.0 DECKDLL.DLL") && !strcmp(dd->program, "") && dd->base == 0x32000000u);
    profile_name(sw, name, sizeof(name));
    CHECK(!strcmp(name, "v1.0 STATWIN.DLL") && !strcmp(sw->program, "") && sw->base == 0x30000000u);

    /* pace.c */
    CHECK(m->pace.tick_fn == 0x5016f9u && m->pace.frame_ret == 0x4e7873u && m->pace.ticks == 0x530da0u);
    CHECK(m->buttons.pass == 0x41f3eau && m->buttons.mouse_var == 0x7039c4u);
    CHECK(m->pace.map_loop.lo == 0x4e73a0u && m->pace.map_loop.hi == 0x4e7936u);
    /* screens.c */
    CHECK(m->buttons.snapshot == 0x44b84bu && m->buttons.ctx_cur == 0x519c24u && m->buttons.ctx_count == 0x67f780u && m->buttons.ctx_ptrs == 0x67f7d0u);
    CHECK(m->buttons.rec_x == 0x10 && m->buttons.rec_y == 0x14 && m->buttons.rec_w == 0x18 && m->buttons.rec_h == 0x1c && m->buttons.rec_handler == 0x24 && m->buttons.rec_type == 0x40);
    CHECK(m->textmenu.loop.lo == 0x489748u && m->textmenu.loop.hi == 0x489c9cu);
    CHECK(m->textmenu.left == 0x539decu && m->textmenu.top == 0x539df0u && m->textmenu.right == 0x676d44u && m->textmenu.line_h == 0x527b30u);
    CHECK(m->textmenu.first == 0x676d50u && m->textmenu.count == 0x676d40u && m->textmenu.mask == 0x676d58u);
    CHECK(m->buycards.loop.lo == 0x509517u && m->buycards.loop.hi == 0x509fd4u && m->buycards.ids == 0x61e060u && m->buycards.count_ebp == -0xa8 && m->buycards.boxes_ebp == -0xa0);
    CHECK(m->clues.loop.lo == 0x48f523u && m->clues.loop.hi == 0x49094cu && m->clues.count_ebp == -0x12d8);
    CHECK(m->title.loop.lo == 0x47a2e6u && m->title.loop.hi == 0x47a94cu);
    /* yesno.c, textfocus.c */
    CHECK(m->keys.wait == 0x48ac2fu && m->keys.pop == 0x4080b2u && m->keys.wait_loop_ret == 0x48ac3du);
    CHECK(m->keys.nsites == 3 && m->keys.sites[0] == 0x509e4au && m->keys.sites[1] == 0x4f156eu && m->keys.sites[2] == 0x45119du);
    CHECK(m->keys.name_loop.lo == 0x47be64u && m->keys.name_loop.hi == 0x47c080u);
    /* main.c */
    CHECK(m->display.width == 0x522458u && m->display.height == 0x52245cu);

    /* lzw.c: the three copies, each field and each offset in the state block against the literal the code had (MAGIC's absolute addresses plus the copy's `delta`) */
    {
        static const struct { uint32_t off, magic; } state[] = {
            {LZW_DICT, 0x532860}, {LZW_SIZE_LO, 0x536860}, {LZW_SIZE_HI, 0x536864}, {LZW_PARAM, 0x536868}, {LZW_STACK_PTR, 0x53686c}, {LZW_COUNT, 0x536870},
            {LZW_REPEAT, 0x536874}, {LZW_BYTE, 0x536875}, {LZW_WIDTH, 0x536876}, {LZW_WIDTH_MAX, 0x536877}, {LZW_MASK, 0x536878}, {LZW_NEXT, 0x53687c},
            {LZW_BITS, 0x536880}, {LZW_BITFILL, 0x536884}, {LZW_NIBBLE, 0x536885}, {LZW_PREV, 0x536886}, {LZW_FIRST, 0x53688a}, {LZW_STACK_BASE, 0x536c8b},
        };
        const struct { const BuildProfile *p; uint32_t delta; } copies[3] = {{m, 0u}, {d, 0xFFFC88F4u}, {dd, 0x31B13FB0u}};
        size_t i;
        int c;

        CHECK(m->lzw.header == 0x70d000u && m->lzw.read == 0x70d484u && m->lzw.read2 == 0x70d1fcu);
        CHECK(m->lzw.in_ptr == 0x706500u && m->lzw.in_end == 0x5327b0u && m->lzw.refill == 0x67f43cu && m->lzw.callback == 0x50e8b0u);
        CHECK(d->lzw.header == 0x6c5000u && d->lzw.read == 0x6c5484u && d->lzw.read2 == 0x6c51fcu);
        CHECK(d->lzw.in_ptr == 0x69453cu && d->lzw.in_end == 0x4f7918u && d->lzw.refill == 0x694740u && d->lzw.callback == 0x43d858u);
        CHECK(dd->lzw.header == 0x32000000u + 0x218000u && dd->lzw.read == 0x32000000u + 0x218000u + 0x484u && dd->lzw.read2 == 0x32000000u + 0x218000u + 0x1fcu);
        CHECK(dd->lzw.in_ptr == 0x3213eefcu && dd->lzw.in_end == 0x3204baecu && dd->lzw.refill == 0x3213f170u && dd->lzw.callback == 0x3200141fu);
        for (c = 0; c < 3; c++)
            for (i = 0; i < sizeof(state) / sizeof(state[0]); i++)
                CHECK(copies[c].p->lzw.block + state[i].off == copies[c].delta + state[i].magic);
    }

    /* the files with nothing hooked */
    CHECK(!k->lzw.header && !k->pace.tick_fn && !k->buttons.pass && !k->keys.wait && !k->display.width);
    CHECK(!sw->lzw.header && !sw->pace.tick_fn && !sw->buttons.pass && !sw->keys.wait && !sw->display.width);
    CHECK(!d->pace.tick_fn && !d->buttons.pass && !d->keys.wait && !d->display.width && d->keys.nsites == 0);
    CHECK(!dd->pace.tick_fn && !dd->buttons.pass && !dd->keys.wait && !dd->display.width);

    /* the table: unique 64-character ids, in the form of tools/lift/builds.py, and the ids the installer has had since before the table (install.py) */
    {
        size_t i, j;

        for (i = 0; i < profile_count(); i++) {
            CHECK(hex_ok(profile_at(i)->id));
            for (j = i + 1; j < profile_count(); j++)
                CHECK(strcmp(profile_at(i)->id, profile_at(j)->id) != 0);
        }
    }
    CHECK(!profile_find(ID_MAGSND));            /* a library the port provides itself is not in the table */
}

/* Spells of the Ancients 2.15: every row, with the values tools/research/sotalzw.py and tools/lift/builds.py give, and the rule that a row with no verified hooks holds none. */
/* The groups (HK_*) a row holds addresses of. A row may hold a group only if its `hooks_verified` has the bit. */
static int hook_groups(const BuildProfile *p)
{
    int g = 0;

    if (p->pace.tick_fn || p->pace.ticks || p->pace.frame_ret || p->pace.map_loop.hi || p->pace.idle_fn || p->pace.idle_ms)
        g |= HK_PACE;
    if (p->buttons.pass || p->buttons.mouse_var)
        g |= HK_PACE;
    if (p->buttons.snapshot || p->buttons.ctx_cur || p->buttons.ctx_count || p->buttons.ctx_ptrs)
        g |= HK_BUTTONS;
    if (p->textmenu.loop.hi || p->textmenu.left || p->textmenu.top || p->textmenu.right || p->textmenu.line_h || p->textmenu.first || p->textmenu.count || p->textmenu.mask)
        g |= HK_TEXTMENU;
    if (p->buycards.loop.hi || p->buycards.ids || p->buycards.count_ebp || p->buycards.boxes_ebp)
        g |= HK_BUYCARDS;
    if (p->clues.loop.hi || p->clues.count_ebp)
        g |= HK_CLUES;
    if (p->title.loop.hi)
        g |= HK_TITLE;
    if (p->keys.wait || p->keys.pop || p->keys.wait_loop_ret || p->keys.nsites || p->keys.name_loop.hi)
        g |= HK_KEYS;
    if (p->display.width || p->display.height)
        g |= HK_DISPLAY;
    return g;
}
static int has_hook_fields(const BuildProfile *p) { return hook_groups(p) != 0; }

static void test_v215_values(void)
{
    static const struct { const char *id, *file, *program; uint32_t base; } rows[] = {
        {ID_S_SHANDALAR, "shandalar.exe", "SHANDALAR", 0}, {ID_S_FACEMAKER, "FaceMaker.exe", "FACEMAKER", 0}, {ID_S_DECK, "DECK.EXE", "DECK", 0},
        {ID_S_DECKDLL, "deckdll.dll", "", 0x32000000u}, {ID_S_CARDARTLIB, "cardartlib.dll", "", 0x34000000u}, {ID_S_DRAWCARDLIB, "drawcardlib.dll", "", 0x36000000u},
        {ID_S_CDTOOLS, "CdTools.dll", "", 0x38000000u}, {ID_S_STATWIN, "STATWIN.DLL", "", 0x30000000u},
    };
    size_t i, n = 0;
    char name[64];
    const BuildProfile *sh = profile_find(ID_S_SHANDALAR), *fm = profile_find(ID_S_FACEMAKER), *dd = profile_find(ID_S_DECKDLL), *dc = profile_find(ID_S_DRAWCARDLIB);

    for (i = 0; i < sizeof(rows) / sizeof(rows[0]); i++) {
        const BuildProfile *p = profile_find(rows[i].id);

        CHECK(p != NULL);
        if (!p)
            continue;
        profile_name(p, name, sizeof(name));
        CHECK(!strcmp(p->build, "v2.15") && !strcmp(p->file, rows[i].file) && !strcmp(p->program, rows[i].program) && p->base == rows[i].base);
        if (p != profile_find(ID_S_SHANDALAR))
            CHECK(!p->hooks_verified && !has_hook_fields(p));       /* only shandalar.exe has hooks: the others hold none */
    }
    for (i = 0; i < profile_count(); i++) {
        const BuildProfile *p = profile_at(i);

        CHECK((hook_groups(p) & ~p->hooks_verified) == 0);          /* a group that is not verified holds none of its addresses, whichever build it is */
        CHECK((p->hooks_verified & ~HK_ALL) == 0);
        if (hook_groups(p))
            n++;
    }
    CHECK(profile_find(ID_MAGIC)->hooks_verified == HK_ALL && hook_groups(profile_find(ID_MAGIC)) == HK_ALL);     /* MAGIC.EXE 1.0: every group verified */
    CHECK(n == 2);                                          /* MAGIC.EXE 1.0 and shandalar.exe 2.15 hold hook addresses */
    CHECK(sh && sh->display.width == 0x57a7d0u && sh->display.height == 0x57a7d4u && hook_groups(sh) == (HK_DISPLAY | HK_PACE) && sh->hooks_verified == (HK_DISPLAY | HK_PACE));
    CHECK(sh->pace.tick_fn == 0x48a3a5u && sh->pace.ticks == 0x566f3cu && sh->pace.frame_ret == 0x438f85u && sh->pace.map_loop.lo == 0x438a70u && sh->pace.map_loop.hi == 0x439059u);
    CHECK(sh->pace.idle_fn == 0x4eab14u && sh->pace.idle_ms == 10 && !profile_find(ID_MAGIC)->pace.idle_ms && !profile_find(ID_MAGIC)->pace.idle_fn);   /* 1.0 does not nap */
    CHECK(sh->buttons.pass == 0x4ba087u && sh->buttons.mouse_var == 0x9199b0u && !sh->buttons.snapshot);
    CHECK(sh && fm && dd && dc);
    if (!sh || !fm || !dd || !dc)
        return;
    /* the picture decompressor of each copy: shandalar.exe 0x91e000, FaceMaker.exe 0x428000, deckdll.dll and drawcardlib.dll at their bases (the section of each library at its own offset) */
    CHECK(sh->lzw.header == 0x91e000u && sh->lzw.read == 0x91e484u && sh->lzw.read2 == 0x91e1fcu && sh->lzw.block == 0x582070u);
    CHECK(sh->lzw.in_ptr == 0x915cd0u && sh->lzw.in_end == 0x581fc0u && sh->lzw.refill == 0x726b1cu && sh->lzw.callback == 0x55d9e0u);
    CHECK(fm->lzw.header == 0x428000u && fm->lzw.read == 0x428484u && fm->lzw.read2 == 0x4281fcu && fm->lzw.block == 0x40d340u);
    CHECK(fm->lzw.in_ptr == 0x422110u && fm->lzw.in_end == 0x40d294u && fm->lzw.refill == 0x422320u && fm->lzw.callback == 0x407720u);
    CHECK(dd->lzw.header == 0x32000000u + 0x1e9000u && dd->lzw.read == dd->lzw.header + 0x484u && dd->lzw.read2 == dd->lzw.header + 0x1fcu && dd->lzw.block == 0x3203505cu);
    CHECK(dd->lzw.in_ptr == 0x3210420cu && dd->lzw.in_end == 0x3203955cu && dd->lzw.refill == 0x32104410u && dd->lzw.callback == 0x3202c598u);
    CHECK(dc->lzw.header == 0x36000000u + 0x155000u && dc->lzw.read == dc->lzw.header + 0x484u && dc->lzw.read2 == dc->lzw.header + 0x1fcu && dc->lzw.block == 0x36022104u);
    CHECK(dc->lzw.in_ptr == 0x3612548cu && dc->lzw.in_end == 0x360220e8u && dc->lzw.refill == 0x36125690u && dc->lzw.callback == 0x36005915u);
    CHECK(!profile_find(ID_S_DECK)->lzw.header && !profile_find(ID_S_CARDARTLIB)->lzw.header && !profile_find(ID_S_CDTOOLS)->lzw.header && !profile_find(ID_S_STATWIN)->lzw.header);
    /* the block of the state is the same distance from the dictionary in every copy: the same offsets as 1.0's (profile.h, LZW_*) fit, e.g. the code width byte */
    CHECK(sh->lzw.block + LZW_WIDTH == 0x582070u + 0x4016u && dd->lzw.block + LZW_STACK_BASE == 0x3203505cu + 0x442bu);
    /* what shandalar.exe may start: FaceMaker.exe, DECK.EXE and itself; the others start nothing */
    CHECK(!strcmp(sh->programs[0].file, "facemaker.exe") && !strcmp(sh->programs[0].module, "game_facemaker"));
    CHECK(!strcmp(sh->programs[1].file, "deck.exe") && !strcmp(sh->programs[1].module, "game_sotadeck"));
    CHECK(!strcmp(sh->programs[2].file, "shandalar.exe") && !strcmp(sh->programs[2].module, "game_shandalar") && !sh->programs[3].file);
    CHECK(!fm->programs[0].file && !dd->programs[0].file && !profile_find(ID_MAGIC)->programs[0].file);
}

/* The hooks a profile installs: the addresses, in the order the sources installed them. */
static int hooks_are(const uint32_t *want_hooks, int nh, const uint32_t *want_over, int no)
{
    int i, ok = port_hook_count() == nh + no;

    for (i = 0; ok && i < nh + no; i++) {
        uint32_t a;
        int ov;

        if (!port_hook_at(i, &a, &ov))
            return 0;
        ok = ov == (i >= nh) && a == (i < nh ? want_hooks[i] : want_over[i - nh]);
    }
    return ok;
}

static void install_all(void)
{
    port_hooks_reset();
    lzw_install();
    pace_install();
    textfocus_install();
    screens_install();
    yesno_install();
}

static void test_hooks(void)
{
    static const uint32_t magic_hooks[] = {0x41f3ea, 0x4080b2, 0x41f3ea, 0x44b84b, 0x48ac2f, 0x4080b2};
    static const uint32_t magic_over[] = {0x70d000, 0x70d484, 0x70d1fc, 0x5016f9};
    static const uint32_t duel_over[] = {0x6c5000, 0x6c5484, 0x6c51fc};
    static const uint32_t deckdll_over[] = {0x32218000, 0x32218484, 0x322181fc};
    static const uint32_t none[] = {0};
    const BuildProfile *m = profile_find(ID_MAGIC), *d = profile_find(ID_DUEL), *dd = profile_find(ID_DECKDLL), *sw = profile_find(ID_STATWIN);

    /* no profile (an unknown build run with PORT_UNKNOWN_BUILD=1, or before the build is known): nothing is hooked, overridden or written */
    profile = &PROFILE_NONE;
    install_all();
    CHECK(port_hook_count() == 0);
    lzw_install_library(&PROFILE_NONE, 0x32000000u);
    lzw_install_library(dd, 0x32000000u - 0x10000u);              /* a library mapped at another base than its code was lifted for gets no override either */
    CHECK(port_hook_count() == 0);
    CHECK(!yesno_site(0x509e4a) && !yesno_site(0x4f156e) && !yesno_site(0x45119d) && !yesno_site(0));
    screens_note(0x4899a9, 0, SRC_SNAPSHOT, 3.0);                   /* the 1.0 text menu's loop, which is no loop to this profile */
    CHECK(screens_kind(3.0) == SCREEN_NONE);
    {
        NavTarget t[4];

        CHECK(screens_collect(t, 4, 3.0) == 0);
    }
    CHECK(profile_write_screen_size(1024, 768) == 0 && profile_guest_writes == 0);
    CHECK(RD32(0x522458u) == 0 && RD32(0x52245cu) == 0);

    /* MAGIC.EXE 1.0: exactly the hooks the sources had */
    profile = m;
    install_all();
    CHECK(hooks_are(magic_hooks, 6, magic_over, 4));
    CHECK(yesno_site(0x509e4a) && yesno_site(0x4f156e) && yesno_site(0x45119d) && !yesno_site(0) && !yesno_site(0x509e45) && !yesno_site(0x48ac3d));
    screens_note(0x4899a9, 0, SRC_SNAPSHOT, 4.0);
    CHECK(screens_kind(4.0) == SCREEN_TEXTMENU);
    CHECK(profile_write_screen_size(800, 600) == 2 && profile_guest_writes == 2 && RD32(0x522458u) == 800 && RD32(0x52245cu) == 600);

    /* the other programs: DUEL.EXE has its picture decompressor and nothing else; DECK.EXE and STATWIN.DLL nothing; DECKDLL.DLL its decompressor, at its own base only */
    profile = d;
    install_all();
    CHECK(hooks_are(none, 0, duel_over, 3));
    CHECK(profile_write_screen_size(1024, 768) == 0 && profile_guest_writes == 2);
    profile = profile_find(ID_DECK);
    install_all();
    CHECK(port_hook_count() == 0);
    port_hooks_reset();
    lzw_install_library(sw, 0x30000000u);
    CHECK(port_hook_count() == 0);
    lzw_install_library(dd, 0x32000000u);
    CHECK(hooks_are(none, 0, deckdll_over, 3));
    /* Spells of the Ancients 2.15: no hook of any kind, the picture decompressor of each file that has one; two libraries have a copy and both are overridden */
    {
        static const uint32_t shandalar_hooks[] = {0x4ba087, 0x4eab14};
        static const uint32_t shandalar_over[] = {0x91e000, 0x91e484, 0x91e1fc, 0x48a3a5};
        static const uint32_t facemaker_over[] = {0x428000, 0x428484, 0x4281fc};
        static const uint32_t both_over[] = {0x321e9000, 0x321e9484, 0x321e91fc, 0x36155000, 0x36155484, 0x361551fc};

        profile = profile_find(ID_S_SHANDALAR);
        install_all();
        CHECK(hooks_are(shandalar_hooks, 2, shandalar_over, 4));
        CHECK(!yesno_site(0x4a3296) && !yesno_site(0x4f0b96) && !yesno_site(0x509e4a));
        CHECK(profile_write_screen_size(800, 600) == 2);      /* the screen-size globals 0x57a7d0 and 0x57a7d4 */
        profile = profile_find(ID_S_FACEMAKER);
        install_all();
        CHECK(hooks_are(none, 0, facemaker_over, 3));
        profile = profile_find(ID_S_DECK);
        install_all();
        CHECK(port_hook_count() == 0);
        profile = profile_find(ID_S_SHANDALAR);
        port_hooks_reset();
        lzw_install_library(profile_find(ID_S_CARDARTLIB), 0x34000000u);       /* a library with no copy of the decompressor overrides nothing */
        lzw_install_library(profile_find(ID_S_CDTOOLS), 0x38000000u);
        CHECK(port_hook_count() == 0);
        lzw_install_library(profile_find(ID_S_DECKDLL), 0x32000000u);
        lzw_install_library(profile_find(ID_S_DRAWCARDLIB), 0x36000000u);
        CHECK(hooks_are(none, 0, both_over, 6));
    }
    profile = &PROFILE_NONE;
    port_hooks_reset();
}

/* A second build that exists only here: other ids, other addresses, other offsets. */
#define ID_FAKE "00000000000000000000000000000000000000000000000000000000000000f2"
static const BuildProfile fake_table[] = {
    {.id = ID_MAGIC, .build = "v1.0", .file = "MAGIC.EXE", .program = "MAGIC", .pace = {.tick_fn = 0x5016f9, .frame_ret = 0x4e7873, .ticks = 0x530da0}, .buttons = {.pass = 0x41f3ea}},
    {
        .id = ID_FAKE, .build = "v9.9", .file = "MAGIC.EXE", .program = "MAGIC",
        .lzw = {.header = 0x91e000, .read = 0x91e484, .read2 = 0x91e1fc, .block = 0x582070, .in_ptr = 0x915cd0, .in_end = 0x581fc0, .refill = 0x726b1c, .callback = 0x55d9e0},
        .pace = {.tick_fn = 0x48a3a5, .ticks = 0x566f3c, .frame_ret = 0x438f85, .map_loop = {0x438a70, 0x439059}},
        .buttons = {.pass = 0x4ba087, .mouse_var = 0x9199b0, .snapshot = 0x4eab14, .ctx_cur = 0x577cec, .ctx_count = 0x7270e0, .ctx_ptrs = 0x727130,
                    .rec_x = 0x10, .rec_y = 0x14, .rec_w = 0x18, .rec_h = 0x1c, .rec_handler = 0x24, .rec_type = 0x40},
        .textmenu = {.loop = {0x4b6fe7, 0x4b753c}, .left = 0x6a0f54, .top = 0x6a0f58, .right = 0x728114, .line_h = 0x577c4c, .first = 0x728120, .count = 0x728110, .mask = 0x728128},
        .buycards = {.loop = {0x4a28c7, 0x4a347c}, .ids = 0x69eb70, .count_ebp = -0xa8, .boxes_ebp = -0xa0},
        .clues = {.loop = {0x4aa415, 0x4ab73e}, .count_ebp = -0x12d4},
        .keys = {.wait = 0x4b84d7, .pop = 0x4a8ea2, .wait_loop_ret = 0x4b84e5, .sites = {0x4a3296, 0x4f0b96}, .nsites = 2, .name_loop = {0x53aecd, 0x53b129}},
        .display = {.width = 0x57a7d0, .height = 0x57a7d4},
    },
};

static void test_second_profile(void)
{
    static const uint32_t fake_hooks[] = {0x4ba087, 0x4a8ea2, 0x4ba087, 0x4eab14, 0x4b84d7, 0x4a8ea2};
    static const uint32_t fake_over[] = {0x91e000, 0x91e484, 0x91e1fc, 0x48a3a5};
    const BuildProfile *p, *q;
    NavTarget t[4];

    /* chosen by build id from its table, and the first build still by its own */
    p = profile_find_in(fake_table, 2, ID_FAKE);
    q = profile_find_in(fake_table, 2, ID_MAGIC);
    CHECK(p == &fake_table[1] && q == &fake_table[0] && p != q);
    CHECK(profile_find_in(fake_table, 2, "") == NULL && profile_find_in(fake_table, 2, NULL) == NULL && profile_find_in(fake_table, 2, ID_DUEL) == NULL);
    CHECK(profile_find(ID_FAKE) == NULL);                                     /* it is not in the real table */
    CHECK(!strcmp(p->build, "v9.9"));
    {
        const BuildProfile *out = NULL;

        CHECK(profile_classify(fake_table, 2, "MAGIC", ID_FAKE, ID_FAKE, &out) == PROFILE_OK && out == p);
        CHECK(profile_classify(fake_table, 2, "MAGIC", ID_MAGIC, ID_MAGIC, &out) == PROFILE_OK && out == q);
        CHECK(profile_classify(fake_table, 2, "DUEL", ID_FAKE, ID_FAKE, &out) == PROFILE_UNKNOWN && out == NULL);     /* a row for another program */
    }

    /* its addresses, not 1.0's, are hooked, noted, asked and written */
    profile = p;
    install_all();
    CHECK(hooks_are(fake_hooks, 6, fake_over, 4));
    CHECK(yesno_site(0x4a3296) && yesno_site(0x4f0b96) && !yesno_site(0x509e4a) && !yesno_site(0x45119d));
    screens_note(0x4899a9, 0, SRC_SNAPSHOT, 10.0);
    CHECK(screens_kind(10.0) == SCREEN_NONE);                                   /* 1.0's text menu loop is not this build's */
    screens_note(0x4b7000, 0, SRC_SNAPSHOT, 11.0);
    CHECK(screens_kind(11.0) == SCREEN_TEXTMENU);
    screens_note(0x4a3000, 0x1000, SRC_SNAPSHOT, 12.0);
    CHECK(screens_kind(12.0) == SCREEN_BUYCARDS);
    screens_note(0x4aa500, 0x2000, SRC_SNAPSHOT, 13.0);
    CHECK(screens_kind(13.0) == SCREEN_CLUES);
    screens_note(0x438b00, 0, SRC_TABLE, 14.0);                                 /* its overworld */
    CHECK(screens_kind(14.0) == SCREEN_NONE);
    {
        int before = profile_guest_writes;

        CHECK(profile_write_screen_size(1024, 768) == 2 && RD32(0x57a7d0u) == 1024 && RD32(0x57a7d4u) == 768 && profile_guest_writes == before + 2);
        CHECK(RD32(0x522458u) == 800);                                          /* 1.0's globals (written in test_hooks) were not touched */
    }
    (void)t;

    /* and the first build of the same table is still the first */
    profile = q;
    install_all();
    {
        static const uint32_t first_hooks[] = {0x41f3ea}, first_over[] = {0x5016f9};

        CHECK(hooks_are(first_hooks, 1, first_over, 1));                        /* this row has the frame pacing only: nothing else is hooked */
    }
    profile = &PROFILE_NONE;
    port_hooks_reset();
}

static void test_verdicts(void)
{
    const BuildProfile *out = NULL;
    char msg[1024];

    /* the real table */
    CHECK(profile_classify(NULL, 0, "MAGIC", ID_MAGIC, ID_MAGIC, &out) == PROFILE_UNKNOWN);                  /* an empty table knows nothing */
    CHECK(profile_classify(NULL, 0, NULL, NULL, NULL, &out) == PROFILE_NO_MODULE_ID);
    CHECK(profile_classify(profile_table(), profile_count(), "MAGIC", ID_MAGIC, ID_MAGIC, &out) == PROFILE_OK && out == profile_find(ID_MAGIC));
    CHECK(profile_classify(profile_table(), profile_count(), "DUEL", ID_DUEL, ID_DUEL, &out) == PROFILE_OK && out == profile_find(ID_DUEL));
    CHECK(profile_classify(profile_table(), profile_count(), "DECK", ID_DECK, ID_DECK, &out) == PROFILE_OK);
    CHECK(profile_classify(profile_table(), profile_count(), NULL, ID_DECKDLL, ID_DECKDLL, &out) == PROFILE_OK && out->base == 0x32000000u);
    CHECK(profile_classify(profile_table(), profile_count(), NULL, ID_STATWIN, ID_STATWIN, &out) == PROFILE_OK && out->base == 0x30000000u);
    /* an unknown build: the module was lifted from the very file, but the table has no row for it */
    CHECK(profile_classify(profile_table(), profile_count(), "MAGIC", ID_FAKE, ID_FAKE, &out) == PROFILE_UNKNOWN && out == NULL);
    /* a known build, but not what this module is (the DUEL module over MAGIC.EXE's id; a program id where a library is expected) */
    CHECK(profile_classify(profile_table(), profile_count(), "DUEL", ID_MAGIC, ID_MAGIC, &out) == PROFILE_UNKNOWN);
    CHECK(profile_classify(profile_table(), profile_count(), NULL, ID_MAGIC, ID_MAGIC, &out) == PROFILE_UNKNOWN);
    CHECK(profile_classify(profile_table(), profile_count(), "MAGIC", ID_DECKDLL, ID_DECKDLL, &out) == PROFILE_UNKNOWN);
    /* the module and the file disagree, whichever of them the table knows */
    CHECK(profile_classify(profile_table(), profile_count(), "MAGIC", ID_MAGIC, ID_FAKE, &out) == PROFILE_FILE_MISMATCH);
    CHECK(profile_classify(profile_table(), profile_count(), "MAGIC", ID_FAKE, ID_MAGIC, &out) == PROFILE_FILE_MISMATCH);
    /* a module with no build id (an older lifter), an id that is not an id, a file that could not be read */
    CHECK(profile_classify(profile_table(), profile_count(), "MAGIC", NULL, ID_MAGIC, &out) == PROFILE_NO_MODULE_ID);
    CHECK(profile_classify(profile_table(), profile_count(), "MAGIC", "", ID_MAGIC, &out) == PROFILE_NO_MODULE_ID);
    CHECK(profile_classify(profile_table(), profile_count(), "MAGIC", "4dc5", ID_MAGIC, &out) == PROFILE_NO_MODULE_ID);
    CHECK(profile_classify(profile_table(), profile_count(), "MAGIC", ID_MAGIC, NULL, &out) == PROFILE_NO_FILE);

    /* what is printed */
    profile_message(msg, sizeof(msg), PROFILE_UNKNOWN, "MAGIC.EXE", "MAGIC", ID_FAKE, ID_FAKE);
    CHECK(!strcmp(msg, "pentamoor: MAGIC.EXE is build " ID_FAKE ", which this version does not support (supported: v1.0 MAGIC.EXE)"));
    profile_message(msg, sizeof(msg), PROFILE_UNKNOWN, "nosuch.exe", "NOSUCH", ID_FAKE, ID_FAKE);            /* a program no row is for: every row is listed */
    CHECK(strstr(msg, "nosuch.exe is build " ID_FAKE ", which this version does not support (supported: v1.0 MAGIC.EXE, v1.0 DUEL.EXE, v1.0 DECK.EXE, v1.0 DECKDLL.DLL, v1.0 STATWIN.DLL, v2.15 shandalar.exe, v2.15 FaceMaker.exe, v2.15 DECK.EXE") != NULL);
    profile_message(msg, sizeof(msg), PROFILE_UNKNOWN, "shandalar.exe", "SHANDALAR", ID_FAKE, ID_FAKE);       /* a program of 2.15: its own row */
    CHECK(strstr(msg, "shandalar.exe is build " ID_FAKE ", which this version does not support (supported: v2.15 shandalar.exe)") != NULL);
    profile_message(msg, sizeof(msg), PROFILE_UNKNOWN, "deckdll.dll", NULL, ID_FAKE, ID_FAKE);               /* a library: the rows for that file */
    CHECK(strstr(msg, "deckdll.dll is build " ID_FAKE ", which this version does not support (supported: v1.0 DECKDLL.DLL, v2.15 deckdll.dll)") != NULL);
    profile_message(msg, sizeof(msg), PROFILE_NO_MODULE_ID, "MAGIC.EXE", "MAGIC", ID_MAGIC, NULL);
    CHECK(strstr(msg, "MAGIC.EXE is build " ID_MAGIC ", which this version does not support") != NULL && strstr(msg, "no build id") != NULL);
    profile_message(msg, sizeof(msg), PROFILE_FILE_MISMATCH, "MAGIC.EXE", "MAGIC", ID_FAKE, ID_MAGIC);
    CHECK(strstr(msg, "MAGIC.EXE is build " ID_FAKE ", but the game module was made from build " ID_MAGIC) != NULL);
    profile_message(msg, sizeof(msg), PROFILE_OK, "x", "MAGIC", ID_MAGIC, ID_MAGIC);
    CHECK(msg[0] == 0);
}

/* profile_init against a game module (lift_game) and a file: PORT_UNKNOWN_BUILD=1 keeps PROFILE_NONE, and an unreadable file too (a refusal ends the process: make check-build tries that) */
static void test_init(void)
{
    static LiftGame g;
    const LiftGame *saved = lift_game;
    char dir[300], path[400], hex[65];
    FILE *f;

    test_tmpdir(dir, sizeof(dir), "profile_");
    snprintf(path, sizeof(path), "%s/PROG.EXE", dir);
    f = fopen(path, "wb");
    fputs("not a game", f);
    fclose(f);
    CHECK(profile_file_id(path, hex));
    g = *saved;
    g.program = "MAGIC";
    g.build_id = hex;                           /* lifted from this very file ... */
    lift_game = &g;

    profile = profile_find(ID_MAGIC);
    putenv("PORT_UNKNOWN_BUILD=");
    CHECK(!profile_allow_unknown());
    putenv("PORT_UNKNOWN_BUILD=0");
    CHECK(!profile_allow_unknown());
    profile_init("/no/such/folder/MAGIC.EXE");                      /* cannot be read: no profile, no message, no exit (the loader reports the file) */
    CHECK(profile == &PROFILE_NONE);
    putenv("PORT_UNKNOWN_BUILD=1");
    CHECK(profile_allow_unknown());
    profile = profile_find(ID_MAGIC);
    fflush(stderr);
    profile_init(path);                                             /* ... which no profile has: with the switch, it goes on with none */
    CHECK(profile == &PROFILE_NONE);
    g.build_id = ID_MAGIC;                                          /* a module for another file than this one */
    profile_init(path);
    CHECK(profile == &PROFILE_NONE);
    {
        LiftModule m = {"statwin.dll", 0x30000000u, 0x30001000u, NULL, 0, NULL, 0, NULL, 0, ID_STATWIN};

        CHECK(profile_check_library(&m, path) == &PROFILE_NONE);    /* a library whose file is not the build the module is for: none under the switch */
        CHECK(profile_check_library(&m, "/no/such/folder/STATWIN.DLL") == &PROFILE_NONE);
    }
    install_all();
    CHECK(port_hook_count() == 0);
    CHECK(profile_write_screen_size(1024, 768) == 0);
    putenv("PORT_UNKNOWN_BUILD=");
    lift_game = saved;
    profile = &PROFILE_NONE;
    test_rmtree(dir);
}

int main(void)
{
    guest_init();
    test_sha256();
    test_v10_values();
    test_v215_values();
    test_hooks();
    test_second_profile();
    test_verdicts();
    test_init();
    printf("test_profile: %d checks, %d failed\n", checks, failures);
    return failures != 0;
}

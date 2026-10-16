/* test_steamdeck.c - the Steam Deck decisions (steamdeck.c) and typed text with no key (textin.c): is this a Deck, does the window start full screen, how the 1024x768 screen is scaled
 * into a 1280x800 display, when text input is wanted, and which key presses type which characters. Pure: no SDL, no game.
 *   make -C src/port test */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "padlog.h"
#include "steamdeck.h"
#include "textin.h"

static int failures, checks;
#define CHECK(c) do { checks++; if (!(c)) { failures++; printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

static const char *const steamos =
    "NAME=\"SteamOS\"\nPRETTY_NAME=\"SteamOS\"\nVERSION_CODENAME=holo\nID=steamos\nID_LIKE=arch\nANSI_COLOR=\"1;35\"\nVARIANT_ID=steamdeck\nBUILD_ID=20240612.1\n";
static const char *const cachyos = "NAME=\"CachyOS Linux\"\nPRETTY_NAME=\"CachyOS\"\nID=cachyos\nID_LIKE=arch\nBUILD_ID=rolling\n";
static const char *const ubuntu = "PRETTY_NAME=\"Ubuntu 22.04.4 LTS\"\nNAME=\"Ubuntu\"\nID=ubuntu\nID_LIKE=debian\n";

static void test_detect(void)
{
    CHECK(deck_detect("1", NULL, NULL, NULL) == 1);                           /* Steam sets SteamDeck=1 for a game it starts on a Deck */
    CHECK(deck_detect("0", NULL, NULL, NULL) == 0);
    CHECK(deck_detect("", cachyos, "", "KDE") == 0);
    CHECK(deck_detect(NULL, steamos, NULL, NULL) == 1);                       /* SteamOS, in desktop mode too (no env at all) */
    CHECK(deck_detect(NULL, "ID=\"steamos\"\n", NULL, NULL) == 1);            /* quotes */
    CHECK(deck_detect(NULL, "ID=SteamOS\n", NULL, NULL) == 1);                /* case */
    CHECK(deck_detect(NULL, "NAME=\"SteamOS Holo\"\nID=holo\n", NULL, NULL) == 1);
    CHECK(deck_detect(NULL, "ID=bazzite\nVARIANT_ID=steamdeck\n", NULL, NULL) == 1);
    CHECK(deck_detect(NULL, cachyos, NULL, NULL) == 0);                       /* Arch-like but not a Deck */
    CHECK(deck_detect(NULL, ubuntu, NULL, NULL) == 0);
    CHECK(deck_detect(NULL, "ID_LIKE=steamos\nID=x\n", NULL, NULL) == 0);     /* only the ID, the NAME and the variant say it */
    CHECK(deck_detect(NULL, "NOTID=steamos\n", NULL, NULL) == 0);
    CHECK(deck_detect(NULL, "", NULL, NULL) == 0);
    CHECK(deck_detect(NULL, NULL, "gamescope-0", NULL) == 1);                 /* inside Gamescope (Game mode) */
    CHECK(deck_detect(NULL, NULL, "", NULL) == 0);
    CHECK(deck_detect(NULL, NULL, NULL, "gamescope") == 1);
    CHECK(deck_detect(NULL, NULL, NULL, "GameScope") == 1);
    CHECK(deck_detect(NULL, NULL, NULL, "KDE:gamescope") == 1);
    CHECK(deck_detect(NULL, NULL, NULL, "gamescope:x") == 1);
    CHECK(deck_detect(NULL, NULL, NULL, "KDE") == 0);
    CHECK(deck_detect(NULL, NULL, NULL, "gamescopes") == 0);
    CHECK(deck_detect(NULL, NULL, NULL, "") == 0);
    CHECK(deck_detect(NULL, NULL, NULL, NULL) == 0);
}

static void test_fullscreen(void)
{
    CHECK(fullscreen_wanted(NULL, 0) == 0);                                   /* nothing set, not a Deck: a window */
    CHECK(fullscreen_wanted(NULL, 1) == 1);                                   /* a Deck: full screen by itself */
    CHECK(fullscreen_wanted("1", 0) == 1);                                    /* asked for, anywhere */
    CHECK(fullscreen_wanted("1", 1) == 1);
    CHECK(fullscreen_wanted("yes", 0) == 1);
    CHECK(fullscreen_wanted("0", 1) == 0);                                    /* the Deck's default can be turned off */
    CHECK(fullscreen_wanted("", 1) == 0);
    CHECK(fullscreen_wanted("off", 1) == 0);
    CHECK(fullscreen_wanted("False", 1) == 0);
    CHECK(fullscreen_wanted("0", 0) == 0);
}

static void test_scale(void)
{
    int integer, vw, vh;
    double s;

    s = view_scale(1024, 768, 1280, 800, &integer, &vw, &vh);                 /* the Deck: 1.04x would be uneven pixels; 1x loses 4% and every pixel stays square */
    CHECK(integer == 1 && s == 1.0 && vw == 1024 && vh == 768);
    s = view_scale(1024, 768, 1920, 1080, &integer, &vw, &vh);                /* a television: 1.41x fractional, not a small 1x in the middle */
    CHECK(integer == 0 && s > 1.40 && s < 1.41 && vh == 1080 && vw == 1440);
    s = view_scale(1024, 768, 3840, 2160, &integer, &vw, &vh);                /* 4K: 2.81x (2x would use 71%) */
    CHECK(integer == 0 && vh == 2160 && vw == 2880);
    s = view_scale(1024, 768, 2048, 1536, &integer, &vw, &vh);                /* exactly twice */
    CHECK(integer == 1 && s == 2.0 && vw == 2048 && vh == 1536);
    s = view_scale(1024, 768, 2100, 1560, &integer, &vw, &vh);                /* 2.03x: whole 2x loses under 10% */
    CHECK(integer == 1 && s == 2.0);
    s = view_scale(1024, 768, 1366, 768, &integer, &vw, &vh);                 /* a 1366x768 laptop: height decides, exactly 1x */
    CHECK(integer == 1 && vw == 1024 && vh == 768);
    s = view_scale(1024, 768, 800, 600, &integer, &vw, &vh);                  /* a smaller display: scaled down, fractional, 4:3 kept */
    CHECK(integer == 0 && s < 0.79 && vw == 800 && vh == 600);
    s = view_scale(1024, 768, 1280, 720, &integer, &vw, &vh);                 /* 16:9 at 720p: 0.94x, smoothed */
    CHECK(integer == 0 && vh == 720 && vw == 960);
    s = view_scale(640, 480, 1280, 800, &integer, &vw, &vh);                  /* PORT_RES=640x480 on the Deck: 1.67x, fractional */
    CHECK(integer == 0 && vh == 800 && vw == 1067);
    s = view_scale(800, 600, 1280, 800, &integer, &vw, &vh);
    CHECK(integer == 0 && vh == 800 && vw == 1067);
    s = view_scale(1024, 768, 0, 0, &integer, &vw, &vh);                      /* an unknown display: the screen as it is */
    CHECK(integer == 0 && s == 1.0 && vw == 1024 && vh == 768);
    s = view_scale(1024, 768, 1280, 800, NULL, NULL, NULL);                   /* the outputs are optional */
    CHECK(s == 1.0);
    /* the shape is kept: the picture is 4:3 within a pixel at every display */
    {
        static const int disp[][2] = {{1280, 800}, {1920, 1080}, {2560, 1440}, {1366, 768}, {1280, 720}, {1600, 900}, {1024, 600}, {3840, 2160}};
        size_t i;

        for (i = 0; i < sizeof(disp) / sizeof(disp[0]); i++) {
            view_scale(1024, 768, disp[i][0], disp[i][1], &integer, &vw, &vh);
            CHECK(vw <= disp[i][0] && vh <= disp[i][1] && abs(vw * 3 - vh * 4) <= 4);
        }
    }
}

static void test_text_wanted(void)
{
    CHECK(text_wanted_rule(5000, 0, 0) == 0);                                 /* nothing has the focus */
    CHECK(text_wanted_rule(5000, 0, 1) == 1);                                 /* an edit control of the open dialog */
    CHECK(text_wanted_rule(5000, 4900, 0) == 1);                              /* the name box asked for a key 100 ms ago */
    CHECK(text_wanted_rule(5000, 4601, 0) == 1);
    CHECK(text_wanted_rule(5000, 4600, 0) == 0);                              /* NAME_HOLD_MS (400) after the last poll: it has been left */
    CHECK(text_wanted_rule(5000, 1000, 0) == 0);
    CHECK(text_wanted_rule(5000, 1000, 1) == 1);
    CHECK(text_wanted_rule(100, 1, 0) == 1);                                  /* the clock started a moment ago */
    CHECK(text_wanted_rule(0xFFFFFFF0u, 0xFFFFFF00u, 0) == 1);                /* the millisecond clock wraps: still unsigned arithmetic */
    CHECK(text_wanted_rule(5, 0xFFFFFFF0u, 0) == 1);
}

static void test_keys(void)
{
    TextKey k;
    int c;

    CHECK(textin_key_for_char('a', &k) && k.vk == 'A' && k.sc == 0x1E && !k.shift);       /* the same codes as front_sdl.c's keymap */
    CHECK(textin_key_for_char('q', &k) && k.vk == 'Q' && k.sc == 0x10 && !k.shift);
    CHECK(textin_key_for_char('m', &k) && k.vk == 'M' && k.sc == 0x32 && !k.shift);
    CHECK(textin_key_for_char('Z', &k) && k.vk == 'Z' && k.sc == 0x2C && k.shift);
    CHECK(textin_key_for_char('1', &k) && k.vk == '1' && k.sc == 0x02 && !k.shift);
    CHECK(textin_key_for_char('0', &k) && k.vk == '0' && k.sc == 0x0B && !k.shift);
    CHECK(textin_key_for_char('!', &k) && k.vk == '1' && k.sc == 0x02 && k.shift);
    CHECK(textin_key_for_char(' ', &k) && k.vk == 0x20 && k.sc == 0x39 && !k.shift);
    CHECK(textin_key_for_char('-', &k) && k.vk == 0xBD && k.sc == 0x0C && !k.shift);
    CHECK(textin_key_for_char('_', &k) && k.vk == 0xBD && k.sc == 0x0C && k.shift);
    CHECK(textin_key_for_char('\'', &k) && k.vk == 0xDE && k.sc == 0x28 && !k.shift);
    CHECK(textin_key_for_char('"', &k) && k.vk == 0xDE && k.shift);
    CHECK(textin_key_for_char(':', &k) && k.vk == 0xBA && k.shift);
    CHECK(textin_key_for_char('.', &k) && k.vk == 0xBE && k.sc == 0x34 && !k.shift);
    CHECK(textin_key_for_char('?', &k) && k.vk == 0xBF && k.shift);
    CHECK(textin_key_for_char('\\', &k) && k.vk == 0xDC && !k.shift);
    CHECK(textin_key_for_char('|', &k) && k.vk == 0xDC && k.shift);
    CHECK(!textin_key_for_char(0xE9, &k));                                    /* e acute: no US key */
    CHECK(!textin_key_for_char('\n', &k));
    CHECK(!textin_key_for_char(0x7F, &k));
    /* every printable ASCII character has a key, and the key types it back */
    for (c = 32; c < 127; c++) {
        CHECK(textin_key_for_char(c, &k) == 1);
        CHECK(textin_char_for_key(k.vk, k.shift) == c);
    }
    CHECK(textin_char_for_key('A', 0) == 'a' && textin_char_for_key('A', 1) == 'A');
    CHECK(textin_char_for_key(0x20, 0) == ' ' && textin_char_for_key(0x20, 1) == ' ');
    CHECK(textin_char_for_key('7', 1) == '&' && textin_char_for_key(0xBB, 1) == '+');
    CHECK(textin_char_for_key(0x25, 0) == -1);                                 /* an arrow key types nothing */
    CHECK(textin_char_for_key(0x70, 0) == -1);
    CHECK(textin_char_for_key(0x10, 0) == -1);
}

static void test_attach(void)
{
    CHECK(textin_attach("a") == 'a');
    CHECK(textin_attach(" ") == ' ');
    CHECK(textin_attach("~") == '~');
    CHECK(textin_attach("ab") == -1);                                         /* a longer text is not one key's */
    CHECK(textin_attach("\xC3\xA9") == -1);                                   /* e acute from a dead key */
    CHECK(textin_attach("") == -1);
    CHECK(textin_attach(NULL) == -1);
    CHECK(textin_attach("\x7F") == -1);
}

static int downs(const TextOut *o) { int i, n = 0; for (i = 0; i < o->n; i++) n += o->act[i].type == TX_KEYDOWN; return n; }

static void test_type(void)
{
    TextOut o;

    /* "ab": two key presses, one character each, no Shift */
    o.n = 0;
    textin_type("ab", 0, &o);
    CHECK(o.n == 4 && o.act[0].type == TX_KEYDOWN && o.act[0].vk == 'A' && o.act[0].ch == 'a' && o.act[1].type == TX_KEYUP && o.act[1].vk == 'A');
    CHECK(o.act[2].type == TX_KEYDOWN && o.act[2].vk == 'B' && o.act[2].ch == 'b' && o.act[3].type == TX_KEYUP);
    /* a capital: Shift down, the key, the key up, Shift up */
    o.n = 0;
    textin_type("A", 0, &o);
    CHECK(o.n == 4 && o.act[0].type == TX_KEYDOWN && o.act[0].vk == VK_SHIFT_CODE && o.act[0].sc == SC_LSHIFT && o.act[0].ch == -1);
    CHECK(o.act[1].type == TX_KEYDOWN && o.act[1].vk == 'A' && o.act[1].ch == 'A' && o.act[2].type == TX_KEYUP && o.act[2].vk == 'A');
    CHECK(o.act[3].type == TX_KEYUP && o.act[3].vk == VK_SHIFT_CODE);
    /* Shift already held by the player: not pressed again, and not let go */
    o.n = 0;
    textin_type("A", 1, &o);
    CHECK(o.n == 2 && o.act[0].type == TX_KEYDOWN && o.act[0].vk == 'A' && o.act[1].type == TX_KEYUP);
    /* a name: every character once */
    o.n = 0;
    textin_type("Ned Way", 0, &o);
    CHECK(downs(&o) == 7 + 2);                                                /* seven characters, two of them with a Shift press (N, W) */
    CHECK(o.act[0].vk == VK_SHIFT_CODE && o.act[1].vk == 'N' && o.act[1].ch == 'N');
    /* every key down is paired with a key up (nothing left held) */
    {
        int i, held = 0, bad = 0;

        for (i = 0; i < o.n; i++) {
            held += o.act[i].type == TX_KEYDOWN;
            held -= o.act[i].type == TX_KEYUP;
            bad |= held < 0;
        }
        CHECK(held == 0 && !bad);
    }
    /* Latin-1 text that no US key types goes as WM_CHAR alone; other code points are skipped */
    o.n = 0;
    textin_type("\xC3\xA9", 0, &o);                                          /* U+00E9 */
    CHECK(o.n == 1 && o.act[0].type == TX_CHAR && o.act[0].ch == 0xE9);
    o.n = 0;
    textin_type("\xE2\x82\xAC", 0, &o);                                      /* the euro sign: not Latin-1 */
    CHECK(o.n == 0);
    o.n = 0;
    textin_type("\xF0\x9F\x98\x80x", 0, &o);                                 /* an emoji, then x */
    CHECK(o.n == 2 && o.act[0].vk == 'X');
    o.n = 0;
    textin_type("\xC3", 0, &o);                                              /* a cut-off sequence does not run past the end */
    CHECK(o.n == 0);
    o.n = 0;
    textin_type("a\xC3" "b", 0, &o);                                         /* a bad byte is skipped, the rest is typed */
    CHECK(downs(&o) == 2);
    /* Enter, Tab, Backspace typed as text are the keys */
    o.n = 0;
    textin_type("\n", 0, &o);
    CHECK(o.n == 2 && o.act[0].vk == 13 && o.act[0].ch == 13);
    o.n = 0;
    textin_type("\b", 0, &o);
    CHECK(o.n == 2 && o.act[0].vk == 8);
    /* NULL and empty */
    o.n = 0;
    textin_type(NULL, 0, &o);
    textin_type("", 0, &o);
    CHECK(o.n == 0);
    /* a long paste fills the buffer and stops, never overruns it */
    {
        char big[2000];

        memset(big, 'A', sizeof(big) - 1);
        big[sizeof(big) - 1] = 0;
        o.n = 0;
        textin_type(big, 0, &o);
        CHECK(o.n <= TEXT_MAX_ACTS && o.n >= TEXT_MAX_ACTS - 4);
    }
    /* appending: the second call goes after the first */
    o.n = 0;
    textin_type("a", 0, &o);
    textin_type("b", 0, &o);
    CHECK(o.n == 4 && o.act[2].vk == 'B');
}

/* PORT_PAD_LOG (padlog.h): off by default and for 0/no/off; on for anything else; the file it also goes to */
static void test_padlog(void)
{
    CHECK(!padlog_enabled(NULL) && !padlog_enabled("") && !padlog_enabled("0") && !padlog_enabled("no") && !padlog_enabled("OFF") && !padlog_enabled("false"));
    CHECK(padlog_enabled("1") && padlog_enabled("stderr") && padlog_enabled("/tmp/x.log") && padlog_enabled("yes"));
    CHECK(padlog_path_for(NULL) == NULL && padlog_path_for("0") == NULL);
    CHECK(padlog_path_for("stderr") == NULL && padlog_path_for("2") == NULL);           /* stderr only (the soak scripts read it there) */
    CHECK(!strcmp(padlog_path_for("1"), "pentamoor-input.log") && !strcmp(padlog_path_for("yes"), "pentamoor-input.log"));   /* a Deck in Game mode has no terminal: a file in the game's folder */
    CHECK(!strcmp(padlog_path_for("/home/deck/pad.txt"), "/home/deck/pad.txt") && !strcmp(padlog_path_for("C:\\x\\pad.txt"), "C:\\x\\pad.txt"));
    CHECK(!strcmp(padlog_path_for("pad.log"), "pad.log") && !strcmp(padlog_path_for("PAD.LOG"), "PAD.LOG"));
}

int main(void)
{
    test_detect();
    test_padlog();
    test_fullscreen();
    test_scale();
    test_text_wanted();
    test_keys();
    test_attach();
    test_type();
    printf("%d checks, %d failed\n", checks, failures);
    return failures ? 1 : 0;
}

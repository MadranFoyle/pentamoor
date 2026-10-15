/* test_sound.c - the sound library (sound.c): WAV loading, the mixer (volume, pan, pitch, loop), the state the game polls, and the no-device clock.
 *   make -C src/port test */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#include "plat.h"
#include "sched.h"
#include "test_util.h"
#include "wm.h"

void kernel32_init(void);
void port_index_functions(void);

static int failures, checks;
#define CHECK(c) do { checks++; if (!(c)) { failures++; printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } } while (0)

static uint32_t cursor = 0x1000000u;
static uint32_t scratch(uint32_t n) { uint32_t p = cursor; cursor += (n + 15) & ~15u; return p; }
static uint32_t cstr(const char *s) { uint32_t p = scratch((uint32_t)strlen(s) + 1); strcpy((char *)(G + p), s); return p; }

static uint32_t mod;

static uint32_t call(const char *name, int n, const uint32_t *args)
{
    uint32_t f = module_proc(mod, name), a = scratch(64), cleanup = 0;
    int i;

    for (i = 0; i < n; i++)
        WR32(a + 4 * (uint32_t)i, args[i]);
    return lift_call(f, a, &cleanup);
}

static void write_wav(const char *path, int rate, int chans, int bits, int frames, int value)
{
    FILE *f = fopen(path, "wb");
    uint32_t bytes = (uint32_t)(frames * chans * bits / 8), v;
    int i, c;

#define W32(x) do { v = (x); fwrite(&v, 4, 1, f); } while (0)
#define W16(x) do { v = (x); fwrite(&v, 2, 1, f); } while (0)
    fwrite("RIFF", 1, 4, f); W32(36 + bytes); fwrite("WAVEfmt ", 1, 8, f); W32(16); W16(1); W16((uint32_t)chans); W32((uint32_t)rate);
    W32((uint32_t)(rate * chans * bits / 8)); W16((uint32_t)(chans * bits / 8)); W16((uint32_t)bits); fwrite("data", 1, 4, f); W32(bytes);
    for (i = 0; i < frames; i++)
        for (c = 0; c < chans; c++) {
            if (bits == 16) W16((uint32_t)value & 0xFFFF);
            else { uint8_t b = (uint8_t)(128 + value / 256); fwrite(&b, 1, 1, f); }
        }
    fclose(f);
}

/* 16 bit mono 22.05 kHz: frame i holds i * 100, and a 'smpl' chunk with one loop over frames ls..le (inclusive) */
static void write_ramp(const char *path, int frames, int ls, int le)
{
    FILE *f = fopen(path, "wb");
    uint32_t v;
    int i;

#define RW32(x) do { v = (x); fwrite(&v, 4, 1, f); } while (0)
#define RW16(x) do { v = (x); fwrite(&v, 2, 1, f); } while (0)
    fwrite("RIFF", 1, 4, f); RW32(4 + 24 + 8 + (uint32_t)frames * 2 + 8 + 60); fwrite("WAVEfmt ", 1, 8, f); RW32(16); RW16(1); RW16(1); RW32(22050); RW32(44100); RW16(2); RW16(16);
    fwrite("data", 1, 4, f); RW32((uint32_t)frames * 2);
    for (i = 0; i < frames; i++)
        RW16((uint32_t)i * 100);
    fwrite("smpl", 1, 4, f); RW32(60);
    RW32(0); RW32(0); RW32(45351); RW32(60); RW32(0); RW32(0); RW32(0); RW32(1); RW32(0);          /* the header: one loop */
    RW32(0); RW32(0); RW32((uint32_t)ls); RW32((uint32_t)le); RW32(0); RW32(0);                      /* id, type, start, end, fraction, play count */
    fclose(f);
}

static uint32_t opts(uint32_t vol, uint32_t pitch, int32_t pan, uint32_t flags)
{
    uint32_t p = scratch(32);

    WR32(p, vol); WR32(p + 4, pitch); WR32(p + 8, (uint32_t)pan); WR32(p + 12, 0); WR32(p + 16, 0); WR32(p + 20, 0); WR32(p + 24, 0); WR32(p + 28, flags);
    return p;
}

static uint32_t state(uint32_t id)
{
    uint32_t out = scratch(4), args[2] = {id, out};

    WR32(out, 99);
    call("GetSndState", 2, args);
    return RD32(out);
}

int main(void)
{
    char root[300], path[300];
    int16_t out[2 * 200];
    uint32_t args[3], i;
    int sum;

    guest_init();
    sched_init();
    kernel32_init();
    port_index_functions();
    sound_install();
    test_tmpdir(root, sizeof(root), "portsound_");
    CHECK(root[0] != 0);
    snprintf(path, sizeof(path), "%s/Program", root); plat_mkdir(path);
    snprintf(path, sizeof(path), "%s/Program/Sound", root); plat_mkdir(path);
    snprintf(path, sizeof(path), "%s/Program/Sound/T.WAV", root);
    write_wav(path, 22050, 1, 16, 2205, 10000);             /* a tenth of a second at a constant level */
    snprintf(path, sizeof(path), "%s/Program/Sound/S.WAV", root);
    write_wav(path, 44100, 2, 16, 4410, -6000);             /* a 44.1 kHz stereo file */
    snprintf(path, sizeof(path), "%s/Program/Sound/E.WAV", root);
    write_wav(path, 22050, 1, 8, 2205, 0);                  /* 8 bit: silence is 128 */
    paths_init(root, root);
    mod = module_load("magsnd.dll");
    CHECK(mod != 0);

    /* load, and what the game asks of a loaded sound */
    args[0] = cstr("C:\\Magic\\Program\\Sound\\T.WAV"); args[1] = 7; args[2] = 0;
    CHECK(call("LoadSnd", 3, args) == 0);
    args[0] = cstr("C:\\Magic\\Program\\Sound\\Nothing.WAV"); args[1] = 8;
    CHECK(call("LoadSnd", 3, args) == 1);                  /* no such file: an error, as the DLL gives */
    {   /* the game's cache: a sound loaded with an info block carries the game's number for it (dword 6), IsSndLoaded finds it by that number, a taken slot keeps its
         * sound, and GetLRUSnd gives a free slot or the least played one */
        uint32_t o = scratch(4), a[3], info = scratch(32), la[3], r;

        a[0] = 7; a[1] = o; WR32(o, 99);
        CHECK(call("IsSndLoaded", 2, a) == 0 && RD32(o) == 99);                 /* slot 7 was loaded without a number: not found by one, and *o is left alone */
        la[0] = cstr("C:\\Magic\\Program\\Sound\\T.WAV"); la[1] = 40; la[2] = info;
        memset(G + info, 0, 32); WR32(info + 0x18, 0x2f);
        CHECK(call("LoadSnd", 3, la) == 0);
        a[0] = 0x2f; WR32(o, 99);
        CHECK(call("IsSndLoaded", 2, a) == 1 && RD32(o) == 40);                 /* number 0x2f is in slot 40 */
        la[0] = cstr("C:\\Magic\\Program\\Sound\\S.WAV"); la[1] = 40; la[2] = 0;
        CHECK(call("LoadSnd", 3, la) == 0);                                     /* taken: succeeds and loads nothing */
        a[0] = 40; a[1] = opts(400, 22050, 0, 0); call("PlaySnd", 2, a);
        sound_set_device(1);
        sound_mix(out, 2);
        CHECK(out[0] == 10000);                                                 /* still T.WAV (a constant 10000), not S.WAV's -6000 */
        a[0] = 40; call("StopSnd", 1, a);
        a[0] = 40; call("UnloadSnd", 1, a);
        a[0] = 0x2f; a[1] = o;
        CHECK(call("IsSndLoaded", 2, a) == 0);                                  /* gone with the unload */
        /* GetLRUSnd(*slot, lo, hi): slots 41..42 are free: the first free one; then fill them and the played-least one is the answer */
        la[0] = o; la[1] = 41; la[2] = 43; WR32(o, 99);
        r = call("GetLRUSnd", 3, la);
        CHECK(r == 1 && RD32(o) == 41);
        la[0] = cstr("C:\\Magic\\Program\\Sound\\T.WAV"); la[1] = 41; la[2] = 0; call("LoadSnd", 3, la);
        la[1] = 42; call("LoadSnd", 3, la);
        a[0] = 41; a[1] = opts(400, 22050, 0, 0); call("PlaySnd", 2, a);
        la[0] = o; la[1] = 41; la[2] = 43; WR32(o, 99);
        r = call("GetLRUSnd", 3, la);
        CHECK(r == 0 && RD32(o) == 42);                                         /* both taken; slot 42 was never played */
        a[0] = 41; call("StopSnd", 1, a);
        a[0] = 41; call("UnloadSnd", 1, a);
        a[0] = 42; call("UnloadSnd", 1, a);
    }
    CHECK(state(7) == 0);

    /* full volume, centred: both channels carry the sample */
    args[0] = 7; args[1] = opts(400, 22050, 0, 0);
    CHECK(call("PlaySnd", 2, args) == 0);
    sound_set_device(1);                                   /* a device pulls from here on: nothing consumes the sound against the clock */
    CHECK(state(7) == 1);
    sound_mix(out, 100);
    CHECK(out[0] == 10000 && out[1] == 10000 && out[198] == 10000);
    sound_mix(out, 100);
    CHECK(state(7) == 1);
    for (i = 0; i < 21; i++)                               /* 2205 frames in all */
        sound_mix(out, 100);
    CHECK(state(7) == 0);                                  /* it ended by itself */
    sound_mix(out, 4);
    CHECK(out[0] == 0);

    /* volume 200 is half; pan +400 silences the left side, -400 the right */
    args[1] = opts(200, 22050, 0, 0); call("PlaySnd", 2, args);
    sound_mix(out, 2);
    CHECK(out[0] == 5000 && out[1] == 5000);
    args[1] = opts(400, 22050, 400, 0); call("PlaySnd", 2, args);
    sound_mix(out, 2);
    CHECK(out[0] == 0 && out[1] == 10000);
    args[1] = opts(400, 22050, -400, 0); call("PlaySnd", 2, args);
    sound_mix(out, 2);
    CHECK(out[0] == 10000 && out[1] == 0);
    args[0] = 7; call("StopSnd", 1, args);
    CHECK(state(7) == 0);

    /* SetVol while playing */
    args[1] = opts(400, 22050, 0, 0); call("PlaySnd", 2, args);
    args[0] = 7; args[1] = 100; call("SetVol", 2, args);
    sound_mix(out, 2);
    CHECK(out[0] == 2500);
    args[0] = 7; call("StopSnd", 1, args);

    /* pitch: twice the rate plays twice as fast, so the sound ends in half the frames */
    args[0] = 7; args[1] = opts(400, 44100, 0, 0); call("PlaySnd", 2, args);
    for (i = 0; i < 11; i++)
        sound_mix(out, 100);                               /* 1100 device frames = 2200 source frames */
    CHECK(state(7) == 1);
    sound_mix(out, 20);
    CHECK(state(7) == 0);

    /* loop: never ends */
    args[0] = 7; args[1] = opts(400, 22050, 0, 1); call("PlaySnd", 2, args);
    for (i = 0; i < 60; i++)
        sound_mix(out, 100);
    CHECK(state(7) == 1);
    sum = out[0];
    CHECK(sum == 10000);
    args[0] = 7; call("StopSnd", 1, args);

    /* a 44.1 kHz stereo file at pitch 22050 plays at the speed it was recorded: the whole file in 2205 device frames */
    args[0] = cstr("C:\\Magic\\Program\\Sound\\S.WAV"); args[1] = 9; args[2] = 0; call("LoadSnd", 3, args);
    args[0] = 9; args[1] = opts(400, 22050, 0, 0); call("PlaySnd", 2, args);
    sound_mix(out, 100);
    CHECK(out[0] == -6000 && out[1] == -6000);
    for (i = 0; i < 22; i++)
        sound_mix(out, 100);
    CHECK(state(9) == 0);

    /* 8 bit: 128 is silence */
    args[0] = cstr("C:\\Magic\\Program\\Sound\\E.WAV"); args[1] = 10; args[2] = 0; call("LoadSnd", 3, args);
    args[0] = 10; args[1] = opts(400, 22050, 0, 0); call("PlaySnd", 2, args);
    sound_mix(out, 4);
    CHECK(out[0] == 0);

    /* mixed sounds add, and the sum is clamped */
    args[0] = 7; args[1] = opts(400, 22050, 0, 0); call("PlaySnd", 2, args);
    for (i = 0; i < 3; i++) {                              /* three more voices of the same file in other slots */
        args[0] = cstr("C:\\Magic\\Program\\Sound\\T.WAV"); args[1] = 20 + i; args[2] = 0; call("LoadSnd", 3, args);
        args[0] = 20 + i; args[1] = opts(400, 22050, 0, 0); call("PlaySnd", 2, args);
    }
    sound_mix(out, 2);
    CHECK(out[0] == 32767);                                /* 4 x 10000, clamped */
    args[0] = 0; call("StopAllSnds", 0, args);
    CHECK(state(7) == 0 && state(20) == 0);

    /* no device: the sound is consumed against the clock, so the game's wait for it to end ends */
    sound_set_device(0);
    args[0] = 7; args[1] = opts(400, 22050, 0, 0); call("PlaySnd", 2, args);
    CHECK(state(7) == 1);
    usleep(250000);
    CHECK(state(7) == 0);                                  /* a tenth of a second long */

    /* the loop region of a file (its 'smpl' chunk, the game's markers): a looping voice plays on to the end of the loop and goes round it; one that does not loop
     * plays the whole file; the marker calls answer as the DLL does and PlaySndMarker starts again at the loop's start */
    sound_set_device(1);
    snprintf(path, sizeof(path), "%s/Program/Sound/R.WAV", root);
    write_ramp(path, 200, 50, 149);                         /* frames 0..199, the loop 50..149 */
    args[0] = cstr("C:\\Magic\\Program\\Sound\\R.WAV"); args[1] = 30; args[2] = 0; CHECK(call("LoadSnd", 3, args) == 0);
    args[0] = 30; args[1] = opts(400, 22050, 0, 1); call("PlaySnd", 2, args);
    {
        int16_t big[2 * 400];

        sound_mix(big, 400);
        CHECK(big[2 * 149] == 14900 && big[2 * 150] == 5000 && big[2 * 199] == 9900 && big[2 * 200] == 10000);   /* ...149, then round to 50, 51, ... */
        CHECK(big[2 * 250] == 5000 + 0 && state(30) == 1);                                                           /* (250 - 150) % 100 + 50 = 50 */
    }
    {
        uint32_t m[2];

        m[0] = 30; m[1] = 1; CHECK(call("SetSndMarker", 2, m) == 0);
        m[1] = 2; CHECK(call("SetSndMarker", 2, m) == 5);          /* the file has one loop */
        m[0] = 31; m[1] = 1; CHECK(call("SetSndMarker", 2, m) == 1);   /* nothing loaded there */
        m[0] = 7; m[1] = 1; CHECK(call("SetSndMarker", 2, m) == 5);    /* a sound with no loop */
        m[0] = 30; m[1] = 1; CHECK(call("PlaySndMarker", 2, m) == 0);
        sound_mix(out, 4);
        CHECK(out[0] == 5000 && out[2] == 5100);                    /* it starts again at the loop's start */
    }
    args[0] = 30; call("StopSnd", 1, args);
    args[0] = 30; args[1] = opts(400, 22050, 0, 0); call("PlaySnd", 2, args);          /* not looping: the whole file, then it ends */
    {
        int16_t big[2 * 250];

        sound_mix(big, 250);
        CHECK(big[2 * 199] == 19900 && state(30) == 0);
    }

    printf("%d checks, %d failed\n", checks, failures);
    return failures ? 1 : 0;
}

int pe_find_resource(uint32_t hinst, uint32_t type, uint32_t name, uint32_t *addr, uint32_t *size)
{
    (void)hinst; (void)type; (void)name; (void)addr; (void)size;
    return 0;
}

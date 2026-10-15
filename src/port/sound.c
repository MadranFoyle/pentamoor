/* sound.c - the game's sound library, MAGSND.DLL, as C functions and a mixer. The DLL needs DirectSound, the multimedia file I/O and AVIFile, none of
 * which exist here, so every export is provided (cdecl, 0 means success, an answer is written through a pointer argument) and the sounds are played by a
 * mixer that the front end's audio device pulls from (front_sdl.c). Port of winemu/magsnd.py, which only played; this one also mixes.
 *
 * The slot numbers and the option block are the game's: LoadSnd(path, id, info) reads a WAV into slot `id`; PlaySnd(id, opts) plays it, with opts = 8 dwords:
 * [0] volume 0..400, [1] pitch (the playback rate, 22050 = as recorded), [2] pan -400..400, [7] flags: bit 0 loops. A slot plays one voice at a time.
 * The game waits for a sound to end by polling GetSndState until it says "stopped", so a sound has to end whether or not a device is pulling samples: with
 * no device (headless, or SDL's audio would not open) the sounds are consumed against the clock instead. */
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "port.h"

#define P(a) ((const char *)(G + (uint32_t)(a)))
#define SLOTS 1024
#define STREAMS 4                /* voices after the game's slots, for the movies' sound (sound_stream_start) */
#define DEVICE_RATE 22050
#define MAX_VOLUME 400.0

#define MAX_LOOPS 16
typedef struct Sound {
    int16_t *pcm;                /* interleaved, `channels` per frame */
    uint32_t frames, rate;
    int channels;
    uint32_t gid;                /* the game's own number for the sound (the info block's dword 6, set by LoadSnd): IsSndLoaded looks sounds up by it */
    uint32_t plays;              /* how often PlaySnd started it: GetLRUSnd evicts the one played least */
    int nloops;                  /* the sampler loops of the file's 'smpl' chunk: the game's "markers" (SetSndMarker, PlaySndMarker) */
    uint32_t loop_start[MAX_LOOPS], loop_end[MAX_LOOPS];     /* in frames; the end is the first frame after the loop */
} Sound;

typedef struct Voice {
    int playing, loop, started;
    double pos;                  /* in source frames */
    double step;                 /* source frames per device frame */
    double volume, pan;
    uint32_t pitch;
} Voice;

static Sound sounds[SLOTS + STREAMS];
static Voice voices[SLOTS + STREAMS];
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static int device_on;
static double last_pump;

static double wall(void)
{
    struct timespec ts;

    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

/* ---- WAV files ------------------------------------------------------------------------------------------------------------------ */
static uint32_t le32(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static uint32_t le16(const uint8_t *p) { return (uint32_t)p[0] | (uint32_t)p[1] << 8; }

/* PCM WAV (8 or 16 bit, any channel count the game uses: 1 or 2) into a Sound; returns 0 if it is anything else. */
static int wav_parse(const uint8_t *d, size_t n, Sound *out)
{
    size_t at = 12;
    uint32_t rate = 0, bits = 0, chans = 0, tag = 0;
    const uint8_t *data = NULL, *smpl = NULL;
    size_t data_len = 0, smpl_len = 0;

    if (n < 12 || memcmp(d, "RIFF", 4) || memcmp(d + 8, "WAVE", 4))
        return 0;
    while (at + 8 <= n) {
        uint32_t len = le32(d + at + 4);
        size_t body = at + 8;

        if (!memcmp(d + at, "fmt ", 4) && body + 16 <= n) {
            tag = le16(d + body); chans = le16(d + body + 2); rate = le32(d + body + 4); bits = le16(d + body + 14);
        } else if (!memcmp(d + at, "data", 4)) {
            data = d + body;
            data_len = body + len > n ? n - body : len;           /* a file cut short plays what is there */
        } else if (!memcmp(d + at, "smpl", 4) && body + len <= n) {
            smpl = d + body;
            smpl_len = len;
        }
        at = body + len + (len & 1);
    }
    if (!data || tag != 1 || (bits != 8 && bits != 16) || (chans != 1 && chans != 2) || !rate)
        return 0;
    {
        uint32_t bytes = bits / 8, frames = (uint32_t)(data_len / (bytes * chans)), i;
        int16_t *pcm = malloc((size_t)frames * chans * sizeof(int16_t) + 2);

        if (!pcm)
            return 0;
        for (i = 0; i < frames * chans; i++)
            pcm[i] = bits == 16 ? (int16_t)le16(data + 2 * (size_t)i) : (int16_t)(((int)data[i] - 128) << 8);
        out->pcm = pcm; out->frames = frames; out->rate = rate; out->channels = (int)chans;
        if (smpl && smpl_len >= 36) {                          /* the loops: 24 bytes each after the 36-byte header (id, type, start, end, fraction, play count) */
            uint32_t k, count = le32(smpl + 28);

            for (k = 0; k < count && k < MAX_LOOPS && 36 + 24 * (size_t)(k + 1) <= smpl_len; k++) {
                uint32_t ls = le32(smpl + 36 + 24 * (size_t)k + 8), le = le32(smpl + 36 + 24 * (size_t)k + 12) + 1;

                if (le > frames)
                    le = frames;
                if (ls >= le)
                    break;
                out->loop_start[out->nloops] = ls;
                out->loop_end[out->nloops++] = le;
            }
        }
    }
    return 1;
}

static void free_sound(uint32_t id)
{
    free(sounds[id].pcm);
    sounds[id] = (Sound){0};
    voices[id].playing = 0;
}

/* ---- the mixer ---------------------------------------------------------------------------------------------------------------- */
/* Adds the playing voices into `acc` (interleaved stereo, 32 bit) for `frames` device frames. */
static void mix_into(int32_t *acc, int frames)
{
    int id;

    for (id = 0; id < SLOTS + STREAMS; id++) {
        Voice *v = &voices[id];
        Sound *s = &sounds[id];
        double left, right;
        int f;

        if (!v->playing || !s->pcm || !s->frames)
            continue;
        left = v->pan > 0 ? 1.0 - v->pan : 1.0;               /* pan -1..1: the far side is turned down */
        right = v->pan < 0 ? 1.0 + v->pan : 1.0;
        left *= v->volume; right *= v->volume;
        for (f = 0; f < frames && v->playing; f++) {
            uint32_t i0 = (uint32_t)v->pos, i1 = i0 + 1;
            double frac = v->pos - (double)i0, l, r;

            {   /* a looping voice plays on to the end of the file's first loop and goes round that loop; a file with none (or a non-looping voice) uses the whole file */
                uint32_t end = v->loop && s->nloops ? s->loop_end[0] : s->frames, back = v->loop && s->nloops ? s->loop_start[0] : 0;

                if (i0 >= end) {
                    if (!v->loop) { v->playing = 0; break; }
                    v->pos -= (double)(end - back);
                    i0 = (uint32_t)v->pos; i1 = i0 + 1; frac = v->pos - (double)i0;
                }
                if (i1 >= end)
                    i1 = v->loop ? back : i0;
            }
            if (s->channels == 1) {
                l = r = s->pcm[i0] * (1.0 - frac) + s->pcm[i1] * frac;
            } else {
                l = s->pcm[2 * i0] * (1.0 - frac) + s->pcm[2 * i1] * frac;
                r = s->pcm[2 * i0 + 1] * (1.0 - frac) + s->pcm[2 * i1 + 1] * frac;
            }
            acc[2 * f] += (int32_t)(l * left);
            acc[2 * f + 1] += (int32_t)(r * right);
            v->pos += v->step;
        }
    }
}

/* The audio device's callback: `out` gets `frames` stereo frames of signed 16 bit samples. */
void sound_mix(int16_t *out, int frames)
{
    int32_t *acc = calloc((size_t)frames * 2, sizeof(int32_t));
    int i;

    if (!acc) {
        memset(out, 0, (size_t)frames * 4);
        return;
    }
    pthread_mutex_lock(&lock);
    mix_into(acc, frames);
    pthread_mutex_unlock(&lock);
    for (i = 0; i < frames * 2; i++)
        out[i] = (int16_t)(acc[i] > 32767 ? 32767 : acc[i] < -32768 ? -32768 : acc[i]);
    free(acc);
}

void sound_set_device(int on) { pthread_mutex_lock(&lock); device_on = on; last_pump = wall(); pthread_mutex_unlock(&lock); }
int sound_rate(void) { return DEVICE_RATE; }

/* With no device nothing pulls samples: the sounds are consumed against the clock so that they end when they would have. Call with the lock held. */
static void pump_locked(void)
{
    double now = wall(), dt = now - last_pump;

    last_pump = now;
    if (device_on || dt <= 0)
        return;
    while (dt > 0) {
        int frames = (int)(dt * DEVICE_RATE), chunk;
        int32_t acc[2 * 2048];

        if (frames <= 0)
            break;
        chunk = frames > 2048 ? 2048 : frames;
        memset(acc, 0, sizeof(acc));
        mix_into(acc, chunk);
        dt -= (double)chunk / DEVICE_RATE;
    }
}

/* A sound that is not the game's own (the sound of a movie): plays at once, as recorded, and the mixer owns the samples (16 bit, interleaved if stereo) from
 * here on. Returns a voice to stop it with, or -1 if they are all busy. */
static void set_pitch(Voice *v, const Sound *s, uint32_t pitch);
int sound_stream_start(int16_t *pcm, uint32_t frames, uint32_t rate, int channels)
{
    int k, id = -1;

    pthread_mutex_lock(&lock);
    pump_locked();
    for (k = 0; k < STREAMS; k++)
        if (!voices[SLOTS + k].playing) {
            id = SLOTS + k;
            break;
        }
    if (id < 0) {
        pthread_mutex_unlock(&lock);
        free(pcm);
        return -1;
    }
    free_sound((uint32_t)id);
    sounds[id] = (Sound){.pcm = pcm, .frames = frames, .rate = rate, .channels = channels};
    voices[id] = (Voice){0};
    voices[id].volume = 1.0;
    voices[id].pos = 0;
    set_pitch(&voices[id], &sounds[id], 22050);
    voices[id].playing = 1;
    pthread_mutex_unlock(&lock);
    return id;
}

void sound_stream_stop(int id)
{
    if (id < SLOTS || id >= SLOTS + STREAMS)
        return;
    pthread_mutex_lock(&lock);
    free_sound((uint32_t)id);
    pthread_mutex_unlock(&lock);
}

static void set_pitch(Voice *v, const Sound *s, uint32_t pitch)
{
    v->pitch = pitch;
    v->step = (double)s->rate / DEVICE_RATE * (pitch ? (double)pitch / 22050.0 : 1.0);     /* pitch 22050 is the rate as recorded */
}

/* ---- the exports ---------------------------------------------------------------------------------------------------------------- */
static void out32(uint32_t ptr, uint32_t v)
{
    if (ptr > 0xFFFF)
        WR32(ptr, v);
}

static int is_loaded(uint32_t id);
static uint32_t snd_load(const uint32_t *a)             /* LoadSnd(path, id, info) */
{
    char host[1200];
    FILE *f;
    uint8_t *d;
    long n;
    Sound s = {0};

    if (a[1] >= SLOTS)
        return 5;
    if (is_loaded(a[1])) {                                    /* the DLL does nothing for a slot that is taken: the sound there stays, and the call succeeds */
        port_trace("magsnd: LoadSnd slot %u is taken: %s not loaded", a[1], a[0] ? P(a[0]) : "(null)");
        return 0;
    }
    if (!a[0] || !paths_host(P(a[0]), 0, host, sizeof(host)))
        return 1;
    f = fopen(host, "rb");
    if (!f)
        return 1;
    fseek(f, 0, SEEK_END);
    n = ftell(f);
    fseek(f, 0, SEEK_SET);
    d = malloc((size_t)n + 1);
    if (!d || fread(d, 1, (size_t)n, f) != (size_t)n) {
        free(d);
        fclose(f);
        return 1;
    }
    fclose(f);
    port_trace("magsnd: LoadSnd slot %u <- %s", a[1], host);
    if (!wav_parse(d, (size_t)n, &s))
        port_trace("magsnd: %s is not a WAV this mixer can play (it stays silent)", host);
    free(d);
    pthread_mutex_lock(&lock);
    free_sound(a[1]);
    sounds[a[1]] = s;
    if (a[2] > 0xFFFF)
        sounds[a[1]].gid = RD32(a[2] + 0x18);
    if (!s.pcm)
        sounds[a[1]].rate = 22050;               /* "loaded", with nothing to play */
    sounds[a[1]].channels = s.pcm ? s.channels : 1;
    pthread_mutex_unlock(&lock);
    return 0;
}

static int is_loaded(uint32_t id) { return id < SLOTS && (sounds[id].pcm || sounds[id].rate); }

static void start(uint32_t id, const uint32_t *block)
{
    Voice *v = &voices[id];
    Sound *s = &sounds[id];
    uint32_t vol = block[0], pitch = block[1], flags = block[7];
    int32_t pan = (int32_t)block[2];

    v->volume = (vol > 400 ? 400.0 : (double)vol) / MAX_VOLUME;
    v->pan = (pan > 400 ? 400 : pan < -400 ? -400 : pan) / MAX_VOLUME;
    v->loop = (flags & 1) != 0;
    v->pos = 0;
    set_pitch(v, s, pitch);
    v->started = 1;
    v->playing = s->pcm != NULL;
}

static uint32_t snd_play(const uint32_t *a)             /* PlaySnd(id, opts) */
{
    uint32_t block[8] = {400, 22050, 0, 0, 0, 0, 0, 0}, i;

    if (a[0] >= SLOTS)
        return 1;
    if (a[1] > 0xFFFF)
        for (i = 0; i < 8; i++)
            block[i] = RD32(a[1] + 4 * i);
    port_trace("magsnd: PlaySnd slot %u volume %u pitch %u pan %d flags 0x%x", a[0], block[0], block[1], (int)block[2], block[7]);
    pthread_mutex_lock(&lock);
    pump_locked();
    if (is_loaded(a[0])) {
        start(a[0], block);
        sounds[a[0]].plays++;
    }
    pthread_mutex_unlock(&lock);
    return 0;
}

static uint32_t snd_play_file(const uint32_t *a)        /* PlaySndFile(path, id, opts) */
{
    uint32_t args[2];

    if (snd_load(a))
        return 1;
    args[0] = a[1];
    args[1] = a[2];
    return snd_play(args);
}

static uint32_t snd_stop(const uint32_t *a)
{
    pthread_mutex_lock(&lock);
    if (a[0] < SLOTS)
        voices[a[0]].playing = 0;
    pthread_mutex_unlock(&lock);
    return 0;
}

static uint32_t snd_stop_all(const uint32_t *a)
{
    int i;

    (void)a;
    pthread_mutex_lock(&lock);
    for (i = 0; i < SLOTS; i++)
        voices[i].playing = 0;
    pthread_mutex_unlock(&lock);
    return 0;
}

static uint32_t snd_unload(const uint32_t *a)
{
    port_trace("magsnd: UnloadSnd slot %u", a[0]);
    pthread_mutex_lock(&lock);
    if (a[0] < SLOTS)
        free_sound(a[0]);
    pthread_mutex_unlock(&lock);
    return 0;
}

static uint32_t snd_unload_all(const uint32_t *a)
{
    uint32_t i;

    (void)a;
    pthread_mutex_lock(&lock);
    for (i = 0; i < SLOTS; i++)
        free_sound(i);
    pthread_mutex_unlock(&lock);
    return 0;
}

static uint32_t snd_set_vol(const uint32_t *a)          /* SetVol(id, volume 0..400) */
{
    int32_t v = (int32_t)a[1];

    pthread_mutex_lock(&lock);
    if (a[0] < SLOTS)
        voices[a[0]].volume = (v < 0 ? 0 : v > 400 ? 400 : v) / MAX_VOLUME;
    pthread_mutex_unlock(&lock);
    return 0;
}

static uint32_t snd_set_pan(const uint32_t *a)          /* SetPan(id, -400..400) */
{
    int32_t v = (int32_t)a[1];

    pthread_mutex_lock(&lock);
    if (a[0] < SLOTS)
        voices[a[0]].pan = (v < -400 ? -400 : v > 400 ? 400 : v) / MAX_VOLUME;
    pthread_mutex_unlock(&lock);
    return 0;
}

static uint32_t snd_set_pitch(const uint32_t *a)        /* SetPitch(id, rate) */
{
    pthread_mutex_lock(&lock);
    if (a[0] < SLOTS && sounds[a[0]].rate)
        set_pitch(&voices[a[0]], &sounds[a[0]], a[1]);
    pthread_mutex_unlock(&lock);
    return 0;
}

/* SetSndMarker(id, n): arm the sound's loop n (1-based); the DLL answers 1 for a sound that is not loaded and 5 for a marker the file does not have. The loop itself is
 * taken from the file when the sound plays (a looping voice goes round the first loop), so there is nothing more to do. */
static uint32_t snd_set_marker(const uint32_t *a)
{
    uint32_t r;

    if (a[0] >= 0x100)
        return 5;
    pthread_mutex_lock(&lock);
    r = !is_loaded(a[0]) ? 1 : (!sounds[a[0]].nloops || (int)a[1] > sounds[a[0]].nloops || a[1] == 0) ? 5 : 0;
    pthread_mutex_unlock(&lock);
    return r;
}

/* PlaySndMarker(id, n): the sound starts again at the start of its loop n, with the volume, pan and pitch it had and looping as it was asked to (the DLL stops
 * the voice and plays a second buffer positioned there). */
static uint32_t snd_play_marker(const uint32_t *a)
{
    uint32_t r = 0;

    if (a[0] >= 0x100 || a[1] > 0x10)
        return 5;
    pthread_mutex_lock(&lock);
    pump_locked();
    if (!is_loaded(a[0])) {
        r = 1;
    } else if (!sounds[a[0]].nloops || (int)a[1] > sounds[a[0]].nloops || a[1] == 0) {
        r = 5;
    } else {
        Voice *v = &voices[a[0]];
        Sound *s = &sounds[a[0]];

        if (!v->started) {                                  /* never played: the defaults of PlaySnd, looping */
            uint32_t block[8] = {400, 22050, 0, 0, 0, 0, 0, 1};

            start(a[0], block);
        }
        v->pos = (double)s->loop_start[a[1] - 1];
        v->playing = s->pcm != NULL;
    }
    pthread_mutex_unlock(&lock);
    return r;
}

static uint32_t snd_state(const uint32_t *a)            /* GetSndState(id, *state): 0 stopped, 1 playing */
{
    int playing;

    pthread_mutex_lock(&lock);
    pump_locked();
    playing = a[0] < SLOTS && voices[a[0]].playing;
    pthread_mutex_unlock(&lock);
    out32(a[1], (uint32_t)playing);
    return 0;
}

/* IsSndLoaded(gid, *slot): 1 and the slot if a sound that was loaded with that number of the game's is there, else 0 (and *slot is left alone). The game keeps its
 * on-demand sound effects (0x14 and up) in a few slots this way. */
static uint32_t snd_is_loaded(const uint32_t *a)
{
    uint32_t k, found = 0, slot = 0;

    if ((int32_t)a[0] > 0) {
        pthread_mutex_lock(&lock);
        for (k = 0; k < SLOTS && !found; k++)
            if (is_loaded(k) && sounds[k].gid == a[0]) {
                found = 1;
                slot = k;
            }
        pthread_mutex_unlock(&lock);
    }
    if (found)
        out32(a[1], slot);
    return found;
}

/* GetLRUSnd(*slot, lo, hi): a free slot in lo..hi-1 (answer 1), else the slot of the sound in that range that was played least (answer 0: the caller unloads it).
 * A range that is empty or past 0xff means all slots. */
static uint32_t snd_get_lru(const uint32_t *a)
{
    int32_t lo = (int32_t)a[1], hi = (int32_t)a[2], k;
    uint32_t least = 0xFFFFFFFFu, pick = 0, answer = 0;

    if (hi == 0 || hi <= lo || hi > 0xff) {
        lo = 0;
        hi = 0xff;
    }
    pthread_mutex_lock(&lock);
    for (k = lo; k < hi; k++) {
        if (!is_loaded((uint32_t)k)) {
            pick = (uint32_t)k;
            answer = 1;
            break;
        }
        if (sounds[k].plays < least) {
            least = sounds[k].plays;
            pick = (uint32_t)k;
        }
    }
    pthread_mutex_unlock(&lock);
    out32(a[0], pick);
    return answer;
}

static uint32_t snd_get_vol(const uint32_t *a)
{
    out32(a[1], a[0] < SLOTS ? (uint32_t)(voices[a[0]].volume * MAX_VOLUME + 0.5) : 0);
    return 0;
}

static uint32_t snd_get_pan(const uint32_t *a)
{
    out32(a[1], a[0] < SLOTS ? (uint32_t)(int32_t)(voices[a[0]].pan * MAX_VOLUME) : 0);
    return 0;
}

static uint32_t snd_get_pitch(const uint32_t *a)
{
    out32(a[1], a[0] < SLOTS ? voices[a[0]].pitch : 0);
    return 0;
}

static uint32_t snd_get_time(const uint32_t *a)         /* GetSndTime(id, *milliseconds into the sound) */
{
    uint32_t ms = 0;

    pthread_mutex_lock(&lock);
    if (a[0] < SLOTS && sounds[a[0]].rate)
        ms = (uint32_t)(voices[a[0]].pos * 1000.0 / sounds[a[0]].rate);
    pthread_mutex_unlock(&lock);
    out32(a[1], ms);
    return 0;
}

static uint32_t accept(const uint32_t *a) { (void)a; return 0; }

static const HostExport MAGSND[] = {
    {"InitSnd", 1, accept}, {"ReleaseSnd", 2, snd_unload_all}, {"LoadSnd", 3, snd_load}, {"UnloadSnd", 4, snd_unload}, {"UnloadAllSnds", 5, snd_unload_all},
    {"PlaySnd", 6, snd_play}, {"PlaySndFile", 7, snd_play_file}, {"StopSnd", 8, snd_stop}, {"StopAllSnds", 9, snd_stop_all}, {"PlayMidiFile", 10, accept},
    {"SetPitch", 11, snd_set_pitch}, {"GetPitch", 12, snd_get_pitch}, {"SetVol", 13, snd_set_vol}, {"GetVol", 14, snd_get_vol}, {"SetPan", 15, snd_set_pan},
    {"GetPan", 16, snd_get_pan}, {"UpdateSnd", 17, accept}, {"SetSndMarker", 18, snd_set_marker}, {"PlaySndMarker", 19, snd_play_marker}, {"GetSndTime", 20, snd_get_time},
    {"ResetSnd", 21, accept}, {"GetSndState", 22, snd_state}, {"GetAVISndBuff", 23, accept}, {"ReleaseAVISndBuff", 24, accept}, {"GetSndHWND", 25, accept},
    {"IsSndLoaded", 26, snd_is_loaded}, {"GetLRUSnd", 27, snd_get_lru},
    {0, 0, 0},
};

void sound_install(void) { module_register_host("magsnd.dll", MAGSND); }

/* video.c - the game's video library, MAGVID.DLL, as C functions (the statistics window, STATWIN.DLL, plays the ending movie with it), and the MCI window the coin
 * toss plays its movie in. Port of winemu/movie.py (the MAGVID half and the MCI half): a movie is a window (movie.c) that shows its frames on the clock.
 * A movie this host cannot decode (Indeo 4 without ffmpeg) is "cannot load": LoadAVI says 4 and the game carries on without it. */
#include <string.h>
#include <unistd.h>

#include "gdi.h"
#include "movie.h"
#include "port.h"

#define P(a) ((const char *)(G + (uint32_t)(a)))
#define VID_SLOTS 3                                                          /* the DLL's own limit: handles are 0..2 */

static uint32_t slots[VID_SLOTS];                                            /* the window of each loaded movie, 0 if free */

static uint32_t accept(const uint32_t *a) { (void)a; return 0; }
static uint32_t one(const uint32_t *a) { (void)a; return 1; }

/* DrawDibDraw(hdd, hdc, xDst, yDst, dxDst, dyDst, lpbi, lpBits, xSrc, ySrc, dxSrc, dySrc, flags): a DIB onto a device context. STATWIN.DLL draws
 * the wizard statistics screen with it. Drawn unstretched (a source size of -1 means the whole DIB); the stretch the call allows is not done. */
static uint32_t drawdib_draw(const uint32_t *a)
{
    uint32_t bmi = a[6], bits = a[7], size, args[12];
    int32_t w, h, bpp, ncol, sw = (int32_t)a[10], sh = (int32_t)a[11];

    if (!bmi)
        return 0;
    size = RD32(bmi);
    w = (int32_t)RD32(bmi + 4);
    h = (int32_t)RD32(bmi + 8);
    bpp = (int32_t)RD16(bmi + 14);
    if (h < 0)
        h = -h;
    ncol = (int32_t)RD32(bmi + 32);
    if (!ncol && bpp <= 8)
        ncol = 1 << bpp;
    if (!bits)                                                  /* the pixels follow the header and its colour table */
        bits = bmi + size + 4 * (uint32_t)ncol;
    if (sw <= 0)
        sw = w;
    if (sh <= 0)
        sh = h;
    args[0] = a[1]; args[1] = a[2]; args[2] = a[3]; args[3] = (uint32_t)sw; args[4] = (uint32_t)sh;
    args[5] = a[8]; args[6] = (uint32_t)(h - (int32_t)a[9] - sh); args[7] = 0; args[8] = (uint32_t)h;     /* ySrc counts from the top; the DIB is bottom-up */
    args[9] = bits; args[10] = bmi; args[11] = 0;
    return gdi_set_dibits_to_device(args);
}

static Movie *open_guest_path(uint32_t path)
{
    char host[1200];

    if (path <= 0xFFFF || !paths_host(P(path), 0, host, sizeof(host)))
        return NULL;
    return movie_open(host);
}

/* LoadAVI(path, *slot, *short pos[2], flags) -> 0, or 3 (no free slot), 4 (cannot be decoded here), 5 (no such file) */
static uint32_t load_avi(const uint32_t *a)
{
    int free_slot, x, y;
    char host[1200];
    Movie *m;
    Window *w;

    for (free_slot = 0; free_slot < VID_SLOTS && slots[free_slot]; free_slot++)
        ;
    if (free_slot == VID_SLOTS)
        return 3;
    if (a[0] <= 0xFFFF || !paths_host(P(a[0]), 0, host, sizeof(host)) || access(host, R_OK) != 0) {
        port_trace("magvid: LoadAVI %s: no such file", a[0] > 0xFFFF ? P(a[0]) : "(null)");
        return 5;
    }
    m = movie_open(host);
    if (!m) {
        port_trace("magvid: LoadAVI %s: cannot be decoded here (Indeo 4 needs ffmpeg)", host);
        return 4;
    }
    if (!(a[3] & 2)) {                                                       /* at the given position (the game moves it with SetVidPos as well) */
        x = a[2] > 0xFFFF ? (int16_t)(RD32(a[2]) & 0xFFFF) : 0;
        y = a[2] > 0xFFFF ? (int16_t)(RD32(a[2]) >> 16) : 0;
    } else {                                                                 /* flag 2: centred on the screen */
        x = (screen_w - movie_width(m)) / 2;
        y = (screen_h - movie_height(m)) / 2;
    }
    w = movie_window("VIDWINCLASS", 0, 0x90000000u, x, y, m);
    w->visible = 0;                                                          /* nothing is drawn until PlayAVI (the clips that lie over the statistics window start with their figure) */
    slots[free_slot] = w->hwnd;
    if (a[1] > 0xFFFF)
        WR32(a[1], (uint32_t)free_slot);
    port_trace("magvid: LoadAVI %s -> slot %d at %d,%d %dx%d flags %u", host, free_slot, x, y, movie_width(m), movie_height(m), a[3]);
    return 0;
}

static Window *slot_window(uint32_t handle) { return handle < VID_SLOTS && slots[handle] ? wm_window(slots[handle]) : NULL; }

static uint32_t play_avi(const uint32_t *a)
{
    Window *w = slot_window(a[0]);

    if (w) {
        port_trace("magvid: PlayAVI %u", a[0]);
        w->visible = 1;
        movie_window_play(w);
    }
    return 0;
}

static uint32_t stop_avi(const uint32_t *a)
{
    Window *w = slot_window(a[0]);

    if (w)
        movie_window_stop(w);
    return 0;
}

static uint32_t unload_avi(const uint32_t *a)
{
    Window *w = slot_window(a[0]);

    if (w) {
        wm_destroy(w->hwnd);
        slots[a[0]] = 0;
        port_trace("magvid: UnloadAVI %u", a[0]);
    }
    return 0;
}

/* SetVidPos(handle, short pos[2]): the video's corner on the screen (the statistics window gives its own origin plus the place of the picture in it) */
static uint32_t set_vid_pos(const uint32_t *a)
{
    Window *w = slot_window(a[0]);

    if (w && a[1] > 0xFFFF) {
        uint32_t p = RD32(a[1]);

        movie_window_move(w, (int16_t)(p & 0xFFFF), (int16_t)(p >> 16));
        port_trace("magvid: SetVidPos %u -> %d,%d", a[0], w->x, w->y);
    }
    return 0;
}

/* SetVidTransparency(handle, on): the clips of the spells and the wizards are figures on black; with this on the black is see-through, so the room shows
 * behind them. (Off: the picture is a plain rectangle, as the death animations of the wizards, which are whole rooms.) */
static uint32_t set_vid_transparency(const uint32_t *a)
{
    Window *w = slot_window(a[0]);

    if (w) {
        movie_window_set_transparent(w, (int)a[1] != 0);
        port_trace("magvid: SetVidTransparency %u %u", a[0], a[1]);
    }
    return 0;
}

/* DrawVidBackground(handle): paints the background again where the video is. The statistics window does it when a clip is done, and a see-through clip (a
 * figure over the window's own picture) is gone then; the clips that are whole rooms stay as their last picture, which is the room.
 * The window is kept (visible, undrawn): STATWIN waits for a click or a key after the last clip with a PeekMessage loop on its own thread, and the only
 * windows of that thread are these, so with the window gone nothing could ever end the wait (a won duel hung on a black screen). */
static uint32_t draw_vid_background(const uint32_t *a)
{
    Window *w = slot_window(a[0]);

    if (w && movie_window_alpha(w) && !movie_window_playing(w)) {
        movie_window_set_held(w, 1);                                         /* not drawn; the window itself stays (see the comment above) */
        port_trace("magvid: DrawVidBackground %u hides the clip", a[0]);
    }
    return 0;
}

/* VidStatus(handle): 1 while the movie plays, 0 when it is over or the slot is empty, 2 for a bad handle */
static uint32_t vid_status(const uint32_t *a)
{
    if (a[0] >= VID_SLOTS)
        return 2;
    return movie_window_playing(slot_window(a[0])) ? 1 : 0;
}

static const HostExport MAGVID[] = {
    {"InitVid", 1, accept}, {"ReleaseVid", 2, accept}, {"LoadAVI", 3, load_avi}, {"UnloadAVI", 4, unload_avi}, {"PlayAVI", 5, play_avi}, {"StopAVI", 6, stop_avi},
    {"SetVidCallBack", 7, accept}, {"SetVidBackground", 8, accept}, {"SetVidBackgroundToBMP", 9, accept}, {"SetVidBackgroundToDIB", 10, accept},
    {"DrawVidBackground", 11, draw_vid_background}, {"PasteToVidBackground", 12, accept}, {"SetVidForeground", 13, accept}, {"PaintVid", 14, accept},
    {"SetVidPos", 15, set_vid_pos}, {"VidStatus", 16, vid_status}, {"LinkVids", 17, accept}, {"SetVidThreadPriority", 18, accept},
    {"SetVidTransparency", 19, set_vid_transparency}, {"_delay", 20, accept},
    {0, 0, 0},
};

/* MCIWndCreateA(parent, instance, style, path), the coin toss's movie window (cdecl): a child window the size of the movie, which the game then sends
 * MCI_PLAY and WM_CLOSE. 0 if there is no such movie or this host cannot play it. */
static uint32_t mciwnd_create(const uint32_t *a)
{
    Movie *m = open_guest_path(a[3]);
    Window *w;

    if (!m) {
        port_trace("MCIWndCreate(%s): no movie this host can play", a[3] > 0xFFFF ? P(a[3]) : "(null)");
        return 0;
    }
    w = movie_window("MCIWndClass", a[0], a[2], 0, 0, m);
    port_trace("MCIWndCreate: %s %dx%d, %d frames at %g fps", P(a[3]), movie_width(m), movie_height(m), movie_frames(m), movie_fps(m));
    return w->hwnd;
}

const WinApi VIDEO_APIS[] = {
    {"msvfw32.dll", "MCIWndCreateA", mciwnd_create}, {"msvfw32.dll", "DrawDibOpen", one}, {"msvfw32.dll", "DrawDibClose", one}, {"msvfw32.dll", "DrawDibDraw", drawdib_draw},
    {0, 0, 0},
};

HostGuestFn video_host_fn(const char *name)         /* a MAGVID export by name (the tests call them without a guest program) */
{
    const HostExport *e;

    for (e = MAGVID; e->name; e++)
        if (!strcmp(e->name, name))
            return e->fn;
    return NULL;
}

void video_install(void) { module_register_host("magvid.dll", MAGVID); }

/* video.c - the game's video library, MAGVID.DLL, as C functions (the statistics window, STATWIN.DLL, plays the ending movie with it), and the MCI window the coin
 * toss plays its movie in. Port of winemu/movie.py (the MAGVID half and the MCI half): a movie is a window (movie.c) that shows its frames on the clock.
 * A movie this host cannot decode (Indeo 4 without ffmpeg) is "cannot load": LoadAVI says 4 and the game carries on without it. */
#include <string.h>
#include <strings.h>
#include <unistd.h>

#include "gdi.h"
#include "movie.h"
#include "port.h"
#include "sched.h"

#define P(a) ((const char *)(G + (uint32_t)(a)))
#define VID_SLOTS 3                                                          /* the DLL's own limit: handles are 0..2 */

static uint32_t slots[VID_SLOTS];                                            /* the window of each loaded movie, 0 if free */
static uint32_t slot_bg[VID_SLOTS];                                          /* SetVidBackgroundToDIB: the picture behind each movie (STATWIN's DIB object), 0 if none */

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

/* SetVidBackgroundToDIB(dib, handle): the picture the movie plays over. `dib` is STATWIN's own DIB object (a C++ class): +4 points to its BITMAPINFOHEADER and +8 to its
 * pixels (a 640x480 24 bit picture of the five wizards, read from a BMP of the statistics window). The real library keeps it and DrawVidBackground paints it. */
static uint32_t set_vid_background_to_dib(const uint32_t *a)
{
    if (a[1] >= VID_SLOTS || !slots[a[1]])
        return 2;
    slot_bg[a[1]] = a[0] > 0xFFFF ? a[0] : 0;
    port_trace("magvid: SetVidBackgroundToDIB %u = 0x%x", a[1], a[0]);
    return 0;
}

/* The picture of a slot, painted on the game's main window, the one that covers the screen (the real library draws it with DrawDibDraw, whole, on one device context: the
 * two DrawVidBackground calls before the first clip are what put the statistics window's picture on the screen; docs/notes/duel-won-black-screen.md, third report).
 * Centred when the screen is larger than the picture. */
static void paint_vid_background(uint32_t handle)
{
    static uint32_t dc, dc_hwnd;
    uint32_t obj = slot_bg[handle], bmi, bits, hwnd = wm_main_hwnd(), args[13];
    int w, h;

    if (!obj || !hwnd)
        return;
    bmi = RD32(obj + 4);
    bits = RD32(obj + 8);
    if (bmi <= 0xFFFF || bits <= 0xFFFF)
        return;
    w = (int32_t)RD32(bmi + 4);
    h = (int32_t)RD32(bmi + 8);
    if (h < 0)
        h = -h;
    if (w <= 0 || h <= 0)
        return;
    if (!dc || dc_hwnd != hwnd) {
        dc = gdi_window_dc(hwnd);
        dc_hwnd = hwnd;
    }
    memset(args, 0, sizeof(args));
    args[1] = dc;
    args[2] = (uint32_t)(screen_w > w ? (screen_w - w) / 2 : 0);
    args[3] = (uint32_t)(screen_h > h ? (screen_h - h) / 2 : 0);
    args[4] = (uint32_t)w; args[5] = (uint32_t)h;
    args[6] = bmi; args[7] = bits;
    args[10] = (uint32_t)w; args[11] = (uint32_t)h;
    drawdib_draw(args);
    wm_dirty = 1;
}

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
        slot_bg[a[0]] = 0;
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

/* DrawVidBackground(handle): paints the background (SetVidBackgroundToDIB) again. The statistics window does it before a clip and when it is done, and a see-through clip (a
 * figure over the window's own picture) is gone then; the clips that are whole rooms stay as their last picture, which is the room.
 * The window is kept (visible, undrawn): STATWIN waits for a click or a key after the last clip with a PeekMessage loop on its own thread, and the only
 * windows of that thread are these, so with the window gone nothing could ever end the wait (a won duel hung on a black screen). */
static uint32_t draw_vid_background(const uint32_t *a)
{
    Window *w = slot_window(a[0]);

    if (w)
        paint_vid_background(a[0]);
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
    {"SetVidCallBack", 7, accept}, {"SetVidBackground", 8, accept}, {"SetVidBackgroundToBMP", 9, accept}, {"SetVidBackgroundToDIB", 10, set_vid_background_to_dib},
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


/* ---- MCI: winmm.dll's mciSendCommandA and mciGetErrorStringA, for the digital video device ------------------------------------------------------------------------------------ */
/* The Magic Shell (magic.exe 2.15) plays its animation and the credits with the multimedia command interface (MCI_OPEN of an AVI as "avivideo" with a parent window, MCI_WHERE for its
 * size, MCI_BREAK for the key that stops it, MCI_PLAY, MCI_STATUS in a loop until it stops, MCI_CLOSE). A device is a movie window (movie.c) in the parent it was given; the commands are the
 * ones the game uses and the ones a player of such a clip is likely to send; any other command is "unrecognized". Only the digital video device exists (an AVI file, or the type "avivideo" or
 * "digitalvideo"): a CD audio, MIDI or wave device is "invalid device name", as on a machine with no such driver. */
enum { MCI_OPEN = 0x803, MCI_CLOSE = 0x804, MCI_PLAY = 0x806, MCI_SEEK = 0x807, MCI_STOP = 0x808, MCI_PAUSE = 0x809, MCI_SET = 0x80D, MCI_BREAK = 0x811, MCI_STATUS = 0x814,
       MCI_REALIZE = 0x840, MCI_WINDOW = 0x841, MCI_PUT = 0x842, MCI_WHERE = 0x843, MCI_UPDATE = 0x854, MCI_GETDEVCAPS = 0x80B };
enum { MCIERR_INVALID_DEVICE_ID = 257, MCIERR_UNRECOGNIZED_COMMAND = 261, MCIERR_INVALID_DEVICE_NAME = 263, MCIERR_CANNOT_LOAD_DRIVER = 266, MCIERR_MISSING_PARAMETER = 273,
       MCIERR_FILE_NOT_FOUND = 275, MCIERR_DEVICE_OPEN = 265 };
enum { MCI_NOTIFY = 1, MCI_WAIT = 2, MCI_OPEN_ELEMENT = 0x200, MCI_OPEN_TYPE = 0x2000, MCI_DGV_OPEN_PARENT = 0x20000 };
enum { MM_MCINOTIFY = 0x3B9, MCI_MODE_STOP = 524, MCI_MODE_PLAY = 525, MCI_MODE_PAUSE = 529 };
#define MCI_DEVICES 8

typedef struct MciDev {
    int used;
    uint32_t win;               /* the movie window */
    uint32_t notify;            /* the window MCI_NOTIFY wants its MM_MCINOTIFY (0: none) and */
    int notify_pending;         /* whether it still has to be told that the movie ended */
    uint32_t break_key;         /* MCI_BREAK: a virtual key that stops a playing movie (0: none) */
    int played;                 /* it has played at least once */
} MciDev;
static MciDev mci_dev[MCI_DEVICES];

static MciDev *mci_by_id(uint32_t id) { return id >= 1 && id <= MCI_DEVICES && mci_dev[id - 1].used ? &mci_dev[id - 1] : NULL; }

static void mci_notify_if_over(MciDev *d, uint32_t id)
{
    Window *w = wm_window(d->win);

    if (d->notify_pending && !movie_window_playing(w)) {
        d->notify_pending = 0;
        wm_post(d->notify, MM_MCINOTIFY, 1 /* MCI_NOTIFY_SUCCESSFUL */, id);
    }
}

static uint32_t mci_open(uint32_t flags, uint32_t parms)
{
    char host[1200];
    uint32_t name = RD32(parms + 12), parent = 0, style = 0, id;
    Movie *m;
    Window *w;
    int slot;

    if (!(flags & MCI_OPEN_ELEMENT) || name <= 0xFFFF)
        return MCIERR_MISSING_PARAMETER;
    if (flags & MCI_OPEN_TYPE) {
        uint32_t type = RD32(parms + 8);

        if (type <= 0xFFFF || (strcasecmp(P(type), "avivideo") && strcasecmp(P(type), "digitalvideo")))
            return MCIERR_INVALID_DEVICE_NAME;
    }
    if (!paths_host(P(name), 0, host, sizeof(host)) || access(host, R_OK) != 0) {
        port_trace("mci: open %s: no such file", P(name));
        return MCIERR_FILE_NOT_FOUND;
    }
    for (slot = 0; slot < MCI_DEVICES && mci_dev[slot].used; slot++)
        ;
    if (slot == MCI_DEVICES)
        return MCIERR_DEVICE_OPEN;
    m = movie_open(host);
    if (!m) {
        port_trace("mci: open %s: a movie this host cannot play", P(name));
        return MCIERR_CANNOT_LOAD_DRIVER;
    }
    if (flags & MCI_DGV_OPEN_PARENT) {
        style = RD32(parms + 20);
        parent = RD32(parms + 24);
    }
    w = movie_window("AVIVideo", wm_window(parent) ? parent : 0, style, 0, 0, m);
    id = (uint32_t)slot + 1;
    memset(&mci_dev[slot], 0, sizeof(mci_dev[slot]));
    mci_dev[slot].used = 1;
    mci_dev[slot].win = w->hwnd;
    WR32(parms + 4, id);                                    /* wDeviceID */
    port_trace("mci: opened %s as device %u: %dx%d, %d frames", P(name), id, movie_width(m), movie_height(m), movie_frames(m));
    return 0;
}

static uint32_t mciSendCommandA(const uint32_t *a)
{
    uint32_t id = a[0], msg = a[1] & 0xFFFF, flags = a[2], parms = a[3];
    MciDev *d;
    Window *w;

    if (msg == MCI_OPEN)
        return mci_open(flags, parms);
    d = mci_by_id(id);
    if (!d)
        return MCIERR_INVALID_DEVICE_ID;
    w = wm_window(d->win);
    switch (msg) {
    case MCI_CLOSE:
        if (w)
            wm_destroy(d->win);
        memset(d, 0, sizeof(*d));
        return 0;
    case MCI_WHERE:                                         /* the picture's rectangle: the movie's own size at 0, 0 (source, destination and window alike) */
        if (parms && w) {
            WR32(parms + 4, 0); WR32(parms + 8, 0); WR32(parms + 12, (uint32_t)w->w); WR32(parms + 16, (uint32_t)w->h);
        }
        return 0;
    case MCI_BREAK:
        if (parms)
            d->break_key = RD32(parms + 4);
        return 0;
    case MCI_PLAY:
        if (!w)
            return MCIERR_INVALID_DEVICE_ID;
        if ((flags & MCI_NOTIFY) && parms) {
            d->notify = RD32(parms);
            d->notify_pending = 1;
        }
        d->played = 1;
        movie_window_play(w);                               /* the window plays it (and its sound) from the first picture */
        if (flags & MCI_WAIT) {
            while (movie_window_playing(wm_window(d->win))) {
                if (d->break_key < 256 && d->break_key && wm_keys[d->break_key]) {
                    movie_window_stop(wm_window(d->win));
                    break;
                }
                sched_sleep(0.01);
            }
        }
        mci_notify_if_over(d, id);
        return 0;
    case MCI_STOP:
    case MCI_PAUSE:
        if (w)
            movie_window_stop(w);
        return 0;
    case MCI_STATUS: {                                      /* dwItem at +8 (MCI_STATUS_...: 1 length, 2 position, 3 tracks, 4 mode, 5 media present, 6 time format, 7 ready), the answer at +4 */
        uint32_t item = parms ? RD32(parms + 8) : 0, v = 0;

        if (!(flags & 0x100) || !parms)                     /* MCI_STATUS_ITEM */
            return MCIERR_MISSING_PARAMETER;
        mci_notify_if_over(d, id);
        switch (item) {
        case 1: v = (uint32_t)movie_window_frames(w); break;                      /* the length, in frames (the time format of the digital video device) */
        case 2: v = d->played && w && !movie_window_playing(w) ? (uint32_t)movie_window_frames(w) : 0; break;   /* where it is: the start, or the end once it has played */
        case 3: v = 1; break;
        case 4: v = w && movie_window_playing(w) ? MCI_MODE_PLAY : MCI_MODE_STOP; break;
        case 5: case 7: v = 1; break;
        default: break;
        }
        WR32(parms + 4, v);
        return 0;
    }
    case MCI_SEEK: case MCI_SET: case MCI_REALIZE: case MCI_WINDOW: case MCI_PUT: case MCI_UPDATE: case MCI_GETDEVCAPS:
        return 0;
    default:
        return MCIERR_UNRECOGNIZED_COMMAND;
    }
}

/* mciGetErrorStringA(error, buffer, size): the text Windows gives an MCI error number, in the buffer; FALSE for a number it has no text for. */
static uint32_t mciGetErrorStringA(const uint32_t *a)
{
    static const struct { uint32_t code; const char *text; } messages[] = {
        {257, "Invalid device ID."}, {259, "Unrecognized keyword."}, {261, "Unrecognized command."}, {262, "A hardware problem occurred."}, {263, "Invalid device name."},
        {264, "Out of memory."}, {265, "The device is already open."}, {266, "The specified device driver cannot be loaded."}, {267, "Command string is missing."},
        {273, "A required parameter is missing."}, {274, "The device does not support that command."}, {275, "The specified file cannot be found."},
        {276, "The device is not ready."}, {277, "An internal error occurred."}, {278, "A driver error occurred."}, {282, "A parameter is out of range."},
        {283, "The specified flags are not compatible."}, {287, "A device type is required."}, {288, "The device is locked."}, {294, "There is no window."},
        {0, NULL}};
    int i;

    for (i = 0; messages[i].text; i++)
        if (messages[i].code == a[0]) {
            if (a[1] && a[2]) {
                snprintf((char *)G + a[1], a[2], "%s", messages[i].text);
            }
            return 1;
        }
    if (a[1] && a[2])
        G[a[1]] = 0;
    return 0;
}

const WinApi VIDEO_APIS[] = {
    {"msvfw32.dll", "MCIWndCreateA", mciwnd_create}, {"msvfw32.dll", "DrawDibOpen", one}, {"msvfw32.dll", "DrawDibClose", one}, {"msvfw32.dll", "DrawDibDraw", drawdib_draw},
    {"winmm.dll", "mciSendCommandA", mciSendCommandA}, {"winmm.dll", "mciGetErrorStringA", mciGetErrorStringA},
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

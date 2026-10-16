/* front_sdl.c - the window half of the front end, over SDL2: shows the composed frames, turns the mouse and keyboard into queued events. */
#include <SDL.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <ctype.h>
#include <fcntl.h>
#include <signal.h>
#include <unistd.h>

#include "front.h"
#include "pad.h"
#include "plat.h"
#include "port.h"
#include "gdi_int.h"
#include "navwm.h"
#include "padlog.h"
#include "steamdeck.h"
#include "textin.h"
#include "wm.h"

void front_set_finished(void);
extern uint8_t *G;                           /* the guest's memory (guest.c) */

static int windowed;

/* SIGINT / SIGTERM. SDL would turn them into an SDL_QUIT, which is the same event as the window's close button and so only posts WM_CLOSE to the game (a polite
 * request the game does not answer by ending: the program used to go on for the 5 s of front.c's fallback). A signal is not a request to the game: the program's
 * own handler (SDL's is switched off) only sets a flag, and the window loop, seeing it, flushes and exits. */
static volatile sig_atomic_t signal_quit;

static void on_signal(int sig) { (void)sig; signal_quit = 1; }

static void install_signal_handlers(void)
{
#ifdef _WIN32
    signal(SIGINT, on_signal);          /* Ctrl+C in the console; the C library raises SIGTERM only for raise(SIGTERM) */
    signal(SIGTERM, on_signal);
    signal(SIGBREAK, on_signal);        /* Ctrl+Break, and the console window being closed */
#else
    struct sigaction sa;

    memset(&sa, 0, sizeof(sa));
    sa.sa_handler = on_signal;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGINT, &sa, NULL);
    sigaction(SIGTERM, &sa, NULL);
#endif
}

int front_has_window(void) { return windowed; }

/* A key as the game's keyboard code sees it: virtual-key code and scan code. The game turns a WM_KEYDOWN's scan code into a character itself
 * and reads Shift, Ctrl, Alt and Caps Lock from GetAsyncKeyState, so those are real key events too (left and right are the same key). */
typedef struct { uint16_t vk, sc; } Key;
static Key keymap[SDL_NUM_SCANCODES];

static void map(int scancode, int vk, int sc) { keymap[scancode] = (Key){(uint16_t)vk, (uint16_t)sc}; }

static void init_keys(void)
{
    static const char *rows[3] = {"qwertyuiop", "asdfghjkl", "zxcvbnm"};
    static const int row_sc[3] = {0x10, 0x1E, 0x2C};
    int i, r;

    for (r = 0; r < 3; r++)
        for (i = 0; rows[r][i]; i++)
            map(SDL_SCANCODE_A + (rows[r][i] - 'a'), rows[r][i] - 'a' + 'A', row_sc[r] + i);
    for (i = 0; i < 10; i++)
        map(i < 9 ? SDL_SCANCODE_1 + i : SDL_SCANCODE_0, i < 9 ? '1' + i : '0', 0x02 + i);
    for (i = 0; i < 10; i++)
        map(SDL_SCANCODE_F1 + i, 0x70 + i, 0x3B + i);
    map(SDL_SCANCODE_F11, 0x7A, 0x57);
    map(SDL_SCANCODE_F12, 0x7B, 0x58);
    map(SDL_SCANCODE_ESCAPE, 27, 0x01);       map(SDL_SCANCODE_BACKSPACE, 8, 0x0E);      map(SDL_SCANCODE_TAB, 9, 0x0F);
    map(SDL_SCANCODE_RETURN, 13, 0x1C);       map(SDL_SCANCODE_KP_ENTER, 13, 0x1C);      map(SDL_SCANCODE_SPACE, 32, 0x39);
    map(SDL_SCANCODE_LCTRL, 0x11, 0x1D);      map(SDL_SCANCODE_RCTRL, 0x11, 0x1D);
    map(SDL_SCANCODE_LSHIFT, 0x10, 0x2A);     map(SDL_SCANCODE_RSHIFT, 0x10, 0x36);
    map(SDL_SCANCODE_LALT, 0x12, 0x38);       map(SDL_SCANCODE_RALT, 0x12, 0x38);        map(SDL_SCANCODE_CAPSLOCK, 0x14, 0x3A);
    map(SDL_SCANCODE_HOME, 0x24, 0x47);       map(SDL_SCANCODE_UP, 38, 0x48);            map(SDL_SCANCODE_PAGEUP, 0x21, 0x49);
    map(SDL_SCANCODE_LEFT, 37, 0x4B);         map(SDL_SCANCODE_RIGHT, 39, 0x4D);         map(SDL_SCANCODE_END, 0x23, 0x4F);
    map(SDL_SCANCODE_DOWN, 40, 0x50);         map(SDL_SCANCODE_PAGEDOWN, 0x22, 0x51);    map(SDL_SCANCODE_INSERT, 0x2D, 0x52);
    map(SDL_SCANCODE_DELETE, 46, 0x53);
    map(SDL_SCANCODE_MINUS, 0xBD, 0x0C);      map(SDL_SCANCODE_EQUALS, 0xBB, 0x0D);      map(SDL_SCANCODE_LEFTBRACKET, 0xDB, 0x1A);
    map(SDL_SCANCODE_RIGHTBRACKET, 0xDD, 0x1B); map(SDL_SCANCODE_SEMICOLON, 0xBA, 0x27); map(SDL_SCANCODE_APOSTROPHE, 0xDE, 0x28);
    map(SDL_SCANCODE_GRAVE, 0xC0, 0x29);      map(SDL_SCANCODE_BACKSLASH, 0xDC, 0x2B);   map(SDL_SCANCODE_COMMA, 0xBC, 0x33);
    map(SDL_SCANCODE_PERIOD, 0xBE, 0x34);     map(SDL_SCANCODE_SLASH, 0xBF, 0x35);
}

/* The characters of keys that always type the same one. The others are typed by SDL's text input (the layout and Shift decide), which follows
 * the key's event in the same batch: the key waits for it. */
static int fixed_char(int vk) { return vk == 13 ? 13 : vk == 8 ? 8 : vk == 9 ? 9 : vk == 27 ? 27 : -1; }

typedef struct { Key k; int pending; int repeat; } Pending;

static Pending pend;
static uint8_t held[SDL_NUM_SCANCODES];            /* keys sent down and not yet up */
static Key held_key[SDL_NUM_SCANCODES];

static void flush_pending(int ch)
{
    if (!pend.pending)
        return;
    front_push_key(pend.k.vk, pend.k.sc, 1, ch, pend.repeat);
    pend.pending = 0;
}

static int shift_held(void) { return held[SDL_SCANCODE_LSHIFT] || held[SDL_SCANCODE_RSHIFT]; }

/* ---- text with no key ---------------------------------------------------------------------------------------------------------------------------------
 * SDL_TEXTINPUT follows the SDL_KEYDOWN of the key that typed it, and then it is that key's character (a key waits for it, above). Text that arrives with no key waiting (the Steam
 * Deck's on-screen keyboard, an input method, a paste, a numeric keypad key we have no mapping for) is turned into the key presses that type it (textin.c: the game's text boxes read
 * keys, not WM_CHAR) and sent once. */
static void deliver_text(const TextOut *o)
{
    int i;

    for (i = 0; i < o->n; i++) {
        const TextAct *a = &o->act[i];

        if (a->type == TX_KEYDOWN)
            front_push_key(a->vk, a->sc, 1, a->ch, 0);
        else if (a->type == TX_KEYUP)
            front_push_key(a->vk, a->sc, 0, -1, 0);
        else
            front_push_char(a->ch);
    }
}

static void handle_text(const char *text)
{
    TextOut out;

    if (pend.pending) {                          /* the text of the key that is waiting for it: its character, and nothing more is typed */
        flush_pending(textin_attach(text));
        return;
    }
    out.n = 0;
    textin_type(text, shift_held(), &out);
    deliver_text(&out);
}

/* Whether SDL's text input is on. Everywhere but the Steam Deck it always is. On the Deck (and with PORT_TEXTINPUT=auto) it is on only while a text field has the focus
 * (front_text_wanted), because there SDL_StartTextInput is what brings the Steam keyboard up, and it must not be up over the title screen. */
static int text_managed, text_on;

static void update_text_input(void)
{
    int want;

    if (!text_managed)
        return;
    want = front_text_wanted();
    if (want == text_on)
        return;
    text_on = want;
    if (want)
        SDL_StartTextInput();
    else
        SDL_StopTextInput();
    if (getenv("PORT_TEXT_LOG"))
        fprintf(stderr, "text input: %s\n", want ? "on (a text field has the focus)" : "off");
}

static void release_all(void)
{
    int i;

    for (i = 0; i < SDL_NUM_SCANCODES; i++)
        if (held[i]) {
            front_push_key(held_key[i].vk, held_key[i].sc, 0, -1, 0);
            held[i] = 0;
        }
}

/* ---- game controllers ----------------------------------------------------------------------------------------------------------------------------------
 * A pad is a mouse and a keyboard to the game (pad.c has the logic and the table of what each control does). The controller events arrive here, on the window's thread, the
 * actions come back and go into the same queue as the real mouse and keyboard (front_push_mouse, front_push_key). The pad's cursor is drawn by us (the game draws none: the pointer
 * is the host's), into the picture that is shown, and the host's own pointer is hidden while the pad is the last device used; the real mouse takes the cursor back the moment it moves.
 * PORT_NOPAD=1 turns all of it off. */
static Pad pad;
static int pad_on;                                  /* the pad logic is running (PORT_NOPAD is not set) */
#define MAX_PADS 8
static SDL_GameController *pads[MAX_PADS];
static Uint32 pad_t;                                /* the last tick of pad_step */
static int shown_active = -1, shown_x = -1, shown_y = -1;      /* what was last drawn: whether the pad's cursor was there, and its position */
static uint8_t *view_buf;                           /* the frame with the pad's cursor drawn into it (only used while the pad is active) */

/* PORT_PAD_LOG: what the pad asked the game to do. The cursor's moves are thinned out (one line a quarter second) so a stick does not fill the log. */
static void log_pad_act(const PadAct *a)
{
    static Uint32 last_move;
    static int moves;

    if (a->type == PA_MOVE) {
        Uint32 now = SDL_GetTicks();

        moves++;
        if (now - last_move < 250)
            return;
        last_move = now;
        padlog("pad: pointer moves to (%d,%d) (%d moves since the last line)", a->x, a->y, moves);
        moves = 0;
        return;
    }
    switch (a->type) {
    case PA_LDOWN:   padlog("pad: left button down at (%d,%d)", a->x, a->y); break;
    case PA_LUP:     padlog("pad: left button up at (%d,%d)", a->x, a->y); break;
    case PA_RDOWN:   padlog("pad: right button down at (%d,%d)", a->x, a->y); break;
    case PA_RUP:     padlog("pad: right button up at (%d,%d)", a->x, a->y); break;
    case PA_KEYDOWN: if (!a->repeat) padlog("pad: key down vk 0x%x", a->vk); break;
    case PA_KEYUP:   padlog("pad: key up vk 0x%x", a->vk); break;
    case PA_NAV:     padlog("pad: D-pad %s from (%d,%d)%s: asks the game for the next target", a->dir == 0 ? "up" : a->dir == 1 ? "down" : a->dir == 2 ? "left" : "right", a->x, a->y, a->repeat ? " (repeat)" : ""); break;
    default: break;
    }
}

static void pad_deliver(const PadOut *o)
{
    int i;

    for (i = 0; i < o->n; i++) {
        const PadAct *a = &o->act[i];

        if (padlog_on())
            log_pad_act(a);
        switch (a->type) {
        case PA_MOVE:    front_push_mouse(IN_MOVE, a->x, a->y); break;
        case PA_LDOWN:   front_push_mouse(IN_DOWN, a->x, a->y); break;
        case PA_LUP:     front_push_mouse(IN_UP, a->x, a->y); break;
        case PA_RDOWN:   front_push_mouse(IN_RDOWN, a->x, a->y); break;
        case PA_RUP:     front_push_mouse(IN_RUP, a->x, a->y); break;
        case PA_KEYDOWN: front_push_key(a->vk, a->sc, 1, a->ch, a->repeat); break;
        case PA_KEYUP:   front_push_key(a->vk, a->sc, 0, -1, 0); break;
        case PA_NAV:     front_push_nav(a->dir, a->x, a->y); break;       /* the D-pad: the guest side finds the next card or button (navwm.c), the answer comes back in pad_nav_answers */
        }
    }
}

static int pad_btn_of(int sdl_button)
{
    switch (sdl_button) {
    case SDL_CONTROLLER_BUTTON_A: return PAD_A;
    case SDL_CONTROLLER_BUTTON_B: return PAD_B;
    case SDL_CONTROLLER_BUTTON_X: return PAD_X;
    case SDL_CONTROLLER_BUTTON_Y: return PAD_Y;
    case SDL_CONTROLLER_BUTTON_BACK: return PAD_BACK;
    case SDL_CONTROLLER_BUTTON_GUIDE: return PAD_GUIDE;
    case SDL_CONTROLLER_BUTTON_START: return PAD_START;
    case SDL_CONTROLLER_BUTTON_LEFTSTICK: return PAD_LSTICK;
    case SDL_CONTROLLER_BUTTON_RIGHTSTICK: return PAD_RSTICK;
    case SDL_CONTROLLER_BUTTON_LEFTSHOULDER: return PAD_LB;
    case SDL_CONTROLLER_BUTTON_RIGHTSHOULDER: return PAD_RB;
    case SDL_CONTROLLER_BUTTON_DPAD_UP: return PAD_DUP;
    case SDL_CONTROLLER_BUTTON_DPAD_DOWN: return PAD_DDOWN;
    case SDL_CONTROLLER_BUTTON_DPAD_LEFT: return PAD_DLEFT;
    case SDL_CONTROLLER_BUTTON_DPAD_RIGHT: return PAD_DRIGHT;
    default: return -1;                       /* the extra buttons (paddles, touchpad, share) do nothing */
    }
}

static int pad_axis_of(int sdl_axis)
{
    switch (sdl_axis) {
    case SDL_CONTROLLER_AXIS_LEFTX: return PAD_AX_LX;
    case SDL_CONTROLLER_AXIS_LEFTY: return PAD_AX_LY;
    case SDL_CONTROLLER_AXIS_RIGHTX: return PAD_AX_RX;
    case SDL_CONTROLLER_AXIS_RIGHTY: return PAD_AX_RY;
    case SDL_CONTROLLER_AXIS_TRIGGERLEFT: return PAD_AX_LT;
    case SDL_CONTROLLER_AXIS_TRIGGERRIGHT: return PAD_AX_RT;
    default: return -1;
    }
}

static void pad_open(int index)
{
    int i;

    if (!SDL_IsGameController(index)) {
        padlog("joystick %d '%s' is not a game controller (SDL has no mapping for it): the pad code ignores it", index, SDL_JoystickNameForIndex(index) ? SDL_JoystickNameForIndex(index) : "?");
        return;
    }
    for (i = 0; i < MAX_PADS; i++)
        if (!pads[i]) {
            pads[i] = SDL_GameControllerOpen(index);
            if (pads[i])
                fprintf(stderr, "controller: %s\n", SDL_GameControllerName(pads[i]));
            if (padlog_on()) {
                char guid[40] = "";
                char *map = pads[i] ? SDL_GameControllerMapping(pads[i]) : NULL;

                SDL_JoystickGetGUIDString(SDL_JoystickGetDeviceGUID(index), guid, sizeof(guid));
                padlog("controller %d opened: '%s' guid %s%s mapping %s", index, pads[i] ? SDL_GameControllerName(pads[i]) : "?", guid, pads[i] ? "" : " (SDL_GameControllerOpen failed)", map ? map : "(none)");
                SDL_free(map);
            }
            return;
        }
}

/* a controller was unplugged: it is closed, and the pad lets go of everything it held (the stick at rest, the buttons up) */
static void pad_close(SDL_JoystickID id)
{
    PadOut out;
    int i;

    for (i = 0; i < MAX_PADS; i++)
        if (pads[i] && SDL_JoystickInstanceID(SDL_GameControllerGetJoystick(pads[i])) == id) {
            SDL_GameControllerClose(pads[i]);
            pads[i] = NULL;
        }
    out.n = 0;
    pad_release_all(&pad, &out);
    pad_deliver(&out);
}

static void pad_event(const SDL_Event *ev)
{
    PadOut out;

    out.n = 0;
    pad_set_nav(&pad, front_nav_ready());
    switch (ev->type) {
    case SDL_CONTROLLERAXISMOTION: {
        int axis = pad_axis_of(ev->caxis.axis);

        if (padlog_on()) {                           /* an axis is logged when it has moved a good way from where it was last logged (a stick is noisy) */
            static int logged[8];
            int a = ev->caxis.axis & 7, v = ev->caxis.value;

            if (abs(v - logged[a]) >= 6000 || (v == 0 && logged[a] != 0)) {
                padlog("controller axis %s = %d", SDL_GameControllerGetStringForAxis((SDL_GameControllerAxis)ev->caxis.axis), v);
                logged[a] = v;
            }
        }
        if (axis >= 0)
            pad_axis(&pad, axis, ev->caxis.value, &out);
        break;
    }
    case SDL_CONTROLLERBUTTONDOWN:
    case SDL_CONTROLLERBUTTONUP: {
        int b = pad_btn_of(ev->cbutton.button);

        if (padlog_on())
            padlog("controller button %s %s (pad cursor %s, D-pad %s)", SDL_GameControllerGetStringForButton((SDL_GameControllerButton)ev->cbutton.button),
                   ev->type == SDL_CONTROLLERBUTTONDOWN ? "down" : "up", pad.active ? "active" : "not active", front_nav_ready() ? "moves between targets" : "is the arrow keys");
        if (b >= 0)
            pad_button(&pad, b, ev->type == SDL_CONTROLLERBUTTONDOWN, &out);
        break;
    }
    default:
        break;
    }
    pad_deliver(&out);
}

/* the real mouse (or a touch, which SDL makes a mouse of) moved or clicked: it has the cursor now */
static void pad_mouse(int x, int y)
{
    PadOut out;

    if (!pad_on)
        return;
    if (pad.active)
        padlog("the real mouse or a touch took the cursor from the pad at (%d,%d); what the pad held is let go", x, y);
    out.n = 0;
    pad_mouse_used(&pad, x, y, &out);
    pad_deliver(&out);
}

static void pad_release(void)
{
    PadOut out;

    if (!pad_on)
        return;
    out.n = 0;
    pad_release_all(&pad, &out);
    pad_deliver(&out);
}

/* the answers to the D-pad's presses (front_nav_result): the pointer goes to the target the guest side chose, as an ordinary move, or the list there scrolls by its arrow key */
static unsigned nav_seen;

static void pad_nav_answers(void)
{
    int kind, x, y, dir;
    PadOut out;

    while (front_nav_result(&nav_seen, &kind, &x, &y, &dir)) {
        if (kind == NAVR_MOVE)
            padlog("D-pad: the game chose a target, the pointer goes to (%d,%d)", x, y);
        else
            padlog("D-pad: a list there scrolls, the arrow key is tapped");
        out.n = 0;
        if (kind == NAVR_MOVE)
            pad_put(&pad, x, y, &out);
        else
            pad_tap_dir(&pad, dir, &out);
        pad_deliver(&out);
    }
}

/* time passes: the cursor moves by the stick */
static void pad_tick(void)
{
    Uint32 now = SDL_GetTicks();
    int dt = (int)(now - pad_t);
    PadOut out;

    if (!pad_on || dt <= 0)
        return;
    pad_t = now;
    if (dt > 100)                                     /* a stall (a window being dragged) must not fling the cursor */
        dt = 100;
    out.n = 0;
    pad_set_nav(&pad, front_nav_ready());
    pad_step(&pad, dt, &out);
    pad_deliver(&out);
}

/* the frame to show: the game's, with the pad's cursor on it while the pad is the device in use */
static const uint8_t *frame_view(const uint8_t *rgb)
{
    if (!pad_on || !pad.active || !view_buf)
        return rgb;
    memcpy(view_buf, rgb, (size_t)SCREEN_W * SCREEN_H * 3);
    pad_draw_cursor(view_buf, SCREEN_W, SCREEN_H, pad.ix, pad.iy);
    return view_buf;
}

/* the cursor (or whether the pad has it) changed since it was last drawn: the picture must be shown again; the host's pointer is hidden while the pad has it */
static int pad_view_changed(void)
{
    if (!pad_on)
        return 0;
    if (pad.active == shown_active && (!pad.active || (pad.ix == shown_x && pad.iy == shown_y)))
        return 0;
    if (pad.active != shown_active)
        SDL_ShowCursor(pad.active ? SDL_DISABLE : SDL_ENABLE);
    shown_active = pad.active;
    shown_x = pad.ix;
    shown_y = pad.iy;
    return 1;
}

/* PORT_PAD_LOG: what SDL delivers that is not the pad's own (the pad's events are logged in pad_event). What a Steam Input layout that makes the Deck a keyboard and a mouse sends shows up
 * here; mouse motion is thinned out. */
static void log_sdl_event(const SDL_Event *ev)
{
    static Uint32 last_motion;
    static int motions;

    switch (ev->type) {
    case SDL_MOUSEMOTION: {
        Uint32 now = SDL_GetTicks();

        motions++;
        if (now - last_motion >= 250) {
            padlog("mouse moved to (%d,%d)%s (%d motion events since the last line)", ev->motion.x, ev->motion.y, ev->motion.which == SDL_TOUCH_MOUSEID ? " by touch" : "", motions);
            last_motion = now;
            motions = 0;
        }
        break;
    }
    case SDL_MOUSEBUTTONDOWN:
    case SDL_MOUSEBUTTONUP:
        padlog("mouse button %d %s at (%d,%d)%s", ev->button.button, ev->type == SDL_MOUSEBUTTONDOWN ? "down" : "up", ev->button.x, ev->button.y, ev->button.which == SDL_TOUCH_MOUSEID ? " by touch" : "");
        break;
    case SDL_KEYDOWN:
    case SDL_KEYUP:
        if (!ev->key.repeat)
            padlog("key %s %s", SDL_GetScancodeName(ev->key.keysym.scancode), ev->type == SDL_KEYDOWN ? "down" : "up");
        break;
    case SDL_TEXTINPUT:
        padlog("text input \"%s\"", ev->text.text);
        break;
    case SDL_CONTROLLERDEVICEADDED:
        padlog("SDL: controller added (device %d)", ev->cdevice.which);
        break;
    case SDL_CONTROLLERDEVICEREMOVED:
        padlog("SDL: controller removed (instance %d)", (int)ev->cdevice.which);
        break;
    case SDL_JOYDEVICEADDED:
        padlog("SDL: joystick added (device %d) '%s'", ev->jdevice.which, SDL_JoystickNameForIndex(ev->jdevice.which) ? SDL_JoystickNameForIndex(ev->jdevice.which) : "?");
        break;
    case SDL_WINDOWEVENT: {
        static const char *const names[] = {"none", "shown", "hidden", "exposed", "moved", "resized", "size changed", "minimized", "maximized", "restored", "mouse entered", "mouse left",
                                            "focus gained", "focus lost", "close", "take focus", "hit test"};
        int e = ev->window.event;

        if (e != SDL_WINDOWEVENT_EXPOSED && e != SDL_WINDOWEVENT_MOVED)
            padlog("window: %s", e >= 0 && e < (int)(sizeof(names) / sizeof(names[0])) ? names[e] : "?");
        break;
    }
    default:
        break;
    }
}

/* PORT_PAD_LOG at start: where the program runs and which controllers SDL has found. */
static void log_start(SDL_Window *win, int deck, int fullscreen)
{
    SDL_version linked;
    int i, n, w = 0, h = 0;
    const char *e;

    padlog_reset();
    SDL_GetVersion(&linked);
    SDL_GetWindowSize(win, &w, &h);
    padlog("input log%s%s (PORT_PAD_LOG)", padlog_file() ? " also in the file " : " on stderr only", padlog_file() ? padlog_file() : "");
    padlog("start: SDL %d.%d.%d, video driver %s, window %dx%d, Steam Deck %s, full screen %s, pad code %s, text input %s", linked.major, linked.minor, linked.patch,
           SDL_GetCurrentVideoDriver() ? SDL_GetCurrentVideoDriver() : "?", w, h, deck ? "yes" : "no", fullscreen ? "yes" : "no", pad_on ? "on" : "off (PORT_NOPAD)", text_managed ? "managed" : "always on");
    padlog("env: SteamDeck=%s SteamGameId=%s SteamAppId=%s XDG_CURRENT_DESKTOP=%s GAMESCOPE_WAYLAND_DISPLAY=%s SDL_VIDEODRIVER=%s SDL_GAMECONTROLLERCONFIG=%s", getenv("SteamDeck") ? getenv("SteamDeck") : "-",
           getenv("SteamGameId") ? getenv("SteamGameId") : "-", getenv("SteamAppId") ? getenv("SteamAppId") : "-", getenv("XDG_CURRENT_DESKTOP") ? getenv("XDG_CURRENT_DESKTOP") : "-",
           getenv("GAMESCOPE_WAYLAND_DISPLAY") ? getenv("GAMESCOPE_WAYLAND_DISPLAY") : "-", getenv("SDL_VIDEODRIVER") ? getenv("SDL_VIDEODRIVER") : "-",
           (e = getenv("SDL_GAMECONTROLLERCONFIG")) != NULL ? (*e ? "set" : "empty") : "-");
    padlog("env: SDL_GAMECONTROLLER_IGNORE_DEVICES=%s SDL_JOYSTICK_HIDAPI=%s LD_PRELOAD=%s", getenv("SDL_GAMECONTROLLER_IGNORE_DEVICES") ? getenv("SDL_GAMECONTROLLER_IGNORE_DEVICES") : "-",
           getenv("SDL_JOYSTICK_HIDAPI") ? getenv("SDL_JOYSTICK_HIDAPI") : "-", getenv("LD_PRELOAD") ? getenv("LD_PRELOAD") : "-");
    n = SDL_NumJoysticks();
    padlog("%d joystick(s) at start%s", n, n ? "" : ": SDL sees no controller (on a Deck with Steam Input's Desktop layout the Deck is a keyboard and a mouse; choose a Gamepad layout)");
    for (i = 0; i < n; i++) {
        char guid[40] = "";

        SDL_JoystickGetGUIDString(SDL_JoystickGetDeviceGUID(i), guid, sizeof(guid));
        padlog("joystick %d: '%s' guid %s, %s", i, SDL_JoystickNameForIndex(i) ? SDL_JoystickNameForIndex(i) : "?", guid, SDL_IsGameController(i) ? "a game controller" : "NOT a game controller (no mapping)");
    }
}

/* PORT_SCRIPT="2.5:move 320 240;3:down;3.2:up;4:key return;5:text abc;6:shot /tmp/a.ppm;9:quit": a test driver. The input is pushed as SDL events (so it takes
 * the same path as the real thing, key mapping and text input included), and `shot` writes what the window shows. Times are seconds from the start. */
typedef struct { double t; char cmd[16]; char arg[512]; } Step;
static Step steps[64];
static int nsteps, next_step;
static const uint8_t *shot_frame;           /* the latest frame (front_run's buffer), for `shot` */
static Uint32 script_window;               /* the window the synthetic events are for */

static void parse_script(void)
{
    char *spec = getenv("PORT_SCRIPT") ? strdup(getenv("PORT_SCRIPT")) : NULL, *tok, *save;

    for (tok = spec ? strtok_r(spec, ";", &save) : NULL; tok && nsteps < 64; tok = strtok_r(NULL, ";", &save)) {
        Step *s = &steps[nsteps];
        char *colon = strchr(tok, ':');

        if (!colon)
            continue;
        s->t = atof(tok);
        if (sscanf(colon + 1, "%15s %511[^\n]", s->cmd, s->arg) < 1)
            continue;
        nsteps++;
    }
    free(spec);
}

static SDL_Scancode scancode_named(const char *n)
{
    SDL_Scancode sc = SDL_GetScancodeFromName(n);

    if (sc == SDL_SCANCODE_UNKNOWN && !strcasecmp(n, "esc"))
        sc = SDL_SCANCODE_ESCAPE;
    return sc;
}

static void key_event(SDL_Scancode sc, int down)
{
    SDL_Event e;

    memset(&e, 0, sizeof(e));
    e.type = down ? SDL_KEYDOWN : SDL_KEYUP;
    e.key.keysym.scancode = sc;
    e.key.keysym.sym = SDL_GetKeyFromScancode(sc);
    e.key.state = down ? SDL_PRESSED : SDL_RELEASED;
    e.key.windowID = script_window;
    SDL_PushEvent(&e);
}

/* A scripted mouse position is in screen pixels, but SDL turns every mouse event, pushed ones too, from window pixels to screen pixels (SDL_RenderSetLogicalSize): when the
 * window is not the screen's size (a window made to fit a small display, or PORT_WINDOW), a pushed position goes through the inverse first, so the game gets the number
 * the script gave (to within a pixel). */
static void to_window(SDL_Renderer *ren, int *x, int *y)
{
#if SDL_VERSION_ATLEAST(2, 0, 18)
    int wx, wy, ww, wh;

    if (ren && SDL_GetRendererOutputSize(ren, &ww, &wh) == 0 && (ww != SCREEN_W || wh != SCREEN_H)) {
        SDL_RenderLogicalToWindow(ren, (float)*x, (float)*y, &wx, &wy);
        *x = wx;
        *y = wy;
    }
#else
    (void)ren; (void)x; (void)y;
#endif
}

/* A controller event from a script, as SDL itself would queue it (the instance id is one no device has: the handler does not look at it), so it takes the path of a real pad:
 *   pad axis lx|ly|rx|ry|lt|rt VALUE      -1..1 (the triggers 0..1)
 *   pad stick l|r X Y                     both axes of a stick
 *   pad button NAME down|up               a b x y back guide start l3 r3 lb rb up down left right
 *   pad press NAME                        down, then up
 *   pad remove                            the controller was unplugged
 *   pad pos                               where the pad's cursor is, on stderr */
static const char *const pad_button_names[] = {"a", "b", "x", "y", "back", "guide", "start", "l3", "r3", "lb", "rb", "up", "down", "left", "right"};
static const int pad_button_sdl[] = {
    SDL_CONTROLLER_BUTTON_A, SDL_CONTROLLER_BUTTON_B, SDL_CONTROLLER_BUTTON_X, SDL_CONTROLLER_BUTTON_Y, SDL_CONTROLLER_BUTTON_BACK, SDL_CONTROLLER_BUTTON_GUIDE,
    SDL_CONTROLLER_BUTTON_START, SDL_CONTROLLER_BUTTON_LEFTSTICK, SDL_CONTROLLER_BUTTON_RIGHTSTICK, SDL_CONTROLLER_BUTTON_LEFTSHOULDER, SDL_CONTROLLER_BUTTON_RIGHTSHOULDER,
    SDL_CONTROLLER_BUTTON_DPAD_UP, SDL_CONTROLLER_BUTTON_DPAD_DOWN, SDL_CONTROLLER_BUTTON_DPAD_LEFT, SDL_CONTROLLER_BUTTON_DPAD_RIGHT,
};
static const char *const pad_axis_names[] = {"lx", "ly", "rx", "ry", "lt", "rt"};
static const int pad_axis_sdl[] = {
    SDL_CONTROLLER_AXIS_LEFTX, SDL_CONTROLLER_AXIS_LEFTY, SDL_CONTROLLER_AXIS_RIGHTX, SDL_CONTROLLER_AXIS_RIGHTY, SDL_CONTROLLER_AXIS_TRIGGERLEFT, SDL_CONTROLLER_AXIS_TRIGGERRIGHT,
};
#define FAKE_PAD_ID (-1)

static void push_pad_axis(int i, double v)
{
    SDL_Event e;

    memset(&e, 0, sizeof(e));
    e.type = SDL_CONTROLLERAXISMOTION;
    e.caxis.which = FAKE_PAD_ID;
    e.caxis.axis = (Uint8)pad_axis_sdl[i];
    e.caxis.value = (Sint16)(v < -1 ? -32768 : v > 1 ? 32767 : v * 32767);
    SDL_PushEvent(&e);
}

static void push_pad_button(int i, int down)
{
    SDL_Event e;

    memset(&e, 0, sizeof(e));
    e.type = down ? SDL_CONTROLLERBUTTONDOWN : SDL_CONTROLLERBUTTONUP;
    e.cbutton.which = FAKE_PAD_ID;
    e.cbutton.button = (Uint8)pad_button_sdl[i];
    e.cbutton.state = down ? SDL_PRESSED : SDL_RELEASED;
    SDL_PushEvent(&e);
}

static int name_index(const char *const *names, int n, const char *name)
{
    int i;

    for (i = 0; i < n; i++)
        if (!strcasecmp(names[i], name))
            return i;
    return -1;
}

static void run_pad_step(const char *arg)
{
    char what[16] = "", a[16] = "", b[16] = "";
    double x = 0, y = 0;
    int i, n;

    n = sscanf(arg, "%15s %15s %15s", what, a, b);
    if (n < 1)
        return;
    if (!strcmp(what, "axis") && n >= 3 && (i = name_index(pad_axis_names, 6, a)) >= 0) {
        push_pad_axis(i, atof(b));
    } else if (!strcmp(what, "stick") && n >= 2 && sscanf(arg, "%*s %*s %lf %lf", &x, &y) == 2) {
        int base = tolower((unsigned char)a[0]) == 'r' ? 2 : 0;

        push_pad_axis(base, x);
        push_pad_axis(base + 1, y);
    } else if (!strcmp(what, "button") && n >= 3 && (i = name_index(pad_button_names, 15, a)) >= 0) {
        push_pad_button(i, !strcasecmp(b, "down"));
    } else if (!strcmp(what, "press") && n >= 2 && (i = name_index(pad_button_names, 15, a)) >= 0) {
        push_pad_button(i, 1);
        push_pad_button(i, 0);
    } else if (!strcmp(what, "remove")) {
        SDL_Event e;

        memset(&e, 0, sizeof(e));
        e.type = SDL_CONTROLLERDEVICEREMOVED;
        e.cdevice.which = FAKE_PAD_ID;
        SDL_PushEvent(&e);
    } else if (!strcmp(what, "pos")) {
        fprintf(stderr, "  pad: %d %d active=%d left=%d\n", pad.ix, pad.iy, pad.active, pad.left_src != 0);
    } else if (!strcmp(what, "nav")) {                 /* the targets the D-pad would move between, and which one the pad's cursor is on (printed by the guest side) */
        front_push_nav(-1, pad.ix, pad.iy);
    }
}

static void run_step(const Step *s, SDL_Renderer *ren)
{
    SDL_Event e;
    int x, y;

    memset(&e, 0, sizeof(e));
    if (!strcmp(s->cmd, "move") && sscanf(s->arg, "%d %d", &x, &y) == 2) {
        to_window(ren, &x, &y);
        e.type = SDL_MOUSEMOTION; e.motion.windowID = script_window; e.motion.x = x; e.motion.y = y;
        SDL_PushEvent(&e);
    } else if (!strcmp(s->cmd, "down") || !strcmp(s->cmd, "up") || !strcmp(s->cmd, "rdown") || !strcmp(s->cmd, "rup")) {
        int x2 = 0, y2 = 0;

        if (sscanf(s->arg, "%d %d", &x2, &y2) == 2) {                 /* the position is given (or the last one stays) */
            to_window(ren, &x2, &y2);
            e.type = SDL_MOUSEMOTION; e.motion.windowID = script_window; e.motion.x = x2; e.motion.y = y2;
            SDL_PushEvent(&e);
            memset(&e, 0, sizeof(e));
        }
        SDL_GetMouseState(&x, &y);
        e.type = s->cmd[s->cmd[0] == 'r'] == 'd' ? SDL_MOUSEBUTTONDOWN : SDL_MOUSEBUTTONUP;
        e.button.windowID = script_window;
        e.button.button = s->cmd[0] == 'r' ? SDL_BUTTON_RIGHT : SDL_BUTTON_LEFT;
        e.button.x = x2 ? x2 : x; e.button.y = y2 ? y2 : y;
        SDL_PushEvent(&e);
    } else if (!strcmp(s->cmd, "click") && sscanf(s->arg, "%d %d", &x, &y) == 2) {       /* move, press, release */
        to_window(ren, &x, &y);
        e.type = SDL_MOUSEMOTION; e.motion.windowID = script_window; e.motion.x = x; e.motion.y = y;
        SDL_PushEvent(&e);
        memset(&e, 0, sizeof(e));
        e.type = SDL_MOUSEBUTTONDOWN; e.button.windowID = script_window; e.button.button = SDL_BUTTON_LEFT; e.button.x = x; e.button.y = y;
        SDL_PushEvent(&e);
        e.type = SDL_MOUSEBUTTONUP;
        SDL_PushEvent(&e);
    } else if (!strcmp(s->cmd, "key")) {
        SDL_Scancode sc = scancode_named(s->arg);

        if (sc != SDL_SCANCODE_UNKNOWN) {
            key_event(sc, 1);
            key_event(sc, 0);
        }
    } else if (!strcmp(s->cmd, "text")) {
        const char *p;

        for (p = s->arg; *p; p++) {
            char name[2] = {(char)toupper((unsigned char)*p), 0};
            SDL_Scancode sc = *p == ' ' ? SDL_SCANCODE_SPACE : scancode_named(name);

            if (sc == SDL_SCANCODE_UNKNOWN)
                continue;
            /* straight to the queue: sdl2-compat cannot be handed a synthetic text event */
            front_push_key(keymap[sc].vk, keymap[sc].sc, 1, (unsigned char)*p, 0);
            front_push_key(keymap[sc].vk, keymap[sc].sc, 0, -1, 0);
        }
    } else if (!strcmp(s->cmd, "ime")) {              /* ime TEXT: text with no key before it, as SDL_TEXTINPUT from the Deck's keyboard or an input method brings it (handle_text) */
        handle_text(s->arg);
    } else if (!strcmp(s->cmd, "textinput")) {        /* where SDL's text input stands, on stderr: "text input: on|off managed=0|1" */
        fprintf(stderr, "  text input: %s managed=%d\n", SDL_IsTextInputActive() ? "on" : "off", text_managed);
    } else if (!strcmp(s->cmd, "shot")) {
        FILE *f = fopen(s->arg, "wb");

        /* the frame as the game made it, screen-sized whatever the window is (reading the renderer back gives window pixels); with the pad's cursor on it while the pad is in use */
        if (f && shot_frame) {
            fprintf(f, "P6\n%d %d\n255\n", SCREEN_W, SCREEN_H);
            fwrite(frame_view(shot_frame), 3, (size_t)SCREEN_W * SCREEN_H, f);
        } else
            fprintf(stderr, "shot: no frame yet\n");
        if (f)
            fclose(f);
    } else if (!strcmp(s->cmd, "pad")) {
        run_pad_step(s->arg);
    } else if (!strcmp(s->cmd, "dump")) {         /* dump ADDR LENGTH FILE: raw guest memory (a debugging aid; the guest keeps running meanwhile) */
        unsigned addr = 0, len = 0;
        char file[400];
        FILE *f;

        if (sscanf(s->arg, "%x %u %399s", &addr, &len, file) == 3 && (f = fopen(file, "wb")) != NULL) {
            fwrite(G + addr, 1, len, f);
            fclose(f);
        }
    } else if (!strcmp(s->cmd, "hit") && sscanf(s->arg, "%d %d", &x, &y) == 2) {    /* which window would a click at x y go to */
        uint32_t h = wm_hit_test(x, y);

        fprintf(stderr, "  hit (%d,%d) -> window 0x%x\n", x, y, h);
    } else if (!strcmp(s->cmd, "call")) {         /* call ADDR [ARG...]: start a guest function; an argument "main" is the main window */
        char *save, *tok, buf[512];
        uint32_t addr = 0, args[4];
        int n = -1;

        snprintf(buf, sizeof(buf), "%s", s->arg);
        for (tok = strtok_r(buf, " ", &save); tok && n < 4; tok = strtok_r(NULL, " ", &save), n++) {
            uint32_t v = !strcmp(tok, "main") ? 0xFFFFFFF0u : (uint32_t)strtoul(tok, NULL, 0);

            if (n < 0)
                addr = v;
            else
                args[n] = v;
        }
        front_push_call(addr, args, n < 0 ? 0 : n);
    } else if (!strcmp(s->cmd, "poke")) {          /* poke ADDR VALUE [BYTES]: write guest memory (a debugging aid: set a life total to test the end of a duel) */
        unsigned long a, v;
        int n = 4;
        char *end;

        a = strtoul(s->arg, &end, 0);
        v = strtoul(end, &end, 0);
        if (*end)
            n = atoi(end);
        if (a < 0xFFFF0000ul && (n == 1 || n == 2 || n == 4)) {
            memcpy(G + a, &v, (size_t)n);
            fprintf(stderr, "  poke 0x%lx = %lu (%d bytes)\n", a, v, n);
        }
    } else if (!strcmp(s->cmd, "peek")) {          /* peek ADDR [COUNT]: print COUNT dwords of guest memory from ADDR (a debugging aid) */
        char *end;
        unsigned long a = strtoul(s->arg, &end, 0), n = strtoul(end, NULL, 0), i;

        if (!n)
            n = 1;
        for (i = 0; i < n && a + 4 * i < 0xFFFF0000ul; i++)
            fprintf(stderr, "  peek 0x%lx = %u (0x%x)\n", a + 4 * i, RD32(a + 4 * i), RD32(a + 4 * i));
    } else if (!strcmp(s->cmd, "trace")) {
        port_trace_imports = !strcmp(s->arg, "on");
    } else if (!strcmp(s->cmd, "windows")) {      /* the window tree, to stderr (a debugging aid) */
        wm_dump(stderr);
        wm_popup_dump(stderr);
        wm_dump_queue(stderr);
    } else if (!strcmp(s->cmd, "quit")) {
        e.type = SDL_QUIT;
        SDL_PushEvent(&e);
    }
}

/* PORT_CONTROL=path: a named pipe (mkfifo) the program reads lines from while it runs, each a PORT_SCRIPT step without its time ("click 330 308",
 * "shot /tmp/a.ppm", "key return", "text abc"): a way to play the game from outside, looking at a screenshot between steps.
 * Windows has no mkfifo: there PORT_CONTROL names an ordinary file (made if it is not there), read from its start and then as it grows, so
 * `echo shot a.ppm >> control.txt` is the same as writing into the pipe. */
static int control_fd = -1;
static char control_buf[1024];
static size_t control_len;

static void poll_control(SDL_Renderer *ren)
{
    ssize_t n;

    if (control_fd < 0)
        return;
    while ((n = read(control_fd, control_buf + control_len, sizeof(control_buf) - control_len - 1)) > 0) {
        char *nl;

        control_len += (size_t)n;
        control_buf[control_len] = 0;
        while ((nl = strchr(control_buf, '\n')) != NULL) {
            Step st = {0};

            *nl = 0;
            if (sscanf(control_buf, "%15s %511[^\n]", st.cmd, st.arg) >= 1)
                run_step(&st, ren);
            memmove(control_buf, nl + 1, control_len - (size_t)(nl + 1 - control_buf) + 1);
            control_len -= (size_t)(nl + 1 - control_buf) + (size_t)0;
            control_len = strlen(control_buf);
        }
        if (control_len >= sizeof(control_buf) - 1)
            control_len = 0;
    }
}

/* The audio device: the mixer (sound.c) is pulled from SDL's audio thread. */
static SDL_AudioDeviceID audio_dev;
static FILE *audio_dump;                          /* PORT_AUDIO_DUMP=file.raw: everything the device was given (signed 16 bit stereo, 22050 Hz) */

static void audio_callback(void *user, Uint8 *stream, int len)
{
    (void)user;
    sound_mix((int16_t *)stream, len / 4);
    if (audio_dump)
        fwrite(stream, 1, (size_t)len, audio_dump);
}

static void open_audio(void)
{
    SDL_AudioSpec want, have;

    if (getenv("PORT_MUTE") || SDL_InitSubSystem(SDL_INIT_AUDIO) != 0)
        return;
    SDL_zero(want);
    want.freq = sound_rate();
    want.format = AUDIO_S16SYS;
    want.channels = 2;
    want.samples = 1024;
    want.callback = audio_callback;
    audio_dev = SDL_OpenAudioDevice(NULL, 0, &want, &have, 0);
    if (!audio_dev) {
        fprintf(stderr, "audio: %s (the sounds play to nowhere)\n", SDL_GetError());
        return;
    }
    if (have.freq != sound_rate() || have.channels != 2 || have.format != AUDIO_S16SYS) {     /* the mixer makes exactly this; SDL converted it for the device */
        fprintf(stderr, "audio: got %d Hz %d channels instead of %d Hz stereo\n", have.freq, have.channels, sound_rate());
    }
    if (getenv("PORT_AUDIO_DUMP"))
        audio_dump = fopen(getenv("PORT_AUDIO_DUMP"), "wb");
    sound_set_device(1);
    SDL_PauseAudioDevice(audio_dev, 0);
}

typedef struct { int (*game)(void *); void *arg; int code; } Game;

static void *game_thread(void *p)
{
    Game *g = p;

    g->code = g->game(g->arg);
    front_set_finished();
    return NULL;
}

/* The window's size: the screen's (SCREEN_W x SCREEN_H), made smaller, keeping the shape, when the display cannot hold it (1024x768 on a 1366x768 laptop). The picture is scaled
 * to the window and the mouse is mapped back (SDL_RenderSetLogicalSize), and the window can be resized by hand. PORT_WINDOW=WxH asks for a size. Runs with a script or a control pipe,
 * and SDL's dummy driver, keep the screen's size: their positions are in screen pixels (see to_window), and an unscaled window makes them exact. */
static void choose_window(int *w, int *h)
{
    const char *env = getenv("PORT_WINDOW");
    const char *drv = SDL_GetCurrentVideoDriver();
    int ew = 0, eh = 0;
    SDL_Rect r;

    *w = SCREEN_W;
    *h = SCREEN_H;
    if (env && sscanf(env, "%dx%d", &ew, &eh) == 2 && ew >= 160 && eh >= 120 && ew <= 8192 && eh <= 8192) {
        *w = ew;
        *h = eh;
    } else if (!(drv && !strcmp(drv, "dummy")) && !getenv("PORT_SCRIPT") && !getenv("PORT_CONTROL") && SDL_GetDisplayUsableBounds(0, &r) == 0)
        window_size_for(SCREEN_W, SCREEN_H, r.w, r.h, w, h);
}

/* A full-screen window shows the screen scaled into the display, keeping its shape (steamdeck.h, view_scale): a whole-number scale where it loses little (the Deck's 1280x800 shows
 * 1024x768 at 1x with thin bars, every pixel square), a fractional one otherwise (smoothed, since uneven pixel doubling looks worse than a soft edge). The display is asked for its
 * desktop mode rather than the window's size, which a compositor may not have settled yet. The mouse and touch are mapped back through SDL_RenderSetLogicalSize either way. */
static void full_screen_scale(SDL_Window *win, SDL_Renderer *ren)
{
    SDL_DisplayMode dm;
    int idx = SDL_GetWindowDisplayIndex(win), integer = 0, vw = 0, vh = 0;
    double s;

    if (idx < 0)
        idx = 0;
    if (SDL_GetDesktopDisplayMode(idx, &dm) != 0)
        return;
    s = view_scale(SCREEN_W, SCREEN_H, dm.w, dm.h, &integer, &vw, &vh);
    SDL_RenderSetIntegerScale(ren, integer ? SDL_TRUE : SDL_FALSE);
    if (!integer)
        SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "linear");           /* read when the texture is made, which comes next */
    fprintf(stderr, "full screen: %dx%d display, %dx%d screen, scale %.3f (%s), picture %dx%d\n", dm.w, dm.h, SCREEN_W, SCREEN_H, s,
            integer ? "whole number" : "fractional, smoothed", vw, vh);
}

int front_run(int (*game)(void *), void *arg)
{
    Game g = {game, arg, 0};
    pthread_t th;
    SDL_Window *win;
    SDL_Renderer *ren;
    SDL_Texture *tex;
    uint8_t *rgb;
    unsigned seen = 0;
    int dirty = 0, win_w, win_h, deck, fullscreen;
    Uint32 t_start;

    if (getenv("PORT_HEADLESS"))                     /* automated runs (screenshots, tests) need no window */
        return game(arg);
    init_keys();
    SDL_SetHint(SDL_HINT_NO_SIGNAL_HANDLERS, "1");      /* SIGINT and SIGTERM are ours (below), not an SDL_QUIT */
    if (SDL_Init(SDL_INIT_VIDEO) != 0) {
        fprintf(stderr, "SDL_Init: %s (running without a window)\n", SDL_GetError());
        return game(arg);
    }
    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "nearest");
    SDL_SetHint(SDL_HINT_MOUSE_FOCUS_CLICKTHROUGH, "1");
    /* SDL's default (touch events make mouse events) is kept: a touch screen is a mouse to the game. Controllers: every one connected is opened (SDL queues an
     * SDL_CONTROLLERDEVICEADDED for each at start and for each plugged in later); SDL_GAMECONTROLLERCONFIG adds mappings as for any SDL program. */
    /* A Steam Deck (or Gamescope: Game mode) starts full screen, keeps hearing the pad while Steam's overlay has the focus, and shows the on-screen keyboard only for a text field.
     * Elsewhere nothing of this is on unless asked for (PORT_FULLSCREEN=1, PORT_TEXTINPUT=auto). */
    deck = deck_here();
    fullscreen = fullscreen_wanted(getenv("PORT_FULLSCREEN"), deck);
    if (deck || getenv("PORT_PAD_BACKGROUND"))
        SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");     /* before the controller subsystem starts */
    if (fullscreen)
        SDL_SetHint(SDL_HINT_VIDEO_MINIMIZE_ON_FOCUS_LOSS, "0");         /* Steam's overlay and Gamescope's own windows must not minimize the game */
    pad_on = !getenv("PORT_NOPAD");
    if (pad_on && SDL_InitSubSystem(SDL_INIT_GAMECONTROLLER) != 0)
        fprintf(stderr, "controllers: %s (the pad does not work)\n", SDL_GetError());
    choose_window(&win_w, &win_h);
    win = SDL_CreateWindow("Magic: The Gathering", SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED, win_w, win_h,
                           SDL_WINDOW_RESIZABLE | (fullscreen ? SDL_WINDOW_FULLSCREEN_DESKTOP : 0));
    ren = win ? SDL_CreateRenderer(win, -1, SDL_RENDERER_PRESENTVSYNC) : NULL;
    if (win && !ren)
        ren = SDL_CreateRenderer(win, -1, SDL_RENDERER_SOFTWARE);
    if (ren && fullscreen)
        full_screen_scale(win, ren);
    tex = ren ? SDL_CreateTexture(ren, SDL_PIXELFORMAT_RGB24, SDL_TEXTUREACCESS_STREAMING, SCREEN_W, SCREEN_H) : NULL;
    if (!tex) {
        fprintf(stderr, "SDL window: %s (running without a window)\n", SDL_GetError());
        return game(arg);
    }
    windowed = 1;
    install_signal_handlers();
    SDL_RenderSetLogicalSize(ren, SCREEN_W, SCREEN_H);       /* the mouse comes in screen pixels whatever the window's size */
    {
        const char *ti = getenv("PORT_TEXTINPUT");

        text_managed = ti ? !strcmp(ti, "auto") : deck;
    }
    if (text_managed)
        SDL_StopTextInput();
    else {
        SDL_StartTextInput();
        text_on = 1;
    }
    if (padlog_on())
        log_start(win, deck, fullscreen);
    rgb = malloc((size_t)SCREEN_W * SCREEN_H * 3);
    shot_frame = rgb;
    memset(rgb, 0, (size_t)SCREEN_W * SCREEN_H * 3);
    view_buf = malloc((size_t)SCREEN_W * SCREEN_H * 3);
    pad_init(&pad, SCREEN_W, SCREEN_H);
    pad_t = SDL_GetTicks();
    script_window = SDL_GetWindowID(win);
    open_audio();
    parse_script();
    if (getenv("PORT_CONTROL"))
#ifdef _WIN32
        control_fd = open(getenv("PORT_CONTROL"), O_RDONLY | O_CREAT | O_BINARY, 0666);
#else
        control_fd = open(getenv("PORT_CONTROL"), O_RDWR | O_NONBLOCK);
#endif
    pthread_create(&th, NULL, game_thread, &g);
    t_start = SDL_GetTicks();

    while (!front_finished()) {
        SDL_Event ev;

        if (signal_quit) {                           /* SIGINT / SIGTERM: end now, with what was written flushed */
            fflush(NULL);
            exit(0);
        }
        while (next_step < nsteps && (SDL_GetTicks() - t_start) / 1000.0 >= steps[next_step].t) {
            if (front_take_frame(rgb, &seen))        /* a shot shows the newest frame */
                SDL_UpdateTexture(tex, NULL, frame_view(rgb), SCREEN_W * 3);
            SDL_RenderClear(ren);
            SDL_RenderCopy(ren, tex, NULL, NULL);
            dirty = 0;
            run_step(&steps[next_step++], ren);
        }
        if (control_fd >= 0) {
            if (front_take_frame(rgb, &seen))
                SDL_UpdateTexture(tex, NULL, frame_view(rgb), SCREEN_W * 3);
            SDL_RenderClear(ren);
            SDL_RenderCopy(ren, tex, NULL, NULL);
            poll_control(ren);
        }
        update_text_input();
        if (SDL_WaitEventTimeout(&ev, 8)) {
            do {
                if (padlog_on())
                    log_sdl_event(&ev);
                switch (ev.type) {
                case SDL_QUIT:
                    front_push_quit();
                    break;
                case SDL_MOUSEMOTION:
                    pad_mouse(ev.motion.x, ev.motion.y);
                    front_push_mouse(IN_MOVE, ev.motion.x, ev.motion.y);
                    break;
                case SDL_CONTROLLERDEVICEADDED:
                    if (pad_on)
                        pad_open(ev.cdevice.which);
                    break;
                case SDL_CONTROLLERDEVICEREMOVED:
                    if (pad_on)
                        pad_close(ev.cdevice.which);
                    break;
                case SDL_CONTROLLERAXISMOTION:
                case SDL_CONTROLLERBUTTONDOWN:
                case SDL_CONTROLLERBUTTONUP:
                    if (pad_on)
                        pad_event(&ev);
                    break;
                case SDL_MOUSEWHEEL:
                    if (ev.wheel.y)
                        front_push_mouse(IN_WHEEL, 0, ev.wheel.direction == SDL_MOUSEWHEEL_FLIPPED ? -ev.wheel.y : ev.wheel.y);
                    break;
                case SDL_MOUSEBUTTONDOWN:
                case SDL_MOUSEBUTTONUP:
                    pad_mouse(ev.button.x, ev.button.y);
                    if (ev.button.button == SDL_BUTTON_LEFT || ev.button.button == SDL_BUTTON_RIGHT) {
                        int down = ev.type == SDL_MOUSEBUTTONDOWN, left = ev.button.button == SDL_BUTTON_LEFT;

                        front_push_mouse(left ? (down ? IN_DOWN : IN_UP) : (down ? IN_RDOWN : IN_RUP), ev.button.x, ev.button.y);
                    }
                    break;
                case SDL_WINDOWEVENT:
                    if (ev.window.event == SDL_WINDOWEVENT_FOCUS_LOST) {       /* keys let go while elsewhere would stay down */
                        flush_pending(-1);
                        release_all();
                        pad_release();           /* so is what the pad held */
                    }
                    break;
                case SDL_KEYDOWN:
                case SDL_KEYUP: {
                    int sc = ev.key.keysym.scancode;
                    Key k = sc < SDL_NUM_SCANCODES ? keymap[sc] : (Key){0, 0};

                    if (!k.vk)
                        break;
                    if (ev.type == SDL_KEYDOWN) {
                        flush_pending(-1);
                        held[sc] = 1;
                        held_key[sc] = k;
                        if (fixed_char(k.vk) >= 0 || k.vk < 0x10 || (k.vk >= 0x10 && k.vk <= 0x14) || (k.vk >= 0x21 && k.vk <= 0x2E) || (k.vk >= 0x70 && k.vk <= 0x7B))
                            front_push_key(k.vk, k.sc, 1, fixed_char(k.vk), ev.key.repeat != 0);
                        else if (!text_on)         /* no text will follow (SDL's text input is off): the character is the US layout's, as the game's own text boxes work it out (none with Ctrl or Alt down) */
                            front_push_key(k.vk, k.sc, 1, (held[SDL_SCANCODE_LCTRL] || held[SDL_SCANCODE_RCTRL] || held[SDL_SCANCODE_LALT] || held[SDL_SCANCODE_RALT]) ? -1 : textin_char_for_key(k.vk, shift_held()), ev.key.repeat != 0);
                        else
                            pend = (Pending){k, 1, ev.key.repeat != 0};
                    } else {
                        flush_pending(-1);
                        held[sc] = 0;
                        front_push_key(k.vk, k.sc, 0, -1, 0);
                    }
                    break;
                }
                case SDL_TEXTINPUT:
                    handle_text(ev.text.text);
                    break;
                default:
                    break;
                }
            } while (SDL_PollEvent(&ev));
            flush_pending(-1);                       /* a key whose text did not follow in the batch types nothing */
        }
        pad_tick();
        if (pad_on)
            pad_nav_answers();
        if (front_take_frame(rgb, &seen))
            dirty = 1;
        if (pad_view_changed())
            dirty = 1;
        if (dirty) {
            SDL_UpdateTexture(tex, NULL, frame_view(rgb), SCREEN_W * 3);
            SDL_RenderClear(ren);
            SDL_RenderCopy(ren, tex, NULL, NULL);
            SDL_RenderPresent(ren);
            dirty = 0;
        }
    }
    pthread_join(th, NULL);
    if (audio_dev) {
        sound_set_device(0);
        SDL_CloseAudioDevice(audio_dev);
        if (audio_dump)
            fclose(audio_dump);
    }
    for (int i = 0; i < MAX_PADS; i++)
        if (pads[i])
            SDL_GameControllerClose(pads[i]);
    free(rgb);
    free(view_buf);
    SDL_DestroyTexture(tex);
    SDL_DestroyRenderer(ren);
    SDL_DestroyWindow(win);
    SDL_Quit();
    return g.code;
}

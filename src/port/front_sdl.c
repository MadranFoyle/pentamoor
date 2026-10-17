/* front_sdl.c - the window half of the front end, over SDL2: shows the composed frames, turns the mouse and keyboard into queued events. */
#include <SDL.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <ctype.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <unistd.h>

#include "display.h"
#include "front.h"
#include "pad.h"
#include "plat.h"
#include "port.h"
#include "gdi_int.h"
#include "navwm.h"
#include "padlog.h"
#include "sched.h"
#include "steamdeck.h"
#include "textin.h"
#include "touch.h"
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
static uint8_t phys[SDL_NUM_SCANCODES];            /* keys physically down, whether or not the game was told (the display's own shortcuts look at the modifiers) */
static uint8_t swallowed[SDL_NUM_SCANCODES];       /* keys the display took (F11, Alt+Enter): their release is not the game's either */
static uint8_t alt_def[SDL_NUM_SCANCODES];         /* an Alt that is down but has not been told to the game yet: Alt+Enter is the display's, and a game that treats any key as "continue" must not see the Alt of it */
static uint8_t alt_eaten[SDL_NUM_SCANCODES];       /* an Alt that went into a display shortcut: its release is not the game's either */

static void flush_pending(int ch)
{
    if (!pend.pending)
        return;
    front_push_key(pend.k.vk, pend.k.sc, 1, ch, pend.repeat);
    pend.pending = 0;
}

/* tell the game about the Alts that were held back (another key, a click, or the Alt's own release needs them to have been down) */
static void flush_alt(void)
{
    int sc;

    for (sc = 0; sc < SDL_NUM_SCANCODES; sc++)
        if (alt_def[sc]) {
            alt_def[sc] = 0;
            held[sc] = 1;
            held_key[sc] = keymap[sc];
            front_push_key(keymap[sc].vk, keymap[sc].sc, 1, -1, 0);
        }
}

/* the Alts that were held back went into a display shortcut: the game never hears of them */
static void eat_alt(void)
{
    int sc;

    for (sc = 0; sc < SDL_NUM_SCANCODES; sc++)
        if (alt_def[sc]) {
            alt_def[sc] = 0;
            alt_eaten[sc] = 1;
        }
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
    memset(alt_def, 0, sizeof(alt_def));
    memset(alt_eaten, 0, sizeof(alt_eaten));
    memset(phys, 0, sizeof(phys));
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

/* The mouse events a script or the control pipe pushes carry this as `which`: their position is already a picture pixel (what the script said), so the loop does not map it
 * from window coordinates. Real events (a mouse, a touch) are mapped by display_to_screen. */
#define SCRIPT_MOUSE 0x5C12u
static int mouse_x, mouse_y;                       /* the last pointer position the game was given, picture pixels */

static void push_mouse_motion(int x, int y)
{
    SDL_Event e;

    memset(&e, 0, sizeof(e));
    e.type = SDL_MOUSEMOTION;
    e.motion.windowID = script_window;
    e.motion.which = SCRIPT_MOUSE;
    e.motion.x = x;
    e.motion.y = y;
    SDL_PushEvent(&e);
}

static void push_mouse_button(int right, int down, int x, int y)
{
    SDL_Event e;

    memset(&e, 0, sizeof(e));
    e.type = down ? SDL_MOUSEBUTTONDOWN : SDL_MOUSEBUTTONUP;
    e.button.windowID = script_window;
    e.button.which = SCRIPT_MOUSE;
    e.button.button = right ? SDL_BUTTON_RIGHT : SDL_BUTTON_LEFT;
    e.button.state = down ? SDL_PRESSED : SDL_RELEASED;
    e.button.x = x;
    e.button.y = y;
    SDL_PushEvent(&e);
}

static void display_print_view(const char *why);
static void winshot(const char *path);

/* A finger event for a picture pixel, as SDL would deliver it (a position as a fraction of the window): the whole of the touch path is then exercised, the display's mapping included. */
static void push_finger(Uint32 type, int id, int px, int py);

static void run_step(const Step *s)
{
    SDL_Event e;
    int x, y, id;

    memset(&e, 0, sizeof(e));
    if (!strcmp(s->cmd, "move") && sscanf(s->arg, "%d %d", &x, &y) == 2) {
        push_mouse_motion(x, y);
    } else if (!strcmp(s->cmd, "down") || !strcmp(s->cmd, "up") || !strcmp(s->cmd, "rdown") || !strcmp(s->cmd, "rup")) {
        int x2 = 0, y2 = 0;

        if (sscanf(s->arg, "%d %d", &x2, &y2) == 2) {                 /* the position is given (or the last one stays) */
            push_mouse_motion(x2, y2);
            x = x2;
            y = y2;
        } else {
            x = mouse_x;
            y = mouse_y;
        }
        push_mouse_button(s->cmd[0] == 'r', s->cmd[s->cmd[0] == 'r'] == 'd', x, y);
    } else if (!strcmp(s->cmd, "click") && sscanf(s->arg, "%d %d", &x, &y) == 2) {       /* move, press, release */
        push_mouse_motion(x, y);
        push_mouse_button(0, 1, x, y);
        push_mouse_button(0, 0, x, y);
    } else if (!strcmp(s->cmd, "key")) {                 /* key NAME, or with modifiers: key ctrl+f11, key alt+return, key shift+f11 */
        SDL_Scancode mods[3];
        int nm = 0, i;
        char buf[sizeof(s->arg)], *tok = buf, *plus;
        SDL_Scancode sc;

        snprintf(buf, sizeof(buf), "%s", s->arg);
        while (nm < 3 && (plus = strchr(tok, '+')) != NULL && plus[1]) {
            *plus = 0;
            sc = !strcasecmp(tok, "ctrl") ? SDL_SCANCODE_LCTRL : !strcasecmp(tok, "alt") ? SDL_SCANCODE_LALT : !strcasecmp(tok, "shift") ? SDL_SCANCODE_LSHIFT : SDL_SCANCODE_UNKNOWN;
            if (sc != SDL_SCANCODE_UNKNOWN)
                mods[nm++] = sc;
            tok = plus + 1;
        }
        sc = scancode_named(tok);
        if (sc != SDL_SCANCODE_UNKNOWN) {
            for (i = 0; i < nm; i++)
                key_event(mods[i], 1);
            key_event(sc, 1);
            key_event(sc, 0);
            for (i = nm - 1; i >= 0; i--)
                key_event(mods[i], 0);
        }
    } else if ((!strcmp(s->cmd, "wmove") || !strcmp(s->cmd, "wclick")) && sscanf(s->arg, "%d %d", &x, &y) == 2) {       /* a pointer position in WINDOW coordinates (points), as a real mouse gives it: the display's own mapping applies */
        SDL_Event m;

        memset(&m, 0, sizeof(m));
        m.type = SDL_MOUSEMOTION;
        m.motion.windowID = script_window;
        m.motion.x = x;
        m.motion.y = y;
        SDL_PushEvent(&m);
        if (s->cmd[1] == 'c') {
            memset(&m, 0, sizeof(m));
            m.type = SDL_MOUSEBUTTONDOWN;
            m.button.windowID = script_window;
            m.button.button = SDL_BUTTON_LEFT;
            m.button.state = SDL_PRESSED;
            m.button.x = x;
            m.button.y = y;
            SDL_PushEvent(&m);
            m.type = SDL_MOUSEBUTTONUP;
            m.button.state = SDL_RELEASED;
            SDL_PushEvent(&m);
        }
    } else if ((!strcmp(s->cmd, "tdown") || !strcmp(s->cmd, "tmove") || !strcmp(s->cmd, "tup")) && sscanf(s->arg, "%d %d %d", &id, &x, &y) == 3) {       /* a finger (id) at a picture pixel: tdown 1 330 308, tmove, tup (touch.h) */
        push_finger(s->cmd[1] == 'd' ? SDL_FINGERDOWN : s->cmd[1] == 'm' ? SDL_FINGERMOTION : SDL_FINGERUP, id, x, y);
    } else if (!strcmp(s->cmd, "winshot")) {
        winshot(s->arg);
    } else if (!strcmp(s->cmd, "view")) {              /* the window, the output and where the picture is, on stderr */
        display_print_view("view");
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

static void poll_control(void)
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
                run_step(&st);
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

/* ---- the window and the picture ------------------------------------------------------------------------------------------------------------------------
 * display.h has the rules (pure, unit tested); this is the SDL half. The game's picture (SCREEN_W x SCREEN_H, RGB24) lives in a streaming texture and is drawn into the window's
 * drawable with SDL_RenderCopy to a rectangle of our own choosing, so there is no SDL_RenderSetLogicalSize and the mapping of the mouse is ours too (display_to_screen):
 *
 *   - the drawable is measured in pixels (SDL_GetRendererOutputSize), the window in points (SDL_GetWindowSize); on a Retina Mac, or with a display scaling factor, a point is two
 *     (or 1.25, 1.5...) pixels. Everything that decides a scale uses pixels. SDL_WINDOW_ALLOW_HIGHDPI is what gives a Retina window its full-resolution drawable;
 *   - three scaling modes (fit, integer, stretch) and three filters (nearest, linear, sharp: the picture is first enlarged by a whole number with nearest neighbour into a render
 *     target, then that is scaled linearly to its final size), changed at run time (Alt+Enter / F11, Ctrl+F11, Shift+F11, L3+R3 held) and kept in display.cfg in the overlay folder. */
typedef struct {
    SDL_Window *win;
    SDL_Renderer *ren;
    SDL_Texture *tex;                                   /* the game's picture */
    SDL_Texture *pre;                                   /* the "sharp" filter's enlarged copy of it (a render target); NULL when not in use */
    int pre_w, pre_h, pre_valid, pre_failed;
    int upload, reupload;                               /* the texture must get the current frame (reupload: the device lost it) */
    int max_tex;
    DisplaySettings now, start;                         /* the settings in use, and those the run started with */
    DisplayCfg file;                                    /* display.cfg as it was read */
    int persist;                                        /* display.cfg is kept (not on SDL's dummy and offscreen drivers) */
    char dir[1100];
    char last_text[1024];                               /* what display.cfg held when last written */
    int ow, oh, ww, wh;                                 /* the drawable in pixels, the window in points */
    DispView view;
    int geom_known, win_x, win_y, win_w, win_h;        /* the window's size and place when it was last a plain window (points): where leaving full screen goes back to */
    int min_cap_w, min_cap_h;                           /* the window it started at: the minimum size never exceeds it */
    int min_w, min_h;                                   /* the minimum size that was last set */
    Uint32 save_at;                                     /* when display.cfg is to be written (0: not pending) */
    Uint32 restore_until;                               /* after leaving full screen: the windowed size is put back until this tick */
    Uint32 fs_t;                                        /* when full screen was last toggled by us: the window system may not have caught up for a moment */
} Disp;

static Disp D;

static int is_fullscreen(void) { return (SDL_GetWindowFlags(D.win) & SDL_WINDOW_FULLSCREEN) != 0; }

static int driver_is_virtual(void)
{
    const char *drv = SDL_GetCurrentVideoDriver();

    return drv && (!strcmp(drv, "dummy") || !strcmp(drv, "offscreen"));
}

static void set_tex_filter(SDL_Texture *t, int linear)
{
#if SDL_VERSION_ATLEAST(2, 0, 12)
    SDL_SetTextureScaleMode(t, linear ? SDL_ScaleModeLinear : SDL_ScaleModeNearest);
#else
    (void)t;
    (void)linear;                                       /* an old SDL has the hint at creation only: nearest, and the enlarged copy linear */
#endif
}

/* the window, the drawable and where the picture goes in it, as of now */
static void refresh_view(void)
{
    SDL_GetWindowSize(D.win, &D.ww, &D.wh);
    if (SDL_GetRendererOutputSize(D.ren, &D.ow, &D.oh) != 0 || D.ow <= 0 || D.oh <= 0) {
        D.ow = D.ww;
        D.oh = D.wh;
    }
    display_layout(SCREEN_W, SCREEN_H, D.ow, D.oh, D.now.scale, &D.view);
}

static void display_print_view(const char *why)
{
    refresh_view();
    fprintf(stderr, "display (%s): %s, window %dx%d points, drawable %dx%d pixels (%.2f per point), picture %dx%d at %d,%d (scale %.3f x %.3f%s), scale %s, filter %s\n", why,
            is_fullscreen() ? "full screen" : "window", D.ww, D.wh, D.ow, D.oh, D.ww > 0 ? (double)D.ow / D.ww : 1.0, D.view.dst.w, D.view.dst.h, D.view.dst.x, D.view.dst.y,
            D.view.sx, D.view.sy, D.view.whole ? ", whole numbers" : "", scale_name(D.now.scale), filter_name(D.now.filter));
}

/* ---- mouse units ----
 * A mouse event's position is in window coordinates, which are points. Except that SDL's renderer turns the positions of the mouse events of its window into render pixels by itself once one is attached
 * (SDL_RendererEventWatch; seen with SDL 2.32 here, with or without SDL_RenderSetLogicalSize): on a Retina window a click at the point 100 arrives as 200. Which units the events come in depends on
 * the SDL (and its version, and which platform's window), so it is measured: a mouse event that is ours alone (`which` is CALIB_MOUSE) is pushed through the same path as the real ones with the position
 * CALIB_AT, and the number that comes back says by what the events are multiplied (1 for points, the pixels per point when SDL has converted them). It is measured at the start and whenever the window's
 * size or display changes (the factor is the display's). The window's size in the events' unit is then ww * scale: the drawable's own size when they are pixels, so display_to_screen works in either. */
#define CALIB_MOUSE 0x5C13u
#define CALIB_AT 100
static double mouse_scale_motion = 1.0, mouse_scale_button = 1.0;     /* by what SDL multiplies the position of a motion event, of a button event */
static Uint32 calib_t;

static void calibrate_mouse(void)
{
    SDL_Event e;

    memset(&e, 0, sizeof(e));
    e.type = SDL_MOUSEMOTION;
    e.motion.windowID = script_window;
    e.motion.which = CALIB_MOUSE;
    e.motion.x = e.motion.y = CALIB_AT;
    SDL_PushEvent(&e);
    memset(&e, 0, sizeof(e));
    e.type = SDL_MOUSEBUTTONDOWN;
    e.button.windowID = script_window;
    e.button.which = CALIB_MOUSE;
    e.button.button = SDL_BUTTON_X2;                    /* a button the game does not use */
    e.button.state = SDL_PRESSED;
    e.button.x = e.button.y = CALIB_AT;
    SDL_PushEvent(&e);
    e.type = SDL_MOUSEBUTTONUP;
    e.button.state = SDL_RELEASED;
    SDL_PushEvent(&e);
    calib_t = SDL_GetTicks();
}

static void calibrate_soon(void)
{
    if (SDL_GetTicks() - calib_t > 300)
        calibrate_mouse();
}

/* the measured factor, if it is a believable one */
static void note_calibration(double *scale, int x)
{
    double f = x / (double)CALIB_AT;

    if (f >= 0.25 && f <= 8.0)
        *scale = f;
}

/* a mouse position as SDL delivered it to the picture's pixels. A script's (marked) position is a picture pixel already, but SDL may have multiplied it on the way: that is undone. A real one is mapped
 * through the window's size in the events' unit. `button`: a button event (else motion). */
static void map_mouse(Uint32 which, int button, int *x, int *y)
{
    double sc = button ? mouse_scale_button : mouse_scale_motion;

    if (which == SCRIPT_MOUSE) {
        *x = (int)(*x / sc + (*x >= 0 ? 0.5 : -0.5));
        *y = (int)(*y / sc + (*y >= 0 ? 0.5 : -0.5));
    } else {
        refresh_view();
        display_to_screen(&D.view, SCREEN_W, SCREEN_H, D.ow, D.oh, D.ww * sc, D.wh * sc, *x, *y, x, y);
    }
    mouse_x = *x;
    mouse_y = *y;
}

/* ---- touch ----
 * A touch screen is a mouse to the game, with a right button: touch.c (pure, tested) turns the fingers into mouse actions; here are the SDL events in and the queued mouse out. It is on for an
 * iOS app and off elsewhere (SDL's own conversion of a finger into the left button stays: a Steam Deck's screen), PORT_TOUCH=1 / 0 turns it on / off. */
static Touch touch;
static int touch_on;
static int in_background;                                   /* iOS: the app is not on the screen: nothing is drawn */

static void touch_flush(void)
{
    TouchAction a;

    while (touch_next(&touch, &a)) {
        mouse_x = a.x;
        mouse_y = a.y;
        pad_mouse(a.x, a.y);
        if (a.kind != TA_MOVE && padlog_on())
            padlog("touch: %s at (%d,%d)", a.kind == TA_LDOWN ? "left button down" : a.kind == TA_LUP ? "left button up" : a.kind == TA_RDOWN ? "right button down" : "right button up", a.x, a.y);
        switch (a.kind) {
        case TA_MOVE:  front_push_mouse(IN_MOVE, a.x, a.y); break;
        case TA_LDOWN: flush_alt(); front_push_mouse(IN_DOWN, a.x, a.y); break;
        case TA_LUP:   front_push_mouse(IN_UP, a.x, a.y); break;
        case TA_RDOWN: flush_alt(); front_push_mouse(IN_RDOWN, a.x, a.y); break;
        case TA_RUP:   front_push_mouse(IN_RUP, a.x, a.y); break;
        }
    }
}

/* a finger event (x and y are fractions of the window) to the picture's pixels, through the same mapping as the mouse's: the window in the events' unit is ww * scale */
static void finger_to_pixel(const SDL_TouchFingerEvent *f, int *px, int *py)
{
    double sc = mouse_scale_button;

    refresh_view();
    display_to_screen(&D.view, SCREEN_W, SCREEN_H, D.ow, D.oh, D.ww * sc, D.wh * sc, (int)(f->x * D.ww * sc + 0.5), (int)(f->y * D.wh * sc + 0.5), px, py);
}

static void finger_event(const SDL_Event *ev)
{
    int x, y, id = (int)(ev->tfinger.fingerId & 0x7FFFFFFF);
    Uint32 now = SDL_GetTicks();

    finger_to_pixel(&ev->tfinger, &x, &y);
    if (ev->type == SDL_FINGERDOWN) {
        if (padlog_on())
            padlog("touch: finger %d down at (%d,%d)", id, x, y);
        flush_alt();
        touch_down(&touch, id, x, y, now);
    } else if (ev->type == SDL_FINGERMOTION)
        touch_move(&touch, id, x, y, now);
    else
        touch_up(&touch, id, x, y, now);
    touch_flush();
}

static void push_finger(Uint32 type, int id, int px, int py)
{
    SDL_Event e;

    refresh_view();
    memset(&e, 0, sizeof(e));
    e.type = type;
    e.tfinger.windowID = script_window;
    e.tfinger.touchId = 1;                                       /* not SDL_MOUSE_TOUCHID: the scripted finger is a real one */
    e.tfinger.fingerId = id;
    e.tfinger.x = (float)((D.view.dst.x + (double)px * D.view.dst.w / SCREEN_W) / D.ow);
    e.tfinger.y = (float)((D.view.dst.y + (double)py * D.view.dst.h / SCREEN_H) / D.oh);
    SDL_PushEvent(&e);
}

static void ensure_pre(int w, int h)
{
    if (D.pre && D.pre_w == w && D.pre_h == h)
        return;
    if (D.pre) {
        SDL_DestroyTexture(D.pre);
        D.pre = NULL;
    }
    D.pre_failed = 0;
    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "linear");           /* read when the texture is made (SDL older than 2.0.12 has no other way) */
    D.pre = SDL_CreateTexture(D.ren, SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_TARGET, w, h);
    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "nearest");
    if (!D.pre) {
        D.pre_failed = 1;
        return;
    }
    set_tex_filter(D.pre, 1);
    D.pre_w = w;
    D.pre_h = h;
    D.pre_valid = 0;
}

/* The picture into the drawable. nearest and linear are the texture drawn with that filter. sharp: where the picture is shown at a whole number of pixels per pixel (on each axis)
 * it is nearest neighbour, which is exact; where it is not, it is first enlarged by the next whole number (ceil of the scale, at most 8x) with nearest neighbour into a render
 * target and that is scaled linearly, down by less than one step, which blurs an edge by under a pixel; shown at less than 1x it is simply linear. */
static void draw_picture(void)
{
    SDL_Rect dst = {D.view.dst.x, D.view.dst.y, D.view.dst.w, D.view.dst.h};
    int sw = SCREEN_W, sh = SCREEN_H;
    int exact = dst.w % sw == 0 && dst.h % sh == 0;
    FilterMode f = D.now.filter;

    if (f == FILTER_SHARP && !exact) {
        int kx = display_prescale(sw, dst.w, 8, D.max_tex), ky = display_prescale(sh, dst.h, 8, D.max_tex);

        if ((kx > 1 || ky > 1) && SDL_RenderTargetSupported(D.ren)) {
            ensure_pre(sw * kx, sh * ky);
            if (D.pre) {
                if (!D.pre_valid) {
                    set_tex_filter(D.tex, 0);
                    SDL_SetRenderTarget(D.ren, D.pre);
                    SDL_RenderCopy(D.ren, D.tex, NULL, NULL);
                    SDL_SetRenderTarget(D.ren, NULL);
                    D.pre_valid = 1;
                }
                SDL_RenderCopy(D.ren, D.pre, NULL, &dst);
                return;
            }
        }
        set_tex_filter(D.tex, 1);
    } else
        set_tex_filter(D.tex, f == FILTER_LINEAR);
    SDL_RenderCopy(D.ren, D.tex, NULL, &dst);
}

/* the picture into the back buffer (not yet shown) */
static void render_current(void)
{
    if (D.upload || D.reupload) {
        SDL_UpdateTexture(D.tex, NULL, frame_view(shot_frame), SCREEN_W * 3);
        D.upload = D.reupload = 0;
        D.pre_valid = 0;
    }
    refresh_view();
    SDL_SetRenderDrawColor(D.ren, 0, 0, 0, 255);
    SDL_RenderClear(D.ren);
    draw_picture();
}

static void present_now(void)
{
    render_current();
    SDL_RenderPresent(D.ren);
}

/* `winshot FILE` (a test aid, like `shot`): what the window shows, at the size of its drawable in pixels (a Retina window's 2x too), as the renderer drew it: the picture, the bars, the filter. It is
 * drawn again into the back buffer and read from there, so it works whether or not the window is on screen (PORT_HIDDEN=1). */
static void winshot(const char *path)
{
    FILE *f = fopen(path, "wb");
    Uint32 *px;
    uint8_t *row;
    int x, y;

    if (!f)
        return;
    render_current();
    px = malloc((size_t)D.ow * D.oh * 4);
    row = malloc((size_t)D.ow * 3);
    if (px && row && SDL_RenderReadPixels(D.ren, NULL, SDL_PIXELFORMAT_ARGB8888, px, D.ow * 4) == 0) {
        fprintf(f, "P6\n%d %d\n255\n", D.ow, D.oh);
        for (y = 0; y < D.oh; y++) {
            for (x = 0; x < D.ow; x++) {
                Uint32 p = px[(size_t)y * D.ow + x];

                row[3 * x] = (uint8_t)(p >> 16);
                row[3 * x + 1] = (uint8_t)(p >> 8);
                row[3 * x + 2] = (uint8_t)p;
            }
            fwrite(row, 3, (size_t)D.ow, f);
        }
    } else
        fprintf(stderr, "winshot: %s\n", SDL_GetError());
    free(px);
    free(row);
    fclose(f);
}

/* the player can also leave or enter full screen without us (the green button on a Mac, a window manager's key): the state is what the window says, except just after our own change */
static int sync_fullscreen(void)
{
    int was = D.now.fullscreen;

    if (SDL_GetTicks() - D.fs_t >= 2000)
        D.now.fullscreen = is_fullscreen();
    return D.now.fullscreen != was;
}

/* ---- keeping display.cfg ---- */
static void save_soon(void) { D.save_at = SDL_GetTicks() + 1000; if (!D.save_at) D.save_at = 1; }

static void save_cfg(void)
{
    DisplayCfg out = D.file;
    DisplaySettings s = D.now;
    char text[1024];

    D.save_at = 0;
    if (!D.persist)
        return;
    sync_fullscreen();
    s = D.now;
    s.has_window = D.geom_known;
    s.win_w = D.win_w;
    s.win_h = D.win_h;
    s.has_pos = D.geom_known && D.win_x != INT_MIN;
    s.win_x = D.win_x;
    s.win_y = D.win_y;
    display_cfg_update(&out, &D.start, &s);
    if (dcfg_format(&out, text, sizeof(text)) < 0 || !strcmp(text, D.last_text))
        return;
    if (dcfg_save(D.dir, &out))
        snprintf(D.last_text, sizeof(D.last_text), "%s", text);
    else
        fprintf(stderr, "display: cannot write %s in %s (the settings are not kept)\n", DISPLAY_CFG_NAME, D.dir);
}

/* the minimum size follows the drawable's scale (a point may be one pixel or two) */
static void update_min_size(void)
{
    int mw, mh;
    double dpi;

    if (driver_is_virtual())
        return;
    SDL_GetWindowSize(D.win, &D.ww, &D.wh);
    if (SDL_GetRendererOutputSize(D.ren, &D.ow, &D.oh) != 0 || D.ww <= 0)
        return;
    dpi = (double)D.ow / D.ww;
    display_min_window(SCREEN_W, SCREEN_H, dpi, D.min_cap_w, D.min_cap_h, &mw, &mh);
    if (mw != D.min_w || mh != D.min_h) {                 /* only when it changed: setting it can make the window system send events */
        D.min_w = mw;
        D.min_h = mh;
        SDL_SetWindowMinimumSize(D.win, mw, mh);
    }
}

/* a window event moved or resized the window: note its size and place while it is a plain window */
static void note_geometry(void)
{
    Uint32 fl = SDL_GetWindowFlags(D.win);
    int x, y, w, h;

    update_min_size();
    if (sync_fullscreen())
        save_soon();
    if ((fl & (SDL_WINDOW_FULLSCREEN | SDL_WINDOW_MINIMIZED | SDL_WINDOW_MAXIMIZED)) || SDL_GetTicks() < D.restore_until || driver_is_virtual())
        return;
    SDL_GetWindowSize(D.win, &w, &h);
    SDL_GetWindowPosition(D.win, &x, &y);
    if (w <= 0 || h <= 0)
        return;
    if (D.geom_known && w == D.win_w && h == D.win_h && x == D.win_x && y == D.win_y)
        return;
    D.geom_known = 1;
    D.win_w = w;
    D.win_h = h;
    D.win_x = x;
    D.win_y = y;
    save_soon();
}

#ifndef PORT_IOS
static void set_fullscreen(int on)
{
    if (on == is_fullscreen())
        return;
    if (on) {
        note_geometry();                                  /* where to come back to */
        SDL_SetWindowFullscreen(D.win, SDL_WINDOW_FULLSCREEN_DESKTOP);
    } else {
        SDL_SetWindowFullscreen(D.win, 0);
        if (D.geom_known) {                               /* SDL goes back to the size it remembers; a window system that is slow or forgetful is told again below */
            SDL_SetWindowSize(D.win, D.win_w, D.win_h);
            if (D.win_x != INT_MIN)
                SDL_SetWindowPosition(D.win, D.win_x, D.win_y);
            D.restore_until = SDL_GetTicks() + 1500;
            if (!D.restore_until)
                D.restore_until = 1;
        }
    }
    D.now.fullscreen = on;
    D.fs_t = SDL_GetTicks();
    save_soon();
}
#endif

/* while a window is being put back after full screen, once its size event shows the wrong size, set it again */
static void restore_step(void)
{
    static Uint32 last;
    Uint32 now = SDL_GetTicks();
    int w, h;

    if (!D.restore_until)
        return;
    if (now >= D.restore_until) {
        D.restore_until = 0;
        note_geometry();
        return;
    }
    if (is_fullscreen() || !D.geom_known || now - last < 100)
        return;
    last = now;
    SDL_GetWindowSize(D.win, &w, &h);
    if (w != D.win_w || h != D.win_h) {
        SDL_SetWindowSize(D.win, D.win_w, D.win_h);
        if (D.win_x != INT_MIN)
            SDL_SetWindowPosition(D.win, D.win_x, D.win_y);
    }
}

static void display_act(DispAction a)
{
    char text[96];

    switch (a) {
    case DA_FULLSCREEN:
#ifndef PORT_IOS
        set_fullscreen(!is_fullscreen());       /* (an iOS app's window is always the whole screen) */
#endif
        break;
    case DA_SCALE:
        D.now.scale = scale_cycle(D.now.scale);
        break;
    case DA_FILTER:
        D.now.filter = filter_cycle(D.now.filter);
        break;
    default:
        return;
    }
    if (a != DA_FULLSCREEN) {
        display_notice_text(D.now.scale, D.now.filter, text, sizeof(text));
        display_notice(text, port_now_ms());
        wm_dirty = 1;                                     /* the compositor draws it into the next frame */
        save_soon();
    }
    D.pre_valid = 0;
    display_print_view(a == DA_FULLSCREEN ? "full screen toggled" : a == DA_SCALE ? "scaling cycled" : "filter cycled");
}

/* ---- opening the window ---- */
static int display_open(int deck)
{
    char warn[256];
    const char *drv;
    int virt, fs, hidden, w, h, uw = 0, uh = 0, pw, ph, idx, n, i;
    SDL_Rect r;
    SDL_RendererInfo info;
    DispRect rects[8];
    double dpi;
    Uint32 flags;
    int px = SDL_WINDOWPOS_CENTERED, py = SDL_WINDOWPOS_CENTERED;

    snprintf(D.dir, sizeof(D.dir), "%s", paths_overlay_default());
    dcfg_load(D.dir, &D.file);
    display_resolve(&D.file, getenv("PORT_FULLSCREEN"), getenv("PORT_SCALE"), getenv("PORT_FILTER"), getenv("PORT_WINDOW"), deck, &D.now, warn, sizeof(warn));
    if (warn[0])
        fputs(warn, stderr);
    D.start = D.now;
    D.win_x = INT_MIN;
    fs = D.now.fullscreen;
    drv = SDL_GetCurrentVideoDriver();
    virt = drv && (!strcmp(drv, "dummy") || !strcmp(drv, "offscreen"));
    D.persist = !virt;
    pw = D.now.has_window ? D.now.win_w : SCREEN_W;
    ph = D.now.has_window ? D.now.win_h : SCREEN_H;
    if (virt) {                                           /* no real window: its size is the picture's, so a run with a script is exact and the same everywhere */
        pw = SCREEN_W;
        ph = SCREEN_H;
    }
    hidden = getenv("PORT_HIDDEN") && !fs;                /* a test aid: the window is made, drawn to and read back (`winshot`) but never shown */
    flags = SDL_WINDOW_RESIZABLE | SDL_WINDOW_ALLOW_HIGHDPI | (fs ? SDL_WINDOW_FULLSCREEN_DESKTOP : SDL_WINDOW_HIDDEN);
    D.win = SDL_CreateWindow("Pentamoor", px, py, pw, ph, flags);
    D.ren = D.win ? SDL_CreateRenderer(D.win, -1, SDL_RENDERER_PRESENTVSYNC) : NULL;
    if (D.win && !D.ren)
        D.ren = SDL_CreateRenderer(D.win, -1, SDL_RENDERER_SOFTWARE);
    if (!D.ren)
        return 0;
    D.max_tex = SDL_GetRendererInfo(D.ren, &info) == 0 ? info.max_texture_width < info.max_texture_height ? info.max_texture_width : info.max_texture_height : 0;
    D.tex = SDL_CreateTexture(D.ren, SDL_PIXELFORMAT_RGB24, SDL_TEXTUREACCESS_STREAMING, SCREEN_W, SCREEN_H);
    if (!D.tex)
        return 0;
    if (!virt) {
        /* the size and place: the player's last (display.cfg, PORT_WINDOW), else the largest whole-number multiple of the picture that fits 90% of what the display has free */
        idx = SDL_GetWindowDisplayIndex(D.win);
        if (idx < 0)
            idx = 0;
        if (SDL_GetDisplayUsableBounds(idx, &r) == 0 || SDL_GetDisplayBounds(idx, &r) == 0) {
            uw = r.w;
            uh = r.h;
        }
        n = SDL_GetNumVideoDisplays();
        for (i = 0; i < 8 && i < n; i++) {
            SDL_Rect b;

            if (SDL_GetDisplayUsableBounds(i, &b) == 0 || SDL_GetDisplayBounds(i, &b) == 0)
                rects[i] = (DispRect){b.x, b.y, b.w, b.h};
            else
                rects[i] = (DispRect){0, 0, 0, 0};
        }
        refresh_view();
        dpi = D.ww > 0 ? (double)D.ow / D.ww : 1.0;
        display_initial_window(SCREEN_W, SCREEN_H, uw, uh, dpi, &w, &h);
        D.min_cap_w = w;
        D.min_cap_h = h;
        if (D.now.has_window) {
            w = D.now.win_w;
            h = D.now.win_h;
            if (!D.now.win_env && uw > 0 && uh > 0) {      /* a size saved on a bigger display: no larger than this one */
                if (w > uw)
                    w = uw;
                if (h > uh)
                    h = uh;
            }
            if (w < D.min_cap_w)
                D.min_cap_w = w;
            if (h < D.min_cap_h)
                D.min_cap_h = h;
        }
        {
            int mw, mh;

            display_min_window(SCREEN_W, SCREEN_H, dpi, D.min_cap_w, D.min_cap_h, &mw, &mh);
            if (w < mw)
                w = mw;
            if (h < mh)
                h = mh;
            D.min_w = mw;
            D.min_h = mh;
            SDL_SetWindowMinimumSize(D.win, mw, mh);
        }
        SDL_SetWindowSize(D.win, w, h);
        if (D.now.has_pos && display_pos_ok(D.now.win_x, D.now.win_y, w, h, rects, n < 8 ? n : 8, 64))
            SDL_SetWindowPosition(D.win, D.now.win_x, D.now.win_y);
        else if (!fs)
            SDL_SetWindowPosition(D.win, SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED);
        D.geom_known = 1;
        D.win_w = w;
        D.win_h = h;
        if (!fs) {
            if (!hidden)
                SDL_ShowWindow(D.win);
            SDL_GetWindowPosition(D.win, &D.win_x, &D.win_y);
        } else if (D.now.has_pos)
            D.win_x = D.now.win_x, D.win_y = D.now.win_y;
    } else if (!hidden)
        SDL_ShowWindow(D.win);
    D.upload = 1;
    return 1;
}

int front_run(int (*game)(void *), void *arg)
{
    Game g = {game, arg, 0};
    pthread_t th;
    uint8_t *rgb;
    unsigned seen = 0;
    int dirty = 1, deck, fullscreen;
    Uint32 t_start;
    DispCombo combo = {0, 0, 0};
    int pad_l3 = 0, pad_r3 = 0;

    if (port_env_on("PORT_HEADLESS"))                /* automated runs (screenshots, tests) need no window (PORT_HEADLESS=0 is off) */
        return game(arg);
    init_keys();
    SDL_SetHint(SDL_HINT_NO_SIGNAL_HANDLERS, "1");      /* SIGINT and SIGTERM are ours (below), not an SDL_QUIT */
#ifdef PORT_IOS
    touch_on = !getenv("PORT_TOUCH") || strcmp(getenv("PORT_TOUCH"), "0");
    SDL_SetHint(SDL_HINT_ORIENTATIONS, "LandscapeLeft LandscapeRight");
    SDL_SetHint(SDL_HINT_IOS_HIDE_HOME_INDICATOR, "1");
    SDL_SetHint("SDL_AUDIO_CATEGORY", "playback");     /* sound plays with the silent switch on, as a game's does (SDL_HINT_AUDIO_CATEGORY, SDL 2.0.22 and newer) */
#else
    touch_on = getenv("PORT_TOUCH") && !strcmp(getenv("PORT_TOUCH"), "1");
#endif
    if (touch_on) {
        SDL_SetHint(SDL_HINT_TOUCH_MOUSE_EVENTS, "0");  /* the fingers are touch.c's, not the left button */
        SDL_SetHint(SDL_HINT_MOUSE_TOUCH_EVENTS, "0");  /* and a mouse or trackpad is not also a finger */
    }
    touch_init(&touch);
    SDL_SetHint("SDL_WINDOWS_DPI_AWARENESS", "permonitorv2");     /* Windows: sharp on a scaled display instead of stretched by the system (SDL 2.24 and newer reads it; older ones ignore it) */
    if (SDL_Init(SDL_INIT_VIDEO) != 0) {
        fprintf(stderr, "SDL_Init: %s (running without a window)\n", SDL_GetError());
        return game(arg);
    }
    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "nearest");
    SDL_SetHint(SDL_HINT_MOUSE_FOCUS_CLICKTHROUGH, "1");
    SDL_SetHint(SDL_HINT_VIDEO_MINIMIZE_ON_FOCUS_LOSS, "0");           /* a full-screen game on one display must not minimize when another is clicked (or Steam's overlay, Gamescope's windows) */
    /* Touch: SDL's default (touch events make left-button mouse events) is kept unless touch.c does the fingers (above). Controllers: every one connected is opened (SDL queues an
     * SDL_CONTROLLERDEVICEADDED for each at start and for each plugged in later); SDL_GAMECONTROLLERCONFIG adds mappings as for any SDL program. */
    /* A Steam Deck (or Gamescope: Game mode) starts full screen, keeps hearing the pad while Steam's overlay has the focus, and shows the on-screen keyboard only for a text field.
     * Elsewhere nothing of this is on unless asked for (PORT_FULLSCREEN=1, PORT_TEXTINPUT=auto). */
    deck = deck_here();
#ifdef PORT_IOS
    deck = 1;                           /* the iPad is handled like a handheld: full screen (always, there), text input only for a text field (the on-screen keyboard), the pad heard whichever app has the focus */
    SDL_DisableScreenSaver();           /* the screen does not dim and lock while a duel is watched */
#endif
    if (deck || getenv("PORT_PAD_BACKGROUND"))
        SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS, "1");     /* before the controller subsystem starts */
    pad_on = !getenv("PORT_NOPAD");
    if (pad_on && SDL_InitSubSystem(SDL_INIT_GAMECONTROLLER) != 0)
        fprintf(stderr, "controllers: %s (the pad does not work)\n", SDL_GetError());
    if (!display_open(deck)) {
        fprintf(stderr, "SDL window: %s (running without a window)\n", SDL_GetError());
        return game(arg);
    }
    fullscreen = D.now.fullscreen;
    windowed = 1;
    install_signal_handlers();
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
        log_start(D.win, deck, fullscreen);
    rgb = malloc((size_t)SCREEN_W * SCREEN_H * 3);
    shot_frame = rgb;
    memset(rgb, 0, (size_t)SCREEN_W * SCREEN_H * 3);
    view_buf = malloc((size_t)SCREEN_W * SCREEN_H * 3);
    pad_init(&pad, SCREEN_W, SCREEN_H);
    pad_t = SDL_GetTicks();
    script_window = SDL_GetWindowID(D.win);
    open_audio();
    parse_script();
    if (getenv("PORT_CONTROL"))
#ifdef _WIN32
        control_fd = open(getenv("PORT_CONTROL"), O_RDONLY | O_CREAT | O_BINARY, 0666);
#else
        control_fd = open(getenv("PORT_CONTROL"), O_RDWR | O_NONBLOCK);
#endif
    calibrate_mouse();
    display_print_view("start");
    pthread_create(&th, NULL, game_thread, &g);
    t_start = SDL_GetTicks();

    while (!front_finished()) {
        SDL_Event ev;

        if (signal_quit) {                           /* SIGINT / SIGTERM: end now, with what was written flushed */
            save_cfg();
            fflush(NULL);
            exit(0);
        }
        while (next_step < nsteps && (SDL_GetTicks() - t_start) / 1000.0 >= steps[next_step].t) {
            if (front_take_frame(rgb, &seen))        /* a shot shows the newest frame */
                D.upload = dirty = 1;
            run_step(&steps[next_step++]);
        }
        if (control_fd >= 0) {
            if (front_take_frame(rgb, &seen))
                D.upload = dirty = 1;
            poll_control();
        }
        update_text_input();
        if (touch_on && touch_active(&touch)) {
            static int was_map = -1;
            int on_map = pace_map_active();

            if (on_map != was_map && padlog_on())
                padlog("touch: the world map's loop is %s", on_map ? "running: a held finger is a held button" : "not running: a held finger becomes a long press");
            was_map = on_map;
            touch_set_hold_press(&touch, on_map);                 /* on the world map a held finger is a held button (the party walks); elsewhere it is a long press (right click) in the end */
            touch_tick(&touch, SDL_GetTicks());
            touch_flush();
        }
        if (SDL_WaitEventTimeout(&ev, 8)) {
            do {
                if (padlog_on())
                    log_sdl_event(&ev);
                switch (ev.type) {
                case SDL_QUIT:
                    front_push_quit();
                    break;
                case SDL_MOUSEMOTION: {
                    int mx = ev.motion.x, my = ev.motion.y;

                    if (ev.motion.which == CALIB_MOUSE) {
                        note_calibration(&mouse_scale_motion, ev.motion.x);
                        break;
                    }
                    map_mouse(ev.motion.which, 0, &mx, &my);
                    pad_mouse(mx, my);
                    front_push_mouse(IN_MOVE, mx, my);
                    break;
                }
                case SDL_CONTROLLERDEVICEADDED:
                    if (pad_on)
                        pad_open(ev.cdevice.which);
                    break;
                case SDL_CONTROLLERDEVICEREMOVED:
                    pad_l3 = pad_r3 = 0;
                    if (pad_on)
                        pad_close(ev.cdevice.which);
                    break;
                case SDL_CONTROLLERAXISMOTION:
                case SDL_CONTROLLERBUTTONDOWN:
                case SDL_CONTROLLERBUTTONUP:
                    if (ev.type != SDL_CONTROLLERAXISMOTION) {              /* the two sticks pressed in together for a second: full screen on or off (display.h) */
                        if (ev.cbutton.button == SDL_CONTROLLER_BUTTON_LEFTSTICK)
                            pad_l3 = ev.type == SDL_CONTROLLERBUTTONDOWN;
                        else if (ev.cbutton.button == SDL_CONTROLLER_BUTTON_RIGHTSTICK)
                            pad_r3 = ev.type == SDL_CONTROLLERBUTTONDOWN;
                    }
                    if (pad_on)
                        pad_event(&ev);
                    break;
                case SDL_FINGERDOWN:
                case SDL_FINGERMOTION:
                case SDL_FINGERUP:
                    if (touch_on && ev.tfinger.touchId != SDL_MOUSE_TOUCHID)
                        finger_event(&ev);
                    break;
                case SDL_APP_WILLENTERBACKGROUND:      /* iOS: nothing may be drawn once the app is in the background (the system ends an app that does) */
                    in_background = 1;
                    flush_pending(-1);
                    release_all();
                    pad_release();
                    break;
                case SDL_APP_DIDENTERFOREGROUND:
                    in_background = 0;
                    dirty = D.upload = D.reupload = 1;
                    break;
                case SDL_MOUSEWHEEL:
                    if (ev.wheel.y)
                        front_push_mouse(IN_WHEEL, 0, ev.wheel.direction == SDL_MOUSEWHEEL_FLIPPED ? -ev.wheel.y : ev.wheel.y);
                    break;
                case SDL_MOUSEBUTTONDOWN:
                case SDL_MOUSEBUTTONUP: {
                    int mx = ev.button.x, my = ev.button.y;

                    if (ev.button.which == CALIB_MOUSE) {
                        if (ev.type == SDL_MOUSEBUTTONDOWN)
                            note_calibration(&mouse_scale_button, ev.button.x);
                        break;
                    }
                    map_mouse(ev.button.which, 1, &mx, &my);
                    if (ev.type == SDL_MOUSEBUTTONDOWN)
                        flush_alt();                 /* Alt+click is the game's */
                    pad_mouse(mx, my);
                    if (ev.button.button == SDL_BUTTON_LEFT || ev.button.button == SDL_BUTTON_RIGHT) {
                        int down = ev.type == SDL_MOUSEBUTTONDOWN, left = ev.button.button == SDL_BUTTON_LEFT;

                        front_push_mouse(left ? (down ? IN_DOWN : IN_UP) : (down ? IN_RDOWN : IN_RUP), mx, my);
                    }
                    break;
                }
                case SDL_WINDOWEVENT:
                    switch (ev.window.event) {
                    case SDL_WINDOWEVENT_FOCUS_LOST:       /* keys let go while elsewhere would stay down */
                        flush_pending(-1);
                        release_all();
                        pad_release();           /* so is what the pad held */
                        pad_l3 = pad_r3 = 0;
                        break;
                    case SDL_WINDOWEVENT_SIZE_CHANGED:
                    case SDL_WINDOWEVENT_RESIZED:
                    case SDL_WINDOWEVENT_MOVED:
                    case SDL_WINDOWEVENT_DISPLAY_CHANGED:
                        note_geometry();
                        if (ev.window.event != SDL_WINDOWEVENT_MOVED || SDL_GetTicks() - calib_t > 2000)
                            calibrate_soon();                  /* the factor is the display's: measure again when the window changes size or display */
                        dirty = 1;
                        break;
                    case SDL_WINDOWEVENT_EXPOSED:
                    case SDL_WINDOWEVENT_SHOWN:
                    case SDL_WINDOWEVENT_RESTORED:
                    case SDL_WINDOWEVENT_MAXIMIZED:
                        dirty = 1;
                        break;
                    default:
                        break;
                    }
                    break;
                case SDL_RENDER_TARGETS_RESET:
                case SDL_RENDER_DEVICE_RESET:
                    D.pre_valid = 0;
                    D.reupload = dirty = 1;
                    break;
                case SDL_KEYDOWN:
                case SDL_KEYUP: {
                    int sc = ev.key.keysym.scancode;
                    Key k = sc < SDL_NUM_SCANCODES ? keymap[sc] : (Key){0, 0};

                    if (sc <= 0 || sc >= SDL_NUM_SCANCODES)
                        break;
                    if (ev.type == SDL_KEYDOWN) {
                        DispKey dk = sc == SDL_SCANCODE_F11 ? DK_F11 : (sc == SDL_SCANCODE_RETURN || sc == SDL_SCANCODE_KP_ENTER) ? DK_RETURN : DK_OTHER;
                        DispAction da = dk == DK_OTHER ? DA_NONE : display_key_action(dk, phys[SDL_SCANCODE_LALT] || phys[SDL_SCANCODE_RALT],
                                                                                      phys[SDL_SCANCODE_LCTRL] || phys[SDL_SCANCODE_RCTRL],
                                                                                      phys[SDL_SCANCODE_LSHIFT] || phys[SDL_SCANCODE_RSHIFT]);

                        phys[sc] = 1;
                        if (da != DA_NONE) {                                /* the display's key: not the game's, and neither is its release; an Alt that was held back stays back */
                            if (!ev.key.repeat)
                                display_act(da);
                            swallowed[sc] = 1;
                            eat_alt();
                            break;
                        }
                    } else {
                        phys[sc] = 0;
                        if (swallowed[sc]) {
                            swallowed[sc] = 0;
                            break;
                        }
                    }
                    if (!k.vk)
                        break;
                    if (sc == SDL_SCANCODE_LALT || sc == SDL_SCANCODE_RALT) {   /* Alt is held back until another key or a click needs it: Alt+Enter is ours, a lone tap is the game's */
                        if (ev.type == SDL_KEYDOWN) {
                            if (!ev.key.repeat)
                                alt_def[sc] = 1;
                            break;
                        }
                        if (alt_def[sc]) {
                            flush_alt();
                        } else if (alt_eaten[sc]) {
                            alt_eaten[sc] = 0;
                            break;
                        }
                    }
                    if (ev.type == SDL_KEYDOWN) {
                        flush_pending(-1);
                        flush_alt();
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
        if (display_combo_step(&combo, pad_l3, pad_r3, SDL_GetTicks()))
            display_act(DA_FULLSCREEN);
        restore_step();
        if (D.save_at && (Sint32)(SDL_GetTicks() - D.save_at) >= 0)
            save_cfg();
        pad_tick();
        if (pad_on)
            pad_nav_answers();
        if (front_take_frame(rgb, &seen))
            D.upload = dirty = 1;
        if (pad_view_changed())
            D.upload = dirty = 1;
        if (dirty && !in_background) {
            present_now();
            dirty = 0;
        }
    }
    pthread_join(th, NULL);
    save_cfg();
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
    if (D.pre)
        SDL_DestroyTexture(D.pre);
    SDL_DestroyTexture(D.tex);
    SDL_DestroyRenderer(D.ren);
    SDL_DestroyWindow(D.win);
    SDL_Quit();
    return g.code;
}

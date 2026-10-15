/* pad.c - a game controller as a mouse and a keyboard (see pad.h). No SDL and no game in here: front_sdl.c feeds it and sends what it returns to the game. */
#include <math.h>
#include <string.h>

#include "pad.h"

/* ---- what to tune --------------------------------------------------------------------------------------------------------------------------------------------
 * Feel can only be judged on a real controller; these are the numbers to change (docs/notes/controller.md says what each does). */
#define PAD_DEADZONE 0.22f            /* the left stick does nothing inside this (radius, of full deflection); drift stays under it on a worn stick */
#define PAD_CURVE 2.0f                /* the response: speed follows (deflection past the dead zone) to this power: small pushes are fine, a full push is fast */
#define PAD_FULL_SPEED 1.0f           /* the cursor's speed at full deflection, in screen widths per second (so it is the same trip across the screen at 640 and at 1024) */
#define PAD_SLOW 0.25f                /* the PB_SLOW modifier (left trigger): times the speed */
#define PAD_FAST 2.0f                 /* the PB_FAST modifier (right stick click): times the speed */
#define PAD_STEP_FRAC (1.0f / 128)    /* one D-pad step, of the screen's width (8 pixels at 1024, 5 at 640) */
#define PAD_STEP_MIN 2
#define PAD_DBL_HOLD 90               /* a double click (the Y button): each press is held this long, and the button is up this long between them (ms): the two presses land well inside
                                       * the game's double-click time (500 ms) and each is held long enough for the game to see it */
#define PAD_DBL_GAP 70
#define PAD_REPEAT_DELAY 400          /* ms a D-pad direction or a repeating key is held before it repeats, and how often then */
#define PAD_REPEAT_MS 70
#define PAD_NAV_REPEAT_MS 150         /* a D-pad direction held in a duel or dialog moves to the next target this often (after PAD_REPEAT_DELAY): a card is further than a key step */
#define PAD_WALK_REACH 0.15f          /* walking aims this far (of the screen's width) from the avatar, in the direction of the stick */
/* Where the party stands on the map's screen, in 640x480 units (it never moves: the map scrolls under it). The map's walking code (Adventure_HandleLocationMenuChoice, 0x4e7a6f) takes
 * the direction from the pointer's place relative to (320, 188), scaled by width/640, in eight directions, and stops for a click in the box around it; it ignores the pointer outside the
 * map (x 64..576, y 48..328). So the target is the avatar plus a vector of PAD_WALK_REACH of the width: 154 pixels at 1024, inside the map for any direction. */
#define PAD_AVATAR_X 320
#define PAD_AVATAR_Y 188
#define PAD_TRIGGER_ON 0.5f           /* a trigger counts as a button pressed past this, released below PAD_TRIGGER_OFF */
#define PAD_TRIGGER_OFF 0.3f
#define PAD_ARROW_ON 0.5f             /* the right stick as arrow keys: starts past this, stays past PAD_ARROW_OFF */
#define PAD_ARROW_OFF 0.3f

/* The controls, in one table: each control of the pad and what it does. Keys are the game's own (virtual-key code, scan code, character): Enter 13/0x1C, Escape 27/0x01,
 * Page Up 0x21/0x49 and Page Down 0x22/0x51 (they scroll the game's lists, the deck builder's and the file dialog's among them). The sticks are not here: the left one moves
 * the cursor, the right one is the arrow keys and eight directions (the castle's and the dungeons' walking, a list's rows). docs/notes/controller.md and the README's Controls list this table. */
static const PadBind binds[] = {
    /* btn         action       vk    sc     ch  rep dx dy */
    {PAD_A,      PB_LCLICK, 0,    0,     -1, 0, 0,  0},       /* left click; held while held (drags, walking on the map) */
    {PAD_B,      PB_RCLICK, 0,    0,     -1, 0, 0,  0},       /* right click (a card's menu in a duel) */
    {PAD_X,      PB_KEY,    13,   0x1C,  13, 0, 0,  0},       /* Enter: the default button */
    {PAD_Y,      PB_DCLICK, 0,    0,     -1, 0, 0,  0},       /* a double click at the cursor (on a card it lets the game pay its mana for you); not Escape: Escape closes the game on some screens */
    {PAD_START,  PB_KEY,    13,   0x1C,  13, 0, 0,  0},       /* Enter */
    {PAD_BACK,   PB_KEY,    27,   0x01,  27, 0, 0,  0},       /* Escape: cancel ("Ready to Quit?" on the map) */
    {PAD_LSTICK, PB_KEY,    32,   0x39,  32, 0, 0,  0},       /* Space (the stick pressed in): stops the party walking by the arrow keys on the map */
    {PAD_LB,     PB_KEY,    0x21, 0x49,  -1, 1, 0,  0},       /* Page Up */
    {PAD_RB,     PB_KEY,    0x22, 0x51,  -1, 1, 0,  0},       /* Page Down */
    {PAD_LT,     PB_SLOW,   0,    0,     -1, 0, 0,  0},       /* held: the cursor moves slowly (precision) */
    {PAD_RT,     PB_WALK,   0,    0,     -1, 0, 0,  0},       /* held: the left stick walks (aims the avatar's way and holds the left button) */
    {PAD_RSTICK, PB_FAST,   0,    0,     -1, 0, 0,  0},       /* held (the stick pressed in): the cursor moves fast */
    {PAD_DUP,    PB_NAV,    38,   0x48,  -1, 1, 0, -1},       /* the D-pad: in a duel, a dialog or a menu the pointer goes to the next card, button or row that way (and stays put when there is none); */
    {PAD_DDOWN,  PB_NAV,    40,   0x50,  -1, 1, 0,  1},       /* anywhere else (the map, a castle, the deck builder) it is the arrow key, repeating as a keyboard's do (walking, a list's rows) */
    {PAD_DLEFT,  PB_NAV,    37,   0x4B,  -1, 1, -1, 0},
    {PAD_DRIGHT, PB_NAV,    39,   0x4D,  -1, 1, 1,  0},
};

/* the right stick's eight directions as the game's keys: arrows, and the keypad diagonals the castles read as Home, Page Up, End and Page Down */
static const struct { uint32_t vk, sc; } dir_keys[8] = {
    {38, 0x48}, {0x21, 0x49}, {39, 0x4D}, {0x22, 0x51}, {40, 0x50}, {0x23, 0x4F}, {37, 0x4B}, {0x24, 0x47},
};

const PadBind *pad_bindings(int *n)
{
    *n = (int)(sizeof(binds) / sizeof(binds[0]));
    return binds;
}

static const PadBind *bind_of(int btn)
{
    size_t i;

    for (i = 0; i < sizeof(binds) / sizeof(binds[0]); i++)
        if (binds[i].btn == btn)
            return &binds[i];
    return NULL;
}

int pad_clamp(int v, int lo, int hi) { return v < lo ? lo : v > hi ? hi : v; }

/* ---- pure functions ------------------------------------------------------------------------------------------------------------------------------------- */
float pad_stick(float x, float y, float *ox, float *oy)
{
    float m = sqrtf(x * x + y * y), r;

    if (m > 1.0f) {                    /* the corner of a square gate: the circle's edge */
        x /= m;
        y /= m;
        m = 1.0f;
    }
    if (m <= PAD_DEADZONE) {
        *ox = *oy = 0;
        return 0;
    }
    r = powf((m - PAD_DEADZONE) / (1.0f - PAD_DEADZONE), PAD_CURVE);
    *ox = x / m * r;
    *oy = y / m * r;
    return r;
}

float pad_speed(float len, int sw, int slow, int fast)
{
    float s = len * PAD_FULL_SPEED * (float)sw;

    if (slow)
        s *= PAD_SLOW;
    if (fast)
        s *= PAD_FAST;
    return s;
}

int pad_dir8(float x, float y, int was)
{
    float m = sqrtf(x * x + y * y), a;
    int d;

    if (m < (was >= 0 ? PAD_ARROW_OFF : PAD_ARROW_ON))
        return -1;
    a = atan2f(x, -y);                                   /* 0 up, clockwise */
    d = (int)floorf(a / 0.78539816f + 0.5f);
    return ((d % 8) + 8) % 8;
}

/* ---- the state ---------------------------------------------------------------------------------------------------------------------------------------- */
static void emit(PadOut *out, int type, int x, int y, uint32_t vk, uint32_t sc, int ch, int repeat)
{
    PadAct *a;

    if (out->n >= PAD_MAXACT)
        return;
    a = &out->act[out->n++];
    a->type = type; a->x = x; a->y = y; a->vk = vk; a->sc = sc; a->ch = ch; a->repeat = repeat; a->dir = 0;
}

static void emit_nav(PadOut *out, int x, int y, int dir, int repeat)
{
    emit(out, PA_NAV, x, y, 0, 0, -1, repeat);
    if (out->n > 0 && out->act[out->n - 1].type == PA_NAV)
        out->act[out->n - 1].dir = dir;
}

void pad_init(Pad *p, int sw, int sh)
{
    memset(p, 0, sizeof(*p));
    p->dir8 = -1;
    pad_set_screen(p, sw, sh);
    p->fx = (float)(p->ix = sw / 2);
    p->fy = (float)(p->iy = sh / 2);
}

void pad_set_screen(Pad *p, int sw, int sh)
{
    p->sw = sw;
    p->sh = sh;
    p->ox = sw * PAD_AVATAR_X / 640;
    p->oy = sw * PAD_AVATAR_Y / 640;
    p->fx = (float)(p->ix = pad_clamp(p->ix, 0, sw - 1));
    p->fy = (float)(p->iy = pad_clamp(p->iy, 0, sh - 1));
}

void pad_set_origin(Pad *p, int x, int y)
{
    p->ox = pad_clamp(x, 0, p->sw - 1);
    p->oy = pad_clamp(y, 0, p->sh - 1);
}

/* the game is told where the pointer is, if that changed */
static void announce(Pad *p, PadOut *out)
{
    int x = pad_clamp((int)(p->fx + 0.5f), 0, p->sw - 1), y = pad_clamp((int)(p->fy + 0.5f), 0, p->sh - 1);

    if (x != p->ix || y != p->iy) {
        p->ix = x;
        p->iy = y;
        emit(out, PA_MOVE, x, y, 0, 0, -1, 0);
    }
}

static void put_cursor(Pad *p, float x, float y)
{
    p->fx = x < 0 ? 0 : x > (float)(p->sw - 1) ? (float)(p->sw - 1) : x;
    p->fy = y < 0 ? 0 : y > (float)(p->sh - 1) ? (float)(p->sh - 1) : y;
}

static void left_set(Pad *p, int src, int on, PadOut *out)
{
    int was = p->left_src != 0;

    if (on)
        p->left_src |= src;
    else
        p->left_src &= ~src;
    if ((p->left_src != 0) == was)
        return;
    announce(p, out);
    emit(out, was ? PA_LUP : PA_LDOWN, p->ix, p->iy, 0, 0, -1, 0);
}

static void right_set(Pad *p, int on, PadOut *out)
{
    if (on == p->right_down)
        return;
    p->right_down = on;
    announce(p, out);
    emit(out, on ? PA_RDOWN : PA_RUP, p->ix, p->iy, 0, 0, -1, 0);
}

static void key_down(Pad *p, int slot, uint32_t vk, uint32_t sc, int ch, int rep, PadOut *out)
{
    if (p->key[slot].on)
        return;
    p->key[slot].on = 1; p->key[slot].rep = rep; p->key[slot].ch = ch; p->key[slot].vk = vk; p->key[slot].sc = sc;
    p->key[slot].held = 0; p->key[slot].next = PAD_REPEAT_DELAY;
    emit(out, PA_KEYDOWN, 0, 0, vk, sc, ch, 0);
}

static void key_up(Pad *p, int slot, PadOut *out)
{
    if (!p->key[slot].on)
        return;
    p->key[slot].on = 0;
    emit(out, PA_KEYUP, 0, 0, p->key[slot].vk, p->key[slot].sc, -1, 0);
}

static int step_index(const PadBind *b) { return b->dy < 0 ? 0 : b->dy > 0 ? 1 : b->dx < 0 ? 2 : 3; }

void pad_set_nav(Pad *p, int on) { p->nav = on != 0; }

void pad_put(Pad *p, int x, int y, PadOut *out)
{
    put_cursor(p, (float)x, (float)y);
    announce(p, out);
}

/* the arrow key of a direction, tapped (the D-pad's own key: the table says which) */
void pad_tap_dir(Pad *p, int dir, PadOut *out)
{
    size_t k;

    (void)p;
    for (k = 0; k < sizeof(binds) / sizeof(binds[0]); k++)
        if (binds[k].act == PB_NAV && step_index(&binds[k]) == dir) {
            emit(out, PA_KEYDOWN, 0, 0, binds[k].vk, binds[k].sc, binds[k].ch, 0);
            emit(out, PA_KEYUP, 0, 0, binds[k].vk, binds[k].sc, -1, 0);
            return;
        }
}

static void step_once(Pad *p, const PadBind *b, PadOut *out)
{
    int px = (int)((float)p->sw * PAD_STEP_FRAC);

    if (px < PAD_STEP_MIN)
        px = PAD_STEP_MIN;
    put_cursor(p, p->fx + (float)(b->dx * px), p->fy + (float)(b->dy * px));
    announce(p, out);
}

/* walking holds the left button while the right trigger is held and the stick is pushed; it ends when either lets go */
static void walk_check(Pad *p, PadOut *out)
{
    float sx, sy;
    int walk = (p->down >> PAD_RT) & 1;

    if (p->walking && !(walk && pad_stick(p->ax[PAD_AX_LX], p->ax[PAD_AX_LY], &sx, &sy) > 0)) {
        p->walking = 0;
        left_set(p, 2, 0, out);
    }
}

void pad_button(Pad *p, int btn, int down, PadOut *out)
{
    const PadBind *b;

    if (btn < 0 || btn >= PAD_NBUTTONS || down == (int)((p->down >> btn) & 1))
        return;
    if (down) {
        p->down |= 1u << btn;
        p->active = 1;
    } else {
        p->down &= ~(1u << btn);
    }
    b = bind_of(btn);
    if (b) {
        switch (b->act) {
        case PB_LCLICK:
            left_set(p, 1, down, out);
            break;
        case PB_RCLICK:
            right_set(p, down, out);
            break;
        case PB_DCLICK:
            if (down && !p->dbl.phase) {
                p->dbl.phase = 1;
                p->dbl.t = 0;
                left_set(p, 4, 1, out);
            }
            break;
        case PB_KEY:
            if (down)
                key_down(p, btn, b->vk, b->sc, b->ch, b->rep, out);
            else
                key_up(p, btn, out);
            break;
        case PB_NAV: {
            int i = step_index(b);

            if (down) {
                p->dp[i].on = 1;
                p->dp[i].nav = p->nav;
                p->dp[i].next = PAD_REPEAT_DELAY;
                if (p->nav)
                    emit_nav(out, p->ix, p->iy, i, 0);
                else
                    key_down(p, btn, b->vk, b->sc, b->ch, b->rep, out);
            } else {
                if (p->dp[i].on && !p->dp[i].nav)
                    key_up(p, btn, out);
                p->dp[i].on = 0;
            }
            break;
        }
        case PB_STEP: {
            int i = step_index(b);

            p->step_held[i] = down ? 1 : 0;
            p->step_next[i] = PAD_REPEAT_DELAY;
            if (down)
                step_once(p, b, out);
            break;
        }
        default:
            break;
        }
    }
    walk_check(p, out);
}

int pad_axis(Pad *p, int axis, int value, PadOut *out)
{
    float v = (float)value / 32767.0f, sx, sy;
    int use = 0;

    if (axis < 0 || axis > PAD_AX_RT)
        return 0;
    v = v < -1.0f ? -1.0f : v > 1.0f ? 1.0f : v;
    p->ax[axis] = v;
    if (axis == PAD_AX_LT || axis == PAD_AX_RT) {
        int btn = axis == PAD_AX_LT ? PAD_LT : PAD_RT, on = (int)((p->down >> btn) & 1);

        if (!on && v >= PAD_TRIGGER_ON)
            pad_button(p, btn, 1, out), use = 1;
        else if (on && v < PAD_TRIGGER_OFF)
            pad_button(p, btn, 0, out);
        return use;
    }
    if (axis == PAD_AX_RX || axis == PAD_AX_RY) {
        int d = pad_dir8(p->ax[PAD_AX_RX], p->ax[PAD_AX_RY], p->dir8);

        if (d != p->dir8) {
            key_up(p, PAD_NBUTTONS, out);
            p->dir8 = d;
            if (d >= 0) {
                key_down(p, PAD_NBUTTONS, dir_keys[d].vk, dir_keys[d].sc, -1, 1, out);
                p->active = 1;
                use = 1;
            }
        }
        return use;
    }
    if (pad_stick(p->ax[PAD_AX_LX], p->ax[PAD_AX_LY], &sx, &sy) > 0) {
        p->active = 1;
        use = 1;
    }
    walk_check(p, out);
    return use;
}

void pad_step(Pad *p, int ms, PadOut *out)
{
    float sx, sy, len, dt = (float)ms / 1000.0f;
    int i, slow = 0, fast = 0, walk = 0;
    size_t k;

    if (ms <= 0 || !p->active)
        return;
    if (p->dbl.phase) {
        p->dbl.t += ms;
        while (p->dbl.phase) {
            int need = p->dbl.phase == 2 ? PAD_DBL_GAP : PAD_DBL_HOLD;

            if (p->dbl.t < need)
                break;
            p->dbl.t -= need;
            if (p->dbl.phase == 1) {
                left_set(p, 4, 0, out);
                p->dbl.phase = 2;
            } else if (p->dbl.phase == 2) {
                left_set(p, 4, 1, out);
                p->dbl.phase = 3;
            } else {
                left_set(p, 4, 0, out);
                p->dbl.phase = 0;
            }
        }
    }
    for (k = 0; k < sizeof(binds) / sizeof(binds[0]); k++) {
        if (!((p->down >> binds[k].btn) & 1))
            continue;
        slow |= binds[k].act == PB_SLOW;
        fast |= binds[k].act == PB_FAST;
        walk |= binds[k].act == PB_WALK;
    }
    len = pad_stick(p->ax[PAD_AX_LX], p->ax[PAD_AX_LY], &sx, &sy);
    if (walk && len > 0) {
        float m = sqrtf(sx * sx + sy * sy), reach = PAD_WALK_REACH * (float)p->sw;

        put_cursor(p, (float)p->ox + sx / m * reach, (float)p->oy + sy / m * reach);
        announce(p, out);
        p->walking = 1;
        left_set(p, 2, 1, out);
    } else {
        if (p->walking) {
            p->walking = 0;
            left_set(p, 2, 0, out);
        }
        if (len > 0) {
            float sp = pad_speed(len, p->sw, slow, fast);

            put_cursor(p, p->fx + sx / len * sp * dt, p->fy + sy / len * sp * dt);
            announce(p, out);
        }
    }
    for (k = 0; k < sizeof(binds) / sizeof(binds[0]); k++) {
        int idx;

        if (binds[k].act != PB_STEP)
            continue;
        idx = step_index(&binds[k]);
        if (!p->step_held[idx])
            continue;
        p->step_next[idx] -= ms;
        while (p->step_next[idx] <= 0) {
            step_once(p, &binds[k], out);
            p->step_next[idx] += PAD_REPEAT_MS;
        }
    }
    for (i = 0; i < 4; i++) {
        if (!p->dp[i].on || !p->dp[i].nav)
            continue;
        p->dp[i].next -= ms;
        while (p->dp[i].next <= 0) {
            emit_nav(out, p->ix, p->iy, i, 1);
            p->dp[i].next += PAD_NAV_REPEAT_MS;
        }
    }
    for (i = 0; i <= PAD_NBUTTONS; i++) {
        if (!p->key[i].on || !p->key[i].rep)
            continue;
        p->key[i].next -= ms;
        while (p->key[i].next <= 0) {
            emit(out, PA_KEYDOWN, 0, 0, p->key[i].vk, p->key[i].sc, p->key[i].ch, 1);
            p->key[i].next += PAD_REPEAT_MS;
        }
    }
}

void pad_release_all(Pad *p, PadOut *out)
{
    int i;

    p->walking = 0;
    p->dbl.phase = 0;
    left_set(p, 7, 0, out);
    right_set(p, 0, out);
    for (i = 0; i <= PAD_NBUTTONS; i++)
        key_up(p, i, out);
    memset(p->step_held, 0, sizeof(p->step_held));
    memset(p->dp, 0, sizeof(p->dp));
    memset(p->ax, 0, sizeof(p->ax));
    p->down = 0;
    p->dir8 = -1;
}

void pad_mouse_used(Pad *p, int x, int y, PadOut *out)
{
    if (p->active)
        pad_release_all(p, out);
    p->active = 0;
    x = pad_clamp(x, 0, p->sw - 1);
    y = pad_clamp(y, 0, p->sh - 1);
    p->fx = (float)(p->ix = x);
    p->fy = (float)(p->iy = y);
}

/* ---- the arrow ------------------------------------------------------------------------------------------------------------------------------------------ */
static const char *arrow[] = {
    "*",
    "**",
    "*o*",
    "*oo*",
    "*ooo*",
    "*oooo*",
    "*ooooo*",
    "*oooooo*",
    "*ooooooo*",
    "*oooooooo*",
    "*ooooo*****",
    "*oo*oo*",
    "*o* *oo*",
    "** *oo*",
    "*   *oo*",
    "    *oo*",
    "     *oo*",
    "     *oo*",
    "      **",
};

int pad_cursor_scale(int w) { return w >= 1024 ? 2 : 1; }

void pad_draw_cursor(uint8_t *rgb, int w, int h, int x, int y)
{
    int s = pad_cursor_scale(w), r, c, dy, dx;

    for (r = 0; r < (int)(sizeof(arrow) / sizeof(arrow[0])); r++)
        for (c = 0; arrow[r][c]; c++) {
            uint8_t v;

            if (arrow[r][c] == ' ')
                continue;
            v = arrow[r][c] == '*' ? 0 : 255;
            for (dy = 0; dy < s; dy++)
                for (dx = 0; dx < s; dx++) {
                    int px = x + c * s + dx, py = y + r * s + dy;

                    if (px >= 0 && px < w && py >= 0 && py < h)
                        rgb[((size_t)py * (size_t)w + (size_t)px) * 3] = rgb[((size_t)py * (size_t)w + (size_t)px) * 3 + 1] = rgb[((size_t)py * (size_t)w + (size_t)px) * 3 + 2] = v;
                }
        }
}

/* navwm.c - the D-pad's targets, read off the window tree (see navwm.h). The game's duel is made of windows: a child window for every card (MAGICGAME_CardClass: "Hand Card" in your hand's list,
 * "In-play Card" in a territory), one each for the life totals, the graveyards and libraries, the mana pools, the phase column and the prompt bar's buttons. A click goes to whichever of them
 * wm_hit_test says is under the pointer, so the same windows, asked the same way, are exactly where a click lands. Nothing of the game's own code or data is read. */
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "gdi.h"
#include "sched.h"
#include "navwm.h"
#include "wm.h"

#define MF_GRAYED 1
#define MF_DISABLED 2
#define MF_SEPARATOR 0x800
#define ZONE_PLAYERS 1                          /* the life totals and faces */
#define ZONE_PILES 2                            /* graveyards and libraries */

typedef struct { int x0, y0, x1, y1; } Rc;

static int cls_is(const Window *w, const char *name) { return w->cname && !strcasecmp(w->cname, name); }

static const Window *parent_of(const Window *w) { return w->parent ? wm_window(w->parent) : NULL; }

/* the window and every ancestor are shown */
static int shown(const Window *w)
{
    for (; w; w = parent_of(w))
        if (!w->visible)
            return 0;
    return 1;
}

static int is_below(const Window *w, uint32_t top)
{
    for (; w; w = parent_of(w))
        if (w->hwnd == top)
            return 1;
    return 0;
}

/* The window's rectangle as it is seen: clipped to the client areas of its parents (a popup is not clipped by its owner) and to the screen. 0 if nothing is left. */
static int clipped_rect(const Window *w, Rc *r)
{
    const Window *cur = w, *p = parent_of(w);

    wm_abs_rect(w, &r->x0, &r->y0, &r->x1, &r->y1);
    while (p && !((cur->style & WS_POPUP) && !(cur->style & WS_CHILD))) {
        int ox, oy, cw, ch;

        wm_client_origin(p, &ox, &oy);
        wm_client_size(p, &cw, &ch);
        if (r->x0 < ox) r->x0 = ox;
        if (r->y0 < oy) r->y0 = oy;
        if (r->x1 > ox + cw) r->x1 = ox + cw;
        if (r->y1 > oy + ch) r->y1 = oy + ch;
        cur = p;
        p = parent_of(p);
    }
    if (r->x0 < 0) r->x0 = 0;
    if (r->y0 < 0) r->y0 = 0;
    if (r->x1 > screen_w) r->x1 = screen_w;
    if (r->y1 > screen_h) r->y1 = screen_h;
    return r->x1 - r->x0 > 0 && r->y1 - r->y0 > 0;
}

static int cmp_int(const void *a, const void *b) { return *(const int *)a - *(const int *)b; }

static int uniq(int *v, int n)
{
    int i, k = 0;

    qsort(v, (size_t)n, sizeof(int), cmp_int);
    for (i = 0; i < n; i++)
        if (!k || v[i] != v[k - 1])
            v[k++] = v[i];
    return k;
}

#define MAX_EDGES 48

/* The biggest piece of `r` (the window's clipped rectangle) where a click lands on `w` or one of its children: windows above it cut it up. The edges of every window that overlaps it cut
 * the rectangle into cells, inside each of which the answer of wm_hit_test is the same, so one probe a cell is enough, and it is asked the way a click is. */
static int visible_part(const Window *w, const Rc *r, Rc *out)
{
    int xs[MAX_EDGES], ys[MAX_EDGES], nx = 0, ny = 0, i, j, n = wm_window_count(), best = 0;

    xs[nx++] = r->x0; xs[nx++] = r->x1; ys[ny++] = r->y0; ys[ny++] = r->y1;
    for (i = 0; i < n; i++) {
        Window *o = wm_window_at_index(i);
        int x0, y0, x1, y1;

        if (!o || o == w || !o->visible || !wm_is_hit_target(o) || is_below(o, w->hwnd) || !shown(o))
            continue;
        wm_abs_rect(o, &x0, &y0, &x1, &y1);
        if (x1 <= r->x0 || x0 >= r->x1 || y1 <= r->y0 || y0 >= r->y1)
            continue;
        if (x0 > r->x0 && nx < MAX_EDGES) xs[nx++] = x0;
        if (x1 < r->x1 && nx < MAX_EDGES) xs[nx++] = x1;
        if (y0 > r->y0 && ny < MAX_EDGES) ys[ny++] = y0;
        if (y1 < r->y1 && ny < MAX_EDGES) ys[ny++] = y1;
    }
    nx = uniq(xs, nx);
    ny = uniq(ys, ny);
    {
        static unsigned char own[MAX_EDGES][MAX_EDGES];          /* [row][column]: a click in this cell lands on w (guest side only, one thread at a time) */
        int bi = -1, bj = -1, i0, i1, j0, j1, grew;

        for (j = 0; j + 1 < ny; j++)
            for (i = 0; i + 1 < nx; i++) {
                const Window *h = wm_window(wm_hit_test(xs[i] + (xs[i + 1] - xs[i]) / 2, ys[j] + (ys[j + 1] - ys[j]) / 2));
                int area = (xs[i + 1] - xs[i]) * (ys[j + 1] - ys[j]);

                own[j][i] = h && is_below(h, w->hwnd);
                if (own[j][i] && area > best) {
                    best = area;
                    bi = i;
                    bj = j;
                }
            }
        if (best <= 0)
            return 0;
        /* grow the biggest cell into a rectangle: the cells that only the edges of windows that are not above it cut apart are one piece again */
        i0 = i1 = bi;
        j0 = j1 = bj;
        do {
            int k;

            grew = 0;
            for (k = j0; i0 > 0 && k <= j1 && own[k][i0 - 1]; k++)
                if (k == j1) { i0--; grew = 1; break; }
            for (k = j0; i1 + 2 < nx && k <= j1 && own[k][i1 + 1]; k++)
                if (k == j1) { i1++; grew = 1; break; }
            for (k = i0; j0 > 0 && k <= i1 && own[j0 - 1][k]; k++)
                if (k == i1) { j0--; grew = 1; break; }
            for (k = i0; j1 + 2 < ny && k <= i1 && own[j1 + 1][k]; k++)
                if (k == i1) { j1++; grew = 1; break; }
        } while (grew);
        out->x0 = xs[i0]; out->x1 = xs[i1 + 1]; out->y0 = ys[j0]; out->y1 = ys[j1 + 1];
    }
    return 1;
}

/* ---- the list of targets ---------------------------------------------------------------------------------------------------------------------------------- */
typedef struct { NavTarget *t; int n, max; } Out;

static NavTarget *add(Out *o, const Rc *r, uint32_t id, int zone, int kind, const char *label)
{
    NavTarget *t;

    if (o->n >= o->max || r->x1 - r->x0 < 1 || r->y1 - r->y0 < 1)
        return NULL;
    t = &o->t[o->n++];
    memset(t, 0, sizeof(*t));
    t->x0 = r->x0; t->y0 = r->y0; t->x1 = r->x1; t->y1 = r->y1;
    t->zone = zone; t->kind = kind; t->id = id;
    if (label) {
        strncpy(t->label, label, sizeof(t->label) - 1);
        t->label[sizeof(t->label) - 1] = 0;
    }
    return t;
}

/* a window the pointer can be on, as one target: the part of it that can be seen */
static void add_window(Out *o, const Window *w, int zone, int kind)
{
    Rc r, v;

    if (!clipped_rect(w, &r) || !visible_part(w, &r, &v))
        return;
    add(o, &v, w->hwnd, zone, kind, w->title);
}

/* part of a window (a row of the mana pool, an icon of the phase column) that is there when the window itself is what a click at its middle reaches */
static void add_slot(Out *o, const Window *w, const Rc *clip, int x0, int y0, int x1, int y1, int zone, int kind, const char *label)
{
    Rc r = {x0, y0, x1, y1}, v;
    const Window *h;

    if (r.x0 < clip->x0) r.x0 = clip->x0;
    if (r.y0 < clip->y0) r.y0 = clip->y0;
    if (r.x1 > clip->x1) r.x1 = clip->x1;
    if (r.y1 > clip->y1) r.y1 = clip->y1;
    if (r.x1 <= r.x0 || r.y1 <= r.y0)
        return;
    h = wm_window(wm_hit_test((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2));
    if (!h || !is_below(h, w->hwnd))
        return;
    v = r;
    add(o, &v, w->hwnd, zone, kind, label);
}

/* ---- a duel ---------------------------------------------------------------------------------------------------------------------------------------------- */
/* The phase column (MAGICGAME_PhaseDisplayClass) is one window; the game finds the icon under a click with Pic_Subsystem_004262cf (0x4262cf): eight icons of a side, each the window's
 * width and 40/760 of its height tall, their tops at 2, 43, 84, 125, 166, 207, 248 and 289 of 760 of its height, the opponent's side from the top, yours 430/760 lower. */
static void add_phase_slots(Out *o, const Window *w)
{
    static const int top[8] = {2, 43, 84, 125, 166, 207, 248, 289};
    Rc clip;
    int ox, oy, cw, ch, side, k;
    char label[24];

    if (!clipped_rect(w, &clip))
        return;
    wm_client_origin(w, &ox, &oy);
    wm_client_size(w, &cw, &ch);
    for (side = 0; side < 2; side++)
        for (k = 0; k < 8; k++) {
            int y0 = oy + ch * top[k] / 760 + (side ? ch * 430 / 760 : 0), y1 = y0 + ch * 40 / 760;

            snprintf(label, sizeof(label), "%s phase %d", side ? "your" : "their", k + 1);
            add_slot(o, w, &clip, ox, y0, ox + cw, y1, (int)w->hwnd * 2 + side, NAVK_PHASE, label);
        }
}

/* The combat column (MAGICGAME_AttackPhaseDisplayClass) takes the phase column's place while there is an attack to assign or block: one side, the icons of Pic_Subsystem_00427a0a (0x427a0a) at 2, 43, 84,
 * 125, 166, 207 and 289 of 760 of the height (two of its phases share the one at 207), each 40/760 tall. */
static void add_attack_slots(Out *o, const Window *w)
{
    static const int top[7] = {2, 43, 84, 125, 166, 207, 289};
    Rc clip;
    int ox, oy, cw, ch, k;
    char label[24];

    if (!clipped_rect(w, &clip))
        return;
    wm_client_origin(w, &ox, &oy);
    wm_client_size(w, &cw, &ch);
    for (k = 0; k < 7; k++) {
        snprintf(label, sizeof(label), "combat phase %d", k + 1);
        add_slot(o, w, &clip, ox, oy + ch * top[k] / 760, ox + cw, oy + ch * top[k] / 760 + ch * 40 / 760, (int)w->hwnd, NAVK_PHASE, label);
    }
}

/* The mana pool (MAGICGAME_ManaSummaryClass) has six rows, one for each colour and colourless: a click in a row is `height / 6` (Ai_CalcManaRequirement, 0x4b9284's window procedure). */
static void add_mana_rows(Out *o, const Window *w)
{
    Rc clip;
    int ox, oy, cw, ch, k;
    char label[24];

    if (!clipped_rect(w, &clip))
        return;
    wm_client_origin(w, &ox, &oy);
    wm_client_size(w, &cw, &ch);
    for (k = 0; k < 6; k++) {
        snprintf(label, sizeof(label), "mana %d", k);
        add_slot(o, w, &clip, ox, oy + ch * k / 6, ox + cw, oy + ch * (k + 1) / 6, (int)w->hwnd, NAVK_MANA, label);
    }
}

static void collect_duel(Out *o)
{
    int i, n = wm_window_count();

    for (i = 0; i < n; i++) {
        Window *w = wm_window_at_index(i);
        const Window *p;

        if (!w || !w->visible || !shown(w))
            continue;
        if (cls_is(w, "MAGICGAME_CardClass") || cls_is(w, "MAGICGAME_BigCardCardClass"))
            add_window(o, w, (int)w->parent, NAVK_CARD);                       /* a zone for each hand, territory, attack or spell list */
        else if (cls_is(w, "MAGICGAME_LifeClass") || cls_is(w, "MAGICGAME_FaceClass"))
            add_window(o, w, ZONE_PLAYERS, NAVK_PLAYER);
        else if (cls_is(w, "MAGICGAME_GraveyardClass") || cls_is(w, "MAGICGAME_LibraryClass"))
            add_window(o, w, ZONE_PILES, NAVK_PILE);
        else if (cls_is(w, "MAGICGAME_ManaSummaryClass"))
            add_mana_rows(o, w);
        else if (cls_is(w, "MAGICGAME_PhaseDisplayClass"))
            add_phase_slots(o, w);
        else if (cls_is(w, "MAGICGAME_AttackPhaseDisplayClass"))
            add_attack_slots(o, w);
        else if (cls_is(w, "MAGICGAME_ScrollbarClass"))
            add_window(o, w, (int)w->hwnd, NAVK_BUTTON);
        else if (!w->proc && cls_is(w, "BUTTON") && (p = parent_of(w)) != NULL && cls_is(p, "MAGIC_TellUserClass") && w->enabled)
            add_window(o, w, (int)p->hwnd, NAVK_BUTTON);                        /* the prompt bar's Cancel and Done */
    }
}

/* ---- a dialog -------------------------------------------------------------------------------------------------------------------------------------------- */
static int has_hit_child(const Window *w)
{
    int i, n = wm_window_count();

    for (i = 0; i < n; i++) {
        Window *c = wm_window_at_index(i);

        if (c && c != w && c->visible && c->proc && is_below(c, w->hwnd) && shown(c))
            return 1;
    }
    return 0;
}

static void add_list_rows(Out *o, const Window *w)
{
    Rc clip;
    int y, rowh, rows, top, x0, x1, i;

    if (!clipped_rect(w, &clip) || w->nitems < 1 || !w->enabled)
        return;
    ui_listbox_geometry(w, &y, &rowh, &rows, &top, &x0, &x1);
    for (i = 0; i < rows; i++) {
        Rc r = {x0, y + i * rowh, x1, y + (i + 1) * rowh};
        NavTarget *t;

        if (r.y1 > clip.y1)
            break;
        t = add(o, &r, w->hwnd, (int)w->hwnd, NAVK_ROW, w->items[top + i].text);
        if (t)
            t->scroll = (top > 0 ? NAVS_UP : 0) | (top + rows < w->nitems ? NAVS_DOWN : 0);
    }
}

static void collect_dialog(Out *o, uint32_t hdlg)
{
    int i, n = wm_window_count();

    for (i = 0; i < n; i++) {
        Window *w = wm_window_at_index(i);
        Rc r;

        if (!w || w->hwnd == hdlg || !w->visible || !is_below(w, hdlg) || !shown(w) || !w->w || !w->h)
            continue;
        if (!w->proc && w->builtin) {
            if (cls_is(w, "BUTTON")) {
                if ((w->style & 0xF) != 7 && w->enabled && clipped_rect(w, &r))        /* not a group box */
                    add(o, &r, w->hwnd, (int)w->parent, NAVK_BUTTON, w->title);
            } else if (cls_is(w, "EDIT")) {
                if (w->enabled && clipped_rect(w, &r))
                    add(o, &r, w->hwnd, (int)w->parent, NAVK_FIELD, w->title);
            } else if (cls_is(w, "COMBOBOX")) {
                if (w->enabled && clipped_rect(w, &r)) {
                    if (r.y1 - r.y0 > COMBO_CLOSED_H)
                        r.y1 = r.y0 + COMBO_CLOSED_H;
                    add(o, &r, w->hwnd, (int)w->parent, NAVK_FIELD, w->title);
                }
            } else if (cls_is(w, "LISTBOX")) {
                add_list_rows(o, w);
            }
        } else if (w->proc && !cls_is(w, "STATIC") && !has_hit_child(w)) {
            add_window(o, w, (int)w->parent, NAVK_OTHER);                              /* a window of the game's own inside a dialog (the card choice) */
        }
    }
}

/* ---- a popup menu and a combo box's list ----------------------------------------------------------------------------------------------------------------------- */
static void collect_menu(Out *o)
{
    int li, levels = wm_popup_levels();

    for (li = 0; li < levels; li++) {
        int x, y, w, h, i;
        const char *text;
        uint32_t flags;
        int y0, y1, hot;

        wm_popup_geometry(li, &x, &y, &w, &h);
        for (i = 0; wm_popup_row(li, i, &text, &flags, &y0, &y1, &hot); i++) {
            Rc r = {x, y0, x + w, y1};

            if (flags & (MF_SEPARATOR | MF_GRAYED | MF_DISABLED))
                continue;
            add(o, &r, 0, li + 1, NAVK_MENU, text);
        }
    }
}

static void collect_combo(Out *o)
{
    Window *w = wm_window((uint32_t)wm_combo_open());
    int x0, y0, x1, y1, rowh, rows, i;

    if (!w)
        return;
    ui_combo_geometry(w, &x0, &y0, &x1, &y1, &rowh, &rows);
    if (w->nitems > rows)
        x1 -= 16;
    for (i = 0; i < rows && w->top + i < w->nitems; i++) {
        Rc r = {x0 + 1, y0 + 1 + i * rowh, x1 - 1, y0 + 1 + (i + 1) * rowh};
        NavTarget *t = add(o, &r, w->hwnd, (int)w->hwnd, NAVK_ROW, w->items[w->top + i].text);

        if (t)
            t->scroll = (w->top > 0 ? NAVS_UP : 0) | (w->top + rows < w->nitems ? NAVS_DOWN : 0);
    }
}

/* ---- ---------------------------------------------------------------------------------------------------------------------------------------------------- */
static int duel_on(void)
{
    int i, n = wm_window_count();

    for (i = 0; i < n; i++) {
        Window *w = wm_window_at_index(i);

        if (w && w->visible && cls_is(w, "MAGICGAME_MainClass") && shown(w))
            return 1;
    }
    return 0;
}

int navwm_mode(void)
{
    if (wm_popup_levels() > 0)
        return NAVWM_MENU;
    if (wm_combo_open())
        return NAVWM_COMBO;
    if (wm_top_dialog())
        return NAVWM_DIALOG;
    return duel_on() ? NAVWM_DUEL : NAVWM_NONE;
}

static int cmp_target(const void *a, const void *b)
{
    const NavTarget *x = a, *y = b;

    if (x->y0 != y->y0) return x->y0 - y->y0;
    if (x->x0 != y->x0) return x->x0 - y->x0;
    return x->id < y->id ? -1 : x->id > y->id ? 1 : strcmp(x->label, y->label);
}

int navwm_collect(NavTarget *out, int max, int x, int y, int *cur)
{
    Out o = {out, 0, max};
    int mode = navwm_mode(), i;

    switch (mode) {
    case NAVWM_MENU: collect_menu(&o); break;
    case NAVWM_COMBO: collect_combo(&o); break;
    case NAVWM_DIALOG: collect_dialog(&o, wm_top_dialog()); break;
    case NAVWM_DUEL: collect_duel(&o); break;
    default: break;
    }
    qsort(out, (size_t)o.n, sizeof(NavTarget), cmp_target);
    *cur = nav_find(out, o.n, x, y);
    if (*cur < 0 && mode != NAVWM_MENU && mode != NAVWM_COMBO) {          /* on a part of a window other than its biggest visible piece: the window's own target */
        uint32_t h = wm_hit_test(x, y);
        long best = 0;

        for (i = 0; i < o.n; i++)
            if (out[i].id && out[i].id == h) {
                int cx, cy;
                long d;

                nav_point(&out[i], &cx, &cy);
                d = (long)(cx - x) * (cx - x) + (long)(cy - y) * (cy - y);
                if (*cur < 0 || d < best) {
                    *cur = i;
                    best = d;
                }
            }
    }
    return o.n;
}

int navwm_pick(int x, int y, int dir, int *tx, int *ty)
{
    NavTarget t[NAV_MAXTARGETS];
    int n, cur;

    n = navwm_collect(t, NAV_MAXTARGETS, x, y, &cur);
    return nav_pick(t, n, cur, x, y, dir, tx, ty);
}

void navwm_dump(FILE *f, int x, int y)
{
    static const char *const modes[] = {"none", "menu", "combo", "dialog", "duel"};
    NavTarget t[NAV_MAXTARGETS];
    int n, cur, i;
    double t0 = port_now();

    n = navwm_collect(t, NAV_MAXTARGETS, x, y, &cur);
    fprintf(f, "  nav: mode %s, %d targets, pointer (%d,%d) on %d, found in %.1f ms\n", modes[navwm_mode()], n, x, y, cur, (port_now() - t0) * 1000.0);
    for (i = 0; i < n; i++)
        fprintf(f, "  target %d zone %d kind %d id 0x%x (%d,%d)-(%d,%d) scroll %d '%s'\n", i, t[i].zone, t[i].kind, t[i].id, t[i].x0, t[i].y0, t[i].x1, t[i].y1, t[i].scroll, t[i].label);
}

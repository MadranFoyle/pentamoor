/* navwm.c - the D-pad's targets, read off the window tree (see navwm.h). The game's duel is made of windows: a child window for every card (MAGICGAME_CardClass: "Hand Card" in your hand's list,
 * "In-play Card" in a territory), one each for the life totals, the graveyards and libraries, the mana pools, the phase column and the prompt bar's buttons. A click goes to whichever of them
 * wm_hit_test says is under the pointer, so the same windows, asked the same way, are exactly where a click lands. Nothing of the game's own code or data is read. */
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "gdi.h"
#include "sched.h"
#include "navwm.h"
#include "profile.h"
#include "screens.h"
#include "wm.h"

#define MF_GRAYED 1
#define MF_DISABLED 2
#define MF_SEPARATOR 0x800
#define ZONE_PLAYERS 1                          /* the life totals and faces */
#define ZONE_PILES 2                            /* graveyards and libraries */

typedef struct { int x0, y0, x1, y1; } Rc;

static int cls_is(const Window *w, const char *name) { return w->cname && !strcasecmp(w->cname, name); }

/* a standard control the program has not taken over: no window procedure of its own, or only a subclass (it keeps the control's looks and behaviour; the Win32 call EnumChildWindows lets 2.15's deck editor subclass its buttons) */
static int plain(const Window *w) { return !w->proc || w->subclassed; }

static const Window *parent_of(const Window *w) { return w->parent ? wm_window(w->parent) : NULL; }

/* the window and every ancestor are shown */
static int shown(const Window *w)
{
    for (; w; w = parent_of(w)) {
        if (!w->visible)
            return 0;
        if ((w->style & WS_POPUP) && !(w->style & WS_CHILD))       /* an owned top-level popup is shown whether or not its owner is (input.c, window_at) */
            return 1;
    }
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
        else if (plain(w) && cls_is(w, "BUTTON") && (p = parent_of(w)) != NULL && cls_is(p, "MAGIC_TellUserClass") && w->enabled)
            add_window(o, w, (int)p->hwnd, NAVK_BUTTON);                        /* the prompt bar's Cancel and Done */
    }
}

/* ---- the deck builder --------------------------------------------------------------------------------------------------------------------------------------- */
/* DECKDLL.DLL's (and DECK.EXE's) window is made of windows too: a MAGICDECK_CardClass child for each card of the deck (136 x 136, laid 24 pixels apart so a strip of each shows, as the duel's hand
 * is), and push buttons (Stats, Exit, the three decks). The filter bar and the row of pictures under it are one window each and draw their parts themselves (the icons are laid out by a function of
 * the game's: DECKDLL.DLL 0x10001294), which are not targets: the stick reaches those. */
static void collect_deck(Out *o)
{
    int i, n = wm_window_count();

    for (i = 0; i < n; i++) {
        Window *w = wm_window_at_index(i);
        const Window *p;

        if (!w || !w->visible || !shown(w))
            continue;
        if (cls_is(w, "MAGICDECK_CardClass"))
            add_window(o, w, (int)w->parent, NAVK_CARD);
        else if (plain(w) && cls_is(w, "BUTTON") && (p = parent_of(w)) != NULL && cls_is(p, "MAGICDECK_MainClass") && w->enabled)
            add_window(o, w, (int)p->hwnd, NAVK_BUTTON);
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

/* A spin button (msctls_updown32, "Spin1") is two arrows a click reaches: the upper half counts up, the lower half down (input.c): two targets, one above the other */
static void add_spin_halves(Out *o, const Window *w, const Rc *r, int zone)
{
    int mid = r->y0 + (r->y1 - r->y0) / 2;
    Rc up = {r->x0, r->y0, r->x1, mid}, down = {r->x0, mid, r->x1, r->y1};

    add(o, &up, w->hwnd, zone, NAVK_BUTTON, "spin up");
    add(o, &down, w->hwnd, zone, NAVK_BUTTON, "spin down");
}

/* Whether a click in the middle of the rectangle would reach `w` (nothing is on top of it): on a page of an ordinary window, controls of other pages may lie under it */
static int reachable(const Window *w, const Rc *r)
{
    const Window *h = wm_window(wm_hit_test((r->x0 + r->x1) / 2, (r->y0 + r->y1) / 2));

    return h && is_below(h, w->hwnd);
}

/* The standard control `w` as a target, if it is one the pointer can act on (a push, check or radio button, an edit box, a combo box's closed box, the rows of a list box, the two halves of a spin
 * button). `page`: on an ordinary window's page, where a control must also be the one a click at its middle reaches. Returns 1 if `w` is such a control (whether or not it made a target). */
static int add_control(Out *o, const Window *w, int page)
{
    Rc r;
    int zone = (int)w->parent;

    if (!plain(w) || !(w->builtin || w->subclassed))
        return 0;
    if (cls_is(w, "BUTTON")) {
        if ((w->style & 0xF) != 7 && w->enabled && clipped_rect(w, &r) && (!page || reachable(w, &r)))        /* not a group box */
            add(o, &r, w->hwnd, zone, NAVK_BUTTON, w->title);
    } else if (cls_is(w, "EDIT")) {
        if (w->enabled && clipped_rect(w, &r) && (!page || reachable(w, &r)))
            add(o, &r, w->hwnd, zone, NAVK_FIELD, w->title);
    } else if (cls_is(w, "COMBOBOX")) {
        if (w->enabled && clipped_rect(w, &r)) {
            if (r.y1 - r.y0 > COMBO_CLOSED_H)
                r.y1 = r.y0 + COMBO_CLOSED_H;
            if (!page || reachable(w, &r))
                add(o, &r, w->hwnd, zone, NAVK_FIELD, w->title);
        }
    } else if (cls_is(w, "LISTBOX")) {
        add_list_rows(o, w);
    } else if (cls_is(w, "msctls_updown32")) {
        if (w->enabled && clipped_rect(w, &r) && (!page || reachable(w, &r)))
            add_spin_halves(o, w, &r, zone);
    } else {
        return 0;
    }
    return 1;
}

/* The rectangles a window of the program's own tests the pointer against (wm_hotspots), as targets of no window of their own: the shell's round buttons, the pack screen's packs. A click in the middle of
 * one must reach the window itself (nothing is on top of it). */
static void add_hotspots(Out *o, const Window *root, const char *label)
{
    int i, spots[WM_HOT_MAX][4], ns;

    if (!root)
        return;
    ns = wm_hotspots(root, spots, WM_HOT_MAX);
    for (i = 0; i < ns; i++) {
        Rc r = {spots[i][0], spots[i][1], spots[i][2], spots[i][3]};

        if (r.x0 < 0) r.x0 = 0;
        if (r.y0 < 0) r.y0 = 0;
        if (r.x1 > screen_w) r.x1 = screen_w;
        if (r.y1 > screen_h) r.y1 = screen_h;
        if (r.x1 > r.x0 && r.y1 > r.y0 && wm_hit_test((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2) == root->hwnd)        /* nothing on top of it */
            add(o, &r, 0, (int)root->hwnd, NAVK_BUTTON, label);                 /* id 0: a part of the window, not a window of its own */
    }
}

static void collect_dialog(Out *o, uint32_t hdlg)
{
    int i, n = wm_window_count();

    for (i = 0; i < n; i++) {
        Window *w = wm_window_at_index(i);

        if (!w || w->hwnd == hdlg || !w->visible || !is_below(w, hdlg) || !shown(w) || !w->w || !w->h)
            continue;
        if (add_control(o, w, 0))
            continue;
        if (w->proc && !w->subclassed && !cls_is(w, "STATIC") && !has_hit_child(w))
            add_window(o, w, (int)w->parent, NAVK_OTHER);                              /* a window of the game's own inside a dialog (the card choice) */
    }
    add_hotspots(o, wm_window(hdlg), "dialog area");                                                  /* what the dialog's own procedure tests the pointer against (the pack screen's packs) */
}

/* ---- a page: an ordinary window with controls on it ------------------------------------------------------------------------------------------------------------- */
/* The Magic Shell of Spells of the Ancients (magic.exe 2.15) is one window with pages on it: standard controls (buttons, radio buttons, check boxes, edit boxes, combo boxes, spin buttons) in
 * child windows, and its five round page buttons, which are no windows: it draws them and tests the click against rectangles of its own (user32.c: wm_hotspots). Nothing is modal there, so
 * the modal dialogs' mode does not see it. */
static int page_control(const Window *w)
{
    if (!w->visible || !w->enabled || !w->w || !w->h || !plain(w) || !(w->builtin || w->subclassed) || !w->cname)
        return 0;
    if (cls_is(w, "BUTTON"))
        return (w->style & 0xF) != 7;
    return cls_is(w, "EDIT") || cls_is(w, "COMBOBOX") || cls_is(w, "msctls_updown32") || (cls_is(w, "LISTBOX") && w->nitems > 0);
}

/* A window that draws buttons of its own has standard controls as its direct children (the shell's page buttons: hidden or not) */
static int has_button_child(const Window *root)
{
    int i, n = wm_window_count();

    for (i = 0; i < n; i++) {
        const Window *w = wm_window_at_index(i);

        if (w && w->parent == root->hwnd && plain(w) && (w->builtin || w->subclassed) && cls_is(w, "BUTTON"))
            return 1;
    }
    return 0;
}

/* the window that has the page: the program's main window, if standard controls of it are shown, or the places it tests its clicks against are known (the title page of the shell has only those). No duel, deck
 * builder or modal dialog is up: navwm_mode asks those first */
static const Window *page_root(void)
{
    const Window *root = wm_window(wm_main_hwnd());
    int i, n = wm_window_count(), spots[WM_HOT_MAX][4];

    if (!root || !root->visible)
        return NULL;
    for (i = 0; i < n; i++) {
        const Window *w = wm_window_at_index(i);

        if (w && w != root && page_control(w) && is_below(w, root->hwnd) && shown(w))
            return root;
    }
    return has_button_child(root) && wm_hotspots(root, spots, WM_HOT_MAX) > 0 ? root : NULL;       /* only a window that is made of standard controls (hidden ones too): a map window that tests its clicks is not a page */
}

static void collect_page(Out *o, const Window *root)
{
    int i, n = wm_window_count();

    for (i = 0; i < n; i++) {
        Window *w = wm_window_at_index(i);

        if (!w || w == root || !w->visible || !is_below(w, root->hwnd) || !shown(w) || !w->w || !w->h)
            continue;
        add_control(o, w, 1);
    }
    add_hotspots(o, root, "page button");
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

static int class_shown(const char *name)
{
    int i, n = wm_window_count();

    for (i = 0; i < n; i++) {
        Window *w = wm_window_at_index(i);

        if (w && w->visible && cls_is(w, name) && shown(w))
            return 1;
    }
    return 0;
}

const char *navwm_mode_name(int mode)
{
    static const char *const modes[] = {"none", "menu", "combo", "dialog", "duel", "deck", "screen", "page"};

    return mode >= 0 && mode < (int)(sizeof(modes) / sizeof(modes[0])) ? modes[mode] : "?";
}

int navwm_mode(void)
{
    if (wm_popup_levels() > 0)
        return NAVWM_MENU;
    if (wm_combo_open())
        return NAVWM_COMBO;
    if (wm_top_dialog())
        return NAVWM_DIALOG;
    if (class_shown("MAGICGAME_MainClass"))
        return NAVWM_DUEL;
    if (class_shown("MAGICDECK_MainClass"))
        return NAVWM_DECK;
    if (page_root())
        return NAVWM_PAGE;
    {
        NavTarget one;

        return screens_collect(&one, 1, port_now()) > 0 ? NAVWM_SCREEN : NAVWM_NONE;          /* with no button on it the D-pad stays the arrow keys */
    }
}

/* Once a frame (front.c): what the mode needs done before the first press. A page of an ordinary window whose own buttons are not known yet (they are no windows: wm_hotspots) is asked to say
 * where they are, once, so that the D-pad can reach them from the first press on. */
void navwm_tick(void)
{
    const Window *root = wm_window(wm_main_hwnd());

    if (!root || !root->visible || root->spot_probed || wm_popup_levels() > 0 || wm_combo_open() || wm_top_dialog() || class_shown("MAGICGAME_MainClass") || class_shown("MAGICDECK_MainClass"))
        return;
    if (has_button_child(root))
        wm_hot_probe((Window *)root);
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
    case NAVWM_DECK: collect_deck(&o); break;
    case NAVWM_PAGE: collect_page(&o, page_root()); break;
    case NAVWM_SCREEN: o.n = screens_collect(out, max, port_now()); break;
    default: break;
    }
    qsort(out, (size_t)o.n, sizeof(NavTarget), cmp_target);
    *cur = nav_find(out, o.n, x, y);
    if (*cur < 0 && mode != NAVWM_MENU && mode != NAVWM_COMBO && mode != NAVWM_SCREEN) {          /* on a part of a window other than its biggest visible piece: the window's own target */
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
    int n, cur, mode_now = navwm_mode();

    n = navwm_collect(t, NAV_MAXTARGETS, x, y, &cur);
    if (cur < 0 && mode_now == NAVWM_SCREEN)                 /* the pointer is on nothing of a screen the game drew: the first press takes the nearest */
        return nav_nearest(t, n, x, y, tx, ty);
    if (cur < 0 && navwm_mode() == NAVWM_COMBO) {                /* a list that has just come down, the pointer still on its closed box: the first press goes to the choice the box shows, whichever way it is pressed */
        const Window *w = wm_window((uint32_t)wm_combo_open());
        int k = w ? w->hot - w->top : -1;

        if (k >= 0 && k < n) {
            nav_point(&t[k], tx, ty);
            return k;
        }
    }
    return nav_pick_ex(t, n, cur, x, y, dir, mode_now == NAVWM_PAGE || mode_now == NAVWM_DIALOG ? NAVF_FORM : 0, tx, ty);
}

int navwm_snap(int x, int y, int slop, int *sx, int *sy)
{
    NavTarget t[NAV_MAXTARGETS];
    int mode = navwm_mode(), n, cur;

    if (mode != NAVWM_PAGE && mode != NAVWM_DIALOG && mode != NAVWM_COMBO)
        return 0;
    n = navwm_collect(t, NAV_MAXTARGETS, x, y, &cur);
    return nav_snap(t, n, x, y, slop, sx, sy);
}

int navwm_cancel_ready(void)
{
    uint32_t hdlg = wm_top_dialog();
    const Window *d, *c;

    if (!hdlg || wm_popup_levels() > 0 || wm_combo_open())
        return 0;
    d = wm_window(hdlg);
    c = wm_dlg_item(hdlg, 2);                                  /* IDCANCEL */
    return d && !d->own_keys && c && cls_is(c, "BUTTON") && c->visible && c->enabled && shown(c);
}

void navwm_dump(FILE *f, int x, int y)
{
    NavTarget t[NAV_MAXTARGETS];
    int n, cur, i;
    double t0 = port_now();

    n = navwm_collect(t, NAV_MAXTARGETS, x, y, &cur);
    fprintf(f, "  nav: mode %s, %d targets, pointer (%d,%d) on %d, found in %.1f ms\n", navwm_mode_name(navwm_mode()), n, x, y, cur, (port_now() - t0) * 1000.0);
    for (i = 0; i < n; i++) {
        char label[sizeof(t[i].label)];
        size_t k;

        for (k = 0; k < sizeof(label); k++)                              /* a title can hold a line break (the pack screen's button says D, O, N, E one under the other): one line a target */
            label[k] = (unsigned char)t[i].label[k] < 32 && t[i].label[k] ? ' ' : t[i].label[k];
        fprintf(f, "  target %d zone %d kind %d id 0x%x (%d,%d)-(%d,%d) scroll %d '%s'\n", i, t[i].zone, t[i].kind, t[i].id, t[i].x0, t[i].y0, t[i].x1, t[i].y1, t[i].scroll, label);
    }
}

/* The duel's card the pointer is on, for the controller's "view card" button: the hwnd of the MAGICGAME_CardClass window a click at (x, y) would reach (a card of a hand, a permanent, a card in
 * the attack or the spell chain), or 0. Only in a duel with nothing on top of it (no dialog, menu or list down: navwm_mode is NAVWM_DUEL) and only in a build whose card windows answer the game's own
 * "View in full card" command (profile->viewcard.cmd). The game's cards are windows (controller-nav.md), so this is the same window wm_hit_test gives a click. */
uint32_t navwm_card_at(int x, int y)
{
    const Window *w;

    if (!profile->viewcard.cmd || navwm_mode() != NAVWM_DUEL)
        return 0;
    w = wm_window(wm_hit_test(x, y));
    if (w && !cls_is(w, "MAGICGAME_CardClass"))
        w = parent_of(w);                                  /* a card is one window; a part drawn by a child of it still means the card */
    return w && w->visible && shown(w) && cls_is(w, "MAGICGAME_CardClass") ? w->hwnd : 0;
}

/* Show the card in the game's own Full-size card window now: the command the card's right-click menu sends for "View in full card", posted to the card's window. The game then does what it does
 * after the pointer has rested on a card for three seconds (a timer), or after that menu item: it sends the Full-size card window the card. Nothing is written to the game's memory. 1 if posted. */
int navwm_view_card(int x, int y)
{
    uint32_t h = navwm_card_at(x, y);

    if (!h)
        return 0;
    wm_post(h, WM_COMMAND, profile->viewcard.cmd & 0xFFFF, 0);
    return 1;
}

/* The game's Full-size card window ("Full-size card": MAGICGAME_FullCardClass in the duel, MagicFullCardClass in the deck builder's library), if it is on the screen: the big card on the left. */
const Window *navwm_fullcard(void)
{
    int i, n = wm_window_count();

    for (i = 0; i < n; i++) {
        const Window *w = wm_window_at_index(i);

        if (w && w->visible && w->surface && (cls_is(w, "MAGICGAME_FullCardClass") || cls_is(w, "MagicFullCardClass")) && shown(w))
            return w;
    }
    return NULL;
}

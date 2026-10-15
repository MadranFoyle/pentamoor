/* menus.c - popup menus: the data (AppendMenu and friends) and the modal TrackPopupMenu the host picks an item of. */
#include <stdlib.h>
#include <string.h>

#include "gdi.h"
#include "sched.h"
#include "wm.h"

#define P(a) ((char *)(G + (a)))
#define MF_GRAYED 0x1
#define MF_DISABLED 0x2
#define MF_CHECKED 0x8
#define MF_POPUP 0x10
#define MF_BYPOSITION 0x400
#define MF_SEPARATOR 0x800
#define TPM_RETURNCMD 0x100
#define MENU_ITEM_H 18
#define MENU_SEP_H 6

typedef struct MenuItem { uint32_t id, flags, sub; char *text; } MenuItem;
typedef struct Menu { MenuItem *items; int n; } Menu;
static Menu *menus;
static int nmenus, capmenus;
#define MENU_BASE 0x9001u

static Menu *get_menu(uint32_t h)
{
    uint32_t i;

    if (h < MENU_BASE || (h - MENU_BASE) % 4)
        return NULL;
    i = (h - MENU_BASE) / 4;
    return i < (uint32_t)nmenus ? &menus[i] : NULL;
}

static uint32_t CreatePopupMenu(const uint32_t *a)
{
    (void)a;
    if (nmenus == capmenus) {
        capmenus = capmenus ? capmenus * 2 : 16;
        menus = realloc(menus, (size_t)capmenus * sizeof(*menus));
    }
    menus[nmenus] = (Menu){0, 0};
    return MENU_BASE + 4u * (uint32_t)nmenus++;
}

static int find_item(Menu *m, uint32_t key, uint32_t flags)
{
    int i;

    if (flags & MF_BYPOSITION)
        return key < (uint32_t)m->n ? (int)key : -1;
    for (i = 0; i < m->n; i++)
        if (m->items[i].id == key && !(m->items[i].flags & MF_POPUP))
            return i;
    return -1;
}

static uint32_t AppendMenuA(const uint32_t *a)
{
    Menu *m = get_menu(a[0]);
    uint32_t flags = a[1];
    MenuItem *it;

    if (!m)
        return 0;
    m->items = realloc(m->items, (size_t)(m->n + 1) * sizeof(*m->items));
    it = &m->items[m->n++];
    it->id = a[2];
    it->flags = flags;
    it->sub = (flags & MF_POPUP) ? a[2] : 0;
    it->text = strdup((flags & (MF_SEPARATOR | 0x100 | 0x4)) || !a[3] ? "" : P(a[3]));
    return 1;
}

/* InsertMenuA(menu, position, flags, id, text): before the item at `position` (an index with MF_BYPOSITION, else a command id); at the end if there is none. */
static uint32_t InsertMenuA(const uint32_t *a)
{
    Menu *m = get_menu(a[0]);
    uint32_t args[4] = {a[0], a[2], a[3], a[4]};
    int at;

    if (!m)
        return 0;
    at = a[1] == 0xFFFFFFFFu ? -1 : find_item(m, a[1], a[2]);
    if (!AppendMenuA(args))
        return 0;
    if (at >= 0 && at < m->n - 1) {
        MenuItem it = m->items[m->n - 1];

        memmove(&m->items[at + 1], &m->items[at], (size_t)(m->n - 1 - at) * sizeof(MenuItem));
        m->items[at] = it;
    }
    return 1;
}

static uint32_t ModifyMenuA(const uint32_t *a)
{
    Menu *m = get_menu(a[0]);
    int i = m ? find_item(m, a[1], a[2]) : -1;

    if (i < 0)
        return 0;
    free(m->items[i].text);
    m->items[i].id = a[3];
    m->items[i].flags = a[2] & ~(uint32_t)MF_BYPOSITION;
    m->items[i].sub = (a[2] & MF_POPUP) ? a[3] : 0;
    m->items[i].text = strdup((a[2] & (MF_SEPARATOR | 0x100 | 0x4)) || !a[4] ? "" : P(a[4]));
    return 1;
}

static uint32_t RemoveMenu(const uint32_t *a)
{
    Menu *m = get_menu(a[0]);
    int i = m ? find_item(m, a[1], a[2]) : -1;

    if (i < 0)
        return 0;
    free(m->items[i].text);
    memmove(&m->items[i], &m->items[i + 1], (size_t)(m->n - i - 1) * sizeof(*m->items));
    m->n--;
    return 1;
}

static uint32_t GetMenuItemCount(const uint32_t *a) { Menu *m = get_menu(a[0]); return m ? (uint32_t)m->n : 0xFFFFFFFFu; }
static uint32_t one(const uint32_t *a) { (void)a; return 1; }

static uint32_t set_flag(const uint32_t *a, uint32_t mask)
{
    Menu *m = get_menu(a[0]);
    int i = m ? find_item(m, a[1], a[2]) : -1;
    uint32_t before;

    if (i < 0)
        return 0xFFFFFFFFu;
    before = m->items[i].flags & mask;
    m->items[i].flags = (m->items[i].flags & ~mask) | (a[2] & mask);
    return before;
}
static uint32_t CheckMenuItem(const uint32_t *a) { return set_flag(a, MF_CHECKED); }
static uint32_t EnableMenuItem(const uint32_t *a) { return set_flag(a, MF_GRAYED | MF_DISABLED); }

/* ---- the open popup ----------------------------------------------------------------------------------------------------------- */
typedef struct Level { Menu *menu; int x, y; } Level;
typedef struct Popup { Level levels[8]; int nlevels; MenuItem *hover; int done; uint32_t choice; } Popup;
static Popup *popup;
static uint32_t swallow;

int wm_popup_open(void) { return popup != NULL; }

/* Where level `li` sits on the screen, and its size (the compositor and the hit test share it). */
void wm_popup_geometry(int li, int *x, int *y, int *w, int *h)
{
    Menu *m = popup->levels[li].menu;
    int i, mx = 8;

    *x = popup->levels[li].x;
    *y = popup->levels[li].y;
    for (i = 0; i < m->n; i++) {
        int len = (int)strlen(m->items[i].text);

        if (len > mx)
            mx = len;
    }
    *w = mx * 7 + 40;
    *h = 4;
    for (i = 0; i < m->n; i++)
        *h += (m->items[i].flags & MF_SEPARATOR) ? MENU_SEP_H : MENU_ITEM_H;
    if (*x + *w > screen_w)
        *x = *w < screen_w ? screen_w - *w : 0;
    if (*y + *h > screen_h)
        *y = *y - *h >= 0 ? *y - *h : (screen_h - *h > 0 ? screen_h - *h : 0);
}

/* The item under a screen point: the level index (-1 if none) and the item. */
static MenuItem *item_at(int x, int y, int *level)
{
    int li;

    *level = -1;
    for (li = popup->nlevels - 1; li >= 0; li--) {
        int lx, ly, w, h, i, cy;

        wm_popup_geometry(li, &lx, &ly, &w, &h);
        if (x < lx || x >= lx + w || y < ly || y >= ly + h)
            continue;
        *level = li;
        cy = ly + 2;
        for (i = 0; i < popup->levels[li].menu->n; i++) {
            MenuItem *it = &popup->levels[li].menu->items[i];
            int hh = (it->flags & MF_SEPARATOR) ? MENU_SEP_H : MENU_ITEM_H;

            if (y >= cy && y < cy + hh)
                return it;
            cy += hh;
        }
        return NULL;
    }
    return NULL;
}

static void choose(MenuItem *it)
{
    if (!it || (it->flags & (MF_SEPARATOR | MF_GRAYED | MF_DISABLED)))
        return;
    if (it->flags & MF_POPUP) {
        Menu *sub = get_menu(it->sub);
        int li = popup->nlevels - 1, lx, ly, w, h, i, cy;

        if (!sub || popup->nlevels >= 8)
            return;
        wm_popup_geometry(li, &lx, &ly, &w, &h);
        cy = ly + 2;
        for (i = 0; i < popup->levels[li].menu->n && &popup->levels[li].menu->items[i] != it; i++)
            cy += (popup->levels[li].menu->items[i].flags & MF_SEPARATOR) ? MENU_SEP_H : MENU_ITEM_H;
        popup->levels[popup->nlevels++] = (Level){sub, lx + w - 2, cy};
        return;
    }
    popup->choice = it->id;
    popup->done = 1;
}

/* Host mouse input while a popup menu is open. */
int wm_popup_mouse(int kind, int x, int y)
{
    int li;
    MenuItem *it = item_at(x, y, &li);

    if (kind == IN_MOVE) {
        if (popup->hover != it) {
            popup->hover = it;
            wm_dirty = 1;
        }
    } else if (kind == IN_DOWN || kind == IN_RDOWN) {
        if (li < 0)                                    /* a click outside dismisses the menu */
            popup->done = 1;
        else {
            popup->nlevels = li + 1;                   /* choosing in a level closes the levels opened from it */
            choose(it);
        }
        if (popup->done)
            swallow = 1;                               /* the release that follows the click that closed the menu is not the game's */
        wm_dirty = 1;
    }
    return 1;
}

int wm_popup_key(uint32_t vk, int down)
{
    if (!down)
        return 1;
    if (vk == 27) {
        if (popup->nlevels > 1)
            popup->nlevels--;
        else
            popup->done = 1;
    } else if (vk == 38 || vk == 40) {                 /* up / down: the next enabled item of the last level */
        Menu *m = popup->levels[popup->nlevels - 1].menu;
        int i, cur = -1, n = 0, cand[64];

        for (i = 0; i < m->n && n < 64; i++)
            if (!(m->items[i].flags & (MF_SEPARATOR | MF_GRAYED | MF_DISABLED)))
                cand[n++] = i;
        for (i = 0; i < n; i++)
            if (&m->items[cand[i]] == popup->hover)
                cur = i;
        if (n) {
            int k = cur >= 0 ? (cur + (vk == 40 ? 1 : -1) + n) % n : (vk == 40 ? 0 : n - 1);

            popup->hover = &m->items[cand[k]];
        }
    } else if (vk == 13 && popup->hover)
        choose(popup->hover);
    wm_dirty = 1;
    return 1;
}

int wm_popup_swallow_up(void) { int s = (int)swallow; swallow = 0; return s; }

static int popup_done(void *p) { return ((Popup *)p)->done; }

/* Show the menu at screen (x, y) and wait for the host: returns the chosen command (TPM_RETURNCMD) or 1 after posting it as a WM_COMMAND to
 * the window, and 0 if the menu was dismissed. */
static uint32_t TrackPopupMenu(const uint32_t *a)
{
    Menu *m = get_menu(a[0]);
    Popup p;

    if (!m || popup)
        return 0;
    /* Windows tells the owner the menu is about to open; the game fills its menus in at these (WM_INITMENU, WM_INITMENUPOPUP). */
    wm_send(a[5], WM_INITMENU, a[0], 0);
    wm_send(a[5], WM_INITMENUPOPUP, a[0], 0);
    if (!m->n)
        return 0;
    memset(&p, 0, sizeof(p));
    p.levels[0] = (Level){m, (int32_t)a[2], (int32_t)a[3]};
    p.nlevels = 1;
    popup = &p;
    wm_dirty = 1;
    while (!p.done) {
        wm_process_sent();
        sched_block(popup_done, &p, 0.003);
    }
    popup = NULL;
    wm_dirty = 1;
    wm_send(a[5], WM_MENUSELECT, 0xFFFF0000u, 0);           /* the menu closed: the game empties it here */
    if (!p.choice)
        return 0;
    if (a[1] & TPM_RETURNCMD)
        return p.choice;
    wm_post(a[5], WM_COMMAND, p.choice & 0xFFFF, 0);
    return 1;
}

const WinApi MENUS_APIS[] = {
    {"user32.dll", "CreatePopupMenu", CreatePopupMenu}, {"user32.dll", "AppendMenuA", AppendMenuA}, {"user32.dll", "InsertMenuA", InsertMenuA}, {"user32.dll", "ModifyMenuA", ModifyMenuA},
    {"user32.dll", "DeleteMenu", RemoveMenu}, {"user32.dll", "RemoveMenu", RemoveMenu}, {"user32.dll", "DestroyMenu", one},
    {"user32.dll", "GetMenuItemCount", GetMenuItemCount}, {"user32.dll", "CheckMenuItem", CheckMenuItem},
    {"user32.dll", "EnableMenuItem", EnableMenuItem}, {"user32.dll", "TrackPopupMenu", TrackPopupMenu}, {0, 0, 0},
};

/* PORT_CONTROL's `windows`: an open popup menu, level by level, one line per row with the pixel box of the row (so a script can click an item
 * without knowing the font size or where the screen edge pushed the menu). */
void wm_popup_dump(FILE *f)
{
    int li, i;

    if (!popup)
        return;
    for (li = 0; li < popup->nlevels; li++) {
        int x, y, w, h;

        wm_popup_geometry(li, &x, &y, &w, &h);
        fprintf(f, "  popup level %d (%d,%d)-(%d,%d)\n", li, x, y, x + w, y + h);
        for (i = 0; i < popup->levels[li].menu->n; i++) {
            const char *text;
            uint32_t flags;
            int y0, y1, hot;

            if (wm_popup_row(li, i, &text, &flags, &y0, &y1, &hot))
                fprintf(f, "  item %d.%d '%s' (%d,%d)-(%d,%d)%s%s\n", li, i, text, x, y0, x + w, y1, (flags & MF_SEPARATOR) ? " separator" : "",
                        (flags & (MF_GRAYED | MF_DISABLED)) ? " disabled" : "");
        }
    }
}

/* For the compositor: how many levels the open popup has, and the rows of one (text, flags, top and bottom pixel, whether the pointer is on it). */
int wm_popup_levels(void) { return popup ? popup->nlevels : 0; }

int wm_popup_row(int li, int i, const char **text, uint32_t *flags, int *y0, int *y1, int *hot)
{
    int lx, ly, w, h, k, cy;
    Menu *m;

    if (!popup || li < 0 || li >= popup->nlevels)
        return 0;
    m = popup->levels[li].menu;
    if (i < 0 || i >= m->n)
        return 0;
    wm_popup_geometry(li, &lx, &ly, &w, &h);
    cy = ly + 2;
    for (k = 0; k < i; k++)
        cy += (m->items[k].flags & MF_SEPARATOR) ? MENU_SEP_H : MENU_ITEM_H;
    *text = m->items[i].text;
    *flags = m->items[i].flags;
    *y0 = cy;
    *y1 = cy + ((m->items[i].flags & MF_SEPARATOR) ? MENU_SEP_H : MENU_ITEM_H);
    *hot = popup->hover == &m->items[i];
    return 1;
}

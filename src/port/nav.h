/*
 * nav.h - spatial navigation between the things a pointer can be put on (the D-pad in a duel or a dialog). Pure: no SDL, no game, no window manager. The caller (navwm.c) makes the
 * list of targets from the window tree; this file chooses the next one in a direction, as a TV's focus does. docs/notes/controller-nav.md says how the targets are found and why.
 *
 * A target is a box on the screen (screen pixels of the game, whatever PORT_RES is), the part of a card, button or list row that is really visible, with a zone: the group it belongs
 * to (one hand, one territory, one list, one dialog's buttons). The rules (nav_pick):
 *   1. The current target is the one the pointer is on. With none, the direction is taken from the pointer itself.
 *   2. A candidate must lie beyond the current one in the direction: its centre strictly past the current centre along that axis, and either overlap the current box sideways (in its
 *      beam: up and down overlap in x, left and right in y) or be inside a 45 degree cone (no further sideways than along). No wrapping: nothing beyond is "none".
 *   3. Candidates are tried in tiers, the first that has any wins: those in the beam, of the current zone, then in the beam of another zone (the jump to the neighbouring zone); then
 *      those in the cone only, of the current zone, then of another.
 *   4. In a tier the nearest wins: distance along the axis plus twice the sideways offset. A tie goes to the smaller sideways offset, then to the earlier in the list (the caller sorts it
 *      top to bottom, left to right, so it is deterministic).
 *   5. A list that scrolls (NAVS_ flags on its targets) has no neighbour of its own zone beyond its last visible row in the direction: nav_pick says NAV_SCROLL, and the caller presses
 *      the arrow key.
 */
#ifndef PORT_NAV_H
#define PORT_NAV_H

#include <stdint.h>

enum { NAV_UP, NAV_DOWN, NAV_LEFT, NAV_RIGHT };

/* what a target is (informational: the caller's own use, tests, the dump of PORT_CONTROL) */
enum { NAVK_OTHER, NAVK_CARD, NAVK_BUTTON, NAVK_FIELD, NAVK_ROW, NAVK_PLAYER, NAVK_PILE, NAVK_MANA, NAVK_PHASE, NAVK_MENU };

/* a target's zone continues past it, in these directions (a list with rows above or below what is shown) */
enum { NAVS_UP = 1, NAVS_DOWN = 2, NAVS_LEFT = 4, NAVS_RIGHT = 8 };

#define NAV_MAXTARGETS 256
#define NAV_NONE (-1)             /* nav_pick: nothing in that direction (and no targets at all if n is 0) */
#define NAV_SCROLL (-2)           /* nav_pick: the zone scrolls that way: press the arrow key instead */

typedef struct {
    int x0, y0, x1, y1;           /* the box (x1 and y1 are exclusive): the pointer is put in its middle */
    int zone;                     /* targets of one zone are preferred as neighbours of each other */
    int kind;                     /* NAVK_ */
    int scroll;                   /* NAVS_ */
    uint32_t id;                  /* the window it comes from (0 for a part of one) */
    char label[28];               /* a few words, for the dump */
} NavTarget;

/* the pointer's place for a target: the middle of its box */
void nav_point(const NavTarget *t, int *x, int *y);
/* the target the pointer (x, y) is on, or -1 */
int nav_find(const NavTarget *t, int n, int x, int y);
/* The target to go to from `cur` (an index, or -1: look under the pointer at x, y) in direction `dir`: its index, with the point to put the pointer at in *hx, *hy; NAV_NONE; or
 * NAV_SCROLL. With no current target the nearest one in the direction is chosen, and with none in that direction the nearest of all (so the pointer can always get back on the targets). */
int nav_pick(const NavTarget *t, int n, int cur, int x, int y, int dir, int *hx, int *hy);
/* The target nearest to the pointer (x, y), whatever the direction (0 when the pointer is in it; the nearest edge otherwise; a tie goes to the earlier), its pointer place in *hx, *hy; NAV_NONE
 * if there are no targets. For a screen the game draws itself, where the pointer is wherever the last click left it: the first press takes hold of what is nearest. */
int nav_nearest(const NavTarget *t, int n, int x, int y, int *hx, int *hy);

#endif

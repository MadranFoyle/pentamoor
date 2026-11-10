/*
 * navwm.h - the targets of the D-pad: where a pointer can be put in a duel, a dialog, a popup menu or a combo box's list, read off the window tree, and on the game's own screens, read off its
 * button table (screens.c). nav.c chooses among them.
 * Runs on the guest side only (it reads the window manager's state: front.c calls it at the point where the queued input is delivered). docs/notes/controller-nav.md.
 */
#ifndef PORT_NAVWM_H
#define PORT_NAVWM_H

#include <stdio.h>

#include "nav.h"
#include "wm.h"

/* what is navigated now: the first that applies */
enum { NAVWM_NONE, NAVWM_MENU, NAVWM_COMBO, NAVWM_DIALOG, NAVWM_DUEL, NAVWM_DECK, NAVWM_SCREEN, NAVWM_PAGE };

/* Cheap and always safe to ask: a popup menu is open, a combo box's list is down, a dialog is open, a duel is on the screen (its window, MAGICGAME_MainClass, is shown), the deck builder is (MAGICDECK_MainClass), or a screen the game
 * draws itself is on that has buttons or choices to move between (screens.c: the title menus, the village, the encounter box ...). */
int navwm_mode(void);
const char *navwm_mode_name(int mode);            /* "none", "menu", "combo", "dialog", "duel", "deck", "screen" (the log and `nav` print it) */
/* "page": the program's main window has standard controls shown on it (no modal dialog, duel or deck builder): the Magic Shell of Spells of the Ancients (docs/notes/controller-screens.md). Its targets are
 * the controls, the two halves of each spin button, and the rectangles the program tests a click against (wm_hotspots). */
/* Once a frame, on the guest side: do what a mode needs before the first press (a page asks its window once where its own buttons are). */
void navwm_tick(void);
/* Touch: where a tap near a control should land. In a page, a dialog or a list that is down, a point on a small control (a spin button's arrow, a check box, a list row: under NAV_SMALL pixels on its short
 * side) or within `slop` pixels of one, or of any control when it is on none, goes to that control: *sx, *sy is where to put it, and the return is 1; 0 when the point stays where it is. */
int navwm_snap(int x, int y, int slop, int *sx, int *sy);
/* The D-pad's B in a dialog: 1 when it would close the dialog (it has an enabled Cancel button, id 2, and does not read Escape itself): the pad then sends Escape for B. */
int navwm_cancel_ready(void);
/* The targets of the current mode, sorted top to bottom and left to right; returns how many (0 in NAVWM_NONE). *cur: the one under (x, y), or -1. */
int navwm_collect(NavTarget *out, int max, int x, int y, int *cur);
/* The D-pad pressed with the pointer at (x, y): nav_pick over navwm_collect. Returns the index of the target chosen (its pointer place in *tx, *ty), NAV_NONE or NAV_SCROLL. */
int navwm_pick(int x, int y, int dir, int *tx, int *ty);
/* The duel's card window under (x, y), or 0 (not in a duel, a dialog or menu on top, the pointer on no card, or a build with no "View in full card" command: profile->viewcard). */
uint32_t navwm_card_at(int x, int y);
/* Post the game's own "View in full card" command to the card under (x, y): its Full-size card window shows that card at once, as it does after the pointer has rested on a card. 1 if there was a card. */
int navwm_view_card(int x, int y);
/* The Full-size card window the game shows the big card in, when it is shown (NULL otherwise). The card zoom copies its picture. */
const Window *navwm_fullcard(void);
/* The targets and the current one, one line each (PORT_CONTROL `nav`). */
void navwm_dump(FILE *f, int x, int y);

#endif

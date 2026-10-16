/*
 * navwm.h - the targets of the D-pad: where a pointer can be put in a duel, a dialog, a popup menu or a combo box's list, read off the window tree, and on the game's own screens, read off its
 * button table (screens.c). nav.c chooses among them.
 * Runs on the guest side only (it reads the window manager's state: front.c calls it at the point where the queued input is delivered). docs/notes/controller-nav.md.
 */
#ifndef PORT_NAVWM_H
#define PORT_NAVWM_H

#include <stdio.h>

#include "nav.h"

/* what is navigated now: the first that applies */
enum { NAVWM_NONE, NAVWM_MENU, NAVWM_COMBO, NAVWM_DIALOG, NAVWM_DUEL, NAVWM_DECK, NAVWM_SCREEN };

/* Cheap and always safe to ask: a popup menu is open, a combo box's list is down, a dialog is open, a duel is on the screen (its window, MAGICGAME_MainClass, is shown), the deck builder is (MAGICDECK_MainClass), or a screen the game
 * draws itself is on that has buttons or choices to move between (screens.c: the title menus, the village, the encounter box ...). */
int navwm_mode(void);
const char *navwm_mode_name(int mode);            /* "none", "menu", "combo", "dialog", "duel", "deck", "screen" (the log and `nav` print it) */
/* The targets of the current mode, sorted top to bottom and left to right; returns how many (0 in NAVWM_NONE). *cur: the one under (x, y), or -1. */
int navwm_collect(NavTarget *out, int max, int x, int y, int *cur);
/* The D-pad pressed with the pointer at (x, y): nav_pick over navwm_collect. Returns the index of the target chosen (its pointer place in *tx, *ty), NAV_NONE or NAV_SCROLL. */
int navwm_pick(int x, int y, int dir, int *tx, int *ty);
/* The targets and the current one, one line each (PORT_CONTROL `nav`). */
void navwm_dump(FILE *f, int x, int y);

#endif

/*
 * screens.h - the D-pad's targets on the screens MAGIC.EXE draws itself (the title menus, the new game, the village, the world map, the wizard's stats, the clues, the encounter boxes ...).
 * Those have no windows to read: the game draws into one window and decides what a click hit with its own code. But almost all of it goes through two pieces of the game, and both keep
 * what the pointer can be put on in guest memory: the button table of the screens' loops (0x41f3ea, once a pass) and the text menu ("Will you...\n Duel a Sorceress.\n Pay 40 gold.",
 * 0x489748). This file reads them. Runs on the guest side only (front.c asks at the point where input is delivered). docs/notes/controller-screens.md says what is where, and how it was found.
 *
 * Which screen is on is known from the passes: the loops call the table's pass and the mouse snapshot (0x44b84b) every time round, and a pre-call hook notes where the call came from
 * (screens_note). A screen whose loop has not passed for a while (it is busy, or has ended) is not "on".
 */
#ifndef PORT_SCREENS_H
#define PORT_SCREENS_H

#include <stdint.h>

#include "nav.h"

/* what screens_kind says is on */
enum { SCREEN_NONE, SCREEN_TABLE, SCREEN_TEXTMENU, SCREEN_BUYCARDS, SCREEN_CLUES, SCREEN_TITLE };      /* SCREEN_TITLE: the title menu, a table screen like SCREEN_TABLE (the D-pad reads the same) */

void screens_install(void);                  /* the hooks (MAGIC.EXE only) */
/* A loop of the game passed (src: SRC_TABLE the button table's pass, SRC_SNAPSHOT the mouse snapshot); ret is the address the call returns to, which says which loop it is, and ebp the frame
 * of the function that made the call (the registers a caller's call leaves in lift_out): a loop that keeps what a click hits in locals is read through it. */
enum { SRC_TABLE = 1, SRC_SNAPSHOT = 2 };
void screens_note(uint32_t ret, uint32_t ebp, int src, double now);
/* The kind of screen that has passed in the last LIVE_S seconds (as of `now`), SCREEN_NONE if none has or if it is one whose D-pad is the arrow keys (the overworld). */
int screens_kind(double now);
/* The targets of the screen that is on (at most max); the number. Zones: one for the buttons of one handler, one for a text menu's lines. */
int screens_collect(NavTarget *out, int max, double now);

/* ---- the pieces, for the tests ---- */
/* one record of the game's button table: its place as the game tests a click (x <= mouse x <= x + w, y <= mouse y <= y + h, both ends in), and its type (3: greyed, not hit). Returns 0 for a record that is
 * not on the screen (no size, or off it: the table also holds keys with no place). */
int screens_record_target(int x, int y, int w, int h, int type, int screen_w, int screen_h, NavTarget *t);
/* the lines of a text menu as the game tests them: the box's left x0 and right edge x1 (both in), the top y, the line height lh, `first` the lines of text above the choices, `count` the choices,
 * `mask` the ones that are shut (bit i). Fills t[] with the open ones; returns how many. */
int screens_textmenu_targets(int x0, int x1, int top, int lh, int first, int count, uint32_t mask, int screen_w, int screen_h, NavTarget *t, int max);
/* the cards of the shop's "Cards for Sale" row: the game's four boxes (x0, y0, x1, y1, both ends in) and which of them still hold a card (the id is not -1). */
int screens_card_targets(const int32_t *boxes, const int32_t *ids, int n, int screen_w, int screen_h, NavTarget *t, int max);
/* the clue list's rows: the game turns the mouse into 640x480 units (x * 640 / screen_w, y * 480 / screen_h) and tests two columns of six rows 62 high; `count` rows have a dungeon in them. */
int screens_clue_targets(int count, int screen_w, int screen_h, NavTarget *t, int max);

#endif

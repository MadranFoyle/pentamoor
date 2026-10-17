/*
 * steamdeck.h - the Steam Deck (and Gamescope) decisions of the front end, as pure functions: no SDL and no game, so they are unit tested (test_steamdeck.c).
 *
 *   - is this a Steam Deck (SteamOS, Steam's Game mode, a Gamescope session)?
 *   - does the window start full screen?
 *   - how is the game's screen scaled into a full-screen display (1024x768 into the Deck's 1280x800)?
 *   - is text input wanted now (a text field has the focus), so that the Deck's keyboard may appear?
 */
#ifndef PORT_STEAMDECK_H
#define PORT_STEAMDECK_H

#include <stdint.h>

#include "display.h"

/* A Steam Deck, from what the system says. steamdeck_env: $SteamDeck (Steam sets it to 1 for the games it starts on a Deck); os_release: the text of /etc/os-release (ID=steamos,
 * NAME="SteamOS"); gamescope_wayland: $GAMESCOPE_WAYLAND_DISPLAY (set inside Gamescope, Game mode's compositor); xdg_desktop: $XDG_CURRENT_DESKTOP ("gamescope" there).
 * Any of them may be NULL. Returns 1 if any of the four says so. */
int deck_detect(const char *steamdeck_env, const char *os_release, const char *gamescope_wayland, const char *xdg_desktop);

/* The real thing: reads the environment and /etc/os-release (or /usr/lib/os-release). $PORT_STEAMDECK=0 says it is not one, =1 that it is (other systems with the same screen and
 * controls: Bazzite, ChimeraOS, a handheld PC). The answer is the same for the whole run. */
int deck_here(void);

/* Whether the window starts full screen: $PORT_FULLSCREEN (NULL if unset) decides when set ("0", "", "no", "off", "false" mean no; anything else yes), else the Deck is full screen
 * and nothing else is. */
int fullscreen_wanted(const char *env, int deck);

/* Scaling the screen (sw x sh) into a full-screen display (dw x dh), keeping its shape: display.h's display_fit (INT_SCALE_MIN is defined there), which is now the "fit" mode of every
 * window and not only of the Deck's. The Deck (1024x768 in 1280x800: 1.04x fractional, 1x whole) gets the whole scale, a 1080p television (1.41x) the fractional one. */
double view_scale(int sw, int sh, int dw, int dh, int *integer, int *vw, int *vh);

/* Text input (the Deck's on-screen keyboard follows SDL_StartTextInput): wanted while a text field has the focus, which is an edit control in the dialog that is open, or the game's
 * own name box (which no window says: the game is asked, see textfocus.c, and answers by polling for keys, so it counts as the focus for NAME_HOLD_MS after the last poll).
 * now_ms, name_ms: the clock and the time of the last name-box poll (0: never). */
#define NAME_HOLD_MS 400
int text_wanted_rule(uint32_t now_ms, uint32_t name_ms, int edit_focus);

#endif

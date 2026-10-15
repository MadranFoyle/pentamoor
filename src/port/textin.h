/*
 * textin.h - typed text that did not come from a key: what the game gets for it. Pure (no SDL, no game), unit tested (test_steamdeck.c).
 *
 * The game's own text boxes (the new game's name) read WM_KEYDOWN with a scan code and turn it into a character themselves (with the Shift they read from GetAsyncKeyState); they
 * ignore WM_CHAR. A real keyboard sends keys, so that works. Text that arrives with no key before it (SDL_TEXTINPUT from the Steam Deck's on-screen keyboard, an input method, a
 * paste) has to be turned back into the key presses that type it on a US keyboard, with Shift held where the character needs it. Characters that no US key types
 * (U+00A0..U+00FF, the Latin-1 letters) go as WM_CHAR alone, which is what the edit boxes of the port's own dialogs read.
 *
 * A key that is waiting for its own text (SDL sends KEYDOWN, then TEXTINPUT for it) takes that text as its character and nothing more is typed: so each character reaches the game once.
 */
#ifndef PORT_TEXTIN_H
#define PORT_TEXTIN_H

#include <stdint.h>

typedef struct { uint16_t vk, sc; int shift; } TextKey;

/* The US-layout key that types ch (printable ASCII): its virtual-key and scan codes, and whether Shift is needed. Returns 0 if no key does. */
int textin_key_for_char(int ch, TextKey *k);

/* The character a US-layout key types (vk as the game's keyboard code sees it), with Shift held or not; -1 for a key that types nothing. */
int textin_char_for_key(int vk, int shift);

/* A key is waiting for the text SDL sends for it. Does this text belong to it? Returns the character to give the key (a single printable ASCII character), else -1: a longer text,
 * a character outside ASCII (a dead key's accent), or nothing, is not what the key typed. */
int textin_attach(const char *utf8);

enum { TX_KEYDOWN, TX_KEYUP, TX_CHAR };
typedef struct { int type; uint16_t vk, sc; int ch; } TextAct;      /* TX_KEYDOWN carries the character the key types in ch */
#define TEXT_MAX_ACTS 192
typedef struct { TextAct act[TEXT_MAX_ACTS]; int n; } TextOut;

/* What to send for text that no key came with (UTF-8 as SDL gives it): for each character the key press that types it (Shift pressed around it unless shift_held already has it
 * down), or TX_CHAR for a Latin-1 one. Characters that cannot be typed are skipped. out->n is 0 on entry or it is appended to; the output stops when it is full. */
void textin_type(const char *utf8, int shift_held, TextOut *out);

#define VK_SHIFT_CODE 0x10
#define SC_LSHIFT 0x2A

#endif

/* front_none.c - no window (SDL is not available, or PORT_HEADLESS is set): the game runs on the calling thread. */
#include "front.h"

int front_has_window(void) { return 0; }

int front_run(int (*game)(void *), void *arg) { return game(arg); }

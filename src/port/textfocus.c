/* textfocus.c - when is the game waiting for typed text?
 *
 * An edit control of a dialog is a window, so the window layer can say it (wm_text_focus). The new game's name box is not: MAGIC.EXE draws it and reads it itself, in the loop of
 * Pic_Load_namepick (0x47be64..0x47c07f), which asks for a key with 0x004080b2 (0x4080b2, a pop from the game's own key queue) on every pass until Enter. That call, made from inside
 * that loop, is the "a text field has the focus" signal: it is noted on the way in (a hook before the call, the function runs as usual), and front.c counts it for a short while after
 * the last one (steamdeck.h, NAME_HOLD_MS), so that the Steam Deck's on-screen keyboard can be asked for while the box is up and let go of when it is not. Nothing here changes what the
 * game does. */
#include <string.h>

#include "front.h"
#include "port.h"
#include "profile.h"

/* Where: the build's profile (profile.c; MAGIC.EXE 1.0's values): keys.pop 0x4080b2, keys.name_loop 0x47be64..0x47c080. */

static uint32_t name_poll(const uint32_t *a)
{
    uint32_t ret = RD32(port_sp);                 /* where the call returns to: the hook runs with the return address on top of the stack, as in pace.c */

    (void)a;
    if (ret >= profile->keys.name_loop.lo && ret < profile->keys.name_loop.hi)
        front_note_name_entry();
    return 0;
}

void textfocus_install(void)
{
    if (!profile->keys.pop || !profile->keys.name_loop.hi)
        return;
    port_prehook(profile->keys.pop, name_poll);
}

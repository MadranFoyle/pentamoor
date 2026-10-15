/* winhelp.c - WinHelpA (user32), and the small message dialog it shows.
 *
 * The game's help is a Windows Help file (DUEL.HLP with DUEL.CNT: the format of WinHelp 3.x, LZ-compressed topics with phrase tables, bitmaps and a keyword
 * index). Showing it would take a WinHelp engine of its own, which this port does not have, so WinHelpA does what the program needs from it and no more: it
 * returns TRUE (the program goes on, and does not learn the help is missing) and, for a command that asks for help to be shown, tells the player in a dialog
 * that in-game help is not available. The program calls it from its right-click menus ("Help...", "Help for this card...", "Help for this phase...") with
 * HELP_CONTEXT and a topic number of its own, and once with HELP_QUIT when its palette window is destroyed (that one is silent: there is no help window to close).
 *
 * The dialog is a message box (msgbox.c) with only an OK button: the text over OK. Enter and the button close it, Esc and the close box too (as Windows does for such a box). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gdi_int.h"
#include "msgbox.h"
#include "sched.h"
#include "wm.h"
#include "winhelp.h"

#define P(a) ((char *)(G + (a)))

int winhelp_shows(uint32_t cmd)
{
    switch (cmd) {
    case HELP_QUIT: case HELP_SETINDEX: case HELP_FORCEFILE: case HELP_SETPOPUP_POS: case HELP_SETWINPOS:
        return 0;
    default:
        return 1;            /* the contexts, the contents and index, the keyword searches, the pop-ups: all of them open the help window or a pop-up in it */
    }
}

void winhelp_file_name(const char *path, char *out, size_t cap)
{
    const char *s = path ? path : "", *p;

    for (p = s; *p; p++)
        if (*p == '\\' || *p == '/' || *p == ':')
            s = p + 1;
    snprintf(out, cap, "%s", s);
}

int winhelp_text(uint32_t cmd, const char *file, char *out, size_t cap)
{
    char name[96];

    if (cap)
        out[0] = 0;
    if (!winhelp_shows(cmd))
        return 0;
    winhelp_file_name(file, name, sizeof(name));
    if (name[0])
        snprintf(out, cap, "In-game help is not available in this port.\n\nThe help file (%s) is in the Windows Help format, which Pentamoor cannot show.", name);
    else
        snprintf(out, cap, "In-game help is not available in this port.");
    return 1;
}

/* ---- the dialog ------------------------------------------------------------------------------------------------------------------ */
/* A message box with only an OK button (msgbox.c): shown whatever the run (it is not the program's own MessageBox call, which a run nobody watches answers at once). */
int port_message_dialog(uint32_t owner, const char *caption, const char *text)
{
    return msgbox_show(owner, caption, text, MB_OK) == IDOK;
}

/* ---- WinHelpA(hWndMain, lpszHelp, uCommand, dwData) ------------------------------------------------------------------------------- */
static uint32_t WinHelpA(const uint32_t *a)
{
    char text[400];
    const char *file = a[1] ? P(a[1]) : "";

    port_trace("WinHelp: window 0x%x, file '%s', command 0x%x, data 0x%x", a[0], file, a[2], a[3]);
    if (winhelp_text(a[2], file, text, sizeof(text)))
        port_message_dialog(a[0], "Help", text);
    return 1;
}

const WinApi WINHELP_APIS[] = {
    {"user32.dll", "WinHelpA", WinHelpA},
    {0, 0, 0},
};

/* winhelp.c - WinHelpA (user32), and the small message dialog it shows.
 *
 * The game's help is a Windows Help file (DUEL.HLP with DUEL.CNT: the format of WinHelp 3.x, LZ-compressed topics with phrase tables, bitmaps and a keyword
 * index). Showing it would take a WinHelp engine of its own, which this port does not have, so WinHelpA does what the program needs from it and no more: it
 * returns TRUE (the program goes on, and does not learn the help is missing) and, for a command that asks for help to be shown, tells the player in a dialog
 * that in-game help is not available. The program calls it from its right-click menus ("Help...", "Help for this card...", "Help for this phase...") with
 * HELP_CONTEXT and a topic number of its own, and once with HELP_QUIT when its palette window is destroyed (that one is silent: there is no help window to close).
 *
 * The dialog is an ordinary modal dialog (wm_dialog_box) built here in code, as the file dialogs are: the text over an OK button. Enter and the button close it
 * (the dialog manager sends IDOK), Esc and the close box too (as Windows does for a message box with only an OK button). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gdi_int.h"
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
enum { C_BUTTON = 0x80, C_STATIC = 0x82 };

static uint8_t tb[2048];
static size_t to;
static void t16(unsigned v) { tb[to++] = (uint8_t)v; tb[to++] = (uint8_t)(v >> 8); }
static void t32(uint32_t v) { t16(v & 0xFFFF); t16(v >> 16); }
static void twide(const char *s) { do t16((unsigned char)*s); while (*s++); }
static void titem(uint32_t style, int x, int y, int cx, int cy, unsigned id, unsigned cls, const char *text)
{
    while (to & 3)
        tb[to++] = 0;
    t32(style | WS_CHILD); t32(0);
    t16((unsigned)x); t16((unsigned)y); t16((unsigned)cx); t16((unsigned)cy); t16(id);
    t16(0xFFFF); t16(cls);
    twide(text);
    t16(0);
}

static uint32_t msg_proc(const uint32_t *a)
{
    Window *dlg = wm_window(a[0]);
    uint32_t msg = a[1], wp = a[2];
    int done = 0;

    if (msg == WM_INITDIALOG)
        return 1;
    if (msg == WM_COMMAND && ((wp & 0xFFFF) == 1 || (wp & 0xFFFF) == 2))
        done = 1;
    else if (msg == WM_KEYDOWN && wp == 0x1B)
        done = 1;
    else if (msg == WM_CLOSE)
        done = 1;
    if (done && dlg) {
        dlg->ended = 1;
        dlg->result = 1;
        return 1;
    }
    return 0;
}

int port_message_dialog(uint32_t owner, const char *caption, const char *text)
{
    static uint32_t proc;
    int lines = 0, width = 0, h, cx = 190;
    const char *p;
    char cap[64], txt[512];                                                /* what goes into the template is bounded: it is two bytes a character */

    if (!proc)
        proc = port_host_function(msg_proc);
    snprintf(cap, sizeof(cap), "%s", caption);
    snprintf(txt, sizeof(txt), "%s", text);
    /* the text's height in dialog units: 8 to a line of MS Sans Serif 8, which takes about 52 characters of the 190 units' width (counted as 50: a spare line is only blank) */
    for (p = txt;; p++) {
        if (*p == '\n' || !*p) {
            lines += 1 + width / 50;
            width = 0;
            if (!*p)
                break;
        } else
            width++;
    }
    h = lines * 8 + 4;
    to = 0;
    t32(0x80C800C4u); t32(0); t16(2);                                      /* popup, caption, system menu, modal frame, 3-D look, font set; two controls */
    t16(0); t16(0); t16((unsigned)(cx + 14)); t16((unsigned)(h + 35));
    t16(0); t16(0);                                                        /* no menu, the dialog class */
    twide(cap);
    t16(8); twide("MS Sans Serif");
    titem(WS_VISIBLE, 7, 7, cx, h, 0xFFFF, C_STATIC, txt);
    titem(WS_VISIBLE | WS_TABSTOP | 1u, (unsigned)((cx + 14 - 50) / 2), (unsigned)(7 + h + 7), 50, 14, 1, C_BUTTON, "OK");
    if (!wm_window(owner))
        owner = 0;
    return wm_dialog_box(tb, 0, owner, proc, 0) == 1;
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

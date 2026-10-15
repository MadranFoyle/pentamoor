/* winhelp.h - WinHelpA (user32) and the small message dialog it shows: the logic the tests check, and the dialog (winhelp.c). */
#ifndef PORT_WINHELP_H
#define PORT_WINHELP_H

#include <stddef.h>
#include <stdint.h>

/* WinHelp's commands (winuser.h) */
enum {
    HELP_CONTEXT = 0x0001, HELP_QUIT = 0x0002, HELP_INDEX = 0x0003, HELP_HELPONHELP = 0x0004, HELP_SETINDEX = 0x0005, HELP_CONTEXTPOPUP = 0x0008,
    HELP_FORCEFILE = 0x0009, HELP_CONTEXTMENU = 0x000A, HELP_FINDER = 0x000B, HELP_WM_HELP = 0x000C, HELP_SETPOPUP_POS = 0x000D,
    HELP_KEY = 0x0101, HELP_COMMAND = 0x0102, HELP_PARTIALKEY = 0x0105, HELP_MULTIKEY = 0x0201, HELP_SETWINPOS = 0x0203
};

/* Does this WinHelp command ask for help to be shown (1), or only close it or set it up (0: HELP_QUIT, HELP_SETINDEX, HELP_FORCEFILE, HELP_SETPOPUP_POS,
 * HELP_SETWINPOS), which needs no answer from the user? */
int winhelp_shows(uint32_t cmd);

/* The text of the dialog that stands in for the help window: `file` is the help file's path as the program gave it (guest spelling, may be empty or NULL).
 * Returns 1 and fills `out` if `cmd` shows help, else returns 0 and leaves it empty. */
int winhelp_text(uint32_t cmd, const char *file, char *out, size_t cap);

/* The file name part of a help file's path ("C:\MAGIC\PROGRAM\duel.hlp" gives "duel.hlp"). */
void winhelp_file_name(const char *path, char *out, size_t cap);

/* A small modal dialog: the text (wrapped; '\n' breaks a line) over an OK button. Returns when OK, Enter, Esc or the close box is used. 0 if there is no window system. */
int port_message_dialog(uint32_t owner, const char *caption, const char *text);

#endif

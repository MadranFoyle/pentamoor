/* textview.h - the window that shows a text file (textview.c): the answer to a program of Windows (Write.exe, Notepad.exe) that a game starts to show one. */
#ifndef PORT_TEXTVIEW_H
#define PORT_TEXTVIEW_H

#include <stddef.h>
#include <stdint.h>

/* How big the dialog and what is in it are, in pixels of its client area, for a screen. */
typedef struct TextViewLayout {
    int client_w, client_h;
    int margin;
    int text_x, text_y, text_w, text_h;          /* the read-only edit box */
    int btn_x, btn_y, btn_w, btn_h;              /* the Close button, centred under it */
} TextViewLayout;
void textview_layout(int sw, int sh, TextViewLayout *out);

/* The text of a file's bytes: at most `cap` bytes of it (and a note at the end when it was cut, *cut set), ending at the first NUL. Returns malloc'ed text. */
char *textview_prepare(const char *bytes, size_t n, size_t cap, int *cut);

/* Show a text in a modal dialog with a Close button (Esc and Enter close it too); returns when it is closed. */
int textview_show(uint32_t owner, const char *title, const char *text);
/* What a program's start of Write does: textview_show, or, in a run nobody watches (msgbox.h's rule: PORT_CONTROL, a script, SDL's dummy drivers, PORT_MSGBOX), only a line in the log. Returns whether it was shown. */
int textview_run(uint32_t owner, const char *title, const char *text);

#endif

/* textview.c - a window that shows a text file: what the programs of Windows that a game starts to show a file (Write.exe, Notepad.exe, WordPad) do for Pentamoor.
 *
 * Spells of the Ancients' Magic Shell has a "Read Me" button that runs `C:\WINDOWS\Write.exe <install>\ReadMe.txt` and waits for it to end. Write is not a program of the game and there is no
 * Windows here, so the runtime (process.c) answers the start of such a program with this: a modal dialog (wm_dialog_box, built here in code as msgbox.c's and the file dialog's are) with a
 * read-only multi-line edit box that shows the text (edit.c: wrapped to the box, a scroll bar, the wheel, the arrows, Page Up and Down, Home and End, selecting and Ctrl+C) and a Close button.
 * Esc, Enter and the close box close it. The program that started it waits for it, as it would for Write.
 *
 * Like MessageBox, a run that nobody watches (the control pipe, a script, SDL's dummy drivers) must not wait for a window nobody can close: there the window is not shown, and the log says so
 * (PORT_MSGBOX=ask or auto overrides the guess, as for MessageBoxA). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "gdi_int.h"
#include "msgbox.h"
#include "sched.h"
#include "textview.h"
#include "wm.h"

#define FACE "MS Sans Serif"
#define PT 8
enum { C_BUTTON = 0x80, C_EDIT = 0x81 };
enum { ID_TEXT = 100, ID_CLOSE = 2 };

/* the dialog's size from the screen's: as large as is comfortable, never larger than the screen leaves room for */
void textview_layout(int sw, int sh, TextViewLayout *L)
{
    int cw = sw - 120, ch = sh - 120;

    if (cw > 700)
        cw = 700;
    if (ch > 520)
        ch = 520;
    if (cw < 240)
        cw = sw > 260 ? sw - 20 : 240;
    if (ch < 160)
        ch = sh > 180 ? sh - 20 : 160;
    L->client_w = cw;
    L->client_h = ch;
    L->margin = 8;
    L->btn_w = 75;
    L->btn_h = 23;
    L->text_x = L->margin;
    L->text_y = L->margin;
    L->text_w = cw - 2 * L->margin;
    L->text_h = ch - 3 * L->margin - L->btn_h;
    L->btn_x = (cw - L->btn_w) / 2;
    L->btn_y = ch - L->margin - L->btn_h;
}

/* what a file's bytes are as text: at most `cap` of them, and a note when it was cut. Returns malloc'ed text. */
char *textview_prepare(const char *bytes, size_t n, size_t cap, int *cut)
{
    char *t;
    size_t k = n > cap ? cap : n;

    *cut = n > cap;
    t = malloc(k + 64);
    if (!t)
        return NULL;
    memcpy(t, bytes, k);
    t[k] = 0;
    if (strlen(t) < k)                                           /* a NUL in it (a binary file): what is before it is what there is to show */
        k = strlen(t);
    if (*cut) {
        strcpy(t + k, "\r\n\r\n[The rest of the file is not shown.]");
    }
    return t;
}

/* ---- the template -------------------------------------------------------------------------------------------------------------------- */
typedef struct Tmpl { uint8_t *b; size_t n, cap; } Tmpl;
static void tput(Tmpl *t, unsigned v) { if (t->n < t->cap) t->b[t->n++] = (uint8_t)v; }
static void t16(Tmpl *t, unsigned v) { tput(t, v); tput(t, v >> 8); }
static void t32(Tmpl *t, uint32_t v) { t16(t, v & 0xFFFF); t16(t, v >> 16); }
static void twide(Tmpl *t, const char *s) { do t16(t, (unsigned char)*s); while (*s++); }
static void titem(Tmpl *t, uint32_t style, int x, int y, int cx, int cy, unsigned id, unsigned cls, const char *text)
{
    while (t->n & 3)
        tput(t, 0);
    t32(t, style | WS_CHILD); t32(t, 0);
    t16(t, (unsigned)x); t16(t, (unsigned)y); t16(t, (unsigned)cx); t16(t, (unsigned)cy); t16(t, id);
    t16(t, 0xFFFF); t16(t, cls);
    twide(t, text);
    t16(t, 0);
}

static char *shown_text;                                          /* the text the dialog being run shows (one at a time) */

static uint32_t textview_proc(const uint32_t *a)
{
    uint32_t msg = a[1], wp = a[2];
    Window *dlg = wm_window(a[0]);

    if (msg == WM_INITDIALOG) {
        Window *ed = wm_dlg_item(a[0], ID_TEXT);

        if (ed && shown_text) {
            free(ed->title);
            ed->title = strdup(shown_text);
            wm_edit_reset(ed);
            wm_set_focus(ed->hwnd);
        }
        return 0;                                                   /* the focus is set here */
    }
    if (!dlg)
        return 0;
    if ((msg == WM_COMMAND && (wp & 0xFFFF) == ID_CLOSE) || msg == WM_CLOSE || (msg == WM_KEYDOWN && wp == 0x0D)) {
        dlg->ended = 1;
        dlg->result = 1;
        return 1;
    }
    return 0;
}

int textview_show(uint32_t owner, const char *title, const char *text)
{
    static uint32_t proc;
    TextViewLayout L;
    Tmpl t;
    char cap[160];
    int bx = 8, by = 16;
    uint32_t result;

    if (!proc)
        proc = port_host_function(textview_proc);
    textview_layout(screen_w, screen_h, &L);
    snprintf(cap, sizeof(cap), "%s", title && *title ? title : "Text");
    ui_font_metrics(FACE, PT, 0, &by, NULL, &bx);
    t.cap = 4096;
    t.b = malloc(t.cap);
    t.n = 0;
#define DX(px) (((px) * 4 + bx - 1) / bx)
#define DY(px) (((px) * 8 + by - 1) / by)
    t32(&t, 0x80C800C4u); t32(&t, 0); t16(&t, 2);
    t16(&t, 0); t16(&t, 0); t16(&t, (unsigned)DX(L.client_w)); t16(&t, (unsigned)DY(L.client_h));
    t16(&t, 0); t16(&t, 0);
    twide(&t, cap);
    t16(&t, PT); twide(&t, FACE);
    /* WS_VISIBLE | WS_TABSTOP | WS_BORDER | WS_VSCROLL | ES_MULTILINE | ES_AUTOVSCROLL | ES_NOHIDESEL | ES_READONLY */
    titem(&t, WS_VISIBLE | WS_TABSTOP | 0x800000u | 0x200000u | 0x4u | 0x40u | 0x100u | 0x800u, DX(L.text_x), DY(L.text_y), DX(L.text_w), DY(L.text_h), ID_TEXT, C_EDIT, "");
    titem(&t, WS_VISIBLE | WS_TABSTOP | 1u, DX(L.btn_x), DY(L.btn_y), DX(L.btn_w), DY(L.btn_h), ID_CLOSE, C_BUTTON, "Close");
    free(shown_text);
    shown_text = strdup(text ? text : "");
    if (!wm_window(owner))
        owner = 0;
    result = wm_dialog_box(t.b, 0, owner, proc, 1);
    free(t.b);
    free(shown_text);
    shown_text = NULL;
    return result == 1;
}

int textview_run(uint32_t owner, const char *title, const char *text)
{
    int shown = msgbox_mode() == MSGBOX_ASK;

    if (shown)
        textview_show(owner, title, text);
    port_log("text viewer: %s (%d bytes)%s", title ? title : "", (int)strlen(text ? text : ""), shown ? "" : ": not shown, nobody is there to close it");
    return shown;
}

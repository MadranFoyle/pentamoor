/* msgbox.h - MessageBoxA (user32): the decisions the tests check (which buttons a style has, what a key does, how big the box is), and the dialog itself (msgbox.c). */
#ifndef PORT_MSGBOX_H
#define PORT_MSGBOX_H

#include <stddef.h>
#include <stdint.h>

/* winuser.h: the buttons (uType & MB_TYPEMASK), the icon (& MB_ICONMASK), the default button (& MB_DEFMASK), and what MessageBox returns */
enum {
    MB_OK = 0, MB_OKCANCEL = 1, MB_ABORTRETRYIGNORE = 2, MB_YESNOCANCEL = 3, MB_YESNO = 4, MB_RETRYCANCEL = 5,
    MB_TYPEMASK = 0xF, MB_ICONHAND = 0x10, MB_ICONQUESTION = 0x20, MB_ICONEXCLAMATION = 0x30, MB_ICONASTERISK = 0x40, MB_ICONMASK = 0xF0,
    MB_DEFBUTTON1 = 0, MB_DEFBUTTON2 = 0x100, MB_DEFBUTTON3 = 0x200, MB_DEFBUTTON4 = 0x300, MB_DEFMASK = 0xF00
};
enum { IDOK = 1, IDCANCEL = 2, IDABORT = 3, IDRETRY = 4, IDIGNORE = 5, IDYES = 6, IDNO = 7 };

/* The buttons of a style, left to right. */
typedef struct MsgBoxSpec {
    int n;                       /* 1 to 3 */
    int id[3];                   /* IDOK ... IDNO */
    const char *label[3];        /* the text, with & before the accelerator ("&Yes") */
    int def;                     /* the default button: an index into the above (MB_DEFBUTTON2 on a one-button box is the first) */
    int cancel;                  /* what Esc and the close box return: IDCANCEL if there is a Cancel button, IDOK for a lone OK button, else 0 (Windows ignores both for Yes/No and Abort/Retry/Ignore) */
    char icon;                   /* '?', '!', 'x', 'i' or 0 */
} MsgBoxSpec;
void msgbox_spec(uint32_t type, MsgBoxSpec *out);

/* What MessageBox returns when nobody is there to answer: the default button's id. */
int msgbox_default_id(uint32_t type);

/* A key in the open box. `cur` is the button that has the focus (the one Enter and Space press). Returns the id to end the box with, or 0 for none:
 * Enter and Space press the focused button, Esc is spec.cancel, a letter that is a button's accelerator presses it (case does not matter). */
int msgbox_key(const MsgBoxSpec *s, int cur, uint32_t vk, int ch);

/* Tab, Right and Down move the focus to the next button, Left and Up to the previous one (wrapping): the new index, or `cur` for any other key. */
int msgbox_move(const MsgBoxSpec *s, int cur, uint32_t vk);

/* The size of the box. All in pixels except the box's own dialog units, which the template is made of. */
typedef struct MsgBoxLayout {
    int text_w, text_h;          /* the text's own area */
    int text_x, text_y;
    int icon_x, icon_y;          /* 32 x 32; icon_x is -1 for no icon */
    int btn_x[3], btn_y, btn_w, btn_h;
    int client_w, client_h;      /* the dialog's client area */
} MsgBoxLayout;
void msgbox_layout(const MsgBoxSpec *s, const char *caption, const char *text, int sw, MsgBoxLayout *out);

/* How MessageBoxA behaves. ASK shows the dialog and waits; AUTO answers at once with the default button (for runs nobody is watching: the control pipe, a script, SDL's dummy
 * drivers, no window), logging the text. PORT_MSGBOX=ask or auto forces either. */
enum { MSGBOX_ASK = 1, MSGBOX_AUTO = 2 };
int msgbox_mode_for(const char *env_msgbox, int unattended);            /* the rule: the variable's value, else AUTO when unattended */
int msgbox_mode(void);                                                  /* the rule applied to the environment (PORT_MSGBOX, PORT_CONTROL, PORT_SCRIPT, PORT_HEADLESS, SDL_VIDEODRIVER) */
void msgbox_set_mode(int mode);                                         /* override it (the tests); 0 goes back to the environment */

/* The line the log gets for a message box: "MessageBox: caption: text -> IDYES", with " (answered)" when somebody answered (the box was shown) rather than the default being taken. */
int msgbox_log_line(char *out, size_t cap, const char *caption, const char *text, int id, int answered);

/* The API, for the host's own use as well. `owner` may be 0 or stale. msgbox_show always shows the box and returns the id of the button that ended it; msgbox_run is what MessageBoxA
 * does: the same, or in AUTO mode just the default button's id. */
int msgbox_show(uint32_t owner, const char *caption, const char *text, uint32_t type);
int msgbox_run(uint32_t owner, const char *caption, const char *text, uint32_t type);

#endif

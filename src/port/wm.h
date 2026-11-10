/*
 * wm.h - the window manager: window classes, windows, message queues, input, the built-in controls and dialogs.
 * The behaviour is that of the Python layer (tools/emu_spike/winemu/user32.py), which was found by playing the game.
 */
#ifndef PORT_WM_H
#define PORT_WM_H

#include <stdint.h>
#include <stdio.h>

#include "port.h"

enum {
    WM_NULL = 0, WM_CREATE = 1, WM_DESTROY = 2, WM_MOVE = 3, WM_SIZE = 5, WM_ACTIVATE = 6, WM_SETFOCUS = 7, WM_KILLFOCUS = 8, WM_ENABLE = 0xA,
    WM_SETTEXT = 0xC, WM_GETTEXT = 0xD, WM_GETTEXTLENGTH = 0xE, WM_PAINT = 0xF, WM_CLOSE = 0x10, WM_QUIT = 0x12, WM_ERASEBKGND = 0x14,
    WM_SHOWWINDOW = 0x18, WM_ACTIVATEAPP = 0x1C, WM_SETCURSOR = 0x20, WM_GETMINMAXINFO = 0x24, WM_DRAWITEM = 0x2B,
    WM_WINDOWPOSCHANGING = 0x46, WM_WINDOWPOSCHANGED = 0x47, WM_NCCREATE = 0x81, WM_NCDESTROY = 0x82, WM_NCCALCSIZE = 0x83,
    WM_NCHITTEST = 0x84, WM_NCACTIVATE = 0x86, WM_KEYDOWN = 0x100, WM_KEYUP = 0x101, WM_CHAR = 0x102, WM_INITDIALOG = 0x110,
    WM_COMMAND = 0x111, WM_TIMER = 0x113, WM_INITMENU = 0x116, WM_INITMENUPOPUP = 0x117, WM_MENUSELECT = 0x11F,
    WM_MOUSEMOVE = 0x200, WM_LBUTTONDOWN = 0x201, WM_LBUTTONUP = 0x202, WM_LBUTTONDBLCLK = 0x203, WM_RBUTTONDOWN = 0x204,
    WM_RBUTTONUP = 0x205, WM_PARENTNOTIFY = 0x210
};
#define WS_CHILD 0x40000000u
#define WS_VISIBLE 0x10000000u
#define WS_POPUP 0x80000000u
#define WS_TABSTOP 0x10000u

typedef struct Class {
    char name[96];
    uint32_t style, proc, cbwnd, hinst, cursor, bg, extra;
} Class;

typedef struct Item {
    char *text;
    uint32_t data;
} Item;

typedef struct Window {
    uint32_t hwnd, parent, proc, style, exstyle, id, userdata, hinst, param;
    int x, y, w, h;
    double z;                    /* stacking order among siblings: higher is above */
    char *cname;
    Class *cls;
    char *title;
    int visible, enabled, invalid, erase, builtin, ownerdraw;
    int subclassed;              /* a standard control (BUTTON, STATIC ...) that the program gave a window procedure of its own (SetWindowLong GWL_WNDPROC): the procedure sees the messages, and the control still looks as Windows draws it */
    int painting;                /* a WM_PAINT has been handed out and not yet answered (BeginPaint, or DispatchMessage returning): the update region still exists for GetUpdateRect and GetUpdateRgn, though `invalid` is clear */
    uint32_t tid;
    uint8_t *extra;
    int nextra;
    /* controls */
    int checked;
    int drop_h, dropped, hot, orig_sel;   /* a drop-down combo box: its list's height (the window itself is the closed box), whether the list is down, (the first row shown is `top` below) the row under the pointer, the choice to go back to on Esc */
    Item *items;
    int nitems, sel;
    int scroll[4][3];            /* [bar][min, max, pos] */
    int top;                     /* a list box: the first item shown (LB_SETTOPINDEX) */
    int spin_set, spin_lo, spin_hi, spin_pos;   /* a spin button (msctls_updown32): its range and position (UDM_SETRANGE, UDM_SETPOS), 0 to 100 until set */
    uint32_t spin_buddy;                         /* ... and the edit box it types its position into (UDM_SETBUDDY; UDS_AUTOBUDDY: the window made just before it) */
    int edit_limit;                              /* an edit box: the most characters it takes (EM_LIMITTEXT; 0: no limit set) */
    int own_mouse;               /* a dialog whose procedure does the clicks on its list boxes and combo boxes itself (the file dialog): they are not the standard ones'  */
    int own_keys;                /* a dialog whose procedure reads Enter and Esc itself (a message box: the default button need not be IDOK): the dialog manager does not turn them into IDOK and IDCANCEL */
    int lb_icons;                /* a list box whose items are drawn with a folder or file icon (an item's data: 1 a folder), as the file dialog's list is */
    int has_caret, caret;        /* an edit box that shows a text cursor (1; 2: with all its text selected), and where (a byte offset in its text): the file dialog's. Every edit box keeps
                                  * its caret here (the active end of the selection) whether or not it has_caret: the caret is drawn when the box has the focus */
    int sel_anchor;              /* an edit box: the other end of the selection (equal to `caret`: none); the selection is [min, max) of the two, as a byte range of the text (edit.c) */
    int edit_xscroll, edit_top;  /* an edit box: how many pixels a one-line box is scrolled to the left, and the first visual line a multi-line one shows */
    uint32_t edit_t;             /* when the caret last moved or the text last changed (port_now_ms): the blink restarts there */
    int edit_drag;               /* the left button is held down in an edit box selecting with the mouse (1), or dragging a multi-line box's scroll thumb (2) */
    int edit_modified;           /* EM_GETMODIFY */
    /* dialogs */
    uint32_t dlgproc, result;
    int ended, is_dialog;
    uint32_t odmem;
    int nc_l, nc_t, nc_r, nc_b;  /* the non-client frame of a dialog (border, caption): the client area is inside it; x, y, w, h are the whole window */
    char dlg_face[40];           /* a dialog's font (DS_SETFONT), which its controls use */
    int dlg_pt;
    uint32_t hfont;              /* WM_SETFONT / WM_GETFONT: the font a dialog gave its controls (DS_SETFONT) */
    int ctl_valid, ctl_transparent, ctl_has_fg, ctl_has_bg;   /* what the parent's WM_CTLCOLOR... answered for this control (controls.c) */
    uint8_t ctl_fg[3], ctl_bg[3];
    void *surface;               /* the client area's pixels (gdi.c) */
    int see_through;             /* WM_ERASEBKGND answered "erased" and drew nothing (the BigCardChoice window of "Sorcerer casts..."): what the window's own painting leaves
                                  * untouched shows what is behind it, as it does on the real screen where a child shares its parent's pixels */
    void *movie;                 /* a movie window (movie.c) */
    /* the places the program tests a click against (the rectangles it passes to PtInRect with the point of a WM_LBUTTONDOWN it is handling): what a window that draws its own buttons
     * (the Magic Shell's five round ones) lets a click land on, in client coordinates; at most WM_HOT_MAX; dropped when the window's size changes (wm_hot_note, wm_hotspots) */
    int spot[16][5], nspot, spot_w, spot_h, spot_probed;                /* l, t, r, b and the place in the program that asked (the return address) */
} Window;
#define WM_HOT_MAX 16

/* windows */
Window *wm_window(uint32_t hwnd);
Window *wm_new_window(const char *cname, uint32_t parent, uint32_t style, uint32_t exstyle, int x, int y, int w, int h, const char *title,
                      uint32_t menu, uint32_t param);
int wm_window_count(void);
Window *wm_window_at_index(int i);
void wm_destroy(uint32_t hwnd);
void wm_abs_rect(const Window *w, int *x0, int *y0, int *x1, int *y1);          /* the window including its frame */
void wm_client_origin(const Window *w, int *x, int *y);                          /* where its client area starts, in screen coordinates */
void wm_client_size(const Window *w, int *cw, int *ch);
int wm_set_dirty(void);
extern int wm_dirty;

void wm_list_reset(Window *w);                                                    /* a list or combo box's items: empty it, add one (with its item data) */
void wm_list_add(Window *w, const char *text, uint32_t data);

/* the modal dialog a template (in host memory) describes; the file dialogs (filedlg.c) build theirs */
uint32_t wm_dialog_box(const uint8_t *tmpl_bytes, uint32_t tmpl, uint32_t parent, uint32_t proc, uint32_t param);

/* messages */
uint32_t wm_send(uint32_t hwnd, uint32_t msg, uint32_t wp, uint32_t lp);
uint32_t wm_send_local(uint32_t hwnd, uint32_t msg, uint32_t wp, uint32_t lp);
void wm_post(uint32_t hwnd, uint32_t msg, uint32_t wp, uint32_t lp);
void wm_process_sent(void);
uint32_t wm_default_proc(uint32_t hwnd, uint32_t msg, uint32_t wp, uint32_t lp);
void wm_show(uint32_t hwnd, int cmd);
uint32_t wm_control_message(Window *w, const char *cls, uint32_t msg, uint32_t wp, uint32_t lp);
Window *wm_dlg_item(uint32_t hdlg, uint32_t id);
/* Hot spots: a window of the program's own that draws buttons itself and tests where a click landed (the Magic Shell: five round buttons on its main window) is no tree of child windows. The program
 * does the test with PtInRect, in its handler of WM_LBUTTONDOWN; the window layer notes each rectangle it is asked about with that message's point (nothing of the program's code or data is read), so
 * the D-pad can put the pointer on them. A program tests its buttons in a loop (one place asks about each of them) and its odd rectangles (the window's own caption buttons, a hidden region) one by one from places of
 * their own, and a press that hits none runs every test: so what wm_hotspots gives is the rectangles one place asked about, the place that asked about most (at least two, or the only one asked). They are in
 * screen coordinates, x0, y0, x1, y1 each (x1 and y1 exclusive); returns how many (at most max).
 * wm_hot_probe: ask the window where they are by sending it one press and release of the left button at the corner of its client area, which hits nothing; done once for a window, 1 if it sent. */
int wm_hotspots(const Window *w, int (*out)[4], int max);
int wm_hot_probe(Window *w);
void wm_hot_note(int l, int t, int r, int b, int x, int y, uint32_t site);   /* PtInRect's: called with each rectangle, the point it is tested against, and where in the program it was asked from */
void wm_button_auto_check(Window *w);          /* a click on an automatic check box or radio button */
void wm_spin_click(Window *w, int up);                 /* a click on a spin button's upper or lower arrow */
void wm_set_focus(uint32_t hwnd);                      /* the keyboard focus (user32.c), as the dialog manager moves it with Tab; an edit box that loses it hides its selection and one that gains it selects its text (the program is sent no message) */
uint32_t wm_get_focus(void);                           /* ... and who has it */
void wm_query_ctl_colors(Window *parent, Window *c);   /* ask the parent's procedure how the control is coloured (WM_CTLCOLORSTATIC and the rest) and keep the answer for when it is drawn */

/* a drop-down combo box (controls.c): the list is drawn over everything (ui.c) and takes the mouse and keys while it is down */
enum { COMBO_CLOSED_H = 21 };
int wm_combo_open(void);                                    /* the hwnd of the combo whose list is down, or 0 */
void wm_combo_drop(Window *w);
int wm_combo_mouse(int kind, int x, int y);
int wm_combo_key(uint32_t vk, int down, int ch);
void wm_combo_wheel(int clicks);                            /* positive: up */
void ui_combo_geometry(const Window *w, int *x0, int *y0, int *x1, int *y1, int *rowh, int *rows);   /* the list's box and rows (ui.c) */
void wm_listbox_click(Window *w, int y);                  /* a press on a list box (screen y) */
int ui_listbox_row(const Window *w, int y);                  /* the row at a screen y, or -1 (ui.c) */
/* The rows of a list box that are drawn: the screen y of the first, the row height, how many are drawn, the first one's index, and the x range of a row (ui.c). */
void ui_listbox_geometry(const Window *w, int *y_first, int *rowh, int *rows, int *top, int *x0, int *x1);
int wm_is_hit_target(const Window *w);                      /* whether the pointer can be on this window at all (the test wm_hit_test applies first; input.c) */
void ui_combo_list(uint8_t *rgb, int sw, int sh, const Window *w);

/* The edit boxes (edit.c): single-line and multi-line, with a caret, a selection, the clipboard and the EM_ messages of Windows. Everything works on the window's own text (`title`) in
 * bytes (Latin-1, one byte a character); a multi-line box keeps its line breaks as CR LF, as Windows does. The functions are what the keyboard and the mouse do, so that a controller's
 * on-screen keyboard (or anything else that types) can call them: wm_edit_text inserts text where the caret is, replacing the selection, as typing does. */
enum { ES_MULTILINE = 0x4, ES_PASSWORD = 0x20, ES_AUTOVSCROLL = 0x40, ES_AUTOHSCROLL = 0x80, ES_NOHIDESEL = 0x100, ES_READONLY = 0x800, ES_NUMBER = 0x2000 };
int wm_edit_is_edit(const Window *w);                                            /* a built-in EDIT control (not one the program subclassed with a procedure of its own) */
int wm_edit_is_multiline(const Window *w);
void wm_edit_get_sel(const Window *w, int *start, int *end);                      /* the selection, start <= end (equal: none) */
void wm_edit_set_sel(Window *w, int start, int end);                              /* EM_SETSEL: -1 for the end is "the end of the text"; start -1 with end 0 removes the selection */
int wm_edit_text(Window *w, const char *s, int n);                                /* type n bytes: replaces the selection, the limit and ES_NUMBER apply; returns how many were taken; no-op when read-only or disabled */
int wm_edit_key(Window *w, uint32_t vk, int shift, int ctrl);                     /* a key press: arrows, Home, End, Page Up and Down, Delete, Ctrl+A C X V; returns 1 if the box used the key */
int wm_edit_char(Window *w, uint32_t ch);                                         /* WM_CHAR: a printable character, Backspace, Enter in a multi-line box */
int wm_edit_mouse(Window *w, int kind, int x, int y, int shift);                  /* IN_DOWN, IN_MOVE (with the button held) and IN_UP at a screen point (a second and third press in a row are the double and triple click); returns 1 if used */
void wm_edit_note_key(uint32_t hwnd, uint32_t vk, int shift, int ctrl);           /* input.c: Shift and Control as they were when this key press was made (the keys may be let go before the box gets the message) */
uint32_t wm_edit_dragging(void);                                                  /* the edit box whose text the mouse is selecting (or whose scroll thumb it is dragging), or 0 */
void wm_edit_reset(Window *w);                                                    /* the text was set from outside (WM_SETTEXT, SetWindowText): the caret goes to the start, nothing is selected */
void wm_edit_tick(void);                                                          /* from the host's serve loop: the caret's blink is a change of the picture */
void wm_edit_wheel(Window *w, int clicks);                                        /* the mouse wheel over a multi-line box */
enum { EDIT_FOCUS_LOST = 0, EDIT_FOCUS_SET = 1, EDIT_FOCUS_DIALOG = 2 };
void wm_edit_focus(Window *w, int how);                                           /* the box loses the focus (it hides its selection), gains it from SetFocus or a click (the caret shows from now; the selection is as it was) or from the dialog manager (Tab: all of the text is selected, as Windows does) */
uint32_t wm_edit_message(Window *w, uint32_t msg, uint32_t wp, uint32_t lp);      /* the EM_ messages, WM_CUT, WM_COPY, WM_PASTE, WM_CLEAR, WM_SETTEXT's effect on the caret ... */
int wm_edit_caret_visible(const Window *w);                                        /* whether the caret is drawn now: the box has the focus (or the file dialog's has_caret) and the blink is in its on half */

/* ui.c: where things are in an edit box, from the same layout the drawing uses */
int ui_edit_index_at(const Window *w, int x, int y);                              /* the byte offset at a screen point */
int ui_edit_scroll_to_caret(Window *w);                                           /* scroll so that the caret shows (changes edit_xscroll / edit_top); returns 1 if it did */
int ui_edit_page_lines(const Window *w);                                          /* the visual lines a multi-line box shows */
int ui_edit_line_count(const Window *w);                                          /* ... and all it has, wrapped to its width */
int ui_edit_line_of(const Window *w, int offset);                                 /* the visual line a byte offset is on */
int ui_edit_line_range(const Window *w, int line, int *start, int *end);          /* the byte range [start, end) of a visual line without its line break; 0 if there is no such line */
int ui_edit_x_in_line(const Window *w, int offset);                               /* the pixels from the start of the visual line an offset is on to the offset */
int ui_edit_offset_at(const Window *w, int line, int x);                          /* the offset on a visual line nearest to x pixels from its start */
int ui_edit_vscroll_pos(const Window *w, int y);                                  /* the first line to show for the scroll thumb dragged to a screen y */
int ui_edit_vscroll_hit(const Window *w, int x, int y, int *part);                /* a press on a multi-line box's scroll bar: 1 if it is on it; *part: 0 up arrow, 1 down arrow, 2 page up, 3 page down, 4 thumb */

/* input from the host (the SDL front end): screen pixels */
enum { IN_MOVE, IN_DOWN, IN_UP, IN_RDOWN, IN_RUP, IN_WHEEL };      /* IN_WHEEL: y is the number of clicks, positive away from the user (scrolls up) */
int wm_inject_mouse(int kind, int x, int y);
int wm_inject_key(uint32_t vk, uint32_t scancode, int down, int ch, int repeat);
int wm_inject_char(int ch);                      /* WM_CHAR alone, to the open dialog or the window that has the keys */
int wm_text_focus(void);                         /* an edit control of the open modal dialog, or (no dialog open) one with the keyboard focus on a page, is there to be typed into (the on-screen keyboard may show) */
extern int wm_cursor_x, wm_cursor_y;
extern uint8_t wm_keys[256];
void wm_clear_presses(void);                      /* ... forget them all (a movie is about to start: the click that started it is not the one that stops it) */
void wm_note_press(uint32_t vk);                 /* a key or mouse button went down (VK_LBUTTON 1, VK_RBUTTON 2): bit 0 of GetAsyncKeyState until it is asked */

uint32_t wm_hit_test(int x, int y);
void wm_dump(FILE *f);
void wm_popup_dump(FILE *f);                  /* an open popup menu, one line per row with its pixel box (PORT_CONTROL windows) */
void wm_dump_queue(FILE *f);                 /* every window: handle, parent, class, title, rectangle, visibility (debugging aid) */

/* the registries other modules add their APIs to */
extern const WinApi USER32_APIS[], CONTROLS_APIS[], FILEDLG_APIS[], WINHELP_APIS[], MSGBOX_APIS[], MENUS_APIS[], GDI32_STATE_APIS[], GDI32_BLIT_APIS[], GDI32_TEXT_APIS[];

/* the case-insensitive class name and string helpers */
char *wm_strdup_guest(uint32_t addr);

/* timing and the pump hook the host uses to serve its own events */
extern void (*wm_pump_hook)(void);

/* resources and dialogs */
int pe_find_resource(uint32_t hinst, uint32_t type, uint32_t name, uint32_t *addr, uint32_t *size);

#endif

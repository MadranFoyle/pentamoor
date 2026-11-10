/* edit.c - the EDIT control: single-line and multi-line text boxes with a caret, a selection, the clipboard and the messages of Windows (EM_..., WM_CHAR, WM_CUT, WM_COPY, WM_PASTE).
 *
 * The text is the window's own title, in bytes (the game is Windows-1252: one byte a character). A multi-line box keeps its line breaks as CR LF, as Windows does, and the caret never sits
 * between the two. The caret is `caret`, the other end of the selection `sel_anchor`; the selection is the bytes between them. Where things are on the screen (which offset is under a point,
 * scrolling the caret into view, the wrapped lines of a multi-line box) is ui.c's, from the layout it draws with (ui_edit_...).
 *
 * What the keyboard does: the arrows, Home, End, Page Up and Down, with Shift to extend the selection and Ctrl to go by words (or to the ends of the text); Delete; Backspace (WM_CHAR 8) and
 * Ctrl+Backspace (127) at the caret; Ctrl+A, C, X, V (and Ctrl+Insert, Shift+Delete, Shift+Insert) with the host's clipboard; typing replaces the selection. A read-only box (ES_READONLY) can
 * be moved in, selected from and copied from. ES_NUMBER takes digits only (typed or pasted), EM_LIMITTEXT limits the length. A one-line box ignores line breaks. The mouse: a press puts the
 * caret there, a drag selects, Shift extends, a double click selects a word, a triple click the line (all of a one-line box), and a multi-line box has its wheel and its scroll bar.
 * The caret blinks (about twice a second) in the box that has the keyboard focus, from the last time it moved; wm_edit_tick makes the screen redraw when it should change.
 *
 * Where it is not Windows 98: no undo (EM_UNDO says there is nothing to undo), no EM_SETWORDBREAKPROC, tab stops, or rich text. */
#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "front.h"
#include "gdi_int.h"
#include "sched.h"
#include "wm.h"

#define P(a) ((char *)(G + (a)))

enum {
    EN_CHANGE = 0x300,
    EM_GETSEL = 0xB0, EM_SETSEL = 0xB1, EM_SCROLL = 0xB5, EM_LINESCROLL = 0xB6, EM_SCROLLCARET = 0xB7, EM_GETMODIFY = 0xB8, EM_SETMODIFY = 0xB9, EM_GETLINECOUNT = 0xBA, EM_LINEINDEX = 0xBB,
    EM_LINELENGTH = 0xC1, EM_REPLACESEL = 0xC2, EM_GETLINE = 0xC4, EM_LIMITTEXT = 0xC5, EM_CANUNDO = 0xC6, EM_UNDO = 0xC7, EM_FMTLINES = 0xC8, EM_LINEFROMCHAR = 0xC9, EM_SETTABSTOPS = 0xCB,
    EM_SETPASSWORDCHAR = 0xCC, EM_EMPTYUNDOBUFFER = 0xCD, EM_GETFIRSTVISIBLELINE = 0xCE, EM_SETREADONLY = 0xCF, EM_GETPASSWORDCHAR = 0xD2, EM_SETMARGINS = 0xD3, EM_GETLIMITTEXT = 0xD5,
    WM_GETDLGCODE = 0x87, WM_CUT = 0x300, WM_COPY = 0x301, WM_PASTE = 0x302, WM_CLEAR = 0x303, WM_UNDO = 0x304,
    ES_WANTRETURN = 0x1000
};
enum { VK_BACK = 8, VK_PRIOR = 0x21, VK_NEXT = 0x22, VK_END = 0x23, VK_HOME = 0x24, VK_LEFT = 0x25, VK_UP = 0x26, VK_RIGHT = 0x27, VK_DOWN = 0x28, VK_INSERT = 0x2D, VK_DELETE = 0x2E };

int wm_edit_is_edit(const Window *w) { return w && w->cname && !strcasecmp(w->cname, "EDIT"); }
int wm_edit_is_multiline(const Window *w) { return wm_edit_is_edit(w) && (w->style & ES_MULTILINE); }

static int text_len(const Window *w) { return w->title ? (int)strlen(w->title) : 0; }
static int is_space(char c) { return c == ' ' || c == '\t' || c == '\r' || c == '\n'; }

static void clamp(Window *w)
{
    int n = text_len(w);

    if (w->caret < 0)
        w->caret = 0;
    if (w->caret > n)
        w->caret = n;
    if (w->sel_anchor < 0)
        w->sel_anchor = 0;
    if (w->sel_anchor > n)
        w->sel_anchor = n;
}

static void touched(Window *w)                           /* the caret moved or the text changed: redraw, and the blink starts again with the caret shown */
{
    w->edit_t = port_now_ms();
    w->invalid = 1;
    wm_dirty = 1;
    ui_edit_scroll_to_caret(w);
}

static void notify_change(Window *w) { wm_post(w->parent, WM_COMMAND, ((uint32_t)EN_CHANGE << 16) | (w->id & 0xFFFF), w->hwnd); }

/* ---- the text ---------------------------------------------------------------------------------------------------------------------- */
static int limit_of(const Window *w)
{
    if (w->edit_limit > 0)
        return w->edit_limit;
    return (w->style & ES_MULTILINE) ? 0x100000 : 32767;
}

/* Replace [a, b) with n bytes, within the limit; the caret goes after what was put in. Returns how many bytes went in. */
static int replace(Window *w, int a, int b, const char *ins, int n, int notify)
{
    int len = text_len(w), room, tail;
    char *t;

    if (a < 0)
        a = 0;
    if (b > len)
        b = len;
    if (a > b)
        a = b;
    room = limit_of(w) - (len - (b - a));
    if (room < 0)
        room = 0;
    if (n > room)
        n = room;
    if (a == b && n == 0)
        return 0;
    tail = len - b;
    t = malloc((size_t)(len - (b - a) + n) + 1);
    if (!t)
        return 0;
    memcpy(t, w->title, (size_t)a);
    memcpy(t + a, ins, (size_t)n);
    memcpy(t + a + n, w->title + b, (size_t)tail + 1);
    free(w->title);
    w->title = t;
    w->caret = w->sel_anchor = a + n;
    w->edit_modified = 1;
    touched(w);
    if (notify)
        notify_change(w);
    return n;
}

/* What a one-line box makes of text: it ends at the first line break; a multi-line box makes every break CR LF. Returns malloc'ed text (and its length), filtered to digits for ES_NUMBER. */
static char *normalize(const Window *w, const char *s, int n, int *outn, int digits_only)
{
    char *o = malloc((size_t)n * 2 + 1);
    int i, k = 0, ml = (w->style & ES_MULTILINE) != 0;

    if (!o)
        return NULL;
    for (i = 0; i < n; i++) {
        unsigned char c = (unsigned char)s[i];

        if (c == '\r' || c == '\n') {
            if (!ml)
                break;
            if (c == '\r' && i + 1 < n && s[i + 1] == '\n')
                i++;
            o[k++] = '\r';
            o[k++] = '\n';
        } else if (digits_only && (c < '0' || c > '9')) {
            continue;
        } else if (c >= 32 && c != 127) {
            o[k++] = (char)c;
        } else if (c == '\t' && ml) {
            o[k++] = (char)c;
        }
    }
    o[k] = 0;
    *outn = k;
    return o;
}

int wm_edit_text(Window *w, const char *s, int n)
{
    char *t;
    int k, a, b, took;

    if (!wm_edit_is_edit(w) || !w->enabled || (w->style & ES_READONLY) || n <= 0)
        return 0;
    clamp(w);
    t = normalize(w, s, n, &k, (w->style & ES_NUMBER) != 0);
    if (!t)
        return 0;
    a = w->sel_anchor < w->caret ? w->sel_anchor : w->caret;
    b = w->sel_anchor < w->caret ? w->caret : w->sel_anchor;
    took = k > 0 || a != b ? replace(w, a, b, t, k, 1) : 0;
    free(t);
    return took;
}

void wm_edit_get_sel(const Window *w, int *start, int *end)
{
    int c = w->caret, a = w->sel_anchor, n = text_len(w);

    c = c < 0 ? 0 : c > n ? n : c;
    a = a < 0 ? 0 : a > n ? n : a;
    if (start)
        *start = a < c ? a : c;
    if (end)
        *end = a < c ? c : a;
}

void wm_edit_set_sel(Window *w, int start, int end)
{
    int n = text_len(w);

    if (!wm_edit_is_edit(w))
        return;
    if (start < 0) {                                         /* -1: no selection (the caret stays) */
        clamp(w);
        w->sel_anchor = w->caret;
    } else {
        if (end < 0 || end > n)
            end = n;
        if (start > n)
            start = n;
        w->sel_anchor = start;
        w->caret = end;
    }
    touched(w);
}

void wm_edit_reset(Window *w)                                /* the text was set from outside (WM_SETTEXT, SetWindowText): caret to the start, no selection, no scroll */
{
    if (!wm_edit_is_edit(w))
        return;
    w->caret = w->sel_anchor = 0;
    w->edit_xscroll = w->edit_top = 0;
    w->edit_modified = 0;
    w->invalid = 1;
    wm_dirty = 1;
}

/* ---- moving ---------------------------------------------------------------------------------------------------------------------- */
static int prev_char(const Window *w, int c)
{
    if (c <= 0)
        return 0;
    if (c >= 2 && w->title[c - 1] == '\n' && w->title[c - 2] == '\r')
        return c - 2;
    return c - 1;
}

static int next_char(const Window *w, int c)
{
    int n = text_len(w);

    if (c >= n)
        return n;
    if (w->title[c] == '\r' && c + 1 < n && w->title[c + 1] == '\n')
        return c + 2;
    return c + 1;
}

static int word_left(const Window *w, int c)
{
    while (c > 0 && is_space(w->title[c - 1]))
        c--;
    while (c > 0 && !is_space(w->title[c - 1]))
        c--;
    return c;
}

static int word_right(const Window *w, int c)
{
    int n = text_len(w);

    while (c < n && !is_space(w->title[c]))
        c++;
    while (c < n && is_space(w->title[c]))
        c++;
    return c;
}

static void word_at(const Window *w, int c, int *a, int *b)
{
    int n = text_len(w);
    int pivot = c < n ? c : (n > 0 ? n - 1 : 0);
    int space;

    if (n == 0) {
        *a = *b = 0;
        return;
    }
    space = is_space(w->title[pivot]);
    *a = pivot;
    *b = pivot;
    while (*a > 0 && is_space(w->title[*a - 1]) == space)
        (*a)--;
    while (*b < n && is_space(w->title[*b]) == space)
        (*b)++;
}

static int line_start(const Window *w, int c)
{
    int s, e;

    return ui_edit_line_range(w, ui_edit_line_of(w, c), &s, &e) ? s : 0;
}

static int line_end(const Window *w, int c)
{
    int s, e, n = text_len(w);

    if (!ui_edit_line_range(w, ui_edit_line_of(w, c), &s, &e))
        return n;
    if (e > s && e < n && w->title[e - 1] == ' ' && w->title[e] != '\r' && w->title[e] != '\n')
        e--;                                                 /* a wrapped line ends before the space that hangs on it, so the caret stays on that line */
    return e;
}

static int vertical(const Window *w, int c, int lines)       /* the offset `lines` visual lines down (negative: up) at about the same x */
{
    int line = ui_edit_line_of(w, c), target = line + lines, s, e, count = ui_edit_line_count(w);

    if (target < 0)
        target = 0;
    if (target >= count)
        target = count - 1;
    if (target == line && lines != 0) {                      /* at the first or last line: the start or the end of the text, as Windows does */
        return lines < 0 ? 0 : text_len(w);
    }
    if (!ui_edit_line_range(w, target, &s, &e))
        return c;
    return ui_edit_offset_at(w, target, ui_edit_x_in_line(w, c));
}

/* ---- clipboard ---------------------------------------------------------------------------------------------------------------------- */
static void copy_sel(Window *w)
{
    int a, b;
    char *t;

    if (w->style & ES_PASSWORD)
        return;
    wm_edit_get_sel(w, &a, &b);
    if (a == b)
        return;
    t = malloc((size_t)(b - a) + 1);
    if (!t)
        return;
    memcpy(t, w->title + a, (size_t)(b - a));
    t[b - a] = 0;
    front_clipboard_set(t);
    free(t);
}

static void delete_sel(Window *w)
{
    int a, b;

    wm_edit_get_sel(w, &a, &b);
    if (a != b)
        replace(w, a, b, "", 0, 1);
}

static void paste(Window *w)
{
    char *t = front_clipboard_get();

    if (t) {
        wm_edit_text(w, t, (int)strlen(t));
        free(t);
    }
}

/* ---- keys -------------------------------------------------------------------------------------------------------------------------- */
int wm_edit_key(Window *w, uint32_t vk, int shift, int ctrl)
{
    int ro, ml, c, a, n, nc, move = 0, page;

    if (!wm_edit_is_edit(w))
        return 0;
    clamp(w);
    ro = (w->style & ES_READONLY) != 0 || !w->enabled;
    ml = (w->style & ES_MULTILINE) != 0;
    c = w->caret;
    a = w->sel_anchor;
    n = text_len(w);
    nc = c;
    page = ml ? ui_edit_page_lines(w) : 1;
    switch (vk) {
    case VK_LEFT:
        nc = (!shift && a != c) ? (a < c ? a : c) : ctrl ? word_left(w, c) : prev_char(w, c);
        move = 1;
        break;
    case VK_RIGHT:
        nc = (!shift && a != c) ? (a < c ? c : a) : ctrl ? word_right(w, c) : next_char(w, c);
        move = 1;
        break;
    case VK_HOME:
        nc = (ctrl || !ml) ? 0 : line_start(w, c);
        move = 1;
        break;
    case VK_END:
        nc = (ctrl || !ml) ? n : line_end(w, c);
        move = 1;
        break;
    case VK_UP:
    case VK_DOWN:
        if (!ml)
            return 0;
        nc = vertical(w, c, vk == VK_UP ? -1 : 1);
        move = 1;
        break;
    case VK_PRIOR:
    case VK_NEXT:
        if (!ml)
            return 0;
        nc = vertical(w, c, vk == VK_PRIOR ? -page : page);
        w->edit_top += vk == VK_PRIOR ? -page : page;
        move = 1;
        break;
    case VK_DELETE:
        if (shift && !ctrl) {                                /* Shift+Delete: cut */
            copy_sel(w);
            if (!ro)
                delete_sel(w);
            return 1;
        }
        if (ro)
            return 1;
        if (a != c)
            delete_sel(w);
        else if (c < n)
            replace(w, c, ctrl ? word_right(w, c) : next_char(w, c), "", 0, 1);
        return 1;
    case VK_INSERT:
        if (ctrl)
            copy_sel(w);
        else if (shift && !ro)
            paste(w);
        return 1;
    case 'A':
        if (!ctrl)
            return 0;
        w->sel_anchor = 0;
        w->caret = n;
        touched(w);
        return 1;
    case 'C':
        if (!ctrl)
            return 0;
        copy_sel(w);
        return 1;
    case 'X':
        if (!ctrl)
            return 0;
        copy_sel(w);
        if (!ro)
            delete_sel(w);
        return 1;
    case 'V':
        if (!ctrl)
            return 0;
        if (!ro)
            paste(w);
        return 1;
    default:
        return 0;
    }
    if (move) {
        w->caret = nc < 0 ? 0 : nc > n ? n : nc;
        if (!shift)
            w->sel_anchor = w->caret;
        touched(w);
        if (vk == VK_PRIOR || vk == VK_NEXT) {               /* the view moved by a page, wherever the caret went */
            int total = ui_edit_line_count(w);

            if (w->edit_top > total - page)
                w->edit_top = total - page;
            if (w->edit_top < 0)
                w->edit_top = 0;
        }
    }
    return 1;
}

int wm_edit_char(Window *w, uint32_t ch)
{
    int ml, c, a, n;
    char b[2];

    if (!wm_edit_is_edit(w) || !w->enabled)
        return 0;
    clamp(w);
    ml = (w->style & ES_MULTILINE) != 0;
    if (w->style & ES_READONLY)
        return 0;
    n = text_len(w);
    if (ch == 8) {                                           /* Backspace */
        c = w->caret;
        a = w->sel_anchor;
        if (a != c)
            delete_sel(w);
        else if (c > 0)
            replace(w, prev_char(w, c), c, "", 0, 1);
        return 1;
    }
    if (ch == 127) {                                         /* Ctrl+Backspace: the word before the caret */
        c = w->caret;
        if (w->sel_anchor != c)
            delete_sel(w);
        else if (c > 0)
            replace(w, word_left(w, c), c, "", 0, 1);
        return 1;
    }
    if (ch == 13 && ml && (w->style & ES_WANTRETURN))
        return wm_edit_text(w, "\r\n", 2) > 0;
    if (ch == 10 && ml)                                      /* Ctrl+Enter */
        return wm_edit_text(w, "\r\n", 2) > 0;
    if (ch >= 32 && ch < 256 && ch != 127) {
        b[0] = (char)ch;
        b[1] = 0;
        (void)n;
        return wm_edit_text(w, b, 1) > 0;
    }
    return 0;
}

/* ---- the mouse ----------------------------------------------------------------------------------------------------------------------- */
static uint32_t drag_h;

uint32_t wm_edit_dragging(void)
{
    Window *w = wm_window(drag_h);

    return w && w->edit_drag ? drag_h : 0;
}

static uint32_t click_t, click_h;                           /* the last press in an edit box: when, where, and how many presses in a row (for the double and triple click) */
static int click_x, click_y, click_n;

int wm_edit_mouse(Window *w, int kind, int x, int y, int shift)
{
    if (!wm_edit_is_edit(w))
        return 0;
    clamp(w);
    if (kind == IN_DOWN) {
        uint32_t now = port_now_ms();
        int part, idx;

        if ((w->style & ES_MULTILINE) && ui_edit_vscroll_hit(w, x, y, &part)) {
            int page = ui_edit_page_lines(w), total = ui_edit_line_count(w), top = w->edit_top;

            switch (part) {
            case 0: top -= 1; break;
            case 1: top += 1; break;
            case 2: top -= page - 1; break;
            case 3: top += page - 1; break;
            default: w->edit_drag = 2; drag_h = w->hwnd; break;
            }
            w->edit_top = top < 0 ? 0 : top > total - page ? (total - page > 0 ? total - page : 0) : top;
            w->invalid = 1;
            wm_dirty = 1;
            return 1;
        }
        idx = ui_edit_index_at(w, x, y);
        if (click_h == w->hwnd && now - click_t <= 500 && abs(x - click_x) <= 4 && abs(y - click_y) <= 4)
            click_n++;
        else
            click_n = 1;
        click_t = now;
        click_h = w->hwnd;
        click_x = x;
        click_y = y;
        if (click_n == 2) {                                   /* a double click: the word */
            int a, b;

            word_at(w, idx, &a, &b);
            w->sel_anchor = a;
            w->caret = b;
        } else if (click_n >= 3) {                            /* a triple click: the line (all of a one-line box) */
            int a = 0, b = text_len(w);

            if (w->style & ES_MULTILINE) {
                int s, e, l = ui_edit_line_of(w, idx);

                if (ui_edit_line_range(w, l, &s, &e)) {
                    a = s;
                    b = e;
                    if (b < text_len(w) && w->title[b] == '\r')
                        b += (b + 1 < text_len(w) && w->title[b + 1] == '\n') ? 2 : 1;
                    else if (b < text_len(w) && w->title[b] == '\n')
                        b++;
                }
            }
            w->sel_anchor = a;
            w->caret = b;
            click_n = 0;
        } else {
            w->caret = idx;
            if (!shift)
                w->sel_anchor = idx;
        }
        w->edit_drag = 1;
        drag_h = w->hwnd;
        touched(w);
        return 1;
    }
    if (kind == IN_MOVE && w->edit_drag) {
        if (w->edit_drag == 2) {
            w->edit_top = ui_edit_vscroll_pos(w, y);
            w->invalid = 1;
            wm_dirty = 1;
        } else {
            int idx = ui_edit_index_at(w, x, y);

            if (idx != w->caret) {
                w->caret = idx;
                touched(w);
            }
        }
        return 1;
    }
    if (kind == IN_UP && w->edit_drag) {
        if (w->edit_drag == 1 && (x != click_x || y != click_y)) {          /* the release is the last place the pointer was (a move or two may have been merged into it), but a click's own release is not a drag */
            int idx = ui_edit_index_at(w, x, y);

            if (idx != w->caret) {
                w->caret = idx;
                touched(w);
            }
        }
        w->edit_drag = 0;
        return 1;
    }
    return 0;
}

void wm_edit_wheel(Window *w, int clicks)
{
    int total, page;

    if (!wm_edit_is_multiline(w))
        return;
    total = ui_edit_line_count(w);
    page = ui_edit_page_lines(w);
    w->edit_top -= clicks * 3;
    if (w->edit_top > total - page)
        w->edit_top = total - page;
    if (w->edit_top < 0)
        w->edit_top = 0;
    w->invalid = 1;
    wm_dirty = 1;
}

/* ---- focus and the caret ---------------------------------------------------------------------------------------------------------- */
void wm_edit_focus(Window *w, int how)
{
    if (!wm_edit_is_edit(w))
        return;
    if (how == EDIT_FOCUS_LOST) {
        w->edit_drag = 0;
        w->invalid = 1;
        wm_dirty = 1;
        return;
    }
    clamp(w);
    if (how == EDIT_FOCUS_DIALOG) {                         /* the dialog manager moved it here (Tab, the dialog's first control): the whole text is selected */
        w->sel_anchor = 0;
        w->caret = text_len(w);
    }
    w->edit_t = port_now_ms();                              /* the caret shows from now */
    w->invalid = 1;
    wm_dirty = 1;
    ui_edit_scroll_to_caret(w);
}

int wm_edit_caret_visible(const Window *w)
{
    uint32_t now = port_now_ms();

    if (w->has_caret)
        return (now / 500) % 2 == 0;
    if (wm_get_focus() != w->hwnd)
        return 0;
    return ((now - w->edit_t) / 530) % 2 == 0;
}

void wm_edit_tick(void)                                      /* the host's serve loop: a blinking caret is a change of the picture */
{
    static uint32_t last_h;
    static int last_phase = -1;
    Window *w = wm_window(wm_get_focus());
    int phase;

    if (!wm_edit_is_edit(w) || !w->visible) {
        last_h = 0;
        return;
    }
    phase = wm_edit_caret_visible(w);
    if (last_h != w->hwnd || phase != last_phase) {
        last_h = w->hwnd;
        last_phase = phase;
        wm_dirty = 1;
    }
}

/* ---- the modifier keys of a key press --------------------------------------------------------------------------------------------------- */
/* Shift and Control are read from the keyboard's state when the key press is delivered to the program, which may be after the keys have been let go again (the press is posted, the program
 * takes it from the queue later: a script, or a program that is busy, does that). So input.c notes the state with the press, and the box takes it from here when the message arrives. */
static struct { uint32_t hwnd, vk, t; int shift, ctrl; } held_mods[32];
static int nheld;

void wm_edit_note_key(uint32_t hwnd, uint32_t vk, int shift, int ctrl)
{
    if (nheld == 32) {
        memmove(held_mods, held_mods + 1, 31 * sizeof(held_mods[0]));
        nheld--;
    }
    held_mods[nheld].t = port_now_ms();
    held_mods[nheld].hwnd = hwnd;
    held_mods[nheld].vk = vk;
    held_mods[nheld].shift = shift;
    held_mods[nheld].ctrl = ctrl;
    nheld++;
}

static int take_mods(uint32_t hwnd, uint32_t vk, int *shift, int *ctrl)
{
    int i;
    uint32_t now = port_now_ms();

    while (nheld > 0 && now - held_mods[0].t > 2000) {           /* a press the program never took (it handled the key before the box saw it) is forgotten */
        memmove(held_mods, held_mods + 1, (size_t)(nheld - 1) * sizeof(held_mods[0]));
        nheld--;
    }
    for (i = 0; i < nheld; i++)
        if (held_mods[i].hwnd == hwnd && held_mods[i].vk == vk) {
            *shift = held_mods[i].shift;
            *ctrl = held_mods[i].ctrl;
            memmove(held_mods + i, held_mods + i + 1, (size_t)(nheld - i - 1) * sizeof(held_mods[0]));
            nheld--;
            return 1;
        }
    return 0;
}

/* ---- messages ---------------------------------------------------------------------------------------------------------------------- */
static int logical_line_of(const Window *w, int off)         /* EM_LINEFROMCHAR counts wrapped lines, as Windows' multi-line box does */
{
    return wm_edit_is_multiline(w) ? ui_edit_line_of(w, off) : 0;
}

uint32_t wm_edit_message(Window *w, uint32_t msg, uint32_t wp, uint32_t lp)
{
    int n = text_len(w), s, e;

    switch (msg) {
    case 0x102:                                              /* WM_CHAR */
        return wm_edit_char(w, wp) ? 0 : 0;
    case 0x100: {                                            /* WM_KEYDOWN: the shift and control keys are those held (GetKeyState); the Command key of a Mac counts as Control */
        int shift = wm_keys[0x10] != 0, ctrl = wm_keys[0x11] != 0 || wm_keys[0x5B] != 0 || wm_keys[0x5C] != 0;

        take_mods(w->hwnd, wp, &shift, &ctrl);                 /* what was held when the press was made, if it was noted; else what is held now */
        wm_edit_key(w, wp, shift, ctrl);
        return 0;
    }
    case WM_GETDLGCODE:
        return 0x80u | 0x8u | ((w->style & ES_MULTILINE) ? 0x1u | ((w->style & ES_WANTRETURN) ? 0x4u : 0) : 0);     /* DLGC_WANTCHARS | DLGC_HASSETSEL (| DLGC_WANTARROWS (| DLGC_WANTALLKEYS for Enter)) */
    case 0x7:                                                /* WM_SETFOCUS */
        wm_edit_focus(w, EDIT_FOCUS_SET);
        return 0;
    case 0x8:                                                /* WM_KILLFOCUS */
        wm_edit_focus(w, EDIT_FOCUS_LOST);
        return 0;
    case EM_LIMITTEXT:
        w->edit_limit = (int)wp;
        return 0;
    case EM_GETLIMITTEXT:
        return (uint32_t)limit_of(w);
    case EM_GETSEL:
        wm_edit_get_sel(w, &s, &e);
        if (wp)
            WR32(wp, (uint32_t)s);
        if (lp)
            WR32(lp, (uint32_t)e);
        return ((uint32_t)e << 16) | ((uint32_t)s & 0xFFFF);
    case EM_SETSEL:
        wm_edit_set_sel(w, (int)wp, (int)lp);
        return 1;
    case EM_REPLACESEL: {
        const char *t = lp ? P(lp) : "";
        int a, b, k;
        char *buf;

        clamp(w);
        wm_edit_get_sel(w, &a, &b);
        buf = normalize(w, t, (int)strlen(t), &k, 0);
        if (buf) {
            replace(w, a, b, buf, k, 1);
            free(buf);
        }
        return 0;
    }
    case WM_CUT:
        clamp(w);
        copy_sel(w);
        if (!(w->style & ES_READONLY))
            delete_sel(w);
        return 0;
    case WM_COPY:
        clamp(w);
        copy_sel(w);
        return 0;
    case WM_PASTE:
        clamp(w);
        if (!(w->style & ES_READONLY))
            paste(w);
        return 0;
    case WM_CLEAR:
        clamp(w);
        if (!(w->style & ES_READONLY))
            delete_sel(w);
        return 0;
    case EM_GETMODIFY:
        return (uint32_t)(w->edit_modified != 0);
    case EM_SETMODIFY:
        w->edit_modified = wp != 0;
        return 0;
    case EM_SETREADONLY:
        w->style = wp ? (w->style | ES_READONLY) : (w->style & ~(uint32_t)ES_READONLY);
        w->invalid = 1;
        wm_dirty = 1;
        return 1;
    case EM_GETLINECOUNT:
        return (uint32_t)(wm_edit_is_multiline(w) ? ui_edit_line_count(w) : 1);
    case EM_LINEFROMCHAR:
        clamp(w);
        return (uint32_t)logical_line_of(w, (int)wp == -1 ? w->caret : (int)wp);
    case EM_LINEINDEX: {
        int line = (int)wp == -1 ? logical_line_of(w, w->caret) : (int)wp;

        if (!wm_edit_is_multiline(w))
            return line == 0 ? 0 : (uint32_t)-1;
        return ui_edit_line_range(w, line, &s, &e) ? (uint32_t)s : (uint32_t)-1;
    }
    case EM_LINELENGTH: {
        int off = (int)wp == -1 ? w->caret : (int)wp;

        if (!wm_edit_is_multiline(w))
            return (uint32_t)n;
        return ui_edit_line_range(w, logical_line_of(w, off), &s, &e) ? (uint32_t)(e - s) : 0;
    }
    case EM_GETLINE: {
        int cap, k;

        if (!lp || !ui_edit_line_range(w, (int)wp, &s, &e))
            return 0;
        cap = (int)(RD32(lp) & 0xFFFF);                      /* the buffer's size is its first word */
        k = e - s < cap ? e - s : cap;
        memcpy(P(lp), w->title + s, (size_t)k);
        if (k < cap)
            P(lp)[k] = 0;
        return (uint32_t)k;
    }
    case EM_GETFIRSTVISIBLELINE:
        return (uint32_t)(wm_edit_is_multiline(w) ? w->edit_top : w->edit_xscroll);
    case EM_LINESCROLL:                                      /* lp lines down */
        if (wm_edit_is_multiline(w)) {
            int total = ui_edit_line_count(w), page = ui_edit_page_lines(w);

            w->edit_top += (int)lp;
            if (w->edit_top > total - page)
                w->edit_top = total - page;
            if (w->edit_top < 0)
                w->edit_top = 0;
            w->invalid = 1;
            wm_dirty = 1;
        }
        return 1;
    case EM_SCROLL: {                                        /* SB_LINEUP 0, SB_LINEDOWN 1, SB_PAGEUP 2, SB_PAGEDOWN 3 */
        int page = ui_edit_page_lines(w), by = wp == 0 ? -1 : wp == 1 ? 1 : wp == 2 ? -page : wp == 3 ? page : 0, before = w->edit_top, total = ui_edit_line_count(w);

        if (wm_edit_is_multiline(w)) {
            w->edit_top += by;
            if (w->edit_top > total - page)
                w->edit_top = total - page;
            if (w->edit_top < 0)
                w->edit_top = 0;
            w->invalid = 1;
            wm_dirty = 1;
        }
        return 0x80000000u | (uint32_t)((w->edit_top - before) & 0xFFFF);
    }
    case EM_SCROLLCARET:
        clamp(w);
        ui_edit_scroll_to_caret(w);
        w->invalid = 1;
        wm_dirty = 1;
        return 1;
    case EM_CANUNDO:
    case EM_UNDO:
    case WM_UNDO:
        return 0;
    case EM_EMPTYUNDOBUFFER:
    case EM_FMTLINES:
    case EM_SETTABSTOPS:
    case EM_SETPASSWORDCHAR:
    case EM_SETMARGINS:
        return 0;
    case EM_GETPASSWORDCHAR:
        return (w->style & ES_PASSWORD) ? '*' : 0;
    default:
        return 0;
    }
}

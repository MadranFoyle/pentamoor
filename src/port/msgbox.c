/* msgbox.c - MessageBoxA (user32): the modal box a program asks a question or reports an error with.
 *
 * It is an ordinary modal dialog (wm_dialog_box) built here in code, as the file dialog and the Help dialog are, so it is drawn by ui.c like Windows 98 draws one (MS Sans Serif 8, the
 * 3-D frame, a caption), is centred on the screen, takes the mouse, the keyboard and the controller (the D-pad's dialog navigation finds its push buttons), and the program waits in it
 * as it would on Windows. Every style is there: MB_OK, OKCANCEL, ABORTRETRYIGNORE, YESNOCANCEL, YESNO and RETRYCANCEL, with the default button MB_DEFBUTTON1 to 3 and an icon (a small
 * drawn one: the question mark, the exclamation mark, the error cross, the "i"). The answer is the button's id: IDOK, IDCANCEL, IDABORT, IDRETRY, IDIGNORE, IDYES, IDNO.
 *
 * The keys are Windows's: Enter (or Space) presses the button that has the focus (the default one at first; Tab, the arrow keys move it), a letter that is underlined on a button ("&Yes",
 * "&No", "&Abort", "&Retry", "&Ignore") presses it, and Esc is IDCANCEL when there is a Cancel button, IDOK when OK is the only button, and nothing for Yes/No and Abort/Retry/Ignore
 * (neither does the close box there). The decisions are plain functions (msgbox_spec, msgbox_key, msgbox_move, msgbox_layout) so the tests can check them.
 *
 * What this does to a run that nobody watches (the soak test, a script, CI on SDL's dummy drivers): it must not wait for an answer that cannot come, so there the box is not shown and the
 * call returns at once with the default button's id (IDOK for a plain OK box), logging "MessageBox: caption: text -> IDxx". PORT_MSGBOX=ask or auto overrides the guess. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <ctype.h>

#include "gdi_int.h"
#include "sched.h"
#include "wm.h"
#include "msgbox.h"

#define P(a) ((char *)(G + (a)))
#define FACE "MS Sans Serif"
#define PT 8

/* ---- what a style is ---------------------------------------------------------------------------------------------------------------- */
void msgbox_spec(uint32_t type, MsgBoxSpec *s)
{
    static const struct { int id; const char *label; } B[] = {
        {IDOK, "OK"}, {IDCANCEL, "Cancel"}, {IDABORT, "&Abort"}, {IDRETRY, "&Retry"}, {IDIGNORE, "&Ignore"}, {IDYES, "&Yes"}, {IDNO, "&No"}
    };
    static const int SETS[6][3] = {{IDOK, 0, 0}, {IDOK, IDCANCEL, 0}, {IDABORT, IDRETRY, IDIGNORE}, {IDYES, IDNO, IDCANCEL}, {IDYES, IDNO, 0}, {IDRETRY, IDCANCEL, 0}};
    unsigned t = type & MB_TYPEMASK, i;
    int d = (int)((type & MB_DEFMASK) >> 8);

    memset(s, 0, sizeof(*s));
    if (t > 5)
        t = 0;                                    /* a style this does not know (MB_CANCELTRYCONTINUE, ...): a plain OK box */
    for (i = 0; i < 3 && SETS[t][i]; i++) {
        s->id[s->n] = SETS[t][i];
        s->label[s->n] = B[SETS[t][i] - 1].label;
        if (SETS[t][i] == IDCANCEL)
            s->cancel = IDCANCEL;
        s->n++;
    }
    if (s->n == 1)
        s->cancel = IDOK;                         /* Esc and the close box close a box that has only OK */
    s->def = d < s->n ? d : 0;
    switch (type & MB_ICONMASK) {
    case MB_ICONHAND:        s->icon = 'x'; break;
    case MB_ICONQUESTION:    s->icon = '?'; break;
    case MB_ICONEXCLAMATION: s->icon = '!'; break;
    case MB_ICONASTERISK:    s->icon = 'i'; break;
    default:                 s->icon = 0;
    }
}

int msgbox_default_id(uint32_t type)
{
    MsgBoxSpec s;

    msgbox_spec(type, &s);
    return s.id[s.def];
}

/* the underlined letter of a label ("&Yes": 'Y'), or 0 */
static int accel_of(const char *label)
{
    const char *p = strchr(label, '&');

    return p && p[1] ? toupper((unsigned char)p[1]) : 0;
}

int msgbox_key(const MsgBoxSpec *s, int cur, uint32_t vk, int ch)
{
    int i;

    if (cur < 0 || cur >= s->n)
        cur = s->def;
    if (vk == 0x0D || vk == 0x20)
        return s->id[cur];
    if (vk == 0x1B)
        return s->cancel;
    if (ch < 0 && vk >= 'A' && vk <= 'Z')
        ch = (int)vk;                               /* a key that typed no character (SDL's text input is off, or it is a pad's key press): its letter */
    if (ch >= 32 && ch < 256)
        for (i = 0; i < s->n; i++)
            if (accel_of(s->label[i]) == toupper(ch))
                return s->id[i];
    return 0;
}

int msgbox_move(const MsgBoxSpec *s, int cur, uint32_t vk)
{
    if (cur < 0 || cur >= s->n)
        cur = s->def;
    if (vk == 0x09 || vk == 0x27 || vk == 0x28)                /* Tab, Right, Down */
        return (cur + 1) % s->n;
    if (vk == 0x25 || vk == 0x26)                              /* Left, Up */
        return (cur + s->n - 1) % s->n;
    return cur;
}

/* ---- how big it is ------------------------------------------------------------------------------------------------------------------ */
void msgbox_layout(const MsgBoxSpec *s, const char *caption, const char *text, int sw, MsgBoxLayout *L)
{
    enum { M = 12, ICON = 32, GAP = 12, BW = 75, BH = 23, BGAP = 9 };
    int maxw = sw * 11 / 20, left, tw = 0, th, row, cw, ch, capw, i;

    if (maxw < 240)
        maxw = 240;
    if (maxw > 520)
        maxw = 520;
    memset(L, 0, sizeof(*L));
    left = M + (s->icon ? ICON + GAP : 0);
    th = ui_text_measure(FACE, PT, 0, text, maxw, &tw);
    row = s->n * BW + (s->n - 1) * BGAP;
    capw = ui_text_width(FACE, PT, 1, caption, strlen(caption)) + 3 + 3 + 20;      /* the title, the frame and the close box */
    cw = left + tw + M;
    if (cw < row + 2 * M)
        cw = row + 2 * M;
    if (cw < capw)
        cw = capw;
    ch = th > (s->icon ? ICON : 0) ? th : (s->icon ? ICON : 0);
    L->text_w = cw - left - M;
    L->text_h = th;
    L->text_x = left;
    L->text_y = M + (ch - th) / 2;
    L->icon_x = s->icon ? M : -1;
    L->icon_y = M + (ch - (s->icon ? ICON : 0)) / 2;
    L->btn_w = BW;
    L->btn_h = BH;
    L->btn_y = M + ch + GAP;
    for (i = 0; i < s->n; i++)
        L->btn_x[i] = (cw - row) / 2 + i * (BW + BGAP);
    L->client_w = cw;
    L->client_h = L->btn_y + BH + M;
}

/* ---- the mode ---------------------------------------------------------------------------------------------------------------------- */
static int mode_override;

int msgbox_mode_for(const char *env, int unattended)
{
    if (env && !strcasecmp(env, "ask"))
        return MSGBOX_ASK;
    if (env && !strcasecmp(env, "auto"))
        return MSGBOX_AUTO;
    return unattended ? MSGBOX_AUTO : MSGBOX_ASK;
}

int msgbox_mode(void)
{
    const char *drv = getenv("SDL_VIDEODRIVER");
    int unattended = getenv("PORT_CONTROL") != NULL || getenv("PORT_SCRIPT") != NULL || port_env_on("PORT_HEADLESS") || (drv && !strcasecmp(drv, "dummy"));

    return mode_override ? mode_override : msgbox_mode_for(getenv("PORT_MSGBOX"), unattended);
}

void msgbox_set_mode(int mode) { mode_override = mode; }

/* ---- the dialog --------------------------------------------------------------------------------------------------------------------- */
enum { C_BUTTON = 0x80, C_STATIC = 0x82 };

/* the template being written (a box made while another is open has its own) */
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

typedef struct State { int used; MsgBoxSpec spec; int cur; } State;
static State states[8];

static void set_focus(uint32_t hdlg, State *st, int cur)
{
    int i;

    st->cur = cur;
    for (i = 0; i < st->spec.n; i++) {
        Window *b = wm_dlg_item(hdlg, (uint32_t)st->spec.id[i]);

        if (b) {
            b->style = (b->style & ~0xFu) | (i == cur ? 1u : 0u);       /* the focused button is the one drawn as the default */
            b->invalid = 1;
        }
    }
    wm_dirty = 1;
}

static uint32_t msgbox_proc(const uint32_t *a)
{
    Window *dlg = wm_window(a[0]);
    uint32_t msg = a[1], wp = a[2];
    State *st = dlg && dlg->param >= 1 && dlg->param <= 8 ? &states[dlg->param - 1] : NULL;
    int id = 0, i;

    if (!st)
        return msg == WM_INITDIALOG ? 1 : 0;
    if (msg == WM_INITDIALOG) {
        dlg->own_keys = 1;                          /* Enter presses the focused button, which need not be IDOK */
        return 1;
    }
    if (msg == WM_COMMAND) {
        for (i = 0; i < st->spec.n; i++)
            if ((int)(wp & 0xFFFF) == st->spec.id[i])
                id = st->spec.id[i];
    } else if (msg == WM_KEYDOWN) {
        int nc = msgbox_move(&st->spec, st->cur, wp);

        if (nc != st->cur)
            set_focus(a[0], st, nc);
        else
            id = msgbox_key(&st->spec, st->cur, wp, -1);
    } else if (msg == WM_CHAR) {
        id = msgbox_key(&st->spec, st->cur, 0, (int)wp);
    } else if (msg == WM_CLOSE) {
        id = st->spec.cancel;
        if (!id)
            return 1;                               /* the close box does nothing here, and the default would destroy the dialog under the loop that waits on it */
    }
    if (id) {
        dlg->ended = 1;
        dlg->result = (uint32_t)id;
        return 1;
    }
    return 0;
}

static const char *id_name(int id)
{
    static const char *const N[] = {"?", "IDOK", "IDCANCEL", "IDABORT", "IDRETRY", "IDIGNORE", "IDYES", "IDNO"};

    return id >= 1 && id <= 7 ? N[id] : "?";
}

int msgbox_log_line(char *out, size_t cap, const char *caption, const char *text, int id, int answered)
{
    return snprintf(out, cap, "MessageBox: %s: %s -> %s%s", caption, text, id_name(id), answered ? " (answered)" : "");
}

int msgbox_show(uint32_t owner, const char *caption, const char *text, uint32_t type)
{
    static uint32_t proc;
    MsgBoxSpec sp;
    MsgBoxLayout L;
    char cap[128], icon[3] = {1, 0, 0}, *txt;
    int slot, i, bx = 8, by = 16, id;
    uint32_t result;
    Tmpl t;

    if (!proc)
        proc = port_host_function(msgbox_proc);
    for (slot = 0; slot < 8 && states[slot].used; slot++)
        ;
    if (slot == 8)
        return msgbox_default_id(type);             /* eight boxes over each other: none of this is real */
    msgbox_spec(type, &sp);
    snprintf(cap, sizeof(cap), "%s", caption);
    txt = malloc(2000);
    snprintf(txt, 2000, "%s", text);                /* what goes into the template is bounded: it is two bytes a character */
    msgbox_layout(&sp, cap, txt, screen_w, &L);
    ui_font_metrics(FACE, PT, 0, &by, NULL, &bx);
    t.cap = 2 * strlen(txt) + 1024;
    t.b = malloc(t.cap);
    t.n = 0;
#define DX(px) (((px) * 4 + bx - 1) / bx)           /* pixels to dialog units, rounded up so that the pixels come back at least as big */
#define DY(px) (((px) * 8 + by - 1) / by)
    t32(&t, 0x80C800C4u); t32(&t, 0); t16(&t, (unsigned)(1 + sp.n + (sp.icon ? 1 : 0)));    /* popup, caption, system menu, modal frame, 3-D look, font set */
    t16(&t, 0); t16(&t, 0); t16(&t, (unsigned)DX(L.client_w)); t16(&t, (unsigned)DY(L.client_h));
    t16(&t, 0); t16(&t, 0);                                                                /* no menu, the dialog class */
    twide(&t, cap);
    t16(&t, PT); twide(&t, FACE);
    if (sp.icon) {
        icon[1] = sp.icon;
        titem(&t, WS_VISIBLE | 3u, DX(L.icon_x), DY(L.icon_y), DX(32), DY(32), 0xFFFF, C_STATIC, icon);
    }
    titem(&t, WS_VISIBLE | 0x80u, DX(L.text_x), DY(L.text_y), DX(L.text_w), DY(L.text_h), 0xFFFF, C_STATIC, txt);    /* SS_NOPREFIX: an & in a message is an & */
    for (i = 0; i < sp.n; i++)
        titem(&t, WS_VISIBLE | WS_TABSTOP | (i == sp.def ? 1u : 0u), DX(L.btn_x[i]), DY(L.btn_y), DX(L.btn_w), DY(L.btn_h), (unsigned)sp.id[i], C_BUTTON, sp.label[i]);
    states[slot].used = 1;
    states[slot].spec = sp;
    states[slot].cur = sp.def;
    if (!wm_window(owner))
        owner = 0;
    result = wm_dialog_box(t.b, 0, owner, proc, (uint32_t)slot + 1);
    states[slot].used = 0;
    free(t.b);
    free(txt);
    id = (int)result;
    return id >= 1 && id <= 7 ? id : sp.id[sp.def];
}

int msgbox_run(uint32_t owner, const char *caption, const char *text, uint32_t type)
{
    int id, shown = msgbox_mode() == MSGBOX_ASK;
    char line[2200];

    if (!caption)
        caption = "Error";                          /* what Windows titles a box that has no caption */
    if (!text)
        text = "";
    id = shown ? msgbox_show(owner, caption, text, type) : msgbox_default_id(type);
    msgbox_log_line(line, sizeof(line), caption, text, id, shown);
    port_log("%s", line);
    return id;
}

static uint32_t MessageBoxA(const uint32_t *a)
{
    return (uint32_t)msgbox_run(a[0], a[2] ? P(a[2]) : NULL, a[1] ? P(a[1]) : NULL, a[3]);
}

const WinApi MSGBOX_APIS[] = {
    {"user32.dll", "MessageBoxA", MessageBoxA},
    {0, 0, 0},
};

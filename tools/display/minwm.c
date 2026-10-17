/* minwm: the least window manager SDL's X11 needs for the display tests, on a virtual X server (Xvfb).
 * EWMH: _NET_SUPPORTING_WM_CHECK, _NET_SUPPORTED, _NET_WORKAREA (a free area of the screen, less a "panel" of PANEL pixels at the bottom: the usable bounds SDL reports),
 * _NET_CURRENT_DESKTOP, _NET_WM_STATE_FULLSCREEN (a window asking at map time or by message becomes the size of the screen; leaving puts the old geometry back, as a real
 * window manager does), WM_NORMAL_HINTS minimum size (a resize request below it is clamped). No decorations: a window's position is where its client area is.
 * Usage: minwm [PANEL]; prints one line per event to stdout. */
#include <X11/Xlib.h>
#include <X11/Xatom.h>
#include <X11/Xutil.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static Display *d;
static Window root;
static Atom A_STATE, A_FS, A_CHECK, A_SUPPORTED, A_NAME, A_WORKAREA, A_DESKTOP;
static int sw, sh, panel;

#define MAXW 16
static struct { Window w; int x, y, wd, ht, saved; } fsw[MAXW];

static int slot(Window w)
{
    int i, free_i = -1;

    for (i = 0; i < MAXW; i++) {
        if (fsw[i].w == w)
            return i;
        if (!fsw[i].w && free_i < 0)
            free_i = i;
    }
    return free_i;
}

static int wants_fullscreen(Window w)
{
    Atom type;
    int fmt;
    unsigned long n, after, i;
    unsigned char *data = NULL;
    int yes = 0;

    if (XGetWindowProperty(d, w, A_STATE, 0, 32, False, XA_ATOM, &type, &fmt, &n, &after, &data) == Success && data) {
        for (i = 0; i < n; i++)
            yes |= ((Atom *)data)[i] == A_FS;
        XFree(data);
    }
    return yes;
}

static void fullscreen(Window w, int on)
{
    int i = slot(w);
    int isfs = wants_fullscreen(w);

    if (on) {
        XWindowAttributes a;

        if (i >= 0 && !fsw[i].saved && !isfs) {
            XGetWindowAttributes(d, w, &a);
            fsw[i].w = w; fsw[i].x = a.x; fsw[i].y = a.y; fsw[i].wd = a.width; fsw[i].ht = a.height; fsw[i].saved = 1;
        }
        XMoveResizeWindow(d, w, 0, 0, (unsigned)sw, (unsigned)sh);
        XChangeProperty(d, w, A_STATE, XA_ATOM, 32, PropModeReplace, (unsigned char *)&A_FS, 1);
        printf("minwm: 0x%lx full screen\n", w);
    } else {
        XDeleteProperty(d, w, A_STATE);
        if (i >= 0 && fsw[i].saved) {
            XMoveResizeWindow(d, w, fsw[i].x, fsw[i].y, (unsigned)fsw[i].wd, (unsigned)fsw[i].ht);
            printf("minwm: 0x%lx back to %dx%d at %d,%d\n", w, fsw[i].wd, fsw[i].ht, fsw[i].x, fsw[i].y);
            fsw[i].saved = 0;
            fsw[i].w = 0;
        }
    }
    fflush(stdout);
}

static void min_size(Window w, int *mw, int *mh)
{
    XSizeHints h;
    long supplied;

    *mw = *mh = 1;
    if (XGetWMNormalHints(d, w, &h, &supplied) && (h.flags & PMinSize)) {
        *mw = h.min_width;
        *mh = h.min_height;
    }
}

int main(int argc, char **argv)
{
    XEvent e;
    Window check;
    Atom supported[3];
    long area[4], desk = 0;

    panel = argc > 1 ? atoi(argv[1]) : 0;
    d = XOpenDisplay(NULL);
    if (!d)
        return 1;
    root = DefaultRootWindow(d);
    sw = DisplayWidth(d, 0);
    sh = DisplayHeight(d, 0);
    A_STATE = XInternAtom(d, "_NET_WM_STATE", False);
    A_FS = XInternAtom(d, "_NET_WM_STATE_FULLSCREEN", False);
    A_CHECK = XInternAtom(d, "_NET_SUPPORTING_WM_CHECK", False);
    A_SUPPORTED = XInternAtom(d, "_NET_SUPPORTED", False);
    A_NAME = XInternAtom(d, "_NET_WM_NAME", False);
    A_WORKAREA = XInternAtom(d, "_NET_WORKAREA", False);
    A_DESKTOP = XInternAtom(d, "_NET_CURRENT_DESKTOP", False);
    check = XCreateSimpleWindow(d, root, 0, 0, 1, 1, 0, 0, 0);
    XChangeProperty(d, root, A_CHECK, XA_WINDOW, 32, PropModeReplace, (unsigned char *)&check, 1);
    XChangeProperty(d, check, A_CHECK, XA_WINDOW, 32, PropModeReplace, (unsigned char *)&check, 1);
    XChangeProperty(d, check, A_NAME, XInternAtom(d, "UTF8_STRING", False), 8, PropModeReplace, (unsigned char *)"minwm", 5);
    supported[0] = A_STATE;
    supported[1] = A_FS;
    supported[2] = A_WORKAREA;
    XChangeProperty(d, root, A_SUPPORTED, XA_ATOM, 32, PropModeReplace, (unsigned char *)supported, 3);
    area[0] = 0; area[1] = 0; area[2] = sw; area[3] = sh - panel;
    XChangeProperty(d, root, A_WORKAREA, XA_CARDINAL, 32, PropModeReplace, (unsigned char *)area, 4);
    XChangeProperty(d, root, A_DESKTOP, XA_CARDINAL, 32, PropModeReplace, (unsigned char *)&desk, 1);
    XSelectInput(d, root, SubstructureRedirectMask | SubstructureNotifyMask);
    XSync(d, False);
    printf("minwm: %dx%d, free area %dx%d\n", sw, sh, sw, sh - panel);
    fflush(stdout);
    for (;;) {
        XNextEvent(d, &e);
        if (e.type == MapRequest) {
            Window w = e.xmaprequest.window;

            if (wants_fullscreen(w))
                fullscreen(w, 1);
            XMapWindow(d, w);
            XSetInputFocus(d, w, RevertToParent, CurrentTime);
        } else if (e.type == ConfigureRequest) {
            XConfigureRequestEvent *c = &e.xconfigurerequest;
            XWindowChanges ch;
            int mw, mh;

            if (wants_fullscreen(c->window)) {
                fullscreen(c->window, 1);
                continue;
            }
            min_size(c->window, &mw, &mh);
            ch.x = c->x; ch.y = c->y; ch.width = c->width; ch.height = c->height; ch.border_width = c->border_width; ch.sibling = c->above; ch.stack_mode = c->detail;
            if ((c->value_mask & CWWidth) && ch.width < mw)
                ch.width = mw;
            if ((c->value_mask & CWHeight) && ch.height < mh)
                ch.height = mh;
            XConfigureWindow(d, c->window, (unsigned)c->value_mask, &ch);
            printf("minwm: configure 0x%lx %s%s%s%s -> %d,%d %dx%d\n", c->window, c->value_mask & CWX ? "x" : "", c->value_mask & CWY ? "y" : "", c->value_mask & CWWidth ? "w" : "",
                   c->value_mask & CWHeight ? "h" : "", ch.x, ch.y, ch.width, ch.height);
            fflush(stdout);
        } else if (e.type == ClientMessage && e.xclient.message_type == A_STATE) {
            long action = e.xclient.data.l[0];
            Atom a = (Atom)e.xclient.data.l[1], b = (Atom)e.xclient.data.l[2];

            if (a == A_FS || b == A_FS)
                fullscreen(e.xclient.window, action == 1 || (action == 2 && !wants_fullscreen(e.xclient.window)));
        }
    }
}

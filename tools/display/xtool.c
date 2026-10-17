/* xtool: what a person does at an X server, by XTest, and what is looked up on it.
 *   xtool click X Y [BUTTON [HOLD_MS]]    move the pointer to root coordinates X,Y, press and release (default button 1, held 100 ms)
 *   xtool move X Y
 *   xtool key NAME[+NAME...] [HOLD_MS]    "alt+Return", "F11", "ctrl+F11": modifiers down in order, the key tapped, released in reverse
 *   xtool find TITLE                      the window id (hex) of the first top-level window whose _NET_WM_NAME or WM_NAME is TITLE; exit 1 if none
 *   xtool geom WINID                      "x y w h fullscreen(0|1)" of the window in root coordinates
 *   xtool resize WINID W H                what a user dragging a corner does: ask for a new size (the window manager may clamp it)
 *   xtool moveto WINID X Y                ... and moving it
 * Compile: cc -o xtool xtool.c -lX11 -lXtst */
#include <X11/Xlib.h>
#include <X11/Xatom.h>
#include <X11/extensions/XTest.h>
#include <X11/keysym.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <unistd.h>

static Display *d;

static KeySym sym_of(const char *n)
{
    if (!strcasecmp(n, "alt")) return XK_Alt_L;
    if (!strcasecmp(n, "ctrl")) return XK_Control_L;
    if (!strcasecmp(n, "shift")) return XK_Shift_L;
    return XStringToKeysym(n);
}

static void key(KeySym s, int down)
{
    KeyCode kc = XKeysymToKeycode(d, s);

    if (kc)
        XTestFakeKeyEvent(d, kc, down, 0);
    XFlush(d);
    usleep(30000);
}

static int has_title(Window w, const char *title)
{
    Atom net = XInternAtom(d, "_NET_WM_NAME", False), utf8 = XInternAtom(d, "UTF8_STRING", False), type;
    int fmt, ok = 0;
    unsigned long n, after;
    unsigned char *data = NULL;
    char *name = NULL;

    if (XGetWindowProperty(d, w, net, 0, 64, False, utf8, &type, &fmt, &n, &after, &data) == Success && data) {
        ok = !strcmp((char *)data, title);
        XFree(data);
    }
    if (!ok && XFetchName(d, w, &name) && name) {
        ok = !strcmp(name, title);
        XFree(name);
    }
    return ok;
}

static Window find(Window w, const char *title, int depth)
{
    Window rr, pp, *kids = NULL, f = 0;
    unsigned int n, i;

    if (has_title(w, title))
        return w;
    if (depth > 2 || !XQueryTree(d, w, &rr, &pp, &kids, &n))
        return 0;
    for (i = 0; i < n && !f; i++)
        f = find(kids[i], title, depth + 1);
    if (kids)
        XFree(kids);
    return f;
}

int main(int argc, char **argv)
{
    const char *cmd = argc > 1 ? argv[1] : "";

    d = XOpenDisplay(NULL);
    if (!d) {
        fprintf(stderr, "xtool: no display\n");
        return 2;
    }
    if (!strcmp(cmd, "click") || !strcmp(cmd, "move")) {
        int x = atoi(argv[2]), y = atoi(argv[3]), btn = argc > 4 ? atoi(argv[4]) : 1, hold = argc > 5 ? atoi(argv[5]) : 100;

        XTestFakeMotionEvent(d, -1, x, y, 0);
        XFlush(d);
        usleep(150000);
        if (!strcmp(cmd, "click")) {
            XTestFakeButtonEvent(d, (unsigned)btn, True, 0);
            XFlush(d);
            usleep((unsigned)hold * 1000);
            XTestFakeButtonEvent(d, (unsigned)btn, False, 0);
            XFlush(d);
            usleep(100000);
        }
    } else if (!strcmp(cmd, "key")) {
        char buf[128], *tok, *save;
        KeySym s[8];
        int n = 0, i, hold = argc > 3 ? atoi(argv[3]) : 80;

        snprintf(buf, sizeof(buf), "%s", argv[2]);
        for (tok = strtok_r(buf, "+", &save); tok && n < 8; tok = strtok_r(NULL, "+", &save))
            s[n++] = sym_of(tok);
        for (i = 0; i < n - 1; i++)
            key(s[i], True);
        key(s[n - 1], True);
        usleep((unsigned)hold * 1000);
        key(s[n - 1], False);
        for (i = n - 2; i >= 0; i--)
            key(s[i], False);
        usleep(100000);
    } else if (!strcmp(cmd, "find")) {
        Window w = find(DefaultRootWindow(d), argv[2], 0);

        if (!w)
            return 1;
        printf("0x%lx\n", w);
    } else if (!strcmp(cmd, "geom")) {
        Window w = strtoul(argv[2], NULL, 16), child;
        XWindowAttributes a;
        int x, y, fs = 0;
        Atom st = XInternAtom(d, "_NET_WM_STATE", False), fsa = XInternAtom(d, "_NET_WM_STATE_FULLSCREEN", False), type;
        int fmt;
        unsigned long n, after, i;
        unsigned char *data = NULL;

        if (!XGetWindowAttributes(d, w, &a))
            return 1;
        XTranslateCoordinates(d, w, DefaultRootWindow(d), 0, 0, &x, &y, &child);
        if (XGetWindowProperty(d, w, st, 0, 32, False, XA_ATOM, &type, &fmt, &n, &after, &data) == Success && data) {
            for (i = 0; i < n; i++)
                fs |= ((Atom *)data)[i] == fsa;
            XFree(data);
        }
        printf("%d %d %d %d %d\n", x, y, a.width, a.height, fs);
    } else if (!strcmp(cmd, "resize")) {
        Window w = strtoul(argv[2], NULL, 16);

        XResizeWindow(d, w, (unsigned)atoi(argv[3]), (unsigned)atoi(argv[4]));
        XFlush(d);
        usleep(300000);
    } else if (!strcmp(cmd, "moveto")) {
        Window w = strtoul(argv[2], NULL, 16);

        XMoveWindow(d, w, atoi(argv[3]), atoi(argv[4]));
        XFlush(d);
        usleep(300000);
    } else {
        fprintf(stderr, "xtool: unknown command\n");
        return 2;
    }
    XCloseDisplay(d);
    return 0;
}

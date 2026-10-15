"""USER32: window classes, windows, messages and the message pump, timers, dialogs and menus (minimal)."""
import struct
import time as _time

from .crt import va
from .cformat import format_c
from .gdi import (brush_pixels, put_region, Surface, SCREEN_W, SCREEN_H, Bitmap, DC, dc_of, fill_rect, get_stock, new_dc, new_obj, obj,
                  colorref, text_size, draw_text, _st as gdi_st)
from .machine import Block, Cont, api, u32
from . import kernel32
from .dialogs import parse_dialog

u = lambda name, argc: api("user32.dll", name, argc)
S32 = lambda v: v - 0x100000000 if v & 0x80000000 else v

WM_NULL, WM_CREATE, WM_DESTROY, WM_MOVE, WM_SIZE, WM_ACTIVATE, WM_SETFOCUS, WM_KILLFOCUS = 0, 1, 2, 3, 5, 6, 7, 8
WM_PAINT, WM_CLOSE, WM_QUIT, WM_ERASEBKGND, WM_SHOWWINDOW, WM_ACTIVATEAPP, WM_SETCURSOR = 0xF, 0x10, 0x12, 0x14, 0x18, 0x1C, 0x20
WM_GETMINMAXINFO, WM_NCCREATE, WM_NCDESTROY, WM_NCCALCSIZE, WM_NCACTIVATE, WM_NCHITTEST = 0x24, 0x81, 0x82, 0x83, 0x86, 0x84
WM_INITDIALOG, WM_COMMAND, WM_TIMER = 0x110, 0x111, 0x113
WM_WINDOWPOSCHANGING, WM_WINDOWPOSCHANGED = 0x46, 0x47
WS_CHILD, WS_VISIBLE, WS_POPUP, WS_CAPTION = 0x40000000, 0x10000000, 0x80000000, 0x00C00000


def _st(m):
    st = m.state.setdefault("u32", {})
    if not st:
        st.update(classes={}, windows={}, next_hwnd=0x10010, queue=[], quit=None, timers={}, focus=0, active=0,
                  capture=0, cursor=(320, 240), dirty=False, keys={}, depth=0,
                  menus={}, next_menu=0x9001, dialogs=[])
    return st


def window(m, h):
    return _st(m)["windows"].get(h)


def mark_dirty(m):
    _st(m)["dirty"] = True


# ---- classes -------------------------------------------------------------------------------------------------
@u("RegisterClassA", 1)
def register_class(m, a):
    style, proc, cbcls, cbwnd, hinst, icon, cursor, bg, menu, name = struct.unpack("<10I", m.rd(a[0], 40))
    key = m.cstr(name).decode("latin-1").lower() if name > 0xFFFF else f"#{name}"
    st = _st(m)
    st["classes"][key] = dict(style=style, proc=proc, cbwnd=cbwnd, hinst=hinst, cursor=cursor, bg=bg,
                              name=key, extra=cbcls)
    return 0xC000 + len(st["classes"])


@u("SetClassLongA", 3)
def set_class_long(m, a):
    return 0


# ---- window creation ----------------------------------------------------------------------------------------
class ExtraBytes:
    """A window's cbWndExtra bytes: addressed by byte offset, read and written as a byte, word or long, so the words and
    longs a window class keeps (HorzList: a count word, an item pointer long, scroll words) do not overlap each other."""

    def __init__(self, size=0):
        self.b = bytearray(max(size, 0))

    def get(self, off, default=0, size=4):
        if off < 0 or off + size > len(self.b):
            return default
        return int.from_bytes(self.b[off:off + size], "little")

    def __setitem__(self, off, val):
        self.put(off, val, 4)

    def put(self, off, val, size=4):
        if off < 0:
            return
        if off + size > len(self.b):
            self.b.extend(bytes(off + size - len(self.b)))
        self.b[off:off + size] = (val & ((1 << (8 * size)) - 1)).to_bytes(size, "little")


def new_window(m, cls, parent, style, exstyle, x, y, w, h, title, menu, param):
    st = _st(m)
    hwnd = st["next_hwnd"]
    st["next_hwnd"] += 4
    c = st["classes"].get(cls.lower() if isinstance(cls, str) else cls)
    win = dict(hwnd=hwnd, cls=cls, proc=c["proc"] if c else 0, parent=parent, style=style, exstyle=exstyle,
               x=x, y=y, w=w, h=h, title=title, visible=False, enabled=True, id=menu if style & WS_CHILD else 0,
               long={}, extra=ExtraBytes(c["cbwnd"] if c else 0), invalid=True, surface=None, children=[], param=param, userdata=0,
               builtin=c is None, hinst=c["hinst"] if c else 0, tid=m.cur.tid if m.cur else 1)
    win["ownerdraw"] = c is None and str(cls).upper() == "BUTTON" and (style & 0xF) == 0xB      # BS_OWNERDRAW: the parent paints it (WM_DRAWITEM)
    st["zcount"] = st.get("zcount", 0) + 1
    win["z"] = float(st["zcount"])                      # stacking order among siblings: a higher z is above (see set_z)
    st["windows"][hwnd] = win
    if parent and parent in st["windows"]:
        st["windows"][parent]["children"].append(hwnd)
    _resize_surface(win)
    return win


def _resize_surface(win):
    cw, ch = client_size(win)
    if win["surface"] is None or (win["surface"].w, win["surface"].h) != (cw, ch):
        win["surface"] = Surface(max(cw, 1), max(ch, 1))


def client_size(win):
    """Client area size. Windows created with a caption/frame lose the frame; kept simple: 0 frame."""
    return max(win["w"], 0), max(win["h"], 0)


def _owner_alive(m, tid):
    return any(t.tid == tid and t.state != "done" for t in m.threads)


def siblings(m, win):
    """The windows with the same parent as `win` (itself included), bottom to top."""
    st = _st(m)
    return sorted((w for w in st["windows"].values() if w["parent"] == win["parent"]), key=lambda w: w["z"])


def set_z(m, win, after):
    """Restack `win` among its siblings. `after`: 0 / -1 (HWND_TOP, HWND_TOPMOST) to the top, 1 (HWND_BOTTOM) to the bottom, -2
    (HWND_NOTOPMOST) to the top, or a sibling's handle: directly below that window (the game's SetWindowPos(hwnd, other, ...))."""
    st = _st(m)
    others = [w for w in siblings(m, win) if w is not win]
    if after in (0, 0xFFFFFFFF, 0xFFFFFFFE) or not others:
        win["z"] = (others[-1]["z"] + 1.0) if others else win["z"]
    elif after == 1:
        win["z"] = others[0]["z"] - 1.0
    else:
        ref = st["windows"].get(after)
        if ref is None or ref["parent"] != win["parent"] or ref is win:
            return
        idx = others.index(ref)
        below = others[idx - 1]["z"] if idx > 0 else ref["z"] - 2.0
        win["z"] = (below + ref["z"]) / 2.0
    if len(others) > 1 and min(abs(a["z"] - b["z"]) for a, b in zip(others, others[1:] + [win])) < 1e-6:
        for i, w in enumerate(siblings(m, win)):      # the gaps have worn thin: number the siblings again
            w["z"] = float(i)


def send(m, hwnd, msg, wp, lp):
    """Generator: SendMessage. Delivered synchronously; a window created by another thread has its procedure run
    *on that thread* (the sender sleeps until the owner next pumps messages), as Windows does."""
    win = window(m, hwnd)
    if win is None:
        return 0
    owner = win.get("tid")
    if owner is not None and owner != m.cur.tid and _owner_alive(m, owner):
        rec = {"hwnd": hwnd, "msg": msg, "wp": wp, "lp": lp, "done": False, "result": 0, "tid": owner}
        _st(m).setdefault("sent", []).append(rec)
        yield Block(ready=lambda: rec["done"])
        return rec["result"]
    r = yield from send_local(m, hwnd, msg, wp, lp)
    return r


def process_sent(m):
    """Generator: run messages other threads sent to windows this thread owns."""
    q = _st(m).get("sent", [])
    while True:
        rec = next((r for r in q if r["tid"] == m.cur.tid and not r["done"] and not r.get("running")), None)
        if rec is None:
            return
        rec["running"] = True                                  # nested pumps inside its handler must not re-run it
        if m.state.get("gdi_debug"):
            m.log(f"   [sent] t{m.cur.tid} runs 0x{rec['hwnd']:x} msg=0x{rec['msg']:x} wp=0x{rec['wp']:x} lp=0x{rec['lp']:x} "
                  f"depth={len(m.cur.conts)} vt={m.vt:.3f} sender_state={[t.state for t in m.threads]}")
        rec["result"] = yield from send_local(m, rec["hwnd"], rec["msg"], rec["wp"], rec["lp"])
        rec["done"] = True
        q.remove(rec)


def send_local(m, hwnd, msg, wp, lp):
    win = window(m, hwnd)
    if win is None:
        return 0
    if win.get("dlgproc"):                                    # dialog procedures return BOOL: nonzero = handled
        r = yield Cont(win["dlgproc"], [hwnd, msg, wp, lp])
        if r:
            return win.get("msgresult", 1) if msg != WM_INITDIALOG else 1
        if msg == WM_PAINT:                                   # the dialog's own default: begin the paint, so WM_ERASEBKGND reaches the procedure
            r = yield from default_window_proc(m, hwnd, msg, wp, lp)
            return r
        return default_proc(m, win, msg, wp, lp)
    if win["proc"]:
        r = yield Cont(win["proc"], [hwnd, msg, wp, lp])
        return r
    return default_proc(m, win, msg, wp, lp)


BM_GETCHECK, BM_SETCHECK, BM_CLICK = 0xF0, 0xF1, 0xF5
WM_SETTEXT, WM_GETTEXT, WM_GETTEXTLENGTH, WM_ENABLE = 0xC, 0xD, 0xE, 0xA


SYSTEM_COLORS = {1: (192, 192, 192), 2: (0, 0, 128), 3: (0, 128, 128), 4: (192, 192, 192), 5: (255, 255, 255),
                 6: (0, 0, 0), 7: (0, 0, 0), 8: (0, 0, 0), 9: (255, 255, 255), 10: (192, 192, 192),
                 11: (192, 192, 192), 12: (128, 128, 128), 13: (0, 0, 128), 14: (255, 255, 255),
                 15: (192, 192, 192)}


def erase_background(m, win):
    """Fill a window's client area with its class background brush (a solid, system colour or pattern)."""
    c = _st(m)["classes"].get(str(win["cls"]).lower())
    if m.state.get("gdi_debug"):
        m.log(f"   [erase] {win['cls']} 0x{win['hwnd']:x} bg={c['bg'] if c else None} brush={obj(m, c['bg']) if c else None}")
    if not c or not c["bg"]:
        return False
    bg = c["bg"]
    br = obj(m, bg)
    if isinstance(br, tuple) and br[0] == "brush":
        brush = br
    elif bg <= 32:                                               # COLOR_xxx + 1
        brush = ("brush", SYSTEM_COLORS.get(bg - 1, (255, 255, 255)))
    else:
        return False
    cw, ch = client_size(win)
    if cw <= 0 or ch <= 0:
        return False
    _, d = new_dc(m, "window", win["hwnd"])
    put_region(m, d, 0, 0, brush_pixels(m, brush, cw, ch))
    return True


def default_proc(m, win, msg, wp, lp):
    if msg == WM_ERASEBKGND:
        return 1 if erase_background(m, win) else 0
    if msg == WM_PAINT:                                          # DefWindowProc paints the background and validates
        erase_background(m, win)
        win["invalid"] = False
        return 0
    if msg == WM_NCCREATE:
        return 1
    if msg == WM_NCHITTEST:
        return 1
    if msg == WM_CLOSE:
        destroy(m, win["hwnd"])
        return 0
    cls = str(win.get("cls", "")).upper()
    if cls == "MCIWNDCLASS":                                   # a movie window (movie.py)
        from . import movie  # noqa: PLC0415
        return movie.message(m, win, msg, wp, lp)
    if cls in ("BUTTON", "STATIC", "EDIT", "COMBOBOX", "LISTBOX", "SCROLLBAR"):
        return control_message(m, win, cls, msg, wp, lp)
    if cls == "#32770":                                        # a dialog with no procedure result
        if msg == WM_CLOSE:
            win["ended"], win["result"] = True, 2
        return 0
    return 0


def _items(win):
    return win.setdefault("items", [])


def control_message(m, win, cls, msg, wp, lp):
    """The built-in behaviour of BUTTON, STATIC, EDIT, COMBOBOX and LISTBOX windows."""
    if msg == WM_SETTEXT:
        win["title"] = m.cstr(lp).decode("latin-1")
        return 1
    if msg == WM_GETTEXT:
        b = win["title"].encode("latin-1")[:max(wp - 1, 0)]
        m.put_cstr(lp, b)
        return len(b)
    if msg == WM_GETTEXTLENGTH:
        return len(win["title"])
    if msg == WM_ENABLE:
        win["enabled"] = bool(wp)
        return 0
    if cls == "BUTTON":
        if msg == BM_SETCHECK:
            win["checked"] = wp
            return 0
        if msg == BM_GETCHECK:
            return win.get("checked", 0)
        return 0
    if cls in ("COMBOBOX", "LISTBOX"):
        cb = cls == "COMBOBOX"
        items = _items(win)
        sorted_ = bool(win["style"] & (0x100 if cb else 0x2))                # CBS_SORT / LBS_SORT
        if msg == (0x143 if cb else 0x180):                                # ADDSTRING
            text = m.cstr(lp).decode("latin-1")
            i = len(items)
            if sorted_:
                i = next((k for k, it in enumerate(items) if it[0].lower() > text.lower()), len(items))
            items.insert(i, [text, 0])
            if win.get("sel", -1) >= i:
                win["sel"] = win["sel"] + 1
            return i
        if msg == (0x145 if cb else 0x18D):                                # DIR: list files matching a pattern
            import fnmatch
            import os
            from .paths import host_path, normalize
            spec = normalize(m.cwd, m.cstr(lp).decode("latin-1"))
            folder, pattern = spec.rsplit("\\", 1)
            hp, ok = host_path(m.game_root, m.overlay_root, m.cwd, folder)
            names = sorted(n.upper() for n in (os.listdir(hp) if ok and os.path.isdir(hp) else [])
                           if fnmatch.fnmatch(n.upper(), pattern.upper()) and os.path.isfile(os.path.join(hp, n)))
            for n in names:
                items.append([n, 0])
            if sorted_:
                items.sort(key=lambda it: it[0].lower())
            return len(items) - 1 if names else 0xFFFFFFFF
        if msg == (0x14A if cb else 0x181):                                # INSERTSTRING
            i = len(items) if S32(wp) < 0 else wp
            items.insert(i, [m.cstr(lp).decode("latin-1"), 0])
            return i
        if msg == (0x144 if cb else 0x182):                                # DELETESTRING
            if wp < len(items):
                items.pop(wp)
            return len(items)
        if msg == (0x14B if cb else 0x184):                                # RESETCONTENT
            items.clear()
            win["sel"] = -1
            return 0
        if msg == (0x146 if cb else 0x18B):                                # GETCOUNT
            return len(items)
        if msg == (0x14E if cb else 0x186):                                # SETCURSEL
            win["sel"] = S32(wp) if S32(wp) < len(items) else -1
            return u32(win["sel"]) if win["sel"] >= 0 else 0xFFFFFFFF
        if msg == (0x147 if cb else 0x188):                                # GETCURSEL
            return u32(win.get("sel", -1))
        if msg == (0x148 if cb else 0x189):                                # GETLBTEXT / GETTEXT
            if wp < len(items):
                b = items[wp][0].encode("latin-1")
                m.put_cstr(lp, b)
                return len(b)
            return 0xFFFFFFFF
        if msg == (0x149 if cb else 0x18A):                                # GETLBTEXTLEN
            return len(items[wp][0]) if wp < len(items) else 0xFFFFFFFF
        if msg == (0x150 if cb else 0x199):                                # GETITEMDATA
            return items[wp][1] if wp < len(items) else 0xFFFFFFFF
        if msg == (0x151 if cb else 0x19A):                                # SETITEMDATA
            if wp < len(items):
                items[wp][1] = lp
                return 1
            return 0xFFFFFFFF
        if msg in ((0x14C, 0x14D) if cb else (0x18F, 0x18C)):              # FINDSTRING / SELECTSTRING
            want = m.cstr(lp).decode("latin-1").lower()
            for i, it in enumerate(items):
                if it[0].lower().startswith(want):
                    if msg in (0x14D, 0x18C):
                        win["sel"] = i
                    return i
            return 0xFFFFFFFF
        return 0
    return 0


def default_window_proc(m, hwnd, msg, wp, lp):
    """Generator: DefWindowProc. WM_PAINT begins a paint, which sends WM_ERASEBKGND to the window's own
    procedure (games draw their backgrounds there); a zero result falls back to the class brush."""
    win = window(m, hwnd)
    if not win:
        return 0
    if msg == WM_PAINT:
        win["invalid"] = False
        if win.get("erase", True):
            win["erase"] = False
            h, _ = new_dc(m, "window", hwnd)
            r = yield from send(m, hwnd, WM_ERASEBKGND, h, 0)
            if not r:
                erase_background(m, win)
        return 0
    return default_proc(m, win, msg, wp, lp)


@u("DefWindowProcA", 4)
def def_window_proc(m, a):
    r = yield from default_window_proc(m, a[0], a[1], a[2], a[3])
    return r


@u("CallWindowProcA", 5)
def call_window_proc(m, a):
    if a[0] in m.stubs:
        r = yield from default_window_proc(m, a[1], a[2], a[3], a[4])
        return r
    return Cont(a[0], [a[1], a[2], a[3], a[4]])


@u("CreateWindowExA", 12)
def create_window_ex(m, a):
    exstyle, cls, title, style, x, y, w, h, parent, menu, hinst, param = a
    cname = m.cstr(cls).decode("latin-1") if cls > 0xFFFF else f"#{cls}"
    ttl = m.cstr(title).decode("latin-1") if title > 0xFFFF else ""
    x, y, w, h = map(S32, (x, y, w, h))
    if x == S32(0x80000000):
        x = 0
    if y == S32(0x80000000):
        y = 0
    win = new_window(m, cname, parent, style, exstyle, x, y, w if w != S32(0x80000000) else 640,
                     h if h != S32(0x80000000) else 480, ttl, menu, param)
    hwnd = win["hwnd"]
    m.log(f"   CreateWindowEx(class={cname!r}, title={ttl!r}, style=0x{style:08x}, {w}x{h} at {x},{y}) -> hwnd 0x{hwnd:x}"
          + ("" if win["proc"] else "  [builtin control]"))
    if not win["proc"]:
        win["visible"] = bool(style & WS_VISIBLE)                  # a built-in control created with WS_VISIBLE is shown from the start
        win["invalid"] = True
        mark_dirty(m)
        return hwnd
    cs = m.alloc(48)
    m.wr(cs, struct.pack("<12I", param, hinst, menu, parent, u32(h), u32(w), u32(y), u32(x), style, title, cls, exstyle))
    r = yield from send(m, hwnd, WM_NCCREATE, 0, cs)
    if not r:
        destroy(m, hwnd)
        return 0
    rect = m.alloc(16)
    m.wr(rect, struct.pack("<4i", x, y, x + win["w"], y + win["h"]))
    yield from send(m, hwnd, WM_NCCALCSIZE, 0, rect)
    r = yield from send(m, hwnd, WM_CREATE, 0, cs)
    if S32(r) == -1:
        destroy(m, hwnd)
        return 0
    if style & WS_CHILD:
        # CreateWindow ends by positioning the window, which DefWindowProc turns into WM_SIZE and WM_MOVE, visible or not. (Top-level windows
        # get theirs in show(), where this emulator has always sent them.) A child that lays out its controls in WM_SIZE needs it.
        cw, ch = client_size(win)
        yield from send(m, hwnd, WM_SIZE, 0, (cw & 0xFFFF) | (ch << 16))
        yield from send(m, hwnd, WM_MOVE, 0, (win["x"] & 0xFFFF) | ((win["y"] & 0xFFFF) << 16))
    if style & WS_VISIBLE:
        yield from show(m, hwnd, 1)
    return hwnd


def destroy(m, hwnd):
    st = _st(m)
    win = st["windows"].pop(hwnd, None)
    if win:
        if win.get("movie"):
            from . import movie  # noqa: PLC0415
            movie.release(m, win)
        for c in list(win["children"]):
            destroy(m, c)
    return 1


@u("DestroyWindow", 1)
def destroy_window(m, a):
    win = window(m, a[0])
    if not win:
        return 0
    if win["proc"]:
        yield Cont(win["proc"], [a[0], WM_DESTROY, 0, 0])
    destroy(m, a[0])
    return 1


def show(m, hwnd, cmd):
    win = window(m, hwnd)
    if win is None:
        return 0
    was = win["visible"]
    win["visible"] = cmd != 0
    if cmd and not was:
        _st(m)["dirty"] = True
        win["invalid"] = True
        yield from send(m, hwnd, WM_SHOWWINDOW, 1, 0)
        if not win["style"] & WS_CHILD:
            st = _st(m)
            st["active"] = st["focus"] = hwnd
            yield from send(m, hwnd, WM_ACTIVATEAPP, 1, 1)
            yield from send(m, hwnd, WM_ACTIVATE, 1, 0)
            yield from send(m, hwnd, WM_SETFOCUS, 0, 0)
            cw, ch = client_size(win)
            yield from send(m, hwnd, WM_SIZE, 0, (cw & 0xFFFF) | (ch << 16))
            yield from send(m, hwnd, WM_MOVE, 0, (win["x"] & 0xFFFF) | (win["y"] << 16))
    return int(was)


@u("ShowWindow", 2)
def show_window(m, a):
    r = yield from show(m, a[0], a[1])
    return r


@u("UpdateWindow", 1)
def update_window(m, a):
    win = window(m, a[0])
    if win and win["invalid"] and win["visible"]:
        yield from send(m, a[0], WM_PAINT, 0, 0)
    return 1


@u("InvalidateRect", 3)
def invalidate_rect(m, a):
    win = window(m, a[0])
    if win:
        win["invalid"] = True
        if a[2]:
            win["erase"] = True
        _st(m)["dirty"] = True
    return 1


@u("ScrollWindow", 5)
def scroll_window(m, a):
    return 1


# ---- window geometry ---------------------------------------------------------------------------------------
def _put_rect(m, p, l, t, r, b):
    m.wr(p, struct.pack("<4i", l, t, r, b))


@u("GetClientRect", 2)
def get_client_rect(m, a):
    win = window(m, a[0])
    if not win:
        return 0
    cw, ch = client_size(win)
    _put_rect(m, a[1], 0, 0, cw, ch)
    return 1


@u("GetWindowRect", 2)
def get_window_rect(m, a):
    win = window(m, a[0])
    if not win:
        return 0
    x0, y0, x1, y1 = abs_rect(m, win)                       # screen coordinates, as the real API gives
    _put_rect(m, a[1], x0, y0, x1, y1)
    return 1


def _geometry_changed(m, win, old):
    """MoveWindow / SetWindowPos end with WM_SIZE for a changed size and WM_MOVE for a changed position, as Windows sends them.
    (The deck editor fills its card surface in the WM_SIZE of the surface.)"""
    if not win["proc"]:
        return
    hwnd = win["hwnd"]
    if (win["w"], win["h"]) != old[2:]:
        cw, ch = client_size(win)
        yield from send(m, hwnd, WM_SIZE, 0, (cw & 0xFFFF) | ((ch & 0xFFFF) << 16))
    if (win["x"], win["y"]) != old[:2]:
        yield from send(m, hwnd, WM_MOVE, 0, (win["x"] & 0xFFFF) | ((win["y"] & 0xFFFF) << 16))


@u("MoveWindow", 6)
def move_window(m, a):
    win = window(m, a[0])
    if win:
        old = (win["x"], win["y"], win["w"], win["h"])
        win["x"], win["y"], win["w"], win["h"] = S32(a[1]), S32(a[2]), S32(a[3]), S32(a[4])
        _resize_surface(win)
        win["invalid"] = True
        mark_dirty(m)
        yield from _geometry_changed(m, win, old)
    return 1


@u("SetWindowPos", 7)
def set_window_pos(m, a):
    win = window(m, a[0])
    hwnd, after, x, y, cx, cy, flags = a
    if win:
        old = (win["x"], win["y"], win["w"], win["h"])
        if not flags & 2:
            win["x"], win["y"] = S32(x), S32(y)
        if not flags & 1:
            win["w"], win["h"] = S32(cx), S32(cy)
            _resize_surface(win)
        if flags & 0x40:
            yield from show(m, hwnd, 1)
        elif flags & 0x80:
            yield from show(m, hwnd, 0)
        if not flags & 4:                                   # SWP_NOZORDER
            set_z(m, win, after)
        win["invalid"] = True
        mark_dirty(m)
        yield from _geometry_changed(m, win, old)
    return 1


@u("AdjustWindowRect", 3)
def adjust_window_rect(m, a):
    return 1


def _origin(m, hwnd):
    """Screen position of a window's client area (windows have no frame here); (0, 0) for NULL, the screen."""
    win = window(m, hwnd) if hwnd else None
    if win is None:
        return 0, 0
    x0, y0, _, _ = abs_rect(m, win)
    return x0, y0


def _shift_points(m, ptr, n, dx, dy):
    for i in range(n):
        x, y = struct.unpack("<ii", m.rd(ptr + 8 * i, 8))
        m.wr(ptr + 8 * i, struct.pack("<ii", x + dx, y + dy))


@u("ClientToScreen", 2)
def client_to_screen(m, a):
    ox, oy = _origin(m, a[0])
    _shift_points(m, a[1], 1, ox, oy)
    return 1


@u("ScreenToClient", 2)
def screen_to_client(m, a):
    ox, oy = _origin(m, a[0])
    _shift_points(m, a[1], 1, -ox, -oy)
    return 1


@u("MapWindowPoints", 4)
def map_window_points(m, a):
    """Points (or a RECT, n = 2) from one window's client coordinates to another's; NULL is the screen."""
    fx, fy = _origin(m, a[0])
    tx, ty = _origin(m, a[1])
    _shift_points(m, a[2], a[3], fx - tx, fy - ty)
    return ((fx - tx) & 0xFFFF) | (((fy - ty) & 0xFFFF) << 16)


@u("GetSystemMetrics", 1)
def get_system_metrics(m, a):
    return {0: SCREEN_W, 1: SCREEN_H, 4: 19, 5: 1, 6: 1, 7: 3, 8: 3, 15: 19, 32: 4, 33: 4, 3: 16, 2: 16, 28: 4, 29: 4,
            16: SCREEN_W, 17: SCREEN_H - 40, 75: 0}.get(a[0], 0)


# ---- rectangles (pure functions) -----------------------------------------------------------------------------
u("SetRect", 5)(lambda m, a: (_put_rect(m, a[0], *map(S32, a[1:5])), 1)[1])
u("CopyRect", 2)(lambda m, a: (m.wr(a[0], m.rd(a[1], 16)), 1)[1])


@u("OffsetRect", 3)
def offset_rect(m, a):
    l, t, r, b = struct.unpack("<4i", m.rd(a[0], 16))
    dx, dy = S32(a[1]), S32(a[2])
    _put_rect(m, a[0], l + dx, t + dy, r + dx, b + dy)
    return 1


@u("InflateRect", 3)
def inflate_rect(m, a):
    l, t, r, b = struct.unpack("<4i", m.rd(a[0], 16))
    dx, dy = S32(a[1]), S32(a[2])
    _put_rect(m, a[0], l - dx, t - dy, r + dx, b + dy)
    return 1


@u("IsRectEmpty", 1)
def is_rect_empty(m, a):
    l, t, r, b = struct.unpack("<4i", m.rd(a[0], 16))
    return int(r <= l or b <= t)


@u("PtInRect", 3)
def pt_in_rect(m, a):
    l, t, r, b = struct.unpack("<4i", m.rd(a[0], 16))
    x, y = S32(a[1]), S32(a[2])
    return int(l <= x < r and t <= y < b)


@u("UnionRect", 3)
def union_rect(m, a):
    r1, r2 = struct.unpack("<4i", m.rd(a[1], 16)), struct.unpack("<4i", m.rd(a[2], 16))
    _put_rect(m, a[0], min(r1[0], r2[0]), min(r1[1], r2[1]), max(r1[2], r2[2]), max(r1[3], r2[3]))
    return 1


# ---- window state ------------------------------------------------------------------------------------------
GWL = {-4: "proc", -16: "style", -20: "exstyle", -21: "userdata", -12: "id", -6: "hinst", -8: "parent"}


@u("GetWindowLongA", 2)
def get_window_long(m, a):
    win = window(m, a[0])
    if not win:
        return 0
    idx = S32(a[1])
    if idx in GWL:
        return u32(win[GWL[idx]])
    return win["extra"].get(idx, 0)


@u("GetWindowWord", 2)
def get_window_word(m, a):
    win = window(m, a[0])
    return win["extra"].get(S32(a[1]), 0, 2) if win else 0


@u("SetWindowWord", 3)
def set_window_word(m, a):
    win = window(m, a[0])
    if not win:
        return 0
    old = win["extra"].get(S32(a[1]), 0, 2)
    win["extra"].put(S32(a[1]), a[2], 2)
    return old


@u("SetWindowLongA", 3)
def set_window_long(m, a):
    win = window(m, a[0])
    if not win:
        return 0
    idx = S32(a[1])
    if idx in GWL:
        old = win[GWL[idx]]
        win[GWL[idx]] = a[2]
        if idx == -4:
            win["builtin"] = False
        return u32(old)
    old = win["extra"].get(idx, 0)
    win["extra"].put(idx, a[2], 4)
    return old


u("GetParent", 1)(lambda m, a: (window(m, a[0]) or {}).get("parent", 0))
def _children_top_down(m, hwnd):
    st = _st(m)
    kids = [w for w in st["windows"].values() if w["parent"] == hwnd and w["hwnd"] != hwnd]
    return sorted(kids, key=lambda w: -w["z"])


@u("GetTopWindow", 1)
def get_top_window(m, a):
    kids = _children_top_down(m, a[0])
    return kids[0]["hwnd"] if kids else 0


@u("GetWindow", 2)
def get_window(m, a):
    """GW_HWNDFIRST 0 / LAST 1 / NEXT 2 / PREV 3 walk the siblings in stacking order (NEXT goes down, PREV up); GW_OWNER 4; GW_CHILD 5."""
    win = window(m, a[0])
    if not win:
        return 0
    cmd = a[1]
    if cmd == 5:
        kids = _children_top_down(m, a[0])
        return kids[0]["hwnd"] if kids else 0
    if cmd == 4:
        return 0
    order = _children_top_down(m, win["parent"])
    if cmd == 0:
        return order[0]["hwnd"]
    if cmd == 1:
        return order[-1]["hwnd"]
    i = order.index(win)
    j = i + 1 if cmd == 2 else i - 1
    return order[j]["hwnd"] if 0 <= j < len(order) else 0


u("GetDlgCtrlID", 1)(lambda m, a: (window(m, a[0]) or {}).get("id", 0))
u("IsWindowVisible", 1)(lambda m, a: int(bool((window(m, a[0]) or {}).get("visible"))))
u("IsIconic", 1)(lambda m, a: 0)
u("EnableWindow", 2)(lambda m, a: 0)
u("SetWindowRgn", 3)(lambda m, a: 1)
u("LockWindowUpdate", 1)(lambda m, a: 1)
@u("BringWindowToTop", 1)
def bring_window_to_top(m, a):
    win = window(m, a[0])
    if win:
        set_z(m, win, 0)
        mark_dirty(m)
    return 1

u("SetForegroundWindow", 1)(lambda m, a: 1)
u("GetWindowThreadProcessId", 2)(lambda m, a: (m.w32(a[1], 1) if a[1] else None, 1)[1])
u("EnumChildWindows", 3)(lambda m, a: 0)
u("GetClassNameA", 3)(lambda m, a: len((window(m, a[0]) or {"cls": ""})["cls"]))
u("WinHelpA", 4)(lambda m, a: 1)
u("MessageBeep", 1)(lambda m, a: 1)


@u("FindWindowA", 2)
def find_window(m, a):
    return 0


@u("FindWindowExA", 4)
def find_window_ex(m, a):
    return 0


@u("SetFocus", 1)
def set_focus(m, a):
    st = _st(m)
    old, st["focus"] = st["focus"], a[0]
    return old


u("GetFocus", 0)(lambda m, a: _st(m)["focus"])
u("SetActiveWindow", 1)(lambda m, a: _st(m).__setitem__("active", a[0]) or 0)
u("SetCapture", 1)(lambda m, a: (_st(m).__setitem__("capture", a[0]), 0)[1])
u("GetCapture", 0)(lambda m, a: _st(m)["capture"])
u("ReleaseCapture", 0)(lambda m, a: (_st(m).__setitem__("capture", 0), 1)[1])


@u("SetWindowTextA", 2)
def set_window_text(m, a):
    win = window(m, a[0])
    if win:
        win["title"] = m.cstr(a[1]).decode("latin-1")
    return 1


@u("GetWindowTextA", 3)
def get_window_text(m, a):
    win = window(m, a[0])
    b = (win["title"] if win else "").encode("latin-1")[:max(a[2] - 1, 0)]
    m.put_cstr(a[1], b)
    return len(b)


# ---- cursor, keyboard state ----------------------------------------------------------------------------------
u("ShowCursor", 1)(lambda m, a: 0)
u("SetCursor", 1)(lambda m, a: 0)
u("LoadCursorA", 2)(lambda m, a: new_obj(m, ("cursor", a[1])))
u("LoadIconA", 2)(lambda m, a: new_obj(m, ("icon", a[1])))
u("DestroyIcon", 1)(lambda m, a: 1)
u("DestroyCursor", 1)(lambda m, a: 1)
u("LoadAcceleratorsA", 2)(lambda m, a: new_obj(m, ("accel", a[1])))
u("TranslateAcceleratorA", 3)(lambda m, a: 0)
u("GetDoubleClickTime", 0)(lambda m, a: 500)


@u("GetCursorPos", 1)
def get_cursor_pos(m, a):
    x, y = _st(m)["cursor"]
    m.w32(a[0], x)
    m.w32(a[0] + 4, y)
    return 1


@u("SetCursorPos", 2)
def set_cursor_pos(m, a):
    _st(m)["cursor"] = (S32(a[0]), S32(a[1]))
    return 1


u("WindowFromPoint", 2)(lambda m, a: next((h for h, w in reversed(list(_st(m)["windows"].items()))
                                            if w["visible"] and not w["style"] & WS_CHILD), 0))
u("GetKeyState", 1)(lambda m, a: 0x8000 if _st(m)["keys"].get(a[0]) else 0)
u("GetAsyncKeyState", 1)(lambda m, a: 0x8000 if _st(m)["keys"].get(a[0]) else 0)


# ---- messages ------------------------------------------------------------------------------------------------
@u("SendMessageA", 4)
def send_message(m, a):
    r = yield from send(m, a[0], a[1], a[2], a[3])
    return r


@u("SendDlgItemMessageA", 5)
def send_dlg_item_message(m, a):
    return 0


@u("PostMessageA", 4)
def post_message(m, a):
    if m.state.get("gdi_debug"):
        try:
            extra = m.rd(a[3], 24).hex() if a[3] > 0x1000 else ""
        except Exception:
            extra = ""
        m.log(f"   [post] t{m.cur.tid} 0x{a[0]:x} msg=0x{a[1]:x} wp=0x{a[2]:x} lp=0x{a[3]:x} {extra}")
    _st(m)["queue"].append((a[0], a[1], a[2], a[3]))
    return 1


@u("PostQuitMessage", 1)
def post_quit(m, a):
    m.cur.quit = a[0]                                    # WM_QUIT belongs to the calling thread's queue (the deck editor's thread must not end the game)
    return 0


u("GetMessageTime", 0)(lambda m, a: kernel32.now_ms(m))
u("TranslateMessage", 1)(lambda m, a: 0)


@u("DispatchMessageA", 1)
def dispatch_message(m, a):
    hwnd, msg, wp, lp = struct.unpack("<4I", m.rd(a[0], 16))
    if m.state.get("gdi_debug") and msg not in (WM_PAINT, WM_TIMER, WM_MOUSEMOVE):
        w = window(m, hwnd)
        m.log(f"   [dispatch] t{m.cur.tid} 0x{hwnd:x} {w['cls'] if w else None} msg=0x{msg:x} wp=0x{wp:x} lp=0x{lp:x}")
    if msg == WM_TIMER and lp:
        yield Cont(lp, [hwnd, WM_TIMER, wp, kernel32.now_ms(m)])
        return 0
    r = yield from send(m, hwnd, msg, wp, lp)
    return r


def _owned(m, hwnd):
    """True if the message's window belongs to the calling thread (windows with no owner go to anyone)."""
    w = window(m, hwnd)
    return w is None or w.get("tid") == m.cur.tid


def _next_message(m, remove, hwnd_filter=0):
    """A pending message for the calling thread, or None. Synthesizes WM_PAINT for invalid visible windows and
    WM_TIMER for due timers. Queues are per thread, as in Windows: a window's messages go to the thread that
    created it."""
    st = _st(m)
    for i, msg in enumerate(st["queue"]):
        if (not hwnd_filter or msg[0] == hwnd_filter) and _owned(m, msg[0]):
            if remove:
                st["queue"].pop(i)
            return msg
    t = kernel32.now_ms(m)
    for (hwnd, tid), tm in list(st["timers"].items()):
        if tm["next"] <= t and (hwnd == 0 or (hwnd in st["windows"] and _owned(m, hwnd))):
            tm["next"] = t + max(tm["delay"], 1)
            return (hwnd, WM_TIMER, tid, tm["proc"])
    for hwnd, win in st["windows"].items():
        if win["invalid"] and win["visible"] and (win["proc"] or win.get("dlgproc")) and win.get("tid") == m.cur.tid:
            if remove:
                win["invalid"] = False
            return (hwnd, WM_PAINT, 0, 0)
    for hwnd, win in st["windows"].items():                         # owner-draw buttons: the parent is asked to paint them
        if win.get("ownerdraw") and win["invalid"] and win["visible"] and win["w"] > 0 and win["h"] > 0 and win.get("tid") == m.cur.tid \
                and win["parent"] in st["windows"] and st["windows"][win["parent"]]["visible"]:
            if remove:
                win["invalid"] = False
                return (win["parent"], WM_DRAWITEM, win["id"], _drawitem_struct(m, win))
            return (win["parent"], WM_DRAWITEM, win["id"], 0)
    return None


WM_DRAWITEM = 0x2B


def _drawitem_struct(m, win):
    """A DRAWITEMSTRUCT for an owner-draw button, with a DC that draws on the button's own surface."""
    from .gdi import new_dc  # noqa: PLC0415
    st = _st(m)
    hdc, dc = new_dc(m, "window", win["hwnd"])
    if win.get("odmem") is None:
        win["odmem"] = m.alloc(0x40)
    selected = st.get("press") == win["hwnd"]
    cw, ch = client_size(win)
    m.wr(win["odmem"], struct.pack("<11I", 4, win["id"] & 0xFFFF, 0, 1, 1 if selected else 0, win["hwnd"], hdc, 0, 0, cw, ch))
    m.w32(win["odmem"] + 0x2C, 0)
    win["surface"].idx[:] = 0
    win["surface"].direct[:] = False
    mark_dirty(m)
    return win["odmem"]


def invalidate_window(m, hwnd):
    win = window(m, hwnd)
    if win:
        win["invalid"] = True
        mark_dirty(m)


def _write_msg(m, p, msg):
    m.wr(p, struct.pack("<7I", msg[0], msg[1], msg[2], msg[3], kernel32.now_ms(m), _st(m)["cursor"][0],
                        _st(m)["cursor"][1]))


@u("PeekMessageA", 5)
def peek_message(m, a):
    yield from process_sent(m)
    hook = m.state.get("on_pump")
    if hook:
        hook(m)
    st = _st(m)
    q = st["quit"] if st["quit"] is not None else getattr(m.cur, "quit", None)
    if q is not None:
        _write_msg(m, a[0], (0, WM_QUIT, q, 0))
        if a[4] & 1:
            st["quit"] = None
            m.cur.quit = None
        return 1
    msg = _next_message(m, bool(a[4] & 1), a[1])
    if msg is None:
        # A thread that keeps polling an empty queue is spinning: after a few misses, put it to sleep for a
        # virtual millisecond (the retry then returns "no message" straight away), so idle waits are cheap.
        t = m.cur
        t.empty_polls = getattr(t, "empty_polls", 0) + 1
        if t.empty_polls > 3 and not getattr(t, "polled_sleep", False):
            t.polled_sleep = True
            # back off while idle: 1 ms, doubling to 16 ms (input then waits at most 16 virtual ms)
            back = min(0.001 * 2 ** min((t.empty_polls - 4) // 4, 5), 0.016)
            return Block(until=m.vt + back)
        t.polled_sleep = False
        return 0
    m.cur.empty_polls = 0
    _write_msg(m, a[0], msg)
    return 1


@u("GetMessageA", 4)
def get_message(m, a):
    st = _st(m)
    yield from process_sent(m)
    hook = m.state.get("on_pump")
    if hook:
        hook(m)
    if st["quit"] is None and m.state.get("should_stop") and m.state["should_stop"](m):
        st["quit"] = 0
    q = st["quit"] if st["quit"] is not None else getattr(m.cur, "quit", None)
    if q is not None:
        _write_msg(m, a[0], (0, WM_QUIT, q, 0))
        m.cur.quit = None                                # the loop ends; a later loop on this thread starts clean
        return 0
    msg = _next_message(m, True, a[1])
    if msg is not None:
        _write_msg(m, a[0], msg)
        return 1
    return Block(until=m.vt + 0.003)                     # idle: let other threads run, then look again


@u("SetTimer", 4)
def set_timer(m, a):
    st = _st(m)
    tid = a[1] or (len(st["timers"]) + 1)
    st["timers"][(a[0], tid)] = {"delay": max(a[2], 1), "proc": a[3], "next": kernel32.now_ms(m) + max(a[2], 1)}
    return tid


@u("KillTimer", 2)
def kill_timer(m, a):
    _st(m)["timers"].pop((a[0], a[1]), None)
    return 1


# ---- painting and DCs ------------------------------------------------------------------------------------------
@u("GetDC", 1)
def get_dc(m, a):
    h, d = new_dc(m, "window", a[0])
    if not a[0] or not window(m, a[0]):
        d.hwnd = _desktop_window(m)
    return h


@u("GetWindowDC", 1)
def get_window_dc(m, a):
    return get_dc(m, a)


def _desktop_window(m):
    st = _st(m)
    if "desktop_hwnd" not in st:
        w = new_window(m, "#desktop", 0, 0, 0, 0, 0, SCREEN_W, SCREEN_H, "", 0, 0)
        w["visible"] = True
        st["desktop_hwnd"] = w["hwnd"]
    return st["desktop_hwnd"]


u("ReleaseDC", 2)(lambda m, a: 1)


@u("BeginPaint", 2)
def begin_paint(m, a):
    win = window(m, a[0])
    h, d = new_dc(m, "window", a[0])
    cw, ch = client_size(win) if win else (0, 0)
    m.wr(a[1], struct.pack("<IIiiiiII", h, 1, 0, 0, cw, ch, 0, 0) + b"\0" * 32)
    if win:
        win["invalid"] = False
        win["texts"] = {}                                        # the text on a window is what its latest paint wrote (gdi.draw_text keeps it)
        if win.get("erase", True):                               # the update region was marked for erasing
            win["erase"] = False
            yield from send(m, a[0], WM_ERASEBKGND, h, 0)
    return h


u("EndPaint", 2)(lambda m, a: 1)


@u("FillRect", 3)
def fill_rect_api(m, a):
    dc = dc_of(m, a[0])
    l, t, r, b = struct.unpack("<4i", m.rd(a[1], 16))
    br = obj(m, a[2])
    if a[2] < 32 and not br:                                # COLOR_xxx + 1 system brush indices
        color = (192, 192, 192)
    else:
        color = br[1] if br and br[0] == "brush" and br[1] else None
    if dc and color is not None:
        fill_rect(m, dc, l, t, r, b, color)
    return 1


@u("FrameRect", 3)
def frame_rect(m, a):
    dc = dc_of(m, a[0])
    l, t, r, b = struct.unpack("<4i", m.rd(a[1], 16))
    br = obj(m, a[2])
    color = br[1] if br and br[0] == "brush" and br[1] else (0, 0, 0)
    for x0, y0, x1, y1 in ((l, t, r, t + 1), (l, b - 1, r, b), (l, t, l + 1, b), (r - 1, t, r, b)):
        fill_rect(m, dc, x0, y0, x1, y1, color)
    return 1


u("DrawFocusRect", 2)(lambda m, a: 1)


DT_CENTER, DT_RIGHT, DT_VCENTER, DT_BOTTOM, DT_WORDBREAK, DT_SINGLELINE, DT_CALCRECT, DT_NOPREFIX = 1, 2, 4, 8, 0x10, 0x20, 0x400, 0x800


def _wrap_lines(m, dc, text, width, wordbreak, single):
    """Lines of `text` for DrawText (all widths in logical units): split at newlines unless single-line, and, with DT_WORDBREAK, at
    spaces so that no line is wider than `width` (a word wider than the line gets its own line)."""
    paras = [text] if single else text.replace("\r", "").split("\n")
    lines = []
    for para in paras:
        if not wordbreak or single:
            lines.append(para)
            continue
        cur = ""
        for word in para.split(" "):
            trial = word if not cur else cur + " " + word
            if cur and text_size(m, dc, trial.encode("latin-1", "replace"))[0] > width:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        lines.append(cur)
    return lines


@u("DrawTextA", 5)
def draw_text_a(m, a):
    dc = dc_of(m, a[0])
    raw = m.cstr(a[1]) if S32(a[2]) < 0 else m.rd(a[1], a[2])
    l, t, r, b = struct.unpack("<4i", m.rd(a[3], 16))
    fmt = a[4]
    text = raw.decode("latin-1")
    if not fmt & DT_NOPREFIX:                                   # "&x" marks a mnemonic (underlined in a menu); "&&" is an ampersand
        text = text.replace("&&", "\0").replace("&", "").replace("\0", "&")
    single = bool(fmt & DT_SINGLELINE)
    lines = _wrap_lines(m, dc, text, r - l, bool(fmt & DT_WORDBREAK), single)
    sizes = [text_size(m, dc, ln.encode("latin-1", "replace")) for ln in lines]
    lh = sizes[0][1] if sizes else 0
    total_h = lh * len(lines)
    widest = max([w for w, _ in sizes] + [0])
    if fmt & DT_CALCRECT:
        right = r if fmt & DT_WORDBREAK and not single else l + widest
        m.wr(a[3], struct.pack("<4i", *(S32(v & 0xFFFFFFFF) for v in (l, t, right, t + total_h))))   # (a RECT of 0x7fffffff wraps as it does in C)
        return total_h
    y = t
    if single and fmt & DT_VCENTER:
        y = t + (b - t - total_h) // 2
    elif single and fmt & DT_BOTTOM:
        y = b - total_h
    for ln, (tw, _) in zip(lines, sizes):
        x = l + (r - l - tw) // 2 if fmt & DT_CENTER else r - tw if fmt & DT_RIGHT else l
        draw_text(m, dc, x, y, ln.encode("latin-1", "replace"), align=False)
        y += lh
    return total_h


# ---- strings ---------------------------------------------------------------------------------------------------
@api("user32.dll", "wsprintfA", None)
def wsprintf(m, a):
    out = format_c(m, m.cstr(a[1]), va(m, 2))
    m.put_cstr(a[0], out)
    return len(out)


# ---- dialogs, controls, menus ------------------------------------------------------------------------------------
@u("MessageBoxA", 4)
def message_box(m, a):
    m.log(f"   MessageBox: {m.cstr(a[2]).decode('latin-1')!r}: {m.cstr(a[1]).decode('latin-1')!r} -> IDOK")
    m.state.setdefault("messageboxes", []).append((m.cstr(a[2]).decode("latin-1"), m.cstr(a[1]).decode("latin-1")))
    return 1


DLU_X, DLU_Y = 1.5, 1.625            # dialog units to pixels, for a 10-point face


def dlg_item(m, hdlg, cid):
    win = window(m, hdlg)
    if not win:
        return 0
    for c in win["children"]:
        cw = window(m, c)
        if cw and cw["id"] == cid:
            return c
    return 0


@u("GetDlgItem", 2)
def get_dlg_item(m, a):
    return dlg_item(m, a[0], a[1])


@u("SendDlgItemMessageA", 5)
def send_dlg_item_message(m, a):
    h = dlg_item(m, a[0], a[1])
    if not h:
        return 0
    r = yield from send(m, h, a[2], a[3], a[4])
    return r


@u("SetDlgItemTextA", 3)
def set_dlg_item_text(m, a):
    w = window(m, dlg_item(m, a[0], a[1]))
    if w:
        w["title"] = m.cstr(a[2]).decode("latin-1")
    return 1


@u("GetDlgItemTextA", 4)
def get_dlg_item_text(m, a):
    w = window(m, dlg_item(m, a[0], a[1]))
    b = (w["title"] if w else "").encode("latin-1")[:max(a[3] - 1, 0)]
    m.put_cstr(a[2], b)
    return len(b)


@u("SetDlgItemInt", 4)
def set_dlg_item_int(m, a):
    w = window(m, dlg_item(m, a[0], a[1]))
    if w:
        w["title"] = str(S32(a[2]) if a[3] else a[2])
    return 1


@u("GetDlgItemInt", 4)
def get_dlg_item_int(m, a):
    w = window(m, dlg_item(m, a[0], a[1]))
    try:
        v = int((w or {"title": "0"})["title"])
    except ValueError:
        v = 0
    if a[2]:
        m.w32(a[2], 1)
    return u32(v)


@u("CheckDlgButton", 3)
def check_dlg_button(m, a):
    w = window(m, dlg_item(m, a[0], a[1]))
    if w:
        w["checked"] = a[2]
    return 1


@u("IsDlgButtonChecked", 2)
def is_dlg_button_checked(m, a):
    w = window(m, dlg_item(m, a[0], a[1]))
    return w.get("checked", 0) if w else 0


@u("CheckRadioButton", 4)
def check_radio_button(m, a):
    for cid in range(a[1], a[2] + 1):
        w = window(m, dlg_item(m, a[0], cid))
        if w:
            w["checked"] = 1 if cid == a[3] else 0
    return 1


@u("EndDialog", 2)
def end_dialog(m, a):
    w = window(m, a[0])
    if w:
        w["ended"], w["result"] = True, a[1]
    return 1


@u("DialogBoxParamA", 5)
def dialog_box(m, a):
    """A modal dialog: build the window and its controls from the template, send WM_INITDIALOG, then serve
    messages until EndDialog. The host (or a script) can press its buttons with `press_dialog_button`."""
    hinst, tmpl, parent, proc, param = a
    res = kernel32.find_resource(m, hinst, tmpl, 5)
    if not res:
        m.log(f"   DialogBoxParam(template={tmpl}): no such resource")
        return 0xFFFFFFFF
    dd = parse_dialog(m.rd(res[0], res[1]))
    w, h = int(dd["cx"] * DLU_X), int(dd["cy"] * DLU_Y)
    win = new_window(m, "#32770", parent, dd["style"], dd["exstyle"], (SCREEN_W - w) // 2, (SCREEN_H - h) // 2, w, h,
                     dd["title"], 0, param)
    win.update(dlgproc=proc, visible=True, ended=False, result=0, dialog=dd)
    hdlg = win["hwnd"]
    first = 0
    for it in dd["items"]:
        c = new_window(m, it["cls"], hdlg, it["style"], it["exstyle"], int(it["x"] * DLU_X), int(it["y"] * DLU_Y),
                       int(it["cx"] * DLU_X), int(it["cy"] * DLU_Y), it["text"], it["id"] & 0xFFFFFFFF, 0)
        c["id"] = it["id"] & 0xFFFFFFFF
        c["visible"] = bool(it["style"] & WS_VISIBLE)
        c["checked"] = 0
        if not first and it["style"] & 0x10000:                  # WS_TABSTOP
            first = c["hwnd"]
    st = _st(m)
    st["dialogs"].append(hdlg)
    st["active"] = st["focus"] = hdlg
    m.log(f"   DialogBoxParam: template {tmpl} '{dd['title']}' with {len(dd['items'])} controls, "
          f"proc 0x{proc:08x}")
    if m.state.get("log_dialogs", True):
        m.log("      controls: " + "; ".join(f"{it['id'] & 0xFFFFFFFF}:{it['cls']}:{it['text'][:24]!r}"
                                            for it in dd["items"] if it["cls"] in ("BUTTON", "COMBOBOX", "LISTBOX", "EDIT")))
    yield Cont(proc, [hdlg, WM_INITDIALOG, first, param])
    while not win["ended"]:
        yield from process_sent(m)
        hook = m.state.get("on_pump")
        if hook:
            hook(m)
        msg = _next_message(m, True)
        if msg is not None:
            yield from send(m, msg[0], msg[1], msg[2], msg[3]) if msg[1] != WM_TIMER or not msg[3] else \
                _timer_callback(m, msg)
            continue
        yield Block(until=m.vt + 0.003)
    st["dialogs"].remove(hdlg)
    r = win["result"]
    destroy(m, hdlg)
    return r


def _timer_callback(m, msg):
    yield Cont(msg[3], [msg[0], WM_TIMER, msg[2], kernel32.now_ms(m)])
    return 0


def press_dialog_button(m, cid):
    """Host input: click a button in the topmost dialog (a WM_COMMAND with BN_CLICKED to its procedure)."""
    st = _st(m)
    if not st["dialogs"]:
        return False
    h = st["dialogs"][-1]
    ctl = dlg_item(m, h, cid)
    if not ctl or not window(m, ctl)["visible"]:
        return False                                              # that button is not in the open dialog (yet)
    st["queue"].append((h, WM_COMMAND, cid & 0xFFFF, ctl))
    return True


def select_dialog_item(m, cid, index):
    """Host input: pick an entry in a combo or list box of the topmost dialog and notify the procedure."""
    st = _st(m)
    if not st["dialogs"]:
        return False
    h = st["dialogs"][-1]
    ctl = dlg_item(m, h, cid)
    w = window(m, ctl)
    if not w:
        return False
    w["sel"] = index
    st["queue"].append((h, WM_COMMAND, (1 << 16) | (cid & 0xFFFF), ctl))          # CBN_SELCHANGE = LBN_SELCHANGE = 1
    return True


def _scroll(win, bar):
    return win.setdefault("scroll", {}).setdefault(bar & 3, [0, 0, 0])             # [min, max, pos]


@u("SetScrollRange", 5)
def set_scroll_range(m, a):
    win = window(m, a[0])
    if win:
        sc = _scroll(win, a[1])
        sc[0], sc[1] = S32(a[2]), S32(a[3])
        sc[2] = min(max(sc[2], sc[0]), sc[1])
    return 1


@u("GetScrollRange", 4)
def get_scroll_range(m, a):
    win = window(m, a[0])
    sc = _scroll(win, a[1]) if win else [0, 0, 0]
    m.wr(a[2], struct.pack("<i", sc[0]))
    m.wr(a[3], struct.pack("<i", sc[1]))
    return 1


@u("SetScrollPos", 4)
def set_scroll_pos(m, a):
    win = window(m, a[0])
    if not win:
        return 0
    sc = _scroll(win, a[1])
    old, sc[2] = sc[2], min(max(S32(a[2]), sc[0]), sc[1])
    return old


u("GetScrollPos", 2)(lambda m, a: _scroll(window(m, a[0]), a[1])[2] if window(m, a[0]) else 0)
u("LoadBitmapA", 2)(lambda m, a: 0)
# ---- popup menus ---------------------------------------------------------------------------------------------
# A menu is ("menu", items); an item is a dict(id, text, flags, sub). The game's right-click menus (card actions, "Run to this
# phase", the graveyard views) are popups: TrackPopupMenu blocks the calling thread until the host picks an item or dismisses
# the menu (the compositor draws it, inject_mouse / inject_key_event drive it).
MF_GRAYED, MF_DISABLED, MF_CHECKED, MF_POPUP, MF_BYPOSITION, MF_SEPARATOR = 0x1, 0x2, 0x8, 0x10, 0x400, 0x800
TPM_RETURNCMD, MENU_ITEM_H, MENU_SEP_H = 0x100, 18, 6
WM_INITMENU, WM_INITMENUPOPUP, WM_MENUSELECT = 0x116, 0x117, 0x11F


def _menu_items(m, h):
    o = obj(m, h)
    return o[1] if isinstance(o, tuple) and o and o[0] == "menu" else None


def _find_item(items, key, flags):
    """Index of the item a menu API names: by position (MF_BYPOSITION) or by command id."""
    if flags & MF_BYPOSITION:
        return key if 0 <= key < len(items) else None
    return next((i for i, it in enumerate(items) if it["id"] == key and not it["flags"] & MF_POPUP), None)


@u("AppendMenuA", 4)
def append_menu(m, a):
    items = _menu_items(m, a[0])
    if items is None:
        return 0
    flags = a[1]
    text = "" if flags & (MF_SEPARATOR | 0x100 | 0x4) or not a[3] else m.cstr(a[3]).decode("latin-1")
    items.append(dict(id=a[2], text=text, flags=flags, sub=a[2] if flags & MF_POPUP else 0))
    return 1


@u("ModifyMenuA", 5)
def modify_menu(m, a):
    items = _menu_items(m, a[0])
    i = _find_item(items, a[1], a[2]) if items is not None else None
    if i is None:
        return 0
    flags = a[2]
    text = "" if flags & (MF_SEPARATOR | 0x100 | 0x4) or not a[4] else m.cstr(a[4]).decode("latin-1")
    items[i] = dict(id=a[3], text=text, flags=flags & ~MF_BYPOSITION, sub=a[3] if flags & MF_POPUP else 0)
    return 1


def _remove_menu(m, a):
    items = _menu_items(m, a[0])
    i = _find_item(items, a[1], a[2]) if items is not None else None
    if i is None:
        return 0
    del items[i]
    return 1


u("DeleteMenu", 3)(_remove_menu)
u("RemoveMenu", 3)(_remove_menu)
u("CreatePopupMenu", 0)(lambda m, a: new_obj(m, ("menu", [])))
u("DestroyMenu", 1)(lambda m, a: 1)
u("GetMenuItemCount", 1)(lambda m, a: len(_menu_items(m, a[0]) or ()) if _menu_items(m, a[0]) is not None else 0xFFFFFFFF)


def _set_item_flag(m, a, mask, on_value):
    items = _menu_items(m, a[0])
    i = _find_item(items, a[1], a[2]) if items is not None else None
    if i is None:
        return 0xFFFFFFFF
    before = items[i]["flags"] & mask
    items[i]["flags"] = (items[i]["flags"] & ~mask) | (a[2] & mask)
    return before


u("CheckMenuItem", 3)(lambda m, a: _set_item_flag(m, a, MF_CHECKED, MF_CHECKED))
u("EnableMenuItem", 3)(lambda m, a: _set_item_flag(m, a, MF_GRAYED | MF_DISABLED, MF_GRAYED))


def popup_levels(m, popup):
    """[(x, y, w, h, [(item, y0, y1)])] for each open level, in screen pixels (the compositor and the hit test share it)."""
    out = []
    for items, x, y in popup["levels"]:
        w = max([len(it["text"].replace("\t", "    ")) for it in items] + [8]) * 7 + 40
        h = 4 + sum(MENU_SEP_H if it["flags"] & MF_SEPARATOR else MENU_ITEM_H for it in items)
        if x + w > SCREEN_W:                                    # a menu stays on the screen: shifted left, or above the point
            x = max(SCREEN_W - w, 0)
        if y + h > SCREEN_H:
            y = max(y - h, 0) if y - h >= 0 else max(SCREEN_H - h, 0)
        rows, cy = [], y + 2
        for it in items:
            hh = MENU_SEP_H if it["flags"] & MF_SEPARATOR else MENU_ITEM_H
            rows.append((it, cy, cy + hh))
            cy += hh
        out.append((x, y, w, h, rows))
    return out


def popup_item_at(m, popup, x, y):
    """(level index, item) under a screen point, or (None, None)."""
    for li in range(len(popup["levels"]) - 1, -1, -1):
        lx, ly, w, h, rows = popup_levels(m, popup)[li]
        if lx <= x < lx + w and ly <= y < ly + h:
            for it, y0, y1 in rows:
                if y0 <= y < y1:
                    return li, it
            return li, None
    return None, None


def _popup_choose(m, popup, item):
    """An item was picked: a command ends the menu, a submenu opens beside it, a grey or separator item does nothing."""
    if item is None or item["flags"] & (MF_SEPARATOR | MF_GRAYED | MF_DISABLED):
        return
    if item["flags"] & MF_POPUP:
        sub = _menu_items(m, item["sub"])
        li, (lx, ly, w, h, rows) = len(popup["levels"]) - 1, popup_levels(m, popup)[-1]
        row = next((r for r in rows if r[0] is item), None)
        if sub is not None and row is not None:
            popup["levels"].append((sub, lx + w - 2, row[1]))
        return
    popup["choice"], popup["done"] = item["id"], True


def popup_mouse(m, kind, x, y):
    """Host mouse input while a popup menu is open. Returns True (the event is the menu's)."""
    st = _st(m)
    popup = st["popup"]
    li, item = popup_item_at(m, popup, x, y)
    if kind == "move":
        if popup["hover"] != item:
            popup["hover"] = item
            mark_dirty(m)
    elif kind in ("down", "rdown"):
        if li is None:                                          # a click outside dismisses the menu
            popup["done"] = True
        else:
            del popup["levels"][li + 1:]                        # choosing in a level closes the levels opened from it
            _popup_choose(m, popup, item)
        if popup["done"]:
            st["swallow_up"] = True                             # the release that follows the click that closed the menu is not the game's
        mark_dirty(m)
    return True


def popup_key(m, vk, down):
    st = _st(m)
    popup = st["popup"]
    if not down:
        return True
    if vk == 27:                                                # Escape
        if len(popup["levels"]) > 1:
            popup["levels"].pop()
        else:
            popup["done"] = True
    elif vk in (38, 40):                                        # up / down: the next enabled item of the last level
        items = popup["levels"][-1][0]
        cand = [it for it in items if not it["flags"] & (MF_SEPARATOR | MF_GRAYED | MF_DISABLED)]
        if cand:
            cur = popup["hover"] if popup["hover"] in cand else None
            i = (cand.index(cur) + (1 if vk == 40 else -1)) % len(cand) if cur is not None else (0 if vk == 40 else len(cand) - 1)
            popup["hover"] = cand[i]
    elif vk == 13 and popup["hover"] is not None:
        _popup_choose(m, popup, popup["hover"])
    mark_dirty(m)
    return True


@u("TrackPopupMenu", 7)
def track_popup_menu(m, a):
    """Show the menu at screen (x, y) and wait for the host: returns the chosen command (TPM_RETURNCMD) or 1 after posting it as a
    WM_COMMAND to the window, and 0 if the menu was dismissed."""
    items = _menu_items(m, a[0])
    st = _st(m)
    if items is None or st.get("popup"):
        return 0
    # Windows tells the owner the menu is about to open; the game fills its menus in at these (WM_INITMENU, WM_INITMENUPOPUP).
    yield from send(m, a[5], WM_INITMENU, a[0], 0)
    yield from send(m, a[5], WM_INITMENUPOPUP, a[0], 0)
    if not items:
        return 0
    popup = dict(levels=[(items, S32(a[2]), S32(a[3]))], hover=None, done=False, choice=0, hwnd=a[5])
    st["popup"] = popup
    mark_dirty(m)
    while not popup["done"]:
        yield from process_sent(m)
        yield Block(until=m.vt + 0.003)
    st["popup"] = None
    mark_dirty(m)
    yield from send(m, a[5], WM_MENUSELECT, 0xFFFF0000, 0)           # the menu closed: the game empties it here
    if not popup["choice"]:
        return 0
    if a[1] & TPM_RETURNCMD:
        return popup["choice"]
    st["queue"].append((a[5], WM_COMMAND, popup["choice"] & 0xFFFF, 0))
    return 1


# ---- host input injection ---------------------------------------------------------------------------------
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_RBUTTONDOWN, WM_RBUTTONUP = 0x200, 0x201, 0x202, 0x204, 0x205
WM_KEYDOWN, WM_KEYUP, WM_CHAR = 0x100, 0x101, 0x102


def main_hwnd(m):
    st = _st(m)
    for h, w in st["windows"].items():
        if w["visible"] and not w["style"] & WS_CHILD and w["proc"] and h != st.get("desktop_hwnd"):
            return h
    return 0


def abs_rect(m, win):
    """A window's rectangle in screen coordinates (children are positioned relative to their parent)."""
    st = _st(m)
    x, y = win["x"], win["y"]
    p = st["windows"].get(win["parent"]) if win["parent"] else None
    while p is not None:
        x, y = x + p["x"], y + p["y"]
        p = st["windows"].get(p["parent"]) if p["parent"] else None
    return x, y, x + win["w"], y + win["h"]


def window_at(m, x, y):
    """The topmost visible window under a screen point. Z-order: windows under a WS_POPUP window are above those
    that are not; among siblings a higher `z` is above (creation order, changed by BringWindowToTop and SetWindowPos); a child
    is above its parent."""
    st = _st(m)
    best, best_key = 0, None
    for order, (h, w) in enumerate(st["windows"].items()):
        builtin_button = not w["proc"] and str(w["cls"]).upper() == "BUTTON" and w["w"] > 0 and w["enabled"]
        if not w["visible"] or not (w["proc"] or w.get("dlgproc") or w.get("movie") or builtin_button) or h == st.get("desktop_hwnd"):
            continue
        anc, ok, popup = w, True, bool(w["style"] & WS_POPUP and not w["style"] & WS_CHILD)
        while anc["parent"] and anc["parent"] in st["windows"]:                 # every ancestor must be visible
            anc = st["windows"][anc["parent"]]
            ok = ok and anc["visible"]
            popup = popup or bool(anc["style"] & WS_POPUP and not anc["style"] & WS_CHILD and anc["parent"] == 0
                                  and anc is not w and False)
        # the top-level ancestor decides popup-ness: popups sit above every non-popup window
        top = w
        while top["parent"] and top["parent"] in st["windows"]:
            top = st["windows"][top["parent"]]
        popup = sum(1 for c in [w["hwnd"]] + _ancestors(st, w)                      # popup nesting depth = layer
                    if st["windows"][c]["style"] & WS_POPUP and not st["windows"][c]["style"] & WS_CHILD)
        if not ok:
            continue
        x0, y0, x1, y1 = abs_rect(m, w)
        if x0 <= x < x1 and y0 <= y < y1:
            key = (popup, tuple(st["windows"][c]["z"] for c in reversed([h] + _ancestors(st, w))))    # top-level z first; a child above its parent
            if m.state.get("gdi_debug"):
                m.log(f"      [hit] 0x{h:x} {w['cls']!r} popup={popup} z={key[1]} rect={(x0, y0, x1, y1)}")
            if best_key is None or key > best_key:
                best, best_key = h, key
    return best


def _ancestors(st, w):
    out = []
    while w["parent"] and w["parent"] in st["windows"]:
        out.append(w["parent"])
        w = st["windows"][w["parent"]]
    return out


def inject_mouse(m, kind, x, y):
    """kind: move | down | up | rdown | rup. (x, y) are screen pixels; the message goes to the window under the
    pointer (or the capturing window) with client coordinates."""
    st = _st(m)
    st["cursor"] = (x, y)
    if st.get("popup"):                                          # an open popup menu takes the mouse
        return popup_mouse(m, kind, x, y)
    if kind in ("up", "rup") and st.pop("swallow_up", False):
        return True
    h = st["capture"] or window_at(m, x, y) or main_hwnd(m)
    if not h:
        return False
    if kind == "down":                                           # a second press at the same spot within the double-click time is
        now, last = kernel32.now_ms(m), st.get("last_down")      # WM_LBUTTONDBLCLK, for windows whose class asks for it (CS_DBLCLKS)
        st["last_down"] = (now, x, y, h)
        cls = st["classes"].get(str(st["windows"][h]["cls"]).lower())
        if last and last[3] == h and now - last[0] <= 500 and abs(x - last[1]) <= 4 and abs(y - last[2]) <= 4 \
                and cls and cls["style"] & 8:
            kind = "dbl"
            st["last_down"] = None
    x0, y0, _, _ = abs_rect(m, st["windows"][h])
    msg = {"move": WM_MOUSEMOVE, "down": WM_LBUTTONDOWN, "up": WM_LBUTTONUP, "rdown": WM_RBUTTONDOWN,
           "rup": WM_RBUTTONUP, "dbl": 0x203}[kind]
    keys = 1 if kind in ("down", "dbl") else 0
    st["keys"][1] = kind in ("down", "dbl") or (kind == "move" and st["keys"].get(1, False))
    lx, ly = x - x0, y - y0
    tw = st["windows"][h]
    if not tw["proc"] and str(tw["cls"]).upper() == "BUTTON":          # a built-in push button: click = WM_COMMAND
        if kind == "down":
            st["press"] = h
            invalidate_window(m, h)
        elif kind == "up" and st.get("press") == h:
            st["press"] = 0
            invalidate_window(m, h)
            st["queue"].append((tw["parent"], WM_COMMAND, tw["id"] & 0xFFFF, h))    # BN_CLICKED
            if m.state.get("gdi_debug"):
                m.log(f"   [input] button 0x{h:x} id {tw['id']} clicked -> WM_COMMAND to 0x{tw['parent']:x}")
        return True
    if kind in ("down", "dbl", "rdown") and not tw["proc"] and tw["style"] & WS_CHILD and tw["parent"] in st["windows"] \
            and str(tw["cls"]).upper() not in ("STATIC",):
        px0, py0, _, _ = abs_rect(m, st["windows"][tw["parent"]])                  # a click on a built-in child (a movie window, an edit box) is
        st["queue"].append((tw["parent"], 0x210, (msg & 0xFFFF) | ((tw["id"] & 0xFFFF) << 16),          # reported to its parent: WM_PARENTNOTIFY
                            (((y - py0) & 0xFFFF) << 16) | ((x - px0) & 0xFFFF)))
    if m.state.get("gdi_debug"):
        w = st["windows"][h]
        m.log(f"   [input] {kind} at {x},{y} -> 0x{h:x} {w['cls']!r} {w['title']!r} client {lx},{ly} tid={w.get('tid')}")
    if kind in ("move", "down", "rdown") and st.get("hover") != h:
        old = st.get("hover")
        st["hover"] = h
        if old and old in st["windows"]:
            st["queue"].append((old, 0x20, old, (0x200 << 16) | 0))                  # WM_SETCURSOR for the old one
        st["queue"].append((h, 0x84, 0, (y << 16) | (x & 0xFFFF)))                   # WM_NCHITTEST
        st["queue"].append((h, 0x20, h, (msg << 16) | 1))                             # WM_SETCURSOR, HTCLIENT
        if kind != "move":
            st["queue"].append((h, WM_MOUSEMOVE, 0, ((ly & 0xFFFF) << 16) | (lx & 0xFFFF)))
    st["queue"].append((h, msg, keys, ((ly & 0xFFFF) << 16) | (lx & 0xFFFF)))
    return True


SCANCODES = {13: 0x1C, 27: 0x01, 32: 0x39, 8: 0x0E, 9: 0x0F, 37: 0x4B, 38: 0x48, 39: 0x4D, 40: 0x50, 46: 0x53}
for _i, _c in enumerate("QWERTYUIOP"):
    SCANCODES[ord(_c)] = 0x10 + _i
for _i, _c in enumerate("ASDFGHJKL"):
    SCANCODES[ord(_c)] = 0x1E + _i
for _i, _c in enumerate("ZXCVBNM"):
    SCANCODES[ord(_c)] = 0x2C + _i
for _i, _c in enumerate("1234567890"):
    SCANCODES[ord(_c)] = 0x02 + _i


def inject_key_event(m, vk, scancode, down, char=None, repeat=False):
    """One half of a key press, as a keyboard sends it: WM_KEYDOWN (and WM_CHAR when it types something) or WM_KEYUP, with
    the scan code in lParam; the key's state (GetKeyState, GetAsyncKeyState) follows. Live input (live.py) uses this; a
    script's `key` (inject_key) is the pair at once."""
    st = _st(m)
    if st.get("popup"):
        return popup_key(m, vk, down)
    if st.get("dialogs") and vk in (0x1B, 0x0D):             # the dialog manager: Esc is IDCANCEL, Enter is IDOK, sent to the open dialog
        if down and not repeat:
            hdlg = st["dialogs"][-1]
            cid = 2 if vk == 0x1B else 1
            st["queue"].append((hdlg, WM_COMMAND, cid, dlg_item(m, hdlg, cid)))
        return True
    h = main_hwnd(m)
    if not h:
        return False
    sc = (scancode & 0xFF) << 16
    if down:
        st["keys"][vk] = True
        st["queue"].append((h, WM_KEYDOWN, vk, 1 | sc | (0x40000000 if repeat else 0)))
        if char is not None:
            st["queue"].append((h, WM_CHAR, char, 1 | sc | (0x40000000 if repeat else 0)))
    else:
        st["keys"][vk] = False
        st["queue"].append((h, WM_KEYUP, vk, 0xC0000001 | sc))
    return True


def inject_key(m, vk, char=None):
    """A key press: WM_KEYDOWN (with its scan code), WM_CHAR if `char`, then WM_KEYUP."""
    st = _st(m)
    h = main_hwnd(m)
    if not h:
        return False
    sc = SCANCODES.get(vk, 0) << 16
    st["keys"][vk] = True
    st["queue"].append((h, WM_KEYDOWN, vk, 1 | sc))
    if char is not None:
        st["queue"].append((h, WM_CHAR, char, 1 | sc))
    st["queue"].append((h, WM_KEYUP, vk, 0xC0000001 | sc))
    st["release"] = st.get("release", []) + [vk]
    return True

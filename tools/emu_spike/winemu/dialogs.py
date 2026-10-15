"""Dialog templates: DLGTEMPLATE and the extended DLGTEMPLATEEX, parsed from a PE resource."""
import struct

CLASSES = {0x0080: "BUTTON", 0x0081: "EDIT", 0x0082: "STATIC", 0x0083: "LISTBOX", 0x0084: "SCROLLBAR", 0x0085: "COMBOBOX"}


def parse_dialog(d):
    """dict(title, style, exstyle, x, y, cx, cy, font=(size, face), items=[dict(...)]) in dialog units."""
    ext = struct.unpack_from("<HH", d, 0) == (1, 0xFFFF)
    o = 0
    if ext:
        help_id, exstyle, style, cnt, x, y, cx, cy = struct.unpack_from("<IIIHhhhh", d, 4 + 0)
        o = 4 + 4 + 4 + 4 + 2 + 8
    else:
        style, exstyle, cnt, x, y, cx, cy = struct.unpack_from("<IIHhhhh", d, 0)
        o = 18

    def wstr(o):
        s = []
        while True:
            c = struct.unpack_from("<H", d, o)[0]
            o += 2
            if c == 0:
                return "".join(map(chr, s)), o
            s.append(c)

    def ordinal_or_str(o):
        if struct.unpack_from("<H", d, o)[0] == 0xFFFF:
            return struct.unpack_from("<H", d, o + 2)[0], o + 4
        if struct.unpack_from("<H", d, o)[0] == 0:
            return "", o + 2
        return wstr(o)

    _, o = ordinal_or_str(o)                                   # menu
    _, o = ordinal_or_str(o)                                   # window class
    title, o = wstr(o)
    font = None
    if style & 0x40:                                           # DS_SETFONT
        size = struct.unpack_from("<H", d, o)[0]
        o += 2
        if ext:
            o += 4                                             # weight, italic, charset
        face, o = wstr(o)
        font = (size, face)
    items = []
    for _ in range(cnt):
        o = (o + 3) & ~3
        if ext:
            hid, ex, st, ix, iy, icx, icy, cid = struct.unpack_from("<IIIhhhhI", d, o)
            o += 24
        else:
            st, ex, ix, iy, icx, icy, cid = struct.unpack_from("<IIhhhhH", d, o)
            o += 18
        cls, o = ordinal_or_str(o)
        txt, o = ordinal_or_str(o)
        extra = struct.unpack_from("<H", d, o)[0]
        o += 2 + extra
        items.append(dict(style=st, exstyle=ex, x=ix, y=iy, cx=icx, cy=icy, id=cid,
                          cls=CLASSES.get(cls, cls) if isinstance(cls, int) else cls, text=txt))
    return dict(title=title, style=style, exstyle=exstyle, x=x, y=y, cx=cx, cy=cy, font=font, items=items, ext=ext)

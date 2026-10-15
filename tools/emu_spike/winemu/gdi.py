"""GDI32: device contexts, bitmaps (DIB sections live in emulated memory), palettes, pens, brushes, text.

Screen model: the desktop is a truecolor surface (numpy RGB). A window has its own client surface; a window
DC draws onto it. The game draws into 8-bit DIB sections itself (writing straight into emulated memory) and
BitBlts them to the window; those blits convert indices to RGB through the DIB's colour table.
"""
import os
import struct

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .machine import api, u32
from .paths import host_path

g32 = lambda name, argc: api("gdi32.dll", name, argc)
SCREEN_W, SCREEN_H = 640, 480

STOCK = {0: ("brush", (255, 255, 255)), 1: ("brush", (192, 192, 192)), 2: ("brush", (128, 128, 128)),
         3: ("brush", (64, 64, 64)), 4: ("brush", (0, 0, 0)), 5: ("brush", None),
         6: ("pen", (255, 255, 255)), 7: ("pen", (0, 0, 0)), 8: ("pen", None),
         10: ("font", 12), 11: ("font", 12), 12: ("font", 13), 13: ("font", 13), 16: ("font", 13), 17: ("font", 13),
         15: ("palette", None)}


def _st(m):
    st = m.state.setdefault("gdi", {})
    if not st:
        st.update(objs={}, next=0x2001, font_cache={}, quant_cache={})
        st["desktop"] = Surface(SCREEN_W, SCREEN_H)
        st["system_palette"] = [(i, i, i) for i in range(256)]
    return st


class Surface:
    """A window's client area. Like the 8-bit display the game targets it holds palette *indices*; colours
    come from the current system palette when the screen is composed, so palette animation changes the
    picture without any redraw."""
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.idx = np.zeros((h, w), np.uint8)
        self.rgb = np.zeros((h, w, 3), np.uint8)           # direct-colour pixels (24/32-bit sources, RGB fills)
        self.direct = np.zeros((h, w), bool)               # where `rgb` overrides the palette lookup


def system_lut(m):
    return np.array(_st(m)["system_palette"] + [(0, 0, 0)] * 256, np.uint8)[:256]


def surface_rgb(m, surf, x0=0, y0=0, x1=None, y1=None):
    out = system_lut(m)[surf.idx[y0:y1, x0:x1]]
    d = surf.direct[y0:y1, x0:x1]
    if d.any():
        out = np.where(d[:, :, None], surf.rgb[y0:y1, x0:x1], out)
    return out


def quantize(m, rgb):
    """Nearest system-palette index for each pixel of an RGB array (h, w, 3)."""
    lut = system_lut(m).astype(np.int32)
    flat = rgb.reshape(-1, 3).astype(np.int32)
    keys = (flat[:, 0] << 16) | (flat[:, 1] << 8) | flat[:, 2]
    uniq, inv = np.unique(keys, return_inverse=True)
    idx = np.empty(len(uniq), np.uint8)
    for i, k in enumerate(uniq):
        c = np.array([(k >> 16) & 255, (k >> 8) & 255, k & 255])
        idx[i] = int(np.argmin(((lut - c) ** 2).sum(1)))
    return idx[inv].reshape(rgb.shape[:2])


def dib_to_system_lut(m, palette):
    """Map a DIB colour table to system-palette indices: identity where the entries agree (as Windows
    does for an identity palette), otherwise the nearest colour."""
    sysp = system_lut(m).astype(np.int32)
    tab = np.array(list(palette) + [(0, 0, 0)] * (256 - len(palette)), np.int32)[:256]
    out = np.empty(256, np.uint8)
    for i in range(256):
        if (tab[i] == sysp[i]).all():
            out[i] = i
        else:
            out[i] = int(np.argmin(((sysp - tab[i]) ** 2).sum(1)))
    return out


def new_obj(m, obj):
    st = _st(m)
    h = st["next"]
    st["next"] += 4
    st["objs"][h] = obj
    st.setdefault("handle_of", {})[id(obj)] = h                # for _handle_of: the object's handle without a scan
    return h


def obj(m, h):
    return _st(m)["objs"].get(h)


# ---- colours -----------------------------------------------------------------------------------------------
def colorref(m, dc, c):
    """(r, g, b) from a COLORREF. Palette-index and palette-relative forms use the DC's palette."""
    flag = (c >> 24) & 0xFF
    if flag == 0x01:                                                   # PALETTEINDEX
        pal = dc.palette if dc is not None and dc.palette else _st(m)["system_palette"]
        e = pal[(c & 0xFFFF) % len(pal)] if pal else (0, 0, 0)
        return e
    return (c & 0xFF, (c >> 8) & 0xFF, (c >> 16) & 0xFF)


# ---- bitmaps -------------------------------------------------------------------------------------------------
class Bitmap:
    """kind 'dib': indices/pixels in emulated memory at `bits`; kind 'ddb': `rgb` numpy array on the host."""
    def __init__(self, kind, w, h, bpp):
        self.kind, self.w, self.h, self.bpp = kind, w, h, bpp
        self.bits = 0
        self.topdown = False
        self.palette = [(i, i, i) for i in range(256)]
        self.idxmap = None                        # DIB_PAL_COLORS: pixel value -> logical (= system) palette index
        self.idx = None                           # ddb: palette indices in system-palette space (the device format)
        self.mono = None                          # 1-bpp ddb: bool (h, w); converted with the destination DC's colours when blitted
        if kind == "ddb":
            self.idx = np.zeros((h, w), np.uint8)

    @property
    def stride(self):
        return ((self.w * self.bpp + 31) // 32) * 4


def read_dib_rgb(m, bmp, x0, y0, x1, y1):
    """RGB array (h, w, 3) of a rectangle of a DIB section, converting through its colour table."""
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, bmp.w), min(y1, bmp.h)
    if x1 <= x0 or y1 <= y0:
        return np.zeros((0, 0, 3), np.uint8)
    raw = np.frombuffer(m.rd(bmp.bits, bmp.stride * bmp.h), np.uint8).reshape(bmp.h, bmp.stride)
    rows = raw if bmp.topdown else raw[::-1]
    if bmp.bpp == 8:
        lut = np.array(bmp.palette + [(0, 0, 0)] * (256 - len(bmp.palette)), np.uint8)
        return lut[rows[y0:y1, x0:x1]]
    if bmp.bpp == 24:
        px = rows[y0:y1, x0 * 3:x1 * 3].reshape(y1 - y0, x1 - x0, 3)
        return px[:, :, ::-1].copy()
    if bmp.bpp == 32:
        px = rows[y0:y1, x0 * 4:x1 * 4].reshape(y1 - y0, x1 - x0, 4)
        return px[:, :, 2::-1].copy()
    if bmp.bpp == 16:
        v = rows[y0:y1, x0 * 2:x1 * 2].copy().view("<u2").reshape(y1 - y0, x1 - x0).astype(np.uint16)
        r, g, b = ((v >> 10) & 31) << 3, ((v >> 5) & 31) << 3, (v & 31) << 3
        return np.stack([r, g, b], -1).astype(np.uint8)
    return np.zeros((y1 - y0, x1 - x0, 3), np.uint8)


def write_dib_rgb(m, bmp, x0, y0, rgb):
    """Store an RGB rectangle into a DIB section (8-bit: nearest palette entry)."""
    h, w = rgb.shape[:2]
    if bmp.bpp in (24, 32):
        px = rgb[:, :, ::-1]
        if bmp.bpp == 32:
            px = np.concatenate([px, np.zeros((h, w, 1), np.uint8)], axis=2)
        for row in range(h):
            y = y0 + row
            if not 0 <= y < bmp.h:
                continue
            line = bmp.h - 1 - y if not bmp.topdown else y
            xs, xe = max(x0, 0), min(x0 + w, bmp.w)
            if xe > xs:
                bp = bmp.bpp // 8
                m.wr(bmp.bits + line * bmp.stride + xs * bp, np.ascontiguousarray(px[row, xs - x0:xe - x0]).tobytes())
        return
    if bmp.bpp != 8:
        return
    lut = np.array(bmp.palette, np.int32)
    flat = rgb.reshape(-1, 3).astype(np.int32)
    keys = (flat[:, 0] << 16) | (flat[:, 1] << 8) | flat[:, 2]
    uniq, inv = np.unique(keys, return_inverse=True)
    idx = np.empty(len(uniq), np.uint8)
    for i, k in enumerate(uniq):
        c = np.array([(k >> 16) & 255, (k >> 8) & 255, k & 255])
        idx[i] = int(np.argmin(((lut - c) ** 2).sum(1)))
    px = idx[inv].reshape(h, w)
    for row in range(h):
        y = y0 + row
        if not 0 <= y < bmp.h:
            continue
        line = bmp.h - 1 - y if not bmp.topdown else y
        xs, xe = max(x0, 0), min(x0 + w, bmp.w)
        if xe > xs:
            m.wr(bmp.bits + line * bmp.stride + xs, px[row, xs - x0:xe - x0].tobytes())


def write_dib_indices(m, bmp, x0, y0, idx):
    h, w = idx.shape
    for row in range(h):
        y = y0 + row
        if not 0 <= y < bmp.h:
            continue
        line = bmp.h - 1 - y if not bmp.topdown else y
        xs, xe = max(x0, 0), min(x0 + w, bmp.w)
        if xe > xs:
            m.wr(bmp.bits + line * bmp.stride + xs, idx[row, xs - x0:xe - x0].tobytes())


def read_dib_indices(m, bmp, x0, y0, x1, y1):
    raw = np.frombuffer(m.rd(bmp.bits, bmp.stride * bmp.h), np.uint8).reshape(bmp.h, bmp.stride)
    rows = raw if bmp.topdown else raw[::-1]
    return rows[y0:y1, x0:x1]


def parse_bitmapinfo(m, p, usage=0):
    """(width, height, topdown, bpp, palette, header size) from a BITMAPINFO at guest address p.
    With usage == 1 (DIB_PAL_COLORS) the colour table is 16-bit indices into the logical palette, returned
    as `palette` = ("idx", [ints])."""
    size, w, h, planes, bpp, comp = struct.unpack("<IiiHHI", m.rd(p, 20))
    used = m.r32(p + 32)
    ncol = used or ((1 << bpp) if bpp <= 8 else 0)
    if usage == 1:
        words = [m.r16(p + size + 2 * i) for i in range(ncol)]
        return w, abs(h), h < 0, bpp, ("idx", words), size + 2 * ncol
    pal = []
    for i in range(ncol):
        b, g, r, _ = m.rd(p + size + 4 * i, 4)
        pal.append((r, g, b))
    return w, abs(h), h < 0, bpp, pal, size + 4 * ncol


def idx_lut(words):
    out = np.arange(256, dtype=np.uint8)
    for i, v in enumerate(words[:256]):
        out[i] = v & 0xFF
    return out


# ---- device contexts -----------------------------------------------------------------------------------------
class DC:
    def __init__(self, kind, hwnd=0):
        self.kind, self.hwnd = kind, hwnd
        self.bitmap = None                        # a Bitmap for memory DCs
        self.palette = None
        self.textcolor, self.bkcolor, self.bkmode = 0x000000, 0xFFFFFF, 2
        self.pen = ("pen", (0, 0, 0), 1)
        self.brush = ("brush", (255, 255, 255))
        self.font = None
        self.org = (0, 0)                         # viewport origin (device)
        self.wo = (0, 0)                          # window origin (logical)
        self.wext, self.vext = (1, 1), (1, 1)     # window / viewport extents (MM_ISOTROPIC and MM_ANISOTROPIC scale by vext / wext)
        self.sx = self.sy = 1.0                   # device pixels per logical unit
        self.mm = 1                               # map mode (1 = MM_TEXT)
        self.pos = (0, 0)
        self.clip = None
        self.textalign = 0


def new_dc(m, kind, hwnd=0):
    d = DC(kind, hwnd)
    return new_obj(m, d), d


def dc_of(m, h):
    d = obj(m, h)
    return d if isinstance(d, DC) else None


def target_size(m, dc):
    if dc.kind == "memory":
        b = dc.bitmap
        return (b.w, b.h) if b else (1, 1)
    from . import user32
    w = user32.window(m, dc.hwnd)
    return (w["surface"].w, w["surface"].h) if w and w.get("surface") else (SCREEN_W, SCREEN_H)


def get_region(m, dc, x0, y0, x1, y1):
    """RGB pixels of a rectangle of the DC's target (clipped to the target)."""
    w, h = target_size(m, dc)
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
    if x1 <= x0 or y1 <= y0:
        return None
    if dc.kind == "memory":
        b = dc.bitmap
        if b.kind == "ddb":
            return system_lut(m)[b.idx[y0:y1, x0:x1]]
        return read_dib_rgb(m, b, x0, y0, x1, y1)
    from . import user32
    return surface_rgb(m, user32.window(m, dc.hwnd)["surface"], x0, y0, x1, y1)


def put_region(m, dc, x0, y0, rgb):
    """Write an RGB rectangle to the DC's target, honouring its clip rectangle."""
    if rgb is None or rgb.size == 0:
        return
    h, w = rgb.shape[:2]
    if dc.clip:
        cx0, cy0, cx1, cy1 = dc.clip
        nx0, ny0, nx1, ny1 = max(x0, cx0), max(y0, cy0), min(x0 + w, cx1), min(y0 + h, cy1)
        if nx1 <= nx0 or ny1 <= ny0:
            return
        rgb = rgb[ny0 - y0:ny1 - y0, nx0 - x0:nx1 - x0]
        x0, y0 = nx0, ny0
    tw, th = target_size(m, dc)
    sx0, sy0 = max(0, -x0), max(0, -y0)
    ex, ey = min(rgb.shape[1], tw - x0), min(rgb.shape[0], th - y0)
    if ex <= sx0 or ey <= sy0:
        return
    rgb = rgb[sy0:ey, sx0:ex]
    x0, y0 = x0 + sx0, y0 + sy0
    if dc.kind == "memory":
        b = dc.bitmap
        if b.kind == "ddb":
            b.idx[y0:y0 + rgb.shape[0], x0:x0 + rgb.shape[1]] = quantize(m, rgb)
        else:
            write_dib_rgb(m, b, x0, y0, rgb)
    else:
        from . import user32
        surf = user32.window(m, dc.hwnd)["surface"]
        surf.rgb[y0:y0 + rgb.shape[0], x0:x0 + rgb.shape[1]] = rgb
        surf.direct[y0:y0 + rgb.shape[0], x0:x0 + rgb.shape[1]] = True
        user32.mark_dirty(m)


def system_to_dib_lut(m, bmp):
    """system-palette index -> index in an 8-bit DIB section (identity for DIB_PAL_COLORS ones)."""
    if bmp.idxmap is not None:
        return np.arange(256, dtype=np.uint8)
    return dib_to_dib_lut([tuple(c) for c in system_lut(m)], bmp.palette)


def put_indices(m, dc, x0, y0, idx):
    """Write palette indices (system-palette space) to a window surface, a device bitmap or an 8-bit DIB,
    clipped to the DC clip rectangle and the target."""
    h, w = idx.shape
    if dc.clip:
        cx0, cy0, cx1, cy1 = dc.clip
        nx0, ny0, nx1, ny1 = max(x0, cx0), max(y0, cy0), min(x0 + w, cx1), min(y0 + h, cy1)
        if nx1 <= nx0 or ny1 <= ny0:
            return
        idx = idx[ny0 - y0:ny1 - y0, nx0 - x0:nx1 - x0]
        x0, y0 = nx0, ny0
    tw, th = target_size(m, dc)
    sx0, sy0 = max(0, -x0), max(0, -y0)
    ex, ey = min(idx.shape[1], tw - x0), min(idx.shape[0], th - y0)
    if ex <= sx0 or ey <= sy0:
        return
    idx = idx[sy0:ey, sx0:ex]
    x0, y0 = x0 + sx0, y0 + sy0
    if dc.kind == "memory":
        b = dc.bitmap
        if b.kind == "ddb":
            b.idx[y0:y0 + idx.shape[0], x0:x0 + idx.shape[1]] = idx
        elif b.bpp == 8:
            write_dib_indices(m, b, x0, y0, np.ascontiguousarray(system_to_dib_lut(m, b)[idx]))
        return
    from . import user32
    surf = user32.window(m, dc.hwnd)["surface"]
    surf.idx[y0:y0 + idx.shape[0], x0:x0 + idx.shape[1]] = idx
    surf.direct[y0:y0 + idx.shape[0], x0:x0 + idx.shape[1]] = False
    user32.mark_dirty(m)


def dc_indices(m, dc, x0, y0, x1, y1, mono_dc=None):
    """Palette indices (system-palette space) of a rectangle of a DC's target; None when nothing is readable
    without a colour conversion (24-bit DIBs, which go through RGB)."""
    w, h = target_size(m, dc)
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
    if x1 <= x0 or y1 <= y0:
        return x0, y0, np.zeros((0, 0), np.uint8)
    if dc.kind == "memory":
        b = dc.bitmap
        if b.kind == "ddb":
            if b.mono is not None and mono_dc is not None:
                return x0, y0, mono_indices(m, mono_dc, b, x0, y0, x1, y1)
            return x0, y0, b.idx[y0:y1, x0:x1]
        if b.bpp == 8:
            lut = b.idxmap if b.idxmap is not None else dib_to_system_lut(m, b.palette)
            return x0, y0, lut[read_dib_indices(m, b, x0, y0, x1, y1)]
        return x0, y0, None
    from . import user32
    surf = user32.window(m, dc.hwnd)["surface"]
    if surf.direct[y0:y1, x0:x1].any():
        return x0, y0, None
    return x0, y0, surf.idx[y0:y1, x0:x1]


# ---- stock, create, select, delete ---------------------------------------------------------------------------
@g32("GetStockObject", 1)
def get_stock(m, a):
    st = _st(m)
    key = ("stock", a[0])
    if key not in st:
        kind, val = STOCK.get(a[0], ("brush", (255, 255, 255)))
        o = ("brush", val) if kind == "brush" else ("pen", val, 1) if kind == "pen" else \
            ("font", "Arial", val, 400) if kind == "font" else ("palette", [(i, i, i) for i in range(256)])
        st[key] = new_obj(m, o)
    return st[key]


@g32("CreateSolidBrush", 1)
def create_solid_brush(m, a):
    return new_obj(m, ("brush", colorref(m, None, a[0])))


@g32("CreateBrushIndirect", 1)
def create_brush_indirect(m, a):
    style, color, hatch = m.r32(a[0]), m.r32(a[0] + 4), m.r32(a[0] + 8)
    if style == 3:                                                     # BS_PATTERN: `hatch` is a bitmap handle
        return new_obj(m, ("brush", None, hatch))
    return new_obj(m, ("brush", None if style == 1 else colorref(m, None, color)))


g32("CreatePatternBrush", 1)(lambda m, a: new_obj(m, ("brush", None, a[0])))


def brush_pixels(m, brush, w, h, origin=(0, 0)):
    """RGB array (h, w, 3) filled with a brush: solid colour, or a bitmap tiled from `origin`."""
    if len(brush) > 2 and brush[2]:
        bmp = obj(m, brush[2])
        if isinstance(bmp, Bitmap) and bmp.w and bmp.h:
            dc = DC("memory")
            dc.bitmap = bmp
            tile = get_region(m, dc, 0, 0, bmp.w, bmp.h)
            if tile is not None:
                ys = (np.arange(h) + origin[1]) % tile.shape[0]
                xs = (np.arange(w) + origin[0]) % tile.shape[1]
                return tile[ys][:, xs]
    color = brush[1] if brush[1] is not None else (0, 0, 0)
    return np.full((h, w, 3), color, np.uint8)


g32("CreateHatchBrush", 2)(lambda m, a: new_obj(m, ("brush", colorref(m, None, a[1]))))
g32("CreatePen", 3)(lambda m, a: new_obj(m, ("pen", None if a[0] == 5 else colorref(m, None, a[2]), max(a[1], 1))))


@g32("CreatePenIndirect", 1)
def create_pen_indirect(m, a):
    style, width, color = m.r32(a[0]), m.r32(a[0] + 4), m.r32(a[0] + 12)
    return new_obj(m, ("pen", None if style == 5 else colorref(m, None, color), max(width, 1)))


@g32("CreateFontIndirectA", 1)
def create_font_indirect(m, a):
    h = struct.unpack("<i", m.rd(a[0], 4))[0]
    weight = m.r32(a[0] + 16)
    face = m.cstr(a[0] + 28, 32).decode("latin-1")
    return new_obj(m, ("font", face, abs(h) or 13, weight or 400, bool(m.rd(a[0] + 20, 1)[0]), h))


@g32("CreateFontA", 14)
def create_font(m, a):
    h = struct.unpack("<i", struct.pack("<I", a[0]))[0]
    return new_obj(m, ("font", m.cstr(a[13]).decode("latin-1"), abs(h) or 13, a[4] or 400, bool(a[5] & 0xFF), h))


def _family_key(face):
    return face.strip().strip('"').lower()


@g32("AddFontResourceA", 1)
def add_font_resource(m, a):
    """Remember the game's own TrueType file under its family name: CreateFont asks for that family and gets it (not a stand-in)."""
    from PIL import ImageFont  # noqa: PLC0415
    hp, ok = host_path(m.game_root, m.overlay_root, m.cwd, m.cstr(a[0]).decode("latin-1"))
    if not ok:
        return 0
    try:
        family, style = ImageFont.truetype(hp, 20).getname()
    except OSError:
        return 0
    _st(m).setdefault("game_fonts", {}).setdefault(_family_key(family), {})[style.lower()] = hp
    return 1


g32("RemoveFontResourceA", 1)(lambda m, a: 1)


@g32("CreatePalette", 1)
def create_palette(m, a):
    n = m.r16(a[0] + 2)
    ents = [tuple(m.rd(a[0] + 4 + 4 * i, 3)) for i in range(n)]
    return new_obj(m, ("palette", ents))


@g32("SetPaletteEntries", 4)
def set_palette_entries(m, a):
    o = obj(m, a[0])
    if not o or o[0] != "palette":
        return 0
    for i in range(a[2]):
        o[1][(a[1] + i) % len(o[1])] = tuple(m.rd(a[3] + 4 * i, 3))
    return a[2]


@g32("GetPaletteEntries", 4)
def get_palette_entries(m, a):
    o = obj(m, a[0])
    if not o or o[0] != "palette":
        return 0
    for i in range(a[2]):
        m.wr(a[3] + 4 * i, bytes(o[1][(a[1] + i) % len(o[1])]) + b"\0")
    return a[2]


@g32("SelectPalette", 3)
def select_palette(m, a):
    dc, o = dc_of(m, a[0]), obj(m, a[1])
    if not dc or not o or o[0] != "palette":
        return 0
    old, dc.palette = dc.palette, o[1]
    return 1


@g32("RealizePalette", 1)
def realize_palette(m, a):
    dc = dc_of(m, a[0])
    if dc and dc.palette:
        if os.environ.get("PALDBG"):
            ph = _handle_of_pal(m, dc.palette)
            w = None
            if dc.kind == "window":
                from . import user32
                w = user32.window(m, dc.hwnd)
            m.log(f"   [pal] RealizePalette dc=0x{a[0]:x} kind={dc.kind} hwnd=0x{dc.hwnd:x} cls={w and w['cls']!r} pal=0x{ph:x} thread={m.cur.tid}")
        # Only the application's own windows set the hardware palette. A memory DC, or the desktop's (GetDC(NULL), which the game uses to
        # draw card art with a palette of its own), realizes in the background: Windows maps it onto the colours already there.
        if os.environ.get("PAL_LEGACY") or dc.kind == "window" and not _is_desktop(m, dc.hwnd) or "system_palette_set" not in _st(m):
            _st(m)["system_palette"] = dc.palette          # shared list: AnimatePalette on it shows at once
            _st(m)["system_palette_set"] = True
        return len(dc.palette)
    return 0


def _is_desktop(m, hwnd):
    from . import user32
    return hwnd == user32._st(m).get("desktop_hwnd")


def _handle_of_pal(m, entries):
    for h, o in _st(m)["objs"].items():
        if isinstance(o, tuple) and o and o[0] == "palette" and o[1] is entries:
            return h
    return 0


@g32("AnimatePalette", 4)
def animate_palette(m, a):
    o = obj(m, a[0])
    if not o or o[0] != "palette":
        return 0
    for i in range(a[2]):
        o[1][(a[1] + i) % len(o[1])] = tuple(m.rd(a[3] + 4 * i, 3))
    return 1
g32("SetSystemPaletteUse", 2)(lambda m, a: 1)
g32("UnrealizeObject", 1)(lambda m, a: 1)


@g32("SelectObject", 2)
def select_object(m, a):
    dc, o = dc_of(m, a[0]), obj(m, a[1])
    if not dc or o is None:
        return 0
    if isinstance(o, Bitmap):
        old = dc.bitmap
        dc.bitmap = o
        return _handle_of(m, old) if old else _default_bitmap(m)
    kind = o[0]
    if kind == "pen":
        old, dc.pen = dc.pen, o
    elif kind == "brush":
        old, dc.brush = dc.brush, o
    elif kind == "font":
        old, dc.font = dc.font, o
    else:
        return 0
    return _handle_of(m, old) or get_stock(m, [7 if kind == "pen" else 0 if kind == "brush" else 13])


def _handle_of(m, o):
    st = _st(m)
    h = st.get("handle_of", {}).get(id(o), 0)
    if h and st["objs"].get(h) is o:
        return h
    for h, v in st["objs"].items():                            # (an object that was not made by new_obj)
        if v is o:
            return h
    return 0


def _default_bitmap(m):
    st = _st(m)
    if "default_bitmap" not in st:
        st["default_bitmap"] = new_obj(m, Bitmap("ddb", 1, 1, 1))
    return st["default_bitmap"]


@g32("DeleteObject", 1)
def delete_object(m, a):
    o = _st(m)["objs"].pop(a[0], None)
    _st(m).get("handle_of", {}).pop(id(o), None)
    return 1


@g32("DeleteDC", 1)
def delete_dc(m, a):
    o = _st(m)["objs"].pop(a[0], None)
    _st(m).get("handle_of", {}).pop(id(o), None)
    return 1


@g32("CreateCompatibleDC", 1)
def create_compat_dc(m, a):
    h, d = new_dc(m, "memory")
    d.bitmap = obj(m, _default_bitmap(m))
    return h


@g32("CreateDCA", 4)
def create_dc(m, a):
    h, d = new_dc(m, "memory")
    d.bitmap = Bitmap("ddb", SCREEN_W, SCREEN_H, 8)
    return h


@g32("CreateCompatibleBitmap", 3)
def create_compat_bitmap(m, a):
    return new_obj(m, Bitmap("ddb", max(a[1], 1), max(a[2], 1), 8))


@g32("CreateBitmap", 5)
def create_bitmap(m, a):
    w, h = max(a[0], 1), max(a[1], 1)
    b = Bitmap("ddb", w, h, a[3] or 1)
    if (a[2] or 1) * (a[3] or 1) == 1:
        b.mono = np.zeros((h, w), bool)
        if a[4]:                                                  # scan lines are padded to 16 bits, most significant bit first
            stride = ((w + 15) // 16) * 2
            raw = np.frombuffer(m.rd(a[4], stride * h), np.uint8).reshape(h, stride)
            b.mono = np.unpackbits(raw, axis=1)[:, :w].astype(bool)
    return new_obj(m, b)


def color_index(m, dc, c):
    """The system-palette index a COLORREF stands for on this DC (a palette index as itself, an RGB value as its nearest entry)."""
    if (c >> 24) & 0xFF == 1:
        return c & 0xFF
    return int(quantize(m, np.array([[colorref(m, dc, c)]], np.uint8))[0, 0])


def mono_indices(m, dst, b, x0, y0, x1, y1):
    """A 1-bpp bitmap's rectangle as indices, the way Windows converts one for a colour destination: 0 bits take the
    destination DC's text colour and 1 bits its background colour."""
    bit = b.mono[y0:y1, x0:x1]
    return np.where(bit, np.uint8(color_index(m, dst, dst.bkcolor)), np.uint8(color_index(m, dst, dst.textcolor)))


g32("SetBitmapDimensionEx", 4)(lambda m, a: 1)


@g32("CreateDIBSection", 6)
def create_dib_section(m, a):
    w, h, topdown, bpp, pal, _ = parse_bitmapinfo(m, a[1], a[2])
    b = Bitmap("dib", w, h, bpp)
    b.topdown = topdown
    if isinstance(pal, tuple):                                        # DIB_PAL_COLORS
        b.idxmap = idx_lut(pal[1]) if pal[1] else np.arange(256, dtype=np.uint8)
        dc = dc_of(m, a[0])
        b.palette = list(dc.palette) if dc and dc.palette else b.palette
    elif pal:
        b.palette = pal
    b.bits = m.alloc(b.stride * h)
    if a[3]:
        m.w32(a[3], b.bits)
    return new_obj(m, b)


@g32("SetDIBColorTable", 4)
def set_dib_color_table(m, a):
    dc = dc_of(m, a[0])
    b = dc.bitmap if dc else None
    if not b or b.kind != "dib":
        return 0
    for i in range(a[2]):
        bb, gg, rr, _ = m.rd(a[3] + 4 * i, 4)
        b.palette[(a[1] + i) % 256] = (rr, gg, bb)
    return a[2]


@g32("SetDIBits", 7)
def set_dibits(m, a):
    dc, bmp = dc_of(m, a[0]), obj(m, a[1])
    w, h, topdown, bpp, pal, hdr = parse_bitmapinfo(m, a[6])
    if not isinstance(bmp, Bitmap):
        return 0
    stride = ((w * bpp + 31) // 32) * 4
    raw = np.frombuffer(m.rd(a[4], stride * a[3]), np.uint8).reshape(a[3], stride)
    if bpp == 8:
        lut = np.array((pal or [(i, i, i) for i in range(256)]) + [(0, 0, 0)] * 256, np.uint8)[:256]
        rgb = lut[raw[:, :w]]
    elif bpp == 24:
        rgb = raw[:, :w * 3].reshape(a[3], w, 3)[:, :, ::-1]
    else:
        return 0
    if not topdown:
        rgb = rgb[::-1]
    y0 = a[2] if topdown else max(h - a[2] - a[3], 0)
    if bmp.kind == "ddb":
        hh = min(rgb.shape[0], bmp.h - y0)
        bmp.idx[y0:y0 + hh, :min(w, bmp.w)] = quantize(m, np.ascontiguousarray(rgb[:hh, :min(w, bmp.w)]))
    else:
        write_dib_rgb(m, bmp, 0, y0, np.ascontiguousarray(rgb))
    return a[3]


def _dib_strip_rows(topdown, dib_h, start, lines, sy, cy, ydest):
    """Which of the supplied scan lines land where. Line k of the buffer is DIB row `start + k`; the source
    rectangle is rows [sy, sy + cy) counted from the bottom (bottom-up DIB) or the top (top-down DIB).
    Returns [(k, dest_y)]."""
    out = []
    for k in range(lines):
        r = start + k
        if sy <= r < sy + cy:
            out.append((k, ydest + ((r - sy) if topdown else (sy + cy - 1 - r))))
    return out


@g32("SetDIBitsToDevice", 12)
def set_dibits_to_device(m, a):
    dc = dc_of(m, a[0])
    hdc, x, y, cx, cy, sx, sy, start, lines, bits, bmi, usage = a
    x, y, cx, cy, sx, sy = map(_s32, (x, y, cx, cy, sx, sy))
    w, h, topdown, bpp, pal, hdr = parse_bitmapinfo(m, bmi, usage)
    stride = ((w * bpp + 31) // 32) * 4
    raw = np.frombuffer(m.rd(bits, stride * lines), np.uint8).reshape(lines, stride)
    placed = _dib_strip_rows(topdown, h, start, lines, sy, cy, y)
    if not placed:
        return 0
    if bpp == 8 and isinstance(pal, tuple):                              # DIB_PAL_COLORS: indices, not colours
        lut = idx_lut(pal[1]) if pal[1] else np.arange(256, dtype=np.uint8)
        for k, dy in placed:
            row = lut[raw[k, sx:sx + cx]]
            if dc.kind == "window":
                put_indices(m, dc, x + dc.org[0], dy + dc.org[1], row[None, :])
            elif dc.bitmap is not None and dc.bitmap.kind == "dib" and dc.bitmap.bpp == 8:
                write_dib_indices(m, dc.bitmap, x + dc.org[0], dy + dc.org[1], np.ascontiguousarray(row[None, :]))
            else:
                put_indices(m, dc, x + dc.org[0], dy + dc.org[1], np.ascontiguousarray(row[None, :]))
        return lines
    if bpp == 8:
        pal = pal or [(i, i, i) for i in range(256)]
        if dc.kind == "window":
            lut = dib_to_system_lut(m, pal)
        elif dc.bitmap is not None and dc.bitmap.kind == "dib" and dc.bitmap.bpp == 8 and dc.bitmap.palette != pal:
            lut = dib_to_dib_lut(pal, dc.bitmap.palette)
        else:
            lut = None
        for k, dy in placed:
            row = raw[k, sx:sx + cx]
            if dc.kind == "window":
                put_indices(m, dc, x + dc.org[0], dy + dc.org[1], lut[row][None, :])
            elif dc.bitmap is not None and dc.bitmap.kind == "dib" and dc.bitmap.bpp == 8:
                write_dib_indices(m, dc.bitmap, x + dc.org[0], dy + dc.org[1],
                                  np.ascontiguousarray((lut[row] if lut is not None else row)[None, :]))
            else:
                put_indices(m, dc, x + dc.org[0], dy + dc.org[1],
                            np.ascontiguousarray(dib_to_system_lut(m, pal)[row][None, :]))
        return lines
    if bpp == 24:
        for k, dy in placed:
            rgb = raw[k, sx * 3:(sx + cx) * 3].reshape(1, -1, 3)[:, :, ::-1]
            put_region(m, dc, x + dc.org[0], dy + dc.org[1], np.ascontiguousarray(rgb))
        return lines
    return 0


@g32("GetObjectA", 3)
def get_object(m, a):
    """GetObject(handle, cbBuffer, lpvObject): fills a BITMAP (24 bytes) for bitmaps, a LOGFONT for fonts."""
    o = obj(m, a[0])
    if isinstance(o, Bitmap):
        if a[1] < 24 or not a[2]:
            return 24
        m.wr(a[2], struct.pack("<IIIIHHI", 0, o.w, o.h, o.stride if o.kind == "dib" else ((o.w * 8 + 31) // 32) * 4,
                               1, o.bpp, o.bits))
        return 24
    return 0


# ---- state ---------------------------------------------------------------------------------------------------
def _dc_setter(name, attr, argc=2):
    def f(m, a):
        dc = dc_of(m, a[0])
        if not dc:
            return 0
        old = getattr(dc, attr)
        setattr(dc, attr, a[1])
        return old
    g32(name, argc)(f)


_dc_setter("SetTextColor", "textcolor")
_dc_setter("SetBkColor", "bkcolor")
_dc_setter("SetBkMode", "bkmode")
_dc_setter("SetTextAlign", "textalign")
g32("GetTextAlign", 1)(lambda m, a: (dc_of(m, a[0]).textalign if dc_of(m, a[0]) else 0))
g32("SetROP2", 2)(lambda m, a: 13)
def _rescale(dc):
    """MM_ISOTROPIC and MM_ANISOTROPIC scale logical units by viewport extent / window extent; every other mode is 1:1 here."""
    if dc.mm in (7, 8) and dc.wext[0] and dc.wext[1]:
        dc.sx, dc.sy = dc.vext[0] / dc.wext[0], dc.vext[1] / dc.wext[1]
        if dc.mm == 7:                                           # isotropic: one scale for both axes (the smaller, as Windows fits it)
            dc.sx = dc.sy = min(abs(dc.sx), abs(dc.sy))
    else:
        dc.sx = dc.sy = 1.0
    if dc.sx == 0 or dc.sy == 0:                                 # an extent not set yet (the game sets the two in separate calls)
        dc.sx, dc.sy = dc.sx or 1.0, dc.sy or 1.0


@g32("SetMapMode", 2)
def set_map_mode(m, a):
    dc = dc_of(m, a[0])
    if not dc:
        return 0
    old = dc.mm
    dc.mm = a[1]
    if a[1] not in (7, 8):
        dc.wext = dc.vext = (1, 1)
    _rescale(dc)
    return old


@g32("GetMapMode", 1)
def get_map_mode(m, a):
    dc = dc_of(m, a[0])
    return dc.mm if dc else 0


def _ext_setter(attr):
    def fn(m, a):
        dc = dc_of(m, a[0])
        if not dc:
            return 0
        if a[3]:
            m.w32(a[3], getattr(dc, attr)[0])
            m.w32(a[3] + 4, getattr(dc, attr)[1])
        if dc.mm in (7, 8):
            setattr(dc, attr, (_s32(a[1]), _s32(a[2])))
            _rescale(dc)
        return 1
    return fn


g32("SetWindowExtEx", 4)(_ext_setter("wext"))
g32("SetViewportExtEx", 4)(_ext_setter("vext"))


@g32("SetWindowOrgEx", 4)
def set_window_org(m, a):
    dc = dc_of(m, a[0])
    if not dc:
        return 0
    if a[3]:
        m.w32(a[3], dc.wo[0])
        m.w32(a[3] + 4, dc.wo[1])
    dc.wo = (_s32(a[1]), _s32(a[2]))
    return 1


def lx(dc, x):
    """Device x (relative to the viewport origin) of a logical x."""
    return int(round((x - dc.wo[0]) * dc.sx))


def ly(dc, y):
    return int(round((y - dc.wo[1]) * dc.sy))


def dev_rect(dc, x, y, w, h):
    """(x, y, w, h) of a logical rectangle in device units, relative to the viewport origin."""
    x0, y0 = lx(dc, x), ly(dc, y)
    return x0, y0, lx(dc, x + w) - x0, ly(dc, y + h) - y0


def _points_converter(to_device):
    def fn(m, a):
        dc = dc_of(m, a[0])
        if not dc:
            return 0
        for i in range(a[2]):
            x, y = struct.unpack("<ii", m.rd(a[1] + 8 * i, 8))
            if to_device:
                x, y = lx(dc, x) + dc.org[0], ly(dc, y) + dc.org[1]
            else:
                x, y = int(round((x - dc.org[0]) / dc.sx)) + dc.wo[0], int(round((y - dc.org[1]) / dc.sy)) + dc.wo[1]
            m.wr(a[1] + 8 * i, struct.pack("<ii", x, y))
        return 1
    return fn


g32("LPtoDP", 3)(_points_converter(True))
g32("DPtoLP", 3)(_points_converter(False))
g32("SetStretchBltMode", 2)(lambda m, a: 1)
g32("GdiFlush", 0)(lambda m, a: 1)
g32("GdiGetBatchLimit", 0)(lambda m, a: 1)
g32("GdiSetBatchLimit", 1)(lambda m, a: 1)
_DC_STATE = ("bitmap", "palette", "textcolor", "bkcolor", "bkmode", "pen", "brush", "font", "org", "wo", "wext", "vext", "sx", "sy", "mm", "pos", "clip", "textalign")


@g32("SaveDC", 1)
def save_dc(m, a):
    """Push the DC's attributes (selected objects, colours, origin, clip region) and return the new level."""
    dc = dc_of(m, a[0])
    if not dc:
        return 0
    dc.__dict__.setdefault("saved", []).append({k: getattr(dc, k) for k in _DC_STATE})
    return len(dc.saved)


@g32("RestoreDC", 2)
def restore_dc(m, a):
    """Pop saved states: level -1 is the last one saved, a positive level is that one (and every later one is dropped)."""
    dc = dc_of(m, a[0])
    stack = dc.__dict__.get("saved") if dc else None
    n = _s32(a[1])
    level = n if n > 0 else len(stack or ()) + n + 1
    if not stack or not 1 <= level <= len(stack):
        return 0
    for k, v in stack[level - 1].items():
        setattr(dc, k, v)
    del stack[level - 1:]
    return 1


@g32("SetViewportOrgEx", 4)
def set_viewport_org(m, a):
    dc = dc_of(m, a[0])
    if dc:
        if a[3]:
            m.w32(a[3], dc.org[0])
            m.w32(a[3] + 4, dc.org[1])
        dc.org = (struct.unpack("<i", struct.pack("<I", a[1]))[0], struct.unpack("<i", struct.pack("<I", a[2]))[0])
    return 1


@g32("OffsetViewportOrgEx", 4)
def offset_viewport_org(m, a):
    dc = dc_of(m, a[0])
    if dc:
        dc.org = (dc.org[0] + struct.unpack("<i", struct.pack("<I", a[1]))[0],
                  dc.org[1] + struct.unpack("<i", struct.pack("<I", a[2]))[0])
    return 1


@g32("SelectClipRgn", 2)
def select_clip_rgn(m, a):
    dc, r = dc_of(m, a[0]), obj(m, a[1])
    if dc:
        dc.clip = tuple(r[1]) if isinstance(r, tuple) and r and r[0] == "region" else None
    return 2


@g32("IntersectClipRect", 5)
def intersect_clip_rect(m, a):
    dc = dc_of(m, a[0])
    if dc:
        x0, y0, x1, y1 = [struct.unpack("<i", struct.pack("<I", v))[0] for v in a[1:5]]
        x0, y0, x1, y1 = lx(dc, x0) + dc.org[0], ly(dc, y0) + dc.org[1], lx(dc, x1) + dc.org[0], ly(dc, y1) + dc.org[1]
        if dc.clip:
            x0, y0, x1, y1 = max(x0, dc.clip[0]), max(y0, dc.clip[1]), min(x1, dc.clip[2]), min(y1, dc.clip[3])
        dc.clip = (x0, y0, max(x1, x0), max(y1, y0))
    return 2


@g32("CreateRectRgn", 4)
def create_rect_rgn(m, a):
    return new_obj(m, ("region", [struct.unpack("<i", struct.pack("<I", v))[0] for v in a[:4]]))      # a list: SetRectRgn changes it


@g32("SetRectRgn", 5)
def set_rect_rgn(m, a):
    r = obj(m, a[0])
    if isinstance(r, tuple) and r and r[0] == "region" and isinstance(r[1], list):
        r[1][:] = [struct.unpack("<i", struct.pack("<I", v))[0] for v in a[1:5]]
        return 1
    return 0


@g32("CreateRectRgnIndirect", 1)
def create_rect_rgn_indirect(m, a):
    return new_obj(m, ("region", struct.unpack("<iiii", m.rd(a[0], 16))))


@g32("CreatePolygonRgn", 3)
def create_polygon_rgn(m, a):
    pts = [struct.unpack("<ii", m.rd(a[0] + 8 * i, 8)) for i in range(a[1])]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return new_obj(m, ("region", (min(xs), min(ys), max(xs), max(ys))))


@g32("GetDeviceCaps", 2)
def get_device_caps(m, a):
    return {8: SCREEN_W, 10: SCREEN_H, 12: 8, 14: 1, 24: 20, 26: 0, 38: 0x7E99 | 0x100, 88: 96, 90: 96, 104: 256,
            106: 20, 4: 0, 6: 0, 2: 1, 0: 0x0400}.get(a[1], 0)


# ---- drawing -----------------------------------------------------------------------------------------------
def _rop_fill(m, dc, x, y, w, h, color):
    put_region(m, dc, x + dc.org[0], y + dc.org[1], np.full((max(h, 0), max(w, 0), 3), color, np.uint8))


def _s32(v):
    return struct.unpack("<i", struct.pack("<I", v))[0]


def blit_indices(m, dst, x, y, w, h, src, sx, sy, sw, sh):
    """Index-preserving copy between windows, device bitmaps and 8-bit DIB sections, with optional
    nearest-neighbour stretch. Returns False when the source cannot be read as indices (caller falls back to RGB)."""
    if w == 0 or h == 0 or sw == 0 or sh == 0:
        return True
    ax0, ay0 = sx + src.org[0], sy + src.org[1]
    ax1, ay1 = ax0 + abs(sw), ay0 + abs(sh)
    cx0, cy0, idx = dc_indices(m, src, ax0, ay0, ax1, ay1, mono_dc=dst)
    if idx is None:
        return False
    if idx.size == 0:
        return True
    if (abs(w), abs(h)) != (abs(sw), abs(sh)):                 # stretch: sample the source nearest-neighbour
        ys = np.minimum(np.arange(abs(h)) * abs(sh) // abs(h), abs(sh) - 1)
        xs = np.minimum(np.arange(abs(w)) * abs(sw) // abs(w), abs(sw) - 1)
        full = np.zeros((abs(sh), abs(sw)), np.uint8)
        full[cy0 - ay0:cy0 - ay0 + idx.shape[0], cx0 - ax0:cx0 - ax0 + idx.shape[1]] = idx
        idx, ox, oy = full[ys][:, xs], x, y
    else:
        ox, oy = x + (cx0 - ax0), y + (cy0 - ay0)
    db = dst.bitmap if dst.kind == "memory" else None
    if db is not None and db.kind == "dib" and db.bpp in (24, 32):
        # indices into a direct-colour bitmap: colours come from the source DC's logical palette (else the
        # system palette), as Windows resolves them when it copies to a device-independent bitmap
        sb = src.bitmap if src.kind == "memory" else None
        if sb is not None and sb.kind == "dib" and sb.bpp == 8 and sb.idxmap is not None:
            # a DIB_PAL_COLORS section: its colour table is a snapshot of the palette when it was created;
            # the pixel's value goes through the index map to a logical entry of that snapshot
            table = sb.palette
            lut = np.array(list(table) + [(0, 0, 0)] * (256 - len(table)), np.uint8)[:256]
            rgb = lut[idx]                                  # idx is already the logical palette index
        else:
            pal = src.palette if src.palette else _st(m)["system_palette"]
            lut = np.array(list(pal) + [(0, 0, 0)] * (256 - len(pal)), np.uint8)[:256]
            rgb = lut[idx]
        write_dib_rgb(m, db, ox + dst.org[0], oy + dst.org[1], np.ascontiguousarray(rgb))
        return True
    put_indices(m, dst, ox + dst.org[0], oy + dst.org[1], np.ascontiguousarray(idx))
    return True


def dib_to_dib_lut(src_pal, dst_pal):
    d = np.array(list(dst_pal) + [(0, 0, 0)] * (256 - len(dst_pal)), np.int32)[:256]
    t = np.array(list(src_pal) + [(0, 0, 0)] * (256 - len(src_pal)), np.int32)[:256]
    out = np.empty(256, np.uint8)
    for i in range(256):
        out[i] = i if (t[i] == d[i]).all() else int(np.argmin(((d - t[i]) ** 2).sum(1)))
    return out


# Raster operations that combine the source with what is already there (the game draws its bitmap-font glyphs as an AND with
# a mask and then an OR with the glyph, so that the glyph's black background stays out of the picture).
_ROPS = {0x8800C6: lambda s, d: s & d,                 # SRCAND
         0xEE0086: lambda s, d: s | d,                 # SRCPAINT
         0x660046: lambda s, d: s ^ d,                 # SRCINVERT
         0x440328: lambda s, d: s & ~d,                # SRCERASE
         0x330008: lambda s, d: ~s,                    # NOTSRCCOPY
         0x1100A6: lambda s, d: ~(s | d),              # NOTSRCERASE
         0xBB0226: lambda s, d: ~s | d}                # MERGEPAINT


def _nearest(arr, w, h):
    """An (h0, w0[, 3]) array stretched to (h, w) by nearest neighbour; negative sizes flip."""
    h0, w0 = arr.shape[:2]
    ys = np.minimum((np.arange(abs(h)) * h0) // max(abs(h), 1), h0 - 1)
    xs = np.minimum((np.arange(abs(w)) * w0) // max(abs(w), 1), w0 - 1)
    out = arr[ys][:, xs]
    return out[::-1] if h < 0 else out


def _rop_blit(m, dst, x, y, w, h, src, sx, sy, sw, sh, rop):
    """Blit with a combining raster operation (device units, relative to the viewport origins): on palette indices when both sides
    are readable as indices (what an 8-bit display does) and on colours otherwise. The source is stretched to the destination."""
    f = _ROPS[rop]
    if w == 0 or h == 0 or sw == 0 or sh == 0:
        return 1
    X, Y = x + dst.org[0], y + dst.org[1]
    _, _, si = dc_indices(m, src, sx + src.org[0], sy + src.org[1], sx + src.org[0] + abs(sw), sy + src.org[1] + abs(sh), mono_dc=dst)
    _, _, di = dc_indices(m, dst, X, Y, X + abs(w), Y + abs(h))
    if si is not None and di is not None and si.size and si.shape == (abs(sh), abs(sw)) and di.shape == (abs(h), abs(w)):
        si = _nearest(si, w, h) if (abs(sw), abs(sh)) != (abs(w), abs(h)) else si
        put_indices(m, dst, X, Y, np.ascontiguousarray(f(si, di).astype(np.uint8)))
        return 1
    sp = get_region(m, src, sx + src.org[0], sy + src.org[1], sx + src.org[0] + abs(sw), sy + src.org[1] + abs(sh))
    dp = get_region(m, dst, X, Y, X + abs(w), Y + abs(h))
    if sp is None or dp is None:
        return 1
    if sp.shape[:2] != dp.shape[:2]:
        sp = _nearest(sp, w, h)
    if sp.shape != dp.shape:
        return 1
    put_region(m, dst, X, Y, np.ascontiguousarray(f(sp, dp).astype(np.uint8)))
    return 1


def _blit(m, dst, src, x, y, w, h, sx, sy, sw, sh, rop):
    """BitBlt / StretchBlt in logical units: the destination rectangle is mapped by the destination DC, the source rectangle by the
    source DC (so a DC with a scaled mapping stretches), then copied or combined with the raster operation."""
    X, Y, W, H = dev_rect(dst, x, y, w, h)
    if rop == 0x000042:
        _rop_fill(m, dst, X, Y, W, H, (0, 0, 0))
        return 1
    if rop == 0xFF0062:
        _rop_fill(m, dst, X, Y, W, H, (255, 255, 255))
        return 1
    if rop == 0xF00021:
        return _pattern_fill(m, dst, X, Y, W, H)
    if not src:
        return 0
    SX, SY, SW, SH = dev_rect(src, sx, sy, sw, sh)
    if rop in _ROPS:
        return _rop_blit(m, dst, X, Y, W, H, src, SX, SY, SW, SH, rop)
    if rop != 0xCC0020:
        _st(m).setdefault("odd_rops", set()).add(rop)
    shrinking = abs(W) < abs(SW) or abs(H) < abs(SH)
    if not shrinking and blit_indices(m, dst, X, Y, W, H, src, SX, SY, SW, SH):
        return 1
    px = get_region(m, src, SX + src.org[0], SY + src.org[1], SX + src.org[0] + abs(SW), SY + src.org[1] + abs(SH))
    if px is None or W == 0 or H == 0:
        return 1
    if px.shape[:2] != (abs(H), abs(W)):
        if shrinking and px.shape[0] and px.shape[1]:
            # The game asks for HALFTONE stretching (SetStretchBltMode 3): shrinking averages the source pixels. Picking one of them
            # (nearest) turns a dithered area, such as a card's parchment, into noise.
            img = Image.fromarray(px).resize((abs(W), abs(H)), Image.BOX)
            px = np.asarray(img)
            if W < 0 or H < 0:
                px = px[::-1 if H < 0 else 1, ::-1 if W < 0 else 1]
        else:
            px = _nearest(px, W, H)
    put_region(m, dst, X + dst.org[0], Y + dst.org[1], np.ascontiguousarray(px))
    return 1


@g32("BitBlt", 9)
def bitblt(m, a):
    hdst, x, y, w, h, hsrc, sx, sy, rop = a
    dst, src = dc_of(m, hdst), dc_of(m, hsrc)
    x, y, w, h, sx, sy = map(_s32, (x, y, w, h, sx, sy))
    if not dst:
        return 0
    return _blit(m, dst, src, x, y, w, h, sx, sy, w, h, rop)


@g32("StretchBlt", 11)
def stretchblt(m, a):
    hdst, x, y, w, h, hsrc, sx, sy, sw, sh, rop = a
    dst, src = dc_of(m, hdst), dc_of(m, hsrc)
    x, y, w, h, sx, sy, sw, sh = map(_s32, (x, y, w, h, sx, sy, sw, sh))
    if not dst:
        return 0
    return _blit(m, dst, src, x, y, w, h, sx, sy, sw, sh, rop)


def _pattern_fill(m, dc, x, y, w, h):
    b = dc.brush
    if b[1] is not None:
        _rop_fill(m, dc, x, y, w, h, b[1])
    return 1


def fill_rect(m, dc, x0, y0, x1, y1, color):
    """Fill the logical rectangle (x0, y0)-(x1, y1) with a colour."""
    X, Y, W, H = dev_rect(dc, x0, y0, x1 - x0, y1 - y0)
    put_region(m, dc, X + dc.org[0], Y + dc.org[1], np.full((max(H, 0), max(W, 0), 3), color, np.uint8))


def _draw(m, dc, x0, y0, x1, y1, painter):
    """Draw onto a rectangle of the target with PIL and write it back."""
    w, h = target_size(m, dc)
    x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, w), min(y1, h)
    px = get_region(m, dc, x0, y0, x1, y1)
    if px is None:
        return
    img = Image.fromarray(px)
    painter(ImageDraw.Draw(img), x0, y0)
    put_region(m, dc, x0, y0, np.asarray(img))


def _dev_box(dc, a):
    """The (left, top, right, bottom) of a shape call's logical arguments a[1:5] as device pixels."""
    l, t, r, b = map(_s32, a[1:5])
    x0, x1 = sorted((lx(dc, l) + dc.org[0], lx(dc, r) + dc.org[0]))
    y0, y1 = sorted((ly(dc, t) + dc.org[1], ly(dc, b) + dc.org[1]))
    return x0, y0, x1, y1


@g32("Rectangle", 5)
def rectangle(m, a):
    dc = dc_of(m, a[0])
    x0, y0, x1, y1 = _dev_box(dc, a)
    fill, pen = dc.brush[1], dc.pen[1]
    _draw(m, dc, x0, y0, x1 + 1, y1 + 1, lambda d, ox, oy: d.rectangle([x0 - ox, y0 - oy, max(x1 - 1, x0) - ox, max(y1 - 1, y0) - oy],
                                                                        fill=tuple(fill) if fill else None,
                                                                        outline=tuple(pen) if pen else None))
    return 1


@g32("RoundRect", 7)
def roundrect(m, a):
    dc = dc_of(m, a[0])
    x0, y0, x1, y1 = _dev_box(dc, a)
    fill, pen = dc.brush[1], dc.pen[1]
    _draw(m, dc, x0, y0, x1 + 1, y1 + 1, lambda d, ox, oy: d.rounded_rectangle(
        [x0 - ox, y0 - oy, max(x1 - 1, x0) - ox, max(y1 - 1, y0) - oy], radius=max(int(min(a[5], a[6]) * dc.sx) // 2, 1),
        fill=tuple(fill) if fill else None, outline=tuple(pen) if pen else None))
    return 1


@g32("Ellipse", 5)
def ellipse(m, a):
    dc = dc_of(m, a[0])
    x0, y0, x1, y1 = _dev_box(dc, a)
    fill, pen = dc.brush[1], dc.pen[1]
    _draw(m, dc, x0, y0, x1 + 1, y1 + 1, lambda d, ox, oy: d.ellipse([x0 - ox, y0 - oy, max(x1 - 1, x0) - ox, max(y1 - 1, y0) - oy],
                                                                       fill=tuple(fill) if fill else None,
                                                                       outline=tuple(pen) if pen else None))
    return 1


@g32("MoveToEx", 4)
def move_to(m, a):
    dc = dc_of(m, a[0])
    if a[3]:
        m.w32(a[3], dc.pos[0])
        m.w32(a[3] + 4, dc.pos[1])
    dc.pos = (_s32(a[1]), _s32(a[2]))
    return 1


@g32("LineTo", 3)
def line_to(m, a):
    dc = dc_of(m, a[0])
    (x0, y0), (x1, y1) = dc.pos, (_s32(a[1]), _s32(a[2]))
    dc.pos = (x1, y1)
    pen = dc.pen[1]
    if pen:
        ox, oy = dc.org
        x0, y0, x1, y1 = lx(dc, x0), ly(dc, y0), lx(dc, x1), ly(dc, y1)
        _draw(m, dc, min(x0, x1) + ox, min(y0, y1) + oy, max(x0, x1) + ox + 1, max(y0, y1) + oy + 1,
              lambda d, px, py: d.line([x0 + ox - px, y0 + oy - py, x1 + ox - px, y1 + oy - py], fill=tuple(pen),
                                       width=dc.pen[2] if len(dc.pen) > 2 else 1))
    return 1


@g32("SetPixel", 4)
def set_pixel(m, a):
    dc = dc_of(m, a[0])
    x, y = lx(dc, _s32(a[1])) + dc.org[0], ly(dc, _s32(a[2])) + dc.org[1]
    c = a[3]
    if (c >> 24) & 0xFF == 0x01:                                       # PALETTEINDEX: the index itself
        if dc.kind == "window":
            put_indices(m, dc, x, y, np.array([[c & 0xFF]], np.uint8))
            return c
        if dc.bitmap is not None and dc.bitmap.kind == "dib" and dc.bitmap.bpp == 8:
            write_dib_indices(m, dc.bitmap, x, y, np.array([[c & 0xFF]], np.uint8))
            return c
    put_region(m, dc, x, y, np.array([[colorref(m, dc, c)]], np.uint8))
    return c


g32("SetPixelV", 4)(lambda m, a: set_pixel(m, a) and 1)


@g32("GetPixel", 3)
def get_pixel(m, a):
    dc = dc_of(m, a[0])
    gx, gy = lx(dc, _s32(a[1])) + dc.org[0], ly(dc, _s32(a[2])) + dc.org[1]
    px = get_region(m, dc, gx, gy, gx + 1, gy + 1)
    if px is None:
        return 0xFFFFFFFF
    r, g, b = px[0, 0]
    return int(r) | (int(g) << 8) | (int(b) << 16)


# ---- text ----------------------------------------------------------------------------------------------------
def _game_font_path(st, face, weight, italic):
    """The host path of the game's own font file for `face` (the style closest to the request), or None."""
    styles = st.get("game_fonts", {}).get(_family_key(face))
    if not styles:
        return None
    want = ("bold italic" if weight >= 600 and italic else "bold" if weight >= 600 else "italic" if italic else "regular")
    for cand in (want, "regular", "bold", "italic"):
        if cand in styles:
            return styles[cand]
    return next(iter(styles.values()))


def _pil_font(m, font, scale=1.0):
    st = _st(m)
    face, size, weight = (font[1], font[2], font[3]) if font else ("Arial", 13, 400)
    italic = bool(font[4]) if font and len(font) > 4 else False
    height = font[5] if font and len(font) > 5 else size                # signed: negative is the em height, positive the cell height
    size = size * scale
    key = (face, round(size, 2), weight >= 600, italic, height < 0)
    if key not in st["font_cache"] and os.environ.get("FONTDBG"):
        m.log(f"   [font] {face!r} height {height} weight {weight} italic {italic} scale {scale:.2f} -> {_game_font_path(st, face, weight, italic)}")
    if key not in st["font_cache"]:
        f = None
        own = _game_font_path(st, face, weight, italic)
        if own:
            try:
                probe = ImageFont.truetype(own, 100)
                ascent, descent = probe.getmetrics()
                em = size if height < 0 else size * 100.0 / (ascent + descent)
                f = ImageFont.truetype(own, max(em, 2))
            except OSError:
                f = None
        for path in () if f else ("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if weight >= 600 else
                     "/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc",
                     "/Library/Fonts/Arial.ttf"):
            try:
                f = ImageFont.truetype(path, max(int(size * 0.75), 6))
                break
            except OSError:
                continue
        st["font_cache"][key] = f or ImageFont.load_default()
    return st["font_cache"][key]


def text_size(m, dc, s):
    """(width, height) of `s` in the DC's logical units. The font is realized at its height scaled by the mapping's vertical scale (a
    20-unit font on a DC that maps 24 logical units to 13 pixels is 11 pixels high), and its width follows from that: so the logical
    width is the realized device width divided by the horizontal scale, not the width of the unscaled font."""
    f = _pil_font(m, dc.font, dc.sy)
    if not s:
        return 0, dc.font[2] if dc.font else 13
    return int(f.getlength(s.decode("latin-1")) / dc.sx), int(dc.font[2]) if dc.font else 13


def draw_text(m, dc, x, y, s, align=True):
    """Draw `s` with its reference point at logical (x, y); `align`: honour the DC's text alignment (TextOut does, DrawText does not)."""
    if not s:
        return
    f = _pil_font(m, dc.font, dc.sy)                  # the font height is in logical units: scaled like everything else
    tw, th = text_size(m, dc, s)
    tw, th = int(tw * dc.sx), int(th * dc.sy)                    # back to device pixels
    fg = colorref(m, dc, dc.textcolor)
    ox, oy = dc.org
    x0, y0 = lx(dc, x) + ox, ly(dc, y) + oy
    if align and dc.textalign & 6 == 6:
        x0 -= tw // 2
    elif align and dc.textalign & 6 == 2:
        x0 -= tw
    if align and dc.textalign & 24 == 8:
        y0 -= th
    if dc.kind == "window" and dc.hwnd:                          # what the game wrote on a window, for a script that reads the screen (live_drive's autopilot)
        win = m.state.get("u32", {}).get("windows", {}).get(dc.hwnd)
        if win is not None:
            win.setdefault("texts", {})[(x0, y0)] = (s.decode("latin-1"), tuple(int(c) for c in fg))
    def paint(d, px, py):
        if dc.bkmode == 2:
            d.rectangle([x0 - px, y0 - py, x0 + tw - px, y0 + th - py], fill=tuple(colorref(m, dc, dc.bkcolor)))
        d.text((x0 - px, y0 - py), s.decode("latin-1"), font=f, fill=tuple(fg))
    _draw(m, dc, x0, y0, x0 + tw + 1, y0 + th + 1, paint)


@g32("TextOutA", 5)
def text_out(m, a):
    dc = dc_of(m, a[0])
    if dc:
        draw_text(m, dc, _s32(a[1]), _s32(a[2]), m.rd(a[3], a[4]))
    return 1


@g32("GetTextExtentPointA", 4)
def get_text_extent(m, a):
    dc = dc_of(m, a[0])
    w, h = text_size(m, dc, m.rd(a[1], a[2])) if dc else (0, 0)
    m.w32(a[3], w)
    m.w32(a[3] + 4, h)
    return 1


g32("GetTextExtentPoint32A", 4)(lambda m, a: get_text_extent(m, a))


@g32("GetTextMetricsA", 2)
def get_text_metrics(m, a):
    dc = dc_of(m, a[0])
    h = dc.font[2] if dc and dc.font else 13
    f = _pil_font(m, dc.font if dc else None)
    avg = int(f.getlength("x"))
    vals = [h, h * 4 // 5, h - h * 4 // 5, 0, 0, avg, avg * 2, 400, 0, 96, 96]
    m.wr(a[1], struct.pack("<11i", *vals) + bytes([32, 255, 63, 32, 0, 0, 0, 0x22, 0]) + b"\0" * 3)
    return 1


@g32("GetCharWidthA", 4)
def get_char_width(m, a):
    dc = dc_of(m, a[0])
    for i, c in enumerate(range(a[1], a[2] + 1)):
        m.w32(a[3] + 4 * i, text_size(m, dc, bytes([c]))[0])
    return 1


@g32("GetCharABCWidthsA", 4)
def get_char_abc_widths(m, a):
    dc = dc_of(m, a[0])
    for i, c in enumerate(range(a[1], a[2] + 1)):
        m.wr(a[3] + 12 * i, struct.pack("<iII", 0, text_size(m, dc, bytes([c]))[0], 0))
    return 1

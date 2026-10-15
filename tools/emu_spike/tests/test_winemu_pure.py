"""Tests for the parts of the Win32 host that need no emulator: printf/scanf formatting and path mapping."""
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from winemu.cformat import VaReader, format_c, scan_c            # noqa: E402
from winemu.paths import host_path, normalize                     # noqa: E402


class FakeMem:
    """Just enough of Machine for the formatters: byte memory, cstr and put_cstr."""
    def __init__(self):
        self.mem = bytearray(4096)

    def rd(self, a, n):
        return bytes(self.mem[a:a + n])

    def wr(self, a, b):
        self.mem[a:a + len(b)] = b

    def r32(self, a):
        return struct.unpack("<I", self.rd(a, 4))[0]

    def cstr(self, a, limit=4096):
        e = self.mem.index(0, a)
        return bytes(self.mem[a:e])

    def put_cstr(self, a, b):
        self.wr(a, bytes(b) + b"\0")


def varargs(m, base, *vals):
    for i, v in enumerate(vals):
        if isinstance(v, float):
            m.wr(base, struct.pack("<d", v))
            base += 8
        else:
            m.wr(base, struct.pack("<I", v & 0xFFFFFFFF))
            base += 4


class FormatTests(unittest.TestCase):
    def setUp(self):
        self.m = FakeMem()

    def fmt(self, f, *args):
        varargs(self.m, 2000, *args)
        return format_c(self.m, f, VaReader(self.m, 2000))

    def test_integers(self):
        self.assertEqual(self.fmt(b"%d|%5d|%-5d|%05d", 5, 42, 42, 42), b"5|   42|42   |00042")
        self.assertEqual(self.fmt(b"%d", 0xFFFFFFFF), b"-1")
        self.assertEqual(self.fmt(b"%u %x %X", 0xFFFFFFFF, 255, 255), b"4294967295 ff FF")

    def test_strings_and_chars(self):
        self.m.put_cstr(100, b"hello")
        self.assertEqual(self.fmt(b"[%s][%8s][%.3s][%c]", 100, 100, 100, ord("z")), b"[hello][   hello][hel][z]")

    def test_float_and_percent(self):
        self.assertEqual(self.fmt(b"%.2f%%", 3.14159), b"3.14%")

    def test_star_width(self):
        self.assertEqual(self.fmt(b"%*d", 4, 7), b"   7")


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.m = FakeMem()

    def test_ints_and_string(self):
        r = scan_c(self.m, b"12 -7 name", b"%d %d %s", [100, 104, 108])
        self.assertEqual(r, 3)
        self.assertEqual(struct.unpack("<ii", self.m.rd(100, 8)), (12, -7))
        self.assertEqual(self.m.cstr(108), b"name")

    def test_literal_and_char_set(self):
        r = scan_c(self.m, b"key=abc,rest", b"key=%[^,],%s", [200, 300])
        self.assertEqual(r, 2)
        self.assertEqual((self.m.cstr(200), self.m.cstr(300)), (b"abc", b"rest"))

    def test_short_input_returns_count_so_far(self):
        self.assertEqual(scan_c(self.m, b"5", b"%d %d", [100, 104]), 1)

    def test_hex_and_short(self):
        scan_c(self.m, b"ff 9", b"%x %hd", [100, 104])
        self.assertEqual(struct.unpack("<I", self.m.rd(100, 4))[0], 255)
        self.assertEqual(struct.unpack("<H", self.m.rd(104, 2))[0], 9)


class PathTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize("C:\\Magic\\Program", "sound\\a.wav"), "C:\\Magic\\Program\\sound\\a.wav")
        self.assertEqual(normalize("C:\\Magic\\Program", "C:sound\\a.wav"), "C:\\Magic\\Program\\sound\\a.wav")
        self.assertEqual(normalize("C:\\Magic\\Program", "..\\Tutorial\\x"), "C:\\Magic\\Tutorial\\x")
        self.assertEqual(normalize("C:\\Magic\\Program", "\\assertFile.txt"), "C:\\assertFile.txt")
        self.assertEqual(normalize("C:\\Magic\\Program", "d:\\x\\.\\y"), "D:\\x\\y")

    def test_case_insensitive_lookup_and_overlay(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as ov:
            os.makedirs(os.path.join(root, "Program", "Sound"))
            with open(os.path.join(root, "Program", "Sound", "KWALKL.WAV"), "wb") as f:
                f.write(b"x")
            p, ok = host_path(root, ov, "C:\\Magic\\Program", "sound\\kwalkl.wav")
            self.assertTrue(ok)
            self.assertTrue(p.endswith("KWALKL.WAV"))
            w, _ = host_path(root, ov, "C:\\Magic\\Program", "save.dat", for_write=True)
            self.assertTrue(w.startswith(ov))
            with open(w, "wb") as f:
                f.write(b"y")
            p2, ok2 = host_path(root, ov, "C:\\Magic\\Program", "SAVE.DAT")
            self.assertTrue(ok2 and p2 == w)


if __name__ == "__main__":
    unittest.main()


def test_combining_raster_operations_draw_a_glyph_over_a_picture():
    """The game's bitmap-font glyphs: an AND with a mask, then an OR with the glyph. A glyph's black background must not show."""
    import numpy as np
    from winemu import gdi
    picture = np.array([13, 14, 83, 84], np.uint8)
    mask = np.array([255, 0, 0, 255], np.uint8)            # 0 where the glyph goes
    glyph = np.array([0, 7, 9, 0], np.uint8)               # the glyph's colours, black elsewhere
    out = gdi._ROPS[0xEE0086](glyph, gdi._ROPS[0x8800C6](mask, picture))
    assert out.tolist() == [13, 7, 9, 84]
    assert gdi._ROPS[0x660046](picture, picture).tolist() == [0, 0, 0, 0]          # XOR with itself
    assert gdi._ROPS[0x330008](np.array([0, 255], np.uint8), picture[:2]).tolist() == [255, 0]


def test_save_and_restore_dc_bring_back_origin_clip_and_colours(monkeypatch):
    from winemu import gdi

    dc = gdi.DC("window", 1)
    st = {"objs": {5: dc}}

    class M:
        state = {"gdi": st}
    m = M()
    monkeypatch.setattr(gdi, "obj", lambda mm, h: st["objs"].get(h))      # the handle table
    dc.org, dc.clip, dc.textcolor = (100, 160), (1, 2, 3, 4), 0x123456
    assert gdi.save_dc(m, [5]) == 1
    dc.org, dc.clip, dc.textcolor = (0, 0), None, 0
    assert gdi.save_dc(m, [5]) == 2
    dc.org = (7, 7)
    assert gdi.restore_dc(m, [5, 0xFFFFFFFF]) == 1                 # -1: the last save
    assert (dc.org, dc.clip, dc.textcolor) == ((0, 0), None, 0)
    assert gdi.restore_dc(m, [5, 1]) == 1                          # level 1
    assert (dc.org, dc.clip, dc.textcolor) == ((100, 160), (1, 2, 3, 4), 0x123456)
    assert gdi.restore_dc(m, [5, 0xFFFFFFFF]) == 0                 # nothing left to restore


def test_sibling_z_order_follows_creation_bring_to_top_and_insert_after():
    from winemu import user32

    class M:
        state = {}
        cur = None                                                                     # no running thread
    m = M()
    user32._st(m).update(windows={}, zcount=0, next_hwnd=0x100, classes={})
    mk = lambda: user32.new_window(m, "X", 0, 0, 0, 0, 0, 1, 1, "", 0, 0)             # noqa: E731
    a, b, c = mk(), mk(), mk()
    order = lambda: [w["hwnd"] for w in user32.siblings(m, a)]                          # noqa: E731  (bottom to top)
    assert order() == [a["hwnd"], b["hwnd"], c["hwnd"]]
    user32.set_z(m, a, 0)                                                              # HWND_TOP / BringWindowToTop
    assert order() == [b["hwnd"], c["hwnd"], a["hwnd"]]
    user32.set_z(m, a, 1)                                                              # HWND_BOTTOM
    assert order() == [a["hwnd"], b["hwnd"], c["hwnd"]]
    user32.set_z(m, c, b["hwnd"])                                                      # directly below b
    assert order() == [a["hwnd"], c["hwnd"], b["hwnd"]]
    for _ in range(60):                                                                # repeated halving renumbers instead of collapsing
        user32.set_z(m, b, a["hwnd"])
        user32.set_z(m, a, 0)
    assert len(set(w["z"] for w in user32.siblings(m, a))) == 3


def test_popup_menu_apis_and_hit_testing(monkeypatch):
    from winemu import user32

    class M:
        state = {}
        cur = None
        texts = {1: b"View card", 2: b"Attack", 3: b"Sub"}

        def cstr(self, p):
            return self.texts[p]
    m = M()
    st = {"objs": {}}
    m.state["gdi"] = st
    import itertools
    ids = itertools.count(0x100)

    def new_obj(mm, o):
        h = next(ids)
        st["objs"][h] = o
        return h
    monkeypatch.setattr(user32, "new_obj", new_obj)
    monkeypatch.setattr(user32, "obj", lambda mm, h: st["objs"].get(h))
    menu = new_obj(m, ("menu", []))
    sub = new_obj(m, ("menu", []))
    A = user32.append_menu
    assert A(m, [menu, 0, 100, 1]) == 1 and A(m, [menu, 0x800, 0, 0]) == 1 and A(m, [menu, 0, 101, 2]) == 1
    assert A(m, [sub, 0, 200, 2]) == 1 and A(m, [menu, user32.MF_POPUP, sub, 3]) == 1
    items = user32._menu_items(m, menu)
    assert [i["text"] for i in items] == ["View card", "", "Attack", "Sub"] and items[3]["sub"] == sub
    # grey out and check by command id
    assert user32._set_item_flag(m, [menu, 101, user32.MF_GRAYED], user32.MF_GRAYED | user32.MF_DISABLED, 0) == 0
    assert items[2]["flags"] & user32.MF_GRAYED
    assert user32._set_item_flag(m, [menu, 100, user32.MF_CHECKED], user32.MF_CHECKED, 0) == 0 and items[0]["flags"] & user32.MF_CHECKED
    assert user32._set_item_flag(m, [menu, 999, 0], user32.MF_CHECKED, 0) == 0xFFFFFFFF          # no such item
    # hit testing and choosing
    popup = dict(levels=[(items, 50, 60)], hover=None, done=False, choice=0, hwnd=1)
    levels = user32.popup_levels(m, popup)
    x, y, w, hgt, rows = levels[0]
    assert (x, y) == (50, 60) and rows[0][2] - rows[0][1] == user32.MENU_ITEM_H and rows[1][2] - rows[1][1] == user32.MENU_SEP_H
    li, it = user32.popup_item_at(m, popup, 60, rows[0][1] + 3)
    assert li == 0 and it["id"] == 100
    assert user32.popup_item_at(m, popup, 5, 5) == (None, None)
    user32._popup_choose(m, popup, items[2])                         # grey: nothing
    assert not popup["done"]
    user32._popup_choose(m, popup, items[3])                         # a submenu opens beside it
    assert len(popup["levels"]) == 2 and popup["levels"][1][0] is user32._menu_items(m, sub)
    user32._popup_choose(m, popup, items[0])
    assert popup["done"] and popup["choice"] == 100


def test_isotropic_mapping_scales_and_offsets_logical_units():
    """The game draws its full-size card in a 200x300 logical space with the origin in the middle (MM_ISOTROPIC) on a 160x240 window."""
    from winemu import gdi
    dc = gdi.DC("memory")
    dc.mm = 7
    dc.wext, dc.vext = (200, 300), (160, 240)
    gdi._rescale(dc)
    dc.wo, dc.org = (100, 150), (80, 120)
    assert (dc.sx, dc.sy) == (0.8, 0.8)
    assert gdi.lx(dc, 0) + dc.org[0] == 0 and gdi.ly(dc, 0) + dc.org[1] == 0           # logical (0, 0) is the window's top-left
    assert gdi.lx(dc, 200) + dc.org[0] == 160 and gdi.ly(dc, 300) + dc.org[1] == 240   # and (200, 300) its bottom-right
    assert gdi.dev_rect(dc, 10, 20, 100, 50) == (-72, -104, 80, 40)                   # relative to the viewport origin
    dc.mm = 1                                                                          # MM_TEXT: back to 1:1
    dc.wext = dc.vext = (1, 1)
    gdi._rescale(dc)
    assert (dc.sx, dc.sy) == (1.0, 1.0)


def test_isotropic_scale_is_the_smaller_ratio():
    from winemu import gdi
    dc = gdi.DC("memory")
    dc.mm = 7
    dc.wext, dc.vext = (100, 100), (200, 50)
    gdi._rescale(dc)
    assert dc.sx == dc.sy == 0.5
    dc.mm = 8                                                                          # MM_ANISOTROPIC keeps both
    gdi._rescale(dc)
    assert (dc.sx, dc.sy) == (2.0, 0.5)


def test_draw_text_wraps_at_spaces_and_newlines():
    from winemu import user32

    class DC:
        pass

    def fake_size(m, dc, s):
        return len(s) * 10, 10
    orig = user32.text_size
    user32.text_size = fake_size
    try:
        wrap = lambda text, width, wb=True, single=False: user32._wrap_lines(None, DC(), text, width, wb, single)   # noqa: E731
        assert wrap("aaa bbb ccc", 70) == ["aaa bbb", "ccc"]                    # 7 characters fit in 70
        assert wrap("aaa bbb ccc", 1000) == ["aaa bbb ccc"]
        assert wrap("one\ntwo", 1000) == ["one", "two"]                         # a newline always breaks...
        assert wrap("one\ntwo", 1000, single=True) == ["one\ntwo"]              # ...except in a single line
        assert wrap("a verylongword b", 50) == ["a", "verylongword", "b"]       # a word wider than the line has its own line
        assert wrap("aaa bbb", 10, wb=False) == ["aaa bbb"]                     # no DT_WORDBREAK: one line
    finally:
        user32.text_size = orig


def test_window_extra_bytes_keep_words_and_longs_apart():
    # HorzList keeps a count word at 0, an item pointer long at 2 and more words at 6..0xc: they must not overlap
    from winemu.user32 import ExtraBytes
    x = ExtraBytes(14)
    x.put(0, 0xFFFF, 2)
    x.put(2, 0x12345678, 4)
    x.put(6, 0xABCD, 2)
    assert x.get(0, 0, 2) == 0xFFFF
    assert x.get(2) == 0x12345678
    assert x.get(6, 0, 2) == 0xABCD
    assert x.get(100, -1) == -1                        # beyond the extra bytes: the default
    x.put(0, 0x10001, 2)                               # a word write keeps to its two bytes
    assert x.get(0, 0, 2) == 1 and x.get(2) == 0x12345678


def test_get_top_window_and_get_window_walk_the_children_top_down():
    # the deck editor lays its cards out by walking GetTopWindow, then GetWindow(GW_HWNDNEXT / GW_HWNDPREV)
    from winemu import user32

    class M:
        state = {}
        cur = None
    m = M()
    user32._st(m).update(windows={}, zcount=0, next_hwnd=0x100, classes={})
    parent = user32.new_window(m, "P", 0, 0, 0, 0, 0, 10, 10, "", 0, 0)
    kid = lambda: user32.new_window(m, "K", parent["hwnd"], 0, 0, 0, 0, 1, 1, "", 0, 0)       # noqa: E731
    a, b, c = kid(), kid(), kid()                                                              # a created first: the bottom
    top = lambda h: user32.get_top_window(m, [h])                                               # noqa: E731
    gw = lambda h, cmd: user32.get_window(m, [h, cmd])                                          # noqa: E731
    assert top(parent["hwnd"]) == c["hwnd"] and gw(parent["hwnd"], 5) == c["hwnd"]
    assert [gw(c["hwnd"], 2), gw(b["hwnd"], 2), gw(a["hwnd"], 2)] == [b["hwnd"], a["hwnd"], 0]    # NEXT goes down
    assert [gw(a["hwnd"], 3), gw(b["hwnd"], 3), gw(c["hwnd"], 3)] == [b["hwnd"], c["hwnd"], 0]    # PREV goes up
    assert (gw(b["hwnd"], 0), gw(b["hwnd"], 1)) == (c["hwnd"], a["hwnd"])                        # FIRST is the top, LAST the bottom
    assert top(a["hwnd"]) == 0                                                                  # no children


def test_escape_and_enter_go_to_the_open_dialog_as_idcancel_and_idok():
    from winemu import user32

    class M:
        state = {}
        cur = None
    m = M()
    st = user32._st(m)
    st.update(windows={}, zcount=0, next_hwnd=0x100, classes={}, dialogs=[], queue=[], keys={})
    dlg = user32.new_window(m, "#32770", 0, 0, 0, 0, 0, 10, 10, "", 0, 0)
    ok = user32.new_window(m, "BUTTON", dlg["hwnd"], 0, 0, 0, 0, 1, 1, "OK", 1, 0)
    cancel = user32.new_window(m, "BUTTON", dlg["hwnd"], 0, 0, 0, 0, 1, 1, "Cancel", 2, 0)
    ok["id"], cancel["id"] = 1, 2
    st["dialogs"].append(dlg["hwnd"])
    assert user32.inject_key_event(m, 0x1B, 1, True)
    assert user32.inject_key_event(m, 0x1B, 1, False)                                  # the release sends nothing
    assert user32.inject_key_event(m, 0x0D, 0x1C, True)
    assert st["queue"] == [(dlg["hwnd"], user32.WM_COMMAND, 2, cancel["hwnd"]),
                           (dlg["hwnd"], user32.WM_COMMAND, 1, ok["hwnd"])]


def test_a_second_press_at_the_same_spot_is_a_double_click_only_for_cs_dblclks_classes(monkeypatch):
    from winemu import user32
    monkeypatch.setattr(user32.kernel32, "now_ms", lambda m: 1000)

    class M:
        state = {}
        cur = None
    m = M()
    st = user32._st(m)
    st.update(windows={}, zcount=0, next_hwnd=0x100, classes={}, queue=[], keys={}, capture=0, cursor=(0, 0), hover=None)
    for name, style in (("dbl", 8), ("plain", 0)):
        st["classes"][name] = dict(style=style, proc=0x1000, cbwnd=0, hinst=0, cursor=0, bg=0, name=name, extra=0)
    for cls, x0 in (("dbl", 0), ("plain", 100)):
        user32.new_window(m, cls, 0, 0, 0, x0, 0, 50, 50, "", 0, 0)["visible"] = True
    for x, expect in ((10, 0x203), (110, 0x201)):
        st["queue"].clear()
        st["last_down"] = None
        user32.inject_mouse(m, "down", x, 10)
        user32.inject_mouse(m, "up", x, 10)
        user32.inject_mouse(m, "down", x, 10)
        assert [q[1] for q in st["queue"]][-1] == expect


def test_rect_regions_are_created_changed_and_clip_a_dc():
    # the deck editor clips each card with a CreateRectRgn region it then re-sets with SetRectRgn
    import struct
    from winemu import gdi

    class M:
        state = {}
        cur = None
    m = M()
    gdi._st(m).update(objs={}, next=0x1000)
    h = gdi.create_rect_rgn(m, [0, 0, 10, 20])
    assert h and gdi.set_rect_rgn(m, [h, 1, 2, 30, 40]) == 1
    dc_h, dc = gdi.new_dc(m, "mem")
    gdi.select_clip_rgn(m, [dc_h, h])
    assert dc.clip == (1, 2, 30, 40)
    gdi.select_clip_rgn(m, [dc_h, 0])                                                  # NULL region (handle 0): no clip, and no crash
    assert dc.clip is None
    gdi.select_clip_rgn(m, [dc_h, dc_h])                                               # a handle that is not a region
    assert dc.clip is None
    assert gdi.set_rect_rgn(m, [dc_h, 0, 0, 1, 1]) == 0


def test_msvideo1_blocks_decode_one_two_and_eight_colours_and_skips():
    import struct
    import numpy as np
    from winemu.movie import decode_msvc16
    w, h = 16, 4                                                                       # four 4x4 blocks in one block row
    pix = np.full((h, w), 0x7FFF, np.uint16)
    one = struct.pack("<H", 0x8000 | 0x1234)                                            # byte_b >= 0x80: one colour (bit 15 ignored)
    two = struct.pack("<HHH", 0x00F0, 0x0011, 0x0022)                                   # flags 0x00F0: bits 4..7 set (second pixel row)
    eight = struct.pack("<HHH", 0x00FF, 0x8001, 2) + struct.pack("<6H", 3, 4, 5, 6, 7, 8)       # flags, then 8 colours (the first has bit 15 set)
    skip = struct.pack("<H", 0x8400 + 1)                                                # skip this block only
    decode_msvc16(one + two + skip + eight, w, h, pix)
    assert (pix[:, 0:4] == 0x1234).all()                                                # block 0
    blk = pix[:, 4:8]
    assert (blk[1] == 0x0011).all() and (blk[0] == 0x0022).all() and (blk[3] == 0x0022).all()   # set bits take colour 0
    assert (pix[:, 8:12] == 0x7FFF).all()                                               # skipped: unchanged
    q = pix[:, 12:16]
    assert (q[0:2, 0:2] == 1).all() and (q[0:2, 2:4] == 3).all()                         # set bits: the quadrant's first colour
    assert (q[2:4, 0:2] == 6).all() and (q[2:4, 2:4] == 8).all()                         # clear bits: its second


def test_magvid_status_is_one_while_a_movie_plays_and_zero_when_it_is_over():
    # STATWIN's play_video loops `while (VidStatus(slot))`; the movie follows the guest clock and ends by itself
    import numpy as np
    from winemu import movie
    from winemu.gdi import Surface

    class Clip:
        w, h, fps = 4, 4, 10.0
        frames = list(range(5))                                                           # half a second
        def frame(self, i):
            return np.full((4, 4, 3), i, np.uint8)
        def pcm16_stereo(self):
            return None

    class M:
        vt = 100.0
        def __init__(self):
            self.state = {"u32": {"windows": {}, "queue": [], "dirty": False}, "magsnd": {}}
    m = M()
    win = dict(hwnd=0x40, parent=0, surface=Surface(4, 4), movie=dict(avi=Clip(), t0=None, playing=False, channel=None, shown=-1))
    m.state["u32"]["windows"][0x40] = win
    m.state["magvid"] = {"slots": {0: 0x40}}
    assert movie._vid_status(m, [0]) == 0                                                # loaded, not started
    movie._play_avi(m, [0])
    assert movie._vid_status(m, [0]) == 1
    m.vt = 100.35
    assert movie._vid_status(m, [0]) == 1 and win["movie"]["shown"] == 3
    m.vt = 100.6
    assert movie._vid_status(m, [0]) == 0 and win["movie"]["shown"] == 4                 # over: the last picture stays
    assert movie._vid_status(m, [7]) == 2 and movie._vid_status(m, [1]) == 0              # a bad handle, an empty slot

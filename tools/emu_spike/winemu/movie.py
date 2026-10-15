"""
The game's AVI movies (the coin toss), played on the host.

MAGIC.EXE shows them with `MCIWndCreateA` (msvfw32): a child window that the game then sends MCI_PLAY (0x806), MCI_STOP (0x808) and
WM_CLOSE. The emulated Windows has no Video for Windows, so here the window is a built-in class whose surface is painted from the movie
on the guest's clock: the screen composer calls `tick` and the frame for the time since MCI_PLAY is decoded and drawn.

MAGVID.DLL, the video engine the statistics window (STATWIN.DLL) plays the ending movie and the wizards' clips with, is replaced the
same way as MAGSND: `install_magvid` makes LoadLibraryA('magvid.dll') find a host module with its 20 exports (LoadAVI, PlayAVI,
VidStatus, StopAVI, UnloadAVI, ...), and a video is a window like the MCI one. Movies in other codecs than Video 1 (the ending
and the clips are Indeo 4) are decoded by ffmpeg when it is installed; without it they are skipped, as a movie that cannot load.

The movies are Microsoft Video 1 ("CRAM", 16-bit, 4x4 blocks) with 8-bit PCM sound, which is small enough to decode here in numpy
(`decode_msvc16`); `Avi` reads the RIFF container. The sound goes through the same pygame mixer as the game's other sounds.
"""
import os
import shutil
import struct
import subprocess

import numpy as np

from . import magsnd
from .machine import REG
from .paths import host_path

MCI_PLAY, MCI_STOP, WM_CLOSE = 0x806, 0x808, 0x10


class Avi:
    """The video and audio of an AVI file: `frames` are (offset, size) in `data`, decoded on demand and in order (each frame is a
    change to the one before)."""

    def __init__(self, data):
        self.data = data
        self.w = self.h = 0
        self.fps = 15.0
        self.fourcc = b""
        self.frames = []
        self.audio_rate, self.audio_bits, self.audio_channels = 22050, 8, 1
        self.audio = []                                            # (offset, size) chunks
        self._walk(12, len(data))
        self.pix = np.zeros((self.h, self.w), np.uint16)           # decoded state, bottom row first (DIB order)
        self.at = -1                                               # the frame `pix` holds

    def _walk(self, pos, end):
        d, kind = self.data, None
        while pos + 8 <= end:
            tag, size = d[pos:pos + 4], struct.unpack_from("<I", d, pos + 4)[0]
            body = pos + 8
            if tag == b"LIST":
                self._walk(body + 4, min(body + size, end))
            elif tag == b"strh":
                kind = d[body:body + 4]
                if kind == b"vids":
                    self.fourcc = d[body + 4:body + 8]
                    scale, rate = struct.unpack_from("<II", d, body + 20)
                    self.fps = rate / scale if scale else 15.0
            elif tag == b"strf":
                if kind == b"vids":
                    _, self.w, self.h = struct.unpack_from("<Iii", d, body)
                elif kind == b"auds":
                    _, self.audio_channels, self.audio_rate = struct.unpack_from("<HHI", d, body)
                    self.audio_bits = struct.unpack_from("<H", d, body + 14)[0]
            elif tag[2:] in (b"dc", b"db"):
                self.frames.append((body, size))
            elif tag[2:] == b"wb":
                self.audio.append((body, size))
            pos = body + size + (size & 1)

    @property
    def duration(self):
        return len(self.frames) / self.fps if self.fps else 0.0

    def frame(self, index):
        """RGB (h, w, 3) of frame `index`, decoding forward from where the last call stopped (or from the start)."""
        index = max(0, min(index, len(self.frames) - 1))
        if index < self.at:
            self.pix[:] = 0
            self.at = -1
        while self.at < index:
            self.at += 1
            off, size = self.frames[self.at]
            if size:
                decode_msvc16(self.data[off:off + size], self.w, self.h, self.pix)
        p = self.pix[::-1].astype(np.uint16)
        r, g, b = (p >> 10) & 31, (p >> 5) & 31, p & 31
        return np.stack([(r << 3) | (r >> 2), (g << 3) | (g >> 2), (b << 3) | (b >> 2)], -1).astype(np.uint8)

    def pcm16_stereo(self):
        """The sound as 16-bit stereo bytes for the mixer, or None."""
        if not self.audio or self.audio_bits not in (8, 16):
            return None
        raw = b"".join(self.data[o:o + s] for o, s in self.audio)
        if self.audio_bits == 8:
            a = (np.frombuffer(raw, np.uint8).astype(np.int16) - 128) << 8
        else:
            a = np.frombuffer(raw[:len(raw) // 2 * 2], np.int16)
        if self.audio_channels == 1:
            a = np.repeat(a, 2)
        return a.astype(np.int16).tobytes()


def decode_msvc16(buf, w, h, pix):
    """Apply one Microsoft Video 1 (16-bit) frame to `pix`, a (h, w) uint16 array in DIB order (the bottom row first). Blocks are 4x4,
    coded left to right from the bottom block row up: a skip run, one colour, two colours (a bit per pixel) or eight (two per quadrant)."""
    bw, bh = w // 4, h // 4
    total = bw * bh
    n = len(buf)
    pos = idx = 0
    while idx < total and pos + 2 <= n:
        a, b = buf[pos], buf[pos + 1]
        pos += 2
        if (b & 0xFC) == 0x84:                                     # skip: this block and the rest of the run are unchanged
            idx += ((b - 0x84) << 8) + a
            continue
        x, y = (idx % bw) * 4, (idx // bw) * 4
        blk = pix[y:y + 4, x:x + 4]
        if b < 0x80:                                               # two or eight colours; (b, a) are the bit flags
            flags = (b << 8) | a
            if pos + 4 > n:
                break
            c0, c1 = struct.unpack_from("<HH", buf, pos)
            pos += 4
            bits = np.array([(flags >> i) & 1 for i in range(16)], bool).reshape(4, 4)
            if c0 & 0x8000:                                        # eight colours: a pair for each 2x2 quadrant
                if pos + 12 > n:
                    break
                cols = [c0 & 0x7FFF, c1 & 0x7FFF] + [v & 0x7FFF for v in struct.unpack_from("<6H", buf, pos)]
                pos += 12
                for qy in (0, 1):
                    for qx in (0, 1):
                        base = qy * 4 + qx * 2
                        sub = bits[qy * 2:qy * 2 + 2, qx * 2:qx * 2 + 2]
                        blk[qy * 2:qy * 2 + 2, qx * 2:qx * 2 + 2] = np.where(sub, cols[base], cols[base + 1])
            else:
                blk[:] = np.where(bits, c0 & 0x7FFF, c1 & 0x7FFF)
        else:                                                      # one colour
            blk[:] = ((b << 8) | a) & 0x7FFF
        idx += 1


class FfmpegMovie:
    """A movie in a codec this module does not decode (Indeo 4): `ffmpeg` streams its frames as RGB through a pipe, in order, and
    its sound is read whole. Same interface as Avi: w, h, fps, frames, frame(i), pcm16_stereo(), close()."""

    def __init__(self, avi, path, ffmpeg):
        self.w, self.h, self.fps, self.frames = avi.w, avi.h, avi.fps, avi.frames
        self.path, self.ffmpeg = path, ffmpeg
        self.proc = None
        self.at = -1
        self.last = np.zeros((self.h, self.w, 3), np.uint8)

    def frame(self, index):
        index = max(0, min(index, len(self.frames) - 1))
        if self.proc is None:
            self.proc = subprocess.Popen([self.ffmpeg, "-v", "error", "-i", self.path, "-an", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                         stdout=subprocess.PIPE, stdin=subprocess.DEVNULL)
        size = self.w * self.h * 3
        while self.at < index:
            raw = self.proc.stdout.read(size)
            if len(raw) < size:                                   # the stream ended early: keep the last picture
                self.at = len(self.frames)
                break
            self.last = np.frombuffer(raw, np.uint8).reshape(self.h, self.w, 3)
            self.at += 1
        return self.last

    def pcm16_stereo(self):
        r = subprocess.run([self.ffmpeg, "-v", "error", "-i", self.path, "-vn", "-f", "s16le", "-ar", "22050", "-ac", "2", "-"],
                           capture_output=True, stdin=subprocess.DEVNULL)
        return r.stdout or None

    def close(self):
        if self.proc is not None:
            self.proc.kill()
            self.proc.wait()
            self.proc = None


def open_movie(path):
    """A movie object for an AVI file, or None if this host cannot play it (an unknown codec and no ffmpeg)."""
    with open(path, "rb") as fh:
        avi = Avi(fh.read())
    if not avi.frames:
        return None
    if avi.fourcc.upper() in (b"CRAM", b"MSVC"):
        return avi
    ffmpeg = shutil.which("ffmpeg")
    return FfmpegMovie(avi, path, ffmpeg) if ffmpeg else None


def _close(movie):
    if hasattr(movie, "close"):
        movie.close()


# ---- the MCI window ----------------------------------------------------------------------------------------------
def _state(m):
    return m.state.setdefault("movies", {})


@REG.api("msvfw32.dll", "MCIWndCreateA", None)                      # cdecl (VFWAPIV): the caller pops its four arguments
def mciwnd_create(m, a):
    from . import user32  # noqa: PLC0415
    parent, _, style, path = a[0], a[1], a[2], a[3]
    hp, ok = host_path(m.game_root, m.overlay_root, m.cwd, m.cstr(path).decode("latin-1")) if path > 0xFFFF else (None, False)
    if not ok:
        m.log(f"   MCIWndCreate({hp!r}): no such movie")
        return 0
    avi = open_movie(hp)
    if avi is None:
        m.log(f"   MCIWndCreate({hp}): a movie this host cannot play (ffmpeg is needed for its codec)")
        return 0
    win = user32.new_window(m, "MCIWndClass", parent, style, 0, 0, 0, avi.w, avi.h, "", 0, 0)
    win["visible"] = bool(style & user32.WS_VISIBLE)
    win["movie"] = dict(avi=avi, t0=None, playing=False, channel=None, shown=-1)
    m.log(f"   MCIWndCreate: {os.path.basename(hp)} {avi.w}x{avi.h}, {len(avi.frames)} frames at {avi.fps:g} fps")
    _show_frame(m, win, 0)
    return win["hwnd"]


def _show_frame(m, win, index):
    mv = win["movie"]
    if mv["shown"] == index:
        return
    frame = mv["avi"].frame(index)
    s = win["surface"]
    s.rgb[:] = frame
    s.direct[:] = True
    mv["shown"] = index
    m.state.setdefault("u32", {})["dirty"] = True


def _stop(m, win, notify=True):
    mv = win["movie"]
    ch = mv.get("channel")
    if ch is not None:
        try:
            ch.stop()
        except Exception:                                          # noqa: BLE001
            pass
        mv["channel"] = None
    if mv["playing"]:
        mv["playing"] = False
        if notify and win["parent"]:
            m.state["u32"]["queue"].append((win["parent"], 0x4C8, win["hwnd"], 524))     # MCIWNDM_NOTIFYMODE, MCI_MODE_STOP


def _play(m, win):
    mv = win["movie"]
    if mv["playing"]:
        return
    mv["playing"], mv["t0"] = True, m.vt
    backend = magsnd._mixer(m).backend
    pcm = mv["avi"].pcm16_stereo() if backend is not None else None
    if pcm:
        try:
            ch = backend.Sound(buffer=pcm).play()
            mv["channel"] = ch
        except Exception:                                          # noqa: BLE001  (no sound device: the picture plays without it)
            pass
    if win["parent"]:
        m.state["u32"]["queue"].append((win["parent"], 0x4C8, win["hwnd"], 525))         # MCI_MODE_PLAY
    m.state["u32"]["dirty"] = True


def message(m, win, msg, wp, lp):
    """The window's own handling of the messages the game sends it."""
    if msg == MCI_PLAY:
        _play(m, win)
        return 0
    if msg == MCI_STOP:
        _stop(m, win)
        return 0
    if msg == WM_CLOSE:
        from . import user32  # noqa: PLC0415
        user32.destroy(m, win["hwnd"])
        return 0
    return 0


def release(m, win):
    """The window is being destroyed: silence its sound."""
    if win.get("movie"):
        _stop(m, win, notify=False)
        _close(win["movie"]["avi"])


def advance(m, win):
    """Bring a playing movie to the frame for the guest's clock; at its end it stops. True while it is still playing."""
    mv = win["movie"]
    if not mv["playing"]:
        return False
    avi = mv["avi"]
    index = int((m.vt - mv["t0"]) * avi.fps)
    if index >= len(avi.frames):
        _show_frame(m, win, len(avi.frames) - 1)
        _stop(m, win)
        return False
    _show_frame(m, win, index)
    m.state["u32"]["dirty"] = True                                # keep composing while it plays
    return True


def tick(m):
    """Called by the screen composer: advance every playing movie."""
    for win in list(m.state.get("u32", {}).get("windows", {}).values()):
        if win.get("movie"):
            advance(m, win)


# ---- MAGVID.DLL on the host ------------------------------------------------------------------------------------------
MAGVID_EXPORTS = {
    1: "InitVid", 2: "ReleaseVid", 3: "LoadAVI", 4: "UnloadAVI", 5: "PlayAVI", 6: "StopAVI", 7: "SetVidCallBack", 8: "SetVidBackground",
    9: "SetVidBackgroundToBMP", 10: "SetVidBackgroundToDIB", 11: "DrawVidBackground", 12: "PasteToVidBackground", 13: "SetVidForeground",
    14: "PaintVid", 15: "SetVidPos", 16: "VidStatus", 17: "LinkVids", 18: "SetVidThreadPriority", 19: "SetVidTransparency", 20: "_delay",
}
MAGVID_BASE = 0x7D000000
SLOTS = 3                                                          # the DLL's own limit: handles are 0..2


def _slots(m):
    return m.state.setdefault("magvid", {}).setdefault("slots", {})


def _log(m, text):
    if os.environ.get("MAGVID_LOG"):
        m.log(f"   [magvid] {text}")


def _load_avi(m, a):                                               # LoadAVI(path, *slot, *short pos[2], flags) -> 0 or an error
    from . import user32  # noqa: PLC0415
    slots = _slots(m)
    free = next((i for i in range(SLOTS) if i not in slots), None)
    if free is None:
        return 3
    hp, ok = host_path(m.game_root, m.overlay_root, m.cwd, m.cstr(a[0]).decode("latin-1")) if a[0] > 0xFFFF else (None, False)
    if not ok:
        _log(m, f"LoadAVI {m.cstr(a[0]) if a[0] > 0xFFFF else a[0]}: no such file")
        return 5
    movie = open_movie(hp)
    if movie is None:
        _log(m, f"LoadAVI {hp}: cannot be decoded here (needs ffmpeg)")
        return 4
    flags = a[3]
    if flags == 0:
        x, y = struct.unpack("<hh", bytes(m.rd(a[2], 4))) if a[2] > 0xFFFF else (0, 0)
    else:                                                          # full screen: centred
        x, y = (user32.SCREEN_W - movie.w) // 2, (user32.SCREEN_H - movie.h) // 2
    win = user32.new_window(m, "VIDWINCLASS", 0, 0x90000000, 0, x, y, movie.w, movie.h, "", 0, 0)
    win["visible"] = True
    win["movie"] = dict(avi=movie, t0=None, playing=False, channel=None, shown=-1)
    _show_frame(m, win, 0)
    slots[free] = win["hwnd"]
    m.w32(a[1], free)
    _log(m, f"LoadAVI {os.path.basename(hp)} -> slot {free} at {x},{y} {movie.w}x{movie.h} flags {flags}")
    return 0


def _slot_win(m, handle):
    h = _slots(m).get(handle & 0xFFFFFFFF)
    return m.state["u32"]["windows"].get(h) if h else None


def _play_avi(m, a):
    win = _slot_win(m, a[0])
    if win:
        _log(m, f"PlayAVI {a[0]}")
        _play(m, win)
    return 0


def _stop_avi(m, a):
    win = _slot_win(m, a[0])
    if win:
        _stop(m, win, notify=False)
    return 0


def _unload_avi(m, a):
    from . import user32  # noqa: PLC0415
    win = _slot_win(m, a[0])
    if win:
        user32.destroy(m, win["hwnd"])
        _slots(m).pop(a[0] & 0xFFFFFFFF, None)
        _log(m, f"UnloadAVI {a[0]}")
    return 0


def _vid_status(m, a):                                             # 1 while the movie plays, 0 when it is over or the slot is empty, 2 for a bad handle
    h = a[0] & 0xFFFFFFFF
    if h >= SLOTS:
        return 2
    win = _slot_win(m, h)
    return 1 if win and advance(m, win) else 0


_MAGVID = {"LoadAVI": _load_avi, "PlayAVI": _play_avi, "StopAVI": _stop_avi, "UnloadAVI": _unload_avi, "VidStatus": _vid_status}
for _name in MAGVID_EXPORTS.values():
    REG.handlers[("magvid.host", _name)] = (_MAGVID.get(_name, lambda m, a: 0), None)          # cdecl; the rest accept and do nothing


def install_magvid(m):
    """Make the game's LoadLibraryA('magvid.dll') find the host version."""
    mods = m.state.setdefault("host_modules", {})
    mods["magvid.dll"] = {"base": MAGVID_BASE, "exports": {f"#{o}": m.stub_for("magvid.host", name) for o, name in MAGVID_EXPORTS.items()}}

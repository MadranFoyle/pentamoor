"""
The game's sound library, MAGSND.DLL, run on the host instead of in the guest.

The real DLL needs DirectSound, the multimedia file I/O (mmio*) and AVIFile, none of which the emulated Windows has. Without
them its InitSnd fails, the game carries on with sound off, and then waits for a sound to finish by polling GetSndState until
it says "stopped" (the duel's coin toss does this, in a loop that makes no calls at all): the loop never ends because the DLL
reports an unloaded sound without touching the answer.

Here all 27 exports exist and work the way the game uses them (`cdecl`, 0 means success, an answer is written through the pointer
argument). With `audio=True` (the live window) the game's WAV files are played through pygame.mixer: LoadSnd / PlaySndFile load a file
into a numbered slot, PlaySnd plays it (volume, looping), GetSndState says whether it is still playing. Without audio, or if there is no
sound device, everything is accepted and nothing is playing.

The slot numbers, option block and ordinals are the game's (MAGSND.DLL's exports as MAGIC.EXE calls them): PlaySnd(id, opts) with
opts = 8 dwords: [0] volume 0..400, [1] pitch in Hz, [2] pan, [7] flags (bit 0: loop).

`install(m)` makes LoadLibraryA("magsnd.dll") return this module and GetProcAddress give out its functions by ordinal.
"""
import os
import struct

from .machine import REG
from .paths import host_path

# ordinal -> name (the real DLL's export table)
EXPORTS = {
    1: "InitSnd", 2: "ReleaseSnd", 3: "LoadSnd", 4: "UnloadSnd", 5: "UnloadAllSnds", 6: "PlaySnd", 7: "PlaySndFile", 8: "StopSnd",
    9: "StopAllSnds", 10: "PlayMidiFile", 11: "SetPitch", 12: "GetPitch", 13: "SetVol", 14: "GetVol", 15: "SetPan", 16: "GetPan",
    17: "UpdateSnd", 18: "SetSndMarker", 19: "PlaySndMarker", 20: "GetSndTime", 21: "ResetSnd", 22: "GetSndState",
    23: "GetAVISndBuff", 24: "ReleaseAVISndBuff", 25: "GetSndHWND", 26: "IsSndLoaded", 27: "GetLRUSnd",
}
BASE = 0x7E000000                                              # the module handle LoadLibraryA gives
MAX_VOLUME = 400.0


class Mixer:
    """Slots of loaded sounds and the channels playing them. `backend` is pygame.mixer or None (silent)."""

    def __init__(self, backend=None):
        self.backend = backend
        self.slots = {}                                        # id -> pygame Sound (or None: a file that is there but could not be decoded)
        self.channels = {}                                     # id -> Channel
        self.volume = {}                                       # id -> 0..1
        self.played = 0                                        # PlaySnd calls that started a sound (a statistic)

    def load(self, ident, path):
        self.stop(ident)
        sound = None
        if self.backend is not None:
            try:
                sound = self.backend.Sound(path)
            except Exception:                                  # noqa: BLE001  (not a WAV pygame can decode: accepted, silent)
                sound = None
        self.slots[ident] = sound

    def unload(self, ident):
        self.stop(ident)
        self.slots.pop(ident, None)

    def play(self, ident, volume, loop):
        sound = self.slots.get(ident)
        self.volume[ident] = max(0.0, min(volume, 1.0))
        if sound is None:
            return
        try:
            ch = sound.play(loops=-1 if loop else 0)
            self.played += 1
            if ch is not None:
                ch.set_volume(self.volume[ident])
                self.channels[ident] = ch
        except Exception:                                      # noqa: BLE001  (the device went away: silent)
            pass

    def stop(self, ident):
        ch = self.channels.pop(ident, None)
        if ch is not None:
            try:
                ch.stop()
            except Exception:                                  # noqa: BLE001
                pass

    def stop_all(self):
        for ident in list(self.channels):
            self.stop(ident)

    def playing(self, ident):
        ch = self.channels.get(ident)
        try:
            return bool(ch is not None and ch.get_busy())
        except Exception:                                      # noqa: BLE001
            return False

    def set_volume(self, ident, volume):
        self.volume[ident] = max(0.0, min(volume, 1.0))
        ch = self.channels.get(ident)
        if ch is not None:
            try:
                ch.set_volume(self.volume[ident])
            except Exception:                                  # noqa: BLE001
                pass


def open_backend():
    """pygame.mixer initialised for the game's 22 kHz stereo sounds, or None if pygame or a sound device is missing."""
    try:
        import pygame  # noqa: PLC0415
        pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=1024)
        pygame.mixer.set_num_channels(32)
        return pygame.mixer
    except Exception:                                          # noqa: BLE001
        return None


def _mixer(m):
    st = m.state.setdefault("magsnd", {})
    if "mixer" not in st:
        st["mixer"] = Mixer(open_backend() if st.get("audio") else None)
    return st["mixer"]


def _guest_file(m, ptr):
    hp, ok = host_path(m.game_root, m.overlay_root, m.cwd, m.cstr(ptr).decode("latin-1"))
    return hp if ok else None


def _out(m, ptr, value):
    if ptr > 0xFFFF:
        m.w32(ptr, value)


def _signed(v):
    return struct.unpack("<i", struct.pack("<I", v & 0xFFFFFFFF))[0]


def _opts(m, ptr):
    """(volume 0..1, loop) from a PlaySnd option block; full volume and no loop without one."""
    if ptr <= 0xFFFF:
        return 1.0, False
    block = struct.unpack("<8I", bytes(m.rd(ptr, 32)))
    return min(block[0], MAX_VOLUME) / MAX_VOLUME, bool(block[7] & 1)


# cdecl: `a` holds the first stack arguments
def _load(m, a):                                               # LoadSnd(path, id, info)
    path = _guest_file(m, a[0]) if a[0] else None
    if path is None:
        return 1
    if os.environ.get("MAGSND_LOG"):
        m.log(f"   [magsnd] LoadSnd slot {a[1]} <- {path}")
    _mixer(m).load(a[1], path)
    return 0


def _play(m, a):                                               # PlaySnd(id, opts)
    vol, loop = _opts(m, a[1])
    if os.environ.get("MAGSND_LOG"):
        m.log(f"   [magsnd] PlaySnd slot {a[0]} volume {vol:.2f} loop {loop}")
    _mixer(m).play(a[0], vol, loop)
    return 0


def _play_file(m, a):                                          # PlaySndFile(path, id, opts)
    if _load(m, a):
        return 1
    vol, loop = _opts(m, a[2])
    _mixer(m).play(a[1], vol, loop)
    return 0


def _stop(m, a):
    _mixer(m).stop(a[0])
    return 0


def _stop_all(m, a):
    _mixer(m).stop_all()
    return 0


def _unload(m, a):
    _mixer(m).unload(a[0])
    return 0


def _unload_all(m, a):
    mx = _mixer(m)
    mx.stop_all()
    mx.slots.clear()
    return 0


def _set_vol(m, a):
    _mixer(m).set_volume(a[0], _signed(a[1]) / MAX_VOLUME)
    return 0


def _state(m, a):                                              # GetSndState(id, *state): 0 stopped, 1 playing
    _out(m, a[1], 1 if _mixer(m).playing(a[0]) else 0)
    return 0


def _is_loaded(m, a):                                          # IsSndLoaded(id, *loaded)
    _out(m, a[1], 1 if a[0] in _mixer(m).slots else 0)
    return 0


def _answer_zero(index):
    def fn(m, a):
        _out(m, a[index], 0)
        return 0
    return fn


SPECIAL = {"LoadSnd": _load, "PlaySnd": _play, "PlaySndFile": _play_file, "StopSnd": _stop, "StopAllSnds": _stop_all,
           "UnloadSnd": _unload, "UnloadAllSnds": _unload_all, "SetVol": _set_vol, "GetSndState": _state, "IsSndLoaded": _is_loaded,
           "GetPitch": _answer_zero(1), "GetVol": _answer_zero(1), "GetPan": _answer_zero(1), "GetSndTime": _answer_zero(1)}

for _name in EXPORTS.values():
    REG.handlers[("magsnd.host", _name)] = (SPECIAL.get(_name, lambda m, a: 0), None)


def install(m, audio=False):
    """Make the game's LoadLibraryA('magsnd.dll') find the host version; `audio`: play the sounds."""
    mods = m.state.setdefault("host_modules", {})
    mods["magsnd.dll"] = {"base": BASE, "exports": {f"#{o}": m.stub_for("magsnd.host", name) for o, name in EXPORTS.items()}}
    m.state.setdefault("magsnd", {})["audio"] = audio

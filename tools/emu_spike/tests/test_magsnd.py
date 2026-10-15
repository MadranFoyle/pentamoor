"""winemu.magsnd: the host sound library has the exports (and ordinals) of the real MAGSND.DLL."""
import os
import struct
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from winemu import magsnd  # noqa: E402
from winemu.machine import REG  # noqa: E402

DLL = os.path.join(os.path.dirname(__file__), "..", "..", "..", "sources", "installed", "Magic", "Program", "MAGSND.DLL")


def test_there_are_27_exports_numbered_1_to_27():
    assert sorted(magsnd.EXPORTS) == list(range(1, 28))


@pytest.mark.skipif(not os.path.exists(DLL), reason="needs the game's own MAGSND.DLL")
def test_names_match_the_real_dll():
    import pefile
    pe = pefile.PE(DLL)
    real = {e.ordinal: e.name.decode() for e in pe.DIRECTORY_ENTRY_EXPORT.symbols}
    assert magsnd.EXPORTS == real


class FakeBackend:
    """pygame.mixer stand-in: Sound(path).play() returns a channel that is busy until stopped."""
    class Channel:
        def __init__(self):
            self.busy, self.volume = True, None

        def get_busy(self):
            return self.busy

        def set_volume(self, v):
            self.volume = v

        def stop(self):
            self.busy = False

    class Sound:
        def __init__(self, path):
            self.path, self.plays = path, []

        def play(self, loops=0):
            ch = FakeBackend.Channel()
            self.plays.append((loops, ch))
            return ch


def test_mixer_plays_reports_state_and_stops():
    mx = magsnd.Mixer(FakeBackend)
    mx.load(7, "/x/y.wav")
    assert 7 in mx.slots and not mx.playing(7)
    mx.play(7, 0.5, False)
    assert mx.playing(7) and mx.channels[7].volume == 0.5
    mx.set_volume(7, 2.0)
    assert mx.channels[7].volume == 1.0                    # clamped
    mx.stop(7)
    assert not mx.playing(7)
    mx.play(7, 1.0, True)
    assert mx.slots[7].plays[-1][0] == -1                  # looping
    mx.unload(7)
    assert 7 not in mx.slots and not mx.playing(7)


def test_silent_mixer_accepts_everything_and_plays_nothing():
    mx = magsnd.Mixer(None)
    mx.load(3, "/x/y.wav")
    mx.play(3, 1.0, False)
    assert 3 in mx.slots and not mx.playing(3)


def test_play_options_block():
    class M:
        def rd(self, a, n):
            return struct.pack("<8I", 400, 22050, 0, 0, 0, 0, 0, 1)
    assert magsnd._opts(M(), 0x50000000) == (1.0, True)
    assert magsnd._opts(M(), 0) == (1.0, False)            # no block: full volume, no loop


def test_an_answer_is_written_through_the_pointer_argument():
    class M:
        def __init__(self):
            self.mem = {}
            self.state = {}

        def w32(self, a, v):
            self.mem[a] = v
    m = M()
    fn, _ = REG.handlers[("magsnd.host", "GetSndState")]
    assert fn(m, [5, 0x5026cc50]) == 0 and m.mem == {0x5026cc50: 0}       # nothing playing
    fn, _ = REG.handlers[("magsnd.host", "IsSndLoaded")]
    assert fn(m, [5, 0x5026cc54]) == 0 and m.mem[0x5026cc54] == 0         # not loaded
    assert fn(m, [5, 0]) == 0                                              # no pointer: nothing written

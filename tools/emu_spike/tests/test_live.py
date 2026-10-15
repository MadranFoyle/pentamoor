"""winemu.live: key table and the pacing of the guest clock (no window needed)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from winemu import live  # noqa: E402
from winemu.user32 import SCANCODES  # noqa: E402


def test_keys_have_the_scan_codes_the_game_expects():
    assert live.key_info("return") == (13, 0x1C, 13)
    assert live.key_info("a", "a") == (ord("A"), 0x1E, ord("a"))
    assert live.key_info("a", "A") == (ord("A"), 0x1E, ord("A"))      # shifted: the character typed
    assert live.key_info("left shift") == (0x10, 0x2A, None)          # modifiers type nothing
    assert live.key_info("1", "1")[:2] == (ord("1"), 0x02)
    assert live.key_info("f1")[:2] == (0x70, 0x3B) and live.key_info("f10")[:2] == (0x79, 0x44)
    assert live.key_info("up")[:2] == (38, 0x48)
    assert live.key_info("left meta") is None


def test_live_scan_codes_agree_with_the_script_ones():
    """Letters, digits and the keys scripts use: the table of scripts' `key` ops (user32.SCANCODES) is the same."""
    for name in "qwertyuiopasdfghjklzxcvbnm1234567890":
        vk, sc, _ = live.key_info(name, name)
        assert SCANCODES[vk] == sc, name
    for name, vk in (("return", 13), ("escape", 27), ("space", 32), ("backspace", 8), ("tab", 9),
                     ("left", 37), ("up", 38), ("right", 39), ("down", 40), ("delete", 46)):
        assert SCANCODES[vk] == live.key_info(name)[1], name


class FakeClock:
    def __init__(self):
        self.t = 100.0
        self.slept = 0.0

    def now(self):
        return self.t

    def sleep(self, d):
        self.t += d
        self.slept += d


def pacer(speed=1.0):
    c = FakeClock()
    return live.Pacer(speed, clock=c.now, sleep=c.sleep), c


def test_pacer_waits_for_the_real_clock():
    p, c = pacer()
    assert p.wait(0.0, 0.5) == 0.5
    assert 0.49 < c.slept < 0.52                       # slept about the virtual gap


def test_pacer_speed():
    p, c = pacer(2.0)
    assert p.wait(0.0, 1.0) == 1.0
    assert 0.49 < c.slept < 0.52                       # twice as fast: half the real time


def test_pacer_returns_early_on_input():
    p, c = pacer()
    p.wait(0.0, 0.0)                                   # anchor
    calls = []

    def interrupt():
        calls.append(1)
        return len(calls) == 3
    got = p.wait(0.0, 5.0, interrupt)
    assert 0.0 <= got < 0.1 and c.slept < 0.1


def test_pacer_does_not_race_to_catch_up():
    p, c = pacer()
    p.wait(0.0, 0.1)
    c.t += 10.0                                        # the host stalled for ten seconds
    assert p.wait(0.1, 0.2) == 0.2
    assert c.slept < 0.2 + 0.1                         # the 0.1 s gap is waited out, not skipped


def test_guest_clock_follows_the_real_one_and_never_goes_back():
    p, c = pacer()
    assert p.now_vt() == 0.0
    c.t += 3.0
    assert abs(p.now_vt() - 3.0) < 1e-9

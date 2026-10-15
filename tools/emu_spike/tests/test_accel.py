"""winemu.accel: the Python stand-ins agree with the guest functions they replace."""
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from winemu import accel  # noqa: E402


def test_find_word_rules():
    f = accel.find_word
    assert f(b"Flying", b"black", False) == -1
    assert f(b"Target black creature", b"black", False) == 7
    assert f(b"black.", b"black", False) == 0                   # followed by '.'
    assert f(b"blacks", b"black", False) == 0                   # followed by 's'
    assert f(b"x black wins", b"black", False) == 2             # followed by a space and a lower-case letter
    assert f(b"black Wins", b"black", False) == -1              # a space and a capital: passed over
    assert f(b"black", b"black", False) == -1                   # at the end of the text: passed over
    assert f(b"BLACK.", b"black", False) == 0                   # case-insensitive
    assert f(b"BLACK.", b"black", True) == -1                   # case-sensitive
    assert f(b"", b"black", False) == -1 and f(b"black.", b"", False) == -1
    assert f(b"blackx black.", b"black", False) == 7            # the first occurrence that counts


TRACE = os.environ.get("FIND_WORD_TRACE", "")


@pytest.mark.skipif(not os.path.exists(TRACE), reason="set FIND_WORD_TRACE to a trace of the original: winemu.run --accel off --seconds 3 --break 0x100327b1:Find:3:0,1:ret")
def test_find_word_against_original():
    """Every call of the original that the trace shows (strings the trace did not cut short) gives the same result."""
    call = re.compile(r"\[trace .*?\] Find\((.*)\) <- 0x[0-9a-f]+")
    ret = re.compile(r"\[ret .*?\] Find\((.*)\) <- 0x[0-9a-f]+\s+= (-?\d+)")
    seen, checked = {}, 0
    for line in open(TRACE, errors="replace"):
        m = ret.search(line)
        if not m:
            continue
        args = eval("(" + m.group(1) + ",)")                        # noqa: S307  (our own trace: two strings and a number)
        text, word, mode = args[0].encode("latin-1"), args[1].encode("latin-1"), args[2]
        if len(text) >= 59 or len(word) >= 59:
            continue
        assert accel.find_word(text, word, mode != 0) == int(m.group(2)), (text, word, mode)
        checked += 1
    assert checked > 100


def test_card_window_match_compares_the_windows_two_longs_with_the_key():
    # MAGIC.EXE FUN_0046bb29(hwnd, key): GetWindowLong(hwnd, [0x5150f4]) == key[0] && GetWindowLong(hwnd, [0x5150f8]) == key[1]
    from winemu.user32 import ExtraBytes

    class M:
        def __init__(self):
            self.mem = {0x5150F4: 0, 0x5150F8: 4, 0x9000: 1, 0x9004: 7, 0x9100: 1, 0x9104: 8, 0x8000: 0x40}
            win = {"extra": ExtraBytes(8)}
            win["extra"].put(0, 1)
            win["extra"].put(4, 7)
            self.state = {"u32": {"windows": {0x40: win}}}

        def r32(self, a):
            return self.mem.get(a, 0)
    m = M()

    def call(hwnd, key):
        m.mem[0x8004], m.mem[0x8008] = hwnd, key                                        # esp = 0x8000: [esp+4], [esp+8]
        return accel._card_window_is_native(m, 0x8000)
    assert call(0x40, 0x9000) == 1                                                       # (1, 7) matches
    assert call(0x40, 0x9100) == 0                                                       # (1, 8) does not
    assert call(0, 0x9000) == 0 and call(0x40, 0) == 0                                   # a null window or key: 0, as the original
    assert call(0x44, 0x9000) == 0                                                       # no such window: GetWindowLong gives 0, 0 != (1, 7)


class FakeMachine:
    """Memory as a dict of dwords, a call counter, a clock and a state dict: what the stand-ins below touch."""

    def __init__(self, words=None):
        self.mem, self.calls, self.vt, self.state = dict(words or {}), 0, 0.0, {}

    def r32(self, a):
        return self.mem.get(a, 0)

    def w32(self, a, v):
        self.mem[a] = v


def test_tick_wait_sleeps_until_the_timer_thread_has_advanced_the_count_by_half_the_argument():
    m = FakeMachine({0x530DA0: 100, 0x1004: 10})          # esp+4 = 10: wait for 5 ticks
    gen = accel._tick_wait_native(m, 0x1000)
    block = next(gen)
    assert not block.ready()
    m.mem[0x530DA0] = 104
    assert not block.ready()
    m.mem[0x530DA0] = 105
    assert block.ready()
    with pytest.raises(StopIteration) as done:
        next(gen)
    assert done.value.value == 5


def test_tick_wait_of_nothing_returns_at_once():
    for n in (0, 1, 0xFFFFFFFF):                           # n / 2 rounded toward zero is 0 for 0, 1 and -1
        gen = accel._tick_wait_native(FakeMachine({0x1004: n}), 0x1000)
        with pytest.raises(StopIteration):
            next(gen)


def test_input_poll_copies_the_input_state_and_clears_what_it_consumed():
    m = FakeMachine({0x5239EC: 1, 0x7039D0: 0x30, 0x7039C4: 0x5, 0x7039CC: 7, 0x7039C8: 9})
    assert accel._input_poll_native(m, 0x1000) == 0x35
    assert (m.mem[0x67BDA0], m.mem[0x67BDA4], m.mem[0x67BDA8], m.mem[0x7039D0]) == (0x35, 7, 9, 0)
    m.mem[0x5239EC] = 0
    assert accel._input_poll_native(m, 0x1000) == 0
    assert (m.mem[0x67BDA0], m.mem[0x67BDA4], m.mem[0x67BDA8]) == (0, 0, 0)


def test_input_poll_called_flat_out_sleeps_before_touching_anything():
    m = FakeMachine({0x5239EC: 1, 0x7039D0: 0x30})
    results = [accel._input_poll_native(m, 0x1000) for _ in range(17)]       # no import call between them
    assert isinstance(results[-1], accel.Block) and results[-1].until == pytest.approx(0.004)
    assert m.mem[0x7039D0] == 0 and all(not isinstance(r, accel.Block) for r in results[:-1])

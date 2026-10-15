"""
Host-side stand-ins for a few guest functions that are pure and called very often, so that a live game starts in seconds
instead of a minute (live.py needs it; the exact-hosting comparisons of tools/lift do not use it, as it changes how many
instructions the guest runs).

Each one is the function's machine code read and written as Python over the same arguments, and checked against what the
original returned for the same arguments (tests/test_accel.py, from a recorded trace when the game's files are present).
"""
import os

from .machine import Block, u32, S32

DECKDLL_FIND_WORD = 0x100327B1
MAGIC_FIND_WORD = 0x004F4CE1          # the same function compiled into MAGIC.EXE (identical but for addresses)


def find_word(text: bytes, word: bytes, case_sensitive: bool) -> int:
    """DECKDLL.DLL FUN_100327b1(text, word, case_sensitive): where `word` occurs in `text` as a word (-1 if it does not).

    An occurrence counts when what follows it is 's' or '.', or a space that is not followed by a capital letter; one
    followed by anything else, or by the end of the text, is passed over (the scan goes on one character further).
    The result is the index of the first occurrence that counts."""
    if not text or not word:
        return -1
    n = len(word)
    if not case_sensitive:
        low_text, low_word = text.lower(), word.lower()                  # the C locale's tolower: ASCII only, as bytes.lower
    else:
        low_text, low_word = text, word
    i = low_text.find(low_word)
    while i >= 0:
        after = text[i + n:i + n + 1]
        if after in (b"s", b"."):
            return i
        if after == b" ":
            nxt = text[i + n + 1:i + n + 2]
            if not (nxt and 65 <= nxt[0] <= 90):                         # isupper in the C locale
                return i
        i = low_text.find(low_word, i + 1)
    return -1


def _find_word_native(m, esp):
    text, word, mode = m.r32(esp + 4), m.r32(esp + 8), m.r32(esp + 12)
    if not text or not word:
        return u32(-1)
    return u32(find_word(m.cstr(text), m.cstr(word), mode != 0))


MAGIC_KEY_POLL = 0x00408089            # MAGIC.EXE: `return DAT_00516bdc != 0` -- the menu loops call it flat out, waiting for input


def _key_poll_native(m, esp):
    """The same function, but a loop that calls it 16 times without any other import call in between is waiting for input: it
    sleeps 4 virtual ms (the machine then runs other threads, or sleeps for real when `--live` paces it). The original spins at
    100% of a CPU; in the emulator that is a laptop's fan for nothing."""
    st = m.state.setdefault("accel_poll", [0, -1])
    if m.calls == st[1]:
        st[0] += 1
    else:
        st[0] = 0
    st[1] = m.calls
    if st[0] >= 16:
        st[0] = 0
        return Block(until=m.vt + 0.004)
    return 1 if m.r32(0x516BDC) else 0


MAGIC_INPUT_POLL = 0x0044B84B          # MAGIC.EXE FUN_0044b84b(): copy the input state (DAT_007039c4..cc, written by the window procedures) into DAT_0067bda0..a8


def _input_poll_native(m, esp):
    """The same function, and the same sleep as `_key_poll_native` when it is called flat out: the title and intro loops call it 8.7 million
    times in a run without any other import call in between, which in the emulator is a core at 100%."""
    st = m.state.setdefault("accel_poll_input", [0, -1])
    if m.calls == st[1]:
        st[0] += 1
    else:
        st[0] = 0
    st[1] = m.calls
    if st[0] >= 16:
        st[0] = 0
        return Block(until=m.vt + 0.004)       # (before it has done anything: the call is run again when the thread wakes)
    if m.r32(0x5239EC):
        eax = m.r32(0x7039D0)
        m.w32(0x7039D0, 0)
        eax |= m.r32(0x7039C4)
        m.w32(0x67BDA0, eax)
        m.w32(0x67BDA4, m.r32(0x7039CC))
        m.w32(0x67BDA8, m.r32(0x7039C8))
        return eax
    m.w32(0x67BDA8, 0)
    m.w32(0x67BDA4, 0)
    m.w32(0x67BDA0, 0)
    return 0


MAGIC_CARD_WINDOW_IS = 0x0046BB29      # MAGIC.EXE FUN_0046bb29(hwnd, int *key): the window's longs 0 and 4 (player, slot) equal key[0], key[1]


def _card_window_is_native(m, esp):
    """The same function without its two GetWindowLongA imports. The board's message handler (Pic_Subsystem_0044bad4) scans its card
    windows with it on every message, and during the opponent's turn that was 60% of all import calls (1.9 million in 77 s)."""
    hwnd, key = m.r32(esp + 4), m.r32(esp + 8)
    if not hwnd or not key:
        return 0
    win = m.state.get("u32", {}).get("windows", {}).get(hwnd)
    extra = win["extra"] if win else None
    a = extra.get(m.r32(0x5150F4), 0) if extra is not None else 0
    b = extra.get(m.r32(0x5150F8), 0) if extra is not None else 0
    return 1 if m.r32(key) == a and m.r32(key + 4) == b else 0


MAGIC_TICK_WAIT = 0x00501736           # MAGIC.EXE FUN_00501736(n): spin until the timer thread's tick count (DAT_00530da0) has advanced n / 2


def _tick_wait_native(m, esp):
    """The same wait without the spin. The original reads the tick count in a loop (two billion instructions in the first 150 seconds of
    a run: an intro delay); here the thread sleeps until the timer thread has advanced it by as much, so the machine runs other
    threads or jumps its clock (scripted), or waits for the real one (live), and a laptop's fan is left alone."""
    n = S32(m.r32(esp + 4))
    want = -((-n) >> 1) if n < 0 else n >> 1            # cdq; sub eax,edx; sar eax,1: n / 2 rounded toward zero
    start = m.r32(0x530DA0)
    if want > 0:
        yield Block(ready=lambda: S32(m.r32(0x530DA0) - start) >= want)
    return u32(want)


def install(m):
    """Replace the guest functions above (those whose module is loaded). Returns how many."""
    n = 0
    if "deckdll.dll" in m.modules:
        m.add_intercept(DECKDLL_FIND_WORD, _find_word_native)             # cdecl: the caller pops its arguments
        n += 1
    if m.exe_guest_path.lower().endswith("\\magic.exe"):
        m.add_intercept(MAGIC_FIND_WORD, _find_word_native)               # (870,000 calls when a new game's cards are set up)
        m.add_intercept(MAGIC_KEY_POLL, _key_poll_native)
        m.add_intercept(MAGIC_CARD_WINDOW_IS, _card_window_is_native)
        if "tick_wait" not in os.environ.get("ACCEL_SKIP", ""):   # (ACCEL_SKIP=tick_wait: the original's spin, to compare)
            m.add_intercept(MAGIC_TICK_WAIT, _tick_wait_native)
            n += 1
        if "input_poll" not in os.environ.get("ACCEL_SKIP", ""):
            m.add_intercept(MAGIC_INPUT_POLL, _input_poll_native)
            n += 1
        n += 3
    return n

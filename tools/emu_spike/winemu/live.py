"""
A live window for the emulated game: `python3 -m winemu.run --live`.

The emulator runs on a worker thread and the window (pygame / SDL) on the main thread, as SDL requires. The two meet at
two places only (the one other call into Unicorn is the ticker thread's emu_stop, below):
  - input: the window's thread puts events in a queue; the emulator's thread turns them into the game's messages
    (user32.inject_mouse / inject_key) between scheduling slices, so the guest's state is only ever touched by one thread;
  - output: the emulator's thread composes the screen (run.compose) up to 30 times a second and hands over the latest frame.
A slice is short (SLICE instructions), so input is served and the frame refreshed many times a second even while the game thread spins.

Time. The guest sees only the virtual clock (machine.py). Live, that clock is the real one (`Pacer`): it never runs behind
what the host's clock says, and when every thread is waiting the jump to the next deadline is slept out in real time, so
animations and timers run at the speed the game was made for however fast or slow the host is.
"""
import os
import queue
import threading
import time

# Keys as the game's keyboard code sees them: name (pygame.key.name) -> (virtual-key code, scan code). The game turns a
# WM_KEYDOWN's scan code into a character itself and reads Shift, Ctrl, Alt and Caps Lock from GetAsyncKeyState, so those
# are real key events too.
KEYS = {"escape": (27, 0x01), "backspace": (8, 0x0E), "tab": (9, 0x0F), "return": (13, 0x1C), "enter": (13, 0x1C),
        "left ctrl": (0x11, 0x1D), "right ctrl": (0x11, 0x1D), "left shift": (0x10, 0x2A), "right shift": (0x10, 0x36),
        "left alt": (0x12, 0x38), "right alt": (0x12, 0x38), "space": (32, 0x39), "caps lock": (0x14, 0x3A),
        "home": (0x24, 0x47), "up": (38, 0x48), "page up": (0x21, 0x49), "left": (37, 0x4B), "right": (39, 0x4D),
        "end": (0x23, 0x4F), "down": (40, 0x50), "page down": (0x22, 0x51), "insert": (0x2D, 0x52), "delete": (46, 0x53),
        "-": (0xBD, 0x0C), "=": (0xBB, 0x0D), "[": (0xDB, 0x1A), "]": (0xDD, 0x1B), ";": (0xBA, 0x27), "'": (0xDE, 0x28),
        "`": (0xC0, 0x29), "\\": (0xDC, 0x2B), ",": (0xBC, 0x33), ".": (0xBE, 0x34), "/": (0xBF, 0x35)}
for _i, _c in enumerate("1234567890"):
    KEYS[_c] = (ord(_c), 0x02 + _i)
for _i, _c in enumerate("qwertyuiop"):
    KEYS[_c] = (ord(_c.upper()), 0x10 + _i)
for _i, _c in enumerate("asdfghjkl"):
    KEYS[_c] = (ord(_c.upper()), 0x1E + _i)
for _i, _c in enumerate("zxcvbnm"):
    KEYS[_c] = (ord(_c.upper()), 0x2C + _i)
for _i in range(1, 11):
    KEYS[f"f{_i}"] = (0x6F + _i, 0x3A + _i)
KEYS["f11"], KEYS["f12"] = (0x7A, 0x57), (0x7B, 0x58)


def key_info(name, unicode_char=""):
    """(vk, scan code, char) for a pygame key name and the character it typed; None for a key the game does not get.
    `char` is what WM_CHAR carries, None for a key that types nothing."""
    k = KEYS.get(name)
    if k is None:
        return None
    ch = {"return": 13, "enter": 13, "backspace": 8, "tab": 9, "escape": 27}.get(name)
    if ch is None and unicode_char and len(unicode_char) == 1 and 32 <= ord(unicode_char) < 127:
        ch = ord(unicode_char)
    return k[0], k[1], ch


class Pacer:
    """Maps virtual time to real time. `wait(target)` returns the virtual time to continue from: `target` once the real
    clock has reached it, sooner if `interrupt()` says something happened meanwhile."""

    def __init__(self, speed=1.0, clock=time.monotonic, sleep=time.sleep, step=0.004):
        self.speed, self.clock, self.sleep, self.step = speed, clock, sleep, step
        self.real0 = None
        self.vt0 = 0.0

    def now_vt(self):
        now = self.clock()
        if self.real0 is None:
            self.real0, self.vt0 = now, 0.0
        return self.real_to_vt(now)

    def real_to_vt(self, now):
        return self.vt0 + (now - self.real0) * self.speed

    def wait(self, vt_now, target, interrupt=lambda: False):
        now = self.clock()
        if self.real0 is None:
            self.real0, self.vt0 = now, vt_now
        behind = self.real_to_vt(now) - vt_now
        if behind > 0.05:                                        # slower than real time: forget the lag, do not race ahead
            self.real0, self.vt0 = now, vt_now
        while True:
            now = self.clock()
            reach = self.real_to_vt(now)
            if reach >= target:
                return target
            if interrupt():
                return max(vt_now, min(target, reach))
            self.sleep(max(0.0001, min(self.step, (target - reach) / self.speed)))


class Live:
    def __init__(self, fps=30, speed=1.0, title="Magic: The Gathering"):
        self.events = queue.SimpleQueue()
        self.frame = None                                        # latest composed frame (numpy RGB), set by the emulator thread
        self.frame_n = 0
        self.lock = threading.Lock()
        self.closed = False
        self.fps, self.title = fps, title
        self.pacer = Pacer(speed)
        self.compose = None
        self.next_frame = 0.0
        self.machine = None
        self.hold_until = 0
        self.stop_calls = int(os.environ.get("EMU_STOP_CALLS", "0"))
        self.last_compose = 0.0
        self.fallbacks = 0                                       # slices ended by the unsafe asynchronous stop (see _ticker)
        self.samples = __import__("collections").Counter() if os.environ.get("LIVE_SAMPLE") else None

    # ---- emulator thread ---------------------------------------------------------------------------
    def attach(self, m, compose):
        """Hook into the machine: service input and output each time it schedules, pace its idle clock jumps."""
        from . import user32  # noqa: PLC0415
        self.machine, self.compose, self.user32 = m, compose, user32
        m.state["pace"] = lambda mm, target: self.pacer.wait(mm.vt, target, lambda: self._service(mm))
        # The guest's clock is the real one (never less than what its instructions cost, never backwards): the game
        # thread busy-waits through whole 200M-instruction slices, and its timers must still run at the right rate.
        m.state["clock"] = lambda mm, before: max(before, self.pacer.now_vt())
        m.state["should_stop"] = lambda mm: self.closed
        m.slice = self.SLICE
        m.state["ticker"] = self.TICK_MS > 0
        m.state["hard_stop"] = None
        m.state["virtual_limit"] = None

    def on_schedule(self, m):
        self._service(m)
        if self.stop_calls and m.calls >= self.stop_calls:           # EMU_STOP_CALLS=N: a fixed amount of work, for timing
            self.closed = True
            m.stop = True
        if self.samples is not None:                                 # LIVE_SAMPLE=1: where the guest spends its time
            from unicorn.x86_const import UC_X86_REG_EIP  # noqa: PLC0415
            self.samples[m.uc.reg_read(UC_X86_REG_EIP)] += 1

    def _service(self, m):
        """Deliver queued input to the game and publish a new frame if one is due. True if input was delivered."""
        got = False
        while True:
            if self.hold_until > m.slices:                       # a button just went down: let the game's own thread see it
                break
            try:
                ev = self.events.get_nowait()
            except queue.Empty:
                break
            got = True
            if (ev[0] == "mouse" and ev[1] in ("down", "rdown")) or (ev[0] == "key" and ev[3] and not ev[5]):
                self.hold_until = m.slices + self.PRESS_SLICES   # the game polls button and key states: they must stay down for a while
            if ev[0] == "call":                                      # a debugging aid (live_drive call:): run a guest function on a new thread
                args = []
                for a in ev[2]:
                    if isinstance(a, str):
                        ptr = m.alloc(len(a) + 1)
                        m.put_cstr(ptr, a.encode("latin-1"))
                        a = ptr
                    args.append(a)
                m.spawn(ev[1], args, "call", one_shot=True)
                continue
            if ev[0] == "mouse":
                self.user32.inject_mouse(m, ev[1], ev[2], ev[3])
            elif ev[0] == "key":
                self.user32.inject_key_event(m, *ev[1:])
        now = time.monotonic()
        if now >= self.next_frame:
            self.next_frame = now + 1.0 / self.fps
            u32 = m.state.get("u32", {})
            # Composing the screen costs several milliseconds: only when something was drawn (the flag drawing sets), a window or
            # dialog changed in a way that does not set it, or a quarter second has passed (so that nothing stays stale for long).
            if got or u32.get("dirty") or self.frame is None or now - self.last_compose >= 0.25:
                u32["dirty"] = False
                frame = self.compose(m)
                self.last_compose = now
                with self.lock:
                    self.frame, self.frame_n = frame, self.frame_n + 1
        return got

    # ---- window thread -----------------------------------------------------------------------------
    def run(self, m):
        """Run the machine on a worker thread and the window here until either ends. Returns the machine's exit code."""
        import pygame  # noqa: PLC0415
        result = {}
        finished = threading.Event()

        def work():
            try:
                if os.environ.get("LIVE_PROFILE"):                  # LIVE_PROFILE=1: where the emulator thread spends host time (printed at exit)
                    import cProfile
                    import pstats
                    prof = cProfile.Profile()
                    try:
                        result["code"] = prof.runcall(m.run)
                    finally:
                        pstats.Stats(prof).sort_stats("tottime").print_stats(25)
                else:
                    result["code"] = m.run()
            except BaseException as e:                           # noqa: BLE001  (shown after the window closes)
                result["error"] = e
            finally:
                result["done"] = True
                finished.set()

        pygame.init()
        pygame.key.set_repeat(400, 40)
        screen = pygame.display.set_mode((640, 480), pygame.SCALED | pygame.RESIZABLE)
        pygame.display.set_caption(self.title)
        clock = pygame.time.Clock()
        worker = threading.Thread(target=work, name="emulator", daemon=True)
        worker.start()
        if self.TICK_MS > 0:
            threading.Thread(target=self._ticker, args=(m, finished), name="ticker", daemon=True).start()
        shown = 0
        held, repeating = {}, set()                               # keys down: what each sent, and which have already repeated
        while not self.closed and not result.get("done"):
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    self._close(m)
                elif ev.type == pygame.MOUSEMOTION:
                    self.events.put(("mouse", "move", ev.pos[0], ev.pos[1]))
                elif ev.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP) and ev.button in (1, 3):
                    kind = ("down" if ev.button == 1 else "rdown") if ev.type == pygame.MOUSEBUTTONDOWN \
                        else ("up" if ev.button == 1 else "rup")
                    self.events.put(("mouse", kind, ev.pos[0], ev.pos[1]))
                elif ev.type == pygame.WINDOWFOCUSLOST:                  # keys let go while elsewhere would stay down
                    for key, (vk, sc, _) in held.items():
                        self.events.put(("key", vk, sc, False, None, False))
                    held.clear()
                    repeating.clear()
                elif ev.type in (pygame.KEYDOWN, pygame.KEYUP):
                    info = key_info(pygame.key.name(ev.key), getattr(ev, "unicode", ""))
                    if ev.type == pygame.KEYDOWN and info:
                        held[ev.key] = info
                    elif ev.type == pygame.KEYUP:
                        info = held.pop(ev.key, info)
                    if info:
                        vk, sc, ch = info
                        self.events.put(("key", vk, sc, ev.type == pygame.KEYDOWN, ch if ev.type == pygame.KEYDOWN else None,
                                         ev.type == pygame.KEYDOWN and ev.key in repeating))
                        repeating.add(ev.key) if ev.type == pygame.KEYDOWN else repeating.discard(ev.key)
            with self.lock:
                frame, n = self.frame, self.frame_n
            if frame is not None and n != shown:
                shown = n
                surf = pygame.image.frombuffer(frame.tobytes(), (frame.shape[1], frame.shape[0]), "RGB")
                screen.blit(surf, (0, 0))
                pygame.display.flip()
            clock.tick(120)
        if not result.get("done"):
            self._close(m)
            worker.join(5)
        pygame.quit()
        if os.environ.get("LIVE_STATS"):
            mx = m.state.get("magsnd", {}).get("mixer")
            print(f"[live] asynchronous fallback stops: {self.fallbacks}; sounds started: {mx.played if mx else 0}"
                  f" ({'audio on' if mx and mx.backend else 'silent'})", flush=True)
        if "error" in result:
            raise result["error"]
        return result.get("code", 0)

    # Instructions a thread runs before the others (and the window) get their turn. The game's own thread busy-waits, so
    # without this the window would wait for the 200M-instruction slice of the exact runs (some twenty seconds of host time).
    # 
    SLICE = int(os.environ.get("LIVE_SLICE", "200000"))
    # A count makes Unicorn call a hook on every instruction, so the guest runs about 35 times slower than it could (40 MIPS
    # against 1,400 here). So slices are ended another way: a ticker thread asks (m.yield_req) every TICK_MS and the
    # machine ends the slice at its next import call, a clean place (inside the hook, with the call finished). A thread that
    # makes no import call for FALLBACK_MS (a busy loop) is stopped from the ticker with uc_emu_stop. That asynchronous stop
    # is only safe while the CPU is in guest code: landing inside an import hook it corrupted the guest in Unicorn 2.1.4
    # (a lone DllMain thread ended with wrong registers within seconds in about half of the runs, when the ticker stopped it
    # directly every 10 ms), and Unicorn's own `timeout=` never fires. LIVE_TICK_MS=0 goes back to counted slices.
    TICK_MS = float(os.environ.get("LIVE_TICK_MS", "10"))
    # How long (host time) a thread may run before it is asked to give way. The game was written for a scheduler that switches threads
    # only when one blocks (its C runtime and its picture decompressor are not thread-safe, and the emulator's original slice is 200M
    # instructions, so in the exact runs threads switch only at blocking calls). Every extra switch is a chance for the races that
    # this hides, so the quantum is long: it only keeps a thread that never blocks (a polling loop) from starving the window.
    QUANTUM_MS = float(os.environ.get("LIVE_QUANTUM_MS", "250"))
    FALLBACK_MS = float(os.environ.get("LIVE_FALLBACK_MS", "100"))
    # Slices a pressed mouse button or key is held before anything else is delivered. The game's own thread polls the button's
    # state, and the window thread's messages (button down, button up) are handled by the main thread in one turn, so
    # without this the thread that polls never sees the button down.
    PRESS_SLICES = int(os.environ.get("LIVE_PRESS_SLICES", "6"))

    def _ticker(self, m, done):
        """Ask the machine to end its slice every TICK_MS: it does so at the next import call, a clean place. Only a thread
        that makes no import call for FALLBACK_MS (a busy loop) is stopped from here, the one unsafe way."""
        asked = None
        while not done.is_set():
            time.sleep(self.TICK_MS / 1000)
            if m.yield_req:                                      # the last request has not been taken
                asked = asked or time.monotonic()
                if time.monotonic() - asked >= self.FALLBACK_MS / 1000:
                    asked = None
                    self.fallbacks += 1
                    m.yield_req = False
                    try:
                        m.uc.emu_stop()
                    except Exception:                            # noqa: BLE001  (not running: nothing to stop)
                        pass
            elif time.monotonic() - m.slice_t0 >= self.QUANTUM_MS / 1000:    # this slice has run a whole quantum without blocking
                asked = None
                m.yield_req = True
            else:
                asked = None

    def _close(self, m):
        """The window was closed: the game's next GetMessage sees WM_QUIT; a slice in progress is cut short."""
        self.closed = True
        m.stop = True

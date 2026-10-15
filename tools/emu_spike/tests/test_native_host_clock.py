"""native_host.Ledger and Machine.publish_clock: what hosted code owes the clock, and the clock it reads from guest memory."""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from winemu.machine import Machine  # noqa: E402
from winemu.native_host import Ledger, NativeHost  # noqa: E402


class FakeHost:
    """Just what Ledger and NativeHost.charge_since use: an instruction counter (lifted code counts them), the charges so far, the machine."""

    def __init__(self, mode):
        self.cost_mode = mode
        self.ic = 0
        self.charged_total = 0.0
        self.native_cost = []
        self.m = types.SimpleNamespace(owed=0, burn=0)

    def mark_clock_window(self):
        pass

    def _counters(self):
        return [], self.ic

    def charge_since(self, before, inner, conts=0):
        return NativeHost.charge_since(self, before, inner, conts)


def run_through_a_guest_call(mode):
    h = FakeHost(mode)
    ledger = Ledger(h)
    h.ic = 100                     # the hosted function ran 100 instructions, then calls out to the guest
    ledger.settle()
    h.ic, h.charged_total = 140, h.charged_total + 40      # the guest function ran hosted code of its own (40) and paid for it
    ledger.rebase()
    h.ic = 190                     # 50 more after the call
    ledger.finish()
    return h


def test_a_replaced_function_pays_the_clock_before_each_guest_call_it_makes():
    h = run_through_a_guest_call("owed")
    assert h.m.owed == 100 + 50 and h.charged_total == 190.0   # not the 40 the guest call's own hosted code paid


def test_exact_mode_burns_the_instructions_less_the_trap_each_guest_call_returns_through():
    h = run_through_a_guest_call("burn")
    assert h.m.burn == 100 + (50 - 1)


def test_the_clock_the_hosted_code_reads_is_the_guests_clock():
    m = types.SimpleNamespace(clock_cells=(0x100, 0x104, 0x108), vt=12.3456, writes={})
    m.w32 = lambda a, v: m.writes.__setitem__(a, v)
    Machine.publish_clock(m)
    assert m.writes[0x100] == 60000 + 12345                    # kernel32 GetTickCount
    assert m.writes[0x104] == int(12.3456 * 54050)             # the timer driver's DeviceIoControl count

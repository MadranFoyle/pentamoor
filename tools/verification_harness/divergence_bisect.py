#!/usr/bin/env python3
"""
Binary search over two tick-indexed traces to localize the earliest point of
divergence, so a mismatch between the port and the original becomes "state first
differed at tick N" instead of "something somewhere is wrong."

This module is pure algorithm -- it doesn't know how to run the game or take a
snapshot. Callers provide a `snapshot_at(tick)` function for each side (in
practice: replay the same input script up to `tick` against a fresh instance of
each binary, then read state). That's why bisection re-runs from tick 0 each time
rather than pausing a single long-running process: it keeps both sides' timelines
directly comparable and doesn't require pause/resume support from either process.
"""


class NoDivergenceError(Exception):
    """Raised when bisect_divergence is asked to search a range where the two
    sides never actually differ -- almost certainly a caller bug (e.g. passing the
    same snapshot function for both sides)."""


def bisect_divergence(snapshot_fn_a, snapshot_fn_b, diff_fn, max_tick):
    """Find the earliest tick in [0, max_tick] at which diff_fn(snapshot_fn_a(t),
    snapshot_fn_b(t)) is non-empty.

    Assumes monotonicity: once the two sides diverge at some tick, they stay
    diverged for all later ticks. This holds for a deterministic replay of the same
    input script, since a divergence in game state doesn't spontaneously self-heal.
    If that assumption is ever violated (e.g. an incidental divergence that
    resolves itself), bisection will report *a* divergence point but not
    necessarily the true first one -- worth keeping in mind before trusting a
    surprising result blindly.

    Returns (tick, diff) for the first diverging tick, or None if no divergence
    was found in [0, max_tick].
    """
    if diff_fn(snapshot_fn_a(max_tick), snapshot_fn_b(max_tick)) == []:
        return None  # no divergence anywhere in range

    lo, hi = 0, max_tick
    # Invariant: diff at hi is non-empty (or hi == max_tick and we just checked it).
    # We're looking for the smallest tick where the diff is non-empty.
    while lo < hi:
        mid = (lo + hi) // 2
        d = diff_fn(snapshot_fn_a(mid), snapshot_fn_b(mid))
        if d:
            hi = mid
        else:
            lo = mid + 1

    final_diff = diff_fn(snapshot_fn_a(lo), snapshot_fn_b(lo))
    return (lo, final_diff)


if __name__ == "__main__":
    # Self-test with synthetic data, no game/toolchain required. See tests/ (next to this file) for the
    # real unittest version; this is just a quick manual sanity check.
    DIVERGE_AT = 37

    def side_a(t):
        return 0

    def side_b(t):
        return 0 if t < DIVERGE_AT else 1

    def diff(a, b):
        return [] if a == b else [f"{a} != {b}"]

    result = bisect_divergence(side_a, side_b, diff, max_tick=100)
    print(result)
    assert result is not None and result[0] == DIVERGE_AT
    print("ok")

# Verification Harness

Automated differential-testing tooling for checking the modern port's behavior against
the original 1997 binaries, without requiring anyone to manually play the game.

See [`docs/VERIFICATION_HARNESS_PLAN.md`](../../docs/VERIFICATION_HARNESS_PLAN.md) for
the full design and roadmap. This directory holds the Phase 0 pieces — the parts that
don't need Wine, MinGW, Frida, or the original discs to build and test.

## Layout

- `input_schema.py` — JSON schema + validator for scripted input event sequences.
- `monkey_policy.py` — deterministic, seeded decision policy that generates an input
  script without any human playthrough or real AI.
- `state_snapshot.py` — data model for the per-tick state record we diff between the
  port and the original.
- `divergence_bisect.py` — binary-search over a divergence between two tick-indexed traces, to
  localize the earliest tick (and therefore the responsible function) automatically.
- `oracle_launch.sh`, `oracle_qemu.py` — boot the Windows 98 oracle under QEMU and drive it (QMP
  keys/screenshots, gdbstub breakpoints/memory). See `docs/ORACLE_VM.md`.
- `oracle_ctl.py` — command-line driver: `shot`, `click X Y`, `move X Y`, `key`.
- `probe_steps.py` — breakpoint on the turn-step runner plus a watchpoint on the step code.
- `probe_globals.py` — watchpoints on the card-event context globals.
- `probe_duel_start.py` — what runs when a duel starts.
- `probe_drawcard.py` — first oracle experiment (see `docs/SYMBOL_VERIFICATION.md`).
- `tests/` — unit tests for everything above that doesn't require the real toolchain.

## Running the tests

```sh
cd tools/verification_harness
python3 -m unittest discover tests
```

## What's real vs. stubbed right now

| Piece | Status |
|---|---|
| Input schema + validator | Real, tested |
| Monkey policy generator | Real, tested (pure logic, no game needed) |
| State snapshot data model | Real, tested (structure only — no live memory reads yet) |
| Bisection algorithm | Real, tested against synthetic traces |
| Driving the port | Not started (`orchestrator.py` was a skeleton for the old SDL2 test binary and has been removed; the port's own control pipe, `tools/soak/pentamoor_ctl.py`, is what drives it now) |
| The original under Wine | Not started — needs `wine-stable`, `mingw-w64`, the clock-override shim DLL, and a legally obtained copy of the game |
| Frida-based function tracing | Not started — Phase 2 |

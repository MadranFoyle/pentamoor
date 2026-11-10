# The processes that "did not start": a control command that came before the guest's memory

**Cause found, fixed in the runtime, checked by `make -C src/port check-run`.** The pad regression ([controller.md](controller.md), "A repeatable run") started about 90 processes of Spells of the Ancients 2.15 in 30 runs and 9 of them printed nothing after the `display (start): ...` line,
until the script's `boot` gave up on them after 100 s and started them again (always the fourth process of a run, the `back` step's; a second start always worked; in one run both starts failed). They were **not stalled. They had crashed**, at once, with a segmentation fault, and a crashed
process leaves exactly that log: the display line is the last thing the window's thread prints before it starts the game's thread.

## What it was

The runtime has two threads at its start. The window's thread (`front_run`, `front_sdl.c`) opens the control pipe (`PORT_CONTROL`), starts the game's thread and then loops, reading the pipe. The game's thread (`game_main`) begins with `guest_init`, which reserves the guest's 4 GiB of address space and
sets `G`, the base every guest address is added to. A control command that reads or writes guest memory (`poke`, `peek`, `dump`) that was in the pipe **before `G` was set** did `memcpy(G + addr, ...)` with `G` null: a segmentation fault in the window's thread.
macOS's crash report of one (`~/Library/Logs/DiagnosticReports/pentamoor-run-*.ips`, 2026-11-09 23:31) says it plainly: `EXC_BAD_ACCESS (SIGSEGV)`, `KERN_INVALID_ADDRESS at 0x0000000000725310`, the crashing thread `_platform_memmove` <- `run_step` <- `poll_control` <- `front_run` <- `main`
(0x725310 is the table of wandering monsters in `shandalar.exe` 2.15, `sota_soak.MONSTERS`).

Who sent the `poke`: `sota_pad_play.py`'s monster keeper, a thread that pokes the table clear four times a second while it is switched on (`keeper_on`), through whichever process is the script's current one (`self.g`). The steps switch it on and off (`s.keeper_on`); the `reward` step, the last of a full run, ends with it on, and nothing switches it off before the `back` step, so the `back` step's process
is the one that is *started* while it is on (the `resume` process is started with an explicit `keeper_on.clear()` just before, and the first process of a run before the first step that sets it): from the moment the script opens the new process's pipe, a `poke` can be in it before the runtime has reserved its memory (the guest's thread
starts after SDL, the window and the audio device are up, and on a loaded machine that is tens of milliseconds, with a keeper that pokes every 250 ms). That is the whole of "always the fourth", and of "more often when several runtimes are started in the same second" (a loaded machine makes the window longer). (`sota_saveload.py`, 2.15, has a keeper of the same kind, which waits for `loaded` now too; `screen_nav_play.py`, 1.0, clears the table from its own waits, never at a process's start.)

## How it was found, and what it measured

1. The harness `boot` told a process that never prints `loaded` from one that is slow, and wrote what it was doing: `Game.wait_loaded`, `Game.diagnose_stall` (macOS `sample`, Linux `/proc/PID/task/*`) in `tools/soak/pentamoor_ctl.py`. Of the first 9 `back` starts (`--only newgame,save,back`, two runs at once, with
   the 2.15 install built into a scratch folder) **one** was reported "no `loaded` line in 30 s, process gone": not alive, so not a stall. The crash report with the time of that start was the one above.
2. `startloop.py` (a scratch driver, not in the repository: it starts the runtime N times, N at once, and says how many printed `loaded`) with a `poke` written to the pipe every 250 ms from a random phase, as the keeper does: **the old runtime died in 59 of 300 starts (20 %)**, with a poke every 10 ms in 99 of 100.
   Without the pokes: 0 of 800 starts (400 sequential and 400 eight at a time, 1.0's `MAGIC.EXE` and 2.15's `shandalar.exe`) failed, so nothing else was wrong with starting a process (SDL, the audio device, the instance file, the module's `dlopen` and the thread's start were all looked at, none of them stalls).

## The fix

- `guest_ready()` (`guest.c`): true once `G` is set (a release store in `guest_init`, an acquire load in the reader). `front_run` reads the control pipe and runs the script's steps only when it is true; what was sent meanwhile stays in the pipe (and a step stays in the list) and runs as soon as the guest exists.
  A command that came a few milliseconds early now runs a few milliseconds late.
- The test: `make -C src/port check-run` (CI runs it on the three systems) starts the runtime on the stub module with a file for `PORT_CONTROL` that holds `poke 0x725310 1 4` and `peek 0x725310`, and `PORT_GUEST_DELAY_MS=400` (a test aid in `guest_init`: the guest's memory comes 400 ms late, as it does on a loaded machine) and wants
  the usual exit status 2 with "cannot open ...". The old code does `segmentation fault` (exit 139) every time, the new code exits 2 (both tried by hand: the old runtime was rebuilt without the two `guest_ready()` tests).
- The harness: the keeper does not poke a process before its `loaded` line (`Game.loaded()`), `boot` waits for the line for 30 s instead of 100 s for a title menu, prints the exit status of a process that died (a negative one is a signal; -11 is this crash) and the stacks of one that did not,
  and tries three times.

## Before and after

| | starts | died or stalled |
|---|---|---|
| the pad regression, the old runtime and harness (controller.md) | about 90 | 9 (the `back` step's, 10 %) |
| two scratch loops of `sota_pad_play.py --only newgame,save,back`, two at a time, the old runtime, the new harness (which reports a process that did not start) | 9 `back` starts (8 whole runs, a ninth stopped after its `back` step) | 1 (crash report as above) |
| `startloop.py`, the old runtime, a poke every 250 ms | 300, one at a time | 59 (20 %) |
| the same, the final runtime (all of this branch's changes), a poke every 250 ms | 1,000, one at a time | 0 |
| the same, the final runtime, a poke every 50 ms, 16 at a time (median start 0.65 s: the machine was loaded) | 1,500 | 0 |
| 1.0's `MAGIC.EXE`, the final runtime, a poke every 100 ms, 4 at a time | 600 | 0 |
| the old runtime, a poke every 50 ms, 16 at a time | 400 | 400 (all) |
| 12 whole runs of `sota_pad_play.py --only newgame,save,back` (two at a time, the new harness) with the runtime that has the stall fix | 12 `back` starts, 36 starts of the three main processes | 0 (one run failed a position check of the Load step, the known "walk after a click", not a start) |
| `pad_regression.py --game 2.15`, seed 8, the final runtime | one whole run, 184 checks | 0 failed |

`startloop.py` is a scratch driver and is not in the repository; the check that is (`make check-run`) is the single deterministic case of it.

## Not done

- A command that does not touch the guest (`windows`, `quit`, `shot` ...) also waits for it now. It costs milliseconds and nothing needed it earlier.
- The Windows front end reads `PORT_CONTROL` as a plain file, and the same gate applies there; it was not run on Windows (the check is in CI's Windows job, which this change has not been through yet).

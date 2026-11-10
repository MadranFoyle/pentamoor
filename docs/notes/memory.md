# Where the memory of a long run went

**The growth of a long duel (1 to 4 MiB a minute, [duel-ux.md](duel-ux.md) "Resident memory") was not the game's. It was the runtime's: six leaks, found with `leaks` and a pinned, endless duel, all fixed, each with a test.** The game's own heap does not grow in a duel at all
(the flat line in the table below), and its own growth in Spells of the Ancients 2.15 is a different, smaller thing (the last section). Measured on macOS (Apple Silicon), 800x600, SDL's dummy drivers, `PORT_HEAP_LOG=30`.

## What was leaking

| what | how much | where | fix |
|---|---|---|---|
| a **record for every finished guest thread**. A multimedia timer starts a thread for each of its callbacks (about 24 a second in a duel) and `new_thread` reused the slot of a finished one by overwriting its pointer | 256 bytes each: 0.35 MiB/min | `sched.c` | a record is freed when its slot is reused and nothing names it any more (`refs`: the handle of `CreateThread`, a timer's last callback, a wait); the exiting thread says it is done with its record only when it has detached |
| the **copies `SaveDC` makes**, dropped by `RestoreDC` without being freed (the game saves and restores a device context for every text it draws) | 192 bytes each: about 0.25 MiB/min | `gdi.c` | freed |
| **pens, brushes, regions, fonts, bitmaps**: `DeleteObject` marked the slot unused and left the memory, the table never used the slot again. A pen or a brush for every tile of a world: 12 million of them making a Spells of the Ancients world in 12 seconds | 660 MiB of the host's memory, for the rest of the run, in 2.15's new game (25 MiB now) | `gdi.c` | `DeleteObject` frees them and the slot is used again; the stock objects, a font or bitmap that is selected into a context, palettes (one may be the system palette) and cursors are left alone |
| a **DIB section's pixels**, in the guest's heap, were never given back at `DeleteObject` | the game's picture buffers | `gdi.c` | given back, after the last 8 MiB of them have waited (a program that draws once more through a pointer it still has finds its pixels) |
| the **device contexts a window's paint makes**: `BeginPaint` made one and `EndPaint` did nothing; `ReleaseDC` kept a window's own; the context for a `WM_ERASEBKGND` and for an owner-draw button's `WM_DRAWITEM` stayed | 7 contexts a second in a duel: 1,300 an hour, each a few hundred bytes and a slot | `user32.c`, `gdi.c` | `EndPaint` and `ReleaseDC` give them back unless the window's class has `CS_OWNDC` (Windows' rule: that class has one for good); the others are given back by whoever made them |
| **`LoadCursor`, `LoadIcon`, `LoadAccelerators`** made a new object for every call | 500 a minute in a duel | `user32.c` | the same handle for the same resource, as Windows' |

None of these showed in `leaks`'s first report on the pre-fix runtime except the first two: the objects of the table and the contexts are *reachable* (the table still points at them), so only counting them could find them (`gdi objects N in a table of M`, below).

## How it was measured

- `PORT_HEAP_LOG=SECONDS` (and the control command `heap`): a line on stderr every SECONDS, `host: malloc N KiB in M blocks, gdi objects L in a table of T (pen 3, brush 5, ...)` from the window's thread, and when the game allocates, `heap: top ..., in use ..., free ..., in use by size ...` from the game's thread (the guest's heap, `guest.c`). The host figure is the allocator's own count (`malloc_zone_statistics` on macOS), so it does not move when the system compresses idle pages, as `ps`'s resident size does (one of the runs below dropped from 100 to 64 MiB by itself at minute 25).
- `tools/soak/soak.py --endless` (new): one duel with both lives held at 9999, nothing attacks, nothing concedes, so the duel runs until the run is over; the other modes end a duel in 3 to 9 turns, which is not a curve. 36 minutes, `rss.csv` once a minute, the log of `PORT_HEAP_LOG` beside it.
- `leaks PID` with `MallocStackLogging=1` in the game's environment (`SOAK_ENV="MallocStackLogging=1"`) names the allocation site of what is unreachable: the thread records and the contexts' copies. (`leaks` without stack logging, `vmmap -summary` and `sample` stopped answering on this machine after a `leaks` was killed in the middle of a scan, for every process, and did not recover while this was written: the later numbers are the runtime's own.)

## The curves (Magic: The Gathering 1.0, the saved game's duel against a Sorcerer, `--endless`, 36 minutes each)

CURVES_1_0

Host malloc is the memory the runtime itself asks for; rss is the resident size `ps` reports. "old" is the runtime of this branch's base with the heap line added; "threads and SaveDC fixed" the first two rows of the table; "all fixed" this branch.
**The guest's heap (the game's `malloc`) in these duels: 16 MiB in use after the first minutes and 17.7 MiB at the end of 36 minutes, with 23 turns played: it does not grow with the duel.** Free blocks do not coalesce in the runtime's allocator (`guest.c`: first fit, a freed block is only marked free), which could matter to a program that allocates blocks of growing sizes; none of the programs here does.

## Spells of the Ancients 2.15

SOTA_CURVES

## Not fixed, and not the game's

- A **window that is destroyed** leaves its `Window` record (about 1 KiB with its strings): 12 a minute in a duel, 15 KiB a minute. Code holds `Window *` across guest calls that can destroy the window (`DestroyWindow` calls the procedure, which may destroy others), and the record was never freed so that a stale pointer finds a dead window and not freed memory. Freeing it needs those places looked at one by one.
- The **guest's heap does not coalesce** free blocks and finds a block by a linear first-fit scan (above).
- The **device context made for a `CS_OWNDC` window** is never given back (a fresh one each `GetDC`, as before: Windows hands out the same one each time, with its state, and making the runtime do that changes what the game sees).
- **Palettes, a screen-sized bitmap in `CreateDCA`** and the timer table (`mmt`, a slot for every `timeSetEvent`) keep what they had.

## The Draw Phase stuck state and `Minit.c line 1598 AddCard error`

Looked for, not found: three endless duels of 36 minutes (23, 15 and 13 turns), the Sorcerer's Naf's Asp among them, never sat on `Fast Effects?...Draw Phase` and never showed the assertion (no `Assertion Error` message box, no `STUCK` event). That says only that the endless duel does not reach the state ([draw-phase-stuck.md](draw-phase-stuck.md) saw it 13 times in about 570 long Linux duels in which the player's life ran out). Nothing was changed about either.

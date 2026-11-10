# Where the memory of a long run went

**The growth of a long duel (1 to 4 MiB a minute, [duel-ux.md](duel-ux.md) "Resident memory") was not the game's. It was the runtime's: six leaks, found with `leaks`, an endless duel and counters, all fixed, each with a test.** The game's own heap does not grow in a duel at all
(the flat line in the table below), and its own growth in Spells of the Ancients 2.15 is a different thing (the 2.15 section). Measured on macOS (Apple Silicon), 800x600, SDL's dummy drivers, `PORT_HEAP_LOG=30`.

## What was leaking

| what | how much | where | fix |
|---|---|---|---|
| a **record for every finished guest thread**. A multimedia timer starts a thread for each of its callbacks (about 24 a second in a duel) and `new_thread` reused the slot of a finished one by overwriting its pointer | 256 bytes each: 0.35 MiB/min | `sched.c` | a record is freed when its slot is reused and nothing names it any more (`refs`: the handle of `CreateThread`, a timer's last callback, a wait); the exiting thread says it is done with its record only when it has detached |
| the **copies `SaveDC` makes**, dropped by `RestoreDC` without being freed (a window procedure of the game, 0x4958b1 in `MAGIC.EXE`, saves a device context on each message it handles) | 192 bytes each: about 0.25 MiB/min | `gdi.c` | freed |
| **pens, brushes, regions, fonts, bitmaps**: `DeleteObject` marked the slot unused and left the memory, the table never used the slot again. A pen or a brush for every tile of a world: 12 million of them making a Spells of the Ancients world in 12 seconds | 660 MiB of the host's memory, for the rest of the run, in 2.15's new game (25 MiB now) | `gdi.c` | `DeleteObject` frees them and the slot is used again; the stock objects, a font or bitmap that is selected into a context, palettes (one may be the system palette) and cursors are left alone |
| a **DIB section's pixels**, in the guest's heap, were never given back at `DeleteObject` | the game's picture buffers | `gdi.c` | given back, after the last 8 MiB of them have waited (a program that draws once more through a pointer it still has finds its pixels) |
| the **device contexts a window's paint makes**: `BeginPaint` made one and `EndPaint` did nothing; `ReleaseDC` kept a window's own; the context for a `WM_ERASEBKGND` and for an owner-draw button's `WM_DRAWITEM` stayed | 7 contexts a second in a duel (25,000 an hour), each a few hundred bytes and a slot | `user32.c`, `gdi.c` | `EndPaint` and `ReleaseDC` give them back unless the window's class has `CS_OWNDC` (Windows' rule: that class has one for good); the others are given back by whoever made them |
| **`LoadCursor`, `LoadIcon`, `LoadAccelerators`** made a new object for every call | about 50 a minute in a duel | `user32.c` | the same handle for the same resource, as Windows' |

`leaks` reported the thread records, the `SaveDC` copies and (a dozen a minute, not fixed) the windows; the rest are *reachable* (the object table still points at them), so only counting them found them (`gdi objects N in a table of M (pen 3, ...)` in `PORT_HEAP_LOG`'s line): at the end of a 36-minute duel before the fixes the table held 19,726 live objects, mostly contexts, now 268.

## How it was measured

- `PORT_HEAP_LOG=SECONDS` (and the control command `heap`): a line on stderr every SECONDS, `host: malloc N KiB in M blocks, gdi objects L in a table of T (pen 3, brush 5, ...)` from the window's thread, and when the game allocates, `heap: top ..., in use ..., free ..., in use by size ...` from the game's thread (the guest's heap, `guest.c`). The host figure is the allocator's own count (`malloc_zone_statistics` on macOS), so it does not move when the system compresses idle pages, as `ps`'s resident size does (one of the runs below dropped from 100 to 64 MiB by itself at minute 25).
- `tools/soak/soak.py --endless` (new): one duel with both lives held at 9999, nothing attacks, nothing concedes, so the duel runs until the run is over; the other modes end a duel in 3 to 9 turns, which is not a curve. 36 minutes, `rss.csv` once a minute, the log of `PORT_HEAP_LOG` beside it.
- `leaks PID` with `MallocStackLogging=1` in the game's environment (`SOAK_ENV="MallocStackLogging=1"`) names the allocation site of what is unreachable: the thread records and the contexts' copies. (`leaks` without stack logging, `vmmap -summary` and `sample` stopped answering on this machine after a `leaks` was killed in the middle of a scan, for every process, and did not recover while this was written: the later numbers are the runtime's own.)

## The curves (Magic: The Gathering 1.0, the saved game's duel against a Sorcerer, `--endless`, 36 minutes each)

| minute | old host / rss MiB | threads and SaveDC fixed host / rss MiB | all fixed host / rss MiB |
|---|---|---|---|
| 0 | 47 / 90 | 48 / 90 | 46 / 89 |
| 3 | 51 / 99 | 49 / 92 | 48 / 93 |
| 6 | 56 / 105 | 48 / 94 | 48 / 94 |
| 9 | 59 / 109 | 49 / 99 | 48 / 98 |
| 12 | 61 / 110 | 50 / 99 | 48 / 96 |
| 15 | 65 / 113 | 50 / 100 | 49 / 97 |
| 18 | 68 / 119 | 51 / 100 | 49 / 98 |
| 21 | 71 / 122 | 51 / 100 | 49 / 98 |
| 24 | 73 / 124 | 51 / 101 | 49 / 99 |
| 27 | 76 / 127 | 52 / 101 | 49 / 99 |
| 30 | 80 / 128 | 52 / 101 | 49 / 99 |
| 33 | 82 / 130 | 52 / 102 | 49 / 99 |
| 36 | - / 133 | - / 102 | - / 99 |

- old: host malloc after minute 10: +0.98 MiB/min; rss after minute 10: +0.97 MiB/min; gdi objects (live in table) at the end: -
- threads and SaveDC fixed: host malloc after minute 10: +0.12 MiB/min; rss after minute 10: +0.10 MiB/min; gdi objects (live in table) at the end: -
- all fixed: host malloc after minute 10: +0.03 MiB/min; rss after minute 10: +0.04 MiB/min; gdi objects (live in table) at the end: 268 in 271

Host malloc is the memory the runtime itself asks for; rss is the resident size `ps` reports. "old" is the runtime of this branch's base with the heap line added; "threads and SaveDC fixed" the first two rows of the table; "all fixed" this branch.
**The guest's heap (the game's `malloc`) in these duels: 16 MiB in use after the first minutes and 17.7 MiB at the end of 36 minutes, with 23 to 30 turns played: it does not grow with the duel.** Free blocks do not coalesce in the runtime's allocator (`guest.c`: first fit, a freed block is only marked free), which could matter to a program that allocates blocks of growing sizes; none of the programs here does.

## Spells of the Ancients 2.15

**Starting a new game** (the world is made): the runtime's own memory went from **404 to 662 MiB** to **25 MiB** (the process, `ps` resident size at 42 s: 454 MiB before, **80 MiB** after), because the world generator makes and deletes a pen or a brush for every tile (12,006,802 objects in the table of one new game, 110 of them live: the third leak above). A Spells of the Ancients process is now about as large as a 1.0 one.

**A monkey run of 32 minutes** (`sota_soak.py --mode monkey`, random clicks and keys at 100 or so places of the world), resident size in MiB:

| run | at 1 min | at 10 min | at 20 min | at 30 min | note |
|---|---|---|---|---|---|
| before (`sota_base`) | 454 | 486 | 502 | 531 | |
| threads and SaveDC fixed (`sota_new2`) | 460 | 491 | 501 | 508 | the 404 MiB of the world is still in it |
| all fixed (`sota_f`) | 81 | 118 | 149 | 187 | |

The last row grows by 3.4 MiB a minute after the tenth, and it is not a leak: the monkey's random keys open the **"Status Screen Options" dialog again and again** (a shortcut the game takes while that dialog's own loop is running, so each is opened on top of the last): `windows` counted 1,566 live windows, 260 of them that dialog with its 3 buttons and 2 labels, at the 18th minute, and the guest's heap holds the game's own 31 to 47 MiB (in use, from 27 at the start of the monkey) for them. Nothing frees what the game does not close. A person does not do this; the 1.0 curves above, a duel played with the mouse, are the ones to read. A 2.15 duel's curve could not be had here: `sota_soak.py --mode duels` ended after 50 seconds in both runs tried (the process was stopped from outside; not looked into).

2.15's **guest heap** grows with the places visited, in blocks of 64 KiB to several MiB (a picture for each place): 27.5 MiB in use at the start, 44 to 47 MiB 27 minutes later with free blocks under 6 MiB, so it is live data of the game's, not fragmentation. How much of it the game would give back on the original machine was not looked at (the DIB sections' pixels now go back when the section is deleted; before, they never did).

## Not fixed, and not the game's

- A **window that is destroyed** leaves its `Window` record (about 1 KiB with its strings): 12 a minute in a duel, 15 KiB a minute. Code holds `Window *` across guest calls that can destroy the window (`DestroyWindow` calls the procedure, which may destroy others), and the record was never freed so that a stale pointer finds a dead window and not freed memory. Freeing it needs those places looked at one by one.
- The **guest's heap does not coalesce** free blocks and finds a block by a linear first-fit scan (above).
- The **device context made for a `CS_OWNDC` window** is never given back (a fresh one each `GetDC`, as before: Windows hands out the same one each time, with its state, and making the runtime do that changes what the game sees).
- **Palettes, a screen-sized bitmap in `CreateDCA`** and the timer table (`mmt`, a slot for every `timeSetEvent`) keep what they had.

## The Draw Phase stuck state and `Minit.c line 1598 AddCard error`

Looked for, not found: five endless duels of 36 minutes (15, 23, 11, 13 and 30 turns), the Sorcerer's Naf's Asp among them, never sat on `Fast Effects?...Draw Phase` and never showed the assertion (no `Assertion Error` message box, no `STUCK` event). That says only that the endless duel does not reach the state ([draw-phase-stuck.md](draw-phase-stuck.md) saw it 13 times in about 570 long Linux duels in which the player's life ran out). Nothing was changed about either.

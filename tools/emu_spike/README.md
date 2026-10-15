# emu_spike: the original game in an emulated Windows

`winemu` runs the 1997 executables (MAGIC.EXE, DUEL.EXE, DECK.EXE) from your own copy in `sources/installed/Magic` on Unicorn, with
Win32, GDI, USER, KERNEL32 and the C runtime written in Python. Nothing from the game is in the repository. Writes go to
`sources/emu_overlay`, so the installed copy is never changed.

    pip install -r requirements.txt         # unicorn, pefile, numpy, pillow, pygame-ce (for --live)
    cd tools/emu_spike

## Play it

    python3 -m winemu.run --live            # a window; mouse and keyboard

Title screen in about 8 s, a new game's overworld in about 20 s. **Resume Game** loads the autosave the game makes at a wizard's door
(click it at the title: about 45 s to the "Duel / Pay gold" choice), and a duel starts from there: coin toss, start-of-duel dialog,
then the board; lands and phases (the bar under the board advances them) work, right-click a card for its menu ("View in full card" shows it in the left panel). The sound effects, the coin-toss movie (`winemu/movie.py`: the AVI decoded on the host, with its sound) and the music play (`winemu/magsnd.py` is a host version of the game's sound library on pygame.mixer; `EMU_NO_AUDIO=1` mutes; the music is on the game CD, which the install does not copy: run `python3 install_cd_music.py` once, see below), the dialogs are drawn plainly, and the AI thinks at emulator speed.

`--live` implies `--accel` (the card-text keyword search, the card-window test and three waiting loops as Python, `winemu/accel.py`) and `--host-sound`. Environment:
`LIVE_TICK_MS` (default 10; 0 = counted slices, 35 times slower but the simplest), `LIVE_FALLBACK_MS`, `LIVE_PRESS_SLICES`, `LIVE_STATS=1`.
See `winemu/live.py` for how slices, the clock and input work, and `docs/PORT_STRATEGY.md` for why.

### Music

The game plays its music from the CD (`sound\locmus0.wav` ... the duel tune, the castle themes), not from the install. Copy it once from your disc image:

    python3 install_cd_music.py            # reads the .iso in sources/Magic_The_Gathering_ISO (macOS mounts it read only)
    python3 install_cd_music.py /Volumes/MTG   # or a mounted CD / any folder with a Sound folder

The files go to `sources/emu_overlay/Program/Sound` (git-ignored). `MAGSND_LOG=1` logs what the game loads and plays.

## Without a screen

`live_drive.py` posts real input events to the live window under SDL's dummy video driver and saves frames as PNG, from a script or a
command file you append to while it runs (see its docstring). This is how the live mode is tested.

## Scripted runs (no window)

    python3 -m winemu.run --seconds 60 --script "20:click 230 308;25:shot a;30:key 13 13"

`--script` ops (`click`, `key`, `shot`, `state`, `inject`, ...), `--native` (host the native layer, `tools/lift`), `--profile`, `--break`,
`--watch`, `--dump-windows`, `--dump-bitmaps`: see `python3 -m winemu.run --help`.

## Debugging aids (environment)

| | |
|---|---|
| `EMU_OVERLAY=DIR` | where the game's writes (saves) go instead of `sources/emu_overlay`; copy that folder first to start from your saves. Runs side by side need one each |
| `EMU_SRAND=N` | every `srand` seeds with N (the game seeds from the clock) |
| `EMU_REGCHECK=1` | report an import or a guest callback that changes EBP/EBX/ESI/EDI |
| `EMU_PROCTRACE=ADDR[,ADDR]` | the last instructions of that guest callback if it changed them |
| `EMU_PEEK=ADDR[,ADDR]` | print all registers each time the guest reaches ADDR |
| `EMU_CALL_HASH=N`, `EMU_CALL_DETAIL=A:B` | running hash of the import calls (compare two runs), and the calls A..B in detail |
| `MAGSND_LOG=1`, `MAGVID_LOG=1` | log what the game loads and plays through the host sound and video libraries |
| `GDI_DEBUG=1` | log mouse routing and blits |
| `PALDBG=1` | log every `RealizePalette` (which DC, window class and palette handle) |
| `PAL_LEGACY=1` | let any DC's `RealizePalette` set the system palette (the old rule) |

Do not read the guest's registers from another thread while it runs: it corrupts it (use Python-side state only).

## What works (checked in the live window)

| | |
|---|---|
| Start-up | title in about 8 s; a new game's overworld in about 20 s; **Resume Game** loads the autosave (about 45 s) |
| Overworld | walking, villages (Buy Cards, Edit deck/Sell cards, Begin a Quest, buy food), towers (trivia, tolls, duels), world map, City Info, wizard sheet and journal |
| Quests | accept in a village, deliver (a delivery from Windlass Village to Sahrmal's Bazaar was completed and paid a blue amulet and a mana link) |
| Duels | coin toss with its movie, start dialogs, lands, creatures, auras and targeted spells (target prompt with Cancel), attacking, blocking, damage assignment, the opponent's spell popups, game over and the ante |
| Deck editor | shows the deck, double click moves cards both ways, colour/type filters, Stats, right-click menus, Deck1-3 slots (kept with the game's save), Exit |
| Saves | right-click the map, Save, slot, name, Enter; Load Saved Game at the title. Files go to `sources/emu_overlay/Program` |
| Sound | effects, music from the CD (`install_cd_music.py`), the coin-toss movie and the ending movie (Indeo 4 through `ffmpeg`) |

Over about 45 minutes of soak play (four runs, walking, towers and duels) there were no emulator errors and memory stayed near 610 MB.

## The native layer on MAGIC.EXE (Phase B)

The native functions (`src/native`: spell stack, card queries, event contexts, the AI search's state and evaluation) and the AI
search's own functions, lifted from machine code, now run in the game you play, MAGIC.EXE, not only in DUEL.EXE.
`src/native/layout.c` has MAGIC's addresses, `native_host.py` picks the layout and library from the executable, and
`tools/lift/ai_functions_magic.txt` lists the 59 search functions at their MAGIC addresses (each is the twin of a DUEL function) and their hot callers (below). Build the library from MAGIC's own machine code (the generated C and the library are git-ignored):

    python3 tools/lift/gen_handlers.py --program magic --exe sources/installed/Magic/Program/MAGIC.EXE --out sources/generated/lift_magic_ai \
        --no-handlers --extra-file tools/lift/ai_functions_magic.txt
    make -C tools/difftest host GEN=../../sources/generated/lift_magic_ai BUILD=build_magic_ai
    NATIVE_LIB=tools/difftest/build_magic_ai/libnative_host.dylib python3 live_drive.py --native ...     # or: -m winemu.run --live --native

(`GEN=../../sources/generated/lift_magic BUILD=build_magic`, generated without `--extra-file`, gives a library of the natives only,
which is what MAGIC uses by default.)

What runs in C: 28 of the 30 native functions (`memcpy` and `memset` are imports in MAGIC.EXE), 77 lifted functions, and these C runtime and
Win32 imports when lifted code calls them (`lift_bridge.c`: without that every call went out to a Python handler, and the hosted code
waited on a thread each time): `rand` (the seed lives in guest memory so a stopped call puts it back), `memcpy`, `memset`, `strcpy`,
`strcat`, `strlen`, `strcmp`, `abs`, `GetTickCount` and the game's timer driver (`DeviceIoControl` on MPSTIME.VXD). The code calls
most of these through a one-instruction thunk, so the thunks are registered too. The clock reaches C through two words in guest
memory that the machine rewrites wherever `vt` changes (`Machine.publish_clock`), so C reads what the guest would have read.

`tools/lift/ai_functions_magic.txt` lists, besides the 59 search functions, the guest functions that called them most and the ones
they called out to most. `HOST_CALLERS=1` prints them from a hosted run: the guest addresses that call a hosted function
(`[callers]`), which guest functions hosted code calls out to (`hosted code calls out to`), and which hosted functions had to run again
on a thread for it. Lifting a caller only pays when what it calls is in C too: a lifted function that calls out on every call is run
twice (the attempt is undone, then it runs on a thread that waits for each guest call), which costs more than the original. So the
list grew in rounds: lift the callers, look at what the hosted code now calls out to, lift that, until the thread runs are rare.

After a third round, 772 of the 307,000 hosted calls in the scripted duel still ran on a thread (UI and sound callouts), 1 s of the run.
A profile of that run (240 virtual seconds, 242 s real) showed 202 s inside Unicorn running the guest and under 1 s in the C
functions: what was left was the guest's own code, and the first of that to go is the search driver, below.

The search driver (`0x501f50`, 15 KB) is lifted too, which needed two things. It polls the game's timer driver for its time budget (50 or
200 ms), and the guest's clock only moves between slices, so a driver that runs in C would see it stand still and never stop. The
C side therefore lets hosted code see the clock advance: in a run that charges the clock (`--native-costs`) it jumps by the work
done once that work reaches what is left of the running slice (where the original's slice, and its clock update, would have
ended: the first search ends after 6,808 evaluations, the original's 6,926); in a live run it advances by the real time since the
guest last published it (`lift_bridge.c`, `host_set_clock_model`). And it must not be tried first: the driver ends every search with
a debug line (`sprintf` and `OutputDebugStringA` go out to the guest), which would abort the attempt, undo a whole search and run
it again on a thread; `NATIVE_THREAD_ONLY` (default `501f50`) runs it on a thread from the start, where those rare calls out are cheap.
While it runs, the guest's other threads do not (as in the original within a slice, but in a live run a search holds the window for
its 50 to 200 ms budget).

`HOST_CALLERS=1` also showed that a hosted function that calls the guest must pay the clock first: the instructions it has run
so far are what the guest function it calls sees on the clock (and whether its slice ends). `native_host.Ledger` settles them before each
call out (and in exact mode runs them as real instructions before the call: `Machine._start_cont`), and starts counting again
after it.

A bug found on the way, and fixed: `lift_inplace`, the flag that tells the host a call out to the guest comes from lifted code
(whose frame is already built), was a global that stayed set while the guest function ran. When that guest code ran a hosted
function that called out again (the native card scan from the guest's own call), the second call found the flag still set,
took lifted code's registers and built its frame in the wrong place: a return to address 0x34 or 0, or the scan's "nested ten deep"
stop. `call_out` now reads the flag and clears it at once. Before the fix the failure was deterministic in the scripted run (at
virtual second 165, the first search) and intermittent live; after it, that run goes on to second 200 with every native on, and six
live duels with the same seeds (three with the lifted search hosted, three with natives only) ran to the end or to the time limit
without an error.

Checked, on a scripted run (resume, duel, pass turns through the opponent's first turn; fixed seed):
- `--native --native-exact --native-shadow-check` with the natives: 378,999 native calls compared against the lifted machine code of MAGIC.EXE, 0 differ, no memory faults.
- Lifted search functions only, exact mode, C builtins off (`NATIVE_NO_BUILTINS=1`): the running hash of every import call (thread and function, return addresses ignored: `EMU_CALL_HASH_NORET=1`) and the virtual time agree with the original for the first 1.7 million calls, up to the first search (virtual second 165). There the two part, in where a time slice ends: the instruction accounting is a few instructions off per slice.
- C builtins on: with one instruction charged per call (`NATIVE_BUILTIN_BURN`, found by trying 1 to 4), the card slots at virtual second 176, with the search under way, equal the original's; with other values they do not.
- Callers lifted: the card-slot digests at virtual seconds 176 and 185 (exact mode) equal those of the run with only the search functions hosted, and equal the previous release's (`digest` parts 1, 2 and, at 185, 4; part 3 is the query counters again). Neither equals the original's: the exact mode is not exact on MAGIC (a run with only the natives already differs by 10 ms at second 162 and does twice the evaluations), so the comparison that counts is hosted against hosted.
- With the driver: the card-slot digest at virtual 185 (exact mode) equals the earlier rounds'; the slice that ends near 176 ends 0.5 s earlier (the clock model), so that digest differs in time, not in state taken at a common time. Three live duels (seeds 51 to 53) played through (two lost, one at the time limit) with no error; their searches ran 60 to 1,300 evaluations, as before.
- Three live duels (autopilot, seeds 31 to 33) with everything hosted ran to the end (lost, as the starter deck does) with no error and no memory fault.
- Not shown equal: the query-counter words (`digest` part 3) differ from the original in every hosted run; their meaning is not known.

Speed, on the same script, charged as the original is (`--native --native-costs FILE` from `--native-calibrate`: the clock is billed the
instructions the replaced code would have run, so the search ends where the original's does and the same number of evaluations is
done). The start-up part varies by 30% between identical runs on this machine, so only the real time from virtual second 150 to 300
is compared:

| | duel part, real seconds | board evaluations | real ms per evaluation |
|---|---|---|---|
| original | 88 | 12,291 | 7.2 |
| natives and the 59 lifted search functions | 78 | 12,607 | 6.2 |
| and the callers lifted (77 functions) | 37, 38 (two runs) | 12,061 | 3.1 |
| and the search driver | 21, 23 (two runs) | 12,443 | 1.7 |

So the search runs 4 times as fast as the original for the same work (the driver took the last of the guest's own code out of it), and 3.6
times as fast as with only the search functions hosted. Before the callers were lifted a profile of the hosted run showed 6.9 million calls from guest code into hosted
functions, each costing a Python call and 11 emulator register accesses (165 s inside Unicorn and 76 s in register reads and
writes); after, most of those calls are made in C.

Without `--native-costs` (the default) nothing bills the clock for hosted work, so the search gets more evaluations in the same
virtual time, about 5 times as many with the callers lifted. In live play that does not matter: the clock is the real one.

In live play the clock is the real one, so none of this shortens the opponent's turn: the AI's search is time-boxed, and hosted
it fits more evaluations in the same box.

### Start-up

A profile of the first 150 virtual seconds of the scripted run (`--profile FILE`, with the functions `tools/lift/fnscan.py` finds in MAGIC.EXE) showed 2.8 billion
guest instructions, and 71% of them were one function: `FUN_00501736(n)`, called once, which spins reading the timer thread's tick count
until it has advanced by n / 2 (an intro delay). Another 7% were the input poll (`FUN_0044b84b`, 8.7 million calls from a title loop
that spins on it). Both now run as Python stand-ins in `accel.py` that sleep instead (the machine runs other threads, jumps its clock in a
scripted run, or waits for the real one live): the screens at virtual 150 and 160 s are byte-identical with and without them
(`ACCEL_SKIP=tick_wait,input_poll` turns them off), and the first 150 virtual seconds take 29 s of real time instead of 140 to 210
(the whole 310-second scripted run, duel included, 59 s instead of about 240). In a live run the same start-up used 31 s of CPU
instead of 63 s over 135 s: a live run is paced by the clock, so what it saves is the core the spins burned, not time.

What is left in start-up is 0.3 billion instructions, almost all of it real work: an LZW decompressor in the MPS_CODE section
(`FUN_0070d300`/`0070d392`, 150 million: it swaps stacks with `xchg esp` and jumps through `pop ebp; jmp ebp`, which the lifter does
not do), dithering and palette code. A live profile shows the emulator asleep for most of the start-up (53 of 83 s in `time.sleep`,
6.5 s in Unicorn), so lifting those would not shorten a live start-up: the game's own waits do.

## Playing tips

- The quest and tower text menus take the keyboard: Down moves the highlight, Enter chooses (a click on a line sometimes does not).
- A tower on the road stops you until you pay its toll (the Pay line shows only if you have the gold) or beat its wizard. With no gold only the duel is offered, and losing it leaves you at the same tower facing a stronger wizard. Selling cards in a village (double click a deck card out, right-click it in the list, Sell) raises toll money.
- Cards in hand are played by clicking their name; lands are tapped by clicking them first. Attack: click your creature in the attackers prompt, Done. Block: click your creature, then the attacker.
- Keep a deck at about 40 cards or more: a shorter one is padded with random basic lands (a 28-card deck was dealt Swamps and Plains that are not in the collection). Leaving the editor with Deck2 or Deck3 active makes duels use that deck, so switch back to Deck1.
- A game saved while standing at a wizard's tower resumes at that tower's prompt; a new game's start varies from run to run (the game seeds from the clock), so use a saved slot for repeatable scripts.

## The test driver and the duel autopilot

`live_drive.py` (see its docstring for every token): clicks, keys, screenshots, window and card listings (`win:`, `hand:`, `cards:`, `texts:`), `call:ADDR,args` to run a guest function, and two duel players:

- `play:SECS` answers the dialogs and plays the top card of the hand each turn; it loses every duel.
- `duel:SECS` (`autoplay.py`, with `winemu/duelview.py` reading the duel from guest memory) plays the game: lands of the colour the hand needs, creatures and the set of spells that spends the most mana (Llanowar Elves and Sisters of the Flame are tapped for mana), helpful auras on its best creature, curses and damage or removal on the opponent's creature it can kill, attacks when enough stays home to survive the opponent's side, blocks (chump blocks when the damage would leave it at 2 life or less), assigns damage to blockers, discards, and prints `RESULT WON/LOST`. It does not play instants held for combat, spells aimed at players or lands, or X spells. With the starter deck it won three of twelve duels against tower wizards, and 0 of 6 (previously 1 of 5) against the red Sorcerer at the Resume Game tower: more play logic made no measurable difference against that opponent.
- Use `EMU_OVERLAY=DIR` (a copy of `sources/emu_overlay`) per run to run several games side by side.

## Known defects (what a player will see)

- The opponent's turn takes 15-30 s. Measured in a live duel (`LIVE_SAMPLE=1` with `live_drive.py duel:`, which prints the import calls made while the prompt bar is empty): the opponent's turn is millions of import calls, not guest computation: 60% were `GetWindowLongA` from the board's message handler scanning its card windows (now replaced by a Python stand-in, `accel.py`), the rest `rand` and `Enter/LeaveCriticalSection` from the AI's search, `SendMessageA` and drawing. So the work left is the search's imports (which a native layer for MAGIC.EXE would make plain C), not only the lifted search functions.
- Sound, music and both movies are checked in the logs and frames, not by ear. The wizards' animation clips on the CD (`StatWin/*.AVI`) were never asked for in a duel. The ending movie was run by calling the game's player directly (`live_drive.py call:`), not by winning the game.
- The dialogs are drawn plainly (a grey panel) when the game does not paint them itself.
- Not tried: the stand-alone deck builder's New/Load/Save deck menu, instants held for combat and X spells (the autopilot does not cast them), trading with another wizard.

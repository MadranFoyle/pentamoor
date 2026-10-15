# Lifting card handlers

The question this answers: can the card handlers (the 383 distinct functions the master card table points at, one
per card behaviour) be turned into native code *mechanically*, and proved right against the original, instead of
being rewritten by hand from decompiled C?

The answer here is a **static recompiler for the integer subset of x86**: it reads a handler's machine code out of
the executable and writes C that performs the same instructions on the same registers and memory. There are no types
or names to guess, which is where hand translation of decompiled code goes wrong. The result is checked the way every
native function in this project is: against vectors recorded from the original running in the emulator.

The lifter finds the functions of a program in its own machine code (`fnscan.py`: the entry point, the calls, tail jumps and
stored function pointers, then the code nothing reaches, which starts like a function). It used to read their starts, sizes and
argument counts from a table made from a decompiler's output; that table and the two tools that needed the decompiled source
(`grow_coverage.py`, `make_inject_script.py`) are no longer in the repository (README, "History"), and the paragraphs below that describe them
are a record of how the handlers were checked.

Nothing generated here is committed. The lifted C is derived from the game's machine code, so it goes under
`sources/generated/` (git-ignored) and only the tools are in the repository.

## Pieces

| File | Job |
|---|---|
| `x86lift.py` | the lifter. Recursive-descent over the function's own instructions (a size from the distance to the next function is sometimes short), one C statement block per instruction, eager flags, calls out through `lift_call`. Refuses (`Unsupported`) rather than guess: indirect jumps and calls, segment overrides, anything outside the integer subset |
| `src/native/lift_rt.h` | what the lifted C compiles against: registers are locals, memory is `G` addressed through `lift_xl`, flag macros, `lift_idiv32` |
| `src/native/lift_tables.h` | the shape of the generated tables (`LIFTED`, `LIFT_CALLEES`) |
| `fnscan.py` | finds the functions of a program in its machine code (starts, sizes, argument counts); `gen_handlers.py` and the tools that attribute an address to a function use it |
| `import_signatures.py` | the calling convention of every function the programs import: the Windows API's argument counts (stdcall, the callee pops) and the C runtime's prototypes (cdecl) |
| `gen_handlers.py` | reads the handler pointers from the master card table, lifts each distinct handler (and, with `--extra-file`, the other functions of `ai_functions.txt`), writes `handlers_gen.c` and `handler_spec.json` (per function: size, instruction count, whether it lifted and why not, argument count, whether it returns a value, the exact functions it calls with argument counts and stack cleanup) |
| `ai_functions.txt` | the functions that are not card handlers and run while the AI is thinking, found with the emulator's `--profile` (below) |
| `compare_hosted.py` | runs the game on the original and with the lifted functions standing in, and compares every import call the guest makes (below) |
| `coverage.py` | how many of the lifted instructions the vectors executed |
| `../difftest/harness_flat.c` | runs a lifted handler on a recorded vector (same line protocol as the native harness) |

## Running it

```
python3 tools/lift/gen_handlers.py --program duel --exe sources/installed/Magic/Program/DUEL.EXE --out sources/generated/lift \
    --extra-file tools/lift/ai_functions.txt     # the AI search's functions too (below); leave it out for the handlers alone
make -C tools/difftest flat

# record: the game runs in the emulator; handlers are called on demand (see below)
python3 tools/lift/make_inject_script.py sources/generated/lift/handler_spec.json --all \     # (no longer in the repository: it needed the decompiled source)
    --base "2:dlgsel 1122 59;2.1:dlgsel 1123 59;3:dlg 1;5:dlg 1158;6:dlg 1;43:cast land" > script.txt
cd tools/emu_spike
LIFT_SPEC=../../sources/generated/lift/handler_spec.json RECORD_HANDLER_SPEC=../../sources/generated/lift/handler_spec.json \
    INJECT_RESTORE=0.07 python3 ../difftest/record_vectors.py OUTDIR 6 --exe ../../sources/installed/Magic/Program/DUEL.EXE \
    --seconds N --script "$(cat script.txt)"

# check
python3 tools/difftest/run_vectors.py --harness tools/difftest/build/harness-flat OUTDIR/Handler_*.json
```

`make_inject_script.py --shard I/N` (removed) split the handlers so several recordings can run in parallel (six at once is fine;
each takes about ten minutes).

## How a handler is recorded

A handler is `handler(player, slot, event)`. Waiting for the game to call each of 383 of them naturally would take
forever, so the emulator's `inject HANDLER EVENT NTH K` script operation calls one on a new guest thread with the
event globals set the way the game's own dispatcher sets them. Two things make that safe and repeatable:

* **The game is put back.** The data section is saved before the call and restored 0.07 virtual seconds later, so one
  handler's effects do not change what the next one sees. A handler still running at that point is stopped.
* **Callees are stubbed.** Handlers call into the UI (prompts, animation, waiting for a click), which cannot work on
  an injected thread. Every function the handler calls is patched for the duration to return `K` at once. The
  recorder sees that return value as the call's result, so the vector says exactly what the lifted code is given
  when it makes the same call. The handler's own logic runs for real; callees are mocked. The injection script
  repeats each (handler, event) with several K so both sides of the branches on a callee's result get exercised.

The recorder also keeps reads of stack slots below ESP that the handler had not written (a local read before it is
set holds whatever the stack held), and writes the entry ESP into the vector as `stack_pointer`.

## What a passing vector means

The harness runs the lifted function twice, with all memory the vector does not define filled with two different bytes,
and the runs must agree. Then it compares the return value, every byte stored outside the stack frame, and every call
made (target and all arguments) with the recording. A pass says: given this memory and these callee results, the C does
what the original machine code did.

It does not say the handler is *understood*. Naming and explaining handlers is still the verified-symbols work; the
point of lifting is that correctness does not wait for it.

## Limits

* A call through the import table is understood for the imports in `KNOWN_IMPORTS` (`Sleep`) only; any other import
  makes the handler refuse. A call through the master table takes its argument count from the recorded call, and
  assumes cdecl, as card handlers are.
* Callees are mocked, so a handler's behaviour is checked up to its calls. Each callee is a function in its own right
  and gets its own vectors.
* What a function leaves below its stack frame is not compared: the recorder keeps the frame as the call found it and the
  harness starts the lifted code with every register zero, so the values it pushes to save the caller's registers differ from
  the original's. Code that reads an uninitialised local later sees the difference (the original game does: see the
  hosting section). The hosted layer starts lifted code with the guest's real registers for that reason.
* The injection reaches the states a one-card board and a handful of events produce. It is a sample of paths, not a
  proof, and the more situations are recorded the better (see Results for how much of the code that is).

## Results

All 383 distinct handlers of DUEL.EXE's master card table (the figures below are from before the six `_sprintf` callers were refused; the vectors of the other 377 are unchanged):

| | |
|---|---|
| lifted to C | **377 of 383**: straight-line and loop code, jump tables, calls through the import table (`Sleep`, nine handlers) and the master card table (one handler) |
| refused | 6: they call `_sprintf`, which takes a variable number of arguments, so a call out with the fixed count of a function with a frame would drop the formatted values (see below) |
| first corpus | 7,323 vectors, events from each handler's own body, callees returning 0, 1 or 2: all match, and run 53% of the lifted instructions |
| grown corpus | about 86,000 more vectors from `grow_coverage.py` (removed; random events, a different result for each function the handler calls, the handler's own card in play, slot fields and other cards' zones filled with arbitrary values, and the globals the handler is gated on set to the values it tests for): all match |
| instructions executed | 70,451 of 82,074 (**85.8%**); 141 handlers fully, every handler at least partly. Four of the nine `Sleep` handlers and the table-call handler have vectors that reach their call; the other five do not yet |
| instruction forms | 188 distinct forms executed; 6 forms (10 instructions) occur only in code no vector reached |

Every vector the harness can run matches the original: return value, every byte stored outside the stack frame, and
every call made with its arguments, under four fills of the memory the vector does not define. The vectors are not
committed (they hold the game's memory); the driver keeps the 904 that each added coverage.

A passing vector proves the instructions it ran, so the remaining 14% is covered only by the lifter translating every
instruction of a given form the same way. What is left is
mostly code behind several conditions at once (a card state, an event, a callee result and a global together) that random
search reaches slowly; `grow_coverage.py` gains about 0.3 points per 25-minute round now, against 5 at the start.

Getting here found and fixed a lot of faults in the test machinery, none of them in the lifter's treatment of the
instructions that were exercised: the harness compared changed bytes instead of stored bytes (a store of the value
already there was invisible), and two fills could agree by luck (`cmp x, 2; jl` gives the same answer under fills of
0x00 and 0xff), so there are four; the recorder missed reads made by the load half of `add [mem], reg` and reads of
stack locals written before use (it now keeps the stack frame as the call found it); stack pointers outside the
harness's memory; a callee-argument limit of eight when one callee takes twenty; a recording that carried on after its
thread was killed and attributed the next call's data to the wrong handler; callee stubs that did not take effect for
functions the game had already run (Unicorn kept the translated original: the cache is now cleared after patching),
which dropped a callee's writes into the caller's locals. Several of these showed up as a handful of vectors that
failed, which is what the differing-vector folder is for. The unit tests (`test_lift.py`) found one lifter bug the
vectors never reached: `push [esp+4]` read its operand after ESP had moved.

## As part of the native layer

The lifted code is also built against the sparse memory image of `src/native/mem.h` (`LIFT_BACKEND_MEM`), where it
shares state with the hand-written native functions. `src/native/lift_bridge.c` routes a lifted function's calls: to a
native function if there is one for that address, to another lifted function, or to the Vm's hook (the difftest harness
replays recorded calls there; hosted in the emulator it would call the original). `native_handler_dispatch` in
`engine.c` is how the native card scan runs a card's handler as lifted code instead of calling out for it.

```
python3 tools/lift/gen_handlers.py --program duel --exe sources/installed/Magic/Program/DUEL.EXE --out sources/generated/lift
make -C tools/difftest lifted                    # build/harness-lifted
python3 tools/difftest/run_vectors.py --harness tools/difftest/build/harness-lifted OUTDIR/Handler_*.json
```

The generated code is derived from the user's own executable, so a build that has not run `gen_handlers.py` does not link
the bridge and the native layer behaves as before.

### What was checked, and how

1. **Each handler on its own** in the native harness (strict memory: a read of a byte nothing defined is a fault): the
   kept vectors of the coverage driver and the first corpus, 2,200+ vectors, all match.
2. **The native scan with the handlers running lifted inside it**, against the original, on boards of arbitrary cards
   (`winemu/run.py` `scan EVENT SEED [K [CARDS]]`: up to a dozen cards with random handlers in play, fields filled with
   arbitrary values, every function a handler can call made to return a value from the seed; recorded with
   `RECORD_LIFTED_HANDLERS=1`, which makes the handlers transparent as nested native calls are). 4,744 scans, all match;
   they reach 382 of the 383 handlers and run about a quarter of the lifted instructions (the handlers' own logic is what the
   per-handler vectors above cover). A native function or lifted handler that the original's real version would
   disagree with shows up here, and the fuzz found two faults of the test setup and one of the bridge (below).
3. **The native functions on the same fuzzed boards** (`callfn ADDR SEED K ARGS...`): 2,362 calls of
   `Magic_QueryCardAttribute`, `Magic_IsManaSource`, `Card_IsInPlay` and `Card_GetColorAndTypeFlags`, and 1,650 of the
   three colour-remap lookups, all match the original. These were verified before only against calls the game made
   by itself; fuzzed boards are a much wider sample.

What the fuzz found: stubbing a function that is also the one under test (or one of the natives, or a handler another
handler calls) made the *original* return early, so the original's recording was wrong, not the native layer; and the
bridge placed the stack frames of lifted code that a native function re-enters (a query scans the cards, which runs
handlers) over the locals of the handler that called it, so a loop counter in a handler was overwritten. The first two
were found by `tools/lift/scan_diff.py`, which runs a failing scan with `LIFT_TRACE` and lines up, handler by handler,
what the lifted run called and what memory held against what the recording says (`RECORD_DUMP`, `RECORD_NATIVE_TRACE`).

## Hosted in the emulator: the game on the native layer

```
make -C tools/difftest host                       # build/libnative_host.dylib, with the generated handlers if there are any
cd tools/emu_spike && python3 -m winemu.run --exe ../../sources/installed/Magic/Program/DUEL.EXE --native --script "..."
```

`--native` replaces the original's native functions (22) and lifted handlers (383) with the native layer, in the running
emulator, at their entry addresses (`winemu/native_host.py`). Each replaced function's first bytes are overwritten with a
jump to a trap in the machine's stub area, which one code hook already watches (a code hook of its own for each of the 405
functions made Unicorn five times slower, and was the whole cost of hosting at first). The native code reads and writes the
guest's memory directly (the machine's memory is host buffers, `Machine.map_region`), and calls the guest for anything not
native by running the guest function and handing its result back. Natives run without a thread when they can: a call that
needs the guest stops, its writes are undone, and it runs again on a worker thread that can wait for the guest. About one
in five calls of the AI's search does. `--native-only NAMES`, `--native-skip NAMES` and `--no-native-handlers` narrow it.

The script op `digest` prints hashes of the card slots and the event state, to compare a run on the original code with a run
on the native layer.

### The guest's clock

The machine charges the guest's clock for the guest's own instructions (a slice that runs to its limit costs the limit
divided by the emulated machine's speed) and for its import calls. A replaced function runs no guest instructions, so
without a charge time passes more slowly for the guest and the time-boxed AI search does about three times the work in the
same virtual seconds (254,000 calls of the card query in 90 virtual seconds on the original, 716,000 hosted). So the work
is charged back. Lifted code executes the original's instructions one for one and counts them; for each hand-written native
function the original's own instructions per call are measured once on the original:

```
python3 -m winemu.run --exe ... --native-calibrate costs.json --script "..."       # the original, with block hooks
python3 -m winemu.run --exe ... --native --native-costs costs.json --script "..."  # hosted, clock charged
```

After each replaced call the instructions it would have taken are owed to the machine, which then runs its slices in
pieces so that one ends when the guest's instructions plus the owed ones reach the limit. With that, the hosted run matches
the original on the pilot duel: outermost calls 254,371 / 73,920 / 114,269 of the card query / scan / in-play test against
254,055 / 72,431 / 99,496, 1,305,591 import calls against 1,305,773, and the same card slots, counts and event globals from
85 s on. It takes 114 s of real time for 90 virtual seconds (the original, with nothing replaced, 88 s for 120).

That agreement is statistical, not exact, and the match of the digests from 85 s on was partly luck: the clock is charged an
average per call of a hand-written native function, the original's thread switches happen after a fixed count of instructions
(`Machine.slice`, 200 million: the AI's two-second search is cut by that, because the clock does not move inside a slice), and
a replaced function can only end a slice where it ends. Charging 6 ms (600,000 instructions) differently moves the cut by two
trials, which changes the plan the AI commits, and from there the game. For a comparison that has to hold exactly, use the
next section.

### Exact hosting: the original's own timeline

`--native-exact` does not owe the clock the instructions a replaced function would have run, it **runs** them: when the
function returns, the guest first executes a counting loop (`jecxz`, `loop $`, `jmp edx` in a page of the stub area the code
hook does not watch) as long as the original's code was. Unicorn then counts them like any others, the 200-million
instruction slices end at the same count as the original's, and so everything the game does with its clock (what the search
does in two seconds, which thread runs next, when a timer fires) is the original's. Lifted code counts the instructions it
executes (one for one), so a lifted function is exact; `Crt_Memcpy` adds the cost of the copy it was asked for (it follows
the original's branches: 959 of 980 measured calls agree exactly, the rest are a backwards copy from an unaligned end
that uses EDX as the caller left it); a hand-written native function is charged its calibrated average and so is not exact
(`compare_hosted.py` leaves those to the original unless asked). The loop runs the instructions at about the speed the emulator
runs the original's, so an exact run takes about twice the original's real time (77 s against 142 s for the pilot duel, 105 s
against 240 s for the red deck); `--native-costs` without `--native-exact` is the faster, approximate mode above (55 s).

It took finding seven things to make the two runs the same, each of which showed as the first import call at which the
hosted game did something else:

* The emulator counts the trap a redirected instruction lands on, so every replaced call cost one more than its original,
  and so does every call out to the original (it returns to a trap): 4 and 1 instructions are taken off the loop.
* A stopped try (a function that turns out to need the guest, which is then run again on a thread) had counted what it
  executed before it stopped. The counters are restored when the write-back is.
* A lifted function calling `Sleep` called the import's slot address as if it were code; a call out through an import slot
  now calls what the slot holds. The original sleeps for 6 ms there, and every later time was 6 ms off.
* A function that calls out used to build the callee a frame of its own below the lifted one, 12 bytes lower than the
  original's, so stack residue lined up differently. The call is now made in place on the frame the lifted code built, with
  the return address slot restored afterwards as a `ret` leaves it, and with the lifted code's registers.
* Lifted code started with every register zero, so what it pushed to save the caller's was zero where the original pushed
  real values. `FUN_00440af9` reads an uninitialised local (`[ebp-4]`, tested for bit 0) that happened to hold
  such a leftover (3 in the original, 0 hosted): it sent a message the hosted run did not, and the runs parted 85 s into the
  duel. Lifted code is now entered with the guest's registers (`lift_in` in `lift_rt.h`), a lifted call passes its own
  registers on (`lift_out`), and the guest's callee-saved registers are put back when a lifted function returns.
* `Crt_Memcpy`, being native, leaves no saves of EBP, EDI and ESI on the stack; it writes them.
* The AI search found one more: a card handler that calls `_sprintf` (above).

```
python3 tools/lift/compare_hosted.py --seconds 90 --script "$(cat script.txt)"
```

runs the script on the original and on the replaced functions (every lifted function, `Crt_Memcpy`) and compares a running
hash of every import call (thread, function, caller) every 5,000 calls with the virtual time to the microsecond, the
digests the script asks for and the totals. If they part it runs both again printing the calls in the first block that
differs, and shows the first that is not the same. On the pilot duel (90 virtual seconds, 1,126,275 import calls) and on a
game against the red AI deck (300 virtual seconds, 1,491,436 calls) **the two are identical, 225 and 298 blocks**, with 438
lifted functions standing in (the 377 handlers and 61 others), about 380,000 replaced calls in the first 60 virtual seconds of the pilot.
Debugging aids that found the above and stay in: `EMU_CALL_HASH=N` and `EMU_CALL_DETAIL=FROM:TO` (the hash and the detail
`compare_hosted.py` uses), `--native-log ADDRS:FILE` (arguments and result of every call of functions, original or hosted),
`EMU_PEEK=ADDR` (the dword at ESP each time the guest reaches `ADDR`: an uninitialised local) and `--watch ADDR:label`.

### Hand-written C for the AI search, and how it is checked

`src/native/ai_state.c` (the game-state snapshots the search saves and restores, `Ai_BeginTrial`) and `src/native/ai_eval.c`
(`Ai_EvaluateBoard` and `Ai_PenalizeCounterattack`, the AI's board score) are hand-written, from the disassembly (the decompiled
bodies hide casts and truncating divisions) with both programs' addresses lined up by comparing their code; the
snapshots are lists of steps read off the machine code of both programs. They are checked four ways, the first being the
usual one:

1. **Vectors** recorded from the original: natural play (12 for the evaluation and counterattack, one per state function) and
   from boards the emulator fuzzes (`callfn`, 60 recorded, 12 kept). The fuzzed boards found two real faults in the first
   version: the evaluation cached a slot's flags where the original reads them again at every test (a query's card handlers can
   change them), and an index the counterattack reads for a creature it did not register in its first pass holds stack garbage in
   the original (now refused as unimplemented). Both programs' remaining differences are paths that depend on such garbage or on
   memory the original overwrites (an aura target outside its table), which the natives stop on (`NATIVE_UNIMPLEMENTED`).
2. **Instruction counts** (`tools/difftest/check_costs.py`): the snapshot natives add the original's instruction count to
   `native_cost_extra` (exact: the code is straight line), checked against the lifted twin of each on the recorded vectors.
3. **Shadow mode** (`--native-shadow` or `--native-shadow-check`): every native function that has a lifted twin (`gen_handlers.py`
   now lifts every native function's machine code as well) is run both ways on every call of a real game, the return value and
   the bytes written outside the stack frame compared, any difference reported, and the twin's result kept, so the run stays the
   original's. On the pilot duel and a game against the red deck, with the hand-written functions of the whole native layer:
   **about 658,000 calls compared in exact mode, 114,000 and 83,000 in check mode (which lets lifted code call the natives whose
   instruction count is only an average), none differ**, and the exact-mode run is identical to the original over 225 blocks of
   5,000 import calls. Line coverage of `ai_eval.c` by the vectors alone is 91%; the real games add the paths the AI takes.
4. `tools/difftest/fuzz_natives.py`: recorded vectors with a few bytes changed, native against twin. Only about a fifth of the
   mutations stay inside the memory the vector has, and none of those differ; it is the weakest of the four.

The AI's instruction costs in a hosted run without the twins (a build from the repository alone) are the calibrated averages of
`--native-costs`, as for the other natives; in shadow mode they are the twin's, exactly.

### Functions that are not card handlers: the AI search

The lifter does not care that a function is a card handler; `gen_handlers.py --extra-file tools/lift/ai_functions.txt` lifts
the functions listed there as well (`--all` tries every function the scan finds: **1,247 of the 1,830 of DUEL.EXE
lift**, counted in the days of the index, the rest call a Win32 function with no signature here, or take their arguments in registers, or use string,
floating-point or other instructions outside the subset). Those functions are verified exactly like the handlers (they are
named `Handler_<address>` too, and the spec marks them `"extra"` with their own argument counts).

Which functions to lift came from profiling the original:

```
python3 -m winemu.run --exe .../DUEL.EXE --seconds 90 --script "$(cat script.txt)" --profile prof.json --profile-gate 0x66aaf4
```

counts the guest's instructions per function found by `fnscan.py` (`--profile-gate` also counts apart while the dword is
set: `0x66aaf4` is `g_IsAiThinking`; `--profile-callers ADDR,...` reports who calls a function and with what). On the pilot
duel the AI's search ran 156 million instructions in 90 virtual seconds, and where they went was not where the AI's own
functions are: **56% in the C runtime's `memcpy`** (the whole-game snapshot the search restores before every trial is 30
copies, 46 KB in all; `Ai_BeginTrial` runs 2,500 times), 9% in the turn loop `FUN_00426c70` (15 KB, calls the UI),
6% `Ai_EvaluateBoard`, 3% `Duel_UpdateBoardState`, and a tail of 75 smaller functions. The memcpy is native now
(`src/native/crt.c`, below); 67 of the rest lift (`ai_functions.txt`), including `Ai_BeginTrial`, the save and restore of the
game state, `Ai_EvaluateBoard`, `Ai_PenalizeCounterattack`, `Ai_ChooseCardToPlay`, `Ai_ChooseChainResponse`,
`Duel_ChooseTarget` and the combat damage step. Not lifted: the turn loop (a Win32 call), `Duel_UpdateBoardState` and the
function that draws (`SendMessageA`, indirect calls), `_memset` (`rep stosd`).

628 vectors recorded from natural play of the pilot duel (nothing injected: these functions run as the game runs them) all
match, for 65 functions. They run 39% of those functions' instructions: the vectors reach what one duel does. The stronger
evidence is the next section.

What lifting the wider set found, and fixed:

* **Functions that take arguments in registers** (`__fastcall`, hand-written assembly): lifted code starts with every register
  zero, so a function that reads ECX on entry would be silently mistranslated. `x86lift.py` now follows which registers are
  written before they are read and refuses a function that reads one first (and a function that calls one: `lift_call`
  passes stack arguments only). None of the 383 handlers is affected.
* **Variadic callees.** A call out passes the argument count the function has, which for `_sprintf(buf, fmt, ...)` is
  two. A lifted handler that formats a string would pass the format and none of the values, and the vectors cannot tell
  (they record the call with two arguments and replay it). Six card handlers call `_sprintf`; they are now refused, and so is
  any function that calls `_printf`, `_sscanf` or the others (`VARIADIC` in `gen_handlers.py`, by address). None of the six ran in the
  pilot duel or in any vector run that matched the original, which is why this went unseen.
* Argument counts: a callee's count is what its frame reads and what its `ret imm16`
  pops (extra arguments are harmless, missing ones are not).
* A function that never sets EAX returns what the caller left there; its vector says `"return_bits": 0` (not compared). The
  lifter works out which functions these are (EAX is not written on every path to a `ret`).

## Growing the coverage

```
python3 tools/lift/grow_coverage.py --out DIR --hours 6     # removed: it needed the decompiled source
```

Records in `--workers` emulators at once (each spends its first few minutes playing the game up to a board it can inject
on), checks every vector through the lifted code with coverage on, keeps the ones that executed something new in
`DIR/keep`, and puts any vector the lifted code does not match in `DIR/fail` with the harness's message. It can be
stopped and started again. Each round aims at the handlers with the most uncovered instructions: the globals a handler
compares (and the slot fields, and the event codes) are found in its lifted code, so injections set them to what it
tests for. An emulator that stops producing vectors (the game wedged on some state) is cut off and only its own chunk
is lost.

## Coverage of a corpus

```
cc -O1 -DLIFT_TRACK_WRITES -DLIFT_COVERAGE -w -Isrc/native -Isources/generated/lift -o tools/difftest/build/harness-flat-cov \
    tools/difftest/harness_flat.c sources/generated/lift/handlers_gen.c
FLAT_COV=cov.txt python3 tools/difftest/run_vectors.py --harness tools/difftest/build/harness-flat-cov OUTDIR/Handler_*.json
python3 tools/lift/coverage.py sources/generated/lift/handlers_gen.c cov.txt
```

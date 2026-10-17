# Lifter gaps: what is not lifted, and why that is (now) nothing

`gen_handlers.py --program magic --all --no-handlers` used to end with "2018 distinct handlers: 2002 lifted, 16 not". It now prints
every function it did not lift and what stands in for it:

    2009 distinct handlers: 1998 lifted, 11 not
    11 of them are covered another way, 0 are not

The numbers changed because 9 functions that were not functions were dropped from the 2018 and 3 real ones were added.

## The 16, one by one (MAGIC.EXE)

| address | what it is | reason it was refused | what stands in for it |
|---|---|---|---|
| 0x513bd0 | `_chkstk` | takes `eax` | inline code at each of its 7 callers (`INTRINSICS`) |
| 0x513c50 | `_allshl` | takes `eax`, `ecx`, `edx` | inline code at its one caller |
| 0x70d000, 0x70d245, 0x70d300, 0x70d392, 0x70d484 | the picture decompressor (`MPS_CODE` section) | `lodsw`, `ecx` argument, indirect `jmp` | `src/port/lzw.c` overrides 0x70d000, 0x70d1fc, 0x70d484; the other three are only called from those |
| 0x48bda1, 0x4f1cfa, 0x4f207a, 0x4f211a | the second half of a function | read `eax` (and `ecx`) on entry | the index splits a function after a `nop` that follows its prologue (`mov eax,[esp+0x14]; sub esp,N; test eax,eax; nop`), so the "function" starts in the middle and reads what its first half set up. Its real entry is the row before: 0x4f2110 is in the index (and lifts whole); 0x48bd90, 0x4f1cf0 and 0x4f2070 are not in it, nothing calls them, and they are now lifted as `head_...` functions |
| 0x43c0ab, 0x46b9c3, 0x4bb965, 0x4bb9b7, 0x50cc0b | "the five bogus addresses" | read `eax`, a call to a non-function, undecodable | not functions. The discovery of functions the index does not list matched an `0xe8` that is the ModRM byte of another instruction (`c7 45 e8 ..`, `c1 e8 10`), or a displacement, or the middle of a `jmp [import]` thunk table, as a `call rel32` |

Seven more of that kind were being lifted as functions (0x46b95d, 0x49411b, 0x4efa1c, 0x50cbfc, 0x50ccb6, 0x50d29b, 0x510fa5: junk C for bytes in the
middle of other functions). They were harmless (nothing real calls them) but they were wrong. 12 false functions in all go.

## What changed in the tools

*(`claim_instructions`, `discover_unlisted` and `split_head` below worked from a function table made by a decompiler. They were replaced by `tools/lift/fnscan.py`, which finds the functions in the program's own code with the same ideas: follow the control flow, take a call target or a stored pointer only where it is the first byte of an instruction nothing else owns, and make the head of a function split by a `nop` one function. The notes are kept as they were written.)*

* `gen_handlers.py` `discover_unlisted`: a hit counts only if the byte that made it is the first byte of an instruction of a function the lifter
  followed (`claim_instructions`: the control flow of every index row, which reaches code the index's sizes leave out), or is in code no
  function claims, and the function it names does not start in code a function owns. 12 false functions go; the 4 found ones that stay are
  0x48b450, 0x4f25b0, 0x510f90 and 0x4056b2 (below).
* `split_head`: a row that is only the tail of a function (reads `eax`/`ecx`/`edx` on entry, preceded by code that falls into it from the `int3` fill)
  gets its real entry lifted. The spec says `tail_of` for the row and the list says "second half of the function at ..., lifted there".
* The unlifted list names, for each function, what covers it (`override`, `intrinsic`, `tail_of`) or says NOT COVERED. `covered_rows`/`missing_rows`.
* `x86lift.Lifter.constants`: every immediate, displacement and branch target of the instructions that were lifted.
* `gen_dll.py --index`, which took a decompiler-made function table and reported every row the closure had not lifted and whether anything live named it (a `call`/`jmp`/pointer),
  is gone with the table: `fnscan.py` finds the functions in the code now (the first run of it was compared with that table: the same reachable functions, and
  the functions nothing reaches differ).
* Tests in `test_lift.py` (46 when this was written, 56 test functions now): the nop-split function lifted whole and run against its machine code (4 inputs), the head found from the tail,
  the `e8`-inside-an-instruction not taken for a call (and the real call beside it taken), `constants`, and the index report.

## The other programs

* **DUEL.EXE** (gen_dll closure from the entry point, the exports and the pointers in code and data): 1,696 functions lifted, 0 failed. The index
  has 1,836 rows; **409 are not lifted: 405 are named by nothing that was lifted (no call, no jump, no pointer in code or data) and 4 are the same
  helpers as above** (`_chkstk` 0x4ddee0, `_allshl` 0x4de220, and the two picture decompressor entries 0x6c5000, 0x6c5484 that `lzw.c` overrides).
  The 405 are the program's statically linked library and unused code (the MAGSND wrappers 0x43db27..0x43dfda, the AI's old variants).
  A first look that scanned the raw bytes of the whole extent found 4 more "live" rows (0x42e217, 0x450b87, 0x450bb7, 0x4e7740): their only callers are
  in code inside a lifted function's extent that nothing jumps to (the function at 0x42b6b0 has a case body after an unconditional `jmp`), so they are
  dead too. Hence `constants` is taken from the instructions that were lifted, not from the extent.
* **DECK.EXE** (161 functions), **STATWIN.DLL** (335), **DECKDLL.DLL** (1,013), **MAGVID.DLL** (511): the closure lifts everything it reaches, 0 refused. There is
  no list of what it did not reach; `gen_dll` finds pointers only where the target looks like a function start after `int3`
  fill (a first byte in `PROLOGUES`), so a callback whose first instruction is not in that list would be missed. Not measured.

## Which of it can ever run

None of the 11 that remain, as functions: the two runtime helpers are replaced at their call sites, the decompressor is overridden (the title screen
decodes the same pixels with the override), and the four tails have either no caller (0x48bda1, 0x4f1cfa, 0x4f207a: no `call`
or pointer names their heads 0x48bd90, 0x4f1cf0, 0x4f2070; the last two are in the wavelet card art code next to the variant at 0x4f2110 that is used) or are the second half of 0x4f2110, whose head lifted. If one were ever called, `lift_call` ends the run with "a call to
0x........, which is neither a lifted function nor an import", so a gap is loud, not silent. No other function of MAGIC.EXE is named by a
pointer in data or code without being a lifted entry (checked over all the dwords of every section: every hit is the interior of a lifted function, i.e. a coincidence).

One thing left as it is: 0x4056b2 is a found "function" whose only caller (0x4056ad, `call` to the next instruction) is in code after an unconditional
jump that nothing reaches. It lifts, nothing runs it.

## Regression

Lifted again into `sources/generated/agent_lifter_magic` (MAGIC.EXE with STATWIN and DECKDLL), `agent_lifter_deck`, `agent_lifter_duel`: the sets of lifted
functions differ from before only by the 12 removed and the 3 heads added; every other function's C is produced by the same code as before. Built
(`make -C src/port GEN=../../sources/generated/agent_lifter_magic BUILD=build_agent`), `make -C src/port test` (101/39/45/30), the title screen (0 pixels
differ from the emulator's), and a scripted run to a duel and a few phases of turns.

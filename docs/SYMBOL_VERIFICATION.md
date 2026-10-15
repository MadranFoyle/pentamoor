# Symbol verification log

Each entry records what the live oracle (see [ORACLE_VM.md](ORACLE_VM.md)) showed about a name
or comment produced by the bulk rename pass. A name is only trustworthy once it appears here as
**verified**. Everything else is a hypothesis. (Paths below such as `src/magic/...`, `magic/...`, `duel/function_index.csv` or `symbols/...` name files of the upstream project's decompiled tree, which was in this repository when the entries were written and has since been removed: README, "History".)

## Magic_DrawCardPhase (MAGIC.EXE 0x00474c7f): WRONG LABEL, it preloads duel sound effects

Claim in the repo: `src/magic/sid/Magic.c` says it executes the draw step.

Oracle evidence (`probe_drawcard.py`, `probe_duel_start.py`, all on the live game):

1. From cold boot to the main menu the function never ran.
2. Clicking "Duel a Sorcerer" runs it during the duel-loading splash (a card back on a black
   screen). Once its page was resident, the code at `0x00474c7f` matched the `MAGIC.EXE` file
   byte for byte (`55 8b ec 81 ec 2c 01 00`), so this is `MAGIC.EXE` and not `DUEL.EXE`.
   It was called from `0x00495bbc`, inside `Palette_Subsystem_00495958` (0x495958 to 0x495cde;
   that name is also an unverified auto-label).
3. The 20 names it loads (table at `0x00525788`, read from the binary) are duel sound effects:
   artifact, buried, draw, enchant, endphase, endturn, instant, interupt, GREY, BLACK, BLUE,
   GREEN, RED, WHITE, lifeloss, sacrfice, sorcery, summon, tap, untap. One of them is `draw.wav`,
   which probably explains the mislabel.

Verdict: it is a duel sound-effects preloader run once when a duel starts. Renamed to
`Duel_PreloadSoundEffects` (and its invented doc comment corrected) everywhere in the repo.

Method notes (they cost real time):

- **Code pages are demand-loaded.** The first time a function runs, a breakpoint on it can fire
  before its page is in memory, and reading the code bytes fails with `E14`. Step over the
  breakpoint (this takes the page fault), re-arm, continue: the retried instruction hits again
  with readable code. `GDBRemote.resume` already does the step-over.
- **Every program loads at `0x00400000`**, so an address alone does not identify the program.
  Compare code bytes with the file in `sources/installed/Magic/Program` before trusting a hit.

## FUN_0046f5d1 (MAGIC.EXE): VERIFIED, the real draw-a-card function

Found statically, confirmed on the live game (`probe_duel_start.py`, saved in
`sources/oracle/probe_draw_result.log`).

Static: 1130 bytes; references the string "Draw a card Phase" (`0x00525af8`), "No more cards, you
lose", and "Draw Card"; chooses a card slot for the player (a random one for the AI), marks the slot
as drawn (`flags |= 1`), increments the hand counter, and is the *only* caller of the sound player
with sound id 2 (`draw.wav`), at `0x0046fa01`.

Dynamic, during a duel (opponent's draw step):

1. `0x0046f5d1` was entered, code bytes matching `MAGIC.EXE`, `arg0 = 1` (the opponent), called
   from `0x00502e28`.
2. Immediately afterwards the sound player was entered with sound id 2 from `0x0046fa06`, the
   instruction right after the call at `0x0046fa01` inside this function.

Also seen on screen, outside the probe: my hand went 7 -> 8 on my own draw step, and the game then
forced a discard back to 7 in the discard phase.

Name: `Magic_ExecuteDrawPhase(player)`. The rename maps already proposed this name, and the
`src/` tree and `include/magic.h` already used it; the raw `magic/` files still called the function
`FUN_0046f5d1`, which is now renamed to match. The oracle supports the name, since the function is
the per-player draw step. Only the opponent's draw was caught by the debugger; the player-0 branch
is verified by reading the code only.

## Magic_UpkeepPhase (MAGIC.EXE 0x0047496b): WRONG LABEL, it is the sound player

788 bytes. Takes a sound id (0..0x2f), looks it up in the 20-name table at `0x00525788` (ids
0x14+ use further tables), loads the `.wav` on demand and plays it. Verified on the live game: it
is called with id 2 from inside the draw function. Renamed to `Duel_PlaySoundById` (prototype fixed
to `int Duel_PlaySoundById(int sound_id)`; the header had `void(void)`). The parameter is named `player` in the
decompilation (in `DUEL.EXE`'s twin, `Sound_PlayTrackById`) but it is a sound id.

## Both programs run the duel engine (verified on the live game)

`MAGIC.EXE` and `DUEL.EXE` contain the same duel engine (identical function sizes: draw 1130
bytes, sound player 788, preloader 143). Which one runs depends on how the game is started:

- **Campaign duels run inside `MAGIC.EXE`.** In two runs a campaign duel loaded and played through
  the coin toss and several turns while breakpoints on `DUEL.EXE`'s entry point (`0x004dea30`) and
  on its draw and sound functions never fired.
- **Launching `DUEL.EXE` from its own shortcut runs the engine from `DUEL.EXE`.** With breakpoints
  on its twins (code bytes checked against the file each time), one run showed:
  1. entry point `0x004dea30` at t=16 s;
  2. sound preloader twin `0x0048d320` at t=18 s (called from `0x00437e96`);
  3. after the coin toss and the deal, the draw twin `0x00487ce1` with `arg0 = 0` (my draw step)
     at t=47 s, called from `0x004a6773`;
  4. immediately after, the sound player twin `0x0048d00c` with sound id 2, returning to
     `0x00488116`, which is the instruction after the call at `0x00488111` found by static
     analysis. The prediction matched exactly.

This closes the earlier caveat that the `DUEL.EXE` entry-point breakpoint might never fire: it does
when `DUEL.EXE` is really launched, so its silence during campaign duels is real. It also covers
both branches of the draw function: the opponent's draw (`arg0 = 1`) in `MAGIC.EXE`, mine
(`arg0 = 0`) in `DUEL.EXE`. The repo's claim that `MAGIC.EXE` is only the overworld and `DUEL.EXE`
the combat engine is wrong: both contain and run the combat engine.

Raw evidence: `sources/oracle/probe_draw_result.log` (MAGIC.EXE) and
`sources/oracle/probe_duelexe_result.log` (DUEL.EXE); both git-ignored.

Method notes added:

- The gdbstub can deliver an asynchronous stop notice (`T02...`) before the reply to your first
  command when you attach to a running guest, and a queued notice must be dropped when you
  resume. Both are handled in `GDBRemote`.
- Mouse: the guest drops events that arrive too fast while the game is loading, so movement is
  paced (12 ms per 2-count step), and a click needs a hold of about 0.35 s to register.

## Renames applied (MAGIC.EXE)

| Address | Was | Now | Status |
|---|---|---|---|
| `0x0047496b` | `Magic_UpkeepPhase` | `Duel_PlaySoundById` | verified, live |
| `0x00474c7f` | `Magic_DrawCardPhase` | `Duel_PreloadSoundEffects` | verified, live |
| `0x0046f5d1` | `FUN_0046f5d1` | `Magic_ExecuteDrawPhase` | verified, live (opponent's draw) |

Applied across the generated sources, headers, symbol CSVs and generator scripts, so re-running the
pipeline does not bring the wrong names back. The `OldName` column of the rename maps keeps the
original `FUN_` names, which is what the Ghidra sync looks up.

The same three functions in `DUEL.EXE`, now observed running too (see above):

| Address | Was | Now | Status |
|---|---|---|---|
| `0x00487ce1` | `FUN_00487ce1` | `Magic_ExecuteDrawPhase` | verified, live (my draw) |
| `0x0048d320` | `FUN_0048d320` | `Duel_PreloadSoundEffects` | verified, live |
| `0x0048d00c` | `Sound_PlayTrackById` | unchanged (name is fine) | verified, live; parameter renamed `player` -> `sound_id` |

The engine functions keep the `Magic_`/`Duel_` names they have in `MAGIC.EXE`, so the same code has the
same name in both programs. The sound player has two names for the same code
(`Duel_PlaySoundById` and `Sound_PlayTrackById`); unifying them would touch unrelated uses of the
latter, so it is left for later.

## Globals renamed (MAGIC.EXE): VERIFIED live

The card-event dispatcher stores its first two arguments in two globals, clears a third and runs the
card handlers, which use the pair to index the card table with the strides `0x5b20` (player) and
`0x120` (slot). Renamed on that static evidence, then checked with write watchpoints on all three
during a real duel (`probe_globals.py`; raw events in the git-ignored
`sources/oracle/probe_globals.json`).

| Address | Was | Now | Meaning |
|---|---|---|---|
| `0x006b2534` | `g_OverworldPlayerCoordX` | `g_EventSourcePlayer` | player that owns the card the event is about |
| `0x0070100c` | `g_OverworldMapGrid` | `g_EventSourceSlot` | that card's slot |
| `0x0068a660` | `g_ActivePalette` | `g_CardEventResult` | flags and counters the handlers accumulate |

Live result: 600 writes captured over about three minutes, from the deal and start of the duel.

- The event dispatcher at `0x00473179` (`ebp+8..` = player, slot, event code, target slot) wrote
  `g_EventSourcePlayer` 93 times, and **93 of 93** equalled its first argument; it wrote
  `g_EventSourceSlot` 92 times and **92 of 92** equalled its second. Players seen: 0 and 1. Slots
  seen: 1 to 5. Event codes seen: 50, 51, 52, 60.
- `g_CardEventResult` values written by it were 1, 3, 0, `0x200000`, 15, 271, 164 and 19: a mix of
  small counts and single flag bits, as "flags and counters" predicts. It was 0 at the start of
  each dispatch, so 0 means nothing was flagged.
- Three other functions write all three globals, presumably from their own arguments and not
  analysed: `FUN_00473e69`, `Pic_Subsystem_004485d6` and `Magic_TriggerCardEvent`.

Limits: one duel, the first three minutes, four event codes, capped at 600 events. It confirms
what the globals hold, not the meaning of each event code or each bit of the result.

Three more members of the same 7-value context are now named, on static evidence only (not
watched live):

| Address | Was | Now | Evidence |
|---|---|---|---|
| `0x006a4f70` | `DAT_006a4f70` | `g_EventCardId` | assigned `g_CardSlot_CardId[player][slot]` by the dispatcher; saved and restored with the frame |
| `0x007006c8` | `DAT_007006c8` | `g_EventTargetPlayer` | defaults to `1 - player` (the opponent) in two places; the 3 handlers that test it compare it with their player argument |
| `0x006b2d5c` | `DAT_006b2d5c` | `g_EventTargetSlot` | defaults to `-1` (none) in three places; set from the dispatcher's `target_slot`; the same 3 handlers compare it with their slot argument, never crossed |

`DAT_006b2fe4` (the seventh member) and `g_PlayerManaPool` are handled in the next section; they are
now `g_EventCardColorMask` and `g_CurrentStepCode`. These `DAT_` names are address-based and other
programs have different variables at the same addresses, so the renames were confined to
`magic/` and `src/magic/`.

### Two more mislabels found by the same run (renamed)

The event context is a **stack** of 7-value frames (0x28 bytes each, 32 deep, depth in
`DAT_0052577c`) so events can nest:

| Address | Called | Really | Evidence |
|---|---|---|---|
| `0x00474428` | `Magic_PayManaCost` -> `Magic_PushEventContext` | **push** the event context | copies the 7 globals into the next frame and increments the depth (guarded at 32) |
| `0x004744de` | `Magic_TapCardForMana` -> `Magic_PopEventContext` | **pop** the event context | decrements the depth and restores the 7 globals from that frame |
| `0x00473179` | `Card_TapForMana` -> `Magic_QueryCardAttribute` | computes a card's modified value (see the next section; an earlier revision of this table called it the dispatcher) | live: writes the (player, slot) globals from its arguments 93/93 and 92/92 times |

The dispatcher calls the push first (when the depth counter `DAT_0063ee18` is non-zero), sets the
globals from its arguments and runs the handlers. The pop ran 98 times and always restored
`g_CardEventResult` to 0, and restored `(player, slot)` to `(0, 0)` 68 times and `(1, 3)` 30 times:
outer event contexts being put back, as a stack predicts. None of these functions deals with mana.
Renamed everywhere (sources, headers, all four symbol maps, generator scripts); the query's
parameters are now `(player, slot, event_code, target_slot)` (they were `x, y, width`), and the
prototypes of the push and pop are `void(void)` (the header had made-up parameters). `DUEL.EXE`'s
maps also list a `Card_TapForMana` at `0x00473179`; that is a different program and was left alone.

## The step code and the other event-context writers (MAGIC.EXE)

The step runner and `g_CurrentStepCode` are **verified live** (`probe_steps.py`, next section). The other
names in this section rest on static evidence.

| Address | Was | Now | Evidence |
|---|---|---|---|
| `0x006ff4c0` | `g_PlayerManaPool` | `g_CurrentStepCode` | only ever set to `-1` or to a step code; assigned from the argument by `Magic_RunTurnStep` and set back to `-1` afterwards; compared with constants in the range `0xc9`-`0xdc`; `Magic_BroadcastCardEventInStep` returns early when it is below 200 |
| `0x0047624f` | `FUN_0047624f` | `Magic_RunTurnStep(player, step_code, step_name, repeat_while_active)` | saves the step context, sets `g_CurrentStepCode`, runs the step handler in a loop until nobody responds (`Pic_Subsystem_004458b0`), restores; every call site passes a step name string |
| `0x00473e69` | `FUN_00473e69` (the maps say `Rules_ApplyContinuousDamage`) | `Magic_BroadcastCardEvent(player, slot, event_code)` | push context, set the source to `(player, slot)`, the target to `(1 - player, -1)`, clear the result, run `Magic_ScanCards(event_code)`, restore the step code, pop, return the result |
| `0x004485d6` | `Pic_Subsystem_004485d6` | `Magic_BroadcastCardEventInStep(player, slot, event_code, event_arg)` | the same scan, but only while a step is running (`g_CurrentStepCode >= 200`); no push or pop; stores its fourth argument at `0x006b2fe8` |
| `0x00473179` | `Magic_DispatchCardEvent` (my earlier name) | `Magic_QueryCardAttribute(player, slot, event_code, target_slot)` | a `switch` over six codes (`0x32` to `0x36`, `0x3c`) computes a value from the card's data, calls `Magic_ScanCards(event_code)` so other cards can adjust `g_CardEventResult`, and returns it; 90 call sites use the codes `0x32` (40), `0x33` (24), `0x34` (22) and `0x3c` (4). What each code measures was established live on the emulator (section below) |
| `0x006b2fe4` | `DAT_006b2fe4` | `g_EventCardColorMask` | a byte copied from offset 6 of the event card's master record. Over the 447 records the values are 1, 2, 4, 8, 16, 32 (63 to 112 cards each) plus a handful of odd ones, and the first five records hold 2, 4, 8, 16 and 32 in order: a colour mask (1 = colourless). Nothing compares it; it is only saved, restored and read from a save file |

`Magic_TriggerCardEvent` keeps its name. It runs the card's own handler (the function pointer at
offset `0x10` of its master record) inside a pushed context. Its parameters are now
`(player, slot, event_code, target_player, target_slot)`; the decompiler had called the last two
`target_slot` and `flags`, but the code stores them in `g_EventTargetPlayer` and `g_EventTargetSlot`.

Step codes, from the call sites that pass a name: `0xc9` Begin Upkeep, `0xcb` End Upkeep, `0xce` Draw
Phase, `0xcf` Draw a card Phase, `0xd9` Choose Attackers, `0xda` Choose Defenders, `0xdc` Pay for
attacker. The live runs added `0xcd` End of Turn, `0xd2` Tapping and `0xd3` Casting.

The last parameter was first called `wait_for_pass`; the code only shows that when it is non-zero the
step is repeated while its handler returns non-zero (and a state mask of `0x30` is set), so it is now
`repeat_while_active`. Live it was 1 for the two draw steps and 0 for the rest.

Still wrong and not renamed: `g_AiSavedPlayerManaPool` (`0x00552938`) is filled with a 0x80-byte
`memcpy` from `0x006ff4d0`, the 32-entry event queue that `Magic_CombatPhase` (which really just
queues an event) appends to, so it is a saved copy of the queue and not of anything mana related.
`DAT_006b2fe8` (the extra event argument) is also unnamed.

### Live result for `Magic_RunTurnStep` and `g_CurrentStepCode`

A breakpoint on `0x0047624f` and a write watchpoint on `0x006ff4c0` during a real duel, stepping through
one turn boundary (77 events; raw log in the git-ignored `sources/oracle/probe_steps_result.log`):

| Step code | Name string | Player | Last arg | Called from |
|---|---|---|---|---|
| `0xcd` | End of Turn | 1, then 0 | 0 | `0x00476220`, `0x0047623d` (`Magic_CleanupPhase`) |
| `0xd2` | Tapping | 0, then 1 | 0 | `0x00476220`, `0x0047623d` (`Magic_CleanupPhase`) |
| `0xc9` | Begin Upkeep | 0 | 0 | `0x00502c75` |
| `0xcb` | End Upkeep | 0 | 0 | `0x00502cc7` |
| `0xce` | Draw Phase | 0 | 1 | `0x00502dc4` |
| `0xcf` | Draw a card Phase | 0 | 1 | `0x0046f5f9`, inside `Magic_ExecuteDrawPhase` (`0x0046f5d1`) |

- All 8 entries had `MAGIC.EXE`'s code bytes at the function, and `g_CurrentStepCode` was `-1` before every
  one of them (8 of 8).
- It was written with the step code exactly once per entry and set back to `-1` exactly once per entry
  (each of the six values above, `0xcd` and `0xd2` twice, and eight `-1` resets), all by `Magic_RunTurnStep`.
  Every other write in the run (53 of 69) was `-1`, by `Magic_BroadcastCardEvent` (42) or
  `Magic_CleanupPhase` (11), as its save and restore predicts.
- The draw step being called from inside `Magic_ExecuteDrawPhase` confirms that function's name from
  the other side.

Not seen in that run: the combat steps. The combat run below saw them. Still not seen: any nested step
(a step code seen non-negative on entry). What the last argument means beyond "repeat while active" is
still a guess.

### Live result for the combat steps

A second duel, played through to combat on both sides (raw logs in the git-ignored
`sources/oracle/probe_combat3.log` and `probe_sites.log`; the turn loop is `FUN_00501f50`). The opponent
attacked me with Goblin Balloon Brigade, and I attacked with Brothers of Fire; the opponent blocked with
Hurr Jackal and they traded.

| Step | Call | Seen |
|---|---|---|
| `0xd9` "Choose Attackers" | `Magic_RunTurnStep(0, 0xd9, ..., 0)` from the call at `0x0050481e`, code bytes match | on my own attack, with the probe on the three call sites only |
| `0xda` "Choose Defenders" | `Magic_RunTurnStep(0, 0xda, ..., 0)` from `0x00504704`, when the opponent attacked (player = the defender, me) | 3 times |
| `0xdc` "Pay for attacker" | `Magic_RunTurnStep(1, 0xdc, ..., 1)` from `0x00504402` (the attacker's side) | 3 times |

New step codes seen in the same run, all with player 0 and 1 back to back from the spell-chain runner:
`0xd4` "Card leaving play", `0xd5` "Card(s) to Graveyard", `0xd6` "Graveyard order", `0xd7` "Damage Dealing",
`0xcc` "End of Combat". So a combat runs `Pay for attacker`, `Choose Defenders`, `Damage Dealing`, then
`Graveyard order`, `Card(s) to Graveyard` and `End of Combat` when creatures die.

What is not shown in the QEMU run: on my own attack the `0xda` call site was not hit (the blockers were assigned all
the same). **The emulator run closes that gap** (see "Live results from the in-process emulator" below).

Probing note: a breakpoint on `Magic_RunTurnStep` itself is too heavy once a spell chain is open, because
the chain calls it dozens of times a second; use the call sites (`probe_combat_sites.py`) for combat.

## The spell stack (MAGIC.EXE): push and resolve seen live, the rest static

Three functions the rename pass called combat, end-of-turn and discard-to-hand-size are the push, resolve
and drop operations of a stack of pending card events (spells, abilities, triggers). Push and resolve were
watched once on the live game (next section); drop, clear and the AI's save and restore were not.

| Address | Was | Now | Evidence |
|---|---|---|---|
| `0x004751d7` | `Magic_CombatPhase` | `Magic_PushSpellStack(player, slot, event_code, target_slot, flags)` | appends an entry at `g_SpellStackCount` (max 0x20) packing card id, event code and target slot into one word, records `(player, slot)`, then increments the count; for cards with id 5 or more it copies the card's 0x120-byte slot into a free slot as a stand-in object. 12 callers, pushing event codes `0x72` (7 sites), `0x7e` (4) and `0x71` (1) |
| `0x004756a1` | `Magic_EndTurnPhase` | `Magic_ResolveTopSpell()` | decrements the count, reads the entry, and runs the card's handler through `Magic_TriggerCardEvent` (or `Magic_BroadcastCardEventInStep` for event `0x7e`), with special handling for stand-in objects. 8 callers |
| `0x00475bb0` | `Magic_DiscardToHandSize` | `Magic_DropTopSpell()` | decrements the count, clears the stand-in slot if its card id is the placeholder, and writes the `-1` sentinel; runs nothing. 17 callers |
| `0x00474d1e` | `Mem_AllocOrFree_00474d1e` | `Magic_ClearSpellStack()` | sets the count to 0 and the first object to `-1`; one caller |

| Address | Was | Now |
|---|---|---|
| `0x006a3f78` | `DAT_006a3f78` | `g_SpellStackCount` |
| `0x006ff4d0` | `DAT_006ff4d0` | `g_SpellStackEntries` (32 packed words: card id, event code << 16, target slot << 24) |
| `0x006fecc0` | `DAT_006fecc0` | `g_SpellStackObjects` (pairs of `(player, slot)`, terminated by `-1`) |
| `0x006fd3f4` | `DAT_006fd3f4` | `g_StackObjectCardId` (the placeholder card id given to stand-in objects) |
| `0x00552938` | `g_AiSavedPlayerManaPool` | `g_AiSavedSpellStackEntries` (a 0x80-byte `memcpy` of `g_SpellStackEntries`) |

The AI saves and restores the count and entries around its lookahead (`Ai_SaveGameState`,
`Ai_RestoreGameState`, `Ai_PushBoardState`, `Ai_PopBoardState`), which fits a stack. Parallel arrays that
hold the stack entry's toughness, original card id, step code and flags are still unnamed.

`Magic_IsManaSource` (`0x00474389`, was `Magic_ResolveSpellStack`) is a small predicate that tests two flag
bits in a card's master record and never touches the stack. It is called by `Magic_TriggerCardEvent` and the step
handler. Its meaning was found on the emulator (section below): it answers "does this card tap for mana". `g_DuelModeFlags` (was `g_PlayerHandCardCount`), tested with `& 0x224` in `Magic_TriggerCardEvent`, was misnamed too (section below).


### Live result for the spell stack

Breakpoints on the four stack functions during a real duel (`probe_steps.py`; raw log in the git-ignored
`sources/oracle/probe_stack_result.log`), while I played a Mountain from my hand:

| Time | Function | Stack depth on entry | Arguments / caller |
|---|---|---|---|
| 62.0 s | `Magic_PushSpellStack` | 0 | player 0, slot 4, event code 113 (`0x71`), target 0, flags 0; called from `0x0047009e` |
| 63.3 s | `Magic_ResolveTopSpell` | 1 | called from `0x00470db7` |
| 63.6 s | `Magic_RunTurnStep` | | step `0xd3` "Casting", player 0, then player 1 |

- Both had `MAGIC.EXE`'s code bytes. The stack was empty before the push and had one entry before the
  resolve, the pair predicted by the names. `0x71` is one of the three event codes the push is called
  with (`0x72`, `0x7e`, `0x71`), and the one that occurs at a single call site.
- The push took exactly the five arguments `(player, slot, event_code, target_slot, flags)` and the
  slot number 4 matches the card I had just played (the fifth card in play order is not verified).
- The step `0xd3` "Casting" is new to the step-code list.

What this does and does not show: one push and one resolve, both associated with playing a land. The old
names (`Magic_CombatPhase` and `Magic_EndTurnPhase`) were both wrong in any case: neither ran anything to
do with combat or the end of a turn here.

**Later duel, full turns on both sides** (`probe_steps.py ... nowatch`, log `probe_combat2.log` and
`probe_combat3.log`):

- `Magic_ClearSpellStack` is entered once at the start of every turn, from `0x005020ba` with the stack
  empty. Its name is confirmed.
- `Magic_DropTopSpell` was entered from `0x004717b4` with depth 1 or 2 (the top entry dropped rather than run),
  several times while the opponent was casting. Its name is confirmed.
- Push event code `0x71` was pushed for a land, for an artifact (Throne of Bone, slot 1) and for the
  opponent's plays, always from `0x0047009e`. So it is not land-specific: it is the event for a card being
  played or cast. Code `0x72` is pushed from three sites (`0x004bb5e9`, `0x004bd2e9`, `0x004712fe`),
  when a cast is paid (`0x004bb5e9`) and just before a Tapping step (`0x004712fe`); the third is unexplained.
- A cast pushes twice: the `0x71` entry when the card is announced, then a `0x72` entry on top while it is
  paid for. The depth 2 resolves in the log are the `0x72` entries.

Still static only: the AI's save and restore of the entries.

## Names restored (MAGIC.EXE)

30 names that a later pass had replaced with worse ones, each checked against its code: the sound
driver thunks `0x00423980` to `0x00424165` (each tests a driver-mode flag and calls the next slot
of the driver function table, in the order of the old names), `CardTypeFromID` and
`CardIDFromType` (an index and id lookup pair on the master card table) and
`UI_Register_WINBK_ManaPool_004b9120`. `InitSndTrack` (called with `.wav` paths) and `PlaySnd` (called
by the verified sound player) were also seen running. 46 other changed names were left as they were;
a sample of 30 names found about 1 in 5 wrong or misleading and about 1 in 3 unsupported by the code.


## Live results from the in-process emulator (`DUEL.EXE`, 2026-09-26)

`tools/emu_spike` (`docs/PORT_STRATEGY.md`) runs `DUEL.EXE` deterministically and traces functions by address, so the
checks above can be repeated without QEMU. Twin addresses in `DUEL.EXE`: `Magic_RunTurnStep` = `Magic_RunTurnStep`,
`Magic_PushSpellStack` = `Magic_PushSpellStack`, `Magic_DropTopSpell` = `Magic_DropTopSpell` (twin by size; not yet entered),
`Magic_ClearSpellStack` = `Magic_ClearSpellStack`. A scripted game (both players a mono-green deck: Forest,
Llanowar Elves, Durkwood Boars, Killer Bees) gave:

| Action | What the trace showed |
|---|---|
| Play a Forest | `PushSpellStack(0, 2, 113, 0, 0)`: player 0, slot 2, event `0x71` |
| Cast Llanowar Elves, pay with the Forest | `PushSpellStack(0, 0, 113, 0, 0)` when announced, then `PushSpellStack(0, 2, 114, 0, 0)` (event `0x72`, slot of the Forest that paid) |
| Start of each turn | `ClearSpellStack()` once |
| Select the Elves as an attacker (my turn 2) | `RunTurnStep(0, 220, "Pay for attacker", 1)` |
| Press Done on the attack prompt | `RunTurnStep(0, 217, "Choose Attackers", 0)` then `RunTurnStep(0, 218, "Choose Defenders", 0)` for both players, then 212 "Card leaving play", 215 "Damage Dealing", 204 "End of Combat", 205 "End of Turn" |

(Decimal codes: 217 = `0xd9`, 218 = `0xda`, 220 = `0xdc`, 215 = `0xd7`, 212 = `0xd4`, 204 = `0xcc`.) So `0xda` "Choose Defenders" **is**
run on my own attack, for both players back to back, right after "Choose Attackers". Event `0x71` is for announcing a
land or spell, `0x72` when it is paid.

Card slots (verified by printing the hand and matching what was played): a slot's card value is an **index into the
master card table** (base `0x4ff590`, `0x34` bytes per record); the record's first dword is the card id, which
indexes the name-pointer table at `0x618ac4` (`0x98` bytes per entry, pointer first); the record's second dword low byte
is the type (`0x01` land, `0x02` creature, `0x08` spell, `0x04` enchantment, `0x42` artifact creature). Slot flag bits
seen: `0x800` = can be played now, `0x30882`/`0x882` = land or permanent in play untapped, `0x30092` = tapped land,
`0x82` = permanent in play (base), `0x1` = in the hand after it was drawn.

### `Magic_QueryCardAttribute` codes (emulator, 2026-09-26)

`Duel_QueryCardAttribute` (`DUEL.EXE` `0x0048b81a`, twin of `Magic_QueryCardAttribute`, was `Duel_TapCardForMana`) was traced
with its return value over the same scripted game (about 350,000 calls: `--break 0x48b81a:Query:4::ret,card`).
Every card in the game agrees with its master record (record `+0xa` and `+0xc` are the printed power and toughness
shorts, `+0x14` the ability dword, `+6` the colour byte, `8` = green):

| `event_code` | Returns | Seen |
|---|---|---|
| `0x32` (50) | current **power** | Llanowar Elves 1, Durkwood Boars 4, Killer Bees 0, Whirling Dervish 1, Forest 0 |
| `0x33` (51) | current **toughness** | Elves 1, Boars 4, Bees 1, Dervish 1, Forest 0 |
| `0x34` (52) | **ability bitmask** (`0x20` on Killer Bees, the only card with a printed ability here) | 0 for the rest |
| `0x3c` (60) | the card's **current card-table index** (a card that copies or transforms reports the new one) | Elves 56, Boars 61, Bees 323, Dervish 380, Forest 2 |

Codes `0x35` (the slot's own power field) and `0x36` (the colour byte) were not called in this run and stay static-only.
The function name `Magic_QueryCardAttribute` replaces `Magic_QueryCardValue`; it never had anything to do with mana.

### `Magic_IsManaSource` (emulator, 2026-09-26)

`DUEL.EXE` `0x0048ca2a` is the twin (now `Magic_IsManaSource` there too). It returns true when the master record's
dword at `+0x18` has bit `0x1000` set and bit `1` clear. Traced with return values on the same scripted game:

| Card | record `+0x18` | Returned |
|---|---|---|
| Forest | `0x1000` | 1 |
| Llanowar Elves | `0x1000` | 1 |
| Durkwood Boars, Desert Twister, Stream of Life, Tranquility, Whirling Dervish, Aspect of Wolf | `0x0` | 0 |
| Killer Bees | `0x19` | 0 |

So bit `0x1000` marks a card that taps for mana (a land and a mana creature), which fits its uses: the handler call
for events `0x73`/`0x74` is undone when the card is not a mana source. What bit `1` excludes is not established (no card with
`0x1000` and bit `1` together was seen). Also learned: the master record's dword at `+0x10` is the card's own
event-handler function pointer, which `Magic_TriggerCardEvent` calls as `handler(player, slot, event_code)`.

### Globals checked with write watches (emulator, 2026-09-26)

`--watch ADDR:label` logs every change of a guest dword with the writing instruction and its caller. On the scripted
game (`DUEL.EXE` addresses; the MAGIC.EXE global of the same role in brackets):

| Address | Old name | New name | What the watch showed |
|---|---|---|---|
| `0x681eb0` (`0x006a4a08`) | `g_DuelPlayerManaPool` (`g_PlayerHandCardCount`) | `g_DuelModeFlags` | Not a count and not mana: a word of mode bits. See the table below |
| `0x666458` (`0x0068a71c`) | `g_DuelDefendingPlayer` (`g_DefendingPlayer`) | `g_TurnPlayer` | Flips 0 to 1 just before player 1's `Begin Upkeep` and back to 0 before player 0's; it is the player argument of the per-turn function `0x00426c70`, which stores it on entry. It is the player whose turn it is, first in every `RunTurnStep` pair (player 1's turn shows `RunTurnStep(1, 205)` then `(0, 205)`) |
| `0x66642c` | `g_DuelCurrentTurnPhase` | `g_CardEventResult` | Holds card ids (56 Elves, 61 Boars, 323 Bees) set inside the card-attribute query and cleared when the saved event context is popped: the twin of the MAGIC.EXE global of that name |
| `0x68ecb0` | `g_DuelActivePlayer` | `g_EventSourcePlayer` | Set from the first argument of the card-attribute query, saved and restored around it |
| `0x690c48` | `g_DuelActiveCardSlot` | `g_EventSourceSlot` | Not watched; renamed because the query function stores its second argument in it, next to the player global (static) |

Bits of `g_DuelModeFlags`, from the set and clear sites seen (function addresses are `DUEL.EXE`):

| Bit | Seen |
|---|---|
| `0x80` | Set at the start of the main phase, cleared the moment I clicked a card (18.5 s to 43.7 s), set again while waiting to pay (43.75 s to 50.7 s): a player action is awaited |
| `0x20` | Set and cleared inside the card-playing routine `0x00488662` (605 to 780 times), the routine that calls `Magic_PushSpellStack`; also set on the way into the spell-chain window |
| `0x2`, `0x4` | 605 exact cycles during the opponent's turn: `0x2` is set (`0x004afd08`) to ask for a state check; `Pic_Subsystem_004475a4` (`0x0046d497`) clears `0x2`, sets `0x4`, runs "Damage prevention", the "Damage Dealing" step and re-checks, then clears `0x4`. The state-based check (damage and death) is requested with `0x2` and running with `0x4` |
| `0x1`, `0x8`, `0x100` | Written by the turn loop `0x00426c70` and the spell-chain window; meaning not established |

`g_CurrentTurnPhase` (MAGIC.EXE `0x006a49e0`, DUEL.EXE `g_DuelTargetPlayer` `0x00676510`) is used as a player index too, but
it did not change in this game (it stayed the same value), so it is not renamed yet.

### The spell-chain window family (emulator, 2026-09-26)

"Spell Chain" is a popup window of class `MAGICGAME_SpellChainClass` that shows the spell stack as card windows (one
`Spell Card` window per stack object, one `Spell Target Card` window per target), with a small minimized tab of class
`SpellMinimized`. Evidence grades: **natural** = seen in the scripted game; **synthetic** = the original function run in
the emulator on an injected input (a snapshot with targets, or a guest thread calling it), because the scripted game
only cast Elves and the window was up for 18 ms of virtual time per cast; **static** = code reading only.

| MAGIC.EXE / DUEL.EXE | Old name | New name | Evidence |
|---|---|---|---|
| `0x4cf8b6` / `0x4a197e` | `SpellChain_GetCardCount` | `SpellChain_FindEntryIndex` | natural: returns an index (`-1` on an empty chain, `0` for the first entry), never a count |
| `0x4cf965` / `0x4a1a2d` | `SpellChain_UpdateTargetPositions` | `SpellChain_RemoveEntry` | natural: called when the chain empties (52.756 s, 80.019 s); synthetic: count 2 to 1, window gone |
| `0x4cfab2` / `0x4a1b7a` | `SpellChain_HasActiveSpells` | `SpellChain_EntryTargetsMatch` | natural: equal records return 1; synthetic: 2 targets against 1 returns 0 |
| `0x4cfb2f` / (twin shares a name) | `SpellChain_CreateCardSlot` | `SpellChain_InsertEntry` | natural: creates the card window and inserts the record; synthetic: with two targets |
| `0x4cfd68` / `0x4a1e30` | `SpellChain_RemoveCardSlot` | `SpellChain_ClearEntryTargets` | synthetic: destroys only the target windows, the record stays with 0 targets |
| `0x4cfe4d` / (twin shares a name) | `SpellChain_CreateTargetSlot` | `SpellChain_RebuildEntryTargets` | synthetic: 0 targets to 1 |
| `0x4d05e8` / `0x4a26ac` | `SpellChain_SetWindowRect` | `SpellChain_GetContentRect` | synthetic: copies a global rectangle out; no callers in either program (dead code, static) |
| `0x4d0965` / `0x4a2a2f` | `SpellChain_IsVisible` | `SpellChain_MinimizeIfShown` | synthetic: with the chain shown it sends the minimize command and swaps to the tab |
| `0x4d09bd` / `0x4a2a87` | `SpellChain_IsMinimized` | `SpellChain_RestoreIfMinimized` | synthetic: sends the restore command |
| `0x4d0a30` / `0x4521d0` | `SpellChain_GetActiveCount` | `Card_DefaultEventHandler` | `xor eax,eax; ret`; its address is the event-handler pointer (record `+0x10`) of 53 of 447 cards, Durkwood Boars among them (natural); never called |
| `0x4d0a42` / `0x4521e2` | `SpellChain_ProcessTriggerEvent` | `Card_GetColorAndTypeFlags` | synthetic: green creatures return `0x2000`, Forest 0, sorceries `0x102000`, Aspect of Wolf `0x22000`; about 300 static callers, all card handlers |
| `0x4b4a3f` / `0x445f05` | `Ai_EvalAttackCandidate_004b4a3f` | `Duel_RefreshAllWindows` | natural: sends `0x412`, `0x432` and `0x40c` to every game window after each play |

Names that held up (twins renamed to match): `SpellChain_RegisterClass` (natural), `SpellChain_WndProc` (natural),
`SpellChain_UpdateLayout` (natural), `SpellChain_MinimizedWndProc` (synthetic), `SpellChain_CleanupUI` (static).
Two `DUEL.EXE` twins (`0x4a1bf7`, `0x4a1f15`) share one generic name (`Palette_Subsystem_0049608e`) and are not renamed.
In `DUEL.EXE` two *different* functions each carried the names `Glue_Subsystem_004cdb4f` (`0x493e30`, 14,669 bytes, and `0x49fc0f`, 7,410 bytes) and `Glue_Subsystem_004d0602` (`0x49918f` and `0x4a26c6`), because the twin-copying script matched by resemblance. Only `0x49fc0f` and `0x4a26c6` were verified as the spell-chain window procedures and carry the `SpellChain_` names; `0x493e30` and `0x49918f` keep the old generic names until someone checks them.

Structures: a table record is `0x58` bytes (`+0` HWND of the card window, whose window longs 0 and 4 are (player, slot);
`+4` to `+0x50` up to 20 target HWNDs; `+0x54` target count), 100 records at most. A snapshot entry is `0xAC` bytes
(player, slot, 20 target (player, slot) pairs, count), passed by value. Message ids: `0x40c` clear all, `0x412` sync to the
snapshot, `0x432` repaint; `WM_COMMAND` `0x65` minimize, `0x66` restore. Also from the report, static only: the slot byte
called `g_CardSlot_TapState` looks like a target count, not a tap state.

### The AI: a random-rollout search with a recorded plan (emulator, 2026-09-26)

Three scripted runs on `DUEL.EXE` (mirror deck; me against a red AI deck for 560 virtual seconds; a short run reading the
colour counts) with entry, return and write traces. The AI is **not** a set of `Ai_Evaluate...`/`Ai_Choose...` heuristics:

1. When it must act, the turn loop (`0x00426c70`) calls `0x0048b5c9(stage, budget)`. It sets the best score to -9999, sets
   `g_IsAiThinking` to 1 and snapshots the game (`Ai_SaveGameState`).
2. For about 2.0 s of virtual time (`g_IsAiThinking` went 0 to 1 and back exactly 2.0 s later, four times) it runs trials:
   `Ai_BeginTrial` restores the snapshot and clears the trial list, random choices are played and each is logged with
   `Ai_RecordChoice`, then `Ai_EvaluateBoard` scores the board (about 4,000 of each in one search-heavy run). If the score beats
   the best, `Ai_CommitBestPlan` copies the trial list to the best list; the best score only ever rose within a search
   (`-9999, -139, -13, 7, 15, 33`).
3. When the flag drops, the game **replays** the best list: `Ai_ReplayChoice` is called from the same four sites as the
   record function, with the flag at 0, and returns 99 when the list is empty.

| MAGIC.EXE / DUEL.EXE | Old MAGIC name | New name | Evidence |
|---|---|---|---|
| `0x4ab28b` / `0x43064a` | `Ai_EvaluateCreaturePower` | `Ai_RecordChoice` | called only while thinking; records `(mode, packed slot, choice)` |
| `0x4ab3f3` / `0x4307b2` | `Ai_CalcCardAdvantage` | `Ai_ReplayChoice` | same four sites, flag 0; writes 99 on an empty list |
| `0x4ab45f` / `0x43081e` | `Ai_ScoreBoardPosition` | `Ai_CommitBestPlan` | runs right after each best-score rise; copies lists, scores nothing |
| `0x4ab214` / `0x4305d3` | `Ai_GetActivePlayerScore` | `Ai_BeginTrial` | once per trial (6,857 in one run) and at search end |
| `0x4ab1ef` / `0x4305ae` | `Ai_ResetEvaluationState` | `Ai_ClearPlan` | called at turn starts; replays read 99 right after (medium-high) |
| `0x4ab510` / `0x4308cf` | `Ai_Util_004ab510` | `Ai_GetPlanCursor` | returns the list length, which is also the replay cursor |
| `0x4ab552` / `0x430911` | `Ai_SimulateCombatRound` | `Ai_EvaluateBoard` | signed zero-sum score: `EvalBoard(1) = -208` 2,577 times and `EvalBoard(0) = 208` 491 times, range -216 to +208 |
| `0x4abff4` / `0x4313b9` | `Ai_ChooseAttackers` | `Ai_PenalizeCounterattack` | only called from the evaluator; lowers the score by 0 to 2 (medium-high) |
| `0x4acc20` / `0x43e0e0` | `Ai_AssignCombatDamage` | `Duel_ShowStartOfDuelDialog` | opens the "Start of duel" dialog at 3.012 s and returns when the script pressed its button |
| `0x4a99a0` / `0x42ed60` | `Palette_Subsystem_004a99a0` | `Ai_ChooseCardToPlay` | returns slots 2, 3 or -1; produces the mode 1 and 2 records |
| `0x4468dc` / `0x46c7d0` | `Pic_Subsystem_004468dc` | `Ai_ChooseChainResponse` | returns -1 (pass) or a slot; the mode 4 records (medium-high) |
| `0x405802` / `0x41e2a2` | `Action_ValidateTarget_*` | `Duel_ChooseTarget` | the mode 3 (target) record site is inside it (medium-high) |

Globals: `g_AiDecisionScore` (MAGIC `0x6ff55c`, DUEL `0x68f2c8`) is not a score. It is the chosen value (an option index, a
colour index in mode 1, or 99 for "no recorded choice"), now `g_AiChoiceValue`. DUEL's `g_DuelDebugModeFlag` (`0x66aaf4`) is
`g_IsAiThinking`. Modes (`0x4f3c6c`): 1 land to play (choice = colour index, -2 = none), 2 card to cast or permanent to
activate, 3 target, 4 spell-chain response. Packed slot (`0x68f0bc`): low byte slot, `0x100` player 1, `0x1000` cast or play from
hand, `0x2000` activate, `0x4000` target pick, `0xffffffff` none. Best score `0x667990`; search stage `0x666400` (1 main
phase, 2 blockers, 3 and 4 end-of-turn steps and responses, 8 declare attackers; 5 to 7 not decoded); trial list length and
replay cursor are one variable (`0x50b37c`).

The `Ai_` prefix on the start-of-duel dialog code and
on most `Ai_Subsystem_*` after `0x4acb7f` in MAGIC.EXE is unsupported: the real `sid\Ai.c` assert string appears only in
`Ai_SaveGameState`. `Ai_SaveGameState`, `Ai_RestoreGameState` and the board-state push and pop (a one-deep snapshot, not a
stack) held up.

### Round 3: the five reported-but-unapplied AI names, resolved with the twin table (2026-09-27)

the twin table (built after round 2) gives each of the five its `DUEL.EXE` twin at score 1.0000 or 0.9392,
well clear of the runner-up, confirming the addresses the live traces already used. Reading each MAGIC.EXE body against that
confirms the earlier reports:

| MAGIC.EXE / DUEL.EXE | Old name | New name | Evidence |
|---|---|---|---|
| `0x4acb7f` / `0x431f41` (twin 1.0000) | `Ai_FilterValidBlockers` | `Ai_GetLandColorMasks` | body: builds two bitmasks from two 5-entry per-colour count arrays (one per player) and returns them through two out-parameters; natural, 498 calls (round 2) |
| `0x4ab35e` / `0x43071d` (twin 1.0000) | `Ai_GetOpponentPlayerScore` | `Ai_PeekPlannedSlot` | body: while not thinking, reads the planned-list slot at `cursor + offset` and masks it to 12 bits (the slot without the mode bits); natural, 54 calls (round 2) |
| `0x4ab3a9` / `0x430768` (twin 1.0000) | `Ai_CalcLifeAdvantage` | `Ai_PeekPlannedChoice` | body: while not thinking, reads the planned-list choice at `cursor + offset`, substituting 0 for 99; never entered live (static only) |
| `0x4ab525` / `0x4308e4` (twin 1.0000) | `Ai_Util_004ab525` | `Ai_PlanCursorBack` | body: decrements the plan cursor by one; natural, entered once (round 2) |
| `0x4ac940` / `0x431d05` (twin 0.6616, weak) | `Ai_ChooseBlockers` | `Ai_FormatPlanDebugText` | body (MAGIC.EXE side, not the weak twin): builds a text dump of the plan list with `strcat`/`_itoa`, the strings "Cast" and " -> target" among them; only runs with a debug flag, never entered live (static only) |
| `0x4cc9c5` / `0x451482` (twin 0.9392) | `Ai_Subsystem_004cc9c5` | `Duel_UpdateBoardState` | the `DUEL.EXE` side already had this name (in the split sources and the rename maps, but not yet in `duel/function_index.csv`, `duel/symbols.csv` or `duel/source_mapping.csv`, fixed here); natural, called `(0, 255)` (round 2) |

`Ai_PeekPlannedChoice` and `Ai_FormatPlanDebugText` are still never entered live; the other four now have live evidence
from round 2 plus a confirmed body. `make check` clean, `make test` passes.

### Colour, palette and sound helpers (emulator, 2026-09-26)

Grades as above; **injected** means the real function was called on real emulator state from a driver, because the game did not
reach it (the scripted `MAGIC.EXE` run never left the title screen).

| MAGIC.EXE / DUEL.EXE | Old name | New name | Evidence |
|---|---|---|---|
| `0x494310` / `0x43504d` | `Color_QuantizeRGBToPalette` | `Color_RGBToOctreePath` | returns nothing; fills 8 bytes, one per bit plane from the top, each a 3-bit octree child index (high, middle, low colour byte = 1, 2, 4): `0xffffff` gives `[7,7,7,7,7,7,7,7]`. Identical output on both programs (injected); natural in the duel, about 14,000 calls from the dither routine |
| `0x493e70` / `0x434a43` | `Catalog_LoadPaletteMap` | `Palette_LoadTRFile` | natural: `('todpal.tr', 0)` at 1.357 s in `MAGIC.EXE` and `('...DUELPALall.TR', '...DUEL.plogpal')` in the duel; returns a Win32 `LOGPALETTE` (version `0x300`, 256 entries, entry 197 = 14 8 8, matching the `.TR` line `197 - 14 8 8`); a second path overlays a binary palette. Nothing in it is a catalog |
| `0x50da40` / none | `Surface_GetPixelPtr` | `Surface_GetPixelValue` | injected on real surfaces: returns the palette index (`0xec`, `0xc3`, `0x58`, matching a direct read of the 8-bit DIB), never a pointer. Not `Surface_GetPixel` because a 198-byte sibling at `0x50d6f0` already has that name |
| `0x4ebe1a` / none | `Adventure_Audio_StopEffectChannel` | `Adventure_Audio_PlayTrack` | injected: builds volume, 22050 Hz and pan words and calls the play-sound function (`PlaySnd(track=16, ...)`); the real stop is `StopSnd`. That flag bit 0 means "loop" (so flags 0 is play once) is static only |
| `0x4ec32f` / none | `Adventure_Audio_PlayFootstep` | `Adventure_Audio_LoadWalkAndBirdSounds` | natural: at 1.357 s, right after `Sound_Init`, it makes 15 sound-track loads (`kwalkl.wav` to `wwalkr.wav` on tracks 0 to 9, `kbird1.wav` to `wbird1.wav` on tracks 10 to 14) and plays nothing |

`Color_FindNearestPaletteIndex` (`0x494540`) held up on behaviour (injected: colour `0x0e0808` gives index 197, whose table entry is exactly that
colour), but it was never entered naturally and nothing appears to call it (a scan for calls and pointers found none), so it
looks like dead code in both programs. Its distance metric swaps two colour channels compared with the other nearest-colour search
(a latent bug in dead code). Live in the duel, `PlaySnd(11|18|17|5)` play GREEN.wav, tap.wav, summon.wav and endturn.wav, the tracks
`InitSndTrack` loaded in that order.

### Round 2: red-deck game (emulator, 2026-09-26)

Me (mono-green) against the red AI deck (index 46: Lightning Bolt, Goblin Balloon Brigade, Sisters of the Flame) for 560 virtual
seconds, about 750,000 traced lines.

- **`Magic_DropTopSpell`** (`FUN_0048e251` in `DUEL.EXE`, exact body twin: decrement the stack count, free the stack object's card
  slot if it still holds the object's card, clear the entry) was entered 213 times, always from `0x0048921a` inside the card-casting
  routine, and always while `g_IsAiThinking` was 1: a `PushSpellStack(.., 113, ..)` announce right after a "Trying to cast ..." prompt,
  then the drop. It undoes an announced cast that the AI's search then abandons. Not seen in a real, non-AI play. The `DUEL.EXE`
  twin is now named `Magic_DropTopSpell`, and its globals `g_SpellStackCount`, `g_SpellStackObjects` and `g_StackObjectCardId` (DUEL-side files only).
- **Attribute query codes `0x35` and `0x36`:** still never called, over about 650,000 calls (codes seen: `0x32` 169,078; `0x33` 170,709;
  `0x34` 140,893; `0x3c` 167,961). They stay static-only, and are probably not reached in ordinary play.
- **`Combat_ResolveBlocksAndDamage`** (was `Ai_EvalAttackCandidate_004c864d`; `DUEL.EXE` `0x0047740d`): entered 20 times, every time
  from `0x004297c7` in the turn loop, right after the `Assign Blockers` phase prompt and before `Damage prevention` and the
  `Damage Dealing` step, in every combat of the game (mine and the AI's). Its argument was always 1. It does the blocker assignment
  and hands over to damage; the exact split with the damage step is not established.
- **AI search stages** (`0x666400`, set by `0x0048b5c9(stage, budget)` and cleared at `0x0043063b`): stage 1 (budget 45 or 90, eight searches),
  3 (30, four), 4 (30, two), 2 (30, one), 8 (30, one). Stages 5 to 7 did not occur. The budget is not the search length: every search lasted 2.0 s.
- **Still not entered:** the plan-to-text dump (`0x431d05`), the planned-choice peek (`0x430768`) and the log-message function (`0x45102d`), so
  their names stay static-only. The planned-slot peek (`0x43071d`, 54 entries) and the colour-mask function (`0x431f41`, 498 entries)
  behaved as reported before; both are now applied (`Ai_PeekPlannedSlot`, `Ai_GetLandColorMasks`), see round 3 below.

### Round 4: the `Mana_CanAffordCost` / `CardTarget_PromptTargetCreature` conflict, resolved (2026-09-27)

the twin propagation report flagged `MAGIC.EXE 0x004e69ac` (`CardTarget_PromptTargetCreature`, unverified) and its twin
`DUEL.EXE 0x00468130` (`Mana_CanAffordCost`, also unverified, and already the name the split sources used) as a
conflict: the same code, two different guesses, neither checked. Reading both bodies (they are identical apart from
addresses) settles it: there is no mana or cost arithmetic anywhere in the function. It defaults its `min_val` argument
to 2, calls the colour/type-flags function and the target picker (`Duel_ChooseTarget`), and on a successful pick stores
the chosen (player, slot) into an "attached aura" slot pair and a combat-target field, incrementing a per-slot counter.
That is a target prompt, not a cost check. `Mana_CanAffordCost` is replaced by `CardTarget_PromptTargetCreature`
everywhere (static evidence only; not yet seen live).

Found along the way, not yet resolved: `duel/duel_all.c` and `duel/duel_unified.c` both contain a function literally
named `Mana_GetCardColorRequirement`, immediately after `Card_DefaultEventHandler`, whose own header comment claims the
same address as `Card_GetColorAndTypeFlags` (`0x004521e2`) even though its body is different (several more locals) and
it is called from many sites in `duel_all.c` that `Card_GetColorAndTypeFlags` is not. `duel/function_index.csv` has no
row named `Mana_GetCardColorRequirement` at any address, so either the header comment's address is stale (most likely,
given other index/source drift found this session) or two functions have been merged under one name by an earlier pass.
Not investigated further; the call sites still compile as calls to a declared prototype (`duel/duel_unified.h`), so
nothing is broken, just unresolved. (Resolved in Round 5 below: the address was right and the name stale.)

### Round 5: the `Mana_GetCardColorRequirement` anomaly and the remaining twin conflicts (static evidence only, 2026-09-27)

**Static evidence only.** No emulator or live game was run for this round: every decision below comes from reading
both decompiled bodies (`magic/magic_unified.c` against `duel/duel_unified.c`, paired through the twin table).
The one piece of dynamic evidence cited, the `tools/difftest` vectors, was recorded before this round.

**The Round 4 anomaly is one function under two names, and the header comment was right.** `duel/duel_unified.c`
and `duel/duel_all.c` hold exactly one body for the index slot `0x004521e2`, and it is the function defined as
`Mana_GetCardColorRequirement`; neither file defines a `Card_GetColorAndTypeFlags` at all. When the spell-chain round
renamed the `DUEL.EXE` twin of `Card_GetColorAndTypeFlags` (`MAGIC.EXE 0x004d0a42`), only `duel/function_index.csv`,
`duel/symbols.csv` and `duel/source_mapping.csv` took the new name; the C files, the headers and the `NewName`
column of three rename maps kept `Mana_GetCardColorRequirement`. So the address in the header comment was correct and
the *name* was stale, the reverse of the index lag found elsewhere. The body matches `MAGIC.EXE 0x004d0a42` line for
line: the same four locals (`cVar1`, `iVar2`, `uVar3`, `local_8`; Round 4's "several more locals" compared it with
something else), the same stand-in-object check against `g_StackObjectCardId`, the same four type-bit branches
(`0x20000`, `0x40000`, `0x80000`, `0x100000`) and the same colour-mask-to-index and colour-override calls. There is no
cost or mana arithmetic in it. Its roughly 280 call sites in `duel_all.c` are card handlers asking for colour and type flags,
as `MAGIC.EXE`'s roughly 300 callers are. The seven `tools/difftest` vectors recorded from `DUEL.EXE 0x004521e2` pass against
the native `Card_GetColorAndTypeFlags`, which was written from the `MAGIC.EXE` body.

The same index/source split turned up once more: at `DUEL.EXE 0x0043071d` the index says `Ai_PeekPlannedSlot`
(round 3) but the source still said `Card_DispatchRulesEvent`. A third twin conflict from the twin propagation report
was clear-cut as well. The three `DUEL.EXE` renames, applied in the C files, headers and symbol maps (static evidence
only):

| Address | Was | Now | Evidence |
|---|---|---|---|
| `0x004521e2` | `Mana_GetCardColorRequirement` (source, headers and the rename maps' new-name column; the index already had the new name) | `Card_GetColorAndTypeFlags` | static: body identical to `MAGIC.EXE 0x004d0a42` (above) |
| `0x0043071d` | `Card_DispatchRulesEvent` (source and headers; the index already had the new name) | `Ai_PeekPlannedSlot` | static: body identical to `MAGIC.EXE 0x004ab35e` (`Ai_PeekPlannedSlot`, twin 1.0000): when not thinking, reads the plan list at `cursor + offset` into the packed-slot global `0x68f0bc` and masks it to 12 bits. It dispatches nothing |
| `0x0048c907` | `Duel_PlayCardSoundEffect` | `Magic_TriggerCardEvent` | static: body identical to `MAGIC.EXE 0x00474266` (`Magic_TriggerCardEvent`, twin 1.0000): pushes the event context, sets the source and target globals, calls the card's own handler through the pointer at master record `+0x10` and pops the context. It plays no sound anywhere. The `DUEL.EXE` copy takes the engine name, as the other engine twins do |

Parameter names of the renamed functions are unchanged (`Magic_TriggerCardEvent`'s `DUEL.EXE` copy still calls its
last three `arg_3`, `arg_4`, `arg_5`). Sharing a name with the `MAGIC.EXE` function meant matching its existing
declarations: the prototypes of `Magic_TriggerCardEvent` copied into other source files now declare the last two
parameters `int` (they said `undefined4`, as `include/shandalar/magic_engine.h` does not), so the rename adds no
conflicting-type errors (checked by compiling every touched file before and after). `src/magic/sid/card_rules_core.c` holds a copy of the `DUEL.EXE` function at
`0x0043071d` (its comment gives that entry point and it uses `DUEL.EXE` globals); it was renamed with the rest, so
`src/magic` now defines `Ai_PeekPlannedSlot` twice (the other, `MAGIC.EXE 0x004ab35e`, is in `src/magic/sid/Ai.c`;
the copy's return type is now `int`, as there).
Neither file is in the build; the misfiled copy should move to `src/duel` or go.

**Not applied**, with the reason:

- `Magic_QueryCardAttribute` (`MAGIC.EXE 0x00473179`, verified) / `Duel_QueryCardAttribute` (`DUEL.EXE 0x0048b81a`):
  the same meaning under two program prefixes, not a disagreement about what the code does. The convention above
  ("the same code has the same name in both programs") would give the `DUEL.EXE` copy the `Magic_` name, but this
  document's own emulator section introduced `Duel_QueryCardAttribute`; which prefix to keep is a naming decision, not
  something the bodies can settle.
- `Duel_PlaySoundById` (`MAGIC.EXE 0x0047496b`) / `Sound_PlayTrackById` (`DUEL.EXE 0x0048d00c`): both verified live
  and both accurate; already left as two names on purpose (see "Renames applied").
- `_write` (`MAGIC.EXE 0x00513fde`) / `RtlUnwind` (`DUEL.EXE 0x004eec20`): not a real twin pair. Both are 6-byte import
  thunks (`jmp [import]`), each named after the import it jumps to, so each name is right for its own program; the
  twin table pairs them only because all 6-byte thunks look alike.

**Found, not examined this round.** The twin conflicts above are the ones that report can see, because it compares
`function_index.csv` names. Comparing the names the *C files* use instead turns up more twin pairs whose two sides
disagree while both index rows are still `FUN_...`: `Card_SetTapState` / `Duel_GetCardColorOverride`
(`0x0041d9d2` / `0x004af7bb`; the body returns the slot's colour-override byte at `+0xf9 + i`, or `i`, so the `DUEL.EXE`
name fits and the `MAGIC.EXE` one does not), `Card_UntapCard` / `Duel_GetCardModifiedPower` (`0x0041d963` /
`0x004af74c`; the same lookup at `+0xff + i`, which fits neither name), `UI_PaintBigCardInfo` /
`UI_SelectTargetCardDialog` (`0x00403250` / `0x0041bcf0`), `Card_ApplyTriggerEffect` / `Duel_TriggerCardEvent`
(`0x00410cc0` / `0x004a2b00`) and `FileIo_ReadStream` / `FileIo_ReadDataBlock` (`0x0048e01d` / `0x00433bb6`). 21
`MAGIC.EXE` and 20 `DUEL.EXE` index rows still say `FUN_...` for functions their C file already names. None of these was
changed here.

### Round 6: six more native functions, and three misnamed ones they exposed (2026-10-01)

Phase B (`tools/difftest`, `src/native`) gained six small helpers that the first six natives used to *replay* from
recorded calls: the event-context push and pop, the in-play check, the colour-mask-to-index function and the two
colour-remap lookups. Each was written from the decompiled body (identical in `MAGIC.EXE` and `DUEL.EXE` apart from
addresses), then checked against calls recorded from the original running in the emulator
(`tools/difftest/record_vectors.py`): 974 recorded calls across both scripted games, all passing, with the callers'
vectors now holding these helpers' reads and writes as their own instead of replayed calls. For the push and pop the
signedness of the depth compares was read off the real instructions (`jl` and `jle`, signed), not the decompiler's `< 0x20`.

| MAGIC.EXE / DUEL.EXE | Old name | New name | Evidence |
|---|---|---|---|
| `0x474428` / `0x48cac9` | `Magic_PushEventContext` / `FUN_0048cac9` | `Magic_PushEventContext` | natural; the `DUEL.EXE` index and source still said `FUN_` |
| `0x4744de` / `0x48cb7f` | `Magic_PopEventContext` / `FUN_0048cb7f` | `Magic_PopEventContext` | natural, same |
| `0x473cc5` / `0x48c367` | `Card_ColorMaskToColorIndex` / `Duel_ColorMaskToIndex` | `Card_ColorMaskToColorIndex` | natural: lowest set colour-mask bit among bits 1 to 5 as an index 1 to 5, else 0 |
| `0x471c32` / `0x48a33f` | `Card_IsTapped` / `Duel_CardIsTapped` | **`Card_IsInPlay`** | natural. It returns 1 for flags `0x30882` and for `0x30892` (the same flags plus the tap bit) and 0 only for cards in the hand or otherwise not in play (`0x800`, `0x1001`, `0x1801`): it ignores tapping. Its formula also requires bit `0x20` clear; that bit never appeared together with bit `0x2` in the recorded games, so that half is static only |
| `0x41d9d2` / `0x4af7bb` | `Card_SetTapState` / `Duel_GetCardColorOverride` | **`Card_RemapColorIndexF9`** | behaviour natural, meaning static: returns the byte at slot `+0xf9 + index` (as a signed char) if non-zero, else the index. The remap byte was zero in every recorded call, so no real remapping was ever seen |
| `0x41d963` / `0x4af74c` | `Card_UntapCard` / `Duel_GetCardModifiedPower` | **`Card_RemapColorIndexFF`** | the same lookup at `+0xff`; never called in the recorded games (its callers are the ability-bit loop of query code `0x34`, reached only for cards with colour-keyed abilities), so static only |

Both programs now use the one name for each (the `DUEL.EXE` prefix `Duel_` is dropped for these helpers, as it was for the
other engine twins). Only four functions are still reached through the replay hook: `Magic_ScanCards`, the two
sprite-marking calls and the free-slot finder.

Also found: `Card_IsTapped` was the third name this session whose body contradicted it once real calls were looked at
(after `Magic_ResolveSpellStack` and `SpellChain_IsVisible`). The name was assigned by the bulk pass; nothing in the
function ever looked at the tap bit.

### Round 7: nine native functions for the AI's recorded plan (2026-10-01)

`src/native/ai_plan.c` implements `Ai_RecordChoice`, `Ai_ReplayChoice`, `Ai_CommitBestPlan`, `Ai_ClearPlan`,
`Ai_GetPlanCursor`, `Ai_PlanCursorBack`, `Ai_PeekPlannedSlot`, `Ai_PeekPlannedChoice` and `Ai_GetLandColorMasks`, in both
programs, from the decompiled bodies. 46 calls recorded from two games (a mirror match and a game against the red AI
deck, the latter stopped before its end) all pass, and six synthetic vectors cover the cases no game reached
(`Ai_PeekPlannedChoice`, which was never entered live, and the edges of `Ai_PlanCursorBack`). The compares are signed
(`jge`/`jle`/`jl` in the binary).

One thing the disassembly showed that the decompiled C does not: `Ai_ReplayChoice` first executes
`if (best_mode[cursor] != mode) mode |= 0x100` and then, at its end, sets `mode = 0`. The decompiler drops the first
write as dead, correctly: the final memory is identical, and the recorded vectors (which record final values) confirm it.
`Ai_GetLandColorMasks` writes through two out-pointers that point into the caller's stack frame, so its vectors hold stack
addresses as arguments and as written regions; the emulator is deterministic, so that is stable.

`Ai_BeginTrial` is not native yet: it calls the whole-game-state restore, which copies about 0xb640 bytes, so every vector
of it would carry that much callee data. It should follow once the restore itself is native.

### Round 8: the card scan is native (2026-10-01)

`Magic_ScanCards` (`MAGIC.EXE 0x00473f06`, `DUEL.EXE 0x0048c5a8`), the duel engine's dispatcher, now has a native version
(`src/native/card_scan.c`). It recomputes each player's highest used slot, then walks the ordered list of up to 500
(player, slot) entries and, for every live in-play card, calls that card's own handler, whose address is read from the master
record (`+0x10`); after a turn-start scan it may mark a card and runs the combat damage step; finally it runs one global
handler. The handlers are the hundreds of per-card scripts and are **not** native: the native reaches them through a new
hook that takes the callee's address as an argument (`vm_call_at`), so cards can be converted one handler at a time while
the rest keeps running as the original.

What was checked: 724 recorded calls from two scripted games (a mono-green mirror, and against the red AI deck for 330 virtual
seconds), all passing: 88 standalone scans over 25 event codes (`0x15`, `0x1a`, `0x1f`, `0x21`, `0x25`, `0x32`, `0x33`,
`0x34`, `0x3c`, `0x6a`, ...), and 108 card-attribute queries that now carry their handler calls inline. All compares are signed
in the binary (`jl`, `jge`, `jle`). **The limits are real:** only 7 distinct handler functions were ever called (two early-game
decks), at most 5 per scan, and only 14 of 193 handler calls wrote any memory. Three branches no recorded game reached are
covered by six **synthetic** vectors, written from the decompiled body and the disassembly, not from a run: the turn-start
marking path (`flags & 0x14 == 4`, the check, the `0x81` broadcast), the global handler, and the loop variable that leaks out.
That last one is a quirk worth knowing: after the card loop the original compares the turn player with the player of the
**last list entry examined**, even a skipped one, or with 2 if the list was empty (so an empty turn-start scan never runs the
combat step). The synthetic vectors confirm the native matches that reading; they do not prove the reading against the running
game. Not implemented (the original asserts or reports a fatal error): a scan nested ten deep, and a card index out of range.

Two recorder bugs the scan exposed, both fixed in `tools/difftest/record_vectors.py`, and worth recording because they would
have produced wrong vectors silently: (1) a callee's reads of a function pointer made by the call instruction itself were
dropped because the recorder had already switched to "inside the callee"; (2) a callee's written bytes were stored with their
values at the end of the whole call, not at the end of the callee, so a callee write that the function then changed again
(here, a nested scan's depth counter, which the outer scan decrements afterwards) replayed one step too far. Both were found
because the first recordings failed (102 of 104 scans, then 4 of 210), and fixed before the vectors were committed.

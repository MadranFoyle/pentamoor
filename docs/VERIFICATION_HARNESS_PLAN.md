# Automated Verification Harness — Design & Roadmap

## Why this exists

The decompilation in this repo has two very different layers of trustworthiness:

1. **Raw decompiled control flow and constants** — mechanically produced by Ghidra from
   the real binaries. This is almost certainly accurate at the instruction level.
2. **Human-readable names, types, and doc comments** — added afterward by a bulk
   automated pass (1,650+ function renames, 268+ global renames, ASD-STE100 comments,
   the AI FAQ, etc.) in a matter of days, with no verification loop against actual
   program behavior.

Layer 2 is demonstrably unreliable in specific, checkable ways:

- `src/magic/sid/Magic.c` (a file of the upstream project's tree, since removed) names a function `Magic_DrawCardPhase`
  and comments it as drawing a card from the library. The actual body loops over
  artifact `.wav` filenames and preloads sound effects — it is not a draw-phase function.
- `src/magic/sid/glue_adventure.c` (likewise) assigns
  `g_CampaignDifficultyLevel` and `g_OverworldPlayerDirection` from the return values of
  `Pic_Load_menu2_hi_...` / `Pic_Load_menu3_but1_...` — image/UI loader calls, not
  gameplay state.
- The AI FAQ and starting-resources spec that shipped with the repo made specific factual
  claims (AI fog-of-war, hand-slot flag meanings, starting gold ranges) in the same
  confident, unverified voice, with links into files that no longer exist. They have been
  removed; nothing in them was checked against the running game.

Goal precedent: **DevilutionX**. Their port is trustworthy because every recovered
function was checked against the real `.exe`'s actual behavior before being renamed or
relied on — not because the decompiler produced good names on its own. We don't have
that verification yet. This harness is how we get it, without requiring anyone to sit
and manually play through the game to generate test cases.

## Non-goals

- This harness does not need to "play well." A dumb, deterministic, seeded policy that
  always takes the first legal action is sufficient — we're testing **behavioral
  equivalence between two implementations**, not game-playing skill.
- We are not trying to prove the whole game is correct in one pass. We're building a
  tool that we run repeatedly, subsystem by subsystem, as we work through the codebase.

## Oracle: the Windows 98SE VM (replaces the abandoned Wine plan)

Running the original 32-bit binaries under Wine on this Apple Silicon Mac is a dead end
(Homebrew's Wine casks are disabled, MacPorts hits a Tahoe universal-build bug, and the
Rosetta 32-bit workarounds are deprecated). The oracle is instead a real Windows 98SE guest
under QEMU's software emulation. See [`ORACLE_VM.md`](ORACLE_VM.md) for setup, quirks, and the
proof that the installed binaries are the same build the decompilation was made from.

## Architecture — four layers

### Layer 1: Determinism

Two runs must line up frame-for-frame. Candidates, in order of preference:

1. **QEMU record/replay** (`-icount ... rr=record|replay` over a qcow2 overlay). Determinism
   at the emulator level, so no guest-side clock shim. Worth prototyping first, but it is
   unproven for this device set (PIIX IDE, Cirrus VGA, SB16, ne2k, PS/2).
2. **Logical checkpoints.** If record/replay is unsupported, compare at game-defined points
   (turn phase changes, card moves) instead of wall-clock ticks.

Port side: the old `src/platform/win32_compat.c` (removed) intercepted the timing calls, and `src/port` has its own clock; add a harness mode that advances a logical tick only on request.

### Layer 2: Synthetic deterministic input driver ("the monkey")

A scripted, seeded decision policy, not a human and not a real AI:

- Menu/dialog navigation: fixed coordinate sequences (recoverable from the decompiled
  UI code in `glue_adventure.c` / `glue_duel_ui.c` — the dialog layout constants are
  part of Layer 1's "trustworthy raw logic," even where names are wrong).
- In-duel decisions: a simple deterministic rule ("first legal action," "attack with
  everything," "cast cheapest castable spell") parameterized by a seed, so we can run
  many varied but fully reproducible sessions.
- Delivered as a **script file** (see format below). For the oracle it is replayed through
  QEMU's QMP interface (`send-key`, `input-send-event`); for the port, through the win32
  shim's message queue.

Input script format (JSON, draft):

```json
{
  "seed": 12345,
  "events": [
    { "tick": 0,   "type": "WM_LBUTTONDOWN", "x": 320, "y": 240 },
    { "tick": 4,   "type": "WM_LBUTTONUP",   "x": 320, "y": 240 },
    { "tick": 20,  "type": "WM_KEYDOWN",     "vk": "VK_RETURN" }
  ]
}
```

Caveat found the hard way: the Windows 98 guest uses a PS/2 relative mouse, so absolute
click coordinates do not map to the guest pointer. Prefer keyboard-driven paths, or send
relative mouse deltas through QMP and verify pointer position from the screen.


### Layer 3: State snapshot + diff

At each checkpoint, dump known global state from both sides and compare:

- Static addresses and struct layouts come from Ghidra (`MasterCardRecord`,
  `g_ActiveCardsInPlay`, board/hand/life globals; see the removed `symbols/engine_globals_map.csv`
  and `include/shandalar/cards.h`). Addresses are valid in the oracle because the binaries are
  the same build (see `ORACLE_VM.md`).
- Oracle side: QEMU's gdbstub. A breakpoint at a known code address in the game's address
  range fires only in the game's process context, so memory reads at `0x004xxxxx`/`0x005xxxxx`
  are then meaningful.
- First divergence = a port bug or a mislabeled function. Either way it is now a concrete,
  reproducible finding.

### Layer 4: Bisection + breakpoint tracing

- **Bisection**: when two runs diverge, binary-search the first differing checkpoint
  (`tools/verification_harness/divergence_bisect.py`).
- **Breakpoint tracing**: gdbstub breakpoints/watchpoints on a suspect function log its
  entry/exit and memory touches. The first target is `Magic_DrawCardPhase` (`0x00474c7f`):
  does it fire on a card draw, or at startup while sounds load?

## Toolchain

| Piece | Tool | Status |
|---|---|---|
| Oracle VM (interactive) | UTM 4.7 + Windows 98SE | installed, game runs |
| Oracle VM (scriptable) | `qemu-system-i386` 11.1 (Homebrew) | installed, not yet driving the disk |
| Windows cross-compiler | `mingw-w64` (`i686-w64-mingw32-gcc`) | installed |
| Disk image tools | `qemu-img`, `mdf2iso`, `hdiutil` | used to extract game files |
| Wine | any | abandoned |
| Frida | - | not needed (gdbstub replaces it) |
| Orchestration | Python 3 | installed |

## Phased roadmap

**Phase 0 (done): pure-logic scaffolding**, tested in `tools/verification_harness/`
- [x] Design doc, input script schema + validator, seeded monkey policy, snapshot model,
      bisection algorithm (the orchestrator skeleton was removed).

**Phase 1: oracle**
- [x] Windows 98SE VM built; original game installed and runs.
- [x] Installed binaries extracted, hashed, and confirmed to be the decompiled build.
- [x] Boot the same disk under plain `qemu-system-i386` with QMP and gdbstub enabled
      (`tools/verification_harness/oracle_launch.sh`, clients in `oracle_qemu.py`).
- [ ] Prototype record/replay determinism.
- [x] First symbol check: `Magic_DrawCardPhase` is wrong; it preloads duel sound effects at
      duel start (see [SYMBOL_VERIFICATION.md](SYMBOL_VERIFICATION.md)).
- [ ] Symbol table with a verified/unverified status column (log started in SYMBOL_VERIFICATION.md).
- [x] Absolute mouse control through QMP (`mouse_goto`, `oracle_ctl.py`); reached a duel.
- [x] Find and verify the real draw function: `FUN_0046f5d1` in `MAGIC.EXE` (also found that
      `Magic_UpkeepPhase` is really the sound player, and that campaign duels run in MAGIC.EXE).
- [x] Rename the verified symbols in the source, headers, CSV symbol maps and generator scripts.
- [x] Launched DUEL.EXE for real: its entry point fires, and its twin draw and sound functions
      run exactly as predicted. Both programs run the duel engine; campaign duels use MAGIC.EXE.
- [x] Sample 30 semantic names at random: about 1 in 5 wrong or misleading, about 1 in 3 unsupported
      (a sample of 30 names found about 1 in 5 wrong or misleading).
- [x] Fix the systematic global mislabels: now `g_EventSourceSlot`, `g_EventSourcePlayer` and
      `g_CardEventResult`. Confirmed live with write watchpoints (600 writes).
- [x] Rename the event-context push and pop and the dispatcher (were `Magic_PayManaCost`,
      `Magic_TapCardForMana`, `Card_TapForMana`), and name three more context globals.
- [x] Restore the earlier names a later pass had replaced: 30 restored, 46 left (code supports neither).
- [x] Name `g_PlayerManaPool` (the current turn-step code) and `DAT_006b2fe4` (the event card's colour
      mask), and the three other functions that write the event context (static evidence).
- [x] Confirmed live: `Magic_RunTurnStep` and `g_CurrentStepCode` (the turn, cast and combat steps).
- [x] Rename the spell stack: `Magic_CombatPhase`, `Magic_EndTurnPhase` and `Magic_DiscardToHandSize` were
      really push, resolve and drop; `g_AiSavedPlayerManaPool` was a copy of its entries (static evidence).
- [x] Spell stack live: push, resolve, drop and clear all seen (the AI's save and restore are not).
- [x] Combat steps live: `0xd9`, `0xda` and `0xdc` seen, plus `0xd4` to `0xd7` and `0xcc`. `0xda` also runs on my own attack
      (emulator).
- [x] `Magic_QueryCardAttribute` codes `0x32`, `0x33`, `0x34`, `0x3c` = power, toughness, abilities, card id (emulator).
- [x] `Magic_ResolveSpellStack` is really `Magic_IsManaSource`: true for cards that tap for mana (emulator).
- [x] `g_PlayerHandCardCount` is `g_DuelModeFlags`; `g_DefendingPlayer` is `g_TurnPlayer` (write watches, emulator).
- [ ] Name `g_CurrentTurnPhase` (MAGIC.EXE `0x6a49e0`): a player index that did not change in the scripted game.
- [x] `Magic_DropTopSpell` confirmed live (only inside the AI's search); `Combat_ResolveBlocksAndDamage` named (round 2).
- [ ] Extend verification to the other duel-engine functions: turn phases, combat, AI choices.
- [ ] Make probes process-aware: every program loads at `0x00400000`, and duels run in `DUEL.EXE`.

**Phase 2: port**
- [ ] `--harness-replay` mode in the port; run against the extracted real assets.
- [ ] Verify the other six binaries against the decomp the same way as `MAGIC.EXE`.
- [ ] Decide native-port vs. hybrid (mingw-compiled function replacement inside the VM);
      first test whether mingw output runs on Windows 98.
- [ ] First real port-vs-original diff on a short scripted sequence.

## Current status

Phase 1 is underway. The oracle exists and is fingerprinted; making it scriptable is next.

# A duel that sits on "Fast Effects?...Draw Phase" with the player at 0 life or less

**The engine's own loop, not a crash and not a hang of the port; why it never ends was found to the point of the line of code, whether the original does the same was not settled.** Found by the long soak
runs of 2026-10-17 (`tools/soak/soak.py` with duels of 12 to 40 turns: [duel-ux.md](duel-ux.md), "Long runs"): eight times in about 400 duels on Linux x86_64 at 1024x768, never in the three hours of short duels (conceded after
3 to 9 turns), and not in the 25 or so long duels on macOS arm64 (too few to say that it cannot happen there).

## What it looks like

The prompt bar says `Fast Effects?...Draw Phase` and Done does nothing: the bar, the hands and the board stay as they were for as long as the script presses it (the soak calls it STUCK after 45 s).
Every time it is the same picture: the player's life is 0 or below (0, -1, -2 ...), the Sorcerer's is 8 to 10, the Sorcerer has a Naf's Asp, and the player's side of the board holds one or two **Asp Legacy** cards
("Naf's Asp takes 1 life!" had been shown earlier in the duel). The process answers everything: `windows` answers, a right click opens the menu, Concede works (the soak's recovery); it is not blocked and
not spinning (2% CPU).

## Measured on stuck processes (kept alive by freezing the soak at the event; three of them, one with the `threads` and `calls` commands below)

- The window tree: one `MAGIC_TellUserClass` bar with its two buttons (Done is the visible one), no dialog, no popup, an empty message queue.
- `threads`: the main thread is in its wait loop for the duel thread (`PeekMessageA` at 0x44225c and `GetExitCodeThread` at 0x442236, over and over: the normal state of the main thread during a duel), the duel
  thread is blocked in `SendMessageA` or `WaitForSingleObject` the way it is whenever it waits for input. `trace on` for 3 s without a click: only those two calls. With one click on Done: 14,426 calls in
  3.5 s (`GetWindowLongA` 9,824, `SendMessageA` 886 ...), then silence again. So the click reaches the duel thread, the engine works through it and **asks the same question again**.
- `calls on` (every call between lifted functions) for one click on Done: 7,753 calls. The Done handler (0x4af765) calls 0x4cc9c5(0, 0xff), which runs the phase triggers (0x473f06, four rounds), the card
  effect handlers (0x414875 six times, a handler with the event codes 0x73, 0x6d and 0x72) and 0x447b57 (a card's activation, twenty times), and when it is over `0x6a4920` holds 3 again.
- The code (disassembly of the program file): `0x475d64` is the "Fast Effects?" prompt and `0x475c8a` its caller (`push 0x531170 "Draw Phase"` at 0x502ecd, in the turn sequence 0x501f50). The prompt repeats
  while the player's action returns non-zero **or while bit 0 of 0x6a4920 is set and the prompt's nesting 0x6ff684 is 1** (0x476014), and it ends early only when the game-over flag 0x6a285c is 1. That flag is
  set by the end-of-game test `0x5062b1` (life 0 or less for either player, or ten poison counters), which is called after the prompt (0x502f11), not inside it. And 0x6a4920 is set to 3 by about twenty card-effect
  handlers (`or [0x6a4920], 3`: "the board changed, ask again"), among them 0x447b57 for a card of the computer's side when the prompt's mode is 4, and 0x414875 (the Asp Legacy's: event 0x73, in phase 10, for the player
  whose draw it is, with its "paid" field 0 and no card being activated: `or [0x6a4920], 3`, return 1).

## What was tried on the kept processes

| poke, then Done | result |
|---|---|
| the player's life to 1 | nothing: the loop does not depend on the life once it is in it |
| the "paid" field of the two Asp Legacy cards (card table, field +0x24) to 1 | nothing |
| the game-over flag 0x6a285c to 1 | the loop is left, the duel goes on into the next phase with the player at -8: nothing ends it |
| the prompt's nesting 0x6ff684 to 2 (the rule "bit 0 of 0x6a4920 and nesting 1" no longer applies) | the loop is left at once, the end-of-game test runs, the dialog "Druid won / Next round / Quit Gauntlet" opens |

So the rule `bit 0 of 0x6a4920 and nesting 1` is the whole reason; what feeds it on every pass is the effects that "ask again" (the Asp Legacy's, the computer's cards' activation, both in the list above).

## What is not known

- Why the effects ask again forever when the player is dead and not when the player has life left (duels in which "Naf's Asp takes 1 life!" was shown went on normally in the same runs): perhaps the
  end-of-game test, which is what normally ends the duel after the prompt, is reached only if the prompt is left, and the player is already at 0 or less when it opens; where the last life went was not traced.
- **Whether the original program does the same.** The code is the original's, lifted as it is, and the loop is driven by game data, not by timing or by anything the port supplies, so the likeliest answer is yes: a
  player who is taken to 0 life by the Asp's loss at the start of the draw phase cannot pass that prompt and has to concede from the menu (which works). It could not be compared with the original here (it
  needs the exact state in the Windows 98 oracle).
- Not a reason to change the port: nothing here is wrong in the runtime (all threads answer, the clicks arrive, Concede ends the duel).

## What was added to find it

- `Soak` writes `rss.csv` and, on a STUCK, the engine state (lives, 0x6a285c, 0x6ff380, 0x6ff558, 0x6a3f78) into the event and, on Linux, every thread's state and CPU ticks twice, 2 s apart (`/proc`: gdb cannot
  attach to a process that is not its own child where `ptrace_scope` is 1). `Game.shot` returns the PPM it made when PIL is missing.
- The control commands `threads` (`sched_dump`: every guest thread, ready or blocked, with a condition, a deadline or neither, and the last import it called and from where; a thread blocked with neither is
  waiting for something nobody will give) and `calls on|off` (every call from one lifted function to another, with its caller), in [PHASE_C.md](../PHASE_C.md). With `trace on|off` (imports) they say what a
  silent process is doing.

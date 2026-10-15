#!/usr/bin/env python3
"""
Deterministic "monkey" input generator.

This is deliberately NOT a smart player and NOT a human recording. It's a seeded,
reproducible policy that produces the same input script every time for a given seed,
so the exact same sequence can be replayed into both the port and the original binary.
The goal is behavioral-equivalence testing, not good play.

Two kinds of scripts:

- menu navigation: fixed coordinate sequences for known dialogs (main menu, deck
  select, etc). These coordinates come from the decompiled UI layout constants
  (glue_adventure.c / glue_duel_ui.c) -- that raw layout data is part of the
  trustworthy "Layer 1" logic even where the surrounding function names are wrong.
  TODO(phase 2): fill in real coordinates once we've confirmed dialog layout against
  a live run; the placeholders below are illustrative only.

- duel actions: seeded pseudo-random choice among "always take the Nth legal action"
  style rules, so many varied-but-reproducible sessions can be generated for coverage.
"""

import random


# TODO(phase 2): replace with real coordinates recovered from a live/verified run.
# Kept here as named constants so callers don't hardcode magic numbers, and so this
# whole table can be swapped out once verified without touching call sites.
KNOWN_UI_COORDS = {
    "main_menu_new_game": (320, 240),
    "deck_select_first_deck": (160, 200),
    "duel_pass_priority": (600, 440),
    "duel_end_turn": (600, 460),
}


def click_sequence(tick, x, y, hold_ticks=4):
    """A mouse-down followed by mouse-up hold_ticks later, at a fixed logical time."""
    return [
        {"tick": tick, "type": "WM_LBUTTONDOWN", "x": x, "y": y},
        {"tick": tick + hold_ticks, "type": "WM_LBUTTONUP", "x": x, "y": y},
    ]


def generate_boot_to_main_menu_script(seed):
    """Smallest possible script: do nothing but let the game boot. Useful as the
    very first oracle comparison once a real run is available -- if this diverges,
    nothing more complex is worth trying yet."""
    return {"seed": seed, "events": []}


def generate_menu_navigation_script(seed, target="main_menu_new_game", click_tick=30):
    x, y = KNOWN_UI_COORDS[target]
    return {"seed": seed, "events": click_sequence(click_tick, x, y)}


def generate_duel_monkey_script(seed, num_actions=20, tick_spacing=15, start_tick=200):
    """Generates a reproducible sequence of generic duel-phase actions (pass priority
    or end turn, alternating deterministically based on the seed) for stress-testing
    the duel engine without needing to understand game state.

    This is intentionally simple. It exists to generate *coverage*, not to win games --
    smarter, game-state-aware policies can be layered on once we can read the port's
    state well enough to make legal-action-aware choices (see state_snapshot.py).
    """
    rng = random.Random(seed)
    events = []
    tick = start_tick
    for _ in range(num_actions):
        action = rng.choice(["duel_pass_priority", "duel_end_turn"])
        x, y = KNOWN_UI_COORDS[action]
        events.extend(click_sequence(tick, x, y))
        tick += tick_spacing
    return {"seed": seed, "events": events}


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["boot", "menu", "duel"])
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", default="-")
    args = parser.parse_args()

    if args.kind == "boot":
        script = generate_boot_to_main_menu_script(args.seed)
    elif args.kind == "menu":
        script = generate_menu_navigation_script(args.seed)
    else:
        script = generate_duel_monkey_script(args.seed)

    text = json.dumps(script, indent=2)
    if args.out == "-":
        print(text)
    else:
        with open(args.out, "w") as f:
            f.write(text)

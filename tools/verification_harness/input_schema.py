#!/usr/bin/env python3
"""
Schema and validator for scripted input-event sequences.

An input script is the thing we replay identically into both the port and the
original binary, at identical logical ticks, so their behavior is directly
comparable. It is produced by monkey_policy.py (or, later, hand-authored for a
specific regression case) and consumed by whatever drives a run.

Format (JSON):

{
  "seed": 12345,
  "events": [
    {"tick": 0,  "type": "WM_LBUTTONDOWN", "x": 320, "y": 240},
    {"tick": 4,  "type": "WM_LBUTTONUP",   "x": 320, "y": 240},
    {"tick": 20, "type": "WM_KEYDOWN",     "vk": "VK_RETURN"}
  ]
}

Events must be sorted by non-decreasing "tick". "tick" is a logical frame count
driven by the harness's virtual clock, never wall-clock time -- see
docs/VERIFICATION_HARNESS_PLAN.md, Layer 1.
"""

MOUSE_EVENT_TYPES = {"WM_LBUTTONDOWN", "WM_LBUTTONUP", "WM_RBUTTONDOWN", "WM_RBUTTONUP", "WM_MOUSEMOVE"}
KEY_EVENT_TYPES = {"WM_KEYDOWN", "WM_KEYUP"}
ALL_EVENT_TYPES = MOUSE_EVENT_TYPES | KEY_EVENT_TYPES


class ScriptValidationError(ValueError):
    pass


def validate_event(event, index):
    if not isinstance(event, dict):
        raise ScriptValidationError(f"event {index}: must be an object")

    if "tick" not in event:
        raise ScriptValidationError(f"event {index}: missing 'tick'")
    tick = event["tick"]
    if not isinstance(tick, int) or tick < 0:
        raise ScriptValidationError(f"event {index}: 'tick' must be a non-negative int")

    etype = event.get("type")
    if etype not in ALL_EVENT_TYPES:
        raise ScriptValidationError(
            f"event {index}: unknown type {etype!r}, expected one of {sorted(ALL_EVENT_TYPES)}"
        )

    if etype in MOUSE_EVENT_TYPES:
        for key in ("x", "y"):
            if key not in event:
                raise ScriptValidationError(f"event {index}: mouse event missing '{key}'")
            if not isinstance(event[key], int):
                raise ScriptValidationError(f"event {index}: '{key}' must be an int")

    if etype in KEY_EVENT_TYPES:
        if "vk" not in event or not isinstance(event["vk"], str):
            raise ScriptValidationError(f"event {index}: key event missing string 'vk'")


def validate_script(script):
    """Raises ScriptValidationError on the first problem found. Returns None on success."""
    if not isinstance(script, dict):
        raise ScriptValidationError("script must be a JSON object")

    if "seed" not in script or not isinstance(script["seed"], int):
        raise ScriptValidationError("script must have an integer 'seed'")

    events = script.get("events")
    if not isinstance(events, list):
        raise ScriptValidationError("script must have an 'events' list")

    last_tick = -1
    for i, event in enumerate(events):
        validate_event(event, i)
        if event["tick"] < last_tick:
            raise ScriptValidationError(
                f"event {i}: tick {event['tick']} is out of order (previous tick was {last_tick})"
            )
        last_tick = event["tick"]


def load_and_validate(path):
    import json

    with open(path) as f:
        script = json.load(f)
    validate_script(script)
    return script


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <input_script.json>", file=sys.stderr)
        sys.exit(2)
    try:
        load_and_validate(sys.argv[1])
    except ScriptValidationError as e:
        print(f"INVALID: {e}", file=sys.stderr)
        sys.exit(1)
    print("valid")

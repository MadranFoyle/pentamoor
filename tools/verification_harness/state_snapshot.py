#!/usr/bin/env python3
"""
Data model for the per-tick state record compared between the port and the original.

This defines *what* we diff, independent of *how* we read it from a live process.
Reading real values (from the port's own memory, or from a Wine process via
/proc/<pid>/mem or a Frida hook) is Phase 1/2 work that needs the toolchain and,
for the original binary, the discs. The shape of the record can be designed and
tested now.

Field names here intentionally do NOT reuse the unverified names from the bulk
rename pass (e.g. we don't assume "g_CampaignDifficultyLevel" means what it says).
Each field lists the source it's cross-referenced against, so we know exactly how
confident we are in what it represents.
"""

from dataclasses import dataclass, field, asdict
import hashlib
import json


@dataclass
class CardSlotSnapshot:
    """One of the 80 per-player card slots.

    The master card record is 0x34 bytes (src/native/engine.h, docs/SYMBOL_VERIFICATION.md).
    Flag bit meanings (0x01 = in hand, 0x02 = in play, ...) were guessed when the slots
    were first named and are UNVERIFIED -- treat them as a hypothesis to confirm via the
    harness, not as ground truth.
    """

    card_id: int
    flags: int


@dataclass
class PlayerSnapshot:
    life_total: int
    card_slots: list  # list[CardSlotSnapshot]


@dataclass
class StateSnapshot:
    """One comparable point-in-time record.

    tick: logical tick from the harness's virtual clock (see Layer 1 in the plan doc),
    never wall-clock time -- this is what makes two independent runs comparable.
    """

    tick: int
    players: list  # list[PlayerSnapshot]
    turn_phase: int  # raw numeric value; the symbolic TurnPhase enum names are
    # part of the unverified rename layer, so we compare raw values, not names.

    def canonical_dict(self):
        return asdict(self)

    def digest(self):
        """Stable hash of this snapshot's contents, used for cheap equality checks
        before falling back to a full structural diff."""
        blob = json.dumps(self.canonical_dict(), sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


def diff_snapshots(a: StateSnapshot, b: StateSnapshot):
    """Returns a list of human-readable difference descriptions, empty if equal.
    Does not compare 'tick' itself -- callers are expected to only diff snapshots
    already known to be at the same logical tick.
    """
    differences = []

    if a.turn_phase != b.turn_phase:
        differences.append(f"turn_phase: {a.turn_phase} != {b.turn_phase}")

    if len(a.players) != len(b.players):
        differences.append(f"player count: {len(a.players)} != {len(b.players)}")
        return differences

    for i, (pa, pb) in enumerate(zip(a.players, b.players)):
        if pa.life_total != pb.life_total:
            differences.append(f"player {i} life_total: {pa.life_total} != {pb.life_total}")
        if len(pa.card_slots) != len(pb.card_slots):
            differences.append(
                f"player {i} card_slots length: {len(pa.card_slots)} != {len(pb.card_slots)}"
            )
            continue
        for slot_idx, (sa, sb) in enumerate(zip(pa.card_slots, pb.card_slots)):
            if sa.card_id != sb.card_id or sa.flags != sb.flags:
                differences.append(
                    f"player {i} slot {slot_idx}: "
                    f"(card_id={sa.card_id}, flags={sa.flags:#x}) != "
                    f"(card_id={sb.card_id}, flags={sb.flags:#x})"
                )

    return differences

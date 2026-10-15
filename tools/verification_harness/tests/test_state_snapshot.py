import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from state_snapshot import CardSlotSnapshot, PlayerSnapshot, StateSnapshot, diff_snapshots


def make_snapshot(tick=0, life_a=20, life_b=20, turn_phase=0):
    slots = [CardSlotSnapshot(card_id=i, flags=0x01) for i in range(3)]
    players = [
        PlayerSnapshot(life_total=life_a, card_slots=list(slots)),
        PlayerSnapshot(life_total=life_b, card_slots=list(slots)),
    ]
    return StateSnapshot(tick=tick, players=players, turn_phase=turn_phase)


class TestStateSnapshot(unittest.TestCase):
    def test_identical_snapshots_have_no_diff(self):
        a = make_snapshot()
        b = make_snapshot()
        self.assertEqual(diff_snapshots(a, b), [])

    def test_identical_snapshots_have_same_digest(self):
        a = make_snapshot()
        b = make_snapshot()
        self.assertEqual(a.digest(), b.digest())

    def test_life_total_mismatch_detected(self):
        a = make_snapshot(life_a=20)
        b = make_snapshot(life_a=18)
        diffs = diff_snapshots(a, b)
        self.assertEqual(len(diffs), 1)
        self.assertIn("life_total", diffs[0])

    def test_turn_phase_mismatch_detected(self):
        a = make_snapshot(turn_phase=1)
        b = make_snapshot(turn_phase=2)
        diffs = diff_snapshots(a, b)
        self.assertTrue(any("turn_phase" in d for d in diffs))

    def test_card_slot_mismatch_detected(self):
        a = make_snapshot()
        b = make_snapshot()
        b.players[0].card_slots[1].card_id = 999
        diffs = diff_snapshots(a, b)
        self.assertTrue(any("slot 1" in d for d in diffs))

    def test_digest_changes_on_mismatch(self):
        a = make_snapshot()
        b = make_snapshot(life_a=1)
        self.assertNotEqual(a.digest(), b.digest())


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from input_schema import validate_script, ScriptValidationError


class TestInputSchema(unittest.TestCase):
    def test_valid_minimal_script(self):
        validate_script({"seed": 1, "events": []})

    def test_valid_mouse_and_key_events(self):
        validate_script(
            {
                "seed": 1,
                "events": [
                    {"tick": 0, "type": "WM_LBUTTONDOWN", "x": 10, "y": 20},
                    {"tick": 4, "type": "WM_LBUTTONUP", "x": 10, "y": 20},
                    {"tick": 10, "type": "WM_KEYDOWN", "vk": "VK_RETURN"},
                ],
            }
        )

    def test_missing_seed(self):
        with self.assertRaises(ScriptValidationError):
            validate_script({"events": []})

    def test_out_of_order_ticks(self):
        with self.assertRaises(ScriptValidationError):
            validate_script(
                {
                    "seed": 1,
                    "events": [
                        {"tick": 5, "type": "WM_KEYDOWN", "vk": "VK_RETURN"},
                        {"tick": 3, "type": "WM_KEYDOWN", "vk": "VK_RETURN"},
                    ],
                }
            )

    def test_unknown_event_type(self):
        with self.assertRaises(ScriptValidationError):
            validate_script({"seed": 1, "events": [{"tick": 0, "type": "WM_BOGUS"}]})

    def test_mouse_event_missing_coords(self):
        with self.assertRaises(ScriptValidationError):
            validate_script({"seed": 1, "events": [{"tick": 0, "type": "WM_LBUTTONDOWN", "x": 1}]})

    def test_key_event_missing_vk(self):
        with self.assertRaises(ScriptValidationError):
            validate_script({"seed": 1, "events": [{"tick": 0, "type": "WM_KEYDOWN"}]})


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from input_schema import validate_script
from monkey_policy import (
    generate_boot_to_main_menu_script,
    generate_menu_navigation_script,
    generate_duel_monkey_script,
)


class TestMonkeyPolicy(unittest.TestCase):
    def test_boot_script_is_valid_and_empty(self):
        script = generate_boot_to_main_menu_script(seed=1)
        validate_script(script)
        self.assertEqual(script["events"], [])

    def test_menu_navigation_script_is_valid(self):
        script = generate_menu_navigation_script(seed=1)
        validate_script(script)
        self.assertTrue(len(script["events"]) >= 2)

    def test_duel_script_is_valid(self):
        script = generate_duel_monkey_script(seed=42, num_actions=10)
        validate_script(script)

    def test_duel_script_is_deterministic(self):
        a = generate_duel_monkey_script(seed=42, num_actions=10)
        b = generate_duel_monkey_script(seed=42, num_actions=10)
        self.assertEqual(a, b)

    def test_duel_script_seed_changes_output(self):
        a = generate_duel_monkey_script(seed=1, num_actions=10)
        b = generate_duel_monkey_script(seed=2, num_actions=10)
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()

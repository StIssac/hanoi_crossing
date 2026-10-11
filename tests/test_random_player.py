"""Random-player signature checks; random selection is still pending."""

import inspect
from random import Random
from typing import get_type_hints
import unittest

from hanoi_crossing import Action, Observation
from hanoi_crossing.random_player import choose_action


class RandomPlayerInterfaceTests(unittest.TestCase):
    def test_player_receives_observation_and_injected_rng(self):
        self.assertEqual(
            tuple(inspect.signature(choose_action).parameters), ("observation", "rng")
        )
        self.assertEqual(
            get_type_hints(choose_action),
            {"observation": Observation, "rng": Random, "return": Action},
        )

    def test_unimplemented_selection_fails_explicitly(self):
        observation = Observation("A", ((1,), (), ()), None)
        with self.assertRaisesRegex(NotImplementedError, "choose_action"):
            choose_action(observation, Random(42))

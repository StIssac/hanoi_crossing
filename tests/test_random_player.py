"""Observation-only selection from every legal action, without heuristics."""

import inspect
from random import Random
from typing import get_type_hints
import unittest
from unittest.mock import Mock, patch

from hanoi_crossing import Action, GameState, Observation, legal_actions, observe
from hanoi_crossing import random_player
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

    def test_choice_receives_the_complete_legal_tuple_for_both_players(self):
        for player in ("A", "B"):
            for stacks, hand in ((((5, 1), (4, 2), (6, 3)), None), (((6,), (5,), ()), 1)):
                observation = Observation(player, stacks, hand)
                actions = legal_actions(observation)
                self.assertEqual(len(actions), 4)
                self.assertEqual(actions[0], Action("skip"))
                for selected in actions:
                    with self.subTest(player=player, hand=hand, selected=selected):
                        rng = Mock(spec=Random)
                        rng.choice.return_value = selected
                        with patch.object(random_player.engine, "legal_actions",
                                          return_value=actions) as enumerate_actions:
                            self.assertIs(choose_action(observation, rng), selected)
                        enumerate_actions.assert_called_once_with(observation)
                        rng.choice.assert_called_once_with(actions)
                        self.assertIs(rng.choice.call_args.args[0], actions)

    def test_seeded_rng_reproduces_choices(self):
        observation = Observation("A", ((3, 1), (4,), (2,)), None)
        first, second = Random(42), Random(42)
        self.assertEqual([choose_action(observation, first) for _ in range(20)],
                         [choose_action(observation, second) for _ in range(20)])

    def test_terminal_observations_do_not_call_rng(self):
        state = GameState(((), (2,), (), (1,), ()), (None, None), "A")
        for player in ("A", "B"):
            with self.subTest(player=player):
                rng = Mock(spec=Random)
                with self.assertRaises(ValueError):
                    choose_action(observe(state, player), rng)
                rng.choice.assert_not_called()

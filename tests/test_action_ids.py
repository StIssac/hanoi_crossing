"""Stable player-relative action IDs, independent of move legality."""

import unittest

from hanoi_crossing import (
    ACTION_IDS,
    Action,
    action_from_id,
    action_to_id,
    legal_actions,
    new_game,
    observe,
    step,
)


class ActionIdTests(unittest.TestCase):
    def test_all_seven_ids_and_round_trips_for_both_players(self):
        self.assertEqual(ACTION_IDS, (0, 1, 2, 3, 4, 5, 6))
        expected = {
            "A": (
                Action("skip"), Action("lift", "1a"), Action("lift", "2"),
                Action("lift", "3a"), Action("place", "1a"),
                Action("place", "2"), Action("place", "3a"),
            ),
            "B": (
                Action("skip"), Action("lift", "1b"), Action("lift", "2"),
                Action("lift", "3b"), Action("place", "1b"),
                Action("place", "2"), Action("place", "3b"),
            ),
        }
        for player, actions in expected.items():
            for action_id, action in enumerate(actions):
                with self.subTest(player=player, action_id=action_id):
                    self.assertEqual(action_from_id(player, action_id), action)
                    self.assertEqual(action_to_id(player, action), action_id)
                    self.assertEqual(
                        action_to_id(player, action_from_id(player, action_id)), action_id,
                    )
                    self.assertEqual(
                        action_from_id(player, action_to_id(player, action)), action,
                    )

    def test_invalid_ids_raise_value_error(self):
        for player in ("A", "B"):
            for action_id in (True, False, -1, 7, 100, 0.0, 1.0, "1", None, [], {}, ()):
                with self.subTest(player=player, action_id=action_id):
                    with self.assertRaises(ValueError):
                        action_from_id(player, action_id)

    def test_both_conversions_validate_player_even_for_skip(self):
        for player in (None, True, 0, "a", "C", [], {}):
            with self.subTest(player=player):
                with self.assertRaises(ValueError):
                    action_from_id(player, 0)
                with self.assertRaises(ValueError):
                    action_to_id(player, Action("skip"))

    def test_encoding_requires_an_action_model(self):
        for action in (None, True, "skip", {"kind": "skip", "pole": None}, ()):
            with self.subTest(action=action):
                with self.assertRaises(ValueError):
                    action_to_id("A", action)

    def test_hidden_poles_cannot_be_encoded_but_remain_illegal_turns(self):
        state = new_game(1)
        for player, hidden in (("A", ("1b", "3b")), ("B", ("1a", "3a"))):
            for kind in ("lift", "place"):
                for pole in hidden:
                    with self.subTest(player=player, kind=kind, pole=pole):
                        action = Action(kind, pole)
                        with self.assertRaises(ValueError):
                            action_to_id(player, action)
                        result = step(state, player, action)
                        self.assertEqual(result.error, "invisible_pole")
                        self.assertIs(result.state, state)

    def test_ids_remain_fixed_as_legal_actions_change(self):
        for player, other in (("A", "B"), ("B", "A")):
            state = new_game(2)
            states = [state]
            for action_id in (1, 5, 1, 6):
                result = step(state, player, action_from_id(player, action_id))
                self.assertIsNone(result.error)
                state = result.state
                states.append(state)
            result = step(state, other, action_from_id(other, 2))
            self.assertIsNone(result.error)
            self.assertEqual(result.state.winner, player)
            states.append(result.state)
            expected_ids = ((0, 1), (0, 4, 5, 6), (0, 1, 2), (0, 4, 6), (0, 2, 3), ())
            for state, ids in zip(states, expected_ids):
                with self.subTest(player=player, state=state):
                    actions = legal_actions(observe(state, player))
                    self.assertEqual(tuple(action_to_id(player, a) for a in actions), ids)
                    self.assertEqual(tuple(action_from_id(player, i) for i in ids), actions)
                    skipped = step(state, player, action_from_id(player, 0))
                    self.assertIs(skipped.state, state)
                    self.assertEqual(skipped.error, "game_over" if state.winner else None)
            holding = states[1]
            lifted_again = step(holding, player, action_from_id(player, 1))
            self.assertEqual(lifted_again.error, "hand_full")
            self.assertIs(lifted_again.state, holding)
            self.assertEqual(action_to_id(player, legal_actions(observe(holding, player))[1]), 4)


if __name__ == "__main__":
    unittest.main()

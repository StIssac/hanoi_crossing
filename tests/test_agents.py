"""Immutable decisions and observation-only agent protocol tests."""

from dataclasses import FrozenInstanceError, fields, is_dataclass
from math import inf, nan
from random import Random
import inspect
import unittest
from unittest.mock import Mock, patch

from hanoi_crossing import Action, PLAYERS, action_from_id, action_to_id
from hanoi_crossing import legal_actions, new_game, observe, step
from hanoi_crossing.agents import AgentBase, Decision
from hanoi_crossing import random_player
from hanoi_crossing.random_player import RandomAgent, choose_action


class _ConcreteAgent(AgentBase):
    def act(self, observation):
        return Decision(0)


class DecisionTests(unittest.TestCase):
    def test_decision_is_a_frozen_slotted_dataclass_with_stable_fields(self):
        self.assertTrue(is_dataclass(Decision))
        self.assertEqual(
            [field.name for field in fields(Decision)],
            ["action_id", "log_prob", "value"],
        )
        decision = Decision(0)
        self.assertIsNone(decision.log_prob)
        self.assertIsNone(decision.value)
        self.assertFalse(hasattr(decision, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            decision.action_id = 1

    def test_decision_accepts_valid_ids_and_finite_numeric_metadata(self):
        for action_id in range(7):
            with self.subTest(action_id=action_id):
                self.assertEqual(Decision(action_id).action_id, action_id)
        decision = Decision(6, log_prob=-3, value=1.25)
        self.assertEqual(decision.log_prob, -3)
        self.assertEqual(decision.value, 1.25)
        self.assertEqual(Decision(2, log_prob=0.0, value=4).value, 4)

    def test_decision_rejects_invalid_action_ids_and_metadata(self):
        for action_id in (-1, 7, True, 1.0, "1", None):
            with self.subTest(action_id=action_id):
                with self.assertRaises(ValueError):
                    Decision(action_id)

        invalid_numbers = (
            ("bool", True),
            ("string", "0.5"),
            ("nan", nan),
            ("positive infinity", inf),
            ("negative infinity", -inf),
            ("oversized integer", 10**400),
        )
        for field in ("log_prob", "value"):
            for label, value in invalid_numbers:
                with self.subTest(field=field, invalid_value=label):
                    with self.assertRaises(ValueError):
                        Decision(0, **{field: value})


class AgentBaseTests(unittest.TestCase):
    def test_agent_base_is_abstract_and_reset_is_keyword_only(self):
        self.assertTrue(inspect.isabstract(AgentBase))
        with self.assertRaises(TypeError):
            AgentBase()

        agent = _ConcreteAgent()
        agent.reset(player="A", n=2)
        self.assertEqual((agent.player, agent.n), ("A", 2))
        agent.reset(player="B", n=1)
        self.assertEqual((agent.player, agent.n), ("B", 1))
        with self.assertRaises(TypeError):
            agent.reset("A", 1)

    def test_reset_rejects_invalid_context_without_overwriting_valid_context(self):
        agent = _ConcreteAgent()
        agent.reset(player="A", n=3)
        for player in ("C", "a", None, True, 1):
            with self.subTest(player=player):
                with self.assertRaises(ValueError):
                    agent.reset(player=player, n=3)
                self.assertEqual((agent.player, agent.n), ("A", 3))
        for n in (0, -1, True, False, 1.0, None, "2"):
            with self.subTest(n=n):
                with self.assertRaises(ValueError):
                    agent.reset(player="B", n=n)
                self.assertEqual((agent.player, agent.n), ("A", 3))


class RandomAgentTests(unittest.TestCase):
    def test_agent_samples_once_from_the_complete_legal_tuple_including_skip(self):
        initial = new_game(1)
        state = step(initial, "A", Action("lift", "1a")).state
        observations = (observe(initial, "A"), observe(state, "A"))

        for observation in observations:
            expected = legal_actions(observation)
            self.assertIn(Action("skip"), expected)
            rng = Mock(spec=Random)
            rng.choice.return_value = expected[-1]
            agent = RandomAgent(rng)
            agent.reset(player=observation.player, n=1)

            with (
                patch.object(random_player.engine, "legal_actions", return_value=expected)
                as enumerate_actions,
                patch.object(random_player, "choose_action", wraps=choose_action) as select,
            ):
                decision = agent.act(observation)

            enumerate_actions.assert_called_once_with(observation)
            select.assert_called_once_with(observation, rng)
            rng.choice.assert_called_once_with(expected)
            self.assertIs(rng.choice.call_args.args[0], expected)
            self.assertEqual(decision, Decision(action_to_id(observation.player, expected[-1])))

    def test_two_agents_sharing_one_rng_match_the_legacy_choice_trajectory(self):
        seed = 918273
        shared_rng = Random(seed)
        reference_rng = Random(seed)
        agents = {player: RandomAgent(shared_rng) for player in PLAYERS}
        state = new_game(2)
        visited = 0

        for index in range(200):
            player = PLAYERS[index % 2]
            observation = observe(state, player)
            agents[player].reset(player=player, n=2)
            expected_action = choose_action(observation, reference_rng)
            expected_id = action_to_id(player, expected_action)
            decision = agents[player].act(observation)
            self.assertEqual(decision, Decision(expected_id))

            result = step(state, player, action_from_id(player, decision.action_id))
            self.assertIsNone(result.error)
            state = result.state
            visited += 1
            if state.winner is not None:
                break

        self.assertGreater(visited, 1)

    def test_terminal_observation_has_no_choice_and_agent_raises(self):
        state = new_game(1)
        state = step(state, "A", Action("lift", "1a")).state
        state = step(state, "A", Action("place", "3a")).state
        self.assertEqual(state.winner, "A")
        observation = observe(state, "A")
        rng = Mock(spec=Random)
        agent = RandomAgent(rng)
        agent.reset(player="A", n=1)

        with self.assertRaises(ValueError):
            agent.act(observation)
        rng.choice.assert_not_called()


if __name__ == "__main__":
    unittest.main()

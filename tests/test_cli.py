"""Direct contract tests for replay and random-runner functions."""

import inspect
import json
from pathlib import Path
import random
import unittest
from unittest.mock import patch

import hanoi_crossing.cli as cli
from hanoi_crossing import Action, observe
from hanoi_crossing.cli import InputError, main, run_random, run_replay


INITIAL_N1 = {
    "poles": {"1a": [1], "1b": [2], "2": [], "3a": [], "3b": []},
    "hands": {"A": None, "B": None},
    "winner": None,
}


def turn(player, kind, pole=None):
    return {"player": player, "action": {"kind": kind, "pole": pole}}


class CliRunnerTests(unittest.TestCase):
    def test_runner_signatures(self):
        for function, names in (
            (main, ()),
            (run_replay, ("data",)),
            (run_random, ("n", "seed", "max_steps")),
        ):
            with self.subTest(function=function.__name__):
                self.assertEqual(tuple(inspect.signature(function).parameters), names)

    def test_documented_replay_fixture_matches_real_runner_output(self):
        examples = Path(__file__).resolve().parents[1] / "examples"
        data = json.loads((examples / "replay.json").read_text())
        expected = json.loads((examples / "replay.expected.json").read_text())

        self.assertEqual(run_replay(data), expected)

    def test_empty_replay_returns_initial_state_and_exhaustion(self):
        self.assertEqual(
            run_replay({"n": 1, "turns": []}),
            {
                "state": INITIAL_N1,
                "steps_consumed": 0,
                "stop_reason": "sequence_exhausted",
                "steps": [],
                "unexecuted_turns": [],
            },
        )

    def test_replay_uses_repeated_actor_order_and_counts_skip(self):
        turns = [
            turn("A", "skip"),
            turn("A", "lift", "1a"),
            turn("A", "place", "3a"),
            turn("B", "skip"),
        ]
        report = run_replay({"n": 1, "turns": turns})

        self.assertEqual(report["steps_consumed"], 3)
        self.assertEqual(report["stop_reason"], "winner")
        self.assertEqual(report["state"]["winner"], "A")
        self.assertEqual(
            [record["player"] for record in report["steps"]], ["A", "A", "A"]
        )
        self.assertEqual(
            report["steps"],
            [
                {"player": item["player"], "action": item["action"], "error": None}
                for item in turns[:3]
            ],
        )
        self.assertEqual(report["unexecuted_turns"], turns[3:])

    def test_illegal_actions_and_skip_each_consume_a_replay_turn(self):
        turns = [
            turn("A", "lift", "1b"),  # Known pole, hidden from A.
            turn("A", "skip"),
            turn("B", "lift", "2"),  # Visible shared pole, currently empty.
        ]
        report = run_replay({"n": 1, "turns": turns})

        self.assertEqual(report["steps_consumed"], 3)
        self.assertEqual(report["steps_consumed"], len(report["steps"]))
        self.assertEqual(report["stop_reason"], "sequence_exhausted")
        self.assertEqual(report["state"], INITIAL_N1)
        self.assertEqual(
            [record["error"] for record in report["steps"]],
            ["invisible_pole", None, "empty_pole"],
        )
        self.assertEqual(report["unexecuted_turns"], [])

    def test_validates_entire_replay_before_initializing_even_after_a_win(self):
        turns = [
            turn("A", "lift", "1a"),
            turn("B", "lift", "1b"),
            turn("A", "place", "3a"),  # Would win before the bad tail.
            turn("B", "teleport"),
        ]
        with patch.object(cli.engine, "new_game") as create_game:
            with self.assertRaises(InputError) as caught:
                run_replay({"n": 1, "turns": turns})

        self.assertIsInstance(caught.exception, ValueError)
        self.assertIn("turns[3].action.kind", str(caught.exception))
        create_game.assert_not_called()

    def test_replay_rejects_schema_errors_with_their_input_paths(self):
        valid = turn("A", "skip")
        cases = (
            ("unknown root key", {"n": 1, "turns": [], "extra": 0}, "input"),
            ("missing root key", {"n": 1}, "input"),
            ("boolean n", {"n": True, "turns": []}, "n"),
            ("boolean turns", {"n": 1, "turns": False}, "turns"),
            (
                "unknown turn key",
                {"n": 1, "turns": [{**valid, "extra": 0}]},
                "turns[0]",
            ),
            (
                "missing player",
                {"n": 1, "turns": [{"action": valid["action"]}]},
                "turns[0]",
            ),
            (
                "invalid player",
                {"n": 1, "turns": [turn("C", "skip")]},
                "turns[0].player",
            ),
            (
                "non-object action",
                {"n": 1, "turns": [{"player": "A", "action": True}]},
                "turns[0].action",
            ),
            (
                "missing action pole",
                {"n": 1, "turns": [{"player": "A", "action": {"kind": "lift"}}]},
                "turns[0].action",
            ),
            (
                "unknown action key",
                {
                    "n": 1,
                    "turns": [
                        {"player": "A", "action": {"kind": "skip", "pole": None, "extra": 0}}
                    ],
                },
                "turns[0].action",
            ),
            (
                "invalid action kind",
                {"n": 1, "turns": [turn("A", "teleport")]},
                "turns[0].action.kind",
            ),
            (
                "boolean pole",
                {"n": 1, "turns": [turn("A", "lift", True)]},
                "turns[0].action.pole",
            ),
            (
                "unknown pole",
                {"n": 1, "turns": [turn("A", "lift", "4")]},
                "turns[0].action.pole",
            ),
            (
                "skip with pole",
                {"n": 1, "turns": [turn("A", "skip", "2")]},
                "turns[0].action.pole",
            ),
        )
        for label, data, path in cases:
            with self.subTest(case=label):
                with self.assertRaises(InputError) as caught:
                    run_replay(data)
                self.assertIsInstance(caught.exception, ValueError)
                self.assertIn(path, str(caught.exception))

    def test_winner_on_last_available_replay_turn_takes_precedence(self):
        examples = Path(__file__).resolve().parents[1] / "examples"
        data = json.loads((examples / "replay.json").read_text())
        report = run_replay(data)

        self.assertEqual(report["steps_consumed"], len(data["turns"]))
        self.assertEqual(report["stop_reason"], "winner")
        self.assertEqual(report["state"]["winner"], "A")

    def test_other_player_can_win_and_complete_replay_tail_is_preserved(self):
        turns = [
            turn("A", "lift", "1a"),
            turn("A", "place", "2"),
            turn("B", "lift", "2"),
            turn("B", "place", "3b"),
            turn("B", "lift", "1b"),
            turn("B", "place", "2"),
            turn("A", "lift", "2"),  # This makes B the winner.
            turn("B", "skip"),
            turn("A", "skip"),
        ]
        report = run_replay({"n": 1, "turns": turns})

        self.assertEqual(report["steps_consumed"], 7)
        self.assertEqual(report["steps"][-1]["player"], "A")
        self.assertEqual(report["state"]["winner"], "B")
        self.assertEqual(report["state"]["hands"], {"A": 2, "B": None})
        self.assertEqual(report["unexecuted_turns"], turns[7:])
        self.assertEqual(report["stop_reason"], "winner")

    def test_engine_failures_are_not_relabelled_as_input_errors(self):
        with patch.object(cli.engine, "new_game", side_effect=RuntimeError("engine bug")):
            with self.assertRaisesRegex(RuntimeError, "engine bug"):
                run_replay({"n": 1, "turns": []})

    def test_random_parameter_validation_rejects_booleans_and_nonpositive_limits(self):
        cases = (
            ((True, 1, 1), "n"),
            ((1, True, 1), "seed"),
            ((1, 1, True), "max_steps"),
            ((0, 1, 1), "n"),
            ((1, 1, 0), "max_steps"),
        )
        for args, path in cases:
            with self.subTest(args=args):
                with self.assertRaises(InputError) as caught:
                    run_random(*args)
                self.assertIn(path, str(caught.exception))

    def test_random_run_stops_at_limit_without_winner(self):
        with patch.object(cli, "choose_action", return_value=Action("skip")) as choose:
            report = run_random(1, 17, 4)

        self.assertEqual(report["state"], INITIAL_N1)
        self.assertEqual(report["steps_consumed"], 4)
        self.assertEqual(report["steps_consumed"], len(report["steps"]))
        self.assertEqual(report["stop_reason"], "max_steps")
        self.assertEqual(report["seed"], 17)
        self.assertEqual(report["unexecuted_turns"], [])
        self.assertEqual(
            [record["player"] for record in report["steps"]], ["A", "B", "A", "B"]
        )
        self.assertTrue(all(record["action"] == {"kind": "skip", "pole": None}
                            for record in report["steps"]))
        self.assertEqual(choose.call_count, 4)

    def test_random_runner_uses_fresh_alternating_observations_and_one_rng(self):
        observations = []
        choices = []
        actions = (
            Action("lift", "1a"),
            Action("lift", "1b"),
            Action("place", "2"),
            Action("skip"),
        )

        def capture_observation(state, player):
            result = observe(state, player)
            observations.append((state, player, result))
            return result

        def choose_skip(observation, rng):
            choices.append((observation, rng))
            return actions[len(choices) - 1]

        with (
            patch.object(cli.engine, "observe", side_effect=capture_observation) as observe_spy,
            patch.object(cli, "choose_action", side_effect=choose_skip) as choose_spy,
        ):
            report = run_random(1, 42, 4)

        self.assertEqual(observe_spy.call_count, 4)
        self.assertEqual(choose_spy.call_count, 4)
        self.assertEqual([player for _, player, _ in observations], ["A", "B", "A", "B"])
        self.assertEqual(len({id(view) for _, _, view in observations}), 4)
        for (state, player, view), (chosen_view, _) in zip(observations, choices):
            self.assertIs(chosen_view, view)
            self.assertEqual(view.player, player)
        self.assertEqual([view.hand for _, _, view in observations], [None, None, 1, 2])
        self.assertEqual(observations[3][2].visible_poles[1], (1,))
        self.assertEqual(len({id(rng) for _, rng in choices}), 1)
        self.assertEqual(report["steps_consumed"], 4)

    def test_random_last_step_win_overrides_step_limit(self):
        actions = (
            Action("lift", "1a"),
            Action("lift", "1b"),
            Action("place", "3a"),
        )
        with patch.object(cli, "choose_action", side_effect=actions) as choose:
            report = run_random(1, 9, 3)

        self.assertEqual(choose.call_count, 3)
        self.assertEqual(report["steps_consumed"], 3)
        self.assertEqual(report["stop_reason"], "winner")
        self.assertEqual(report["state"]["winner"], "A")

    def test_random_results_are_seed_reproducible_and_do_not_use_global_rng(self):
        original_global_state = random.getstate()
        self.addCleanup(random.setstate, original_global_state)
        random.seed(731)
        global_state_before = random.getstate()
        first = run_random(2, 42, 25)
        run_random(1, -13, 7)
        second = run_random(2, 42, 25)
        global_state_after = random.getstate()

        self.assertEqual(first, second)
        self.assertEqual(first["seed"], 42)
        self.assertEqual(global_state_after, global_state_before)

    def test_random_trajectory_can_be_replayed_to_the_same_state_and_steps(self):
        random_report = run_random(2, 42, 30)
        turns = [
            {"player": item["player"], "action": item["action"]}
            for item in random_report["steps"]
        ]
        replay_report = run_replay({"n": 2, "turns": turns})

        self.assertEqual(replay_report["state"], random_report["state"])
        self.assertEqual(replay_report["steps_consumed"], random_report["steps_consumed"])
        self.assertEqual(replay_report["steps"], random_report["steps"])
        if random_report["state"]["winner"] is not None:
            self.assertEqual(replay_report["stop_reason"], "winner")
        else:
            self.assertEqual(replay_report["stop_reason"], "sequence_exhausted")

    def test_random_runner_rejects_illegal_strategy_action_without_retry(self):
        with patch.object(cli, "choose_action", return_value=Action("lift", "1b")) as choose:
            with self.assertRaises(RuntimeError):
                run_random(1, 42, 10)

        self.assertEqual(choose.call_count, 1)


if __name__ == "__main__":
    unittest.main()

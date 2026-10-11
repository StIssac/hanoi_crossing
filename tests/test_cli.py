"""CLI interface and hand-authored protocol fixture checks, not CLI execution."""

import inspect
import json
from pathlib import Path
import unittest

from hanoi_crossing import Action, GameState, PLAYERS, POLE_IDS, StepResult
from hanoi_crossing.cli import main, run_random, run_replay


class CliInterfaceTests(unittest.TestCase):
    def test_runner_signatures(self):
        for function, names in (
            (main, ()),
            (run_replay, ("data",)),
            (run_random, ("n", "seed", "max_steps")),
        ):
            with self.subTest(function=function.__name__):
                self.assertEqual(tuple(inspect.signature(function).parameters), names)

    def test_unimplemented_frontends_fail_explicitly(self):
        for function, args in (
            (main, ()),
            (run_replay, ({"n": 1, "turns": []},)),
            (run_random, (1, 42, 100)),
        ):
            with self.subTest(function=function.__name__):
                with self.assertRaises(NotImplementedError):
                    function(*args)

    def test_documented_replay_fixture_is_structurally_consistent(self):
        examples = Path(__file__).resolve().parents[1] / "examples"
        data = json.loads((examples / "replay.json").read_text())
        report = json.loads((examples / "replay.expected.json").read_text())
        self.assertEqual(data["n"], 1)
        self.assertEqual([turn["player"] for turn in data["turns"]], ["A", "B", "A"])
        self.assertEqual(report["steps_consumed"], len(report["steps"]))
        self.assertEqual(report["steps_consumed"] + len(report["unexecuted_turns"]),
                         len(data["turns"]))
        for turn, result in zip(data["turns"], report["steps"]):
            self.assertEqual(result["player"], turn["player"])
            self.assertEqual(Action(**result["action"]), Action(**turn["action"]))
            self.assertIsNone(result["error"])
        raw = report["state"]
        state = GameState(
            tuple(tuple(raw["poles"][pole]) for pole in POLE_IDS),
            tuple(raw["hands"][player] for player in PLAYERS),
            raw["winner"],
        )
        self.assertEqual(state, GameState(((), (), (), (1,), ()), (None, 2), "A"))
        self.assertIsNone(StepResult(state).error)
        self.assertEqual(report["stop_reason"], "winner")

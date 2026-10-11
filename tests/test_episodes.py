"""Episode provenance, replay integrity, checkpoints, and archive failure boundaries."""

from contextlib import chdir, redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
from random import Random
import shutil
import signal
import subprocess
import sys
import sysconfig
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import UUID

from hanoi_crossing import engine, random_player
from hanoi_crossing import cli
from hanoi_crossing.agents import AgentBase, Decision


def turn(player, kind, pole=None):
    return {"player": player, "action": {"kind": kind, "pole": pole}}


class ScriptedAgent(AgentBase):
    policy_version = "test-v1"

    def __init__(self, decisions):
        self.decisions = decisions
        self.resets = []

    def reset(self, *, player, n):
        super().reset(player=player, n=n)
        self.resets.append((player, n))
        self.views = []

    def act(self, observation):
        self.views.append(observation)
        return self.decisions[len(self.views) - 1]


class ReplayAssertions:
    def assert_replays(self, data):
        events = data["events"]
        report = cli.run_replay({"n": data["metadata"]["n"], "turns": [
            {k: event[k] for k in ("player", "action")} for event in events
        ]})
        self.assertEqual(report["state"], data["end"]["final_state"])
        self.assertEqual(report["steps_consumed"], data["end"]["steps_consumed"])
        self.assertEqual(report["steps"], [
            {k: event[k] for k in ("player", "action", "error")} for event in events
        ])
        state = engine.new_game(data["metadata"]["n"])
        for index, event in enumerate(events):
            player = event["player"]
            view = engine.observe(state, player)
            self.assertEqual(event["ply"], index)
            self.assertEqual(event["observation"], {
                "player": player, "visible_poles": [list(s) for s in view.visible_poles],
                "hand": view.hand, "winner": view.winner,
            })
            ids = {engine.action_to_id(player, a) for a in engine.legal_actions(view)}
            self.assertEqual(event["action_mask"], [i in ids for i in range(7)])
            self.assertTrue(all(type(value) is bool for value in event["action_mask"]))
            action = engine.Action(**event["action"])
            if event["action_id"] is not None:
                self.assertEqual(engine.action_from_id(player, event["action_id"]), action)
            else:
                self.assertEqual(event["error"], "invisible_pole")
            state = engine.step(state, player, action).state


class EpisodeTests(ReplayAssertions, unittest.TestCase):
    def test_n2_initial_event_and_fixed_mask_are_exact(self):
        data = cli._replay_episode({"n": 2, "turns": [turn("A", "lift", "1a")]}).document()
        self.assertEqual(data["events"], [{
            "ply": 0, "player": "A",
            "observation": {"player": "A", "visible_poles": [[3, 1], [], []],
                            "hand": None, "winner": None},
            "action_mask": [True, True, False, False, False, False, False],
            "action": {"kind": "lift", "pole": "1a"}, "action_id": 1,
            "error": None, "policy_data": None,
        }])
        self.assertEqual(data["end"]["status"], "truncated")
        self.assertEqual(data["end"]["stop_reason"], "sequence_exhausted")
        self.assert_replays(data)

    def test_hidden_and_illegal_actions_are_preserved_with_repeated_actors_and_tail(self):
        turns = [turn("A", "lift", "1b"), turn("A", "place", "3a"),
                 turn("A", "skip"), turn("A", "lift", "1a"),
                 turn("A", "place", "3a"), turn("B", "skip")]
        data = cli._replay_episode({"n": 1, "turns": turns}).document()
        self.assertEqual(data["metadata"]["schedule"], {
            "kind": "explicit", "players": [t["player"] for t in turns],
        })
        self.assertEqual([e["action_id"] for e in data["events"]], [None, 6, 0, 1, 6])
        self.assertEqual([e["error"] for e in data["events"]],
                         ["invisible_pole", "empty_hand", None, None, None])
        self.assertEqual(data["events"][4]["action_mask"],
                         [True, False, False, False, True, True, True])
        self.assertEqual(data["end"]["unexecuted_turns"], turns[5:])
        self.assertEqual(data["end"]["status"], "terminated")
        self.assert_replays(data)

    def test_each_agent_resets_once_and_receives_only_its_own_observations(self):
        a = ScriptedAgent((Decision(1, -0.25, 0.75), Decision(6)))
        b = ScriptedAgent((Decision(1),))
        for match in range(2):
            data = cli._run_agents(1, (a, b), 20, "random", 42).document()
            self.assertEqual(a.resets, [("A", 1)] * (match + 1))
            self.assertEqual(b.resets, [("B", 1)] * (match + 1))
            self.assertEqual((len(a.views), len(b.views)), (2, 1))
            for player, agent in (("A", a), ("B", b)):
                self.assertTrue(all(type(v) is engine.Observation for v in agent.views))
                self.assertTrue(all(v.player == player for v in agent.views))
                self.assertFalse(any(hasattr(v, "hands") or hasattr(v, "events")
                                     for v in agent.views))
            self.assertEqual(data["events"][0]["policy_data"], {"log_prob": -0.25, "value": 0.75})
            self.assertTrue(all(e["policy_data"] is None for e in data["events"][1:]))
            self.assertEqual(data["end"]["steps_consumed"], 3)
            self.assertEqual(data["metadata"]["agents"]["A"]["policy_version"], "test-v1")
            self.assert_replays(data)

    def test_rejects_shared_instances_bad_decisions_and_illegal_agent_actions(self):
        agent = ScriptedAgent((Decision(0),))
        with self.assertRaises(cli.InputError):
            cli._run_agents(1, (agent, agent), 1, "random")
        for decision, error in (({"action_id": 0}, TypeError), (Decision(2), RuntimeError)):
            with self.subTest(decision=decision):
                a, b = ScriptedAgent((decision,)), ScriptedAgent((Decision(0),))
                with self.assertRaises(error):
                    cli._run_agents(1, (a, b), 10, "random")
                self.assertEqual(len(a.views), 1)
                self.assertEqual(len(b.views), 0)

    def test_seed_42_n5_trajectory_matches_the_pre_agent_policy(self):
        state, rng, expected = engine.new_game(5), Random(42), []
        for i in range(10000):
            player = engine.PLAYERS[i % 2]
            action = random_player.choose_action(engine.observe(state, player), rng)
            state = engine.step(state, player, action).state
            expected.append(turn(player, action.kind, action.pole) | {"error": None})
            if state.winner:
                break
        episode = cli._random_episode(5, 42, 10000)
        self.assertEqual(cli._report(episode)["steps"], expected)
        self.assertEqual((episode.attempts, episode.state.winner), (1675, "A"))
        self.assert_replays(episode.document())

    def test_python_batch_runners_do_not_read_or_write_files_or_print(self):
        output, error = StringIO(), StringIO()
        with patch("builtins.open", side_effect=AssertionError("file I/O")), \
                patch.object(cli, "_save_episode", side_effect=AssertionError("archive I/O")), \
                patch.object(cli, "_source_hash", side_effect=AssertionError("source I/O")), \
                redirect_stdout(output), redirect_stderr(error):
            cli.run_random(2, 42, 10)
            cli.run_replay({"n": 1, "turns": []})
        self.assertEqual((output.getvalue(), error.getvalue()), ("", ""))

    def test_interruption_during_event_append_discards_the_inflight_step(self):
        class InterruptedAppend(list):
            def append(self, value):
                super().append(value)
                raise KeyboardInterrupt

        episode = cli._Episode(1, "random", 42, 10)
        episode.events = InterruptedAppend()
        with self.assertRaises(KeyboardInterrupt):
            episode.apply("A", engine.observe(episode.state, "A"), engine.Action("lift", "1a"))
        episode.stop_reason = "interrupted"
        data = episode.document()
        self.assertEqual(data["events"], [])
        self.assertEqual(data["end"]["steps_consumed"], 0)
        self.assertEqual(data["end"]["status"], "aborted")
        self.assert_replays(data)


class ArchiveTests(ReplayAssertions, unittest.TestCase):
    def setUp(self):
        self.folder = Path(self.enterContext(TemporaryDirectory()))
        self.enterContext(chdir(self.folder))
        self.command = shutil.which("hanoi-crossing", path=sysconfig.get_path("scripts"))
        self.assertIsNotNone(self.command)

    def main(self, *args):
        out, err = StringIO(), StringIO()
        with patch.object(sys, "argv", ["hanoi-crossing", *args]), \
                redirect_stdout(out), redirect_stderr(err):
            code = cli.main()
        return code, out.getvalue(), err.getvalue()

    def archive(self):
        files = list(Path("runs").glob("*.json"))
        self.assertEqual(len(files), 1)
        data = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(files[0].stem, str(UUID(data["episode_id"])))
        self.assertEqual(list(Path("runs").glob("*.tmp")), [])
        self.assert_replays(data)
        return data

    def test_registered_random_saves_archive_and_preserves_stdout_report(self):
        result = subprocess.run([self.command, "random", "--n", "2", "--seed", "42",
                                 "--max-steps", "30"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(json.loads(result.stdout), cli.run_random(2, 42, 30))
        data = self.archive()
        self.assertEqual(data["schema_version"], "hanoi-crossing-episode-v1")
        meta = data["metadata"]
        self.assertEqual((meta["mode"], meta["n"], meta["seed"], meta["max_steps"]),
                         ("random", 2, 42, 30))
        self.assertEqual(meta["python_version"], sys.version.split()[0])
        self.assertRegex(meta["source_sha256"], r"^[a-f0-9]{64}$")
        self.assertEqual(meta["versions"], {"rules": "hanoi-crossing-v1", "action_ids": "v1",
                                          "observation": "v1"})
        self.assertEqual(meta["agents"], {p: {"type": "RandomAgent", "policy_version": "uniform-v1"}
                                         for p in engine.PLAYERS})

    def test_registered_replay_preserves_arbitrary_schedule_and_no_seed(self):
        replay = {"n": 1, "turns": [turn("A", "lift", "1b"), turn("A", "lift", "1a"),
                                      turn("A", "place", "3a"), turn("B", "skip")]}
        Path("input.json").write_text(json.dumps(replay))
        result = subprocess.run([self.command, "replay", "input.json"],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), cli.run_replay(replay))
        data = self.archive()
        self.assertIsNone(data["metadata"]["seed"])
        self.assertIsNone(data["metadata"]["max_steps"])
        self.assertEqual(data["events"][0]["action_id"], None)
        self.assertEqual(data["end"]["unexecuted_turns"], replay["turns"][3:])

    def test_invalid_input_or_tail_does_not_start_or_archive_a_game(self):
        bad = {"n": 1, "turns": [turn("A", "lift", "1a"), turn("A", "place", "3a"),
                                   turn("C", "skip")]}
        Path("input.json").write_text(json.dumps(bad))
        for args in (("random", "--n", "0", "--seed", "42", "--max-steps", "10"),
                     ("replay", "input.json")):
            code, out, err = self.main(*args)
            self.assertEqual(code, 2)
            self.assertEqual(out, "")
            self.assertTrue(err)
            self.assertFalse(Path("runs").exists())

    def test_collision_is_reported_without_overwriting_or_leaving_temporary_files(self):
        args = ("random", "--n", "1", "--seed", "42", "--max-steps", "1")
        with patch.object(cli, "uuid4", return_value=UUID(int=123)):
            self.assertEqual(self.main(*args)[0], 0)
            original = next(Path("runs").glob("*.json")).read_bytes()
            code, out, err = self.main(*args)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("could not save episode", err)
        self.assertEqual(next(Path("runs").glob("*.json")).read_bytes(), original)
        self.archive()

    def test_save_failures_return_nonzero_and_clean_only_our_temporary_file(self):
        Path("runs").mkdir()
        existing = Path("runs/keep.json")
        existing.write_text("existing result")
        for operation in ("fsync", "link"):
            with self.subTest(operation=operation), \
                    patch(f"hanoi_crossing.cli.os.{operation}", side_effect=OSError("disk failed")):
                code, out, err = self.main("random", "--n", "1", "--seed", "42", "--max-steps", "1")
                self.assertEqual(code, 1)
                self.assertEqual(out, "")
                self.assertIn("could not save episode", err)
                self.assertEqual(list(Path("runs").iterdir()), [existing])
                self.assertEqual(existing.read_text(), "existing result")

    def test_serialization_failure_does_not_create_an_archive_directory(self):
        data = cli._random_episode(1, 42, 1).document()
        data["invalid"] = float("nan")
        with self.assertRaises(ValueError):
            cli._save_episode(data)
        self.assertFalse(Path("runs").exists())

    def test_sigint_during_archive_publication_finishes_then_returns_130(self):
        real_fsync = os.fsync
        previous_handler = signal.getsignal(signal.SIGINT)

        def interrupt_flush(fd):
            os.kill(os.getpid(), signal.SIGINT)
            real_fsync(fd)

        with patch.object(cli.os, "fsync", side_effect=interrupt_flush):
            code, out, err = self.main("random", "--n", "1", "--seed", "42", "--max-steps", "1")
        self.assertEqual(code, 130)
        self.assertEqual(out, "")
        self.assertIn("interrupted", err)
        self.assertIs(signal.getsignal(signal.SIGINT), previous_handler)
        self.assertEqual(self.archive()["end"]["steps_consumed"], 1)

    def test_output_failure_is_not_reported_as_success_even_when_archive_is_complete(self):
        out, err = StringIO(), StringIO()
        out.close()
        with patch.object(sys, "argv", ["hanoi-crossing", "random", "--n", "1", "--seed",
                                        "42", "--max-steps", "1"]), \
                redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(cli.main(), 1)
        self.assertIn("output failed", err.getvalue())
        self.assertNotIn("saved", err.getvalue())
        self.archive()

    def test_sigint_during_failed_agent_archive_preserves_failure(self):
        real_fsync = os.fsync

        def interrupt_flush(fd):
            os.kill(os.getpid(), signal.SIGINT)
            real_fsync(fd)

        with patch.object(cli.os, "fsync", side_effect=interrupt_flush), \
                patch.object(random_player.RandomAgent, "act", return_value=Decision(2)) as act:
            code, out, err = self.main("random", "--n", "1", "--seed", "42", "--max-steps", "10")
        self.assertEqual(code, 130)
        self.assertEqual(out, "")
        self.assertIn("empty_pole; interrupted", err)
        self.assertEqual(act.call_count, 1)
        data = self.archive()
        self.assertEqual((data["end"]["status"], data["end"]["stop_reason"]),
                         ("failed", "agent_error"))
        self.assertEqual(data["end"]["steps_consumed"], 1)

    def test_random_keyboard_interrupt_archives_only_completed_actions(self):
        with patch.object(random_player.RandomAgent, "act", side_effect=(Decision(1), KeyboardInterrupt)):
            code, out, err = self.main("random", "--n", "1", "--seed", "42", "--max-steps", "10")
        self.assertEqual(code, 130)
        self.assertEqual(out, "")
        self.assertIn("interrupted", err)
        data = self.archive()
        self.assertEqual(data["end"]["steps_consumed"], 1)
        self.assertEqual((data["end"]["status"], data["end"]["stop_reason"]),
                         ("aborted", "interrupted"))

    def test_illegal_agent_attempt_is_archived_as_failure_without_retry(self):
        with patch.object(random_player.RandomAgent, "act", return_value=Decision(2)) as act:
            code, out, err = self.main("random", "--n", "1", "--seed", "42", "--max-steps", "10")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("agent produced an illegal action: empty_pole", err)
        self.assertEqual(act.call_count, 1)
        data = self.archive()
        self.assertEqual((data["end"]["status"], data["end"]["stop_reason"]),
                         ("failed", "agent_error"))
        self.assertEqual(data["end"]["steps_consumed"], 1)
        self.assertEqual(data["events"][0]["error"], "empty_pole")

    def test_replay_interrupt_preserves_unexecuted_tail(self):
        turns = [turn("A", "lift", "1a"), turn("B", "skip"), turn("A", "place", "3a")]
        Path("input.json").write_text(json.dumps({"n": 1, "turns": turns}))
        real_step, calls = engine.step, []

        def interrupt_second(state, player, action):
            calls.append(player)
            if len(calls) == 2:
                raise KeyboardInterrupt
            return real_step(state, player, action)

        with patch.object(cli.engine, "step", side_effect=interrupt_second):
            code, out, err = self.main("replay", "input.json")
        self.assertEqual(code, 130)
        self.assertEqual(out, "")
        self.assertIn("interrupted", err)
        data = self.archive()
        self.assertEqual(data["end"]["unexecuted_turns"], turns[1:])
        self.assertEqual(data["end"]["steps_consumed"], 1)

    def test_play_interrupt_after_computer_feedback_keeps_committed_state(self):
        write = cli._write

        def interrupt_feedback(text):
            if text == "Computer turn completed.\n":
                raise KeyboardInterrupt
            write(text)

        with patch.object(cli, "_write", side_effect=interrupt_feedback), \
                patch("builtins.input", return_value="1"):
            code, out, err = self.main("play", "--n", "1", "--seed", "42", "--max-steps", "10")
        self.assertEqual(code, 130)
        self.assertIn("interrupted", err)
        self.assertIn("Game stopped by user.", out)
        self.assertEqual(self.archive()["end"]["steps_consumed"], 2)


if __name__ == "__main__":
    unittest.main()

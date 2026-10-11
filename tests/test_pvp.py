"""Hot-seat handoff, observation privacy, and PvP episode archive tests."""

from contextlib import chdir, redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import re
import shutil
import subprocess
import sysconfig
import tempfile
import unittest
from unittest.mock import patch

import hanoi_crossing.cli as cli
from hanoi_crossing import Action, observe, step


class PvpInteractionTests(unittest.TestCase):
    def run_pvp(self, inputs, *, n=1, max_steps=4):
        output = StringIO()
        with patch("builtins.input", side_effect=inputs), redirect_stdout(output):
            status = cli.run_pvp(n, max_steps)
        return status, output.getvalue()

    def test_handoff_precedes_each_view_and_displays_only_current_players_information(self):
        output = StringIO()
        inputs = iter(("", "1", "", "0", "", "6"))
        before_input = []

        def read_input():
            before_input.append(output.getvalue())
            return next(inputs)

        with (
            patch("builtins.input", side_effect=read_input),
            patch.object(cli.engine, "observe", wraps=observe) as observe_spy,
            redirect_stdout(output),
        ):
            status = cli.run_pvp(1, 3)

        self.assertEqual(status, 0)
        self.assertEqual([call.args[1] for call in observe_spy.call_args_list], ["A", "B", "A"])
        self.assertEqual(
            [snapshot.count("Stacks: bottom -> top") for snapshot in before_input],
            [0, 1, 1, 2, 2, 3],
        )

        text = output.getvalue()
        handoffs = re.findall(r"请交给玩家 ([AB])，按 Enter 查看（q 退出）>", text)
        self.assertEqual(handoffs, ["A", "B", "A"])
        screens = [
            screen.split("Action [0-6 / h / q] > ", 1)[0]
            for screen in text.split("Stacks: bottom -> top\n")[1:]
        ]
        self.assertEqual(len(screens), 3)
        self.assertIn("Start  1a : [1]", screens[0])
        self.assertNotIn("1b", screens[0])
        self.assertIn("Start  1b : [2]", screens[1])
        self.assertNotIn("1a", screens[1])
        self.assertIn("Hand      : empty", screens[1])
        self.assertIn("Hand      : 1", screens[2])
        self.assertNotIn("1b", screens[2])

    def test_help_and_malformed_input_do_not_consume_turns_but_illegal_id_does(self):
        output = StringIO()
        inputs = ("", "h", "", "7", "4", "", "0")
        with (
            patch("builtins.input", side_effect=inputs),
            patch.object(cli.engine, "step", wraps=step) as step_spy,
            redirect_stdout(output),
        ):
            status = cli.run_pvp(1, 2)

        self.assertEqual(status, 0)
        self.assertEqual(step_spy.call_count, 2)
        self.assertEqual(step_spy.call_args_list[0].args[2], Action("place", "1a"))
        self.assertEqual(step_spy.call_args_list[1].args[2], Action("skip"))
        text = output.getvalue()
        for label in cli.ACTION_LABELS:
            self.assertIn(label, text)
        self.assertEqual(text.count("Action [0-6 / h / q] > "), 5)
        self.assertEqual(text.count("No turn consumed."), 2)
        self.assertIn("Illegal action: empty_hand. Turn consumed.", text)
        self.assertIn("Attempts: 2 / 2", text)

    def test_either_player_can_win_on_the_last_allowed_action(self):
        cases = (
            # A moves disk 1 to its goal, with B skipping between A's turns.
            ("A", 3, ("", "1", "", "0", "", "6")),
            # B moves its original disk 2 to its goal while A skips.
            ("B", 4, ("", "0", "", "1", "", "0", "", "6")),
        )
        for winner, max_steps, inputs in cases:
            with self.subTest(winner=winner):
                output = StringIO()
                stepped = []

                def record_step(*args):
                    result = step(*args)
                    stepped.append((args, result))
                    return result

                with (
                    patch("builtins.input", side_effect=inputs),
                    patch.object(cli.engine, "step", side_effect=record_step),
                    redirect_stdout(output),
                ):
                    status = cli.run_pvp(1, max_steps)

                self.assertEqual(status, 0)
                self.assertEqual(len(stepped), max_steps)
                self.assertEqual(stepped[-1][0][1], winner)
                self.assertEqual(stepped[-1][1].state.winner, winner)
                self.assertIn(f"Winner: {winner}.", output.getvalue())
                self.assertNotIn("Step limit reached.", output.getvalue())
                self.assertIn(f"Attempts: {max_steps} / {max_steps}", output.getvalue())

    def test_opponents_move_can_complete_the_other_players_win(self):
        # A leaves disk 1 shared, then clears its start and places disk 3 on 3a.
        # B lifting the last shared disk completes A's win, despite B holding it.
        inputs = (
            "", "1", "", "0", "", "5", "", "0",
            "", "1", "", "0", "", "6", "", "2",
        )
        output = StringIO()
        stepped = []

        def record_step(*args):
            result = step(*args)
            stepped.append((args, result))
            return result

        with (
            patch("builtins.input", side_effect=inputs),
            patch.object(cli.engine, "step", side_effect=record_step),
            redirect_stdout(output),
        ):
            status = cli.run_pvp(2, 8)

        self.assertEqual(status, 0)
        self.assertEqual(len(stepped), 8)
        final_args, final_result = stepped[-1]
        self.assertEqual(final_args[1], "B")
        self.assertEqual(final_args[2], Action("lift", "2"))
        self.assertEqual(final_result.state.winner, "A")
        self.assertEqual(final_result.state.hands, (None, 1))
        self.assertIn("Winner: A.", output.getvalue())

    def test_step_cap_without_a_winner_is_truncation_not_a_draw(self):
        output = StringIO()
        with (
            patch("builtins.input", side_effect=("", "0", "", "0")),
            patch.object(cli, "_show_end", wraps=cli._show_end) as show_end,
            redirect_stdout(output),
        ):
            status = cli.run_pvp(1, 2)

        episode = show_end.call_args.args[0]
        end = episode.document()["end"]
        self.assertEqual(status, 0)
        self.assertIsNone(episode.state.winner)
        self.assertEqual(end["status"], "truncated")
        self.assertEqual(end["stop_reason"], "max_steps")
        self.assertIn("Step limit reached. No winner.", output.getvalue())
        self.assertNotIn("Draw", output.getvalue())

    def test_quit_eof_and_interrupt_are_distinguished_in_both_input_phases(self):
        controls = (
            ("quit", "q", "quit", 0),
            ("eof", EOFError, "eof", 0),
            ("interrupt", KeyboardInterrupt, "interrupted", 130),
        )
        for stage in ("handoff", "action"):
            for label, signal, reason, expected_status in controls:
                with self.subTest(stage=stage, control=label):
                    inputs = (signal,) if stage == "handoff" else ("", signal)
                    output = StringIO()
                    with (
                        patch("builtins.input", side_effect=inputs),
                        patch.object(cli.engine, "observe", wraps=observe) as observe_spy,
                        patch.object(cli, "_show_end", wraps=cli._show_end) as show_end,
                        redirect_stdout(output),
                    ):
                        status = cli.run_pvp(1, 5)

                    episode = show_end.call_args.args[0]
                    self.assertEqual(status, expected_status)
                    self.assertEqual(episode.stop_reason, reason)
                    self.assertEqual(episode.attempts, 0)
                    self.assertEqual(episode.events, [])
                    self.assertIsNone(episode.state.winner)
                    self.assertEqual(observe_spy.call_count, 0 if stage == "handoff" else 1)
                    self.assertIn("Game stopped by user. No winner.", output.getvalue())
                    self.assertNotIn("Winner:", output.getvalue())
                    self.assertEqual("Stacks: bottom -> top" in output.getvalue(), stage == "action")


class PvpArchiveTests(unittest.TestCase):
    def test_main_passes_the_pvp_episode_document_to_the_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workdir = Path(temp_dir).resolve()
            captured = []
            output, errors = StringIO(), StringIO()
            with (
                chdir(workdir),
                patch("sys.argv", ["hanoi-crossing", "pvp", "--n", "1", "--max-steps", "3"]),
                patch("builtins.input", side_effect=("", "1", "", "0", "", "6")),
                patch.object(cli, "_save_episode",
                              side_effect=lambda document: captured.append(document)),
                redirect_stdout(output),
                redirect_stderr(errors),
            ):
                status = cli.main()

        self.assertEqual(status, 0)
        self.assertEqual(errors.getvalue(), "")
        self.assertEqual(len(captured), 1)
        archive = captured[0]
        self.assertEqual(archive["schema_version"], "hanoi-crossing-episode-v1")
        metadata = archive["metadata"]
        self.assertEqual(metadata["mode"], "pvp")
        self.assertEqual(metadata["seed"], None)
        self.assertEqual(metadata["schedule"], {"kind": "alternating", "first": "A"})
        self.assertEqual(metadata["agents"]["A"],
                         {"type": "HumanAgent", "policy_version": "terminal-v1"})
        self.assertEqual(metadata["agents"]["B"],
                         {"type": "HumanAgent", "policy_version": "terminal-v1"})
        self.assertRegex(metadata["source_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(archive["end"]["winner"], "A")
        self.assertEqual(archive["end"]["status"], "terminated")
        self.assertEqual(archive["end"]["stop_reason"], "winner")
        self.assertEqual(archive["end"]["steps_consumed"], 3)
        self.assertEqual([event["player"] for event in archive["events"]], ["A", "B", "A"])
        self.assertEqual(archive["events"][0]["observation"]["visible_poles"], [[1], [], []])
        self.assertEqual(archive["events"][1]["observation"]["visible_poles"], [[2], [], []])

    @classmethod
    def setUpClass(cls):
        command = shutil.which("hanoi-crossing", path=sysconfig.get_path("scripts"))
        if command is None:
            raise AssertionError("hanoi-crossing entry point missing; run uv sync --locked")
        cls.command = str(Path(command).resolve())

    def test_registered_pvp_command_saves_archive_in_the_current_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workdir = Path(temp_dir).resolve()
            result = subprocess.run(
                [self.command, "pvp", "--n", "1", "--max-steps", "3"],
                cwd=workdir,
                input="\n1\n\n0\n\n6\n",
                capture_output=True,
                text=True,
                timeout=15,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, "")
            self.assertIn("Winner: A.", result.stdout)
            archive_dir = workdir / "runs"
            self.assertTrue(archive_dir.is_dir())
            archive_paths = list(archive_dir.glob("*.json"))
            self.assertEqual(len(archive_paths), 1)
            archive_path = archive_paths[0].resolve()
            self.assertTrue(archive_path.is_absolute())
            archive = json.loads(archive_path.read_text(encoding="utf-8"))

        self.assertEqual(archive["metadata"]["mode"], "pvp")
        self.assertEqual(archive["metadata"]["n"], 1)
        self.assertEqual(archive["metadata"]["max_steps"], 3)
        self.assertIsNone(archive["metadata"]["seed"])
        self.assertEqual(archive["end"]["winner"], "A")
        self.assertEqual(archive["end"]["status"], "terminated")
        self.assertEqual(archive["end"]["steps_consumed"], 3)


if __name__ == "__main__":
    unittest.main()

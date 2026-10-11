"""Direct behavior tests for the human/random interactive frontend."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import unittest
from unittest.mock import patch

import hanoi_crossing.cli as cli
from hanoi_crossing import Action, step


class InteractiveTests(unittest.TestCase):
    def test_all_fixed_action_ids_decode_for_each_human_player(self):
        expected = {
            "A": (
                Action("skip"),
                Action("lift", "1a"),
                Action("lift", "2"),
                Action("lift", "3a"),
                Action("place", "1a"),
                Action("place", "2"),
                Action("place", "3a"),
            ),
            "B": (
                Action("skip"),
                Action("lift", "1b"),
                Action("lift", "2"),
                Action("lift", "3b"),
                Action("place", "1b"),
                Action("place", "2"),
                Action("place", "3b"),
            ),
        }
        for human, actions in expected.items():
            for action_id, expected_action in enumerate(actions):
                with self.subTest(human=human, action_id=action_id):
                    output = StringIO()
                    max_steps = 1 if human == "A" else 2
                    with (
                        patch("builtins.input", return_value=str(action_id)),
                        patch.object(cli, "choose_action", return_value=Action("skip")),
                        patch.object(cli.engine, "step", wraps=step) as step_spy,
                        redirect_stdout(output),
                    ):
                        status = cli.run_interactive(1, human, 42, max_steps)

                    self.assertEqual(status, 0)
                    self.assertEqual(step_spy.call_args.args[1], human)
                    self.assertEqual(step_spy.call_args.args[2], expected_action)

    def test_help_shows_fixed_labels_without_consuming_a_turn(self):
        output = StringIO()
        with (
            patch("builtins.input", side_effect=("h", "1")),
            patch.object(cli.engine, "step", wraps=step) as step_spy,
            redirect_stdout(output),
        ):
            status = cli.run_interactive(1, "A", 42, 1)

        self.assertEqual(status, 0)
        self.assertEqual(step_spy.call_count, 1)
        text = output.getvalue()
        labels = (
            "0  skip",
            "1  lift_start",
            "2  lift_shared",
            "3  lift_goal",
            "4  place_start",
            "5  place_shared",
            "6  place_goal",
        )
        for label in labels:
            self.assertIn(label, text)

    def test_screen_shows_only_the_current_legal_actions(self):
        output = StringIO()
        with (
            patch("builtins.input", side_effect=("1", "q")),
            patch.object(cli, "choose_action", return_value=Action("skip")),
            redirect_stdout(output),
        ):
            cli.run_interactive(1, "A", 42, 3)

        screens = output.getvalue().split("Legal actions:\n")
        self.assertEqual(len(screens), 3)
        initial_actions = screens[1].split("Action [", 1)[0]
        holding_actions = screens[2].split("Action [", 1)[0]
        self.assertEqual(initial_actions.splitlines(), ["0  skip", "1  lift_start"])
        self.assertEqual(
            holding_actions.splitlines(),
            ["0  skip", "4  place_start", "5  place_shared", "6  place_goal"],
        )

    def test_blank_malformed_and_out_of_range_input_retries_without_a_turn(self):
        output = StringIO()
        with (
            patch("builtins.input", side_effect=("", "x", "7", "1")),
            patch.object(cli.engine, "step", wraps=step) as step_spy,
            redirect_stdout(output),
        ):
            status = cli.run_interactive(1, "A", 42, 1)

        self.assertEqual(status, 0)
        self.assertEqual(step_spy.call_count, 1)
        text = output.getvalue()
        self.assertEqual(text.count("Action [0-6 / h / q] > "), 4)
        self.assertEqual(text.count("No turn consumed."), 3)

    def test_valid_but_illegal_id_consumes_turn_and_reports_engine_error(self):
        output = StringIO()
        with (
            patch("builtins.input", return_value="2"),
            patch.object(cli.engine, "step", wraps=step) as step_spy,
            redirect_stdout(output),
        ):
            status = cli.run_interactive(1, "A", 42, 1)

        self.assertEqual(status, 0)
        self.assertEqual(step_spy.call_count, 1)
        self.assertEqual(step_spy.call_args.args[2], Action("lift", "2"))
        self.assertIn("Illegal action: empty_pole. Turn consumed.", output.getvalue())
        self.assertIn("Attempts: 1 / 1", output.getvalue())

    def test_quit_aliases_and_eof_exit_without_consuming_a_turn(self):
        for input_side_effect in ("q", "quit", EOFError):
            with self.subTest(input=input_side_effect):
                output = StringIO()
                input_patch = (
                    patch("builtins.input", side_effect=EOFError)
                    if input_side_effect is EOFError
                    else patch("builtins.input", return_value=input_side_effect)
                )
                with (
                    input_patch,
                    patch.object(cli.engine, "step", wraps=step) as step_spy,
                    redirect_stdout(output),
                ):
                    status = cli.run_interactive(1, "A", 42, 4)

                self.assertEqual(status, 0)
                self.assertEqual(step_spy.call_count, 0)
                self.assertIn("Game stopped by user. No winner.", output.getvalue())
                self.assertNotIn("Winner:", output.getvalue())
                self.assertIn("Attempts: 0 / 4", output.getvalue())

    def test_attempt_count_includes_both_players_and_skips(self):
        output = StringIO()
        with (
            patch("builtins.input", side_effect=("0", "q")),
            patch.object(cli, "choose_action", return_value=Action("skip")) as choose,
            patch.object(cli.engine, "step", wraps=step) as step_spy,
            redirect_stdout(output),
        ):
            status = cli.run_interactive(1, "A", 42, 3)

        self.assertEqual(status, 0)
        self.assertEqual(step_spy.call_count, 2)
        self.assertEqual(choose.call_count, 1)
        self.assertIn("Computer turn completed.", output.getvalue())
        self.assertIn("Attempts: 2 / 3", output.getvalue())

    def test_player_views_and_computer_message_hide_opponent_information(self):
        cases = (
            # A skips, then B picks up disk 2 while it remains private to B.
            (
                "A", ("0", "q"), (Action("lift", "1b"),), "1b", "3b", "2",
                "Action [0-6 / h / q] > Computer turn completed.",
            ),
            # A picks up disk 1 before B's first view.
            (
                "B", ("q",), (Action("lift", "1a"),), "1a", "3a", "1",
                "Computer turn completed.",
            ),
        )
        for (
            human, inputs, computer_actions, hidden_start, hidden_goal, hidden_hand,
            expected_computer_line,
        ) in cases:
            with self.subTest(human=human):
                output = StringIO()
                chosen_observations = []

                def choose_computer(observation, rng):
                    chosen_observations.append(observation)
                    return computer_actions[len(chosen_observations) - 1]

                with (
                    patch("builtins.input", side_effect=inputs),
                    patch.object(cli, "choose_action", side_effect=choose_computer),
                    redirect_stdout(output),
                ):
                    status = cli.run_interactive(1, human, 42, 3)

                self.assertEqual(status, 0)
                self.assertEqual(len(chosen_observations), 1)
                self.assertEqual(chosen_observations[0].player, "B" if human == "A" else "A")
                self.assertNotIn(hidden_start, output.getvalue())
                self.assertNotIn(hidden_goal, output.getvalue())
                self.assertNotIn(f"Hand      : {hidden_hand}", output.getvalue())
                computer_lines = [
                    line for line in output.getvalue().splitlines()
                    if "Computer turn completed." in line
                ]
                self.assertEqual(computer_lines, [expected_computer_line])
                self.assertNotIn(f"lift {hidden_start}", output.getvalue())
                self.assertNotIn("Computer action", output.getvalue())

    def test_human_win_on_last_step_precedes_limit(self):
        output = StringIO()
        with (
            patch("builtins.input", side_effect=("1", "6")),
            patch.object(cli, "choose_action", return_value=Action("lift", "1b")),
            redirect_stdout(output),
        ):
            status = cli.run_interactive(1, "A", 42, 3)

        self.assertEqual(status, 0)
        self.assertIn("Winner: A. You win!", output.getvalue())
        self.assertNotIn("Step limit reached.", output.getvalue())
        self.assertIn("Attempts: 3 / 3", output.getvalue())

    def test_human_move_can_make_computer_win_on_last_step(self):
        output = StringIO()
        computer_actions = (Action("lift", "1b"), Action("place", "3b"))
        choices = []

        def choose_computer(observation, rng):
            choices.append((observation, rng))
            return computer_actions[len(choices) - 1]

        with (
            patch("builtins.input", side_effect=("1", "5", "2")),
            patch.object(cli, "choose_action", side_effect=choose_computer),
            redirect_stdout(output),
        ):
            status = cli.run_interactive(1, "A", 42, 5)

        self.assertEqual(status, 0)
        self.assertEqual([observation.player for observation, _ in choices], ["B", "B"])
        self.assertEqual(len({id(rng) for _, rng in choices}), 1)
        self.assertIn("Winner: B. Computer wins.", output.getvalue())
        self.assertNotIn("Step limit reached.", output.getvalue())
        self.assertIn("Attempts: 5 / 5", output.getvalue())

    def test_step_limit_counts_computer_turn_and_reports_no_winner(self):
        output = StringIO()
        with (
            patch("builtins.input", return_value="0"),
            patch.object(cli, "choose_action", return_value=Action("skip")),
            patch.object(cli.engine, "step", wraps=step) as step_spy,
            redirect_stdout(output),
        ):
            status = cli.run_interactive(1, "A", 42, 2)

        self.assertEqual(status, 0)
        self.assertEqual(step_spy.call_count, 2)
        self.assertIn("Step limit reached. No winner.", output.getvalue())
        self.assertIn("Attempts: 2 / 2", output.getvalue())

    def test_human_b_gets_one_computer_attempt_before_eof(self):
        output = StringIO()
        with (
            patch("builtins.input", side_effect=EOFError),
            patch.object(cli, "choose_action", return_value=Action("skip")) as choose,
            patch.object(cli.engine, "step", wraps=step) as step_spy,
            redirect_stdout(output),
        ):
            status = cli.run_interactive(1, "B", 42, 4)

        self.assertEqual(status, 0)
        self.assertEqual(step_spy.call_count, 1)
        self.assertEqual(step_spy.call_args.args[1], "A")
        self.assertEqual(choose.call_count, 1)
        self.assertIn("Computer turn completed.", output.getvalue())
        self.assertIn("Game stopped by user. No winner. Attempts: 1 / 4", output.getvalue())

    def test_direct_interactive_arguments_are_validated_before_game_creation(self):
        cases = (
            ((0, "A", 1, 1), "n"),
            ((1, "C", 1, 1), "human"),
            ((1, True, 1, 1), "human"),
            ((1, "A", True, 1), "seed"),
            ((1, "A", 1, 0), "max_steps"),
        )
        for args, field in cases:
            with self.subTest(args=args):
                with patch.object(cli.engine, "new_game") as new_game:
                    with self.assertRaises(cli.InputError) as caught:
                        cli.run_interactive(*args)
                self.assertIn(field, str(caught.exception))
                new_game.assert_not_called()

    def test_illegal_computer_action_raises_without_retry(self):
        output = StringIO()
        with (
            patch("builtins.input", return_value="0"),
            patch.object(cli, "choose_action", return_value=Action("lift", "1a")) as choose,
            redirect_stdout(output),
        ):
            with self.assertRaises(RuntimeError):
                cli.run_interactive(1, "A", 42, 10)

        self.assertEqual(choose.call_count, 1)
        self.assertNotIn("Computer turn completed.", output.getvalue())

    def test_main_routes_play_default_and_explicit_human(self):
        cases = (
            (
                ["hanoi-crossing", "play", "--n", "1", "--seed", "42", "--max-steps", "1"],
                "q",
                "A",
                (),
            ),
            (
                ["hanoi-crossing", "play", "--n", "1", "--human", "B", "--seed", "42",
                 "--max-steps", "2"],
                "q",
                "B",
                (Action("skip"),),
            ),
        )
        for argv, human_input, expected_human, computer_actions in cases:
            with self.subTest(human=expected_human):
                output = StringIO()
                with (
                    patch.object(sys, "argv", argv),
                    patch("builtins.input", return_value=human_input),
                    patch.object(cli, "choose_action", side_effect=computer_actions or None,
                                 return_value=Action("skip")),
                    redirect_stdout(output),
                ):
                    status = cli.main()

                self.assertEqual(status, 0)
                self.assertIn(f"You: {expected_human}", output.getvalue())

    def test_play_parser_requires_numeric_options_and_restricts_human(self):
        invalid = (
            ["hanoi-crossing", "play"],
            ["hanoi-crossing", "play", "--n", "1", "--seed", "42"],
            ["hanoi-crossing", "play", "--n", "1", "--max-steps", "3"],
            ["hanoi-crossing", "play", "--seed", "42", "--max-steps", "3"],
            ["hanoi-crossing", "play", "--n", "1", "--seed", "42", "--max-steps", "3",
             "--human", "C"],
        )
        for argv in invalid:
            with self.subTest(argv=argv):
                err = StringIO()
                with (
                    patch.object(sys, "argv", argv),
                    redirect_stderr(err),
                    redirect_stdout(StringIO()),
                ):
                    with self.assertRaises(SystemExit) as caught:
                        cli.main()
                self.assertEqual(caught.exception.code, 2)
                self.assertIn("usage:", err.getvalue())


class InteractiveMainBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.argv = patch.object(
            sys,
            "argv",
            ["hanoi-crossing", "play", "--n", "1", "--seed", "42", "--max-steps", "3"],
        )
        self.argv.start()
        self.addCleanup(self.argv.stop)

    def test_keyboard_interrupt_returns_130(self):
        output, error = StringIO(), StringIO()
        with (
            patch.object(cli, "run_interactive", side_effect=KeyboardInterrupt),
            redirect_stdout(output),
            redirect_stderr(error),
        ):
            status = cli.main()

        self.assertEqual(status, 130)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("interrupted", error.getvalue())

    def test_oserror_and_closed_input_valueerror_return_1(self):
        for input_error in (OSError("input pipe closed"), ValueError("I/O on closed input")):
            with self.subTest(error=type(input_error).__name__):
                output, error = StringIO(), StringIO()
                with (
                    patch("builtins.input", side_effect=input_error),
                    redirect_stdout(output),
                    redirect_stderr(error),
                ):
                    status = cli.main()

                self.assertEqual(status, 1)
                self.assertIn("input failed:", error.getvalue())
                self.assertNotIn("Winner:", output.getvalue())

    def test_engine_valueerror_propagates_unchanged(self):
        output, error = StringIO(), StringIO()
        with (
            patch.object(cli.engine, "new_game", side_effect=ValueError("engine defect")),
            redirect_stdout(output),
            redirect_stderr(error),
        ):
            with self.assertRaisesRegex(ValueError, "engine defect"):
                cli.main()

        self.assertEqual(output.getvalue(), "")
        self.assertEqual(error.getvalue(), "")


class InteractiveProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.command = shutil.which("hanoi-crossing", path=sysconfig.get_path("scripts"))
        if cls.command is None:
            raise AssertionError("hanoi-crossing entry point missing; run uv sync --locked")

    def test_registered_play_process_retries_counts_and_hides_private_poles(self):
        result = subprocess.run(
            [
                self.command,
                "play",
                "--n", "3",
                "--seed", "42",
                "--max-steps", "1000",
            ],
            input="h\nx\n1\n1\n6\nq\n",
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("0  skip", result.stdout)
        self.assertIn("No turn consumed.", result.stdout)
        self.assertIn("Illegal action: hand_full. Turn consumed.", result.stdout)
        self.assertEqual(result.stdout.count("Computer turn completed."), 3)
        self.assertIn("Attempts: 6 / 1000", result.stdout)
        self.assertNotIn("1b", result.stdout)
        self.assertNotIn("3b", result.stdout)


if __name__ == "__main__":
    unittest.main()

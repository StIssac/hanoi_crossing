"""Registered CLI execution and narrow process error boundaries."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import shutil
import subprocess
import sysconfig
import tempfile
import unittest
from unittest.mock import Mock, patch

from hanoi_crossing import cli


ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


class CliProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.command = shutil.which("hanoi-crossing", path=sysconfig.get_path("scripts"))
        if cls.command is None:
            raise AssertionError("hanoi-crossing entry point missing; run uv sync --locked")

    def run_cli(self, *args):
        return subprocess.run([self.command, *map(str, args)], cwd=ROOT,
                              capture_output=True, text=True, timeout=10)

    def test_replay_command_matches_fixture(self):
        result = self.run_cli("replay", EXAMPLES / "replay.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        expected = json.loads((EXAMPLES / "replay.expected.json").read_text())
        self.assertEqual(json.loads(result.stdout), expected)

    def test_random_command_matches_direct_runner(self):
        result = self.run_cli("random", "--n", 3, "--seed", 42, "--max-steps", 1000)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(json.loads(result.stdout), cli.run_random(3, 42, 1000))

    def test_json_syntax_duplicates_nonstandard_numbers_and_utf8_are_rejected(self):
        malformed = (
            b'{"n":1,',
            b'{"n":1,"n":2,"turns":[]}',
            b'{"n":1,"turns":[{"player":"A","player":"B","action":'
            b'{"kind":"skip","pole":null}}]}',
            b'{"n":NaN,"turns":[]}',
            b'{"n":Infinity,"turns":[]}',
            b'{"n":-Infinity,"turns":[]}',
            b'{"n":1e9999,"turns":[]}',
            b'\xff',
            b'[' * 2000 + b']' * 2000,
        )
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.json"
            for content in malformed:
                with self.subTest(content=content[:80]):
                    path.write_bytes(content)
                    result = self.run_cli("replay", path)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertEqual(result.stdout, "")
                    self.assertTrue(result.stderr)
                    self.assertNotIn("Traceback", result.stderr)

    def test_missing_file_and_schema_errors_are_locatable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "replay.json"
            missing = self.run_cli("replay", path)
            self.assertEqual(missing.returncode, 2)
            self.assertEqual(missing.stdout, "")
            self.assertIn(str(path), missing.stderr)
            path.write_text(json.dumps({"n": 1, "turns": [
                {"player": "A", "action": {"kind": "lift", "pole": "missing"}},
            ]}), encoding="utf-8")
            invalid = self.run_cli("replay", path)
            self.assertEqual(invalid.returncode, 2)
            self.assertEqual(invalid.stdout, "")
            self.assertIn("turns[0].action.pole", invalid.stderr)

    def test_random_arguments_are_required_and_validated(self):
        invalid = (
            (), ("random",),
            ("random", "--seed", "42", "--max-steps", "1"),
            ("random", "--n", "1", "--max-steps", "1"),
            ("random", "--n", "1", "--seed", "42"),
            ("random", "--n", "0", "--seed", "42", "--max-steps", "1"),
            ("random", "--n", "1", "--seed", "True", "--max-steps", "1"),
            ("random", "--n", "1", "--seed", "42", "--max-steps", "-1"),
        )
        for args in invalid:
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertTrue(result.stderr)

    def test_help_is_successful(self):
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertIn("usage:", result.stdout)
        self.assertIn("random", result.stdout)
        self.assertIn("replay", result.stdout)


class MainBoundaryTests(unittest.TestCase):
    def setUp(self):
        args = ["hanoi-crossing", "random", "--n", "1", "--seed", "42", "--max-steps", "1"]
        self.argv = patch("sys.argv", args)
        self.argv.start()
        self.addCleanup(self.argv.stop)

    def test_keyboard_interrupt_returns_130_without_a_report(self):
        out, err = StringIO(), StringIO()
        with patch.object(cli, "run_random", side_effect=KeyboardInterrupt), \
                redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(cli.main(), 130)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("interrupted", err.getvalue())

    def test_internal_value_errors_are_not_misclassified_as_input(self):
        for function in ("run_random", "json.dumps"):
            out, err = StringIO(), StringIO()
            with self.subTest(function=function):
                with patch(f"hanoi_crossing.cli.{function}", side_effect=ValueError("bug")), \
                        redirect_stdout(out), redirect_stderr(err):
                    with self.assertRaisesRegex(ValueError, "bug"):
                        cli.main()
                self.assertEqual(out.getvalue(), "")
                self.assertEqual(err.getvalue(), "")

    def test_write_and_flush_failures_return_nonzero(self):
        for operation in ("write", "flush"):
            with self.subTest(operation=operation):
                stdout = Mock()
                getattr(stdout, operation).side_effect = OSError("output unavailable")
                err = StringIO()
                with patch.dict("os.environ", {"TERM": "xterm-256color", "NO_COLOR": "",
                                               "FORCE_COLOR": "", "PYTHON_COLORS": ""}), \
                        patch("sys.stdout", stdout), redirect_stderr(err):
                    self.assertEqual(cli.main(), 1)
                self.assertIn("output failed", err.getvalue())

    def test_closed_stdout_is_reported_as_output_failure(self):
        out, err = StringIO(), StringIO()
        out.close()
        with patch.dict("os.environ", {"TERM": "xterm-256color", "NO_COLOR": "",
                                       "FORCE_COLOR": "", "PYTHON_COLORS": ""}), \
                redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(cli.main(), 1)
        self.assertIn("output failed", err.getvalue())


if __name__ == "__main__":
    unittest.main()

"""Count every core source line, including blanks, comments, and docstrings."""

from pathlib import Path
import unittest

import hanoi_crossing


class CoreSizeTests(unittest.TestCase):
    def test_core_stays_below_500_physical_lines(self):
        package = Path(hanoi_crossing.__file__).resolve().parent
        # Only the two existing frontend modules are excluded; new helpers count.
        frontends = {package / "cli.py", package / "random_player.py"}
        counts = {
            str(path.relative_to(package)): len(path.read_bytes().splitlines())
            for path in sorted(package.rglob("*.py")) if path not in frontends
        }
        self.assertIn("engine.py", counts)
        self.assertIn("__init__.py", counts)
        self.assertLess(sum(counts.values()), 500, f"Core physical line counts: {counts}")

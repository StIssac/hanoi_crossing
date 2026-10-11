"""Replay and random-runner interfaces; see README for the pending JSON protocol."""


def run_replay(data: dict[str, object]) -> dict[str, object]:
    """Validate a complete replay and return its report; pending implementation."""
    raise NotImplementedError("run_replay is not implemented")


def run_random(n: int, seed: int, max_steps: int) -> dict[str, object]:
    """Run alternating observation-only random players; pending implementation."""
    raise NotImplementedError("run_random is not implemented")


def main() -> int:
    """Parse CLI input and emit one JSON report; pending implementation."""
    raise NotImplementedError("CLI parsing and execution are not implemented")

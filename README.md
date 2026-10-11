# Hanoi Crossing

Project scaffold managed with uv. All Python files and example JSON files are
intentionally empty. The game engine, CLI commands, and tests are not implemented
yet.

## Setup

Requires uv and Python 3.14 or newer. The development Python version is pinned to
3.14 in `.python-version`.

```sh
uv sync --locked
```

## Layout

```text
src/hanoi_crossing/
    __init__.py          # Public engine interface
    engine.py            # State, observations, legal actions, and transitions
    random_player.py     # Random player using the external-agent interface
    cli.py               # Replay and random-play frontends
tests/
    test_engine.py
    test_random_player.py
    test_cli.py
examples/
    replay.json
    replay.expected.json
```

The planned implementation uses the Python standard library, including `unittest`
for tests. The CLI entry point will be registered when its implementation exists.
The empty example files are placeholders, not valid replay inputs yet.

## AI assistance

OpenAI Codex was used to discuss the rules and project structure, initialize this
scaffold, and prepare the commit. No game, CLI, or test implementation is included.

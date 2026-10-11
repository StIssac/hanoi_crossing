"""Replay, random-play reports, and an observation-only interactive terminal."""

import argparse
from functools import partial
import json
from pathlib import Path
from random import Random
import sys

from . import engine
from .random_player import choose_action


class InputError(ValueError):
    """An invalid input document or parameter, before any game is run."""


class TerminalError(OSError):
    """A failure reading or writing a terminal stream."""


ACTION_LABELS = (
    "skip", "lift_start", "lift_shared", "lift_goal",
    "place_start", "place_shared", "place_goal",
)


def _write(text: str) -> None:
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except (OSError, ValueError) as error:
        raise TerminalError(f"output failed: {error}") from error


def _fields(value: object, names: tuple[str, ...], path: str) -> None:
    if type(value) is not dict or value.keys() != set(names):
        raise InputError(f"{path}: expected an object with exactly {', '.join(names)}")


def _integer(value: object, path: str, *, positive: bool = False) -> None:
    if type(value) is not int or (positive and value <= 0):
        expected = "a positive integer" if positive else "an integer"
        raise InputError(f"{path}: expected {expected}, not a boolean")


def _turn(player: engine.Player, action: engine.Action) -> dict[str, object]:
    return {"player": player, "action": {"kind": action.kind, "pole": action.pole}}


def _report(
    state: engine.GameState, steps: list[dict[str, object]],
    stop_reason: str, unexecuted_turns: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "state": {
            "poles": {p: list(stack) for p, stack in zip(engine.POLE_IDS, state.poles)},
            "hands": dict(zip(engine.PLAYERS, state.hands)),
            "winner": state.winner,
        },
        "steps_consumed": len(steps),
        "stop_reason": "winner" if state.winner is not None else stop_reason,
        "steps": steps,
        "unexecuted_turns": unexecuted_turns,
    }


def run_replay(data: dict[str, object]) -> dict[str, object]:
    """Validate the entire replay, then execute its explicit player schedule."""
    _fields(data, ("n", "turns"), "input")
    _integer(data["n"], "n", positive=True)
    if type(data["turns"]) is not list:
        raise InputError("turns: expected an array")
    turns = []
    for i, turn in enumerate(data["turns"]):
        path = f"turns[{i}]"
        _fields(turn, ("player", "action"), path)
        player = turn["player"]
        if type(player) is not str or player not in engine.PLAYERS:
            raise InputError(f"{path}.player: expected 'A' or 'B'")
        raw = turn["action"]
        _fields(raw, ("kind", "pole"), f"{path}.action")
        kind, pole = raw["kind"], raw["pole"]
        if type(kind) is not str or kind not in ("lift", "place", "skip"):
            raise InputError(f"{path}.action.kind: expected 'lift', 'place', or 'skip'")
        if kind == "skip":
            if pole is not None:
                raise InputError(f"{path}.action.pole: skip requires null")
        elif type(pole) is not str or pole not in engine.POLE_IDS:
            raise InputError(f"{path}.action.pole: expected a known pole ID")
        turns.append((player, engine.Action(kind, pole)))

    state = engine.new_game(data["n"])
    steps = []
    for player, action in turns:
        result = engine.step(state, player, action)
        state = result.state
        steps.append(_turn(player, action) | {"error": result.error})
        if state.winner is not None:
            break
    tail = [_turn(player, action) for player, action in turns[len(steps):]]
    return _report(state, steps, "sequence_exhausted", tail)


def run_random(n: int, seed: int, max_steps: int) -> dict[str, object]:
    """Run alternating observation-only random players with a per-game RNG."""
    _integer(n, "n", positive=True)
    _integer(seed, "seed")
    _integer(max_steps, "max_steps", positive=True)
    state, rng = engine.new_game(n), Random(seed)
    steps = []
    for i in range(max_steps):
        player = engine.PLAYERS[i % 2]
        action = choose_action(engine.observe(state, player), rng)
        result = engine.step(state, player, action)
        if result.error is not None:
            raise RuntimeError(f"random player produced an illegal action: {result.error}")
        state = result.state
        steps.append(_turn(player, action) | {"error": None})
        if state.winner is not None:
            break
    return _report(state, steps, "max_steps", []) | {"seed": seed}


def _view(observation: engine.Observation, attempts: int, max_steps: int) -> str:
    lines = [f"\nAttempts: {attempts} / {max_steps}", "Stacks: bottom -> top", ""]
    for action_id, label, stack in zip(
        (1, 2, 3), ("Start", "Shared", "Goal"), observation.visible_poles,
    ):
        pole = engine.action_from_id(observation.player, action_id).pole
        lines.append(f"{label:6} {pole:2} : {list(stack)}")
    hand = "empty" if observation.hand is None else str(observation.hand)
    lines.extend((f"Hand      : {hand}", "", "Legal actions:"))
    for action in engine.legal_actions(observation):
        action_id = engine.action_to_id(observation.player, action)
        lines.append(f"{action_id}  {ACTION_LABELS[action_id]}")
    return "\n".join(lines) + "\n"


def _read_action(player: engine.Player) -> engine.Action | None:
    while True:
        _write("Action [0-6 / h / q] > ")
        try:
            value = input().strip().lower()
        except EOFError:
            return None
        except (OSError, ValueError) as error:
            raise TerminalError(f"input failed: {error}") from error
        if value in ("q", "quit"):
            return None
        if value in ("h", "help"):
            _write("\n".join(f"{i}  {label}" for i, label in enumerate(ACTION_LABELS))
                   + "\nh/help: help; q/quit: stop. Lift and place are separate turns.\n")
        elif value in tuple(map(str, engine.ACTION_IDS)):
            return engine.action_from_id(player, int(value))
        else:
            _write("Enter 0-6, h/help, or q/quit. No turn consumed.\n")


def run_interactive(n: int, human: engine.Player, seed: int, max_steps: int) -> int:
    """Play alternating human/random turns, exposing only the human observation."""
    _integer(n, "n", positive=True)
    _integer(seed, "seed")
    _integer(max_steps, "max_steps", positive=True)
    if type(human) is not str or human not in engine.PLAYERS:
        raise InputError("human: expected 'A' or 'B'")
    state, rng = engine.new_game(n), Random(seed)
    opponent = "B" if human == "A" else "A"
    _write(f"You: {human}    Opponent: {opponent} (random)\nA acts first. Players alternate.\n")
    for i in range(max_steps):
        player = engine.PLAYERS[i % 2]
        observation = engine.observe(state, player)
        if player == human:
            _write(_view(observation, i, max_steps))
            action = _read_action(human)
            if action is None:
                _write(f"\nGame stopped by user. No winner. Attempts: {i} / {max_steps}\n")
                return 0
        else:
            action = choose_action(observation, rng)
        result = engine.step(state, player, action)
        if player != human:
            if result.error is not None:
                raise RuntimeError(f"random player produced an illegal action: {result.error}")
            _write("Computer turn completed.\n")
        elif result.error is not None:
            _write(f"Illegal action: {result.error}. Turn consumed.\n")
        state = result.state
        if state.winner is not None:
            break
    _write(_view(engine.observe(state, human), i + 1, max_steps))
    if state.winner is not None:
        outcome = "You win!" if state.winner == human else "Computer wins."
        _write(f"Winner: {state.winner}. {outcome}\n")
    else:
        _write("Step limit reached. No winner.\n")
    return 0


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise InputError(f"nonstandard JSON number: {value}")


def main() -> int:
    """Emit a batch JSON report or run the interactive terminal frontend."""
    # Avoid argparse's color probes touching stdout before output error handling.
    parser_type = partial(argparse.ArgumentParser, color=False,
                          formatter_class=partial(argparse.HelpFormatter, color=False))
    parser = parser_type(prog="hanoi-crossing", description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True, parser_class=parser_type)
    replay = commands.add_parser("replay", help="run a recorded sequence of turns")
    replay.add_argument("path", type=Path, help="UTF-8 replay JSON file")
    random = commands.add_parser("random", help="sample all legal actions uniformly")
    random.add_argument("--n", type=int, required=True)
    random.add_argument("--seed", type=int, required=True)
    random.add_argument("--max-steps", type=int, required=True)
    play = commands.add_parser("play", help="play against a random opponent")
    play.add_argument("--n", type=int, required=True)
    play.add_argument("--human", choices=engine.PLAYERS, default="A")
    play.add_argument("--seed", type=int, required=True)
    play.add_argument("--max-steps", type=int, required=True)
    try:
        args = parser.parse_args()
        if args.mode == "play":
            return run_interactive(args.n, args.human, args.seed, args.max_steps)
        if args.mode == "replay":
            try:
                content = args.path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                raise InputError(f"{args.path}: {error}") from error
            try:
                data = json.loads(content, object_pairs_hook=_unique_object,
                                  parse_constant=_reject_constant)
            except (ValueError, RecursionError) as error:
                raise InputError(f"{args.path}: {error}") from error
            report = run_replay(data)
        else:
            report = run_random(args.n, args.seed, args.max_steps)
        output = json.dumps(report, indent=2, allow_nan=False) + "\n"
        _write(output)
        return 0
    except TerminalError as error:
        print(f"hanoi-crossing: {error}", file=sys.stderr)
        return 1
    except InputError as error:
        print(f"hanoi-crossing: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("hanoi-crossing: interrupted", file=sys.stderr)
        return 130

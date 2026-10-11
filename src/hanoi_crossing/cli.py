"""Replay, random-play reports, and an observation-only interactive terminal."""

import argparse
from functools import partial
from hashlib import sha256
import json
import os
from pathlib import Path
from random import Random
import signal
import sys
from tempfile import NamedTemporaryFile
from uuid import uuid4

from . import engine
from .agents import AgentBase, Decision
from .random_player import RandomAgent


class InputError(ValueError):
    """An invalid input document or parameter, before any game is run."""


class TerminalError(OSError):
    """A failure reading or writing a terminal stream."""


class ArchiveError(OSError):
    """An episode could not be published to its archive path."""


class _StopGame(Exception):
    """A terminal control signal, not a submitted game action."""


class _AgentError(RuntimeError):
    def __init__(self, episode, error):
        super().__init__(f"agent produced an illegal action: {error}")
        self.episode = episode


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


def _state_json(state: engine.GameState) -> dict[str, object]:
    return {
        "poles": {p: list(stack) for p, stack in zip(engine.POLE_IDS, state.poles)},
        "hands": dict(zip(engine.PLAYERS, state.hands)),
        "winner": state.winner,
    }


class _Episode:
    def __init__(self, n, mode, seed, max_steps, agents=None, turns=()):
        self._checkpoint = (engine.new_game(n), 0)
        self.events = []
        self.turns = turns
        self.episode_id = str(uuid4())
        self.stop_reason = "sequence_exhausted" if mode == "replay" else "max_steps"
        self.metadata = {
            "n": n, "mode": mode, "seed": seed, "max_steps": max_steps,
            "schedule": ({"kind": "explicit", "players": [p for p, _ in turns]}
                         if mode == "replay" else {"kind": "alternating", "first": "A"}),
            "versions": {"rules": "hanoi-crossing-v1", "action_ids": "v1",
                         "observation": "v1"},
            "source_sha256": None, "python_version": sys.version.split()[0],
            "agents": {
                p: {"type": type(a).__name__, "policy_version": a.policy_version}
                for p, a in zip(engine.PLAYERS, agents)
            } if agents else {p: {"type": "Replay", "policy_version": None}
                              for p in engine.PLAYERS},
        }

    @property
    def state(self):
        return self._checkpoint[0]

    @property
    def attempts(self):
        return self._checkpoint[1]

    def apply(self, player, observation, action, decision=None, *, strict=False):
        legal_ids = {engine.action_to_id(player, a) for a in engine.legal_actions(observation)}
        result = engine.step(self.state, player, action)
        event = {
            "ply": self.attempts, "player": player,
            "observation": {"player": observation.player,
                            "visible_poles": [list(s) for s in observation.visible_poles],
                            "hand": observation.hand, "winner": observation.winner},
            "action_mask": [i in legal_ids for i in engine.ACTION_IDS],
            "action": _turn(player, action)["action"],
            "action_id": (None if result.error == "invisible_pole"
                          else engine.action_to_id(player, action)),
            "error": result.error,
            "policy_data": ({"log_prob": decision.log_prob, "value": decision.value}
                            if decision and (decision.log_prob is not None
                                             or decision.value is not None) else None),
        }
        self.events.append(event)
        # Publish state and trace length together; discard any interrupted in-flight step.
        self._checkpoint = (result.state, len(self.events))
        if strict and result.error is not None:
            self.stop_reason = "agent_error"
            raise _AgentError(self, result.error)
        return result

    def document(self):
        reason = "winner" if self.state.winner else self.stop_reason
        status = ("terminated" if self.state.winner else "failed" if reason == "agent_error" else "truncated"
                  if reason in ("max_steps", "sequence_exhausted") else "aborted")
        return {
            "schema_version": "hanoi-crossing-episode-v1", "episode_id": self.episode_id,
            "metadata": dict(self.metadata), "events": self.events[:self.attempts],
            "end": {"final_state": _state_json(self.state), "winner": self.state.winner,
                    "status": status, "stop_reason": reason, "steps_consumed": self.attempts,
                    "unexecuted_turns": [_turn(p, a) for p, a in self.turns[self.attempts:]]},
        }


def _report(episode: _Episode) -> dict[str, object]:
    data = episode.document()
    end = data["end"]
    report = {
        "state": end["final_state"], "steps_consumed": end["steps_consumed"],
        "stop_reason": end["stop_reason"], "unexecuted_turns": end["unexecuted_turns"],
        "steps": [{k: event[k] for k in ("player", "action", "error")}
                  for event in data["events"]],
    }
    if episode.metadata["mode"] == "random":
        report["seed"] = episode.metadata["seed"]
    return report


def _replay_episode(data: dict[str, object]) -> _Episode:
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

    episode = _Episode(data["n"], "replay", None, None, turns=turns)
    try:
        for player, action in turns:
            observation = engine.observe(episode.state, player)
            episode.apply(player, observation, action)
            if episode.state.winner is not None:
                break
    except KeyboardInterrupt:
        episode.stop_reason = "interrupted"
    return episode


def run_replay(data: dict[str, object]) -> dict[str, object]:
    """Validate the entire replay and return the compatible report without I/O."""
    episode = _replay_episode(data)
    if episode.stop_reason == "interrupted":
        raise KeyboardInterrupt
    return _report(episode)


def _random_episode(n: int, seed: int, max_steps: int) -> _Episode:
    _integer(seed, "seed")
    rng = Random(seed)
    return _run_agents(n, (RandomAgent(rng), RandomAgent(rng)), max_steps, "random", seed)


def run_random(n: int, seed: int, max_steps: int) -> dict[str, object]:
    """Run observation-only random agents and return the compatible report without I/O."""
    episode = _random_episode(n, seed, max_steps)
    if episode.stop_reason == "interrupted":
        raise KeyboardInterrupt
    return _report(episode)


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


def _read_line(prompt: str) -> str:
    _write(prompt)
    try:
        value = input().strip().lower()
    except EOFError:
        raise _StopGame("eof") from None
    except (OSError, ValueError) as error:
        raise TerminalError(f"input failed: {error}") from error
    if value in ("q", "quit"):
        raise _StopGame("quit")
    return value


def _read_decision() -> Decision:
    while True:
        value = _read_line("Action [0-6 / h / q] > ")
        if value in ("h", "help"):
            _write("\n".join(f"{i}  {label}" for i, label in enumerate(ACTION_LABELS))
                   + "\nh/help: help; q/quit: stop. Lift and place are separate turns.\n")
        elif value in tuple(map(str, engine.ACTION_IDS)):
            return Decision(int(value))
        else:
            _write("Enter 0-6, h/help, or q/quit. No turn consumed.\n")


class HumanAgent(AgentBase):
    policy_version = "terminal-v1"

    def act(self, observation: engine.Observation) -> Decision:
        return _read_decision()


def _handoff(player: engine.Player) -> None:
    if sys.stdout.isatty():
        _write("\033[2J\033[H")
    while _read_line(f"请交给玩家 {player}，按 Enter 查看（q 退出）> "):
        _write("Press Enter to view, or q/quit to stop. No turn consumed.\n")


def _run_agents(n, agents, max_steps, mode, seed=None) -> _Episode:
    _integer(n, "n", positive=True)
    _integer(max_steps, "max_steps", positive=True)
    if len(agents) != 2 or agents[0] is agents[1] or any(
        not isinstance(agent, AgentBase) for agent in agents
    ):
        raise InputError("A and B require separate AgentBase instances")
    for player, agent in zip(engine.PLAYERS, agents):
        agent.reset(player=player, n=n)
    episode = _Episode(n, mode, seed, max_steps, agents)
    try:
        if mode == "play":
            human = next(p for p, a in zip(engine.PLAYERS, agents) if isinstance(a, HumanAgent))
            opponent = "B" if human == "A" else "A"
            _write(f"You: {human}    Opponent: {opponent} (random)\nA acts first. Players alternate.\n")
        for i in range(max_steps):
            player, agent = engine.PLAYERS[i % 2], agents[i % 2]
            if mode == "pvp":
                _handoff(player)
            observation = engine.observe(episode.state, player)
            if isinstance(agent, HumanAgent):
                _write(_view(observation, episode.attempts, max_steps))
            decision = agent.act(observation)
            if not isinstance(decision, Decision):
                raise TypeError("Agent.act must return a Decision")
            action = engine.action_from_id(player, decision.action_id)
            result = episode.apply(player, observation, action, decision,
                                   strict=not isinstance(agent, HumanAgent))
            if mode == "play" and not isinstance(agent, HumanAgent):
                _write("Computer turn completed.\n")
            elif result.error is not None:
                _write(f"Illegal action: {result.error}. Turn consumed.\n")
            if episode.state.winner is not None:
                break
    except _StopGame as error:
        episode.stop_reason = str(error)
    except KeyboardInterrupt:
        episode.stop_reason = "interrupted"
    return episode


def _interactive_episode(n, human, seed, max_steps) -> _Episode:
    _integer(seed, "seed")
    if type(human) is not str or human not in engine.PLAYERS:
        raise InputError("human: expected 'A' or 'B'")
    rng = Random(seed)
    agents = tuple(HumanAgent() if p == human else RandomAgent(rng) for p in engine.PLAYERS)
    return _run_agents(n, agents, max_steps, "play", seed)


def _show_end(episode: _Episode, human: engine.Player | None = None) -> int:
    count, limit = episode.attempts, episode.metadata["max_steps"]
    if episode.state.winner is None and episode.stop_reason in ("quit", "eof", "interrupted"):
        _write(f"\nGame stopped by user. No winner. Attempts: {count} / {limit}\n")
    else:
        if human is not None:
            _write(_view(engine.observe(episode.state, human), count, limit))
        else:
            _write(f"\nAttempts: {count} / {limit}\n")
        if episode.state.winner is not None:
            outcome = ("" if human is None else " You win!" if episode.state.winner == human
                       else " Computer wins.")
            _write(f"Winner: {episode.state.winner}.{outcome}\n")
        else:
            _write("Step limit reached. No winner.\n")
    return 130 if episode.stop_reason == "interrupted" else 0


def run_interactive(n: int, human: engine.Player, seed: int, max_steps: int) -> int:
    """Play human/random in the terminal; only the registered CLI archives files."""
    return _show_end(_interactive_episode(n, human, seed, max_steps), human)


def run_pvp(n: int, max_steps: int) -> int:
    """Play local hot-seat PvP; only the registered CLI archives files."""
    return _show_end(_run_agents(n, (HumanAgent(), HumanAgent()), max_steps, "pvp"))


def _source_hash() -> str | None:
    try:
        digest = sha256()
        for path in sorted(Path(__file__).parent.glob("*.py")):
            digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
        return digest.hexdigest()
    except OSError:
        return None


def _save_episode(data: dict[str, object], directory: Path = Path("runs")) -> Path:
    interrupted = False

    def defer_interrupt(signum, frame):
        nonlocal interrupted
        interrupted = True

    previous = signal.signal(signal.SIGINT, defer_interrupt)
    try:
        # Finish publishing an already-ended game before honoring another Ctrl-C.
        target = _publish_episode(data, directory)
    finally:
        signal.signal(signal.SIGINT, previous)
    if interrupted:
        raise KeyboardInterrupt
    return target


def _publish_episode(data: dict[str, object], directory: Path) -> Path:
    content = json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    target = directory / f"{data['episode_id']}.json"
    temporary = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                    prefix=".episode-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            # Hard-link publication is atomic and fails if the final name already exists.
            os.link(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    except OSError as error:
        raise ArchiveError(f"could not save episode {target}: {error}") from error
    return target


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
    pvp = commands.add_parser("pvp", help="play local two-player hot-seat")
    pvp.add_argument("--n", type=int, required=True)
    pvp.add_argument("--max-steps", type=int, required=True)
    try:
        args = parser.parse_args()
        source_hash = _source_hash()
        if args.mode == "play":
            episode = _interactive_episode(args.n, args.human, args.seed, args.max_steps)
        elif args.mode == "pvp":
            episode = _run_agents(args.n, (HumanAgent(), HumanAgent()), args.max_steps, "pvp")
        elif args.mode == "replay":
            try:
                content = args.path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                raise InputError(f"{args.path}: {error}") from error
            try:
                data = json.loads(content, object_pairs_hook=_unique_object,
                                  parse_constant=_reject_constant)
            except (ValueError, RecursionError) as error:
                raise InputError(f"{args.path}: {error}") from error
            episode = _replay_episode(data)
        else:
            episode = _random_episode(args.n, args.seed, args.max_steps)
        archive = episode.document()
        archive["metadata"]["source_sha256"] = source_hash
        _save_episode(archive)
        if args.mode in ("play", "pvp"):
            _show_end(episode, args.human if args.mode == "play" else None)
        if episode.stop_reason == "interrupted":
            print("hanoi-crossing: interrupted", file=sys.stderr)
            return 130
        if args.mode in ("random", "replay"):
            _write(json.dumps(_report(episode), indent=2, allow_nan=False) + "\n")
        return 0
    except _AgentError as error:
        archive = error.episode.document()
        archive["metadata"]["source_sha256"] = source_hash
        try:
            _save_episode(archive)
        except KeyboardInterrupt:
            print(f"hanoi-crossing: {error}; interrupted", file=sys.stderr)
            return 130
        except ArchiveError as archive_error:
            print(f"hanoi-crossing: {error}; {archive_error}", file=sys.stderr)
            return 1
        print(f"hanoi-crossing: {error}", file=sys.stderr)
        return 1
    except (TerminalError, ArchiveError) as error:
        print(f"hanoi-crossing: {error}", file=sys.stderr)
        return 1
    except InputError as error:
        print(f"hanoi-crossing: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("hanoi-crossing: interrupted", file=sys.stderr)
        return 130

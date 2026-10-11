"""Immutable game data and pure transitions for externally scheduled turns."""

from dataclasses import dataclass
from typing import Literal

type Player = Literal["A", "B"]
type PoleId = Literal["1a", "1b", "2", "3a", "3b"]
type ActionKind = Literal["lift", "place", "skip"]
type Disk = int
type Stack = tuple[Disk, ...]
type Poles = tuple[Stack, Stack, Stack, Stack, Stack]
type Hands = tuple[Disk | None, Disk | None]
type VisiblePoles = tuple[Stack, Stack, Stack]
type Error = Literal[
    "game_over", "invisible_pole", "hand_full", "empty_pole",
    "empty_hand", "illegal_placement",
]

PLAYERS: tuple[Player, Player] = ("A", "B")
POLE_IDS: tuple[PoleId, ...] = ("1a", "1b", "2", "3a", "3b")
_VISIBLE_INDICES = ((0, 2, 3), (1, 2, 4))
STEP_ERRORS: tuple[Error, ...] = (
    "game_over", "invisible_pole", "hand_full", "empty_pole",
    "empty_hand", "illegal_placement",
)


def _validate_player(player: Player) -> None:
    if type(player) is not str or player not in PLAYERS:
        raise ValueError("player must be 'A' or 'B'")


def _require_model(value: object, model: type) -> None:
    if type(value) is not model:
        raise ValueError(f"expected {model.__name__}")


def _validate_disk(disk: Disk) -> None:
    if type(disk) is not int or disk <= 0:
        raise ValueError("a disk must be a positive integer, not a boolean")


def _validate_stacks(stacks: tuple[Stack, ...], count: int) -> None:
    if type(stacks) is not tuple or len(stacks) != count:
        raise ValueError(f"expected a tuple containing {count} stacks")
    for stack in stacks:
        if type(stack) is not tuple:
            raise ValueError("each stack must be a tuple")
        for disk in stack:
            _validate_disk(disk)
        if any(lower <= upper for lower, upper in zip(stack, stack[1:])):
            raise ValueError("stacks must be strictly decreasing, bottom to top")


def _winner(poles: Poles, hands: Hands) -> Player | None:
    winners = [
        player for i, player in enumerate(PLAYERS)
        if hands[i] is None and not poles[i] and not poles[2] and poles[i + 3]
    ]
    if len(winners) > 1:
        raise ValueError("both players cannot win in the same state")
    return winners[0] if winners else None


def _move_error(kind: ActionKind, hand: Disk | None, stack: Stack) -> Error | None:
    if kind == "lift":
        if hand is not None:
            return "hand_full"
        if not stack:
            return "empty_pole"
    else:
        if hand is None:
            return "empty_hand"
        if stack and stack[-1] <= hand:
            return "illegal_placement"
    return None


@dataclass(frozen=True, slots=True)
class GameState:
    """Referee snapshot: poles follow POLE_IDS; hands follow PLAYERS."""

    poles: Poles
    hands: Hands
    winner: Player | None = None

    def __post_init__(self) -> None:
        _validate_stacks(self.poles, 5)
        if type(self.hands) is not tuple or len(self.hands) != 2:
            raise ValueError("hands must be a tuple of length 2")
        for disk in self.hands:
            if disk is not None:
                _validate_disk(disk)
        if self.winner is not None:
            _validate_player(self.winner)
        disks = [disk for stack in self.poles for disk in stack]
        disks.extend(disk for disk in self.hands if disk is not None)
        if len(disks) < 2 or len(disks) % 2:
            raise ValueError("a state must contain 2N disks for positive N")
        if set(disks) != set(range(1, len(disks) + 1)):
            raise ValueError("a state must contain every disk in 1..2N exactly once")
        if self.winner != _winner(self.poles, self.hands):
            raise ValueError("winner does not match the board")


@dataclass(frozen=True, slots=True)
class Observation:
    """Player view: own start, shared, own goal; never the other player's hand."""

    player: Player
    visible_poles: VisiblePoles
    hand: Disk | None
    winner: Player | None = None

    def __post_init__(self) -> None:
        _validate_player(self.player)
        _validate_stacks(self.visible_poles, 3)
        if self.hand is not None:
            _validate_disk(self.hand)
        if self.winner is not None:
            _validate_player(self.winner)
        disks = [disk for stack in self.visible_poles for disk in stack]
        if self.hand is not None:
            disks.append(self.hand)
        if len(set(disks)) != len(disks):
            raise ValueError("an observation cannot contain a disk twice")


@dataclass(frozen=True, slots=True)
class Action:
    """A shaped request; visibility and move legality require engine validation."""

    kind: ActionKind
    pole: PoleId | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not str or self.kind not in ("lift", "place", "skip"):
            raise ValueError("kind must be 'lift', 'place', or 'skip'")
        if self.kind == "skip":
            if self.pole is not None:
                raise ValueError("skip must have no pole")
        elif type(self.pole) is not str or self.pole not in POLE_IDS:
            raise ValueError("lift and place require a known pole ID")


@dataclass(frozen=True, slots=True)
class StepResult:
    """An accepted action has no error; rejection must retain the input state."""

    state: GameState
    error: Error | None = None

    def __post_init__(self) -> None:
        _require_model(self.state, GameState)
        if self.error is not None and (
            type(self.error) is not str or self.error not in STEP_ERRORS
        ):
            raise ValueError("unknown step error")


type ActionList = tuple[Action, ...]


def new_game(n: int) -> GameState:
    """Create a fresh game with n odd disks for A and n even disks for B."""
    if type(n) is not int or n <= 0:
        raise ValueError("n must be a positive integer, not a boolean")
    poles = (tuple(range(2 * n - 1, 0, -2)), tuple(range(2 * n, 0, -2)), (), (), ())
    return GameState(poles, (None, None))


def observe(state: GameState, player: Player) -> Observation:
    """Expose only this player's three poles, hand, and the public winner."""
    _require_model(state, GameState)
    _validate_player(player)
    i = PLAYERS.index(player)
    poles = tuple(state.poles[p] for p in _VISIBLE_INDICES[i])
    return Observation(player, poles, state.hands[i], state.winner)


def legal_actions(observation: Observation) -> ActionList:
    """List actions from this view alone: skip, then own start, shared, own goal."""
    _require_model(observation, Observation)
    if observation.winner is not None:
        return ()
    kind = "lift" if observation.hand is None else "place"
    actions = [Action("skip")]
    indices = _VISIBLE_INDICES[PLAYERS.index(observation.player)]
    for p, stack in zip(indices, observation.visible_poles):
        if _move_error(kind, observation.hand, stack) is None:
            actions.append(Action(kind, POLE_IDS[p]))
    return tuple(actions)


def step(state: GameState, player: Player, action: Action) -> StepResult:
    """Apply one atomic action, preserving the input and checking both players."""
    _require_model(state, GameState)
    _validate_player(player)
    _require_model(action, Action)
    if state.winner is not None:
        return StepResult(state, "game_over")
    if action.kind == "skip":
        return StepResult(state)
    i = PLAYERS.index(player)
    p = POLE_IDS.index(action.pole)
    if p not in _VISIBLE_INDICES[i]:
        return StepResult(state, "invisible_pole")
    stack, hand = state.poles[p], state.hands[i]
    error = _move_error(action.kind, hand, stack)
    if error is not None:
        return StepResult(state, error)
    if action.kind == "lift":
        next_stack, next_hand = stack[:-1], stack[-1]
    else:
        next_stack, next_hand = stack + (hand,), None
    poles = state.poles[:p] + (next_stack,) + state.poles[p + 1:]
    hands = state.hands[:i] + (next_hand,) + state.hands[i + 1:]
    return StepResult(GameState(poles, hands, _winner(poles, hands)))

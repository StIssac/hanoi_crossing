"""Immutable game data and engine interfaces; gameplay is not implemented yet."""

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
STEP_ERRORS: tuple[Error, ...] = (
    "game_over", "invisible_pole", "hand_full", "empty_pole",
    "empty_hand", "illegal_placement",
)


def _validate_player(player: Player) -> None:
    if type(player) is not str or player not in PLAYERS:
        raise ValueError("player must be 'A' or 'B'")


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
        if type(self.state) is not GameState:
            raise ValueError("state must be a GameState")
        if self.error is not None and (
            type(self.error) is not str or self.error not in STEP_ERRORS
        ):
            raise ValueError("unknown step error")


type ActionList = tuple[Action, ...]


def new_game(n: int) -> GameState:
    """Create the initial state for positive integer n; pending implementation."""
    raise NotImplementedError("new_game is not implemented")


def observe(state: GameState, player: Player) -> Observation:
    """Project the current state into one player's view; pending implementation."""
    raise NotImplementedError("observe is not implemented")


def legal_actions(observation: Observation) -> ActionList:
    """Enumerate valid actions from this view alone; pending implementation."""
    raise NotImplementedError("legal_actions is not implemented")


def step(state: GameState, player: Player, action: Action) -> StepResult:
    """Revalidate and execute one external turn; pending implementation."""
    raise NotImplementedError("step is not implemented")

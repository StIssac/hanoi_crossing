"""Observation-only agents and immutable decisions with optional policy data."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from math import isfinite

from .engine import ACTION_IDS, PLAYERS, Observation, Player


@dataclass(frozen=True, slots=True)
class Decision:
    action_id: int
    log_prob: float | None = None
    value: float | None = None

    def __post_init__(self) -> None:
        if type(self.action_id) is not int or self.action_id not in ACTION_IDS:
            raise ValueError("action_id must be an integer from 0 to 6, not a boolean")
        for name in ("log_prob", "value"):
            value = getattr(self, name)
            if value is not None:
                try:
                    valid = type(value) in (int, float) and isfinite(value)
                except OverflowError:
                    valid = False
                if not valid:
                    raise ValueError(f"{name} must be a finite number or None")


class AgentBase(ABC):
    policy_version: str | None = None

    def reset(self, *, player: Player, n: int) -> None:
        """Initialize public context; stateful subclasses must also clear memory."""
        if type(player) is not str or player not in PLAYERS:
            raise ValueError("player must be 'A' or 'B'")
        if type(n) is not int or n <= 0:
            raise ValueError("n must be a positive integer, not a boolean")
        self.player, self.n = player, n

    @abstractmethod
    def act(self, observation: Observation) -> Decision:
        """Choose from this player's observation, never from referee state."""

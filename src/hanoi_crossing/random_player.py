"""Observation-only random-player interface; selection is not implemented yet."""

from random import Random

from .engine import Action, Observation


def choose_action(observation: Observation, rng: Random) -> Action:
    """Uniformly sample legal actions, including skip, using the supplied RNG."""
    raise NotImplementedError("choose_action is not implemented")

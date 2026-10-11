"""Uniform random choices from the current player's complete legal action set."""

from random import Random

from . import engine


def choose_action(observation: engine.Observation, rng: Random) -> engine.Action:
    """Uniformly sample legal actions, including skip, using the supplied RNG."""
    actions = engine.legal_actions(observation)
    if not actions:
        raise ValueError("no legal actions in a terminal observation")
    return rng.choice(actions)

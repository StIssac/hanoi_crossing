"""Uniform random choices from the current player's complete legal action set."""

from random import Random

from . import engine
from .agents import AgentBase, Decision


def choose_action(observation: engine.Observation, rng: Random) -> engine.Action:
    """Uniformly sample legal actions, including skip, using the supplied RNG."""
    actions = engine.legal_actions(observation)
    if not actions:
        raise ValueError("no legal actions in a terminal observation")
    return rng.choice(actions)


class RandomAgent(AgentBase):
    policy_version = "uniform-v1"

    def __init__(self, rng: Random):
        self.rng = rng

    def act(self, observation: engine.Observation) -> Decision:
        action = choose_action(observation, self.rng)
        return Decision(engine.action_to_id(observation.player, action))

"""Model and interface checks, not acceptance tests for pending gameplay."""

from dataclasses import FrozenInstanceError, fields
import inspect
import unittest

import hanoi_crossing as game


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.state = game.GameState(((1,), (2,), (), (), ()), (None, None))
        self.view = game.Observation("A", ((1,), (), ()), None)

    def test_fixed_orders_and_observation_fields(self):
        self.assertEqual(game.POLE_IDS, ("1a", "1b", "2", "3a", "3b"))
        self.assertEqual(game.PLAYERS, ("A", "B"))
        self.assertEqual(
            [field.name for field in fields(game.Observation)],
            ["player", "visible_poles", "hand", "winner"],
        )

    def test_models_and_nested_data_are_immutable(self):
        values = (
            (self.state, "winner", "A"),
            (self.view, "hand", 1),
            (game.Action("skip"), "kind", "lift"),
            (game.StepResult(self.state), "error", "game_over"),
        )
        for value, field, replacement in values:
            with self.subTest(model=type(value).__name__):
                with self.assertRaises(FrozenInstanceError):
                    setattr(value, field, replacement)
                hash(value)
        with self.assertRaises(TypeError):
            self.state.poles[0][0] = 3
        with self.assertRaises(TypeError):
            self.state.hands[0] = 1
        with self.assertRaises(TypeError):
            self.view.visible_poles[0][0] = 3

    def test_mutable_inputs_are_rejected_not_retained(self):
        constructors = (
            lambda: game.GameState([(1,), (2,), (), (), ()], (None, None)),
            lambda: game.GameState(([1], (2,), (), (), ()), (None, None)),
            lambda: game.GameState(self.state.poles, [None, None]),
            lambda: game.Observation("A", [(1,), (), ()], None),
            lambda: game.Observation("A", ([1], (), ()), None),
            lambda: game.Observation("A", ((), (), ()), [1]),
            lambda: game.Action("lift", ["1a"]),
            lambda: game.StepResult({"poles": self.state.poles}),
            lambda: game.StepResult(self.state, ["empty_pole"]),
        )
        for construct in constructors:
            with self.subTest(construct=construct):
                with self.assertRaises(ValueError):
                    construct()

    def test_state_shape_disk_order_and_inventory(self):
        invalid = (
            (((1,), (2,), (), ()), (None, None), None),
            (self.state.poles, (None,), None),
            (((1, 3), (4, 2), (), (), ()), (None, None), None),
            (((1,), (1,), (), (), ()), (None, None), None),
            (((1,), (2,), (), (), ()), (1, 2), None),
            (((1,), (4,), (), (), ()), (None, None), None),
            (((1,), (), (), (), ()), (None, None), None),
            (((), (), (), (), ()), (None, None), None),
            (((True,), (2,), (), (), ()), (None, None), None),
            (((0,), (2,), (), (), ()), (None, None), None),
            (self.state.poles, (False, None), None),
            (self.state.poles, (None, None), "C"),
        )
        for poles, hands, winner in invalid:
            with self.subTest(poles=poles, hands=hands, winner=winner):
                with self.assertRaises(ValueError):
                    game.GameState(poles, hands, winner)
        terminal = game.GameState(((), (), (), (1,), ()), (None, 2), "A")
        self.assertEqual(terminal.winner, "A")

    def test_observation_validates_only_its_visible_inventory(self):
        partial = game.Observation("A", ((3, 1), (), ()), None)
        self.assertEqual(partial.visible_poles[0], (3, 1))
        invalid = (
            ("C", ((1,), (), ()), None, None),
            ("A", ((1,), ()), None, None),
            ("A", ((1, 3), (), ()), None, None),
            ("A", ((1,), (1,), ()), None, None),
            ("A", ((1,), (), ()), 1, None),
            ("A", ((1,), (), ()), -1, None),
            ("A", ((1,), (), ()), None, "C"),
        )
        for args in invalid:
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    game.Observation(*args)

    def test_action_shape_is_separate_from_move_legality(self):
        self.assertEqual(game.Action("skip").pole, None)
        for kind in ("lift", "place"):
            for pole in game.POLE_IDS:
                self.assertEqual(game.Action(kind, pole).pole, pole)
        for kind, pole in (
            ("move", "1a"), ("lift", None), ("place", None),
            ("skip", "2"), ("lift", "4"), (True, None),
        ):
            with self.subTest(kind=kind, pole=pole):
                with self.assertRaises(ValueError):
                    game.Action(kind, pole)

    def test_step_result_accepts_only_a_state_and_declared_errors(self):
        for error in (None, *game.STEP_ERRORS):
            result = game.StepResult(self.state, error)
            self.assertIs(result.state, self.state)
            self.assertEqual(result.error, error)
        with self.assertRaises(ValueError):
            game.StepResult(self.state, "unknown")

    def test_engine_interfaces_are_explicit_stubs(self):
        calls = (
            (game.new_game, (1,), ("n",)),
            (game.observe, (self.state, "A"), ("state", "player")),
            (game.legal_actions, (self.view,), ("observation",)),
            (game.step, (self.state, "A", game.Action("skip")),
             ("state", "player", "action")),
        )
        for function, args, parameters in calls:
            with self.subTest(function=function.__name__):
                self.assertEqual(tuple(inspect.signature(function).parameters), parameters)
                with self.assertRaisesRegex(NotImplementedError, function.__name__):
                    function(*args)

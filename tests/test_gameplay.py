"""Direct behavior tests for the immutable game engine."""

from collections import deque
import unittest

from hanoi_crossing import (
    Action,
    GameState,
    PLAYERS,
    POLE_IDS,
    legal_actions,
    new_game,
    observe,
    step,
)


ALL_ACTIONS = (Action("skip"),) + tuple(
    Action(kind, pole)
    for kind in ("lift", "place")
    for pole in POLE_IDS
)


class GameplayTests(unittest.TestCase):
    def move(self, state: GameState, player: str, kind: str, pole: str | None = None) -> GameState:
        result = step(state, player, Action(kind, pole))
        self.assertIsNone(result.error, f"{player} {kind} {pole}: {result.error}")
        return result.state

    def assert_rejected(
        self, state: GameState, player: str, kind: str, pole: str | None, error: str
    ) -> None:
        result = step(state, player, Action(kind, pole))
        self.assertEqual(result.error, error)
        self.assertIs(result.state, state)

    def reference_winner(self, state: GameState) -> str | None:
        winners = []
        for i, player in enumerate(PLAYERS):
            start, goal = ((0, 3), (1, 4))[i]
            if (
                state.hands[i] is None
                and not state.poles[start]
                and not state.poles[2]
                and state.poles[goal]
            ):
                winners.append(player)
        self.assertLessEqual(len(winners), 1)
        return winners[0] if winners else None

    def assert_n1_invariants(self, state: GameState) -> None:
        disks = [disk for stack in state.poles for disk in stack]
        disks.extend(disk for disk in state.hands if disk is not None)
        self.assertEqual(sorted(disks), [1, 2])
        for stack in state.poles:
            self.assertTrue(all(a > b for a, b in zip(stack, stack[1:])))
        self.assertEqual(state.winner, self.reference_winner(state))

    def test_initial_stacks_and_private_observations(self) -> None:
        state = new_game(3)
        self.assertEqual(state.poles, ((5, 3, 1), (6, 4, 2), (), (), ()))
        self.assertEqual(state.hands, (None, None))
        self.assertIsNone(state.winner)

        n1 = new_game(1)
        a_before = observe(n1, "A")
        b_before = observe(n1, "B")
        after_b_lifts = self.move(n1, "B", "lift", "1b")
        a_after = observe(after_b_lifts, "A")
        b_after = observe(after_b_lifts, "B")

        self.assertEqual(a_before.visible_poles, ((1,), (), ()))
        self.assertEqual(a_before, a_after)
        self.assertEqual(b_before.visible_poles, ((2,), (), ()))
        self.assertEqual(b_after.visible_poles, ((), (), ()))
        self.assertEqual(b_after.hand, 2)

        shared = self.move(self.move(n1, "A", "lift", "1a"), "A", "place", "2")
        self.assertEqual(observe(shared, "A").visible_poles, ((), (1,), ()))
        self.assertEqual(observe(shared, "B").visible_poles, ((2,), (1,), ()))

    def test_external_repeated_turns_shared_pickup_and_two_hands(self) -> None:
        state = new_game(1)
        state = self.move(state, "A", "lift", "1a")
        state = self.move(state, "A", "place", "2")
        state = self.move(state, "B", "lift", "2")
        self.assertEqual(state.hands, (None, 1))
        self.assertIsNone(state.winner)
        self.assertEqual(legal_actions(observe(state, "A")), (Action("skip"),))

        both_hold = new_game(1)
        both_hold = self.move(both_hold, "A", "lift", "1a")
        both_hold = self.move(both_hold, "B", "lift", "1b")
        self.assertEqual(both_hold.hands, (1, 2))
        self.assertIsNone(both_hold.winner)

    def test_goal_disk_can_be_lifted_and_small_disk_can_return_on_larger(self) -> None:
        state = new_game(2)
        state = self.move(state, "A", "lift", "1a")
        state = self.move(state, "A", "place", "3a")
        state = self.move(state, "A", "lift", "1a")
        state = self.move(state, "A", "place", "2")
        self.assertEqual(state.poles[2], (3,))
        self.assertEqual(state.poles[3], (1,))

        state = self.move(state, "A", "lift", "3a")
        self.assertEqual(state.hands[0], 1)
        self.assertIn(Action("place", "2"), legal_actions(observe(state, "A")))
        state = self.move(state, "A", "place", "2")
        self.assertEqual(state.poles[2], (3, 1))
        self.assertIsNone(state.winner)

    def test_illegal_actions_and_skip_preserve_state_identity(self) -> None:
        initial = new_game(1)
        skipped = step(initial, "A", Action("skip"))
        self.assertIsNone(skipped.error)
        self.assertIs(skipped.state, initial)

        self.assert_rejected(initial, "A", "lift", "1b", "invisible_pole")
        self.assert_rejected(initial, "A", "lift", "3a", "empty_pole")
        self.assert_rejected(initial, "A", "place", "3a", "empty_hand")

        holding = self.move(initial, "A", "lift", "1a")
        self.assert_rejected(holding, "A", "lift", "1b", "invisible_pole")
        self.assert_rejected(holding, "A", "lift", "1a", "hand_full")
        held_skip = step(holding, "A", Action("skip"))
        self.assertIsNone(held_skip.error)
        self.assertIs(held_skip.state, holding)

        blocked = new_game(2)
        blocked = self.move(blocked, "A", "lift", "1a")
        blocked = self.move(blocked, "A", "place", "3a")
        blocked = self.move(blocked, "A", "lift", "1a")
        blocked = self.move(blocked, "B", "lift", "1b")
        blocked = self.move(blocked, "B", "place", "2")
        self.assert_rejected(blocked, "A", "place", "2", "illegal_placement")

        terminal = new_game(1)
        terminal = self.move(terminal, "A", "lift", "1a")
        terminal = self.move(terminal, "B", "lift", "1b")
        terminal = self.move(terminal, "A", "place", "3a")
        self.assertEqual(terminal.winner, "A")
        self.assert_rejected(terminal, "B", "skip", None, "game_over")

    def test_repeated_positions_and_skips_do_not_draw(self) -> None:
        initial = new_game(1)
        state = initial
        for _ in range(4):
            state = self.move(state, "A", "lift", "1a")
            state = self.move(state, "A", "place", "1a")
            self.assertIsNone(state.winner)
        self.assertEqual(state, initial)

        for _ in range(8):
            result = step(state, "B", Action("skip"))
            self.assertIsNone(result.error)
            self.assertIs(result.state, state)
            self.assertIsNone(result.state.winner)

    def test_other_player_can_win_with_only_opponent_disk(self) -> None:
        state = new_game(1)
        state = self.move(state, "A", "lift", "1a")
        state = self.move(state, "A", "place", "2")
        state = self.move(state, "B", "lift", "2")
        state = self.move(state, "B", "place", "3b")
        state = self.move(state, "B", "lift", "1b")
        state = self.move(state, "B", "place", "2")
        self.assertIsNone(state.winner)

        # A's lift clears the shared pole and makes B win while A holds disk 2.
        state = self.move(state, "A", "lift", "2")
        self.assertEqual(state.winner, "B")
        self.assertEqual(state.hands, (2, None))
        self.assertEqual(state.poles[4], (1,))

        for player in PLAYERS:
            self.assertEqual(legal_actions(observe(state, player)), ())
        frozen = step(state, "A", Action("lift", "1a"))
        self.assertEqual(frozen.error, "game_over")
        self.assertIs(frozen.state, state)

    def test_blocked_player_can_hold_largest_disk_while_other_can_move(self) -> None:
        state = new_game(2)
        state = self.move(state, "A", "lift", "1a")
        state = self.move(state, "A", "place", "3a")
        state = self.move(state, "B", "lift", "1b")
        state = self.move(state, "B", "place", "3b")
        state = self.move(state, "B", "lift", "1b")
        state = self.move(state, "B", "place", "2")
        state = self.move(state, "B", "lift", "3b")
        state = self.move(state, "A", "lift", "2")
        state = self.move(state, "B", "place", "2")

        self.assertEqual(state.hands, (4, None))
        self.assertEqual(state.poles, ((3,), (), (2,), (1,), ()))
        self.assertIsNone(state.winner)
        self.assertEqual(legal_actions(observe(state, "A")), (Action("skip"),))
        self.assertEqual(
            legal_actions(observe(state, "B")),
            (Action("skip"), Action("lift", "2")),
        )

    def test_win_can_use_fewer_than_n_goal_disks(self) -> None:
        state = new_game(2)
        state = self.move(state, "A", "lift", "1a")
        state = self.move(state, "A", "place", "2")
        state = self.move(state, "A", "lift", "1a")
        state = self.move(state, "A", "place", "3a")
        state = self.move(state, "B", "lift", "2")

        self.assertEqual(state.winner, "A")
        self.assertEqual(state.poles[3], (3,))
        self.assertEqual(state.hands, (None, 1))

    def test_own_disk_on_goal_is_insufficient_and_more_than_n_can_win(self) -> None:
        state = new_game(1)
        state = self.move(state, "A", "lift", "1a")
        state = self.move(state, "B", "lift", "1b")
        state = self.move(state, "B", "place", "2")
        state = self.move(state, "A", "place", "3a")
        self.assertEqual(state.poles[3], (1,))
        self.assertEqual(state.poles[2], (2,))
        self.assertIsNone(state.winner)

        state = self.move(state, "A", "lift", "2")
        self.assertEqual(state.hands[0], 2)
        self.assertIsNone(state.winner)
        state = self.move(state, "A", "place", "1a")
        self.assertEqual(state.poles[0], (2,))
        self.assertEqual(state.poles[3], (1,))
        self.assertIsNone(state.winner)

        state = new_game(1)
        state = self.move(state, "A", "lift", "1a")
        state = self.move(state, "A", "place", "2")
        state = self.move(state, "B", "lift", "1b")
        state = self.move(state, "A", "lift", "2")
        state = self.move(state, "A", "place", "1a")
        state = self.move(state, "B", "place", "2")
        state = self.move(state, "A", "lift", "1a")
        state = self.move(state, "A", "place", "3a")
        self.assertIsNone(state.winner)  # Shared disk 2 still blocks A's win.
        state = self.move(state, "A", "lift", "3a")
        state = self.move(state, "A", "place", "1a")
        state = self.move(state, "A", "lift", "2")
        state = self.move(state, "A", "place", "3a")
        self.assertIsNone(state.winner)  # A's start pole still contains disk 1.
        state = self.move(state, "A", "lift", "1a")
        state = self.move(state, "A", "place", "3a")
        self.assertEqual(state.winner, "A")
        self.assertEqual(state.poles[3], (2, 1))

    def test_game_instances_are_independent(self) -> None:
        first = new_game(1)
        second = new_game(2)
        second_before = (second.poles, second.hands, second.winner)

        changed_first = self.move(first, "A", "lift", "1a")
        changed_first = self.move(changed_first, "A", "place", "2")

        self.assertEqual((second.poles, second.hands, second.winner), second_before)
        self.assertEqual(first.poles, ((1,), (2,), (), (), ()))
        self.assertEqual(changed_first.poles[2], (1,))
        self.assertIsNone(second.winner)

    def test_exhaustive_n1_reachable_states_match_step_and_reference_rules(self) -> None:
        initial = new_game(1)
        queue = deque([initial])
        seen = {initial}
        outcomes = {"ongoing": 0, "A": 0, "B": 0}

        while queue:
            state = queue.popleft()
            self.assert_n1_invariants(state)
            outcomes[state.winner or "ongoing"] += 1
            before = (state.poles, state.hands, state.winner)

            for player in PLAYERS:
                observation = observe(state, player)
                accepted = []
                for action in ALL_ACTIONS:
                    result = step(state, player, action)
                    self.assertEqual((state.poles, state.hands, state.winner), before)
                    if result.error is None:
                        accepted.append(action)
                        self.assert_n1_invariants(result.state)
                        if action.kind == "skip":
                            self.assertIs(result.state, state)
                        if result.state not in seen:
                            seen.add(result.state)
                            queue.append(result.state)
                    else:
                        self.assertIs(result.state, state)

                self.assertEqual(legal_actions(observation), tuple(accepted))

            if state.winner is None:
                self.assertFalse(
                    legal_actions(observe(state, "A")) == (Action("skip"),)
                    and legal_actions(observe(state, "B")) == (Action("skip"),)
                )

        self.assertGreater(len(seen), 1)
        self.assertGreater(outcomes["ongoing"], 0)
        self.assertGreater(outcomes["A"], 0)
        self.assertGreater(outcomes["B"], 0)
        self.assertLessEqual(len(seen), 100)
        print(f"N=1 exhaustive coverage: {len(seen)} states; {outcomes}")


if __name__ == "__main__":
    unittest.main()

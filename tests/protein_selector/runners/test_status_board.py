"""Tests for protein_selector.runners.status_board (PLAN.md §32).

``BoardState`` is plain Python by design, so the whole state machine is tested here with
no Ray and no cluster. The Ray wrapper is a pass-through to these same methods.
"""

from __future__ import annotations

from protein_selector.runners.status_board import (
    BoardState,
    StepState,
    board_actor_name,
    create_board,
    format_board,
    get_board,
)


class TestBoardState:
    def test_registered_steps_start_pending(self):
        board = BoardState(run_id="r1")
        board.register(["a", "b"])
        assert board.run_state == "pending"
        assert all(s.state is StepState.PENDING for s in board.steps.values())

    def test_reports_the_state_the_store_cannot_represent(self):
        # The point of the board: a failed step persists NO row, so the store shows only
        # an absence -- indistinguishable from "never started". The board distinguishes.
        board = BoardState(run_id="r1")
        board.register(["a", "b"])
        board.mark_running("a")
        board.mark_failed("a", "boom")
        assert board.steps["a"].state is StepState.FAILED
        assert board.steps["a"].detail == "boom"
        assert board.steps["b"].state is StepState.PENDING
        assert board.run_state == "failed"

    def test_terminal_states_are_locked_against_duplicate_reports(self):
        # Ray retries tasks, so duplicate/late reports are expected, not hypothetical.
        board = BoardState(run_id="r1")
        board.mark_running("a")
        board.mark_completed("a", "done")
        board.mark_running("a")
        assert board.steps["a"].state is StepState.COMPLETED
        board.mark_failed("a", "late failure")
        assert board.steps["a"].state is StepState.COMPLETED
        assert board.steps["a"].detail == "done"

    def test_failure_wins_over_later_success_report(self):
        board = BoardState(run_id="r1")
        board.mark_failed("a", "boom")
        board.mark_completed("a", "not really")
        assert board.steps["a"].state is StepState.FAILED

    def test_run_state_is_computed_not_stored(self):
        board = BoardState(run_id="r1")
        board.register(["a", "b"])
        board.mark_completed("a")
        assert board.run_state == "pending"      # b hasn't started
        board.mark_running("b")
        assert board.run_state == "running"
        board.mark_completed("b")
        assert board.run_state == "completed"

    def test_duration_needs_both_ends(self):
        board = BoardState(run_id="r1")
        board.mark_running("a", now=100.0)
        assert board.steps["a"].duration_seconds is None
        board.mark_completed("a", now=104.5)
        assert board.steps["a"].duration_seconds == 4.5

    def test_snapshot_is_renderable(self):
        board = BoardState(run_id="r1")
        board.register(["alpha"])
        board.mark_running("alpha", now=1.0)
        board.mark_completed("alpha", "12 candidates", now=3.0)
        text = format_board(board.snapshot())
        assert "r1" in text and "alpha" in text and "12 candidates" in text
        assert "completed" in text


class TestBoardIsNeverRequired:
    """PLAN.md §32's invariant: the board is a view, never an authority."""

    def test_lookup_without_ray_returns_none_rather_than_raising(self):
        # A missing board is a normal state -- Ray absent, not initialised, or no such
        # actor. Callers must degrade to "no status", never to a failed run.
        assert get_board("no-such-run") is None

    def test_create_without_an_initialised_ray_returns_none(self):
        assert create_board("no-such-run", ["a"]) is None

    def test_actor_name_is_deterministic_so_any_process_can_find_it(self):
        assert board_actor_name("abc") == board_actor_name("abc")
        assert "abc" in board_actor_name("abc")

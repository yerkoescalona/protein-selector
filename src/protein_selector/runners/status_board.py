"""Live status board for a run (PLAN.md §32).

**What this answers that the store cannot.** ``cache/protein_selector.db`` is the
authority on what is *done* -- a row appears when a stage finishes. It therefore cannot
answer three questions that matter while a run is in flight:

* which step is **running right now**;
* which step **failed** (a failure persists no row at all, so the store shows only an
  absence, indistinguishable from "not started");
* how long each step **took**.

The board answers exactly those and nothing else.

**The invariant that keeps this from repeating the marker-file mistake.** This repo
already shipped a second completion ledger once -- 2,830 ``results/*.done`` files -- and
it went stale: the store knew 2,357 md_simulation results against 1,506 markers
(PLAN.md §31a). So:

    The board is a VIEW, never an authority.
    Nothing may ever read it to decide whether to run work.

Skip decisions stay where they are: each stage asks the store. If the board disappears --
actor killed, cluster restarted, never created at all -- the run must behave identically.
That is why every board call in the runner is wrapped so a failure degrades to "no
status", never to a failed run.

``BoardState`` is deliberately plain Python with no Ray import, so the state machine is
unit-testable without a cluster; ``RunStatusBoard`` is the thin Ray actor wrapper.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class StepState(StrEnum):
    """Lifecycle of one step within a run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


_TERMINAL = frozenset({StepState.COMPLETED, StepState.FAILED})


@dataclass
class StepStatus:
    """One row of the board."""

    step: str
    state: StepState = StepState.PENDING
    started_at: float | None = None
    finished_at: float | None = None
    detail: str | None = None

    @property
    def duration_seconds(self) -> float | None:
        """Wall-clock seconds the step ran, or ``None`` if it hasn't finished."""
        if self.started_at is None or self.finished_at is None:
            return None
        return self.finished_at - self.started_at


@dataclass
class BoardState:
    """The state machine behind the board -- plain Python, no Ray, so it is testable.

    Terminal states are **locked**: a late or duplicated report can never flip a finished
    step back to running. Ray retries a failed task, so duplicate reports are expected,
    not hypothetical.
    """

    run_id: str
    steps: dict[str, StepStatus] = field(default_factory=dict)

    def register(self, step_names: list[str]) -> None:
        """Declare every step up front so a run shows what has *not* started yet."""
        for name in step_names:
            self.steps.setdefault(name, StepStatus(step=name))

    def mark_running(self, step: str, now: float | None = None) -> None:
        """Record that a step began. Ignored if the step already finished."""
        status = self.steps.setdefault(step, StepStatus(step=step))
        if status.state in _TERMINAL:
            return
        status.state = StepState.RUNNING
        status.started_at = time.time() if now is None else now

    def mark_completed(
        self, step: str, detail: str | None = None, now: float | None = None
    ) -> None:
        """Record success. A step that already failed stays failed -- see class docstring."""
        status = self.steps.setdefault(step, StepStatus(step=step))
        if status.state in _TERMINAL:
            return
        status.state = StepState.COMPLETED
        status.finished_at = time.time() if now is None else now
        status.detail = detail

    def mark_failed(
        self, step: str, detail: str | None = None, now: float | None = None
    ) -> None:
        """Record failure, which is the state the store can never represent on its own."""
        status = self.steps.setdefault(step, StepStatus(step=step))
        if status.state in _TERMINAL:
            return
        status.state = StepState.FAILED
        status.finished_at = time.time() if now is None else now
        status.detail = detail

    @property
    def run_state(self) -> str:
        """Overall state, COMPUTED from the steps rather than stored as a fourth field.

        Storing it would be a second thing to keep consistent with the rows it summarises
        -- the same class of bug as the stale marker files.
        """
        states = {s.state for s in self.steps.values()}
        if StepState.FAILED in states:
            return "failed"
        if states and states <= {StepState.COMPLETED}:
            return "completed"
        if StepState.RUNNING in states:
            return "running"
        return "pending"

    def snapshot(self) -> dict[str, object]:
        """A picklable view for another process to render."""
        return {
            "run_id": self.run_id,
            "run_state": self.run_state,
            "steps": [
                {
                    "step": s.step,
                    "state": str(s.state),
                    "started_at": s.started_at,
                    "finished_at": s.finished_at,
                    "duration_seconds": s.duration_seconds,
                    "detail": s.detail,
                }
                for s in self.steps.values()
            ],
        }


def format_board(snapshot: dict[str, object]) -> str:
    """Render a snapshot as a table, in the spirit of `squeue` for one run."""
    icons = {"pending": "…", "running": "▶", "completed": "✔", "failed": "✗"}
    lines = [
        f"run {snapshot['run_id']} -- {snapshot['run_state']}",
        f"{'step':<26}{'state':<12}{'seconds':>9}  detail",
        "-" * 72,
    ]
    for row in snapshot["steps"]:  # ty: ignore[not-iterable]
        secs = row["duration_seconds"]
        lines.append(
            f"{row['step']:<26}"
            f"{icons.get(row['state'], '?') + ' ' + row['state']:<12}"
            f"{('' if secs is None else f'{secs:.1f}'):>9}  "
            f"{row['detail'] or ''}"
        )
    return "\n".join(lines)


# A FIXED namespace, so a board created by one process is findable from another (PLAN.md
# §36). Ray puts detached actors in an anonymous per-session namespace by default, and then
# warns that you must reconnect with that random namespace to reach them -- which makes
# `make ray-watch` in a second terminal impossible. Naming it removes the guesswork.
NAMESPACE = "protein-selector"


def board_actor_name(run_id: str) -> str:
    """Deterministic actor name, so any process in the cluster can find a run's board."""
    return f"protein-selector-status-{run_id}"


def get_board(run_id: str):
    """Look up a running board by run id, or ``None`` if there isn't one.

    Returns ``None`` rather than raising for every failure mode (Ray absent, not
    initialised, no such actor) -- a missing board is a normal state, not an error.
    """
    try:
        import ray

        if not ray.is_initialized():
            return None
        return ray.get_actor(board_actor_name(run_id), namespace=NAMESPACE)
    except Exception:
        return None


def create_board(run_id: str, step_names: list[str]):
    """Create (or replace) the detached actor holding this run's board.

    ``lifetime="detached"`` so the board outlives the driver script -- the point is to
    still be able to ask "what happened" after a driver crash. Returns ``None`` if Ray
    is unavailable, so callers degrade to running without status rather than failing.
    """
    try:
        import ray

        if not ray.is_initialized():
            return None
        name = board_actor_name(run_id)
        try:  # replace a board left behind by a previous run of the same id
            ray.kill(ray.get_actor(name, namespace=NAMESPACE))
        except Exception:
            pass
        board = RunStatusBoard.options(
            name=name, namespace=NAMESPACE, lifetime="detached"
        ).remote(run_id)
        ray.get(board.register.remote(step_names))
        return board
    except Exception:
        return None


def _make_actor_class():
    """Define the Ray actor lazily, so importing this module never requires Ray."""
    import ray

    @ray.remote
    class _RunStatusBoard:
        """Thin Ray wrapper over ``BoardState`` -- all logic lives in the plain class."""

        def __init__(self, run_id: str) -> None:
            self._state = BoardState(run_id=run_id)

        def register(self, step_names: list[str]) -> None:
            self._state.register(step_names)

        def mark_running(self, step: str) -> None:
            self._state.mark_running(step)

        def mark_completed(self, step: str, detail: str | None = None) -> None:
            self._state.mark_completed(step, detail)

        def mark_failed(self, step: str, detail: str | None = None) -> None:
            self._state.mark_failed(step, detail)

        def snapshot(self) -> dict[str, object]:
            return self._state.snapshot()

    return _RunStatusBoard


class _LazyActor:
    """Defers ``@ray.remote`` class creation to first use (Ray is an optional group)."""

    _cls = None

    def options(self, **kwargs):
        """Mirror ``ActorClass.options`` so callers read like normal Ray code."""
        if _LazyActor._cls is None:
            _LazyActor._cls = _make_actor_class()
        return _LazyActor._cls.options(**kwargs)


RunStatusBoard = _LazyActor()

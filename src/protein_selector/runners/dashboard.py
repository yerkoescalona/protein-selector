"""A terminal view of the graph as it executes (PLAN.md §36).

**Why this exists alongside Ray's own dashboard.** Ray's dashboard shows *Ray tasks* --
anonymous worker processes, CPU and memory, object-store pressure. It is the right tool for
"is the cluster healthy, is anything stuck". It cannot show what this project is actually
about, because it has never heard of a candidate: it cannot say *"21 of 27 candidates
passed MD"* or *"docking is waiting on relaxed_structure"*. That is the same job-level vs
domain-level split §29b found when Snakemake's report could not answer how many candidates
passed docking either.

So the two views are complementary and neither replaces the other:

    Ray dashboard   :8265   are the workers healthy, what is each task doing
    this            CLI     where is the graph, per stage and per node, in domain terms

**Everything here is derived, never stored.** Node states come from the run's status board
(§32) when a cluster is up, and the per-candidate counts come from the store, which is the
only authority on what is done (§31a). Nothing is written, so watching a run can never
change it -- and if the board is missing the view degrades to store-only rather than
failing.

The "waiting on ..." line is the payoff from the node cards (§35): a node that has not run
is blocked on some input socket, and the socket declarations say which -- so the view can
name the wire rather than just saying "pending".
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from protein_selector.core.registry import (
    STAGE_ORDER,
    NodeSpec,
    SocketKind,
    discover_nodes,
    producers_of,
)

_ICON = {
    "completed": "✔",
    "running": "▶",
    "failed": "✗",
    "pending": "·",
    "unknown": " ",
}


@dataclass
class NodeView:
    """One rendered row: a node, its state, and whatever progress is knowable."""

    name: str
    stage: str
    state: str
    detail: str = ""
    done: int | None = None
    total: int | None = None

    @property
    def bar(self) -> str:
        """A ten-cell progress bar, or blank when progress is not countable."""
        if self.done is None or not self.total:
            return ""
        filled = round(10 * min(self.done / self.total, 1.0))
        return "█" * filled + "░" * (10 - filled) + f" {self.done}/{self.total}"


def _table_counts(db_path: Path) -> dict[str, int]:
    """Row count per table, or an empty mapping if the store isn't there yet."""
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    try:
        tables = [
            r[0] for r in conn.execute("select name from sqlite_master where type='table'")
        ]
        return {t: conn.execute(f"select count(*) from {t}").fetchone()[0] for t in tables}
    finally:
        conn.close()


def _validation_counts(db_path: Path) -> dict[str, int]:
    """Rows per exercise in `validation` -- the per-candidate progress of the slow lanes."""
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    try:
        return {
            row[0]: row[1]
            for row in conn.execute(
                "select exercise, count(*) from validation group by exercise"
            )
        }
    finally:
        conn.close()


# Node -> the plan entry that already knows this node's ELIGIBLE POOL. Reused rather than
# re-derived: getting a denominator wrong has bitten this project twice already (docking
# counted against every candidate, 2,065 phantom jobs; modeling counted candidates with no
# UniProt accession, 28 more). `plan_pipeline` is where those were fixed, so the dashboard
# asks it instead of computing its own and repeating the mistake a third time.
_PLAN_ENTRY_OF_NODE = {
    "check_simulability": "simulability",
    "resolve_ligands": "ligands",
    "count_literature": "literature",
    "lookup_alphafold": "modeling",
    "sanitize_ligand": "parameterizability",
    "parameterize_ligand": "meeko",
    "simulate_md": "md_simulation",
    "dock_ligand": "docking",
}


def _relaxed_structures_exist(db_path: Path) -> bool:
    """Has any MD-relaxed receptor been written (the ARTIFACT socket, §35b)?

    Artifact sockets are files, not tables, so a table-count check can never see them --
    which made every downstream node read as "waiting on relaxed_structure" even when
    thousands existed.
    """
    structures = db_path.parent / "structures"
    if not structures.exists():
        return False
    return any(structures.glob("*/*_relaxed.pdb"))


def blocked_on(spec: NodeSpec, satisfied: set[str]) -> str:
    """Which declared input socket is not yet available -- named, not guessed.

    This is what the cards buy: a pending node is pending *for a reason*, and the reason is
    a wire. Without socket declarations the only honest thing to print is "pending".
    """
    missing = [
        s.name
        for s in spec.inputs
        if s.required and s.name not in satisfied and producers_of(s.name)
    ]
    return f"waiting on {', '.join(missing)}" if missing else ""


def build_view(db_path: Path, board_snapshot: dict | None = None) -> list[NodeView]:
    """Render the whole graph's current state from the board and the store."""
    states: dict[str, str] = {}
    details: dict[str, str] = {}
    if board_snapshot:
        for row in board_snapshot.get("steps", []):  # type: ignore[union-attr]
            states[row["step"]] = row["state"]
            secs = row.get("duration_seconds")
            details[row["step"]] = row.get("detail") or (
                f"{secs:.1f}s" if secs is not None else ""
            )

    tables = _table_counts(db_path)
    satisfied = {name for name, count in tables.items() if count}
    if _relaxed_structures_exist(db_path):
        satisfied |= {"relaxed_structure", "complex_relaxed_structure"}
    # Collections are handed along in memory, so their availability is a property of the
    # run rather than of the store; treat them as satisfied once their producer has run.
    satisfied |= {
        s.name
        for spec in discover_nodes()
        if states.get(spec.name) == "completed"
        for s in spec.outputs
    }

    plan = {}
    try:
        from protein_selector.runners.ray_runner import plan_pipeline

        plan = {p.stage: p for p in plan_pipeline(db_path)}
    except Exception:  # pragma: no cover - the view must never break a run
        plan = {}

    views: list[NodeView] = []
    for stage in STAGE_ORDER:
        for spec in (n for n in discover_nodes() if n.stage == stage):
            state = states.get(spec.name, "unknown")
            detail = details.get(spec.name, "")
            done = total = None
            entry = plan.get(_PLAN_ENTRY_OF_NODE.get(spec.name, ""))
            if entry is not None:
                done = entry.already_done
                total = entry.already_done + entry.pending
            elif spec.outputs:
                first = spec.outputs[0]
                if first.kind is SocketKind.TABLE and first.name in tables:
                    detail = detail or f"{tables[first.name]} rows"
            if state in ("unknown", "pending") and not detail:
                detail = blocked_on(spec, satisfied)
            views.append(NodeView(spec.name, stage, state, detail, done, total))
    return views


def render(views: list[NodeView], run_id: str | None, run_state: str | None) -> str:
    """Format the view as a table, grouped by stage."""
    header = f"run {run_id or '(none)'} -- {run_state or 'no live board'}"
    lines = [header, "=" * 72]
    current = None
    for view in views:
        stage = view.stage if view.stage != current else ""
        current = view.stage
        icon = _ICON.get(view.state, " ")
        progress = view.bar or view.detail
        lines.append(f"{stage:<12} {icon} {view.name:<26} {progress}")
    return "\n".join(lines)

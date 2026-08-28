"""Provenance: a stamped run groups a coherent set of validation results (PLAN.md §27d W2.1).

Additive-only, same discipline as everything else touching the store
(``.claude/CLAUDE.md``'s database-safety rule): creating a run only inserts into the new
``runs`` table, never rewrites ``validation``. A caller opts a batch of
``upsert_validation_results`` calls into a run by passing the resulting ``run_id`` through
-- rows nobody stamps stay ``run_id IS NULL``, i.e. "provenance unknown" (W2.3), not
silently attributed to a run that didn't produce them.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from protein_selector.core.db import DEFAULT_DB_PATH, connect

_REPORT_VERSIONS_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "report_versions.py"


@dataclass
class RunRecord:
    """One stamped run's provenance metadata (PLAN.md §27d W2.1)."""

    run_id: str
    created_at_utc: str
    tool_version: str
    git_sha: str | None
    resolved_parameters: dict[str, Any]
    environment_fingerprint: dict[str, Any]


def new_run_id() -> str:
    """A sortable, human-legible run id: a UTC timestamp to the second."""
    return datetime.now(UTC).strftime("run-%Y%m%dT%H%M%SZ")


def get_git_sha() -> str | None:
    """Best-effort HEAD SHA. ``None`` (not a fake value) if git/repo isn't available."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() or None


def get_tool_version() -> str:
    """This package's installed version, or ``"unknown"`` if it can't be determined."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("protein-selector")
    except PackageNotFoundError:
        return "unknown"


def collect_environment_fingerprint() -> dict[str, Any]:
    """Run ``scripts/report_versions.py --json`` and parse its output.

    ``--no-conda-probe``: a run's environment snapshot should be fast and never block on
    spawning a conda env's own interpreter -- that deeper probe is for a human debugging
    session, not automatic per-run stamping. Best-effort: returns ``{"error": ...}``
    rather than raising, so a run still gets stamped even if this one diagnostic piece
    can't run (e.g. a packaged install with no ``scripts/`` directory).
    """
    if not _REPORT_VERSIONS_SCRIPT.exists():
        return {"error": f"{_REPORT_VERSIONS_SCRIPT} not found"}
    try:
        result = subprocess.run(
            [sys.executable, str(_REPORT_VERSIONS_SCRIPT), "--json", "--no-conda-probe"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return json.loads(result.stdout)
    except Exception as exc:  # noqa: BLE001 -- deliberately never fatal, see docstring
        return {"error": str(exc)}


def create_run(
    resolved_parameters: dict[str, Any],
    db_path: Path = DEFAULT_DB_PATH,
    run_id: str | None = None,
) -> RunRecord:
    """Stamp a new run: snapshot tool version/git SHA/environment, persist, return it.

    Additive: ``INSERT ... ON CONFLICT DO UPDATE`` into ``runs`` only -- never touches
    ``validation``. Callers pass the returned ``run_id`` into
    ``core.validation_store.upsert_validation_results(..., run_id=...)`` for whatever they
    validate under this run.
    """
    record = RunRecord(
        run_id=run_id or new_run_id(),
        created_at_utc=datetime.now(UTC).isoformat(),
        tool_version=get_tool_version(),
        git_sha=get_git_sha(),
        resolved_parameters=resolved_parameters,
        environment_fingerprint=collect_environment_fingerprint(),
    )
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO runs
                (run_id, created_at_utc, tool_version, git_sha, resolved_parameters,
                 environment_fingerprint)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                created_at_utc=excluded.created_at_utc,
                tool_version=excluded.tool_version,
                git_sha=excluded.git_sha,
                resolved_parameters=excluded.resolved_parameters,
                environment_fingerprint=excluded.environment_fingerprint
            """,
            (
                record.run_id,
                record.created_at_utc,
                record.tool_version,
                record.git_sha,
                json.dumps(record.resolved_parameters),
                json.dumps(record.environment_fingerprint),
            ),
        )
    return record


def load_run(run_id: str, db_path: Path = DEFAULT_DB_PATH) -> RunRecord | None:
    """Load one stamped run's provenance metadata by id, or ``None`` if it doesn't exist."""
    if not db_path.exists():
        return None
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT run_id, created_at_utc, tool_version, git_sha, resolved_parameters,
                   environment_fingerprint
            FROM runs WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
    if row is None:
        return None
    return RunRecord(
        run_id=row[0],
        created_at_utc=row[1],
        tool_version=row[2],
        git_sha=row[3],
        resolved_parameters=json.loads(row[4]),
        environment_fingerprint=json.loads(row[5]),
    )


def load_runs(db_path: Path = DEFAULT_DB_PATH) -> list[RunRecord]:
    """Load every stamped run, most recent first."""
    if not db_path.exists():
        return []
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT run_id, created_at_utc, tool_version, git_sha, resolved_parameters,
                   environment_fingerprint
            FROM runs ORDER BY created_at_utc DESC
            """
        ).fetchall()
    return [
        RunRecord(
            run_id=row[0],
            created_at_utc=row[1],
            tool_version=row[2],
            git_sha=row[3],
            resolved_parameters=json.loads(row[4]),
            environment_fingerprint=json.loads(row[5]),
        )
        for row in rows
    ]

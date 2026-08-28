#!/usr/bin/env python3
"""Print a stamped run's provenance as a plain-text table (PLAN.md §27d W2.5).

Usage:
    uv run python scripts/provenance.py                # list every stamped run
    uv run python scripts/provenance.py RUN=run-20260823T120000Z
    uv run python scripts/provenance.py run-20260823T120000Z
    uv run python scripts/provenance.py --db-path cache/protein_selector.db RUN=...

No stamped runs exist yet in the shipped store (PLAN.md §27d W2.4, the full-validation-set
re-run under one run_id, is real compute not yet performed) -- this script becomes useful
once a caller passes `run_id=` into `core.validation_store.upsert_validation_results` via
`core.runs.create_run`. Reads only; never writes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from protein_selector.core.db import DEFAULT_DB_PATH
from protein_selector.core.runs import RunRecord, load_run, load_runs
from protein_selector.core.validation_store import load_validation_run_ids

# Every exercise label this store has ever written to `validation.exercise`
# (PLAN.md §4a) -- used only to summarize how many rows a run touched per
# exercise, not to gate anything.
_KNOWN_EXERCISES = ("modeling", "md_simulation", "docking", "complex_md_simulation")


def _print_run_table(record: RunRecord, db_path: Path) -> None:
    print(f"Run:                  {record.run_id}")
    print(f"Created (UTC):        {record.created_at_utc}")
    print(f"Tool version:         {record.tool_version}")
    print(f"Git SHA:              {record.git_sha or '(unknown)'}")
    print()
    print("Resolved parameters:")
    print(json.dumps(record.resolved_parameters, indent=2, sort_keys=True))
    print()
    print("Environment fingerprint:")
    print(json.dumps(record.environment_fingerprint, indent=2, sort_keys=True))
    print()
    print("Rows stamped with this run, by exercise:")
    for exercise in _KNOWN_EXERCISES:
        run_ids = load_validation_run_ids(exercise, db_path=db_path)
        n = sum(1 for v in run_ids.values() if v == record.run_id)
        print(f"  {exercise:<24} {n}")


def _print_run_list(db_path: Path) -> None:
    runs = load_runs(db_path=db_path)
    if not runs:
        print(
            "No stamped runs found in this store. See this script's module docstring -- "
            "W2.4 (a full re-run under one run_id) hasn't happened yet."
        )
        return
    print(f"{'run_id':<28} {'created_at_utc':<28} tool_version")
    for record in runs:
        print(f"{record.run_id:<28} {record.created_at_utc:<28} {record.tool_version}")


def main() -> None:
    """CLI entry point: print one run's provenance, or list every stamped run."""
    parser = argparse.ArgumentParser(description="Print a stamped run's provenance (PLAN.md §27d W2.5).")
    parser.add_argument(
        "run_id",
        nargs="?",
        default=None,
        help="a run id, or RUN=<id> (the Makefile `provenance` target's own convention)",
    )
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    args = parser.parse_args()

    run_id = args.run_id
    if run_id is not None and run_id.startswith("RUN="):
        run_id = run_id[len("RUN=") :]

    if run_id is None:
        _print_run_list(args.db_path)
        return

    record = load_run(run_id, db_path=args.db_path)
    if record is None:
        raise SystemExit(f"no such run: {run_id!r}")
    _print_run_table(record, args.db_path)


if __name__ == "__main__":
    main()

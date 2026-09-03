#!/usr/bin/env python3
"""Benchmark the pipeline's throughput, cheap lane and validation lanes alike.

Answers a real, recurring question about this tool: is the batched-API approach fast
enough, or does it need a local database mirror (PLAN.md §4b) -- and, since PLAN.md §27,
what is candidates/hour per lane, tracked over time so a regression is visible instead of
rediscovered by hand.

Measured 2026-07-04 (see PLAN.md §4b and .claude/CLAUDE.md): the full hard-filters +
simulability pipeline processes ~500 real candidates in under 3 seconds, dominated by
fixed round-trip latency rather than data volume, because the RCSB Data API batches up to
1000 IDs per request (``rcsbapi.const.const.DATA_API_MAX_BATCH_ID_SIZE``) and the
hard-filters search itself runs server-side. Conclusion: a local database mirror is NOT
needed at this tool's scale.

**Two independent lanes, two independent data sources (PLAN.md §27d task S1.1):**

- The **cheap lane** (hard filters + simulability) needs live network access to
  data.rcsb.org/search.rcsb.org -- it is genuinely re-measured every run.
- The **validation lanes** (modeling/md_simulation/docking/complex_md_simulation) are
  measured from this repo's own accumulated ``validation.effort_seconds`` -- re-running the
  real OpenMM/Vina/PLIP/AmberTools validators just to benchmark them would be dishonest
  effort spent for no new information; the store already has 5,505 real timings. This
  reproduces PLAN.md §27a's numbers exactly, by construction, and is why S1.1's own
  "Done when" check is "reproduces the §27a baselines within 20%" -- it is the same query.

Every run appends one row per lane to ``results/benchmark_history.csv`` so throughput is
visible over time, not just at the moment someone happens to look. That file used to be a
tracked ``.gitignore`` exception; it is per-run output now, like everything else in
``results/``, so keep your own copy if you care about the history.

This is NOT a pytest test (deliberately not under tests/): it's a manual diagnostic to
re-run whenever you want to re-check real-world performance, e.g. after an RCSB API change,
before deciding whether to revisit the local-DB question, or after any PLAN.md §27d Phase 1
task that claims to move a throughput number.

Usage:
    uv run python scripts/benchmark_pipeline.py                    # both lanes
    uv run python scripts/benchmark_pipeline.py --sizes 100 500 2000
    uv run python scripts/benchmark_pipeline.py --offline           # validation lanes only,
                                                                     # no network required
    uv run python scripts/benchmark_pipeline.py --db-path cache/protein_selector.db
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import time
from collections.abc import Callable, Sized
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from protein_selector.core.db import DEFAULT_DB_PATH, connect
from protein_selector.domain.structural_biology.rcsb_composition import (
    fetch_non_standard_residues,
    fetch_oligomeric_state,
)
from protein_selector.domain.structural_biology.rcsb_search import (
    fetch_entry_metadata,
    search_candidate_ids,
)

_HISTORY_PATH = Path(__file__).resolve().parent.parent / "docs" / "benchmark_history.csv"
_HISTORY_FIELDS = [
    "timestamp_utc",
    "git_sha",
    "lane",
    "stage",
    "n_candidates",
    "seconds",
    "candidates_per_hour",
]


@dataclass
class StageTiming:
    """Elapsed time for one pipeline stage, at one candidate-set size."""

    stage: str
    n_requested: int
    n_returned: int
    seconds: float

    @property
    def candidates_per_hour(self) -> float:
        """Throughput implied by this one timing, extrapolated to a full hour."""
        if self.seconds <= 0:
            return float("inf")
        return self.n_returned / self.seconds * 3600


def time_stage[T: Sized](stage: str, n_requested: int, fn: Callable[[], T]) -> tuple[StageTiming, T]:
    """Run ``fn``, returning a ``StageTiming`` alongside ``fn``'s own (typed) result."""
    start = time.time()
    result = fn()
    elapsed = time.time() - start
    return StageTiming(stage, n_requested, len(result), elapsed), result


def benchmark_cheap_lane(n: int) -> list[StageTiming]:
    """Live-benchmark the hard-filters + simulability lane for ``n`` requested candidates.

    Requires network access to data.rcsb.org/search.rcsb.org.
    """
    timings: list[StageTiming] = []

    search_timing, ids = time_stage(
        "hard_filters search_candidate_ids",
        n,
        lambda: search_candidate_ids(max_atoms=50_000, max_resolution=3.0, rows=n),
    )
    timings.append(search_timing)

    fetch_timing, entries_list = time_stage(
        "hard_filters fetch_entry_metadata", n, lambda: fetch_entry_metadata(ids)
    )
    timings.append(fetch_timing)

    assembly_timing, _ = time_stage(
        "simulability fetch_oligomeric_state", n, lambda: fetch_oligomeric_state(entries_list)
    )
    timings.append(assembly_timing)

    entity_timing, _ = time_stage(
        "simulability fetch_non_standard_residues", n, lambda: fetch_non_standard_residues(entries_list)
    )
    timings.append(entity_timing)

    return timings


def benchmark_validation_lanes(db_path: Path) -> list[StageTiming]:
    """Throughput per validation exercise, from this repo's own accumulated ``validation`` table.

    Not a live measurement -- re-running the real OpenMM/Vina/PLIP/AmberTools validators
    just to benchmark them would burn real compute for numbers the store already has
    (PLAN.md §27a). This is the exact query behind §27a's per-lane CPU-hour figures; running
    it here keeps that table honest over time instead of frozen at one audit date.
    """
    timings: list[StageTiming] = []
    with connect(db_path) as conn:
        rows = conn.execute(
            "select exercise, count(*) n, sum(effort_seconds) total_seconds "
            "from validation where effort_seconds is not null group by exercise "
            "order by exercise"
        ).fetchall()
    for exercise, n, total_seconds in rows:
        if n == 0 or total_seconds is None:
            continue
        # seconds is TOTAL elapsed across n candidates, matching StageTiming's
        # candidates_per_hour = n_returned/seconds*3600 -- passing a per-candidate
        # average here instead would inflate throughput by a factor of n.
        timings.append(StageTiming(f"validation:{exercise}", n, n, total_seconds))
    return timings


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def append_history(lane: str, timings: list[StageTiming], history_path: Path = _HISTORY_PATH) -> None:
    """Append one row per stage timing to the tracked benchmark-history CSV.

    Additive only -- never overwrites or truncates a prior run's rows, same append-only
    discipline as the main result store (§4b), just for a different tracked file.
    """
    is_new = not history_path.exists()
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=_HISTORY_FIELDS)
        if is_new:
            writer.writeheader()
        timestamp = datetime.now(UTC).isoformat()
        sha = _git_sha()
        for t in timings:
            writer.writerow(
                {
                    "timestamp_utc": timestamp,
                    "git_sha": sha,
                    "lane": lane,
                    "stage": t.stage,
                    "n_candidates": t.n_returned,
                    "seconds": round(t.seconds, 4),
                    "candidates_per_hour": round(t.candidates_per_hour, 1),
                }
            )


def print_report(label: str, timings: list[StageTiming]) -> None:
    """Print a stage-by-stage timing/throughput table for one lane's run."""
    if not timings:
        print(f"{label}: no data")
        return
    header = f"{'stage':<38}{'n':>8}{'seconds':>12}{'candidates/hour':>18}"
    print(f"\n{label}")
    print(header)
    print("-" * len(header))
    for t in timings:
        cph = "inf" if t.candidates_per_hour == float("inf") else f"{t.candidates_per_hour:,.0f}"
        print(f"{t.stage:<38}{t.n_returned:>8}{t.seconds:>12.3f}{cph:>18}")


def main() -> None:
    """Parse CLI args, run the requested lane(s), print + append one history row each."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--sizes", type=int, nargs="+", default=[200, 500],
        help="Cheap-lane candidate-set sizes to benchmark (default: 200 500). Ignored with --offline.",
    )
    parser.add_argument(
        "--offline", action="store_true",
        help="Skip the cheap lane (no network required); benchmark validation lanes only.",
    )
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH, help="Result store to read validation timings from.")
    parser.add_argument(
        "--history-path", type=Path, default=_HISTORY_PATH,
        help=f"Tracked CSV to append results to (default: {_HISTORY_PATH.relative_to(Path.cwd()) if _HISTORY_PATH.is_relative_to(Path.cwd()) else _HISTORY_PATH}).",
    )
    args = parser.parse_args()

    validation_timings = benchmark_validation_lanes(args.db_path)
    print_report("validation lanes (from accumulated store, not live-run)", validation_timings)
    append_history("validation", validation_timings, args.history_path)

    if not args.offline:
        print(f"\ncheap lane: benchmarking hard-filters + simulability for sizes {args.sizes}")
        print("(requires live network access to data.rcsb.org / search.rcsb.org)")
        for n in args.sizes:
            timings = benchmark_cheap_lane(n)
            print_report(f"cheap lane, N={n}", timings)
            append_history("cheap", timings, args.history_path)

    print(f"\nappended to {args.history_path}")


if __name__ == "__main__":
    main()

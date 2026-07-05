#!/usr/bin/env python3
"""Benchmark the L1+L2 pipeline against the live RCSB API.

Answers a real, recurring question about this tool: is the batched-API
approach fast enough, or does it need a local database mirror (PLAN.md §4b)?

Measured 2026-07-04 (see PLAN.md §4b and .claude/CLAUDE.md): the full L1+L2
pipeline processes ~500 real candidates in under 3 seconds, dominated by
fixed round-trip latency rather than data volume, because the RCSB Data API
batches up to 1000 IDs per request (``rcsbapi.const.const.DATA_API_MAX_BATCH_ID_SIZE``)
and the L1 search itself runs server-side (never scans the whole archive
locally). Conclusion: a local database mirror is NOT needed at this tool's
target scale (~hundreds of candidates, annual cadence -- PLAN.md §13).

Requires live network access to data.rcsb.org/search.rcsb.org -- this is NOT
a pytest test (deliberately not under tests/): it's a manual diagnostic to
re-run whenever you want to re-check real-world performance, e.g. after an
RCSB API change or before deciding whether to revisit the local-DB question.

Usage:
    uv run python scripts/benchmark_pipeline.py
    uv run python scripts/benchmark_pipeline.py --sizes 100 500 2000
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable, Sized
from dataclasses import dataclass
from typing import TypeVar

from protein_selector.candidates import fetch_entry_metadata, search_candidate_ids
from protein_selector.composition import (
    fetch_non_standard_residues,
    fetch_oligomeric_state,
)

_T = TypeVar("_T", bound=Sized)


@dataclass
class StageTiming:
    """Elapsed time for one pipeline stage, at one candidate-set size."""

    stage: str
    n_requested: int
    n_returned: int
    seconds: float


def time_stage(stage: str, n_requested: int, fn: Callable[[], _T]) -> tuple[StageTiming, _T]:
    """Run ``fn``, returning a ``StageTiming`` alongside ``fn``'s own (typed) result."""
    start = time.time()
    result = fn()
    elapsed = time.time() - start
    return StageTiming(stage, n_requested, len(result), elapsed), result


def benchmark_one_size(n: int) -> list[StageTiming]:
    """Run the full L1+L2 pipeline once for ``n`` requested candidates."""
    timings: list[StageTiming] = []

    search_timing, ids = time_stage(
        "L1 search_candidate_ids",
        n,
        lambda: search_candidate_ids(max_atoms=50_000, max_resolution=3.0, rows=n),
    )
    timings.append(search_timing)

    fetch_timing, entries_list = time_stage(
        "L1 fetch_entry_metadata", n, lambda: fetch_entry_metadata(ids)
    )
    timings.append(fetch_timing)

    assembly_timing, _ = time_stage(
        "L2 fetch_oligomeric_state", n, lambda: fetch_oligomeric_state(entries_list)
    )
    timings.append(assembly_timing)

    entity_timing, _ = time_stage(
        "L2 fetch_non_standard_residues", n, lambda: fetch_non_standard_residues(entries_list)
    )
    timings.append(entity_timing)

    return timings


def print_report(sizes: list[int], results: dict[int, list[StageTiming]]) -> None:
    """Print a stage-by-stage timing table, one column per candidate-set size."""
    stage_names = [t.stage for t in results[sizes[0]]]

    header = f"{'stage':<32}" + "".join(f"N={n:<10}" for n in sizes)
    print(header)
    print("-" * len(header))
    for stage in stage_names:
        row = f"{stage:<32}"
        for n in sizes:
            timing = next(t for t in results[n] if t.stage == stage)
            row += f"{timing.seconds:<10.2f}"[:10].ljust(11)
        print(row)

    print("-" * len(header))
    totals_row = f"{'TOTAL':<32}"
    for n in sizes:
        total = sum(t.seconds for t in results[n])
        totals_row += f"{total:<10.2f}"[:10].ljust(11)
    print(totals_row)


def main() -> None:
    """Parse CLI args, run the benchmark for each requested size, print the report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes",
        type=int,
        nargs="+",
        default=[200, 500],
        help="Candidate-set sizes to benchmark (default: 200 500)",
    )
    args = parser.parse_args()

    print(f"Benchmarking L1+L2 pipeline for sizes: {args.sizes}")
    print("(requires live network access to data.rcsb.org / search.rcsb.org)\n")

    results = {n: benchmark_one_size(n) for n in args.sizes}
    print()
    print_report(args.sizes, results)


if __name__ == "__main__":
    main()

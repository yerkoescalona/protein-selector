#!/usr/bin/env python3
"""A real, from-zero demo run: pick a few PDB entries at random and actually validate them.

There is no committed database. This script starts with an empty file, asks RCSB which
entries pass the hard filters, samples a handful at random, and runs the real pipeline
against them, going as deep as the installed toolchain allows:

    hard filters -> simulability -> ligands -> literature -> AlphaFold DB
                 -> [MD] -> [pocket] -> [docking] -> [complex MD]

The bracketed stages need packages that are conda-only (openmm, vina, plip, ambertools).
When they are missing the stage is skipped and *said to be skipped*, rather than being
reported as a scientific failure -- the distinction that matters here is "this candidate is
hard" versus "you have not installed the heavy half of the toolchain".

Because candidates are sampled at random from the whole PDB, a run is not reproducible and
not meant to be: whether any given run reaches a working protein+ligand complex MD is
genuinely down to what it drew. That is the honest demonstration. Pass ``--seed`` to repeat
a specific draw.

Usage:
    uv run python scripts/demo_run.py                    # cheap lanes, no conda needed
    uv run --extra validate python scripts/demo_run.py --candidates 8
    uv run --extra validate python scripts/demo_run.py --seed 7 --heavy
"""

from __future__ import annotations

import argparse
import logging
import random
import sqlite3
import sys
import threading
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

_DEFAULT_DB = Path("demo/demo_run.db")
_DEFAULT_N = 5
_DEFAULT_SCREEN = 60
# A wide, cheap window: the point is to draw something interesting, not to reproduce the
# course's own candidate criteria (workflow/config.yaml owns those for real runs).
_MIN_RESIDUES = 50
_MAX_RESIDUES = 250
_MAX_RESOLUTION = 2.5
_SEARCH_ROWS = 2000


def _heavy_tools_available() -> dict[str, bool]:
    """Which optional stages this machine can actually run, checked rather than assumed."""
    import importlib.util
    import shutil

    def mod(name: str) -> bool:
        try:
            return importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            return False

    return {
        "md": mod("openmm") and mod("pdbfixer"),
        "pocket": shutil.which("fpocket") is not None,
        "dock": mod("vina") and mod("meeko") and shutil.which("obabel") is not None,
        "complex_md": mod("openff.toolkit") and shutil.which("antechamber") is not None,
    }


class _LiveProgress(logging.Handler):
    """Turn the pipeline's own log stream into one live, self-updating status line.

    The store-backed view (`make demo-watch`) can only show a stage once it has FINISHED
    and persisted a row, so during a single candidate's 30-60s of MD and docking it looks
    frozen. Nothing is wrong there; it simply has nothing new to read. This handler gets
    the missing signal from the place that actually has it: the pipeline's own log records,
    as they happen.

    Falls back to plain scrolling lines when stderr is not a terminal, so piping into a
    file or a CI log stays readable instead of filling with carriage returns.
    """

    _FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, total: int) -> None:
        super().__init__(level=logging.INFO)
        self.total = total
        self.index = 0
        self.pdb_id = ""
        self.message = "starting"
        self._frame = 0
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.tty = sys.stderr.isatty()
        self._thread: threading.Thread | None = None

    # logging.Handler -----------------------------------------------------------------
    def emit(self, record: logging.LogRecord) -> None:
        text = record.getMessage().strip()
        if not text:
            return
        with self._lock:
            self.message = text[:64]
        if not self.tty:
            print(f"      {text}", file=sys.stderr, flush=True)

    # rendering -----------------------------------------------------------------------
    def _render(self) -> str:
        width = 22
        done = int(width * (self.index - 1) / self.total) if self.total else 0
        bar = "█" * done + "░" * (width - done)
        spin = self._FRAMES[self._frame % len(self._FRAMES)]
        return f"  {bar} {self.index}/{self.total}  {self.pdb_id:<6} {spin} {self.message}"

    def _animate(self) -> None:
        while not self._stop.wait(0.12):
            with self._lock:
                self._frame += 1
                line = self._render()
            print(f"\r\033[2K{line}", end="", file=sys.stderr, flush=True)

    # lifecycle -----------------------------------------------------------------------
    def start(self) -> None:
        if self.tty:
            self._thread = threading.Thread(target=self._animate, daemon=True)
            self._thread.start()

    def candidate(self, index: int, pdb_id: str) -> None:
        with self._lock:
            self.index, self.pdb_id, self.message = index, pdb_id, "fetching metadata"
        if not self.tty:
            print(f"  [{index}/{self.total}] {pdb_id}", file=sys.stderr, flush=True)

    def done_line(self, text: str) -> None:
        """Print a line that stays, without the spinner overwriting it."""
        if self.tty:
            print("\r\033[2K", end="", file=sys.stderr)
        print(text, file=sys.stderr, flush=True)

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        if self.tty:
            print("\r\033[2K", end="", file=sys.stderr, flush=True)
        super().close()


def _summarise(db_path: Path, pdb_ids: list[str]) -> list[dict[str, object]]:
    """Read back what the run persisted, for the candidates it actually validated.

    Scoped to ``pdb_ids`` on purpose: ``check_simulability`` persists every entry that
    survives screening, which is more than the run goes on to validate, and listing those
    extra rows as all-dashes reads like a wall of failures rather than "not attempted".
    """
    placeholders = ",".join("?" * len(pdb_ids))
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""
            SELECT c.pdb_id, c.n_residues, c.organism,
                   MAX(CASE WHEN v.exercise='modeling' THEN v.status END)              AS modeling,
                   MAX(CASE WHEN v.exercise='md_simulation' THEN v.status END)         AS md,
                   MAX(CASE WHEN v.exercise='docking' THEN v.status END)               AS docking,
                   MAX(CASE WHEN v.exercise='complex_md_simulation' THEN v.status END) AS complex_md
            FROM candidates c LEFT JOIN validation v ON v.pdb_id = c.pdb_id
            WHERE c.pdb_id IN ({placeholders})
            GROUP BY c.pdb_id ORDER BY c.n_residues
            """,
            pdb_ids,
        ).fetchall()
    return [dict(row) for row in rows]


def main() -> None:
    """Draw a few random PDB entries and run the real pipeline against them."""
    parser = argparse.ArgumentParser(
        prog="demo_run.py",
        description=(
            "Run the real pipeline from zero against a random draw of PDB entries.\n"
            "No committed database, no pre-computed results: the draw is live and the\n"
            "run goes as deep as the installed toolchain allows."
        ),
        epilog=(
            "examples:\n"
            "  uv run python scripts/demo_run.py                      cheap lanes, no conda\n"
            "  uv run python scripts/demo_run.py --candidates 8       validate more of them\n"
            "  uv run python scripts/demo_run.py --seed 7             repeat a draw\n"
            "  uv run --extra validate python scripts/demo_run.py     + docking, if installed\n"
            "\n"
            "via make (note the quotes -- `make demo --seed 7` is a make error):\n"
            "  make demo\n"
            '  make demo DEMO_ARGS="--seed 7 --candidates 8"\n'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--db-path", type=Path, default=_DEFAULT_DB)
    parser.add_argument("--candidates", type=int, default=_DEFAULT_N,
                        help=f"how many survivors to fully validate (default {_DEFAULT_N})")
    parser.add_argument("--screen", type=int, default=_DEFAULT_SCREEN,
                        help=f"how many random entries to screen first (default {_DEFAULT_SCREEN})")
    parser.add_argument("--seed", type=int, default=None,
                        help="repeat a specific random draw")
    parser.add_argument("--heavy", action="store_true",
                        help="attempt MD/docking/complex-MD even if the probe says a tool is missing")
    parser.add_argument("--verbose", action="store_true",
                        help="show the pipeline's full log instead of the live progress line")
    parser.add_argument("--keep", action="store_true",
                        help="keep an existing db and add to it instead of starting from zero")
    args = parser.parse_args()

    from protein_selector.core.config import CandidateFilterConfig
    from protein_selector.domain.structural_biology.rcsb_search import (
        fetch_entry_metadata,
        search_candidate_ids,
    )
    from protein_selector.nodes.check_simulability_node import check_simulability
    from protein_selector.pipelines.single_pdb_pipeline import validate_single_pdb

    if args.db_path.exists() and not args.keep:
        args.db_path.unlink()  # a demo starts from zero; --keep opts out
    args.db_path.parent.mkdir(parents=True, exist_ok=True)

    tools = _heavy_tools_available()
    for name, ok in tools.items():
        logger.info("   %-11s %s", name, "available" if ok else "not installed, will skip")
    if args.heavy:
        tools = dict.fromkeys(tools, True)

    logger.info("\n🔎 asking RCSB which entries pass the hard filters ...")
    pool = search_candidate_ids(
        max_resolution=_MAX_RESOLUTION, rows=_SEARCH_ROWS
    )
    if not pool:
        logger.error("❌ RCSB returned nothing. Network down, or the API changed.")
        raise SystemExit(1)
    logger.info("   %d entries pass the hard filters (resolution, size, method)", len(pool))

    # The hard-filters search cannot express a residue-count window, so a naive random draw
    # of N mostly returns entries the simulability gate then rejects -- an accurate but very
    # dull demo (the first version of this script drew 5 and kept 0). Sample a batch, screen
    # it cheaply, and validate the survivors: that IS the funnel this tool is about.
    rng = random.Random(args.seed)
    batch = rng.sample(pool, min(args.screen, len(pool)))
    logger.info("🎲 screening a random batch of %d ...", len(batch))
    entries = fetch_entry_metadata(batch)
    candidate_filter = CandidateFilterConfig(
        min_residues=_MIN_RESIDUES, max_residues=_MAX_RESIDUES, max_resolution=_MAX_RESOLUTION
    )
    survivors = check_simulability(entries, candidate_filter, args.db_path)
    logger.info("🧬 %d of %d survived the simulability gate", len(survivors), len(batch))
    if not survivors:
        logger.error("Nothing survived this draw. Re-run, or raise --screen.")
        raise SystemExit(0)

    drawn = [e.pdb_id for e in survivors][: args.candidates]
    logger.info("▶️  validating %d of them: %s\n", len(drawn), ", ".join(drawn))

    config = {"min_residues": _MIN_RESIDUES, "max_residues": _MAX_RESIDUES,
              "max_resolution": _MAX_RESOLUTION}
    started = time.monotonic()
    root = logging.getLogger()
    progress = _LiveProgress(len(drawn))
    saved_handlers = root.handlers[:]
    if not args.verbose:
        # Take over the pipeline's log stream: its per-stage records become the live line
        # instead of scrolling past. --verbose puts the normal handlers back.
        root.handlers = [progress]
    progress.start()

    try:
        for i, pdb_id in enumerate(drawn, 1):
            progress.candidate(i, pdb_id)
            candidate_started = time.monotonic()
            try:
                validate_single_pdb(
                    pdb_id, args.db_path, config,
                    run_md=tools["md"], run_pocket=tools["pocket"],
                    run_dock=tools["dock"], run_complex_md=tools["complex_md"],
                    force_refresh=False,
                )
                mark = "✔"
            except Exception as exc:  # a demo must survive one bad draw and keep going
                mark = "✗"
                progress.message = f"{type(exc).__name__}: {exc}"[:64]
            progress.done_line(
                f"  {mark} [{i}/{len(drawn)}] {pdb_id}  "
                f"{time.monotonic() - candidate_started:.0f}s"
            )
    finally:
        progress.close()
        root.handlers = saved_handlers

    rows = _summarise(args.db_path, drawn)
    logger.info("\n%s", "=" * 78)
    logger.info("RESULT  (%.0fs, db: %s)", time.monotonic() - started, args.db_path)
    logger.info("%s", "=" * 78)
    if not rows:
        logger.info("No candidate survived the simulability gate. That is a real outcome, "
                    "not an error: try again, or --candidates 10 for a wider draw.")
        return
    logger.info("%-6s %5s  %-24s %-9s %-9s %-9s %s",
                "PDB", "res", "organism", "modeling", "MD", "docking", "complex MD")
    for r in rows:
        logger.info("%-6s %5s  %-24s %-9s %-9s %-9s %s",
                    r["pdb_id"], r["n_residues"] or "?", str(r["organism"] or "?")[:24],
                    r["modeling"] or "-", r["md"] or "-", r["docking"] or "-",
                    r["complex_md"] or "-")
    full = [r for r in rows if r["complex_md"] == "success"]
    logger.info("")
    if full:
        logger.info("🎉 %d of %d reached a working protein+ligand complex MD: %s",
                    len(full), len(rows), ", ".join(str(r["pdb_id"]) for r in full))
    elif not tools["complex_md"]:
        logger.info("Complex MD was skipped (ambertools/openff not installed) -- see "
                    "INSTALL.md, or `make env-validation`.")
    else:
        logger.info("No candidate reached complex MD this time. That is the normal outcome "
                    "for a small random draw: most PDB entries have no dockable ligand.")
    logger.info("A dash means the stage was never reached, not that it failed. Re-run for "
                "a different draw; nothing here is cached between runs.")

    # The table above is raw status. The tool's actual product is the ranked report: the
    # per-exercise difficulty tiers and the `suitable_for` verdict, which is what an
    # instructor reads. Writing it here means the demo ends on the real deliverable.
    from protein_selector.core.report import build_report_table, write_report_csv

    report_path = args.db_path.with_name(args.db_path.stem + "_report.csv")
    table = build_report_table(args.db_path)
    write_report_csv(table, report_path)
    logger.info("\n📊 ranked report (difficulty tiers, suitable_for, notes): %s", report_path)
    logger.info("   live progress for a run, from another terminal: make demo-watch")


if __name__ == "__main__":
    main()

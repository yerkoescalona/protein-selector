#!/usr/bin/env python3
"""CLI wrapper for `stages.validate_one.run_validate_one_stage`. See PLAN.md §22.

Usage:
    uv run --extra validate python scripts/validate_one.py 1UBQ
    uv run --extra validate python scripts/validate_one.py 1UBQ --no-dock --force-refresh
    uv run --extra validate python scripts/validate_one.py 1FSZ --complex-md

MD/pocket/docking/complex-md need the conda env from `workflow/config.yaml`'s
`validation_conda_prefix` active on PATH (complex-md additionally needs `ambertools` in
it); missing env is reported per-stage, not fatal. If running under `conda activate`
directly (not Snakemake's `--sdm conda`), the PATH-ordering gotcha that broke
`complex_md_validate` under Snakemake (Makefile's `workflow-complex-md` target's comment)
doesn't apply here -- this script runs as one plain Python process, no env re-activation.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

from protein_selector.stages.validate_one import run_validate_one_stage

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path("workflow/config.yaml")


def _load_workflow_config(config_path: Path) -> dict:
    """Read `workflow/config.yaml` for defaults; missing file -> empty dict (dataclass defaults apply)."""
    if not config_path.exists():
        logger.warning(
            "⚠️ %s not found -- using this script's own built-in defaults, not "
            "workflow/config.yaml's (they may have diverged from the batch run's)",
            config_path,
        )
        return {}
    return yaml.safe_load(config_path.read_text()) or {}


def main() -> None:
    """CLI entry point: parse args, load config, run `run_validate_one_stage` for the given PDB id."""
    parser = argparse.ArgumentParser(
        description="Validate ONE PDB entry end-to-end, no Snakemake, no checkpoints (PLAN.md §22)."
    )
    parser.add_argument("pdb_id", help="4-character PDB accession, e.g. 1UBQ")
    parser.add_argument(
        "--db-path", type=Path, default=None, help="defaults to workflow/config.yaml's db_path"
    )
    parser.add_argument(
        "--config", type=Path, default=_DEFAULT_CONFIG_PATH, help="workflow config.yaml path"
    )
    parser.add_argument("--no-md", action="store_false", dest="run_md")
    parser.add_argument("--no-pocket", action="store_false", dest="run_pocket")
    parser.add_argument("--no-dock", action="store_false", dest="run_dock")
    parser.add_argument(
        "--complex-md",
        action="store_true",
        dest="run_complex_md",
        help="also run GAFF2/AMBER receptor+ligand complex MD (PLAN.md §23a, needs "
        "ambertools in the conda env; off by default, unlike --no-md/--no-dock)",
    )
    parser.add_argument(
        "--force-refresh", action="store_true", help="recompute even if already persisted (upsert, not delete)"
    )
    parser.add_argument(
        "--min-residues", type=int, default=None,
        help="override workflow/config.yaml's simulability min_residues for this one run "
        "(e.g. to validate a candidate outside the course's normal size window)",
    )
    parser.add_argument(
        "--max-residues", type=int, default=None,
        help="override workflow/config.yaml's simulability max_residues for this one run",
    )
    parser.add_argument(
        "--max-resolution", type=float, default=None,
        help="override workflow/config.yaml's simulability max_resolution for this one run",
    )
    parser.add_argument(
        "--max-unmodeled-fraction", type=float, default=None,
        help="override the simulability completeness gate (default 0.1 = 10%% unmodeled "
        "residues) for this one run -- e.g. a candidate just over the default cutoff",
    )
    args = parser.parse_args()

    config = _load_workflow_config(args.config)
    db_path = args.db_path or Path(config.get("db_path", "cache/protein_selector.db"))

    for key, value in (
        ("min_residues", args.min_residues),
        ("max_residues", args.max_residues),
        ("max_resolution", args.max_resolution),
        ("max_unmodeled_fraction", args.max_unmodeled_fraction),
    ):
        if value is not None:
            logger.info(
                "⚙️ overriding %s: %s -> %s (this run only, not written back to %s)",
                key, config.get(key), value, args.config,
            )
            config[key] = value

    run_validate_one_stage(
        args.pdb_id,
        db_path,
        config,
        run_md=args.run_md,
        run_pocket=args.run_pocket,
        run_dock=args.run_dock,
        run_complex_md=args.run_complex_md,
        force_refresh=args.force_refresh,
    )


if __name__ == "__main__":
    sys.exit(main())

"""Validate ONE PDB entry end-to-end, no Snakemake, no checkpoints (PLAN.md §22).

Calls the same `run_<stage>_stage(...)` functions Snakemake's rules call, directly, for
one `pdb_id` -- same DB, no checkpoints/markers/shortlist files. Does NOT write
`results/report.csv` itself (that stays the batch `report` rule's job -- would destroy
other rows, PLAN.md §4b). `scripts/validate_one.py` is the thin CLI wrapper around this
(argparse + config loading only), same split as every other `stages/` module vs. its
`workflow/scripts/*.py` Snakemake caller.
"""

from __future__ import annotations

import logging
from pathlib import Path

from protein_selector.core.report import build_report_table
from protein_selector.domain.docking.store import load_ligand_ccd_codes
from protein_selector.domain.structural_biology.candidates import fetch_entry_metadata
from protein_selector.stages.complex_md_simulation import (
    run_complex_md_simulation_stage,
)
from protein_selector.stages.config import (
    CandidateFilterConfig,
    ComplexMdSimulationConfig,
    DockingConfig,
    MdSimulationConfig,
    ModelingLookupConfig,
    PocketDetectionConfig,
)
from protein_selector.stages.docking import run_docking_stage
from protein_selector.stages.ligands import run_ligands_stage
from protein_selector.stages.literature import run_literature_stage
from protein_selector.stages.md_simulation import run_md_simulation_stage
from protein_selector.stages.meeko import run_meeko_stage
from protein_selector.stages.modeling import run_modeling_stage
from protein_selector.stages.parameterizability import run_parameterizability_stage
from protein_selector.stages.pocket_detection import run_pocket_detection_stage
from protein_selector.stages.simulability import run_simulability_stage

logger = logging.getLogger(__name__)


def run_validate_one_stage(
    pdb_id: str,
    db_path: Path,
    config: dict,
    *,
    run_md: bool,
    run_pocket: bool,
    run_dock: bool,
    run_complex_md: bool,
    force_refresh: bool,
) -> None:
    """Run every stage for one PDB id: metadata -> simulability -> ligands/literature/modeling -> parameterizability/meeko -> md -> pocket -> dock -> complex_md. No checkpoints."""
    pdb_id = pdb_id.upper()
    logger.info("🔎 fetching metadata for %s", pdb_id)
    entries = fetch_entry_metadata([pdb_id])
    if not entries:
        logger.error("❌ %s: no RCSB entry metadata found (typo, or not X-ray?)", pdb_id)
        return

    candidate_filter = CandidateFilterConfig(
        min_residues=config.get("min_residues", CandidateFilterConfig.min_residues),
        max_residues=config.get("max_residues", CandidateFilterConfig.max_residues),
        max_resolution=config.get("max_resolution", CandidateFilterConfig.max_resolution),
        max_unmodeled_fraction=config.get(
            "max_unmodeled_fraction", CandidateFilterConfig.max_unmodeled_fraction
        ),
    )
    survivors = run_simulability_stage(entries, candidate_filter, db_path)
    if not survivors:
        logger.error(
            "❌ %s: failed simulability -- see the `simulability` table's `reasons` column", pdb_id
        )
        return
    logger.info("✅ %s: passed simulability", pdb_id)

    smiles_by_ccd = run_ligands_stage(survivors, db_path)
    run_literature_stage([pdb_id], db_path, force_refresh=force_refresh)
    run_modeling_stage(
        survivors, ModelingLookupConfig(enabled=True), db_path, force_refresh=force_refresh
    )

    ccd_codes = load_ligand_ccd_codes(db_path).get(pdb_id, [])
    if ccd_codes:
        run_parameterizability_stage(smiles_by_ccd, db_path, force_refresh=force_refresh)
        run_meeko_stage(ccd_codes, smiles_by_ccd, db_path, force_refresh=force_refresh)
    else:
        logger.info("ℹ️ %s: no bound ligand -- skipping parameterizability/meeko/docking", pdb_id)
        run_dock = False

    if run_md:
        md_result = run_md_simulation_stage(
            pdb_id,
            MdSimulationConfig(
                enabled=True,
                n_steps=config.get("md_n_steps", MdSimulationConfig.n_steps),
                max_minimization_iterations=config.get(
                    "md_max_minimization_iterations",
                    MdSimulationConfig.max_minimization_iterations,
                ),
            ),
            db_path,
            force_refresh=force_refresh,
        )
        if md_result is None:
            logger.warning(
                "⚠️ %s: MD stage skipped (validation conda env not active/installed)", pdb_id
            )
        else:
            logger.info("🧪 %s: MD simulation -> %s", pdb_id, md_result.status.value)
    else:
        logger.info("⏭️ %s: MD skipped (--no-md)", pdb_id)

    if run_pocket:
        pocket_result = run_pocket_detection_stage(
            pdb_id,
            PocketDetectionConfig(
                enabled=True,
                box_padding_angstroms=config.get(
                    "dock_box_padding", PocketDetectionConfig.box_padding_angstroms
                ),
            ),
            db_path,
            force_refresh=force_refresh,
        )
        if pocket_result is not None:
            logger.info(
                "🕳️ %s: pocket detection -> %d pocket(s) found (informational, PLAN.md §20)",
                pdb_id,
                len(pocket_result.pockets),
            )
    else:
        logger.info("⏭️ %s: pocket detection skipped (--no-pocket)", pdb_id)

    if run_dock:
        dock_result = run_docking_stage(
            pdb_id,
            DockingConfig(
                enabled=True,
                exhaustiveness=config.get("dock_exhaustiveness", DockingConfig.exhaustiveness),
                rmsd_threshold_angstrom=config.get(
                    "dock_rmsd_threshold", DockingConfig.rmsd_threshold_angstrom
                ),
            ),
            db_path,
            force_refresh=force_refresh,
        )
        if dock_result is None:
            logger.warning(
                "⚠️ %s: docking stage skipped (validation conda env not active/installed)",
                pdb_id,
            )
        else:
            logger.info(
                "🎯 %s: docking -> %s%s",
                pdb_id,
                dock_result.status.value,
                f" ({dock_result.failure_mode.value})" if dock_result.failure_mode else "",
            )
    elif ccd_codes:
        logger.info("⏭️ %s: docking skipped (--no-dock)", pdb_id)

    if run_complex_md and run_dock:
        complex_md_result = run_complex_md_simulation_stage(
            pdb_id,
            ComplexMdSimulationConfig(
                enabled=True,
                n_steps=config.get("complex_md_n_steps", ComplexMdSimulationConfig.n_steps),
                max_minimization_iterations=config.get(
                    "complex_md_max_minimization_iterations",
                    ComplexMdSimulationConfig.max_minimization_iterations,
                ),
            ),
            db_path,
            force_refresh=force_refresh,
        )
        if complex_md_result is None:
            logger.warning(
                "⚠️ %s: complex MD stage skipped (validation conda env not active/installed, "
                "needs ambertools)",
                pdb_id,
            )
        else:
            logger.info(
                "🧪🎯 %s: complex MD (receptor+ligand) -> %s%s",
                pdb_id,
                complex_md_result.status.value,
                f" ({complex_md_result.failure_mode.value})" if complex_md_result.failure_mode else "",
            )
    elif ccd_codes and run_complex_md:
        logger.info("⏭️ %s: complex MD skipped (docking is off, needs a docked pose)", pdb_id)

    print_validate_one_summary(pdb_id, db_path)


def print_validate_one_summary(pdb_id: str, db_path: Path) -> None:
    """Print this candidate's report row. Read-only -- does not write results/report.csv."""
    rows = [row for row in build_report_table(db_path=db_path) if row.pdb_id == pdb_id]
    if not rows:
        logger.warning("⚠️ %s: no report row found (did simulability fail?)", pdb_id)
        return
    row = rows[0]
    print(f"\n--- {pdb_id} summary ---")
    print(f"title: {row.title}")
    print(f"organism: {row.organism}")
    print(f"residues: {row.n_residues}  resolution: {row.resolution}")
    print(f"ligand: {row.ligand_ccd}")
    print(f"modeling:      {row.modeling.status:<8} {row.modeling.notes}")
    print(f"md_simulation: {row.md_simulation.status:<8} {row.md_simulation.notes}")
    print(f"docking:       {row.docking.status:<8} {row.docking.notes}")
    print(f"suitable_for: {row.suitable_for}")

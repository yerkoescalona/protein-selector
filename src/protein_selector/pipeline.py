"""End-to-end orchestration: hard filters -> ... -> report (PLAN.md §7/§10, §12).

Per PLAN.md §7's decision ("script-first for hard filters through
parameterizability; introduce Snakemake when validation lands"): this is
deliberately a plain function, not a Snakemake DAG. Revisit if per-protein
caching/resume across runs becomes a real pain point -- persistence in
``core/db.py``'s SQLite tables already gives *most* of "don't recompute
unchanged work" for free (every upsert is idempotent, keyed by
pdb_id/ligand_id/uniprot_accession/etc.), which is weaker motivation for a
full workflow engine than PLAN.md's §7 argument assumed before this pipeline
existed.

**Stage coverage, stated explicitly:**

- Hard filters -> simulability (incl. oligomeric-state/non-standard-residue
  composition checks) -> ligand CCD/SMILES wiring -> RDKit parameterizability
  -> literature counts: always run, all cheap/network-only, no conda needed.
- Meeko real-parameterization: best-effort, needs the `validate` extra
  (rdkit/meeko); a missing extra is caught and logged as skipped, not fatal.
- ex02 (modeling/AlphaFold DB lookup): on by default (`run_ex02=True`) --
  cheap, fetch-only, no conda needed.
- ex03 (MD validator): off by default (`run_ex03=False`) -- needs the
  conda-only `environment-validation.yml` env; a missing ``openmm``/
  ``pdbfixer`` install is caught on the *first* candidate and stops further
  attempts for the rest of the run (there's no point retrying 20 candidates
  against an environment that's already confirmed absent).
- **ex04 (docking validator) and fpocket-based pocket detection are
  deliberately NOT auto-wired here, and that's a real, stated gap, not an
  oversight:** ``docking.docking_validation.run_docking_validation`` needs a
  *prepared* receptor PDBQT (this repo has no receptor-preparation wrapper --
  the live verification in this project's history used `obabel -xr`
  manually, not a module) and a docking-box center (fpocket's `parse_fpocket_info`
  only returns score/druggability/volume, not per-pocket 3D coordinates --
  extracting a real box center needs parsing fpocket's separate
  `pocket{N}_atm.pdb`/`_vert.pdb` output files, which no module here does
  yet). Pocket *detection* itself only needs a plain downloaded PDB file
  (fpocket operates directly on PDB, no PDBQT prep), so it's wired here as
  `run_pocket_detection` (off by default, needs a local `fpocket` binary) --
  but running an actual test-dock is not. Call
  `docking.docking_validation.run_docking_validation` directly with your own
  prepared receptor/box until that wiring is built.

Returns the final joined report rows (`core.report.CandidateReportRow`);
optionally writes them to CSV.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import requests

from protein_selector.bioinformatics.literature import fetch_literature_counts
from protein_selector.bioinformatics.store import upsert_literature_counts
from protein_selector.core.db import DEFAULT_DB_PATH
from protein_selector.core.difficulty import ScoringWeights
from protein_selector.core.report import (
    CandidateReportRow,
    build_report_table,
    write_report_csv,
)
from protein_selector.core.validation_result import ValidationResult
from protein_selector.core.validation_store import upsert_validation_results
from protein_selector.docking.ligands import (
    fetch_ligand_ccd_codes,
    fetch_smiles_for_ccd_codes,
)
from protein_selector.docking.parameterizability import filter_parameterizable
from protein_selector.docking.pocket import check_pocket_detected
from protein_selector.docking.store import (
    upsert_ligand_ccd_codes,
    upsert_parameterizability,
    upsert_pocket_detection,
)
from protein_selector.modeling.alphafold_lookup import fetch_alphafold_entry
from protein_selector.modeling.modeling_validation import EXERCISE_NAME as EX02_EXERCISE
from protein_selector.modeling.modeling_validation import run_modeling_validation
from protein_selector.modeling.store import upsert_alphafold_entry
from protein_selector.molecular_dynamics.md_validation import (
    EXERCISE_NAME as EX03_EXERCISE,
)
from protein_selector.structural_biology.candidates import (
    fetch_entry_metadata,
    search_candidate_ids,
)
from protein_selector.structural_biology.composition import (
    fetch_non_standard_residues,
    fetch_oligomeric_state,
)
from protein_selector.structural_biology.simulability import check_full_simulability
from protein_selector.structural_biology.store import (
    upsert_candidates,
    upsert_entity_composition,
    upsert_oligomeric_state,
    upsert_simulability,
)

logger = logging.getLogger(__name__)

_PDB_DOWNLOAD_URL = "https://files.rcsb.org/download"
_PDB_DOWNLOAD_TIMEOUT_SECONDS = 30


def _download_pdb_file(pdb_id: str, dest_dir: Path) -> Path:
    """Download a real PDB coordinate file from RCSB -- needed only for pocket detection.

    Not used by ex03 (``md_validation.run_test_md`` fetches via PDBFixer's own
    ``pdbid=`` argument, no separate download needed) or by ex02 (fetch-only,
    no structure file at all). fpocket, unlike Vina, operates directly on a
    plain PDB file -- no PDBQT/receptor-prep step is needed for detection
    itself (see this module's docstring for what IS still missing for a real
    test-dock).
    """
    response = requests.get(
        f"{_PDB_DOWNLOAD_URL}/{pdb_id}.pdb", timeout=_PDB_DOWNLOAD_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    dest_path = dest_dir / f"{pdb_id}.pdb"
    dest_path.write_text(response.text)
    return dest_path


def run_pipeline(
    db_path: Path = DEFAULT_DB_PATH,
    max_candidates: int = 20,
    max_atoms: int = 50_000,
    hard_filter_max_resolution: float = 3.0,
    method: str = "X-RAY DIFFRACTION",
    min_residues: int = 50,
    max_residues: int = 300,
    simulability_max_resolution: float = 2.5,
    run_ex02: bool = True,
    run_ex03: bool = False,
    run_pocket_detection: bool = False,
    ex03_n_steps: int | None = None,
    report_csv_path: Path | None = None,
    weights: ScoringWeights | None = None,
) -> list[CandidateReportRow]:
    """Run every wired stage over one hard-filters search, persisting as it goes.

    Returns the final joined report (also written to ``report_csv_path`` if
    given). Safe to call repeatedly -- every persisted table is upsert-based
    (see each domain's ``store.py``), so re-running just refreshes rows
    rather than duplicating them.
    """
    pdb_ids = search_candidate_ids(
        max_atoms=max_atoms, max_resolution=hard_filter_max_resolution, method=method,
        rows=max_candidates,
    )
    entries = fetch_entry_metadata(pdb_ids)
    upsert_candidates(entries, db_path=db_path)
    logger.info("hard filters: %d candidates", len(entries))

    assembly_info_by_pdb_id = fetch_oligomeric_state(entries)
    entity_infos_by_pdb_id = fetch_non_standard_residues(entries)
    upsert_oligomeric_state(list(assembly_info_by_pdb_id.values()), db_path=db_path)
    upsert_entity_composition(
        [info for infos in entity_infos_by_pdb_id.values() for info in infos], db_path=db_path
    )
    simulability_results = [
        check_full_simulability(
            entry,
            assembly_info_by_pdb_id.get(entry.pdb_id),
            entity_infos_by_pdb_id.get(entry.pdb_id),
            min_residues=min_residues,
            max_residues=max_residues,
            max_resolution=simulability_max_resolution,
        )
        for entry in entries
    ]
    upsert_simulability(simulability_results, db_path=db_path)
    logger.info(
        "simulability: %d/%d passed",
        sum(r.passed for r in simulability_results),
        len(simulability_results),
    )

    ligand_ccd_by_pdb_id = fetch_ligand_ccd_codes(entries)
    upsert_ligand_ccd_codes(ligand_ccd_by_pdb_id, db_path=db_path)
    all_ccd_codes = sorted({code for codes in ligand_ccd_by_pdb_id.values() for code in codes})
    smiles_by_ccd_code = fetch_smiles_for_ccd_codes(all_ccd_codes)
    _, parameterizability_results = filter_parameterizable(smiles_by_ccd_code)
    upsert_parameterizability(parameterizability_results, db_path=db_path)
    logger.info("parameterizability: %d ligands checked", len(parameterizability_results))

    try:
        from protein_selector.docking.meeko_parameterization import (
            filter_meeko_parameterizable,
        )
        from protein_selector.docking.store import upsert_meeko_parameterization
    except ImportError:
        logger.info("meeko parameterization skipped: `validate` extra not installed")
    else:
        _, meeko_results = filter_meeko_parameterizable(smiles_by_ccd_code)
        upsert_meeko_parameterization(meeko_results, db_path=db_path)
        logger.info("meeko parameterization: %d ligands checked", len(meeko_results))

    literature_counts = fetch_literature_counts(pdb_ids)
    upsert_literature_counts(literature_counts, db_path=db_path)
    logger.info("literature: %d counts fetched", len(literature_counts))

    if run_ex02:
        ex02_results: list[ValidationResult] = []
        for entry in entries:
            uniprot_accession = entry.uniprot_ids[0] if entry.uniprot_ids else None
            if uniprot_accession is None:
                continue
            try:
                alphafold_entry = fetch_alphafold_entry(uniprot_accession)
            except ValueError as exc:
                logger.warning("ex02 skipped for %s: %s", entry.pdb_id, exc)
                continue
            if alphafold_entry is not None:
                upsert_alphafold_entry(alphafold_entry, db_path=db_path)
            ex02_results.append(run_modeling_validation(entry.pdb_id, uniprot_accession))
        upsert_validation_results(EX02_EXERCISE, ex02_results, db_path=db_path)
        logger.info("ex02 modeling: %d candidates validated", len(ex02_results))

    if run_ex03:
        from protein_selector.molecular_dynamics.md_validation import run_test_md

        ex03_results: list[ValidationResult] = []
        for entry in entries:
            try:
                if ex03_n_steps is None:
                    ex03_results.append(run_test_md(entry.pdb_id))
                else:
                    ex03_results.append(run_test_md(entry.pdb_id, n_steps=ex03_n_steps))
            except ImportError:
                logger.warning(
                    "ex03 MD validation stopped: validation conda env not installed "
                    "(see environment-validation.yml)"
                )
                break
        if ex03_results:
            upsert_validation_results(EX03_EXERCISE, ex03_results, db_path=db_path)
            logger.info("ex03 MD: %d candidates validated", len(ex03_results))

    if run_pocket_detection:
        pocket_results = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            for entry in entries:
                try:
                    pdb_path = _download_pdb_file(entry.pdb_id, Path(tmp_dir))
                    pocket_results.append(check_pocket_detected(entry.pdb_id, pdb_path))
                except FileNotFoundError as exc:
                    logger.warning("pocket detection stopped: %s", exc)
                    break
                except requests.RequestException as exc:
                    logger.warning("pocket detection skipped for %s: %s", entry.pdb_id, exc)
        if pocket_results:
            upsert_pocket_detection(pocket_results, db_path=db_path)
            logger.info("pocket detection: %d candidates checked", len(pocket_results))

    rows = build_report_table(db_path=db_path, weights=weights)
    if report_csv_path is not None:
        write_report_csv(rows, report_csv_path)
        logger.info("report written to %s (%d rows)", report_csv_path, len(rows))
    return rows

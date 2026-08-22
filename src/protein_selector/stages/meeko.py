"""Real Meeko/PDBQT parameterizability (PLAN.md §16b's `meeko` rule).

Best-effort: needs the `validate` extra (rdkit/meeko). A missing extra is caught and
logged, not fatal -- the rest of the DAG must still run in a base-only env. The whole
``filter_meeko_parameterizable`` call must be inside the try (not just the import
statement) -- see ``.claude/CLAUDE.md`` bug 8 for why.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_meeko_stage(
    ccd_codes: list[str],
    smiles_by_ccd_code: dict[str, str | None],
    db_path,
    force_refresh: bool = False,
) -> None:
    """Run Meeko/PDBQT parameterization on any CCD code not already persisted.

    ``smiles_by_ccd_code`` need not cover every code in ``ccd_codes`` -- codes missing a
    SMILES here (e.g. a first run without the `validate` extra, followed by one with it)
    are fetched fresh via ``docking.ligands.fetch_smiles_for_ccd_codes``.
    """
    try:
        from protein_selector.docking.ligands import fetch_smiles_for_ccd_codes
        from protein_selector.docking.meeko_parameterization import (
            filter_meeko_parameterizable,
        )
        from protein_selector.docking.store import (
            load_meeko_parameterization,
            upsert_meeko_parameterization,
        )

        already_checked = (
            set() if force_refresh else set(load_meeko_parameterization(db_path).keys())
        )
        new_codes = [c for c in ccd_codes if c not in already_checked]
        logger.info(
            "💊 meeko: %d/%d ligands already checked (⏭️), %d new",
            len(ccd_codes) - len(new_codes),
            len(ccd_codes),
            len(new_codes),
        )
        if not new_codes:
            return
        still_needed = [c for c in new_codes if c not in smiles_by_ccd_code]
        if still_needed:
            smiles_by_ccd_code = {
                **smiles_by_ccd_code,
                **fetch_smiles_for_ccd_codes(still_needed),
            }
        _, results = filter_meeko_parameterizable(
            {c: smiles_by_ccd_code.get(c) for c in new_codes}
        )
        upsert_meeko_parameterization(results, db_path=db_path)
    except ImportError as exc:
        logger.info("⏭️ meeko parameterization skipped: %s", exc)

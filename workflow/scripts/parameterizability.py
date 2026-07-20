"""Snakemake `script:` target for `rule parameterizability` (PLAN.md §16b).

Depends on `ligands` for the persisted `ligand_ccd_codes` table; re-fetches SMILES for
those codes (cheap, batched, no persisted SMILES table exists -- same as
`pipeline.run_pipeline`'s original behavior).
"""

from pathlib import Path

from protein_selector.docking.ligands import fetch_smiles_for_ccd_codes
from protein_selector.docking.store import load_ligand_ccd_codes
from protein_selector.stages.parameterizability import run_parameterizability_stage

# Guarded defensively -- `docking.parameterizability.check_ligand_parameterizable` runs
# in-process today (no multiprocessing), but RDKit's own `AllChem.EmbedMolecule` or a
# future change could introduce the same spawn-based isolation `meeko.py` already needs
# this guard for -- see that script's docstring for the real bug this pattern fixes.
if __name__ == "__main__":
    db_path = Path(snakemake.config["db_path"])  # noqa: F821
    all_ccd_codes = sorted(
        {c for codes in load_ligand_ccd_codes(db_path).values() for c in codes}
    )
    smiles_by_ccd_code = fetch_smiles_for_ccd_codes(all_ccd_codes)

    run_parameterizability_stage(smiles_by_ccd_code, db_path=db_path)
    Path(snakemake.output.marker).touch()  # noqa: F821

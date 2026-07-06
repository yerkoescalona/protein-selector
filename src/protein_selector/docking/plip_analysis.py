"""ex04 docking validator, piece 2: PLIP interaction analysis (PLAN.md §4a/§10 step 4).

A self-dock RMSD close to the crystal pose (``vina_docking.py``) is
necessary but not sufficient -- PLAN.md §4a's easy-signal also wants
"interactions make biological sense." This module runs the real PLIP
(Protein-Ligand Interaction Profiler) analysis on a docked complex and
reports whether it finds any interpretable interaction at all (hydrogen
bonds, hydrophobic contacts, pi-stacking, salt bridges, halogen bonds,
water bridges) -- a pose with zero interactions of any kind is not a
teachable example regardless of how low its RMSD is.

Requires the validation conda environment's ``plip`` package. **Not
pip-installable in this project's base/`.venv`**: verified live
(2026-07-05) -- ``pip wheel plip`` fails during its build step, which
shells out to install `openbabel` via pip and that itself fails without
system Boost/openbabel C++ libs present (the same class of build-time
native-dependency problem as ``vina``, not a stub gap). conda-forge ships
prebuilt ``plip``/``openbabel`` packages instead -- see
``environment-validation.yml``. Lazily imported inside the one function
that needs it, same reason as this domain's other conda-only modules.

**Live-verified (2026-07-06)** in a throwaway `micromamba` env bootstrapped
from `environment-validation.yml`, against a real docked complex (1UBQ +
a real Vina-docked ethanol pose): `PDBComplex.ligands`, `characterize_complex`,
`interaction_sets` (keyed by exactly `f"{hetid}:{chain}:{position}"`, e.g.
`"UNL:X:1"`), and every attribute name in `_INTERACTION_ATTRIBUTES` below
(`hbonds_pdon`/`hbonds_ldon`/`hydrophobic_contacts`/`pistacking`/etc.) all
confirmed real, not guessed. **One real bug caught and fixed by this
verification, in the caller** (`docking_validation.py`, not this module):
a blank ligand chain-ID column made `PDBComplex.ligands` silently return
`[]` -- PLIP requires a real, non-blank chain ID to detect the ligand at
all. See `docking_validation.py`'s `_pdbqt_pose_to_pdb_hetatm_block`
docstring for the fix.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Not imported at module level -- see module docstring; keeps this module
# importable without the validation conda environment installed.

_INTERACTION_ATTRIBUTES = {
    "hydrogen_bonds": ("hbonds_pdon", "hbonds_ldon"),
    "hydrophobic_contacts": ("hydrophobic_contacts",),
    "pi_stacking": ("pistacking",),
    "pi_cation": ("pication_paro", "pication_laro"),
    "salt_bridges": ("saltbridge_lneg", "saltbridge_pneg"),
    "halogen_bonds": ("halogen_bonds",),
    "water_bridges": ("water_bridges",),
}


@dataclass
class PlipAnalysisResult:
    """Outcome of the PLIP interaction-analysis gate for one docked complex."""

    pdb_id: str
    passed: bool
    reasons: list[str] = field(default_factory=list)
    interaction_counts: dict[str, int] = field(default_factory=dict)


def run_plip_analysis(pdb_id: str, complex_pdb_path: Path) -> PlipAnalysisResult:
    """Run PLIP on a docked protein-ligand complex PDB and count interaction types.

    ``complex_pdb_path`` must be a single PDB file containing both the
    receptor and the docked ligand pose (e.g. the docked pose converted to
    PDB and appended to the receptor's own structure) -- PLIP analyzes
    ligand/protein interactions within one structure, it does not accept
    them as separate files.

    Requires the validation conda environment; raises ``ImportError`` with
    an install hint if ``plip`` isn't available.
    """
    try:
        import plip.structure.preparation as plip_prep  # ty: ignore[unresolved-import]
    except ImportError as exc:
        raise ImportError(
            "run_plip_analysis requires the plip package; "
            "install it via the validation conda environment "
            "(`micromamba env create -f environment-validation.yml`), not pip "
            "(its build tries to pip-install openbabel, which needs system libs)."
        ) from exc

    logger.info("%s: running PLIP on %s", pdb_id, complex_pdb_path)
    complex_ = plip_prep.PDBComplex()
    complex_.load_pdb(str(complex_pdb_path))

    if not complex_.ligands:
        logger.warning("%s: PLIP found no ligand in the complex", pdb_id)
        return PlipAnalysisResult(
            pdb_id=pdb_id,
            passed=False,
            reasons=["PLIP found no ligand in the complex"],
            interaction_counts={},
        )

    ligand = complex_.ligands[0]
    complex_.characterize_complex(ligand)
    binding_site_id = f"{ligand.hetid}:{ligand.chain}:{ligand.position}"
    interaction_set = complex_.interaction_sets.get(binding_site_id)
    if interaction_set is None:
        return PlipAnalysisResult(
            pdb_id=pdb_id,
            passed=False,
            reasons=[f"PLIP produced no interaction set for binding site {binding_site_id}"],
            interaction_counts={},
        )

    counts = {
        name: sum(len(getattr(interaction_set, attr)) for attr in attrs)
        for name, attrs in _INTERACTION_ATTRIBUTES.items()
    }
    total = sum(counts.values())
    if total == 0:
        logger.info("%s: PLIP found no interpretable interactions", pdb_id)
        return PlipAnalysisResult(
            pdb_id=pdb_id,
            passed=False,
            reasons=["PLIP found no interpretable protein-ligand interactions"],
            interaction_counts=counts,
        )

    logger.info("%s: PLIP interactions: %s", pdb_id, counts)
    return PlipAnalysisResult(pdb_id=pdb_id, passed=True, reasons=[], interaction_counts=counts)

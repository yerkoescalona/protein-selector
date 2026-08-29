"""Native (crystal) ligand selection + prep for the `dock_validate` rule (PLAN.md §17/§18).

Docks the CRYSTAL pose (not Meeko's SMILES-embedded conformer, which is in an arbitrary
frame), picks the largest organic (Meeko-parameterizable) ligand when a structure has
several, and prepares that ligand's PDBQT straight from its bound-pose coordinates via
`obabel`. Extraction + alignment into the MD-relaxed frame live in
``molecular_dynamics.structure_alignment.align_ligand_into_md_frame`` (PLAN.md §18/§21).
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path

from protein_selector.domain.docking.meeko_ligand import (
    MeekoParameterizationResult,
)
from protein_selector.domain.docking.vina import _parse_heavy_atom_coords

logger = logging.getLogger(__name__)

# "Passed Meeko" is not sufficient for "meaningful biological ligand" -- see PLAN.md §19.
# Same list as scripts/course_candidates.sql's excluded_ccd_codes CTE (kept in sync by hand
# -- one is SQL, one is Python, no shared source).
_EXCLUDED_CCD_CODES = frozenset(
    {
        "SO4", "CL", "NA", "GOL", "EDO", "PO4", "FMT", "PEG", "TRS",
        "MES", "IPA", "K", "MOH", "DCE", "ACY", "MRD", "MLI", "MPD",
        "BME", "HOH", "ACT", "UNX", "1PE", "DMS", "TLA", "CIT", "NH4",
        "BR", "IOD", "PGE",
        "FE", "FE2", "ZN", "MG", "CA", "MN", "CU", "CD", "HG", "GA",
        "SR", "CS", "SCN", "UNL", "NI", "LI", "CO",
        "SF4", "F3S", "FES", "HEM", "HEC", "RBF", "FMN", "FAD", "BTN",
        "COA", "NAD", "GTP", "GSP", "PLP",
        # Small polyatomic crystallization ions -- nitrate/nitrite were the concrete
        # bug this brief reports (1LKS/1V7S).
        "NO3", "NO2",
        # PLAN.md §28 C.1, added 2026-08-28 from a measurement, not a guess: these are
        # the codes that actually reached Vina in the real store and behaved like
        # non-ligands -- 49 of 370 docking-tested candidates (13%), passing at 10.2%
        # against the pool's own 35.4%. Each group is a *reason*, not a list of
        # coincidences:
        #   PEG family -- crystallization additives. "PEG"/"1PE"/"PGE" were already
        #   here; the longer chains were not, so P6G/PG4 slipped through (2IEK's
        #   "docking target" was hexaethylene glycol). 0/7 passed.
        "P6G", "PG4", "PE4", "2PE", "XPE", "P33", "7PE", "PG0", "PG5", "PG6", "DIO",
        #   Sugars/glycosylation residues -- NAG in particular is normally N-linked to
        #   asparagine, i.e. part of the protein, not a bound ligand to redock. 0/10.
        "NAG", "NDG", "BGC", "MAN", "BMA", "FUC", "GAL", "XYL",
        #   Buffers, detergents and cryoprotectants: HED (2-hydroxyethyl disulfide,
        #   12 candidates, 0 passed), EPE (HEPES), IMD (imidazole), MPD, BOG, LDA.
        "HED", "EPE", "IMD", "BOG", "LDA", "C8E", "SBT", "POL", "PIN", "EOH",
        #   Diatomic/triatomic gases and ions -- too few atoms for a meaningful pose
        #   or RMSD (the B.1 coverage guard rejects them downstream anyway; excluding
        #   them here means not spending a Vina run to find that out).
        "NO", "CMO", "OXY", "CYN",
    }
)


def is_dockable_ligand_code(
    ccd_code: str, meeko_results: Mapping[str, MeekoParameterizationResult]
) -> bool:
    """The real "is this a meaningful, dockable organic ligand" predicate (Problem 1/3).

    Two independent gates, both required: not on ``_EXCLUDED_CCD_CODES`` (checked FIRST,
    regardless of Meeko's own verdict -- a denylisted ion/additive that happens to pass
    Meeko's chemistry checks must still be excluded), AND passed real Meeko
    parameterization (``meeko_results``, persisted by the ``meeko`` stage).
    """
    if ccd_code in _EXCLUDED_CCD_CODES:
        return False
    result = meeko_results.get(ccd_code)
    return result is not None and result.passed


def ligand_centroid(ligand_pdb_block: str) -> tuple[float, float, float] | None:
    """Heavy-atom centroid of an extracted ligand HETATM block.

    ``None`` if no heavy atoms parse (e.g. an empty block).
    """
    coords = _parse_heavy_atom_coords(ligand_pdb_block)
    if not coords:
        return None
    n = len(coords)
    return (
        sum(c[0] for c in coords) / n,
        sum(c[1] for c in coords) / n,
        sum(c[2] for c in coords) / n,
    )


_DEFAULT_BOX_PADDING_ANGSTROM = 6.0  # PLAN.md §20: same padding value §17b used for
# fpocket-derived boxes, applied here to the ligand's own extent instead. Generous enough
# that Vina can search local rotations/translations around the true pose without the box
# itself constraining a correct answer out of reach.


def ligand_bounding_box(
    ligand_pdb_block: str, padding_angstroms: float = _DEFAULT_BOX_PADDING_ANGSTROM
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    """PLAN.md §20: the self-dock Vina box, built from the LIGAND's own aligned coordinates.

    Not fpocket's pocket -- see PLAN.md §20 for why. Per-axis (anisotropic) bounding box of
    the ligand's own heavy-atom coordinates, each axis padded independently -- an elongated
    ligand wastes less of Vina's search volume this way than an isotropic cube would.
    Returns ``None`` if no heavy atoms parse.
    """
    coords = _parse_heavy_atom_coords(ligand_pdb_block)
    if not coords:
        return None
    xs = [c[0] for c in coords]
    ys = [c[1] for c in coords]
    zs = [c[2] for c in coords]
    center = (
        (min(xs) + max(xs)) / 2,
        (min(ys) + max(ys)) / 2,
        (min(zs) + max(zs)) / 2,
    )
    size = (
        (max(xs) - min(xs)) + padding_angstroms,
        (max(ys) - min(ys)) + padding_angstroms,
        (max(zs) - min(zs)) + padding_angstroms,
    )
    return center, size


def pick_largest_organic_ligand(
    ccd_codes: list[str],
    meeko_results: Mapping[str, MeekoParameterizationResult],
    smiles_by_ccd: Mapping[str, str | None],
) -> str | None:
    """PLAN.md §17a.2/§19: among a candidate's bound ligands, pick the largest ORGANIC one.

    "Organic" is ``is_dockable_ligand_code`` -- not on the ion/additive denylist AND passed
    real Meeko parameterization (see PLAN.md §19 for why "passed Meeko" alone isn't
    sufficient). "Largest" is heavy-atom count from RDKit on the persisted SMILES. Ties
    broken by CCD code alphabetically. Returns ``None`` if no candidate is dockable.

    Requires the `validate` extra (rdkit).
    """
    candidates = [code for code in ccd_codes if is_dockable_ligand_code(code, meeko_results)]
    if not candidates:
        return None

    try:
        from rdkit import Chem, RDLogger
    except ImportError as exc:
        raise ImportError(
            "pick_largest_organic_ligand requires rdkit; "
            "install it via `uv sync --extra validate`."
        ) from exc

    RDLogger.DisableLog("rdApp.*")  # ty: ignore[unresolved-attribute]

    def heavy_atom_count(code: str) -> int:
        smiles = smiles_by_ccd.get(code)
        if not smiles:
            return 0
        mol = Chem.MolFromSmiles(smiles)
        return mol.GetNumHeavyAtoms() if mol is not None else 0

    ranked = sorted(candidates, key=lambda code: (-heavy_atom_count(code), code))
    return ranked[0]


def prepare_ligand_pdbqt(ligand_pdb_block: str, dest_path: Path) -> Path:
    """Convert the extracted native-ligand HETATM block into a Vina-ready ligand PDBQT.

    Uses `obabel` directly on the crystal coordinates -- not Meeko's SMILES-embedded
    conformer, which is in an arbitrary frame (PLAN.md §17a.1). No `-xr` flag (the ligand
    must stay flexible for Vina). Same obabel exit-0-on-empty-output footgun as
    ``receptor_prep.prepare_receptor_pdbqt`` -- checked by file existence+size, not return
    code.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        src_path = Path(tmp_dir) / "ligand.pdb"
        src_path.write_text(ligand_pdb_block + "\nEND\n")
        try:
            result = subprocess.run(
                ["obabel", str(src_path), "-O", str(dest_path)],
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                "obabel binary not found on PATH; install it via "
                "`conda install -c conda-forge openbabel`."
            ) from exc

        if not dest_path.exists() or dest_path.stat().st_size == 0:
            logger.warning(
                "❌ obabel failed to prepare ligand PDBQT from extracted HETATM block: %s",
                result.stderr,
            )
            raise RuntimeError(
                "obabel failed to prepare a ligand PDBQT from the extracted native "
                f"ligand block: {result.stderr.strip() or result.stdout.strip() or '(no output)'}"
            )

    return dest_path

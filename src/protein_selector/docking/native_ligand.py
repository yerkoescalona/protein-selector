"""Native (crystal) ligand selection + prep for the `dock_validate` rule (PLAN.md §17/§18).

Resolves the decisions PLAN.md §17a settled: dock the CRYSTAL pose (not Meeko's
SMILES-embedded conformer, which is in an arbitrary frame -- see
``docking_validation.py``'s module docstring for why that distinction matters), pick the
largest organic (Meeko-parameterizable) ligand when a structure has several, and prepare
that ligand's own PDBQT straight from its real bound-pose coordinates via `obabel` (not
via `meeko_parameterization.py`'s pipeline, which is a parameterizability *gate*, not a
coordinate source -- its persisted pass/fail is reused here, its embedded conformer is
not).

**PLAN.md §18 (2026-07-19): extraction + alignment now live in
``molecular_dynamics.structure_alignment.align_ligand_into_md_frame``**, via MDAnalysis --
this module previously hand-rolled the crystal HETATM extraction
(``extract_ligand_hetatm_block``) and a "strip this ligand from the receptor"
(``strip_ligand_records``) step, both removed once the receptor became the MD-relaxed
structure directly (already heterogen-free, no stripping needed) and ligand extraction
moved to MDAnalysis (which also handles the crystal-to-MD-frame alignment in the same
step, more robustly than the hand-rolled version did).
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path

from protein_selector.docking.meeko_parameterization import MeekoParameterizationResult
from protein_selector.docking.vina_docking import _parse_heavy_atom_coords

logger = logging.getLogger(__name__)

# scripts/ligand_filter_fix_brief.md, Problem 1 (2026-07-19): "passed Meeko
# parameterization" is NOT sufficient to mean "a meaningful biological ligand" -- small
# polyatomic crystallization ions/cryoprotectants (nitrate, sulfate, phosphate, ...) have
# real covalent bonds and pass Meeko's chemistry checks cleanly, even though they aren't
# real binding-site ligands. Confirmed live: 1LKS/1V7S (both nitrate-only structures) were
# picked as "organic" and reached `docking: success`. Same list as
# `scripts/course_candidates.sql`'s `excluded_ccd_codes` CTE (kept in sync by hand -- one
# is SQL, one is Python, no shared source; re-verify both stay identical if either changes)
# -- a judgment call, not derived from any schema field: crystallization
# additives/cryoprotectants, bare metal ions (real biology, but not a real
# protein-ligand *interaction* worth docking), and metal clusters/covalently-tricky
# cofactors "too difficult to parametrize" per the instructor's explicit ask.
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

    **Real design fix, replacing §17a.3/§17b's fpocket-pocket-derived box.** The self-dock
    validation question is "can Vina reproduce the experimentally observed pose" -- so the
    search box must be centered on and sized to that pose directly, not on whatever pocket
    fpocket's independent alpha-sphere clustering happens to carve out nearby. fpocket can
    legitimately return a pocket that geometrically *contains* the ligand centroid while
    being a small, low-quality artifact (confirmed live, PDB 3DAU: the containing pocket
    had `druggability_score` 0.0, volume 187 Å³, while a real 1571 Å³/druggability-0.581
    pocket sat ~15 Å away, uninvolved because it didn't happen to contain the centroid
    point) -- handing Vina that small/wrong box, not the real binding-site geometry, then
    silently miscredits an off-target search as "the receptor changed" or "Vina is
    inaccurate" when the actual cause is upstream box selection. fpocket/pocket_detection
    stays a real, persisted, independently useful signal (a legitimate "did blind pocket
    detection also find the true site, unprompted" comparison worth discussing with
    students) -- it just no longer gates or defines the Vina search box.

    Per-axis (anisotropic) bounding box of the ligand's own heavy-atom coordinates, each
    axis padded independently by ``padding_angstroms`` -- NOT the isotropic
    max-pairwise-vertex-distance cube ``pocket._parse_vertex_extent`` uses for fpocket
    alpha spheres (that shape suits a roughly spherical pocket; a real bound ligand is
    frequently elongated, and an anisotropic box wastes less of Vina's search volume on
    empty space while still comfortably containing the true pose). Returns ``None`` if no
    heavy atoms parse (same failure signal as ``ligand_centroid``) -- callers already
    require a real centroid before reaching this point, so ``None`` here at that stage
    would indicate an internal inconsistency, not a normal candidate-level failure.
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
    """PLAN.md §17a.2: among a candidate's bound ligands, pick the largest ORGANIC one.

    "Organic, not an ion/cofactor that's hard to parametrize" is operationalized as
    ``is_dockable_ligand_code`` -- NOT on the crystallization-additive/ion denylist AND
    passed the real Meeko/AutoDock parameterization check. **Real, live-discovered gap,
    fixed 2026-07-19 (scripts/ligand_filter_fix_brief.md, Problem 1): "passed Meeko" alone
    is NOT sufficient.** Small polyatomic ions (nitrate, sulfate, phosphate, ...) have real
    covalent bonds and pass Meeko's chemistry checks cleanly despite not being meaningful
    biological ligands -- confirmed live: 1LKS/1V7S (both nitrate-only structures) were
    picked as "organic" this way and reached `docking: success`. The denylist check now
    runs FIRST, regardless of what Meeko says. "Largest" is heavy-atom count from RDKit on
    the persisted SMILES (same SMILES source ``meeko``/``parameterizability`` already
    used). Ties broken by CCD code alphabetically, for determinism. Returns ``None`` if no
    candidate ligand is dockable.

    Requires the `validate` extra (rdkit); raises ``ImportError`` with that hint if
    unavailable, same pattern as every other rdkit-touching function in this package.
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

    Uses `obabel` directly on the crystal coordinates -- deliberately NOT
    ``meeko_parameterization.py``'s SMILES -> RDKit-embed -> Meeko pipeline, which builds
    a conformer in an arbitrary frame unrelated to the receptor's own coordinate system
    (useless both as a docking-box-relative starting ligand and as an RMSD reference, see
    PLAN.md §17a.1). No `-xr` flag (that's ``receptor_prep.py``'s "rigid receptor" option;
    the ligand must stay flexible for Vina to search torsions).

    **Same real footgun as ``receptor_prep.prepare_receptor_pdbqt`` (2026-07-08 finding,
    applies here unverified but by the same mechanism):** `obabel` can exit 0 while
    writing an empty output file on a bad/unparseable input. Checked by file
    existence+size, not return code, same discipline.

    **Not yet live-verified** (no `obabel` binary in this sandbox) -- confirm a real
    extracted HETATM block round-trips through `obabel` to a real, loadable PDBQT before
    trusting this in a live run.
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

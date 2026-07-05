"""L3 ligand parameterizability check, stage 2: real Meeko/AutoDock parameterization.

``parameterizability.py``'s RDKit sanitization is necessary but not
sufficient: a ligand can parse and sanitize fine and still fail real
force-field parameterization (e.g. 3D embedding failure, an unusual
functional group Meeko's atom typer can't assign charges/types to). This
module runs the real, heavier check Vina docking actually depends on:
SMILES -> 3D conformer -> Meeko ``MoleculePreparation`` -> PDBQT.

Requires the `validate` extra (`uv sync --extra validate`); `rdkit` and
`meeko` are imported lazily inside the check function, same reason as
``parameterizability.py`` -- keeps `store.py` (which every layer needs)
importable without the extra installed.

`meeko` needs `scipy`, `numpy`, and `gemmi` transitively, none of which it
declares as dependencies (a real, live-discovered gap, not something to
guess around) -- all three are pinned explicitly in this project's
`validate` extra for that reason. `openmm` is separately included per
PLAN.md's Meeko/OpenFF parameterization goal but not yet used by this
module -- OpenFF-side (MD, not docking) parameterization is a further step,
not started here.

Call sequence below was run live against a real SMILES (2026-07-05,
ethanol and phosphate) to confirm the actual meeko API, not inferred from
its docstrings alone:

    mol = Chem.AddHs(Chem.MolFromSmiles(smiles))
    AllChem.EmbedMolecule(mol, randomSeed=...)   # returns 0 on success, -1 on failure
    setups = MoleculePreparation().prepare(mol)  # a list; empty list on failure
    pdbqt_string, is_ok, err = PDBQTWriterLegacy.write_string(setups[0])
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Not imported at module level -- see module docstring; keeps this module
# importable (by store.py, transitively by everything) without the heavy
# `validate` extra installed.

_EMBED_RANDOM_SEED = 42


@dataclass
class MeekoParameterizationResult:
    """Outcome of the L3 real-parameterization check for one ligand."""

    ligand_id: str
    passed: bool
    reasons: list[str] = field(default_factory=list)


def check_meeko_parameterizable(
    ligand_id: str, smiles: str | None
) -> MeekoParameterizationResult:
    """L3 stage-2 gate: can Meeko actually parameterize this ligand for docking?

    Three independent failure modes, each surfaced explicitly:
    - RDKit can't parse/sanitize the SMILES at all (same check as
      ``parameterizability.py``, repeated here since this function is meant
      to be usable standalone on the L3 shortlist).
    - RDKit can't generate a 3D conformer (``EmbedMolecule`` returns ``-1``).
    - Meeko's ``MoleculePreparation`` produces no usable setup, or its PDBQT
      writer reports a failure.

    Requires the `validate` extra; raises ``ImportError`` with that hint if
    rdkit/meeko aren't installed.
    """
    if not smiles:
        return MeekoParameterizationResult(
            ligand_id=ligand_id, passed=False, reasons=["no SMILES provided"]
        )

    try:
        import meeko
        from rdkit import Chem, RDLogger
        from rdkit.Chem import AllChem
    except ImportError as exc:
        raise ImportError(
            "check_meeko_parameterizable requires rdkit and meeko; "
            "install them via `uv sync --extra validate`."
        ) from exc

    RDLogger.DisableLog("rdApp.*")  # ty: ignore[unresolved-attribute]

    mol = Chem.MolFromSmiles(smiles)
    if mol is None or mol.GetNumHeavyAtoms() == 0:
        return MeekoParameterizationResult(
            ligand_id=ligand_id,
            passed=False,
            reasons=["RDKit could not parse/sanitize SMILES"],
        )

    mol = Chem.AddHs(mol)
    # EmbedMolecule is a real Boost.Python C-extension function (verified at
    # runtime, same as RDLogger.DisableLog in parameterizability.py); rdkit's
    # bundled type stubs just don't declare it -- a third-party stub gap.
    embed_result = AllChem.EmbedMolecule(  # ty: ignore[unresolved-attribute]
        mol, randomSeed=_EMBED_RANDOM_SEED
    )
    if embed_result != 0:
        return MeekoParameterizationResult(
            ligand_id=ligand_id,
            passed=False,
            reasons=["RDKit could not generate a 3D conformer"],
        )

    setups = meeko.MoleculePreparation().prepare(mol)
    if not setups:
        return MeekoParameterizationResult(
            ligand_id=ligand_id,
            passed=False,
            reasons=["Meeko produced no molecule setup"],
        )

    _pdbqt_string, is_ok, error_message = meeko.PDBQTWriterLegacy.write_string(setups[0])
    if not is_ok:
        return MeekoParameterizationResult(
            ligand_id=ligand_id,
            passed=False,
            reasons=[f"Meeko PDBQT writer failed: {error_message}"],
        )

    return MeekoParameterizationResult(ligand_id=ligand_id, passed=True, reasons=[])


def filter_meeko_parameterizable(
    ligands: dict[str, str],
) -> tuple[list[str], list[MeekoParameterizationResult]]:
    """Apply the L3 stage-2 check to a batch of ``{ligand_id: smiles}`` pairs.

    Returns (ligand IDs that passed, results for every ligand) -- mirrors
    ``parameterizability.filter_parameterizable``'s shape.
    """
    results = [
        check_meeko_parameterizable(ligand_id, smiles)
        for ligand_id, smiles in ligands.items()
    ]
    passed = [result.ligand_id for result in results if result.passed]
    return passed, results

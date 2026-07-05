"""OpenFF ligand parameterization: can this ligand be force-fielded for an OpenMM MD run?

Per PLAN.md §10 step 4, this is now sequenced ahead of the ex04 docking
validator: the actual pedagogical end goal is a protein + relevant-ligand MD
simulation (extending ``md_validation.py`` beyond the apo protein), not just
a docking test-run, so this check comes first.

This is a **different toolchain from `docking/meeko_parameterization.py`**,
even though both start from a ligand SMILES: Meeko/PDBQT parameterizes a
ligand for Vina (docking), while this module parameterizes it for the
*OpenMM* force field (MD) via OpenFF's SMIRNOFF small-molecule force fields.
A ligand can pass one and fail the other -- they exercise different code
paths (atom typing/charge assignment differ completely), so don't assume
one implies the other.

Requires the validation conda environment (``openff-toolkit``, see
``environment-validation.yml``'s header for why it has no usable pip
release). Lazily imported inside the one function that needs it, same
reason as ``md_validation.py``: keeps this module (and anything that
transitively imports it, e.g. ``store.py``) loadable without the conda env
installed.

**Not yet cross-checked against a real OpenFF install** (this sandbox has no
conda by default, same caveat as ``docking/pocket.py``'s fpocket wrapper and
``md_validation.py`` itself) -- built from the documented
``openff.toolkit.Molecule``/``ForceField`` API, not guessed, but run it for
real (e.g. against a real bound-ligand SMILES) before trusting it on actual
candidates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_DEFAULT_FORCEFIELD = "openff-2.1.0.offxml"

# Not imported at module level -- see module docstring; keeps this module
# (and anything that transitively imports it, e.g. a future store.py)
# importable without the validation conda environment installed.


@dataclass
class OpenFFParameterizationResult:
    """Outcome of the OpenFF real-parameterization check for one ligand."""

    ligand_id: str
    passed: bool
    reasons: list[str] = field(default_factory=list)


def check_ligand_openff_parameterizable(
    ligand_id: str, smiles: str | None, forcefield: str = _DEFAULT_FORCEFIELD
) -> OpenFFParameterizationResult:
    """Can OpenFF actually parameterize this ligand for an OpenMM MD run?

    Three independent failure modes, each surfaced explicitly:
    - OpenFF can't parse/sanitize the SMILES at all.
    - OpenFF can't generate a 3D conformer.
    - The SMIRNOFF force field can't build an OpenMM ``System`` for the
      molecule (e.g. partial-charge assignment fails, or a chemistry the
      force field's parameter tree has no match for).

    Requires the validation conda environment; raises ``ImportError`` with
    an install hint if ``openff.toolkit`` isn't available.
    """
    if not smiles:
        return OpenFFParameterizationResult(
            ligand_id=ligand_id, passed=False, reasons=["no SMILES provided"]
        )

    try:
        from openff.toolkit import ForceField, Molecule  # ty: ignore[unresolved-import]
    except ImportError as exc:
        raise ImportError(
            "check_ligand_openff_parameterizable requires openff-toolkit; "
            "install it via the validation conda environment "
            "(`micromamba env create -f environment-validation.yml`), not pip."
        ) from exc

    try:
        molecule = Molecule.from_smiles(smiles, allow_undefined_stereo=True)
    except Exception as exc:  # OpenFF doesn't document a narrow exception set here
        return OpenFFParameterizationResult(
            ligand_id=ligand_id,
            passed=False,
            reasons=[f"OpenFF could not parse/sanitize SMILES: {exc}"],
        )

    try:
        molecule.generate_conformers(n_conformers=1)
    except Exception as exc:
        return OpenFFParameterizationResult(
            ligand_id=ligand_id,
            passed=False,
            reasons=[f"OpenFF could not generate a 3D conformer: {exc}"],
        )

    try:
        ff = ForceField(forcefield)
        ff.create_openmm_system(molecule.to_topology())
    except Exception as exc:
        return OpenFFParameterizationResult(
            ligand_id=ligand_id,
            passed=False,
            reasons=[f"SMIRNOFF force field could not parameterize the molecule: {exc}"],
        )

    return OpenFFParameterizationResult(ligand_id=ligand_id, passed=True, reasons=[])


def filter_openff_parameterizable(
    ligands: dict[str, str],
) -> tuple[list[str], list[OpenFFParameterizationResult]]:
    """Apply the OpenFF check to a batch of ``{ligand_id: smiles}`` pairs.

    Returns (ligand IDs that passed, results for every ligand) -- mirrors
    ``docking.parameterizability.filter_parameterizable``'s shape.
    """
    results = [
        check_ligand_openff_parameterizable(ligand_id, smiles)
        for ligand_id, smiles in ligands.items()
    ]
    passed = [result.ligand_id for result in results if result.passed]
    return passed, results

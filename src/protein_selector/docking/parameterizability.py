"""L3 ligand parameterizability check: can RDKit sanitize the ligand's SMILES?

Per PLAN.md §3/§5, "docking suitability" partly depends on whether the bound
ligand can even be parameterized for docking/MD -- a ligand RDKit can't
sanitize will break the exercise regardless of how good the protein is.

Implemented here: a pure RDKit sanitization check (no network, no external
Java tool). Requires the `validate` extra (`uv sync --extra validate`).

Deliberately NOT implemented here:
- Full Meeko/OpenFF force-field parameterization -- a stronger, slower check.
  RDKit sanitization is a fast, necessary-but-not-sufficient pre-filter: a
  ligand that fails here will definitely break docking/MD; one that passes
  still needs real parameterization (Meeko for Vina; OpenFF for MD) to be
  fully confirmed, which is a separate, heavier L3/L5 step -- not started.
- Pocket detection lives in `pocket.py` (fpocket, a native C binary -- p2rank
  was rejected outright for its JVM dependency, see PLAN.md §9).

Where does the SMILES come from? `ligands.py` wires this up: entry ->
non-polymer entity IDs (from `candidates.py`'s L1 fetch) -> CCD codes (e.g.
"ATP", "HEM") -> SMILES, via two batched RCSB Data API calls
(`fetch_ligand_ccd_codes` then `fetch_smiles_for_ccd_codes`). This module
still takes a SMILES directly so it can be tested independently of that
network wiring.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# `rdkit` is NOT imported at module level: this module is imported by
# store.py (which everyone needs, including L1/L2-only users), and rdkit
# lives behind the optional `validate` extra. Importing rdkit lazily, inside
# the one function that actually calls it, keeps `ParameterizabilityResult`
# and the rest of this module importable without the `validate` extra
# installed. Do not hoist this import back to module level.


@dataclass
class ParameterizabilityResult:
    """Outcome of the L3 RDKit sanitization check for one ligand."""

    ligand_id: str
    passed: bool
    reasons: list[str] = field(default_factory=list)


def check_ligand_parameterizable(
    ligand_id: str, smiles: str | None
) -> ParameterizabilityResult:
    """L3 gate: can RDKit parse and sanitize this ligand's SMILES?

    Two independent failure modes, both surfaced explicitly:
    - RDKit fails to parse/sanitize the string at all (``MolFromSmiles``
      returns ``None`` -- this also covers valence/kekulization errors,
      which RDKit resolves internally to ``None`` rather than raising).
    - The string parses but yields an empty molecule (e.g. ``""`` parses to
      a valid zero-atom ``Mol``, not ``None`` -- this is NOT a pass).

    Requires the `validate` extra (`uv sync --extra validate`); raises
    ``ImportError`` with that hint if rdkit isn't installed.
    """
    if not smiles:
        return ParameterizabilityResult(
            ligand_id=ligand_id, passed=False, reasons=["no SMILES provided"]
        )

    try:
        from rdkit import Chem, RDLogger
    except ImportError as exc:
        raise ImportError(
            "check_ligand_parameterizable requires rdkit; "
            "install it via `uv sync --extra validate`."
        ) from exc

    # RDKit logs parse errors to stderr by default. A failed sanitization
    # attempt is an expected, handled outcome here -- not a bug that should
    # print console noise on every failing ligand. Idempotent, so calling it
    # on every invocation (rather than once at import time) is harmless.
    # DisableLog is a real Boost.Python C-extension function (verified at
    # runtime); rdkit's bundled type stubs just don't declare it -- a
    # third-party stub gap, not a bug here.
    RDLogger.DisableLog("rdApp.*")  # ty: ignore[unresolved-attribute]

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return ParameterizabilityResult(
            ligand_id=ligand_id,
            passed=False,
            reasons=["RDKit could not parse/sanitize SMILES"],
        )
    if mol.GetNumHeavyAtoms() == 0:
        return ParameterizabilityResult(
            ligand_id=ligand_id,
            passed=False,
            reasons=["SMILES parsed to an empty molecule"],
        )

    return ParameterizabilityResult(ligand_id=ligand_id, passed=True, reasons=[])


def filter_parameterizable(
    ligands: dict[str, str],
) -> tuple[list[str], list[ParameterizabilityResult]]:
    """Apply the L3 check to a batch of ``{ligand_id: smiles}`` pairs.

    Returns (ligand IDs that passed, results for every ligand) -- mirrors
    ``simulability.filter_simulable``'s shape.
    """
    results = [
        check_ligand_parameterizable(ligand_id, smiles)
        for ligand_id, smiles in ligands.items()
    ]
    passed = [result.ligand_id for result in results if result.passed]
    return passed, results

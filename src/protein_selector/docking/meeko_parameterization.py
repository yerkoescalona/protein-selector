"""Parameterizability ligand check, stage 2: real Meeko/AutoDock parameterization.

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

**Real, live-discovered bug (2026-07-06), fixed here:** ``AllChem.EmbedMolecule``
can hang indefinitely, not just fail fast, on certain real bound ligands --
confirmed live running the real pipeline against a random hard-filters
sample: HEM (heme) hung for minutes with no CPU-bound progress (its
iron-coordination bonds are a known real limitation of RDKit's ETKDG
embedding algorithm, not a bug in this code). There is no in-process,
reliable way to interrupt a hung native (C-extension) call from Python --
``signal.alarm`` does not reliably interrupt code that never returns to the
Python bytecode dispatch loop. ``filter_meeko_parameterizable`` therefore
runs each ligand's check in its own subprocess (``multiprocessing``, spawn
context) with a real wall-clock timeout, killing and recording a timeout
failure for any ligand that hangs, rather than letting one bad ligand stall
an entire batch/pipeline run indefinitely.
"""

from __future__ import annotations

import logging
import multiprocessing
from collections.abc import Mapping
from dataclasses import dataclass, field

from tqdm.auto import tqdm

# Not imported at module level -- see module docstring; keeps this module
# importable (by store.py, transitively by everything) without the heavy
# `validate` extra installed.

logger = logging.getLogger(__name__)

_EMBED_RANDOM_SEED = 42
_DEFAULT_TIMEOUT_SECONDS = 30.0


@dataclass
class MeekoParameterizationResult:
    """Outcome of the parameterizability real-parameterization check for one ligand."""

    ligand_id: str
    passed: bool
    reasons: list[str] = field(default_factory=list)


def check_meeko_parameterizable(
    ligand_id: str, smiles: str | None
) -> MeekoParameterizationResult:
    """Parameterizability stage-2 gate: can Meeko actually parameterize this ligand for docking?

    Three independent failure modes, each surfaced explicitly:
    - RDKit can't parse/sanitize the SMILES at all (same check as
      ``parameterizability.py``, repeated here since this function is meant
      to be usable standalone on the parameterizability shortlist).
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


def _run_check_into_queue(
    ligand_id: str, smiles: str | None, queue: multiprocessing.Queue[MeekoParameterizationResult]
) -> None:
    """Subprocess entry point: run the real check and put its result on the queue.

    Not called directly -- see ``_check_meeko_parameterizable_with_timeout``.
    """
    queue.put(check_meeko_parameterizable(ligand_id, smiles))


def _check_meeko_parameterizable_with_timeout(
    ligand_id: str, smiles: str | None, timeout_seconds: float
) -> MeekoParameterizationResult:
    """Run ``check_meeko_parameterizable`` in its own process, killing it on a real hang.

    See the module docstring for why: ``AllChem.EmbedMolecule`` can hang
    indefinitely on some real ligands (live-confirmed on HEM), and there is
    no reliable in-process way to interrupt a hung native call. Uses the
    ``spawn`` start method deliberately (not the default ``fork`` on Linux) --
    safer around native extensions that may hold locks/threads at fork time.
    """
    ctx = multiprocessing.get_context("spawn")
    queue: multiprocessing.Queue[MeekoParameterizationResult] = ctx.Queue()
    process = ctx.Process(target=_run_check_into_queue, args=(ligand_id, smiles, queue))
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join()
        return MeekoParameterizationResult(
            ligand_id=ligand_id,
            passed=False,
            reasons=[
                f"Meeko/RDKit check timed out after {timeout_seconds}s -- likely a hung "
                "3D embed (known real limitation for some organometallic/coordination "
                "ligands, e.g. HEM)"
            ],
        )
    return queue.get()


def filter_meeko_parameterizable(
    ligands: Mapping[str, str | None],
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> tuple[list[str], list[MeekoParameterizationResult]]:
    """Apply the parameterizability stage-2 check to a batch of ``{ligand_id: smiles}`` pairs.

    ``smiles`` may be ``None`` -- see ``parameterizability.filter_parameterizable``'s
    docstring for why (straight from ``ligands.fetch_smiles_for_ccd_codes``);
    ``check_meeko_parameterizable`` already handles it as a real failure.

    Each ligand is checked in its own subprocess with a real wall-clock
    ``timeout_seconds`` -- see ``_check_meeko_parameterizable_with_timeout``'s
    docstring for why (a live-confirmed hang on HEM, not a guessed risk).

    Returns (ligand IDs that passed, results for every ligand) -- mirrors
    ``parameterizability.filter_parameterizable``'s shape.
    """
    results = []
    for ligand_id, smiles in tqdm(ligands.items(), desc="💊 Meeko parameterization", unit="ligand"):
        logger.debug("💊 meeko %s: starting real 3D-embed + PDBQT check", ligand_id)
        result = _check_meeko_parameterizable_with_timeout(ligand_id, smiles, timeout_seconds)
        logger.debug("%s meeko %s: passed=%s", "✅" if result.passed else "❌", ligand_id, result.passed)
        results.append(result)
    passed = [result.ligand_id for result in results if result.passed]
    return passed, results

"""Parameterizability ligand check, stage 2: real Meeko/AutoDock parameterization.

``parameterizability.py``'s RDKit sanitization is necessary but not sufficient -- this
module runs the real, heavier check Vina docking actually depends on: SMILES -> 3D
conformer -> Meeko ``MoleculePreparation`` -> PDBQT.

Requires the `validate` extra; `rdkit`/`meeko` are imported lazily, same reason as
``parameterizability.py``. `meeko` needs `scipy`/`numpy`/`gemmi` transitively without
declaring them -- pinned explicitly in the `validate` extra.

Each ligand runs in its own subprocess with a wall-clock timeout -- ``AllChem.EmbedMolecule``
can hang indefinitely (not just fail) on some real ligands (e.g. HEM); see
``.claude/CLAUDE.md`` bugs 6-8 for the three real, silent failure modes this discipline
was built to catch.
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


def _interpret_process_result(
    ligand_id: str,
    process: multiprocessing.process.BaseProcess,
    queue: multiprocessing.Queue[MeekoParameterizationResult],
    timeout_seconds: float,
) -> MeekoParameterizationResult:
    """Turn a joined subprocess's outcome into a result -- never blocks, never raises.

    Split out from ``_check_meeko_parameterizable_with_timeout`` so its two failure modes
    (timeout vs. a crashed child that queued nothing) are independently testable. See
    ``.claude/CLAUDE.md`` bug 7 for why ``queue.empty()`` matters here.
    """
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

    if queue.empty():
        return MeekoParameterizationResult(
            ligand_id=ligand_id,
            passed=False,
            reasons=[
                f"Meeko/RDKit check subprocess exited (code {process.exitcode}) without a "
                "result -- see stderr for the real traceback (multiprocessing prints "
                "unhandled child exceptions there, not to this process' exception chain)"
            ],
        )
    return queue.get()


def _check_meeko_parameterizable_with_timeout(
    ligand_id: str, smiles: str | None, timeout_seconds: float
) -> MeekoParameterizationResult:
    """Run ``check_meeko_parameterizable`` in its own process, killing it on a real hang.

    See the module docstring. Uses ``spawn`` deliberately (not the default ``fork`` on
    Linux) -- safer around native extensions that may hold locks/threads at fork time.
    """
    ctx = multiprocessing.get_context("spawn")
    queue: multiprocessing.Queue[MeekoParameterizationResult] = ctx.Queue()
    process = ctx.Process(target=_run_check_into_queue, args=(ligand_id, smiles, queue))
    process.start()
    process.join(timeout_seconds)
    return _interpret_process_result(ligand_id, process, queue, timeout_seconds)


def filter_meeko_parameterizable(
    ligands: Mapping[str, str | None],
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
) -> tuple[list[str], list[MeekoParameterizationResult]]:
    """Apply the parameterizability stage-2 check to a batch of ``{ligand_id: smiles}`` pairs.

    ``smiles`` may be ``None`` -- ``check_meeko_parameterizable`` handles it as a real
    failure. Each ligand is checked in its own subprocess with a real wall-clock
    ``timeout_seconds``. Checks rdkit/meeko importability once here, in the parent process,
    before spawning anything -- see ``.claude/CLAUDE.md`` bug 8 for why deferring that check
    into the subprocess silently broke every caller's `except ImportError` guard.

    Returns (ligand IDs that passed, results for every ligand) -- mirrors
    ``parameterizability.filter_parameterizable``'s shape.
    """
    try:
        import meeko  # noqa: F401
        import rdkit  # noqa: F401
    except ImportError as exc:
        raise ImportError(
            "filter_meeko_parameterizable requires rdkit and meeko; "
            "install them via `uv sync --extra validate`."
        ) from exc

    results = []
    for ligand_id, smiles in tqdm(ligands.items(), desc="💊 Meeko parameterization", unit="ligand"):
        logger.debug("💊 meeko %s: starting real 3D-embed + PDBQT check", ligand_id)
        result = _check_meeko_parameterizable_with_timeout(ligand_id, smiles, timeout_seconds)
        logger.debug("%s meeko %s: passed=%s", "✅" if result.passed else "❌", ligand_id, result.passed)
        results.append(result)
    passed = [result.ligand_id for result in results if result.passed]
    return passed, results

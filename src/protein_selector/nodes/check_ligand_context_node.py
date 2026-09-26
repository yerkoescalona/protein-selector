"""Ligand context per candidate: is the ligand the selector docks held by a metal or a bond?

A recorded check like ``check_numbering``, not a validator: it writes one
``ligand_context`` row per candidate and never a ``validation`` row. The pipeline filters
nothing on it; the report carries the verdict for whoever builds a course list.

Only candidates with a dockable ligand are checked, and the ligand judged is the one the
docking step would pick (``pick_largest_organic_ligand``, the same call
``resolve_docking_target`` makes). It ranks on the stored SMILES; a dockable code with none
stored is looked up at RCSB, where the docking step gets every SMILES it ranks on. A
candidate without a dockable ligand gets no row.

Incremental: a stored row is reused only when it judged the ligand that would be picked
now; a different pick (the Meeko results changed) checks again, as does ``force_refresh``.
Downloads run on a small thread pool and each row is persisted as its check finishes. A
check that fails (``LigandContextError``: the file could not be fetched or read, or holds
no copy of the ligand) is logged and persists **no row**, which leaves the candidate
pending. Any other exception is a bug: no further check is started, the running ones
finish and are stored, and the exception propagates.

The store is upsert-only, so a row is never removed. A row whose ligand is no longer the
pick (the candidate lost its dockable ligand, or its recheck failed) stays behind, naming
the ligand it judged in ``ccd_code``. The run counts those as ``stale``; the report
withholds the verdict of a row whose ligand is no longer dockable for that entry.
"""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import TypedDict

from protein_selector.core.config import LigandContextConfig
from protein_selector.core.registry import Granularity, collection, table
from protein_selector.domain.docking.ligand_context import (
    LigandContextError,
    LigandContextResult,
    find_ligand_context,
)
from protein_selector.domain.docking.native_ligand import (
    is_dockable_ligand_code,
    pick_largest_organic_ligand,
)
from protein_selector.domain.docking.store import (
    load_ligand_ccd_codes,
    load_ligand_context,
    load_ligand_smiles,
    load_meeko_parameterization,
    upsert_ligand_context,
)
from protein_selector.domain.structural_biology.models import CandidateEntry
from protein_selector.nodes.base import Node, NodeContext, NodeResult

logger = logging.getLogger(__name__)


class CheckLigandContextOutputs(TypedDict):
    """Output sockets of :class:`CheckLigandContextNode` -- keys checked statically."""

    # A receipt, not a payload: the rows live in the store (§15b).
    ligand_context: int


class CheckLigandContextNode(Node):
    """The card (PLAN.md §35): what this node needs, what it gives.

    A wire exists wherever a socket name here matches one on another node.
    Nothing outside these sockets may be read -- ``ctx.get`` refuses the rest.
    """

    name = "check_ligand_context"
    granularity = Granularity.BATCH
    inputs = (
        collection("survivors"),
        table("ligand_ccd_codes"),
        table("meeko_parameterization"),
        table("ligand_smiles"),
    )
    outputs = (table("ligand_context"),)
    needs_network = True

    def run(self, ctx: NodeContext) -> NodeResult[CheckLigandContextOutputs]:
        """Delegates to the module function, which stays the implementation."""
        run = check_ligand_context(
            ctx.get("survivors"),
            ctx.config or LigandContextConfig(),
            ctx.db_path,
            force_refresh=ctx.force_refresh,
        )
        return NodeResult(outputs=CheckLigandContextOutputs(ligand_context=len(run.stored)))


@dataclass
class LigandContextRun:
    """What one :func:`check_ligand_context` call did.

    ``stored`` holds the verdicts it wrote; ``failed`` names the candidates whose check
    failed and so have no new row. ``stale`` names the candidates left with a row that
    judged a ligand other than today's pick. ``skipped`` counts rows reused, ``no_ligand``
    the candidates with no dockable ligand, which are never checked.
    """

    stored: list[LigandContextResult] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    skipped: int = 0
    no_ligand: int = 0


def _fetch_smiles(ccd_codes: list[str]) -> dict[str, str | None]:
    # Imported here: the ligands module pulls in rcsbapi, which goes online at import time.
    from protein_selector.domain.docking.ligands import fetch_smiles_for_ccd_codes

    return fetch_smiles_for_ccd_codes(ccd_codes)


def docking_picks(pdb_ids: list[str], db_path) -> dict[str, str]:
    """The ligand the docking step would pick for each candidate that has one.

    Requires the `validate` extra (rdkit), like ``pick_largest_organic_ligand`` itself.
    """
    ccd_codes = load_ligand_ccd_codes(db_path)
    meeko = load_meeko_parameterization(db_path)
    smiles = load_ligand_smiles(db_path)
    missing = sorted({
        code for pdb_id in pdb_ids for code in ccd_codes.get(pdb_id, [])
        if code not in smiles and is_dockable_ligand_code(code, meeko)
    })
    if missing:
        smiles = {**smiles, **_fetch_smiles(missing)}
    picks = {}
    for pdb_id in pdb_ids:
        ccd_code = pick_largest_organic_ligand(ccd_codes.get(pdb_id, []), meeko, smiles)
        if ccd_code is not None:
            picks[pdb_id] = ccd_code
    return picks


def check_ligand_context(
    entries: list[CandidateEntry],
    config: LigandContextConfig,
    db_path,
    force_refresh: bool = False,
) -> LigandContextRun:
    """Check every candidate whose docking ligand has no stored verdict; persist each."""
    run = LigandContextRun()
    if not config.enabled:
        return run
    picks = docking_picks([e.pdb_id for e in entries], db_path)
    run.no_ligand = len(entries) - len(picks)
    stored = load_ligand_context(db_path)
    reusable = {} if force_refresh else stored
    pending = {p: c for p, c in picks.items()
               if p not in reusable or reusable[p].ccd_code != c}
    run.skipped = len(picks) - len(pending)
    if pending:
        _check_all(pending, config, db_path, run)

    written = {r.pdb_id for r in run.stored}
    run.stale = sorted(
        e.pdb_id for e in entries
        if e.pdb_id in stored and e.pdb_id not in written
        and stored[e.pdb_id].ccd_code != picks.get(e.pdb_id)
    )
    logger.info(
        "🧲 ligand context: %d/%d already stored (⏭️), %d new (%d held by a metal or a "
        "bond), %d failed, %d without a dockable ligand, %d stored rows judged another "
        "ligand",
        run.skipped,
        len(entries),
        len(run.stored),
        sum(1 for r in run.stored if not r.self_contained),
        len(run.failed),
        run.no_ligand,
        len(run.stale),
    )
    return run


def _check_all(
    pending: dict[str, str], config: LigandContextConfig, db_path, run: LigandContextRun
) -> None:
    pool = ThreadPoolExecutor(max_workers=max(1, config.max_workers))
    futures = {pool.submit(find_ligand_context, pdb_id, ccd_code): pdb_id
               for pdb_id, ccd_code in pending.items()}
    handled: set[Future] = set()
    try:
        for future in as_completed(futures):
            handled.add(future)
            _record(future, futures[future], db_path, run)
    except BaseException:
        # A bug or an interrupt, not a failed check: start nothing new, let the checks
        # already running finish, and keep what they found before re-raising.
        pool.shutdown(wait=True, cancel_futures=True)
        for future, pdb_id in futures.items():
            if future in handled or future.cancelled():
                continue
            try:
                _record(future, pdb_id, db_path, run)
            except Exception:
                logger.exception("could not keep the finished ligand-context check for %s",
                                 pdb_id)
        raise
    pool.shutdown(wait=True)


def _record(
    future: Future[LigandContextResult], pdb_id: str, db_path, run: LigandContextRun
) -> None:
    """Persist one finished check, or log its failure and persist nothing."""
    try:
        result = future.result()
    except LigandContextError as exc:
        run.failed.append(pdb_id)
        logger.warning("⚠️ ligand-context check failed for %s, retried next run: %s",
                       pdb_id, exc)
        return
    upsert_ligand_context([result], db_path=db_path)
    run.stored.append(result)
    logger.debug("ligand context %s %s: %s %s %s", pdb_id, result.ccd_code,
                 "self-contained" if result.self_contained else "held",
                 result.links, result.metal_contacts)

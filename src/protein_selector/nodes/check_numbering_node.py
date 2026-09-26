"""Residue numbering per candidate: is every residue numbered as UniProt numbers it?

A recorded check like ``align_relatives``, not a validator: it writes one
``residue_numbering`` row per candidate and never a ``validation`` row. The pipeline
filters nothing on it; the report carries the verdict for whoever builds a course list.

Only candidates with a UniProt accession are checked: the rule compares the file's
numbers with UniProt's, so a candidate without one gets no row and is not counted as
pending (``plan_pipeline``).

Incremental: a candidate with a stored row is not checked again unless ``force_refresh``.
The checks run on a small bounded thread pool (``ResidueNumberingConfig.max_workers``) to
stay polite to EBI, and each row is persisted the moment its check finishes, from this
thread rather than the workers, so a crash partway through loses no finished work. A check
that fails (SIFTS or UniProt unreachable or unreadable: the domain raises
``NumberingCheckError`` for all of them) is logged and persists **no row**, which leaves the
candidate pending for the next run. Any other exception is a bug: no further check is
started, the running ones finish and are stored, and the exception propagates.
"""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import TypedDict

from protein_selector.core.config import ResidueNumberingConfig
from protein_selector.core.registry import Granularity, collection, table
from protein_selector.domain.bioinformatics.models import NumberingCheckError
from protein_selector.domain.bioinformatics.residue_numbering import (
    ResidueNumberingResult,
    find_residue_numbering,
)
from protein_selector.domain.bioinformatics.store import (
    load_residue_numbering,
    upsert_residue_numbering,
)
from protein_selector.domain.structural_biology.models import CandidateEntry
from protein_selector.nodes.base import Node, NodeContext, NodeResult

logger = logging.getLogger(__name__)


class CheckNumberingOutputs(TypedDict):
    """Output sockets of :class:`CheckNumberingNode` -- keys checked statically."""

    # A receipt, not a payload: the rows live in the store (§15b).
    residue_numbering: int


class CheckNumberingNode(Node):
    """The card (PLAN.md §35): what this node needs, what it gives.

    A wire exists wherever a socket name here matches one on another node.
    Nothing outside these sockets may be read -- ``ctx.get`` refuses the rest.
    """

    name = "check_numbering"
    granularity = Granularity.BATCH
    inputs = (collection("survivors"), table("candidates"),)
    outputs = (table("residue_numbering"),)
    needs_network = True

    def run(self, ctx: NodeContext) -> NodeResult[CheckNumberingOutputs]:
        """Delegates to the module function, which stays the implementation."""
        run = check_numbering(
            ctx.get("survivors"),
            ctx.config or ResidueNumberingConfig(),
            ctx.db_path,
            force_refresh=ctx.force_refresh,
        )
        return NodeResult(outputs=CheckNumberingOutputs(residue_numbering=len(run.stored)))


@dataclass
class NumberingRun:
    """What one :func:`check_numbering` call did.

    ``stored`` holds the verdicts it wrote. ``failed`` names the candidates whose check
    failed and so have no row; they stay pending for the next run. ``skipped`` counts
    candidates that already had a row, ``no_accession`` those with no UniProt accession,
    which are never checked.
    """

    stored: list[ResidueNumberingResult] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: int = 0
    no_accession: int = 0


def check_numbering(
    entries: list[CandidateEntry],
    config: ResidueNumberingConfig,
    db_path,
    force_refresh: bool = False,
) -> NumberingRun:
    """Check every candidate without a stored verdict; persist each as it finishes."""
    run = NumberingRun()
    if not config.enabled:
        return run
    checkable = [e for e in entries if e.uniprot_ids]
    run.no_accession = len(entries) - len(checkable)
    stored = {} if force_refresh else load_residue_numbering(db_path)
    pending = [e for e in checkable if e.pdb_id not in stored]
    run.skipped = len(checkable) - len(pending)
    if pending:
        _check_all(pending, config, db_path, run)

    logger.info(
        "🔢 residue numbering: %d/%d already stored (⏭️), %d new (%d not numbered as "
        "UniProt), %d failed, %d without a UniProt accession",
        run.skipped,
        len(entries),
        len(run.stored),
        sum(1 for r in run.stored if not r.uniprot_numbered),
        len(run.failed),
        run.no_accession,
    )
    return run


def _check_all(
    pending: list[CandidateEntry],
    config: ResidueNumberingConfig,
    db_path,
    run: NumberingRun,
) -> None:
    pool = ThreadPoolExecutor(max_workers=max(1, config.max_workers))
    futures = {pool.submit(find_residue_numbering, entry.pdb_id): entry.pdb_id
               for entry in pending}
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
                logger.exception("could not keep the finished numbering check for %s", pdb_id)
        raise
    pool.shutdown(wait=True)


def _record(
    future: Future[ResidueNumberingResult], pdb_id: str, db_path, run: NumberingRun
) -> None:
    """Persist one finished check, or log its failure and persist nothing."""
    try:
        result = future.result()
    except NumberingCheckError as exc:
        run.failed.append(pdb_id)
        logger.warning("⚠️ numbering check failed for %s, retried next run: %s", pdb_id, exc)
        return
    upsert_residue_numbering([result], db_path=db_path)
    run.stored.append(result)
    logger.debug("numbering %s: %s %s", pdb_id,
                 "UniProt" if result.uniprot_numbered else "not UniProt", result.problems)

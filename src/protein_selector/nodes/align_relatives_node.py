"""Sequence relatives per candidate: its UniProt chain vs. Swiss-Prot, FAMSA, 95% (§40).

An annotation like ``count_literature``, not a validator: it writes one
``sequence_relatives`` row per candidate and never a ``validation`` row. Nothing reads
that row to exclude, rank or gate a candidate.

Only candidates with a UniProt accession are searched: the query is the UniProt chain the
structure lies in, found through the first accession (the one ``lookup_alphafold`` uses).
A candidate without one gets no row and is not counted as pending (``plan_pipeline``).

Incremental: a candidate is searched again only when its stored row was computed for
another accession than its current first one, or against another database or grouping
identity (``is_reusable``, the predicate ``plan_pipeline`` counts pending work with), or
on ``force_refresh``. A change of ``min_relatives`` alone
searches nothing: ``passed`` is recomputed from the stored count and the row upserted. The
searches run on a small bounded thread pool
(``SequenceRelativesConfig.max_workers``) to stay polite to EBI, and each candidate's row
is persisted the moment its search finishes, from this thread rather than the workers, so
a crash partway through loses no finished work. A search that fails (network, timeout,
HTTP error, an unreadable answer: the domain raises ``SequenceSearchError`` for all of
them) is logged and persists **no row**, which leaves the candidate pending for the next
run -- the same "a failure persists nothing" rule the rest of the store follows. A search
that succeeds with zero significant hits is a real answer and does get its row. Any other
exception is a bug: no further search is started, the running ones are allowed to finish
and are stored, and the exception propagates.
"""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import TypedDict

from protein_selector.core.config import SequenceRelativesConfig
from protein_selector.core.registry import Granularity, collection, table
from protein_selector.domain.bioinformatics.models import SequenceSearchError
from protein_selector.domain.bioinformatics.sequence_relatives import (
    SequenceRelativesResult,
    find_sequence_relatives,
    is_reusable,
    with_min_relatives,
)
from protein_selector.domain.bioinformatics.store import (
    load_sequence_relatives,
    upsert_sequence_relatives,
)
from protein_selector.domain.structural_biology.models import CandidateEntry
from protein_selector.nodes.base import Node, NodeContext, NodeResult

logger = logging.getLogger(__name__)


class AlignRelativesOutputs(TypedDict):
    """Output sockets of :class:`AlignRelativesNode` -- keys checked statically."""

    # A receipt, not a payload: the rows live in the store (§15b). Counts every row
    # written, searched or re-flagged.
    sequence_relatives: int


class AlignRelativesNode(Node):
    """The card (PLAN.md §35): what this node needs, what it gives.

    A wire exists wherever a socket name here matches one on another node.
    Nothing outside these sockets may be read -- ``ctx.get`` refuses the rest.
    """

    name = "align_relatives"
    granularity = Granularity.BATCH
    inputs = (collection("survivors"), table("candidates"),)
    outputs = (table("sequence_relatives"),)
    needs_network = True

    def run(self, ctx: NodeContext) -> NodeResult[AlignRelativesOutputs]:
        """Delegates to the module function, which stays the implementation."""
        run = align_relatives(
            ctx.get("survivors"),
            ctx.config or SequenceRelativesConfig(),
            ctx.db_path,
            force_refresh=ctx.force_refresh,
        )
        written = len(run.stored) + len(run.reflagged)
        return NodeResult(outputs=AlignRelativesOutputs(sequence_relatives=written))


@dataclass
class RelativesRun:
    """What one :func:`align_relatives` call did.

    ``stored`` holds the rows its searches wrote, ``reflagged`` the stored rows it
    rewrote under a new ``min_relatives`` without searching. ``failed`` names the
    candidates whose search failed and so have no row; they stay pending for the next
    run. ``skipped`` counts candidates whose stored row already matched their current
    accession and settings and was left alone, ``no_accession`` those with no UniProt
    accession, which are never searched.
    """

    stored: list[SequenceRelativesResult] = field(default_factory=list)
    reflagged: list[SequenceRelativesResult] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped: int = 0
    no_accession: int = 0


def align_relatives(
    entries: list[CandidateEntry],
    config: SequenceRelativesConfig,
    db_path,
    force_refresh: bool = False,
) -> RelativesRun:
    """Search every candidate without a current row; persist each row as its search finishes."""
    run = RelativesRun()
    if not config.enabled:
        return run
    searchable = [e for e in entries if e.uniprot_ids]
    run.no_accession = len(entries) - len(searchable)
    stored = {} if force_refresh else load_sequence_relatives(db_path)
    pending: list[CandidateEntry] = []
    for entry in searchable:
        row = stored.get(entry.pdb_id)
        if is_reusable(row, entry.uniprot_ids[0], config.database, config.max_identity):
            if row.min_relatives != config.min_relatives:
                run.reflagged.append(with_min_relatives(row, config.min_relatives))
        else:
            pending.append(entry)
    if run.reflagged:
        upsert_sequence_relatives(run.reflagged, db_path=db_path)
    run.skipped = len(searchable) - len(pending) - len(run.reflagged)
    if pending:
        _search_all(pending, config, db_path, run)

    logger.info(
        "🧬 sequence relatives: %d/%d already stored (⏭️), %d re-flagged at %d relatives "
        "without a search, %d new (%d below %d relatives), %d failed, "
        "%d without a UniProt accession",
        run.skipped,
        len(entries),
        len(run.reflagged),
        config.min_relatives,
        len(run.stored),
        sum(1 for r in run.stored if not r.passed),
        config.min_relatives,
        len(run.failed),
        run.no_accession,
    )
    return run


def _search_all(
    pending: list[CandidateEntry],
    config: SequenceRelativesConfig,
    db_path,
    run: RelativesRun,
) -> None:
    pool = ThreadPoolExecutor(max_workers=max(1, config.max_workers))
    futures = {pool.submit(_search, entry, config): entry.pdb_id for entry in pending}
    handled: set[Future] = set()
    try:
        for future in as_completed(futures):
            handled.add(future)
            _record(future, futures[future], db_path, run)
    except BaseException:
        # A bug or an interrupt, not a failed search: start nothing new, let the searches
        # already running finish, and keep what they found before re-raising.
        pool.shutdown(wait=True, cancel_futures=True)
        for future, pdb_id in futures.items():
            if future in handled or future.cancelled():
                continue
            try:
                _record(future, pdb_id, db_path, run)
            except Exception:
                logger.exception("could not keep the finished relatives search for %s", pdb_id)
        raise
    pool.shutdown(wait=True)


def _record(
    future: Future[SequenceRelativesResult], pdb_id: str, db_path, run: RelativesRun
) -> None:
    """Persist one finished search, or log its failure and persist nothing."""
    try:
        result = future.result()
    except SequenceSearchError as exc:
        run.failed.append(pdb_id)
        logger.warning("⚠️ relatives search failed for %s, retried next run: %s", pdb_id, exc)
        return
    upsert_sequence_relatives([result], db_path=db_path)
    run.stored.append(result)
    logger.debug(
        "relatives %s (%s %d-%d): %d hits -> %d relatives",
        pdb_id, result.uniprot_accession, result.chain_start, result.chain_end,
        result.n_hits, result.n_relatives,
    )


def _search(entry: CandidateEntry, config: SequenceRelativesConfig) -> SequenceRelativesResult:
    """One candidate's search; the domain opens its own HTTP session for it."""
    return find_sequence_relatives(
        entry.pdb_id,
        entry.uniprot_ids[0],
        database=config.database,
        max_identity=config.max_identity,
        min_relatives=config.min_relatives,
        famsa_threads=config.famsa_threads,
    )

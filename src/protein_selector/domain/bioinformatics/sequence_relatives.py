"""Sequence relatives of a candidate: its UniProt chain, phmmer, FAMSA, grouped at 95%.

An annotation, not a validator (PLAN.md §40). For each candidate it answers one question:
*how many genuinely different, significantly similar proteins exist for this one?* It
produces no ``ValidationResult``, no ``FailureMode`` and no difficulty score, and it fills
no exercise slot. Like the literature count, it is a fact about the candidate that the
report carries alongside the validators' verdicts. Nothing may filter or rank on it.

This module is the pure logic plus the one entry point that composes the adapters, one
per external tool (PLAN.md §34c):

* ``uniprot_entry``: the UniProt sequence and its "Chain" features, the mature chains.
* ``rcsb_uniprot_regions``: the UniProt range the PDB entity covers.
* ``ebi_hmmer``: phmmer on EBI's HMMER web API and the hits' full-length sequences.
* ``famsa``: the multiple sequence alignment.

Four steps, each checked against the live services before this was written:

1. **The query is the full protein, not the PDB construct.** The candidate's first
   UniProt accession (the one ``lookup_alphafold`` uses) gives the UniProt sequence and
   its chains. ``choose_chain`` takes the Chain feature overlapping the structure's range
   most; on a tie the shortest, because a polyprotein lists the whole precursor and every
   cleaved product (HIV-1 protease, 2QD8, resolves to "Protease" 501-599, not "Gag-Pol
   polyprotein" 2-1447). With no Chain feature the whole UniProt sequence is the query. A
   structure of one domain still searches with its whole chain; ``structure_coverage``
   records how much of the chain the structure covers, so domain cases stay visible
   rather than filtered.

2. **The search.** phmmer against ``database``; the significant hits are fetched in full
   length, in rank order, best first.

3. **The alignment.** ``summarise_relatives`` aligns the query and every full-length hit
   with FAMSA, rows back in input order.

4. **The grouping.** Only the columns where the query has a residue are kept, so the
   work scales with the query's length, not the alignment's width. ``filter_redundant``
   walks the hits best first with the query already kept: a hit is kept only if its
   identity to *every* kept sequence is below ``max_identity``. Identity counts the
   query columns where both sequences have a residue.

``find_sequence_relatives`` is the one entry point callers need, and its failure contract
is a single exception: anything that stops it producing a trustworthy count (transport,
HTTP status, deadline, an unreadable answer) raises ``SequenceSearchError``, with the
original exception as its cause. Anything else escaping it is a bug. It imports the three
network adapters, and ``requests`` with them, when it is called: the store and the report
import this module for ``SequenceRelativesResult`` and must not load an HTTP stack to read
a row.

Deliberately no family, coverage or identity-floor filter on the hits: tubulins among the
relatives of FtsZ are expected, since they share its GTPase domain.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, TypeGuard

import numpy as np

from protein_selector.domain.bioinformatics.famsa import align_sequences
from protein_selector.domain.bioinformatics.models import (
    ChainFeature,
    PhmmerSearch,
    SequenceSearchError,
    UniProtEntry,
)

if TYPE_CHECKING:
    import requests

DEFAULT_DATABASE = "swissprot"
DEFAULT_MAX_IDENTITY = 0.95
DEFAULT_MIN_RELATIVES = 10

_GAP = ord("-")


@dataclass
class SequenceRelativesResult:
    """One candidate's row in the ``sequence_relatives`` table.

    The query is the UniProt chain ``chain_start``-``chain_end`` of ``uniprot_accession``
    (``query_length`` residues). ``uniprot_accession`` is the accession the search was
    asked for, the candidate's first as RCSB lists it, even when UniProt answers under
    another primary accession: ``is_reusable`` compares it with the candidate's current
    first accession. ``structure_start``/``structure_end`` are the UniProt
    positions the PDB entity covers and ``structure_coverage`` the fraction of the chain
    inside them; all three are ``None`` when RCSB aligns no entity to the accession.
    ``n_hits`` counts the significant phmmer hits, ``n_relatives`` the ones left after
    grouping at ``max_identity``, never counting the query. ``alignment_columns`` is the
    width of the FAMSA alignment, ``None`` when there was nothing to align.
    ``median_identity`` is the median identity of the relatives to the query, ``None``
    when there are none. ``passed`` is ``n_relatives >= min_relatives``: a recorded flag,
    never a filter. Both thresholds are stored with the row because the counts mean
    nothing without them.
    """

    pdb_id: str
    uniprot_accession: str
    chain_start: int
    chain_end: int
    query_length: int
    structure_start: int | None
    structure_end: int | None
    structure_coverage: float | None
    database: str
    n_hits: int
    n_relatives: int
    alignment_columns: int | None
    median_identity: float | None
    max_identity: float
    min_relatives: int
    passed: bool


def is_reusable(
    row: SequenceRelativesResult | None,
    uniprot_accession: str,
    database: str,
    max_identity: float,
) -> TypeGuard[SequenceRelativesResult]:
    """Can a stored row stand for a new search of ``uniprot_accession`` under these settings?

    The row must have searched the same accession: a candidate's first accession can
    change between runs (RCSB does not keep its entities in a fixed order), and a count
    for another protein must not stand beside the new one in the report. Of the
    settings, only those that change the count decide: the database searched and the
    identity at which hits are grouped. ``min_relatives`` does not, since it only sets the
    ``passed`` flag, which ``with_min_relatives`` recomputes from the stored count without
    a search. ``align_relatives`` and ``plan_pipeline`` both decide what is pending with
    this one predicate, so the plan and the run cannot disagree.
    """
    return (
        row is not None
        and row.uniprot_accession == uniprot_accession
        and row.database == database
        and row.max_identity == max_identity
    )


def with_min_relatives(
    row: SequenceRelativesResult, min_relatives: int
) -> SequenceRelativesResult:
    """``row`` flagged against ``min_relatives``: ``passed`` recomputed, nothing searched."""
    return replace(
        row, min_relatives=min_relatives, passed=row.n_relatives >= min_relatives
    )


# ---- the query -----------------------------------------------------------------------


def merge_regions(regions: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    """Sorted, non-overlapping inclusive intervals covering the same positions."""
    merged: list[tuple[int, int]] = []
    for start, end in sorted(regions):
        if merged and start <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def covered_positions(chain: ChainFeature, regions: Iterable[tuple[int, int]]) -> int:
    """How many positions of ``chain`` fall inside ``regions``."""
    return sum(
        max(0, min(end, chain.end) - max(start, chain.start) + 1)
        for start, end in merge_regions(regions)
    )


def choose_chain(
    chains: Sequence[ChainFeature],
    regions: Sequence[tuple[int, int]],
    sequence_length: int,
) -> ChainFeature:
    """The UniProt chain the structure lies in: the query for the search.

    The chain covering most of ``regions`` (the UniProt positions the structure covers);
    on a tie the shortest, since a polyprotein lists its precursor as well as every
    cleaved product; then the lowest start. The whole sequence stands in when the entry
    has no chain, when no chain overlaps the structure at all, or when the structure's
    range is unknown and the entry has more than one chain to choose from.
    """
    whole = ChainFeature(1, sequence_length, "whole sequence")
    if not chains:
        return whole
    if not regions:
        return chains[0] if len(chains) == 1 else whole
    best = min(
        chains, key=lambda c: (-covered_positions(c, regions), c.length, c.start)
    )
    return best if covered_positions(best, regions) > 0 else whole


def select_query(
    entry: UniProtEntry, regions: Sequence[tuple[int, int]]
) -> tuple[ChainFeature, str]:
    """The chain ``choose_chain`` picks for ``entry``, and its sequence."""
    chain = choose_chain(entry.chains, regions, len(entry.sequence))
    return chain, entry.sequence[chain.start - 1 : chain.end]


def structure_coverage(
    chain: ChainFeature, regions: Sequence[tuple[int, int]]
) -> float | None:
    """Fraction of ``chain`` the structure covers; ``None`` when its range is unknown."""
    if not regions:
        return None
    return covered_positions(chain, regions) / chain.length


# ---- alignment and grouping ----------------------------------------------------------


def parse_fasta(text: str) -> list[tuple[str, str]]:
    """``(name, sequence)`` pairs in file order; the name is the header's first word."""
    records: list[tuple[str, str]] = []
    name: str | None = None
    chunks: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(">"):
            if name is not None:
                records.append((name, "".join(chunks)))
            name, chunks = (line[1:].split() or [""])[0], []
        elif name is not None:
            chunks.append(line)
    if name is not None:
        records.append((name, "".join(chunks)))
    return records


def query_columns(rows: Sequence[bytes]) -> np.ndarray:
    """The aligned rows restricted to the columns where row 0, the query, has a residue.

    Returns a ``(len(rows), query length)`` ``uint8`` matrix. Built one row at a time so
    a wide alignment (tens of thousands of columns for a multidomain family) never has
    to exist as one matrix.
    """
    query = np.frombuffer(rows[0], dtype=np.uint8)
    columns = np.flatnonzero(query != _GAP)
    matrix = np.empty((len(rows), columns.size), dtype=np.uint8)
    for i, row in enumerate(rows):
        aligned = np.frombuffer(row, dtype=np.uint8)
        if aligned.size != query.size:
            raise SequenceSearchError(
                f"aligned row {i} is {aligned.size} columns wide, the query row "
                f"{query.size}"
            )
        matrix[i] = aligned[columns]
    return matrix


def filter_redundant(
    matrix: np.ndarray, max_identity: float = DEFAULT_MAX_IDENTITY
) -> list[int]:
    """Indices (0 = first hit) of the hits kept after grouping at ``max_identity``.

    ``matrix`` is ``query_columns``' output: row 0 is the query, then the hits in rank
    order. Greedy with the query kept first: a hit survives only if its identity to
    *every* sequence kept so far is below ``max_identity``, so the query's own near-twins
    are dropped and each group of near-identical hits is represented by its best-ranked
    member. Identity counts the columns where both rows have a residue; two rows sharing
    none are no evidence of redundancy and do not block each other.
    """
    n_rows = matrix.shape[0]
    if n_rows <= 1:
        return []
    residues = matrix != _GAP
    pool = np.empty_like(matrix)
    pool_residues = np.empty_like(residues)
    pool[0], pool_residues[0] = matrix[0], residues[0]
    n_pool = 1
    kept: list[int] = []
    for index in range(1, n_rows):
        row, row_residues = matrix[index], residues[index]
        # Equal and a residue in this row implies a residue in the pooled row too.
        same = np.count_nonzero((pool[:n_pool] == row) & row_residues, axis=1)
        shared = np.count_nonzero(pool_residues[:n_pool] & row_residues, axis=1)
        fraction = np.divide(
            same, shared, out=np.zeros(n_pool, dtype=float), where=shared > 0
        )
        redundant = (shared > 0) & (fraction >= max_identity)
        if not redundant.any():
            pool[n_pool], pool_residues[n_pool] = row, row_residues
            n_pool += 1
            kept.append(index - 1)
    return kept


def identities_to_query(matrix: np.ndarray, hits: Sequence[int]) -> list[float]:
    """Identity of each listed hit (0 = first hit) to the query, over shared columns.

    A hit sharing no column with the query has no identity and is left out.
    """
    query = matrix[0]
    values = []
    for hit in hits:
        row = matrix[hit + 1]
        residues = (row != _GAP) & (query != _GAP)
        shared = int(np.count_nonzero(residues))
        if shared:
            values.append(int(np.count_nonzero((row == query) & residues)) / shared)
    return values


def summarise_relatives(
    pdb_id: str,
    entry: UniProtEntry,
    regions: Sequence[tuple[int, int]],
    search: PhmmerSearch,
    *,
    database: str = DEFAULT_DATABASE,
    max_identity: float = DEFAULT_MAX_IDENTITY,
    min_relatives: int = DEFAULT_MIN_RELATIVES,
    famsa_threads: int = 1,
    uniprot_accession: str | None = None,
) -> SequenceRelativesResult:
    """Align one finished search and turn it into the candidate's row. No network.

    ``regions`` are the UniProt ranges the structure covers, in any order; overlapping
    ranges are merged first. The row records ``uniprot_accession``, the accession the
    search was asked for, or ``entry``'s own when none is given. FAMSA runs on
    ``famsa_threads`` threads. Raises ``SequenceSearchError`` when the full-length file
    cannot describe the hits the search reported: no FASTA record at all (an HTML error
    page served with HTTP 200 must not read as "zero relatives"), or more sequences than
    ``n_hits``.
    """
    regions = merge_regions(regions)
    chain, query = select_query(entry, regions)
    relatives: list[int] = []
    identities: list[float] = []
    columns: int | None = None
    if search.n_hits > 0:
        records = parse_fasta(search.full_fasta or "")
        if not records:
            raise SequenceSearchError(
                f"{search.n_hits} hits but the full-length file holds no FASTA record"
            )
        if len(records) > search.n_hits:
            raise SequenceSearchError(
                f"full-length file holds {len(records)} sequences, search reported only "
                f"{search.n_hits}"
            )
        rows = align_sequences(
            [query, *(sequence for _, sequence in records)], threads=famsa_threads
        )
        columns = len(rows[0])
        matrix = query_columns(rows)
        if matrix.shape[1] != len(query):
            raise SequenceSearchError(
                f"aligned query has {matrix.shape[1]} residues, the chain {len(query)}"
            )
        relatives = filter_redundant(matrix, max_identity)
        identities = identities_to_query(matrix, relatives)
    return SequenceRelativesResult(
        pdb_id=pdb_id,
        uniprot_accession=uniprot_accession or entry.accession,
        chain_start=chain.start,
        chain_end=chain.end,
        query_length=len(query),
        structure_start=regions[0][0] if regions else None,
        structure_end=regions[-1][1] if regions else None,
        structure_coverage=structure_coverage(chain, regions),
        database=database,
        n_hits=search.n_hits,
        n_relatives=len(relatives),
        alignment_columns=columns,
        median_identity=statistics.median(identities) if identities else None,
        max_identity=max_identity,
        min_relatives=min_relatives,
        passed=len(relatives) >= min_relatives,
    )


# ---- the entry point -----------------------------------------------------------------


def find_sequence_relatives(
    pdb_id: str,
    uniprot_accession: str,
    *,
    database: str = DEFAULT_DATABASE,
    max_identity: float = DEFAULT_MAX_IDENTITY,
    min_relatives: int = DEFAULT_MIN_RELATIVES,
    famsa_threads: int = 1,
    session: requests.Session | None = None,
) -> SequenceRelativesResult:
    """Pick the candidate's UniProt chain, search it, align the hits, count relatives.

    The alignment runs on ``famsa_threads`` threads. Every failure of the search raises ``SequenceSearchError`` (a transport, HTTP or
    deadline failure is chained as its ``__cause__``) rather than returning a partial
    row: a caller persists nothing for a failed candidate, so it is simply searched again
    on the next run. Without a ``session`` it opens one for this search, so concurrent
    callers never share one.
    """
    import requests

    try:
        if session is None:
            with requests.Session() as own_session:
                return _find_sequence_relatives(
                    pdb_id, uniprot_accession, database, max_identity, min_relatives,
                    famsa_threads, own_session,
                )
        return _find_sequence_relatives(
            pdb_id, uniprot_accession, database, max_identity, min_relatives,
            famsa_threads, session,
        )
    except (requests.RequestException, TimeoutError) as exc:
        raise SequenceSearchError(f"{pdb_id}: {type(exc).__name__}: {exc}") from exc


def _find_sequence_relatives(
    pdb_id: str,
    uniprot_accession: str,
    database: str,
    max_identity: float,
    min_relatives: int,
    famsa_threads: int,
    session: requests.Session,
) -> SequenceRelativesResult:
    from protein_selector.domain.bioinformatics.ebi_hmmer import run_phmmer
    from protein_selector.domain.bioinformatics.rcsb_uniprot_regions import (
        fetch_structure_regions,
    )
    from protein_selector.domain.bioinformatics.uniprot_entry import fetch_uniprot_entry

    entry = fetch_uniprot_entry(uniprot_accession, session)
    regions = merge_regions(fetch_structure_regions(pdb_id, uniprot_accession, session))
    _, query = select_query(entry, regions)
    search = run_phmmer(query, database, session=session)
    return summarise_relatives(
        pdb_id,
        entry,
        regions,
        search,
        database=database,
        max_identity=max_identity,
        min_relatives=min_relatives,
        famsa_threads=famsa_threads,
        uniprot_accession=uniprot_accession,
    )

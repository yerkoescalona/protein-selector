"""Tests for protein_selector.domain.bioinformatics.sequence_relatives.

The pure logic (chain choice, coverage, the query-column matrix, the 95% redundancy
filter, the summary) runs against fixed inputs shaped like the live UniProt, RCSB and
HMMER answers: UniProt "Chain" features for a polyprotein (P03367) and for an entry with
nested chains (P00644), RCSB aligned regions, and a ``fullfasta`` file whose headers are
entry names only. The summary runs the real FAMSA (``pyfamsa``) on short sequences, which
takes milliseconds. ``find_sequence_relatives`` runs with its three network adapters
replaced, so nothing here touches the network; the adapters have their own tests.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from unittest.mock import MagicMock

import numpy as np
import pytest
import requests

from protein_selector.domain.bioinformatics import (
    ebi_hmmer,
    rcsb_uniprot_regions,
    sequence_relatives,
    uniprot_entry,
)
from protein_selector.domain.bioinformatics.models import (
    ChainFeature,
    PhmmerSearch,
    SequenceSearchError,
    UniProtEntry,
)
from protein_selector.domain.bioinformatics.sequence_relatives import (
    choose_chain,
    filter_redundant,
    find_sequence_relatives,
    identities_to_query,
    is_reusable,
    merge_regions,
    parse_fasta,
    query_columns,
    select_query,
    structure_coverage,
    summarise_relatives,
)

# P03367 (HIV-1 Gag-Pol), its Chain features as UniProt lists them (2026-09-23).
_GAG_POL_CHAINS = (
    ChainFeature(2, 1447, "Gag-Pol polyprotein"),
    ChainFeature(2, 132, "Matrix protein p17"),
    ChainFeature(133, 363, "Capsid protein p24"),
    ChainFeature(378, 432, "Nucleocapsid protein p7"),
    ChainFeature(441, 500, "p6-pol"),
    ChainFeature(501, 599, "Protease"),
    ChainFeature(600, 1159, "Reverse transcriptase/ribonuclease H"),
    ChainFeature(600, 1039, "p51 RT"),
    ChainFeature(1040, 1159, "p15"),
    ChainFeature(1160, 1447, "Integrase"),
)

# 20 residues: 95% identity is exactly one mismatch.
_QUERY = "ACDEFGHIKLMNPQRSTVWY"


def _mutate(sequence: str, positions: dict[int, str]) -> str:
    chars = list(sequence)
    for position, residue in positions.items():
        chars[position] = residue
    return "".join(chars)


_HIT_A = _mutate(_QUERY, {0: "W", 3: "W", 6: "W", 9: "W", 12: "W"})  # 75% to query
_HIT_A_TWIN = _mutate(_HIT_A, {15: "A"})  # 95% to hit A, 70% to query
_HIT_C = _mutate(_QUERY, {1: "Y", 4: "Y", 7: "Y", 10: "Y", 13: "Y", 16: "Y"})  # divergent


def _matrix(query: str, *hits: str) -> np.ndarray:
    """A query-column matrix built by hand: row 0 the query, then the hits."""
    return np.frombuffer("".join([query, *hits]).encode(), dtype=np.uint8).reshape(
        1 + len(hits), len(query)
    )


class TestChooseChain:
    def test_a_polyprotein_resolves_to_the_cleaved_chain_not_the_precursor(self):
        # 2QD8: the structure covers 501-599. The precursor overlaps as much as the
        # protease does, so the tie goes to the shorter chain.
        chain = choose_chain(_GAG_POL_CHAINS, [(501, 599)], 1447)
        assert (chain.start, chain.end, chain.description) == (501, 599, "Protease")

    def test_nested_chains_tie_to_the_shorter_one(self):
        # 3ERO: P00644 lists Nuclease B 64-231 and Nuclease A 83-231; the structure
        # covers 83-225, inside both.
        chains = (ChainFeature(64, 231, "Nuclease B"), ChainFeature(83, 231, "Nuclease A"))
        assert choose_chain(chains, [(83, 225)], 231).description == "Nuclease A"

    def test_the_largest_overlap_wins_over_a_shorter_chain(self):
        chains = (ChainFeature(1, 100, "long"), ChainFeature(101, 130, "short"))
        assert choose_chain(chains, [(60, 110)], 130).description == "long"

    def test_a_structure_across_a_cleavage_site_lies_in_the_precursor(self):
        # Protease plus the start of RT: only the precursor holds all of it.
        chain = choose_chain(_GAG_POL_CHAINS, [(590, 700)], 1447)
        assert (chain.start, chain.end) == (2, 1447)

    def test_a_domain_construct_still_searches_with_its_whole_chain(self):
        # 1O4B: the Src SH2 domain, 145-252 of a 2-536 chain.
        src = (ChainFeature(2, 536, "Proto-oncogene tyrosine-protein kinase Src"),)
        assert choose_chain(src, [(145, 252)], 536) == src[0]

    def test_no_chain_feature_means_the_whole_sequence(self):
        chain = choose_chain((), [(10, 50)], 120)
        assert (chain.start, chain.end) == (1, 120)

    def test_no_overlap_with_any_chain_means_the_whole_sequence(self):
        # e.g. a structure of the propeptide, which lies outside every mature chain.
        chain = choose_chain((ChainFeature(30, 120, "mature"),), [(1, 25)], 120)
        assert (chain.start, chain.end) == (1, 120)

    def test_an_unknown_structure_range_uses_a_lone_chain(self):
        chains = (ChainFeature(24, 142, "pilotin"),)
        assert choose_chain(chains, [], 142) == chains[0]

    def test_an_unknown_structure_range_with_several_chains_means_the_whole_sequence(self):
        chain = choose_chain(_GAG_POL_CHAINS, [], 1447)
        assert (chain.start, chain.end) == (1, 1447)


class TestStructureCoverage:
    def test_a_domain_construct_covers_a_fraction_of_its_chain(self):
        src = ChainFeature(2, 536)
        assert structure_coverage(src, [(145, 252)]) == pytest.approx(108 / 535)

    def test_a_whole_chain_is_covered_completely(self):
        assert structure_coverage(ChainFeature(501, 599), [(501, 599)]) == 1.0

    def test_only_positions_inside_the_chain_count(self):
        assert structure_coverage(ChainFeature(10, 19), [(1, 14)]) == pytest.approx(0.5)

    def test_overlapping_regions_are_not_counted_twice(self):
        assert merge_regions([(5, 10), (1, 6), (12, 12), (11, 11)]) == [(1, 12)]
        assert structure_coverage(ChainFeature(1, 20), [(1, 10), (5, 10)]) == 0.5

    def test_an_unknown_range_has_no_coverage(self):
        assert structure_coverage(ChainFeature(1, 20), []) is None


class TestParseFasta:
    def test_fullfasta_shaped_records_in_file_order(self):
        text = ">FTSZ1_METJA\nMKF\nVKE\n\n>TBA_PLAFK extra words\nMRE\n"
        assert parse_fasta(text) == [("FTSZ1_METJA", "MKFVKE"), ("TBA_PLAFK", "MRE")]

    def test_text_before_the_first_header_is_ignored(self):
        assert parse_fasta("junk\n>A\nAC\n") == [("A", "AC")]


class TestQueryColumns:
    def test_only_the_columns_where_the_query_has_a_residue_are_kept(self):
        rows = [b"A-CD-E", b"AKC-QE", b"--CDWE"]
        matrix = query_columns(rows)
        assert [bytes(row).decode() for row in matrix] == ["ACDE", "AC-E", "-CDE"]

    def test_ragged_rows_raise(self):
        with pytest.raises(SequenceSearchError, match="columns wide"):
            query_columns([b"ACD", b"AC"])


class TestFilterRedundant:
    def test_the_query_goes_in_first_so_its_own_twin_is_dropped(self):
        assert filter_redundant(_matrix(_QUERY, _QUERY, _HIT_A)) == [1]

    def test_a_95_percent_twin_of_a_kept_hit_is_dropped(self):
        assert filter_redundant(_matrix(_QUERY, _HIT_A, _HIT_A_TWIN, _HIT_C)) == [0, 2]

    def test_below_95_percent_is_kept(self):
        near = _mutate(_HIT_A, {15: "A", 16: "A"})  # 90% to hit A
        assert filter_redundant(_matrix(_QUERY, _HIT_A, near)) == [0, 1]

    def test_rank_order_decides_which_member_represents_a_group(self):
        assert filter_redundant(_matrix(_QUERY, _HIT_A_TWIN, _HIT_A)) == [0]

    def test_gaps_do_not_dilute_identity(self):
        # Identical to hit A wherever it has a residue: 100% over 10 shared columns,
        # not 50% over 20, so it is redundant with A.
        fragment = _HIT_A[:10] + "-" * 10
        assert filter_redundant(_matrix(_QUERY, _HIT_A, fragment)) == [0]

    def test_rows_sharing_no_column_do_not_block_each_other(self):
        left, right = "-" * 20, "-" * 20
        assert filter_redundant(_matrix(_QUERY, _HIT_A, left, right)) == [0, 1, 2]

    def test_the_threshold_is_a_parameter(self):
        matrix = _matrix(_QUERY, _HIT_A, _HIT_A_TWIN)
        assert filter_redundant(matrix, max_identity=0.99) == [0, 1]

    def test_no_hits_keeps_nothing(self):
        assert filter_redundant(_matrix(_QUERY)) == []


class TestIdentitiesToQuery:
    def test_identity_over_the_columns_both_have_a_residue(self):
        matrix = _matrix(_QUERY, _HIT_A, _HIT_C, _QUERY[:10] + "-" * 10, "-" * 20)
        values = identities_to_query(matrix, [0, 1, 2, 3])
        assert values == pytest.approx([0.75, 0.70, 1.0])  # the empty row has none


def _entry(sequence=_QUERY, chains=(), accession="P12345"):
    return UniProtEntry(accession=accession, sequence=sequence, chains=tuple(chains))


class TestSummariseRelatives:
    def test_zero_hits_is_a_real_row_that_fails(self):
        result = summarise_relatives(
            "1ABC", _entry(), [(1, 20)], PhmmerSearch(job_id="j", n_hits=0)
        )
        assert (result.n_hits, result.n_relatives, result.passed) == (0, 0, False)
        assert result.alignment_columns is None and result.median_identity is None
        assert (result.chain_start, result.chain_end, result.query_length) == (1, 20, 20)
        assert result.structure_coverage == 1.0

    def test_counts_relatives_excluding_the_query_through_a_real_alignment(self):
        full = "".join(
            f">HIT{i}_X\n{sequence}\n"
            for i, sequence in enumerate([_QUERY, _HIT_A, _HIT_A_TWIN, _HIT_C])
        )
        result = summarise_relatives(
            "1ABC", _entry(), [(1, 20)], PhmmerSearch("j", 4, full), min_relatives=2
        )
        assert result.n_hits == 4
        assert result.n_relatives == 2  # the query's twin and hit A's twin are gone
        assert result.passed is True
        assert result.alignment_columns == 20
        assert result.median_identity == pytest.approx((0.75 + 0.70) / 2)
        assert (result.max_identity, result.min_relatives) == (0.95, 2)

    def test_the_query_is_the_chosen_chain_and_coverage_is_recorded(self):
        # A 30-residue entry whose chain is 6-25; the structure covers 6-15 of it.
        sequence = "MMMMM" + _QUERY + "KKKKK"
        entry = _entry(sequence, [ChainFeature(1, 30, "precursor"),
                                  ChainFeature(6, 25, "mature")])
        full = f">HIT_A\nGGG{_HIT_A}GGG\n"
        result = summarise_relatives(
            "1ABC", entry, [(6, 15)], PhmmerSearch("j", 1, full), min_relatives=1
        )
        assert (result.chain_start, result.chain_end, result.query_length) == (6, 25, 20)
        assert (result.structure_start, result.structure_end) == (6, 15)
        assert result.structure_coverage == pytest.approx(0.5)
        assert result.n_relatives == 1
        assert result.median_identity == pytest.approx(0.75)

    def test_an_unknown_structure_range_is_recorded_as_none(self):
        result = summarise_relatives("1ABC", _entry(), [], PhmmerSearch("j", 0))
        assert (result.structure_start, result.structure_end) == (None, None)
        assert result.structure_coverage is None

    def test_more_sequences_than_reported_raises(self):
        full = f">A_X\n{_HIT_A}\n>C_X\n{_HIT_C}\n"
        with pytest.raises(SequenceSearchError, match="search reported only 1"):
            summarise_relatives("1ABC", _entry(), [], PhmmerSearch("j", 1, full))

    def test_a_body_with_no_fasta_record_raises(self):
        # e.g. an HTML page served with HTTP 200: never read as "zero relatives".
        with pytest.raises(SequenceSearchError, match="no FASTA record"):
            summarise_relatives(
                "1ABC", _entry(), [],
                PhmmerSearch("j", 3, "<html><body>Service unavailable</body></html>"),
            )

    def test_overlapping_regions_in_any_order_are_merged_first(self):
        # The RCSB adapter lists every aligned region of every entity as given.
        result = summarise_relatives(
            "1ABC", _entry(), [(12, 20), (1, 6), (5, 10)], PhmmerSearch("j", 0)
        )
        assert (result.structure_start, result.structure_end) == (1, 20)
        assert result.structure_coverage == pytest.approx(19 / 20)

    def test_the_row_records_the_accession_it_was_asked_for(self):
        # UniProt may answer a secondary accession under its primary one.
        result = summarise_relatives(
            "1ABC", _entry(accession="P12345"), [], PhmmerSearch("j", 0),
            uniprot_accession="Q99999",
        )
        assert result.uniprot_accession == "Q99999"

    def test_without_an_accession_the_row_records_the_entrys_own(self):
        result = summarise_relatives("1ABC", _entry(), [], PhmmerSearch("j", 0))
        assert result.uniprot_accession == "P12345"

    def test_select_query_cuts_the_chain_out_of_the_sequence(self):
        entry = _entry("MMMMM" + _QUERY, [ChainFeature(6, 25, "mature")])
        chain, query = select_query(entry, [(6, 25)])
        assert (chain.start, query) == (6, _QUERY)


def _stub_lookups(monkeypatch, entry, regions):
    monkeypatch.setattr(
        uniprot_entry, "fetch_uniprot_entry", lambda accession, session=None: entry
    )
    monkeypatch.setattr(
        rcsb_uniprot_regions,
        "fetch_structure_regions",
        lambda pdb_id, accession, session=None: regions,
    )


class TestFindSequenceRelatives:
    @pytest.mark.parametrize(
        "error",
        [
            requests.ConnectionError("network down"),
            requests.HTTPError("HTTP 503"),
            requests.Timeout("read timed out"),
            TimeoutError("phmmer job j not ready before the deadline"),
        ],
        ids=["network", "http", "request-timeout", "deadline"],
    )
    def test_every_search_failure_is_one_exception_type(self, monkeypatch, error):
        # The caller's whole failure contract: one type, the cause kept for the log.
        _stub_lookups(monkeypatch, _entry(), [(1, 20)])

        def failing_phmmer(sequence, database, **kwargs):
            raise error

        monkeypatch.setattr(ebi_hmmer, "run_phmmer", failing_phmmer)
        with pytest.raises(SequenceSearchError, match="1ABC") as caught:
            find_sequence_relatives("1ABC", "P12345", session=MagicMock())
        assert caught.value.__cause__ is error

    def test_a_failed_lookup_is_the_same_exception_type(self, monkeypatch):
        def failing_uniprot(accession, session=None):
            raise requests.ConnectionError("UniProt unreachable")

        monkeypatch.setattr(uniprot_entry, "fetch_uniprot_entry", failing_uniprot)
        with pytest.raises(SequenceSearchError, match="ConnectionError"):
            find_sequence_relatives("1ABC", "P12345", session=MagicMock())

    def test_without_a_session_it_opens_and_closes_its_own(self, monkeypatch):
        opened = []

        class _Session:
            closed = False

            def __enter__(self):
                opened.append(self)
                return self

            def __exit__(self, *exc_info):
                self.closed = True

        monkeypatch.setattr(requests, "Session", _Session)
        _stub_lookups(monkeypatch, _entry(), [(1, 20)])
        used = []
        monkeypatch.setattr(
            ebi_hmmer, "run_phmmer",
            lambda sequence, database, session=None: used.append(session)
            or PhmmerSearch("j", 0),
        )
        find_sequence_relatives("1ABC", "P12345")
        assert len(opened) == 1 and used == opened and opened[0].closed

    def test_searches_the_chain_the_structure_lies_in(self, monkeypatch):
        # 2QD8-shaped: a polyprotein whose structure covers only the protease.
        sequence = "".join("ACDEFGHIKLMNPQRSTVWY"[i % 20] for i in range(1447))
        _stub_lookups(
            monkeypatch, _entry(sequence, _GAG_POL_CHAINS, "P03367"), [(501, 599)]
        )
        searched = {}

        def fake_phmmer(query, database, **kwargs):
            searched["args"] = (query, database)
            return PhmmerSearch("j", 0)

        monkeypatch.setattr(ebi_hmmer, "run_phmmer", fake_phmmer)
        result = find_sequence_relatives("2QD8", "P03367", database="swissprot")
        assert searched["args"] == (sequence[500:599], "swissprot")
        assert (result.uniprot_accession, result.chain_start, result.chain_end) == (
            "P03367", 501, 599,
        )
        assert (result.query_length, result.structure_coverage) == (99, 1.0)
        assert (result.n_hits, result.passed) == (0, False)

    def test_the_row_keeps_the_requested_accession_not_uniprots_primary(
        self, monkeypatch
    ):
        # The candidate's accession as RCSB lists it can be a secondary one. The row must
        # carry it, or ``is_reusable`` would never match it and every run would search
        # the candidate again.
        _stub_lookups(monkeypatch, _entry(accession="P12345"), [(1, 20)])
        monkeypatch.setattr(
            ebi_hmmer, "run_phmmer",
            lambda sequence, database, session=None: PhmmerSearch("j", 0),
        )
        result = find_sequence_relatives("1ABC", "Q99999", session=MagicMock())
        assert result.uniprot_accession == "Q99999"
        assert is_reusable(result, "Q99999", "swissprot", 0.95)

    def test_the_structure_regions_are_merged_before_use(self, monkeypatch):
        _stub_lookups(monkeypatch, _entry(), [(10, 20), (1, 12)])
        monkeypatch.setattr(
            ebi_hmmer, "run_phmmer",
            lambda sequence, database, session=None: PhmmerSearch("j", 0),
        )
        result = find_sequence_relatives("1ABC", "P12345", session=MagicMock())
        assert (result.structure_start, result.structure_end) == (1, 20)
        assert result.structure_coverage == 1.0

    def test_the_famsa_thread_count_reaches_the_alignment(self, monkeypatch):
        _stub_lookups(monkeypatch, _entry(), [(1, 20)])
        monkeypatch.setattr(
            ebi_hmmer, "run_phmmer",
            lambda sequence, database, session=None: PhmmerSearch(
                "j", 1, f">A_X\n{_HIT_A}\n"
            ),
        )
        seen = []
        real_align = sequence_relatives.align_sequences

        def recording_align(sequences, threads=1):
            seen.append(threads)
            return real_align(sequences, threads=threads)

        monkeypatch.setattr(sequence_relatives, "align_sequences", recording_align)
        find_sequence_relatives("1ABC", "P12345", famsa_threads=3, session=MagicMock())
        assert seen == [3]


class TestIsReusable:
    @staticmethod
    def _row(**changes):
        row = summarise_relatives("1ABC", _entry(), [(1, 20)], PhmmerSearch("j", 0))
        return replace(row, **changes)

    def test_a_row_for_the_same_accession_and_settings_is_reused(self):
        assert is_reusable(self._row(), "P12345", "swissprot", 0.95)

    def test_no_row_is_not_reusable(self):
        assert not is_reusable(None, "P12345", "swissprot", 0.95)

    def test_a_row_for_another_accession_is_not_reused(self):
        # The candidate's first accession changed: the count belongs to another protein.
        assert not is_reusable(self._row(), "P99999", "swissprot", 0.95)

    @pytest.mark.parametrize(
        "database,max_identity", [("refprot", 0.95), ("swissprot", 0.9)],
        ids=["database", "max_identity"],
    )
    def test_a_row_counted_under_other_settings_is_not_reused(
        self, database, max_identity
    ):
        assert not is_reusable(self._row(), "P12345", database, max_identity)

    def test_min_relatives_does_not_decide(self):
        # It only sets the passed flag, which is recomputed without a search.
        assert is_reusable(self._row(min_relatives=3), "P12345", "swissprot", 0.95)


def test_importing_the_logic_loads_no_http_stack_and_no_famsa():
    # The store and the report import this module for SequenceRelativesResult, so
    # reading a row must not need requests (or the network adapters) or pyfamsa.
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; "
         "import protein_selector.domain.bioinformatics.sequence_relatives; "
         "import protein_selector.domain.bioinformatics.store; "
         "loaded = {'requests', 'pyfamsa'} & set(sys.modules); "
         "assert not loaded, loaded; print('ok')"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr

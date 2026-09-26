"""Tests for protein_selector.domain.bioinformatics.famsa.

The alignment tests run the real FAMSA (``pyfamsa``) on short sequences, which takes
milliseconds. The crash guard is tested with FAMSA replaced, since the inputs it refuses
kill the process with a segmentation fault (PLAN.md §40).
"""

from __future__ import annotations

import pytest

from protein_selector.domain.bioinformatics.famsa import align_sequences, famsa_residues
from protein_selector.domain.bioinformatics.models import SequenceSearchError

_QUERY = "ACDEFGHIKLMNPQRSTVWY"
_HIT_A = "WCDWFGWIKWMNWQRSTVWY"  # 75% identical to the query
_HIT_C = "AYDEYGHYKLYNPYRYTVWY"  # 70% identical to the query


class TestFamsaResidues:
    def test_residues_outside_famsas_alphabet_become_x(self):
        # U (selenocysteine) and O (pyrrolysine) are not in FAMSA's alphabet.
        assert famsa_residues("mku o\nAC*") == "MKXXACX"


class TestAlignSequences:
    def test_a_real_famsa_alignment_keeps_every_residue(self):
        sequences = [_QUERY, "MMM" + _HIT_A, _HIT_C[:12]]
        rows = align_sequences(sequences)
        assert len({len(row) for row in rows}) == 1
        assert [row.decode().replace("-", "") for row in rows] == sequences

    @pytest.mark.parametrize(
        "sequences",
        [
            ["ACDEFGHIKLMNPQ", "ACDEF", "WWWWWWWWW"],
            # FAMSA does not treat the ambiguity codes as shared residues: each of these
            # pairs segfaulted pyfamsa 0.7.0 when aligned with the UPGMA tree.
            ["ACDEF", "XXXXX"],
            ["ACDB", "WWB"],
            ["ACDZ", "WWZ"],
            ["ACDX", "WWX"],
            # U, O and J are aligned as X, so a sequence of them has no standard residue.
            ["ACDEF", "UOJ"],
        ],
        ids=["disjoint", "all-x", "only-b", "only-z", "only-x", "only-u-o-j"],
    )
    def test_two_sequences_sharing_no_standard_residue_are_refused_not_aligned(
        self, monkeypatch, sequences
    ):
        # pyfamsa's UPGMA tree segfaults on such a pair, killing the whole process; the
        # guard must fire before FAMSA is ever called.
        import pyfamsa

        def must_not_run(**kwargs):
            raise AssertionError("FAMSA was called")

        monkeypatch.setattr(pyfamsa, "Aligner", must_not_run)
        with pytest.raises(SequenceSearchError, match="share no standard residue"):
            align_sequences(sequences)

    def test_one_shared_standard_residue_is_enough_to_align(self):
        # The real FAMSA: this pair aligned without crashing when checked.
        rows = align_sequences(["ACDEF", "WWWA"])
        assert [row.decode().replace("-", "") for row in rows] == ["ACDEF", "WWWA"]

    def test_rows_come_back_in_input_order_whatever_order_famsa_uses(self, monkeypatch):
        import pyfamsa

        class _ReversingAligner:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

            def align(self, sequences):
                return [
                    pyfamsa.GappedSequence(s.id, s.sequence) for s in reversed(sequences)
                ]

        monkeypatch.setattr(pyfamsa, "Aligner", _ReversingAligner)
        assert align_sequences(["ACD", "ADE", "AFG"]) == [b"ACD", b"ADE", b"AFG"]

    def test_the_thread_count_is_passed_to_famsa_as_given(self, monkeypatch):
        import pyfamsa

        made = []

        class _RecordingAligner:
            def __init__(self, **kwargs):
                made.append(kwargs)

            def align(self, sequences):
                return [pyfamsa.GappedSequence(s.id, s.sequence) for s in sequences]

        monkeypatch.setattr(pyfamsa, "Aligner", _RecordingAligner)
        align_sequences(["ACD", "ADE"], threads=3)
        align_sequences(["ACD", "ADE"])
        assert made == [
            {"guide_tree": "upgma", "threads": 3},
            {"guide_tree": "upgma", "threads": 1},
        ]

    def test_zero_threads_is_refused(self):
        # FAMSA would read 0 as one thread per host CPU.
        with pytest.raises(ValueError, match="at least one thread"):
            align_sequences(["ACD", "ADE"], threads=0)

"""Tests for protein_selector.domain.bioinformatics.residue_numbering.

The chains are built residue by residue with ``_chain``: a sequence of
``(author_number, uniprot_position)`` pairs, ``None`` for "unresolved" and for "not in
UniProt". Residue names cycle through the twenty amino acids by sequence position, so
PDBFixer's matching of the resolved residues onto the sequence has one answer, as it does
for a real protein. Each rule gets a passing and a failing case, shaped after a real entry
(2MYC, 1UCD, 3B2K, 1E98, 11IF, 3ERO, 1A46). ``rebuilt_numbers`` agrees with real
PDBFixer 1.12 on 50 entries, those included.
"""

from __future__ import annotations

import pytest

from protein_selector.domain.bioinformatics import residue_numbering as module
from protein_selector.domain.bioinformatics.models import (
    NumberingCheckError,
    SiftsResidue,
)
from protein_selector.domain.bioinformatics.residue_numbering import (
    check_residue_numbering,
    rebuilt_numbers,
    split_author_number,
)

ACCESSION = "P00001"
NAMES = (
    "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
    "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
)


def _chain(pairs, chain="A", accession=ACCESSION):
    """One chain from ``(author_number, uniprot_position)`` pairs, in sequence order."""
    return [
        SiftsResidue(
            chain=chain,
            position=i,
            author_number=None if number is None else str(number),
            residue_name=NAMES[(i - 1) % len(NAMES)],
            accession=None if uniprot is None else accession,
            uniprot_position=uniprot,
            uniprot_residue=None if uniprot is None else "A",
        )
        for i, (number, uniprot) in enumerate(pairs, start=1)
    ]


def _check(residues, length=200):
    return check_residue_numbering("1XYZ", residues, {ACCESSION: length})


class TestRuleOneUniProtsResiduesOnUniProtsNumbers:
    def test_a_late_start_and_a_hole_are_fine(self):
        # UniProt MACK, the crystal holds -A-K: A and K must be 2 and 4, and they are.
        result = _check(_chain([(None, 1), (2, 2), (None, 3), (4, 4)]))
        assert (result.uniprot_numbered, result.problems, result.n_chains) == (True, "", 1)

    def test_a_first_methionine_left_uncounted_fails(self):
        # 2MYC: every residue sits one number below its UniProt position.
        result = _check(_chain([(1, 2), (2, 3), (3, 4)]))
        assert not result.uniprot_numbered
        assert result.problems == (
            "chain A: every residue numbered 1 below its UniProt position"
        )

    def test_a_start_counted_early_fails_the_other_way(self):
        result = _check(_chain([(11, 1), (12, 2)]))
        assert "numbered 10 above its UniProt position" in result.problems

    def test_numbering_that_closes_over_a_deletion_fails(self):
        # 1UCD: right up to 49, then one below UniProt from 50 on.
        result = _check(_chain([(48, 48), (49, 49), (50, 51), (51, 52)]))
        assert "departs from UniProt partway" in result.problems

    def test_insertion_codes_fail(self):
        residues = _chain([(1, 1), ("1A", 2), (3, 3)])
        assert "insertion codes on 1 residue(s), first ARG1A" in _check(residues).problems


class TestRuleTwoNothingElseOnAUniProtNumber:
    def test_a_tag_residue_on_a_uniprot_number_fails(self):
        # 3B2K: an expression-tag serine numbered 1, where UniProt has its Met1.
        residues = _chain([(1, None), (2, 2), (3, 3)])
        assert "1 residue(s) not in UniProt P00001 sit on its numbers, first ALA1" in (
            _check(residues).problems
        )

    def test_an_insertion_code_does_not_take_a_residue_off_the_number(self):
        # A construct insert numbered 50A and 50B: MDAnalysis reads both as resid 50.
        residues = _chain(
            [(48, 48), (49, 49), (50, 50), ("50A", None), ("50B", None), (51, 51)]
        )
        assert "2 residue(s) not in UniProt P00001 sit on its numbers, first ASP50A" in (
            _check(residues).problems
        )

    def test_a_tag_beyond_the_uniprot_length_is_fine(self):
        residues = _chain([(1, 1), (2, 2), (3, None), (4, None)])
        assert _check(residues, length=2).uniprot_numbered

    def test_a_tag_numbered_below_one_is_fine(self):
        residues = _chain([(0, None), ("0A", None), (1, 1), (2, 2)])
        assert _check(residues).uniprot_numbered

    def test_without_the_uniprot_length_the_rule_is_not_guessed(self):
        residues = _chain([(1, None), (2, 2)])
        assert check_residue_numbering("1XYZ", residues, {}).uniprot_numbered


class TestRuleThreeTheRebuiltResidues:
    def test_a_rebuilt_start_below_zero_fails(self):
        # 1E98: a three-residue tag plus Met1 and Ala2, unresolved, before Ala3. Rebuilt
        # from 3 back, the tag takes -2, -1 and 0, and -2 and -1 wrap.
        residues = _chain([(None, None)] * 3 + [(None, 1), (None, 2), (3, 3), (4, 4)])
        result = _check(residues)
        assert result.problems == (
            "chain A: 2 unresolved residue(s) would be rebuilt below number 0, first ALA-2"
        )

    def test_a_rebuilt_start_on_zero_is_fine(self):
        # PDBFixer writes 0 as 0, and MDAnalysis does not wrap on it.
        residues = _chain([(None, None), (1, 1), (2, 2)])
        assert _check(residues).uniprot_numbered

    def test_a_rebuilt_start_that_fits_is_fine(self):
        residues = _chain([(None, 1), (None, 2), (3, 3), (4, 4)])
        assert _check(residues).uniprot_numbered

    def test_a_tag_rebuilt_in_front_of_a_uniprot_start_fails(self):
        # 11IF: an unresolved His tag in front of Ala27 is rebuilt on 19 to 26.
        residues = _chain([(None, None)] * 3 + [(27, 27), (28, 28)])
        assert (
            "3 unresolved residue(s) not in UniProt P00001 would be rebuilt on its "
            "numbers, first ALA24"
        ) in _check(residues).problems

    def test_a_tag_rebuilt_after_a_truncated_chain_fails(self):
        # Numbered on from the last resolved residue, into UniProt's range.
        residues = _chain([(1, 1), (2, 2), (None, None), (None, None)])
        assert "2 unresolved residue(s) not in UniProt P00001 would be rebuilt" in (
            _check(residues).problems
        )
        assert _check(residues, length=2).uniprot_numbered

    def test_an_internal_gap_rebuilt_below_zero_fails(self):
        # Resolved tag residues at -5 and -4, four unresolved, then Met1: the gap is
        # numbered back from 1, so -3, -2 and -1 wrap.
        residues = _chain([(-5, None), (-4, None)] + [(None, None)] * 4 + [(1, 1), (2, 2)])
        assert "3 unresolved residue(s) would be rebuilt below number 0, first ASN-3" in (
            _check(residues).problems
        )

    def test_a_uniprot_residue_rebuilt_off_its_position_fails(self):
        # UniProt 2 deleted from the construct, inside the unresolved start: counting
        # back from residue 4 puts UniProt 1 on 2.
        residues = _chain([(None, 1), (None, 3), (4, 4), (5, 5)])
        assert (
            "1 unresolved residue(s) would be rebuilt off their UniProt position, first "
            "ALA2 (UniProt 1)"
        ) in _check(residues).problems

    def test_a_rebuilt_run_that_inherits_rule_one_s_offset_is_not_reported_twice(self):
        residues = _chain([(None, 2), (2, 3), (3, 4)])
        assert _check(residues).problems == (
            "chain A: every residue numbered 1 below its UniProt position"
        )

    def test_a_chain_pdbfixer_cannot_line_up_gets_nothing_rebuilt(self):
        # 3ERO: the numbering skips a deleted residue, so the resolved residues laid out
        # by number fit nowhere on the sequence and PDBFixer rebuilds nothing, the tag
        # included.
        residues = _chain([(None, None), (None, None), (3, 3), (5, 5), (6, 6)])
        assert rebuilt_numbers(residues) == {}
        assert _check(residues).uniprot_numbered

    def test_a_wrap_in_a_chain_uniprot_does_not_have_fails_the_candidate(self):
        # MDAnalysis carries a wrap on through every later chain.
        residues = _chain([(1, 1), (2, 2)]) + _chain(
            [(None, None), (None, None), (1, None), (2, None)], chain="P"
        )
        result = _check(residues)
        assert (result.uniprot_numbered, result.n_chains) == (False, 1)
        assert result.problems == (
            "chain P: 1 unresolved residue(s) would be rebuilt below number 0, first ALA-1"
        )


class TestRebuiltNumbers:
    def test_numbers_every_run_as_pdbfixer_does(self):
        # Back from the residue after a run at the start and in a gap, on from the last
        # residue at the end.
        residues = _chain([(None, 1), (2, 2), (None, 3), (None, 4), (5, 5), (None, 6)])
        assert rebuilt_numbers(residues) == {0: 1, 2: 3, 3: 4, 5: 6}

    def test_an_insertion_code_moves_the_layout_on_by_one(self):
        # Thrombin light-chain style (1A46): 1, 1A and 2 take three places in a row, so one
        # unresolved residue fits between 2 and 4 and is numbered back from 4.
        residues = _chain([(1, None), ("1A", None), (2, None), (None, None), (4, None)])
        assert rebuilt_numbers(residues) == {3: 3}

    def test_a_chain_with_nothing_resolved_gets_nothing_rebuilt(self):
        assert rebuilt_numbers(_chain([(None, 1), (None, 2)])) == {}


class TestTheVerdict:
    def test_a_homodimer_says_it_once(self):
        residues = _chain([(1, 2), (2, 3)]) + _chain([(1, 2), (2, 3)], chain="B")
        result = _check(residues)
        assert result.n_chains == 2
        assert result.problems == (
            "chains A, B: every residue numbered 1 below its UniProt position"
        )

    def test_a_chain_with_no_uniprot_residue_is_not_judged(self):
        residues = _chain([(1, 1), (2, 2)]) + _chain([(1, None), (2, None)], chain="P")
        result = _check(residues)
        assert (result.uniprot_numbered, result.n_chains) == (True, 1)

    def test_no_chain_mapping_onto_uniprot_fails(self):
        result = _check(_chain([(1, None), (2, None)]))
        assert (result.uniprot_numbered, result.n_chains) == (False, 0)
        assert result.problems == "no chain maps onto UniProt"


class TestSplitAuthorNumber:
    @pytest.mark.parametrize(
        ("text", "expected"), [("52", (52, "")), ("52A", (52, "A")), ("-3", (-3, ""))]
    )
    def test_number_and_insertion_code(self, text, expected):
        assert split_author_number(text) == expected

    def test_an_unreadable_number_is_refused(self):
        with pytest.raises(NumberingCheckError):
            split_author_number("abc")


class TestFindResidueNumbering:
    def test_composes_sifts_and_the_uniprot_lengths(self, monkeypatch):
        from protein_selector.domain.bioinformatics import sifts, uniprot_entry
        from protein_selector.domain.bioinformatics.models import UniProtEntry

        monkeypatch.setattr(
            sifts, "fetch_sifts_residues", lambda pdb_id, session: _chain([(1, None), (2, 2)])
        )
        monkeypatch.setattr(
            uniprot_entry, "fetch_uniprot_entry",
            lambda accession, session: UniProtEntry(accession, "MA"),
        )
        result = module.find_residue_numbering("1XYZ")
        assert "sit on its numbers, first ALA1" in result.problems

    def test_a_uniprot_failure_becomes_the_one_exception(self, monkeypatch):
        import requests

        from protein_selector.domain.bioinformatics import sifts, uniprot_entry

        def refuse(accession, session):
            raise requests.ConnectionError("down")

        monkeypatch.setattr(
            sifts, "fetch_sifts_residues", lambda pdb_id, session: _chain([(2, 2)])
        )
        monkeypatch.setattr(uniprot_entry, "fetch_uniprot_entry", refuse)
        with pytest.raises(NumberingCheckError, match="UniProt sequence for P00001"):
            module.find_residue_numbering("1XYZ")

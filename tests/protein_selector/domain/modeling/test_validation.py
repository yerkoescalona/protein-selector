"""Tests for protein_selector.domain.modeling.validation.

fetch_alphafold_entry (the actual network boundary) is monkeypatched here --
covered for real by test_alphafold_lookup.py. This module's own job is the
confidence-threshold composition logic.
"""

from __future__ import annotations

import pytest

from protein_selector.core.validation_result import FailureMode, ValidationStatus
from protein_selector.domain.modeling import validation as modeling_validation
from protein_selector.domain.modeling.alphafold_db import AlphaFoldEntry
from protein_selector.domain.modeling.validation import run_modeling_validation

_GOOD_ENTRY = AlphaFoldEntry(
    uniprot_accession="P69905",
    entry_id="AF-P69905-F1",
    mean_plddt=98.06,
    fraction_plddt_very_low=0.0,
    fraction_plddt_low=0.007,
    fraction_plddt_confident=0.0,
    fraction_plddt_very_high=0.993,
    pdb_url="https://alphafold.ebi.ac.uk/files/AF-P69905-F1-model_v6.pdb",
    cif_url="https://alphafold.ebi.ac.uk/files/AF-P69905-F1-model_v6.cif",
    pae_doc_url="https://alphafold.ebi.ac.uk/files/AF-P69905-F1-predicted_aligned_error_v6.json",
    model_created_date="2025-08-01T00:00:00Z",
)


class TestRunModelingValidation:
    def test_no_entry_fails_as_completeness(self):
        # PLAN.md §34 N.3: the validator no longer fetches, so there is nothing to
        # monkeypatch -- "no entry" is now simply passing None.
        result = run_modeling_validation("1ABC", "Q00000", None)

        assert result.status == ValidationStatus.FAILURE
        assert result.failure_mode == FailureMode.COMPLETENESS
        assert "no AlphaFold DB entry" in result.notes[0]

    def test_high_confidence_entry_succeeds(self):
        result = run_modeling_validation("1ABC", "P69905", _GOOD_ENTRY)

        assert result.status == ValidationStatus.SUCCESS
        assert result.failure_mode is None
        assert "mean pLDDT 98.1" in result.notes[0]

    def test_floppy_entry_fails_as_confidence(self):
        floppy_entry = AlphaFoldEntry(
            uniprot_accession="P00000",
            entry_id="AF-P00000-F1",
            mean_plddt=40.0,
            fraction_plddt_very_low=0.5,
            fraction_plddt_low=0.2,
            fraction_plddt_confident=0.2,
            fraction_plddt_very_high=0.1,
            pdb_url="https://example.org/model.pdb",
            cif_url="https://example.org/model.cif",
            pae_doc_url="https://example.org/pae.json",
            model_created_date="2025-01-01T00:00:00Z",
        )
        result = run_modeling_validation("1ABC", "P00000", floppy_entry)

        assert result.status == ValidationStatus.FAILURE
        assert result.failure_mode == FailureMode.CONFIDENCE
        assert "low/very-low" in result.notes[0]

    @pytest.mark.parametrize(
        ("threshold", "expected_status"),
        [(0.9, ValidationStatus.SUCCESS), (0.001, ValidationStatus.FAILURE)],
        ids=["above_actual_fraction", "below_actual_fraction"],
    )
    def test_threshold_is_configurable(self, threshold, expected_status):
        # _GOOD_ENTRY's low-confidence fraction is 0.007
        result = run_modeling_validation(
            "1ABC", "P69905", _GOOD_ENTRY, max_low_confidence_fraction=threshold
        )
        assert result.status == expected_status


class TestValidatorPerformsNoIO:
    """PLAN.md §34 N.3 / §34c: a validator turns adapter output into a ValidationResult.

    It must not fetch. The old signature took only (pdb_id, accession) and fetched the
    entry itself -- while its only caller had just fetched the same record to persist it,
    costing two live HTTP requests per candidate (~2,445 redundant calls store-wide).
    """

    def test_module_does_not_import_the_fetch_function(self):
        assert not hasattr(modeling_validation, "fetch_alphafold_entry"), (
            "the validator must take the entry as an argument, never fetch it"
        )

    def test_is_a_pure_function_of_its_arguments(self):
        a = run_modeling_validation("1ABC", "P69905", _GOOD_ENTRY)
        b = run_modeling_validation("1ABC", "P69905", _GOOD_ENTRY)
        assert (a.status, a.failure_mode, a.notes) == (b.status, b.failure_mode, b.notes)

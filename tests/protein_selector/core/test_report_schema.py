"""Drift-detection test for the output-table data dictionary (PLAN.md §7b).

Asserts three independently-maintained representations of "what columns
does the report have" agree: ``core.report_schema.REPORT_COLUMN_NAMES``
(the declared dictionary), ``CandidateReportRow``'s actual fields (after
flattening its three ``ExerciseAssessment`` fields the same way
``core.report._flatten_row`` does), and a real CSV header built from a
populated fixture db. A future rename that only touches one of these three
places should fail here, not silently reintroduce the drift this file's
whole existence is meant to catch.
"""

from __future__ import annotations

from dataclasses import fields

from protein_selector.core.report import (
    _EXERCISE_FIELDS,
    CandidateReportRow,
    build_report_table,
    write_report_csv,
)
from protein_selector.core.report_schema import (
    _EXERCISE_ASSESSMENT_SUFFIXES,
    REPORT_COLUMNS,
)
from protein_selector.structural_biology.candidates import CandidateEntry
from protein_selector.structural_biology.store import upsert_candidates

_CANDIDATE = CandidateEntry(pdb_id="4HHB", title="Hemoglobin")


def _candidate_report_row_flattened_field_names() -> set[str]:
    """Mirror core.report._flatten_row's column-naming logic, without running it."""
    names = set()
    for f in fields(CandidateReportRow):
        if f.name in _EXERCISE_FIELDS:
            names |= {f"{f.name}_{suffix}" for suffix in _EXERCISE_ASSESSMENT_SUFFIXES}
        elif f.name == "rationale":
            names.add("rationale_json")
        else:
            names.add(f.name)
    return names


class TestReportSchemaDrift:
    def test_schema_dictionary_matches_candidate_report_row_fields(self):
        """core/report_schema.py's declared columns == CandidateReportRow's actual fields."""
        declared = {spec.name for spec in REPORT_COLUMNS}
        assert declared == _candidate_report_row_flattened_field_names()

    def test_schema_dictionary_matches_real_csv_header(self, tmp_path):
        """The declared columns == an actual CSV header written by write_report_csv."""
        db_path = tmp_path / "protein_selector.db"
        upsert_candidates([_CANDIDATE], db_path=db_path)
        rows = build_report_table(db_path=db_path)

        csv_path = tmp_path / "report.csv"
        write_report_csv(rows, csv_path)

        header = csv_path.read_text().splitlines()[0].split(",")
        declared = {spec.name for spec in REPORT_COLUMNS}
        assert set(header) == declared

    def test_no_duplicate_column_names(self):
        names = [spec.name for spec in REPORT_COLUMNS]
        assert len(names) == len(set(names))

    def test_every_column_traces_to_a_real_producer_module(self):
        """Producer-ownership rule (PLAN.md §7b): every spec names a dotted module path."""
        for spec in REPORT_COLUMNS:
            assert "." in spec.producer, f"{spec.name}'s producer {spec.producer!r} isn't a module path"

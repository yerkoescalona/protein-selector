"""Tests for protein_selector.domain.structural_biology.models.

PLAN.md §27d W1.2: this module must stay importable with ZERO network calls -- it's what
lets `core/report.py` read an already-populated store fully offline. Also checks that
`candidates.py`/`composition.py`'s re-exports are the SAME objects (identity), not
accidental duplicate classes -- a duplicate would silently break isinstance checks and
dataclass equality across module boundaries.
"""

from __future__ import annotations

import subprocess
import sys


def test_models_module_never_imports_rcsbapi():
    # A subprocess, not sys.modules bookkeeping in-process: another test in this same
    # run may have already imported protein_selector.domain.structural_biology.rcsb_search
    # (which DOES need rcsbapi for its own live-fetch functions), polluting sys.modules
    # for the rest of the process regardless of what this one test does. Only a fresh
    # interpreter proves models.py itself never triggers the import.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import protein_selector.domain.structural_biology.models; "
            "assert not any(m.startswith('rcsbapi') for m in sys.modules), sys.modules.keys()",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_candidates_reexports_are_identical_objects():
    from protein_selector.domain.structural_biology import models
    from protein_selector.domain.structural_biology import rcsb_search as candidates

    assert candidates.CandidateEntry is models.CandidateEntry
    assert candidates.ExperimentalMethod is models.ExperimentalMethod


def test_composition_reexports_are_identical_objects():
    from protein_selector.domain.structural_biology import models
    from protein_selector.domain.structural_biology import (
        rcsb_composition as composition,
    )

    assert composition.AssemblyInfo is models.AssemblyInfo
    assert composition.EntityCompositionInfo is models.EntityCompositionInfo

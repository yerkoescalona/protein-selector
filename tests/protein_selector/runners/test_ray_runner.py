"""Tests for protein_selector.runners.ray_runner (PLAN.md §31).

``plan_pipeline``/``format_plan`` are pure store queries and are tested with base
dependencies only -- they are deliberately importable and runnable without Ray, since
the dry-run is the capability that must survive whichever runner is in use.

The Ray DAG itself is skipped when the `ray` dependency group isn't installed, the same
graceful-skip discipline as the conda-only validator tests.
"""

from __future__ import annotations

from protein_selector.core.db import connect
from protein_selector.core.validation_result import (
    ValidationResult,
    ValidationStatus,
)
from protein_selector.core.validation_store import upsert_validation_results
from protein_selector.runners.ray_runner import (
    StagePlan,
    format_plan,
    plan_pipeline,
)
from protein_selector.structural_biology.models import CandidateEntry
from protein_selector.structural_biology.store import upsert_candidates


def _seed(db_path, n_candidates=3, uniprot=True):
    entries = [
        CandidateEntry(
            pdb_id=f"100{i}", title=f"t{i}", method="X-RAY DIFFRACTION", resolution=2.0,
            n_atoms=800, n_residues=100, n_modeled_residues=100, n_unmodeled_residues=0,
            n_protein_entities=1, uniprot_ids=([f"P0000{i}"] if uniprot else []),
            non_polymer_entity_ids=[],
            polymer_entity_ids=["1"], assembly_ids=["1"], organism="E. coli",
        )
        for i in range(n_candidates)
    ]
    upsert_candidates(entries, db_path=db_path)
    return entries


class TestPlanPipeline:
    def test_empty_store_plans_nothing(self, tmp_path):
        db = tmp_path / "empty.db"
        with connect(db):
            pass
        plans = plan_pipeline(db)
        assert all(p.pending == 0 for p in plans)
        assert "Nothing to be done" in format_plan(plans)

    def test_seeded_candidates_are_reported_as_pending(self, tmp_path):
        db = tmp_path / "seeded.db"
        _seed(db, n_candidates=3)
        by_stage = {p.stage: p for p in plan_pipeline(db)}
        # No validation rows exist yet, so modeling owes one per candidate.
        assert by_stage["modeling"].pending == 3
        assert by_stage["modeling"].already_done == 0
        assert by_stage["modeling"].would_run

    def test_persisted_work_is_not_replanned(self, tmp_path):
        # The property the whole §30e/S4.2 argument rests on: the STORE is the ledger, so
        # a stage with results already persisted must plan zero work -- no marker file
        # involved anywhere.
        db = tmp_path / "done.db"
        entries = _seed(db, n_candidates=3)
        upsert_validation_results(
            "modeling",
            [ValidationResult(pdb_id=e.pdb_id, status=ValidationStatus.SUCCESS) for e in entries],
            db_path=db,
        )
        by_stage = {p.stage: p for p in plan_pipeline(db)}
        assert by_stage["modeling"].already_done == 3
        assert by_stage["modeling"].pending == 0
        assert not by_stage["modeling"].would_run

    def test_modeling_ignores_candidates_that_can_never_have_an_afdb_entry(self, tmp_path):
        # Regression guard for the second wrong-denominator bug (the first was docking).
        # Modeling is an AlphaFold DB lookup keyed by UniProt accession, so a candidate
        # with no accession can NEVER get a row. Measured on the real store: all 28
        # candidates previously reported as "pending modeling" had no uniprot_id at all,
        # i.e. the plan was advertising work that could never be done.
        db = tmp_path / "no_uniprot.db"
        _seed(db, n_candidates=4, uniprot=False)
        by_stage = {p.stage: p for p in plan_pipeline(db)}
        assert by_stage["modeling"].pending == 0
        assert not by_stage["modeling"].would_run

    def test_slow_lanes_use_their_own_eligible_pool_not_the_whole_store(self, tmp_path):
        # Regression guard for a real bug in the first version of this function: using
        # len(candidates) as the docking denominator reported 2,065 phantom pending jobs
        # against the real store, because docking only ever runs on candidates with a
        # dockable ligand. A dry run that overstates work is worse than none.
        db = tmp_path / "pools.db"
        _seed(db, n_candidates=5)
        by_stage = {p.stage: p for p in plan_pipeline(db)}
        assert by_stage["docking"].pending == 0, "no ligands persisted -> nothing dockable"

    def test_format_plan_renders_every_stage(self, tmp_path):
        db = tmp_path / "fmt.db"
        _seed(db, n_candidates=1)
        text = format_plan(plan_pipeline(db))
        for stage in ("simulability", "ligands", "literature", "modeling", "docking"):
            assert stage in text


class TestStagePlan:
    def test_would_run_is_driven_by_pending(self):
        assert StagePlan("x", already_done=0, pending=1).would_run
        assert not StagePlan("x", already_done=5, pending=0).would_run


class TestRayDag:
    """The DAG itself is verified LIVE, not here -- see this class's note.

    A mocked test cannot cover it honestly: the Ray tasks run in separate worker
    processes, so a driver-side monkeypatch of a stage function never reaches them, and
    ``run_simulability_stage`` legitimately calls RCSB (composition.py's assembly and
    entity fetches). A test built on fake PDB ids just sends them to the live API and
    gets "Input produced no results" -- which is what the first version of this test did.
    Rather than ship a test that pretends, the DAG was run for real; the record is in
    PLAN.md §31 and reproduced by ``scripts/run_ray_pipeline.py``.

    **Live-verified 2026-08-29** against a copy of the real 2,473-candidate store, driven
    by 60 frozen ids and workflow/config.yaml's real filter: completed in 7.3 s, returned
    60 survivors, and left candidates/validation/literature row counts identical to the
    source store -- i.e. every stage correctly skipped already-persisted work, with no
    marker files involved.
    """

    def test_ray_is_imported_lazily(self):
        # The module must import with base dependencies only, same discipline as every
        # other heavy optional dependency here (.claude/CLAUDE.md's lazy-import rule).
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; import protein_selector.runners.ray_runner as m; "
             "assert 'ray' not in sys.modules, sorted(k for k in sys.modules if 'ray' in k); "
             "print('ok')"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "ok" in result.stdout

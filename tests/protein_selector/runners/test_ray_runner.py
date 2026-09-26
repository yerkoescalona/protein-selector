"""Tests for protein_selector.runners.ray_runner (PLAN.md §31).

``plan_pipeline``/``format_plan`` are pure store queries and are tested with base
dependencies only -- they are deliberately importable and runnable without Ray, since
the dry-run is the capability that must survive whichever runner is in use.

The Ray DAG itself is skipped when the `ray` dependency group isn't installed, the same
graceful-skip discipline as the conda-only validator tests.
"""

from __future__ import annotations

import pytest

from protein_selector.core.db import connect
from protein_selector.core.validation_result import (
    ValidationResult,
    ValidationStatus,
)
from protein_selector.core.validation_store import upsert_validation_results
from protein_selector.domain.structural_biology.models import CandidateEntry
from protein_selector.domain.structural_biology.store import upsert_candidates
from protein_selector.runners.ray_runner import (
    RayPipelineConfig,
    StagePlan,
    annotation_cpus,
    format_plan,
    plan_pipeline,
)


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

    def test_relatives_are_owed_one_row_per_survivor_with_an_accession(self, tmp_path):
        # PLAN.md §40: the query is the survivor's UniProt chain, so the denominator is
        # the survivors with an accession -- and a stored row for a candidate that no
        # longer survives must not hide a survivor's pending search.
        from protein_selector.domain.bioinformatics.sequence_relatives import (
            SequenceRelativesResult,
        )
        from protein_selector.domain.bioinformatics.store import (
            upsert_sequence_relatives,
        )
        from protein_selector.domain.structural_biology.store import (
            upsert_simulability,
        )
        from protein_selector.domain.structural_biology.validation import (
            SimulabilityResult,
        )

        db = tmp_path / "relatives.db"
        entries = _seed(db, n_candidates=4)
        no_accession = CandidateEntry(pdb_id="2000", uniprot_ids=[])
        upsert_candidates([no_accession], db_path=db)
        upsert_simulability(
            [SimulabilityResult(pdb_id=e.pdb_id, passed=i < 3) for i, e in enumerate(entries)]
            + [SimulabilityResult(pdb_id="2000", passed=True)],
            db_path=db,
        )
        upsert_sequence_relatives(
            [
                SequenceRelativesResult(
                    pdb_id=pdb_id, uniprot_accession="P00000", chain_start=1,
                    chain_end=100, query_length=100, structure_start=None,
                    structure_end=None, structure_coverage=None, database="swissprot",
                    n_hits=0, n_relatives=0, alignment_columns=None,
                    median_identity=None, max_identity=0.95, min_relatives=10,
                    passed=False,
                )
                for pdb_id in (entries[0].pdb_id, entries[3].pdb_id)  # [3] failed sim
            ],
            db_path=db,
        )
        by_stage = {p.stage: p for p in plan_pipeline(db)}
        # Survivors 1000-1002 plus 2000; 2000 has no accession and can never get a row.
        assert by_stage["relatives"].already_done == 1
        assert by_stage["relatives"].pending == 2

    def test_a_relatives_row_for_another_accession_is_pending(self, tmp_path):
        # The candidate's first accession changed since its row was stored (RCSB does not
        # keep entities in a fixed order): the node searches it again, so the plan must
        # count it as pending, not done.
        from protein_selector.domain.bioinformatics.sequence_relatives import (
            SequenceRelativesResult,
        )
        from protein_selector.domain.bioinformatics.store import (
            upsert_sequence_relatives,
        )
        from protein_selector.domain.structural_biology.store import (
            upsert_simulability,
        )
        from protein_selector.domain.structural_biology.validation import (
            SimulabilityResult,
        )

        db = tmp_path / "relatives_accession.db"
        entries = _seed(db, n_candidates=2)
        upsert_simulability(
            [SimulabilityResult(pdb_id=e.pdb_id, passed=True) for e in entries], db_path=db
        )
        upsert_sequence_relatives(
            [
                SequenceRelativesResult(
                    pdb_id=entry.pdb_id, uniprot_accession=accession, chain_start=1,
                    chain_end=100, query_length=100, structure_start=None,
                    structure_end=None, structure_coverage=None, database="swissprot",
                    n_hits=0, n_relatives=0, alignment_columns=None,
                    median_identity=None, max_identity=0.95, min_relatives=10,
                    passed=False,
                )
                for entry, accession in zip(
                    entries, (entries[0].uniprot_ids[0], "Q99999"), strict=True
                )
            ],
            db_path=db,
        )
        relatives = {p.stage: p for p in plan_pipeline(db)}["relatives"]
        assert (relatives.already_done, relatives.pending) == (1, 1)

    def test_numbering_is_owed_one_row_per_survivor_with_an_accession(self, tmp_path):
        # The same pool as relatives: the check compares with UniProt, so a candidate
        # without an accession can never get a row, and a row left over for a candidate
        # that no longer survives must not hide a survivor's pending check.
        from protein_selector.domain.bioinformatics.residue_numbering import (
            ResidueNumberingResult,
        )
        from protein_selector.domain.bioinformatics.store import (
            upsert_residue_numbering,
        )
        from protein_selector.domain.structural_biology.store import (
            upsert_simulability,
        )
        from protein_selector.domain.structural_biology.validation import (
            SimulabilityResult,
        )

        db = tmp_path / "numbering.db"
        entries = _seed(db, n_candidates=4)
        no_accession = CandidateEntry(pdb_id="2000", uniprot_ids=[])
        upsert_candidates([no_accession], db_path=db)
        upsert_simulability(
            [SimulabilityResult(pdb_id=e.pdb_id, passed=i < 3) for i, e in enumerate(entries)]
            + [SimulabilityResult(pdb_id="2000", passed=True)],
            db_path=db,
        )
        upsert_residue_numbering(
            [ResidueNumberingResult(pdb_id, True, 1, "")
             for pdb_id in (entries[0].pdb_id, entries[3].pdb_id)],  # [3] failed sim
            db_path=db,
        )
        numbering = {p.stage: p for p in plan_pipeline(db)}["numbering"]
        assert (numbering.already_done, numbering.pending) == (1, 2)

    def test_format_plan_renders_every_stage(self, tmp_path):
        db = tmp_path / "fmt.db"
        _seed(db, n_candidates=1)
        text = format_plan(plan_pipeline(db))
        for stage in ("simulability", "ligands", "literature", "modeling", "relatives",
                      "numbering", "ligand_context", "docking"):
            assert stage in text


def _config(*, md=False, dock=False, md_threads=2, dock_threads=2, workers=4,
            famsa_threads=1, relatives=True, numbering=True, ligand_context=True):
    from protein_selector.core.config import (
        DockingConfig,
        LigandContextConfig,
        MdSimulationConfig,
        ResidueNumberingConfig,
        SequenceRelativesConfig,
    )

    return RayPipelineConfig(
        md_simulation=MdSimulationConfig(enabled=md),
        docking=DockingConfig(enabled=dock),
        md_threads=md_threads,
        dock_threads=dock_threads,
        sequence_relatives=SequenceRelativesConfig(
            enabled=relatives, max_workers=workers, famsa_threads=famsa_threads
        ),
        residue_numbering=ResidueNumberingConfig(enabled=numbering),
        ligand_context=LigandContextConfig(enabled=ligand_context),
    )


class TestAnnotationCpus:
    """The annotations run for hours beside chemistry and the slow lanes on one cluster."""

    @pytest.mark.parametrize("cluster", [1, 2, 3, 4, 6, 8, 16, 64])
    @pytest.mark.parametrize(
        "config,largest",
        [
            (_config(), 1),  # chemistry and pocket detection: one CPU
            (_config(md=True), 2),
            (_config(md=True, dock=True, dock_threads=4), 4),
            (_config(md=True, md_threads=8), 8),
            (_config(md=True, workers=8, famsa_threads=2), 2),
            (_config(workers=1), 1),
        ],
        ids=["cheap-lane", "md", "md+dock4", "md8", "relatives-8x2", "one-worker"],
    )
    def test_the_largest_slow_lane_task_always_fits_beside_the_annotations(
        self, cluster, config, largest
    ):
        cpus = annotation_cpus(config, cluster)
        held = cpus.relatives + cpus.numbering + cpus.ligand_context
        assert min(cpus.relatives, cpus.numbering, cpus.ligand_context) >= 0
        # Below `largest` no such task can ever run; the annotations then hold nothing.
        assert held + largest <= max(cluster, largest)

    def test_a_four_cpu_cluster_keeps_room_for_md(self):
        # The default 4 workers x 1 FAMSA thread once reserved all 4 CPUs of a 4-CPU run,
        # so chemistry, and MD behind it, waited for the whole EBI backfill.
        cpus = annotation_cpus(_config(md=True), 4)
        assert cpus.relatives == 2
        assert cpus.relatives + cpus.numbering + cpus.ligand_context == 2

    def test_relatives_gets_its_whole_request_when_the_cluster_has_room(self):
        cpus = annotation_cpus(_config(md=True, workers=4, famsa_threads=2), 16)
        assert (cpus.relatives, cpus.numbering, cpus.ligand_context) == (8, 1, 1)

    def test_a_cluster_no_bigger_than_one_md_task_reserves_nothing(self):
        # Ray still runs a zero-CPU task; it shares cores rather than waiting for them.
        cpus = annotation_cpus(_config(md=True, md_threads=4), 4)
        assert (cpus.relatives, cpus.numbering, cpus.ligand_context) == (0, 0, 0)

    def test_a_lane_switched_off_reserves_nothing(self):
        cpus = annotation_cpus(
            _config(relatives=False, numbering=False, ligand_context=False), 16
        )
        assert (cpus.relatives, cpus.numbering, cpus.ligand_context) == (0, 0, 0)

    def test_fractional_cluster_cpus_are_rounded_down(self):
        # ray.cluster_resources() reports CPUs as a float.
        assert annotation_cpus(_config(), 4.0) == annotation_cpus(_config(), 4)
        assert annotation_cpus(_config(), 3.5) == annotation_cpus(_config(), 3)


class TestStagePlan:
    def test_would_run_is_driven_by_pending(self):
        assert StagePlan("x", already_done=0, pending=1).would_run
        assert not StagePlan("x", already_done=5, pending=0).would_run


class TestRayDag:
    """The DAG itself is verified LIVE, not here -- see this class's note.

    A mocked test cannot cover it honestly: the Ray tasks run in separate worker
    processes, so a driver-side monkeypatch of a stage function never reaches them, and
    ``check_simulability`` legitimately calls RCSB (composition.py's assembly and
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

"""Per-stage config dataclasses (PLAN.md §16d). One dataclass per Snakemake rule's config."""

from __future__ import annotations

from dataclasses import dataclass, field

from protein_selector.structural_biology.candidates import ExperimentalMethod

_RCSB_MAX_ATOMS_CEILING = 50_000  # RCSB has no residue-count query field; this is a loose
# safety ceiling on the search itself, not a pedagogical knob (see CandidateSearchConfig).


@dataclass
class CandidateSearchConfig:
    """What to ask RCSB's Search API for, and how many candidates to sample.

    Search-side only (PLAN.md §3/§7a) -- fields sent to RCSB as query parameters, or
    controlling the pool-then-sample step (RCSB has no random-sort option). For filtering
    *by* what RCSB returns, see ``CandidateFilterConfig``.
    """

    max_candidates: int = 20
    methods: list[ExperimentalMethod] = field(
        default_factory=lambda: [ExperimentalMethod.X_RAY_DIFFRACTION]
    )  # OR query (Attr.in_()); narrow to a subset downstream via CandidateFilterConfig.methods.
    max_resolution: float = 3.0  # also the client-side quality bar via
    # CandidateFilterConfig.max_resolution -- one number, not a coarse/tight pair.
    sample_pool_size: int | None = None  # None = max(max_candidates * 20, 200).
    random_seed: int | None = None  # None = OS-entropy random sample each call.


@dataclass
class CandidateFilterConfig:
    """Client-side gate on every ``CandidateSearchConfig`` survivor (PLAN.md §3/§10 step 2).

    A candidate that fails (``SimulabilityResult.passed is False``) is dropped from the
    pool before any downstream stage sees it, not just recorded for the report.
    """

    min_residues: int = 50
    max_residues: int = 50  # MD here is O(atoms^2) NoCutoff; keeps a default run's MD
    # stage fast. Widen if not running MD.
    max_resolution: float = 2.5
    max_unmodeled_fraction: float = 0.1
    methods: list[ExperimentalMethod] | None = None  # None = no further narrowing beyond
    # CandidateSearchConfig.methods; set to a subset when the search cast a wider net.


@dataclass
class ModelingLookupConfig:
    """Fetch-only AlphaFold DB check -- persisted as exercise "ex02". Never runs a new prediction."""

    enabled: bool = True


@dataclass
class MdSimulationConfig:
    """Real OpenMM test-MD validator -- persisted as exercise "ex03". Conda-only, off by default."""

    enabled: bool = False
    n_steps: int | None = None  # None = md_validation.py's own default.
    max_minimization_iterations: int = 0  # 0 = unbounded (OpenMM default).


@dataclass
class ComplexMdSimulationConfig:
    """Real GAFF2/AMBER receptor+ligand complex MD -- persisted as "complex_md_simulation" (PLAN.md §24).

    Needs ``md_simulation`` and ``docking`` to have already succeeded for a candidate.
    """

    enabled: bool = False
    n_steps: int | None = None
    max_minimization_iterations: int = 0


@dataclass
class PocketDetectionConfig:
    """Real fpocket run -- needs a local `fpocket` binary. Not persisted as any exercise."""

    enabled: bool = False
    box_padding_angstroms: float = 6.0  # margin added to a pocket's max pairwise-vertex
    # distance so a comparably-sized ligand fits the derived Vina box (PLAN.md §17b).


@dataclass
class DockingConfig:
    """Real Vina self-dock + PLIP validator -- persisted as exercise "docking" (PLAN.md §17).

    Requires ``pocket_detection`` and the ``ligands``/``meeko`` stages to have already run
    and persisted for a candidate -- see ``stages.docking_common.resolve_docking_target``.
    """

    enabled: bool = False
    exhaustiveness: int = 8  # do NOT lower for speed -- low exhaustiveness produces false
    # self-dock failures (PLAN.md §15h/§17h).
    rmsd_threshold_angstrom: float = 2.5  # self-dock success cutoff (see
    # docking.vina_docking._DEFAULT_RMSD_THRESHOLD_ANGSTROM for why 2.5, not 2.0).

"""Per-stage config dataclasses (PLAN.md §16d). One dataclass per Snakemake rule's config."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from protein_selector.domain.structural_biology.rcsb_search import ExperimentalMethod

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


def load_run_config(path: Path | str = Path("workflow/config.yaml")) -> dict:
    """Read the run config file into a plain dict (PLAN.md §38).

    One file describes a run, and every runner reads it. It survived the Snakemake removal
    unchanged because it was always *run* configuration rather than workflow-engine
    configuration -- thresholds, lane switches, resource counts.
    """
    import yaml

    path = Path(path)
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def candidate_filter_from(config: dict) -> CandidateFilterConfig:
    """The client-side screening window (§7a)."""
    return CandidateFilterConfig(
        min_residues=config.get("min_residues", CandidateFilterConfig().min_residues),
        max_residues=config.get("max_residues", CandidateFilterConfig().max_residues),
        max_resolution=config.get("max_resolution", CandidateFilterConfig().max_resolution),
    )


def candidate_search_from(config: dict) -> CandidateSearchConfig:
    """The RCSB query terms (§7a)."""
    return CandidateSearchConfig(
        max_candidates=config.get("max_candidates", CandidateSearchConfig().max_candidates),
        max_resolution=config.get("max_resolution", CandidateSearchConfig().max_resolution),
    )


def md_simulation_from(config: dict) -> MdSimulationConfig:
    """The ex03 MD lane. Off unless `run_md` says otherwise."""
    return MdSimulationConfig(
        enabled=bool(config.get("run_md", False)),
        n_steps=config.get("md_n_steps"),
        max_minimization_iterations=config.get("md_max_minimization_iterations", 0),
    )


def pocket_detection_from(config: dict) -> PocketDetectionConfig:
    """Fpocket. Tied to `run_dock`: pocket data only ever feeds the docking path (§20)."""
    return PocketDetectionConfig(
        enabled=bool(config.get("run_dock", False)),
        box_padding_angstroms=config.get(
            "dock_box_padding", PocketDetectionConfig().box_padding_angstroms
        ),
    )


def docking_from(config: dict) -> DockingConfig:
    """The ex04 docking lane."""
    return DockingConfig(
        enabled=bool(config.get("run_dock", False)),
        exhaustiveness=config.get("dock_exhaustiveness", DockingConfig().exhaustiveness),
        rmsd_threshold_angstrom=config.get(
            "dock_rmsd_threshold", DockingConfig().rmsd_threshold_angstrom
        ),
    )


def complex_md_from(config: dict) -> ComplexMdSimulationConfig:
    """The receptor+ligand complex MD lane (§24). Off by default -- needs ambertools."""
    return ComplexMdSimulationConfig(
        enabled=bool(config.get("run_complex_md", False)),
        n_steps=config.get("complex_md_n_steps"),
        max_minimization_iterations=config.get(
            "complex_md_max_minimization_iterations", 0
        ),
    )

"""Per-stage config dataclasses (PLAN.md §16d), relocated from ``pipeline.py`` unchanged.

Kept as typed dataclasses, not bare dicts read straight from ``snakemake.config`` --
each field carries real documentation (why it exists, what it does to a live RCSB query
or a client-side filter) that a dict would lose. ``workflow/config.yaml`` values map onto
these at the Snakemake `script:` boundary; nothing about the fields themselves changed
during the PLAN.md §16 migration out of ``pipeline.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from protein_selector.structural_biology.candidates import ExperimentalMethod

_RCSB_MAX_ATOMS_CEILING = 50_000  # loose technical safety ceiling on the RCSB search
# query itself (RCSB has no residue-count query field to filter on directly) -- not a
# pedagogical knob, see CandidateSearchConfig's docstring for why it isn't a field there.
# Note: the RCSB Search API's own real per-request `rows` ceiling
# (``structural_biology.candidates._RCSB_MAX_ROWS_PER_QUERY``) used to also need
# duplicating/clamping here -- fixed 2026-07-18 by moving that concern entirely into
# `search_candidate_ids` itself (it now transparently paginates past its own per-request
# ceiling), so `run_search_candidates_stage` no longer needs to know about or clamp to it.


@dataclass
class CandidateSearchConfig:
    """What to ask RCSB's Search API for, and how many candidates to sample.

    Search-side only (PLAN.md §3's hard-filters SQL query, §7a's split): every
    field here is either sent straight to RCSB as a server-side query
    parameter (``methods``, ``max_resolution``) or controls the
    pool-then-sample step that works around RCSB having no random-sort option
    (``sample_pool_size``, ``random_seed``). It never inspects a candidate's
    own metadata client-side -- for filtering *by* what RCSB returns (residue
    count, oligomeric state, composition), see ``CandidateFilterConfig``.
    ``max_atoms`` is deliberately not a field here -- see
    ``_RCSB_MAX_ATOMS_CEILING`` below.
    """

    max_candidates: int = 20  # how many candidates this run actually processes
    methods: list[ExperimentalMethod] = field(
        default_factory=lambda: [ExperimentalMethod.X_RAY_DIFFRACTION]
    )  # sent to RCSB via Attr.in_() (an OR query, live-verified -- see
    # candidates.build_hard_filters_query's docstring) -- pass more than one to cast a
    # wider net (e.g. also SOLUTION NMR) and narrow to a subset later via
    # CandidateFilterConfig.methods, rather than missing those candidates from the
    # pool/report entirely.
    max_resolution: float = 3.0  # also the real client-side quality bar, via
    # CandidateFilterConfig.max_resolution -- see that field's docstring for why
    # there's only one resolution number, not a separate coarse/tight pair.
    sample_pool_size: int | None = None  # None = max(max_candidates * 20, 200);
    # see search_candidates.run_search_candidates_stage's docstring for why a larger pool
    # than max_candidates is fetched at all (RCSB's Search API has no random-sort option).
    random_seed: int | None = None  # None = a genuinely different random sample each
    # call (Python's random.Random(None) seeds from OS entropy) -- this is already the
    # default behavior, not something you need to set. Pass a fixed int only when you
    # specifically want a reproducible sample (e.g. in a test). PLAN.md §16c: a Snakemake
    # rule calling this stage freezes its sampled ids to a file and never re-samples
    # while that file exists, so this only matters for a deliberate re-sample.


@dataclass
class CandidateFilterConfig:
    """Client-side gate applied to every ``CandidateSearchConfig`` survivor, using RCSB metadata.

    This is the *filtering* half of PLAN.md §3/§10 step 2 ("simulability"):
    residue-count window, a tightened resolution ceiling, completeness, and
    (informational by default) oligomeric-state/non-standard-residue checks
    -- see ``structural_biology.simulability.check_full_simulability``'s
    docstring for what each check actually does. Every candidate that fails
    (``SimulabilityResult.passed is False``) is dropped from the pool right
    after these checks run, BEFORE it (or any downstream stage --
    parameterizability, Meeko, modeling lookup, MD simulation, pocket
    detection) does any further work on it -- not just recorded for the report.

    ``max_residues`` defaults to 50 (not PLAN.md §13's original 100-300 aa
    Colab-budget window) because MD simulation here is O(atoms^2) NoCutoff
    (see ``MdSimulationConfig``'s docstring): a 50-residue ceiling keeps a
    default run's MD stage fast. Widen it if you don't plan to run MD, or
    want the fuller teaching-structure window instead.

    ``methods``, unlike ``max_residues``/``max_resolution``, is not a
    tightened version of its ``CandidateSearchConfig`` counterpart -- it's a
    genuine *subset* check. ``None`` (the default) means don't narrow further;
    whatever ``CandidateSearchConfig.methods`` returned survives this check.
    Set it when the search intentionally cast a wider net than you want
    downstream (e.g. search ``[X_RAY_DIFFRACTION, SOLUTION_NMR]`` so both show
    up in the report, filter to ``[X_RAY_DIFFRACTION]`` only, since NMR
    entries are typically multi-model ensembles the MD/pocket-detection stages
    below don't handle).
    """

    min_residues: int = 50
    max_residues: int = 50
    max_resolution: float = 2.5
    max_unmodeled_fraction: float = 0.1  # check_full_simulability's own default,
    # threaded through here (2026-07-22) so scripts/validate_one.py can override it
    # per-run without touching workflow/config.yaml -- previously hardcoded, unreachable.
    methods: list[ExperimentalMethod] | None = None


@dataclass
class ModelingLookupConfig:
    """Fetch-only AlphaFold DB check -- persisted as exercise "ex02". Never runs a new prediction."""

    enabled: bool = True  # cheap, fetch-only, no conda needed -- on by default.


@dataclass
class MdSimulationConfig:
    """Real OpenMM test-MD validator -- persisted as exercise "ex03". The slow, conda-only stage.

    Size is capped upstream, in ``CandidateFilterConfig.max_residues`` -- not
    here. Filtering the whole candidate pool right after simulability checks
    run benefits every downstream stage (this one most of all, since it's
    the slowest, but also parameterizability/Meeko/modeling-lookup/
    pocket-detection all skip doing any work on a candidate that failed the
    filter), not just MD.
    """

    enabled: bool = False  # needs environment-validation.yml's conda env -- off by default.
    n_steps: int | None = None  # None = md_validation.py's own default (a quick smoke test).
    max_minimization_iterations: int = 0  # 0 = unbounded (OpenMM's own default) -- see
    # md_validation.run_test_md's docstring for the real, unbounded-wall-clock risk this
    # controls. Set a real cap here for triage runs where bounded worst-case time matters
    # more than every candidate's minimization reaching full convergence.


@dataclass
class ComplexMdSimulationConfig:
    """Real GAFF2/AMBER receptor+ligand complex MD, persisted as exercise "complex_md_simulation".

    PLAN.md §23a. Needs ``md_simulation`` and ``docking`` to have already succeeded for a
    candidate (starts from the MD-relaxed receptor + the ligand's real crystal pose, not a
    freshly re-embedded conformer or Vina's predicted pose).
    """

    enabled: bool = False  # needs environment-validation.yml's conda env (ambertools too,
    # not just openmm/openff-toolkit) -- off by default, same as MdSimulationConfig.
    n_steps: int | None = None  # None = complex_md_validation.py's own default.
    max_minimization_iterations: int = 0  # 0 = unbounded, same rationale as MdSimulationConfig.


@dataclass
class PocketDetectionConfig:
    """Real fpocket run -- needs a local `fpocket` binary. Not persisted as any exercise."""

    enabled: bool = False
    box_padding_angstroms: float = 6.0  # PLAN.md §17b: forwarded to
    # docking.pocket.run_fpocket -- the margin added to a pocket's own maximum
    # pairwise-vertex distance so a bound ligand comparable in size to the pocket fits
    # inside the derived Vina box. ⚠ Candidate default, not yet live-verified (§17b).


@dataclass
class DockingConfig:
    """Real Vina self-dock + PLIP validator -- persisted as exercise "docking" (PLAN.md §17).

    The slow, conda-only stage's docking-side sibling of ``MdSimulationConfig``.

    Requires ``pocket_detection`` (for ``box_center``/``box_size``, PLAN.md §17b) and the
    ``ligands``/``meeko`` stages (for the CCD codes + Meeko pass/fail
    ``pick_largest_organic_ligand`` needs, PLAN.md §17a.2) to have already run and
    persisted for a candidate before ``run_docking_stage`` can resolve a target at all --
    see ``stages.docking_common.resolve_docking_target``.
    """

    enabled: bool = False  # needs environment-validation.yml's conda env -- off by default.
    exhaustiveness: int = 8  # Vina search effort -- do NOT lower for speed (PLAN.md §15h/
    # §17h: low exhaustiveness produces FALSE self-dock failures and poisons the
    # measured-difficulty / predicted-vs-measured gap this tool exists to compute).
    rmsd_threshold_angstrom: float = 2.5  # self-dock "success" cutoff, passed straight
    # through to `docking.vina_docking.run_self_dock` -- see that module's own
    # `_DEFAULT_RMSD_THRESHOLD_ANGSTROM` for why 2.5, not the literature-standard 2.0.

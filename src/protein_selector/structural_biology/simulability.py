"""L2 simulability checks: cheap, metadata-only gates on L1 survivors.

Per PLAN.md §3/§10 step 2, L2 tightens L1's coarse SQL-side filters (resolution
ceiling, atom-count ceiling), adds the residue-count window PLAN.md §13 assumes
for the Colab compute budget (~100-300 aa), and checks completeness, oligomeric
state, and non-standard residues.

All four checks implemented (2026-07-04, all field paths live-verified against
data.rcsb.org -- see candidates.py and composition.py's module docstrings for
the verification detail, including a real bug the verification caught):

- Residue-count window + resolution ceiling (`check_size_and_resolution`) --
  pure logic on `CandidateEntry` fields L1 already fetches, no new network call.
- Completeness/gaps (`check_completeness`) -- also pure logic on `CandidateEntry`
  fields (`n_modeled_residues`/`n_unmodeled_residues`), no new network call;
  these were added to L1's entry-level fetch since they're free (same query).
- Oligomeric state (`check_oligomeric_state`) -- needs `composition.AssemblyInfo`
  from `composition.fetch_oligomeric_state`'s separate assembly-level fetch.
- Non-standard residues (`check_non_standard_residues`) -- needs
  `composition.EntityCompositionInfo` from `composition.fetch_non_standard_residues`'s
  separate polymer-entity-level fetch.

`check_full_simulability` composes all four into one `SimulabilityResult`.
Oligomeric state and non-standard-residue checks are **informational by
default** (no ceiling / non-standard residues allowed) -- PLAN.md didn't
specify a hard pedagogical rule for either, and many good teaching structures
are dimers/tetramers or use minor substitutions (e.g. SeMet/MSE). Set
`max_oligomeric_count`/`allow_non_standard_residues` to actually gate on them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from protein_selector.structural_biology.candidates import CandidateEntry
from protein_selector.structural_biology.composition import (
    AssemblyInfo,
    EntityCompositionInfo,
)


@dataclass
class SimulabilityResult:
    """Outcome of the L2 size/resolution gate for one candidate."""

    pdb_id: str
    passed: bool
    reasons: list[str] = field(default_factory=list)


def check_size_and_resolution(
    entry: CandidateEntry,
    min_residues: int = 50,
    max_residues: int = 300,
    max_resolution: float = 2.5,
) -> SimulabilityResult:
    """L2 gate: residue-count window + a tightened resolution ceiling.

    L1 already filters on a coarser resolution/atom-count ceiling (see
    ``candidates.build_l1_query``); this catches survivors that cleared L1's
    SQL-side filter but are still too large, too small, or too low-resolution
    for a Colab-budget MD/docking exercise.

    An unknown ("None") value is treated as a failure with an explicit reason,
    not silently passed -- unknown is not the same as acceptable.
    """
    reasons: list[str] = []

    if entry.n_residues is None:
        reasons.append("residue count unknown")
    elif not (min_residues <= entry.n_residues <= max_residues):
        reasons.append(
            f"residue count {entry.n_residues} outside "
            f"[{min_residues}, {max_residues}]"
        )

    if entry.resolution is None:
        reasons.append("resolution unknown")
    elif entry.resolution > max_resolution:
        reasons.append(f"resolution {entry.resolution} Å > {max_resolution} Å")

    return SimulabilityResult(pdb_id=entry.pdb_id, passed=not reasons, reasons=reasons)


def check_completeness(
    entry: CandidateEntry, max_unmodeled_fraction: float = 0.1
) -> list[str]:
    """L2 gate: fraction of unmodeled (missing/disordered) residues.

    Uses ``n_modeled_residues``/``n_unmodeled_residues`` -- fields L1 already
    fetches (verified RCSB fields ``deposited_modeled_polymer_monomer_count``/
    ``deposited_unmodeled_polymer_monomer_count``; see candidates.py), so this
    needs no new network call. A high unmodeled fraction means significant
    missing loops/regions, which complicates MD prep (PDBFixer gap-filling)
    and makes the structure a worse teaching example.

    Returns a bare reason list (not a ``SimulabilityResult``) so it composes
    directly inside ``check_full_simulability`` -- unlike
    ``check_size_and_resolution``, which is also used standalone.
    """
    if entry.n_unmodeled_residues is None or not entry.n_residues:
        return ["completeness unknown (modeled/unmodeled residue counts missing)"]
    unmodeled_fraction = entry.n_unmodeled_residues / entry.n_residues
    if unmodeled_fraction > max_unmodeled_fraction:
        return [
            f"{entry.n_unmodeled_residues}/{entry.n_residues} residues unmodeled "
            f"({unmodeled_fraction:.0%} > {max_unmodeled_fraction:.0%})"
        ]
    return []


def check_oligomeric_state(
    assembly_info: AssemblyInfo, max_oligomeric_count: int | None = None
) -> list[str]:
    """L2 gate: reject overly complex oligomers, if a ceiling is set.

    Informational by default (``max_oligomeric_count=None`` => no ceiling,
    never fails) -- PLAN.md doesn't mandate a specific pedagogical rule here,
    and many good teaching structures are dimers/tetramers. Set a ceiling to
    actively prefer simpler oligomers for an intro exercise.
    """
    if assembly_info.oligomeric_count is None:
        return ["oligomeric state unknown"]
    if (
        max_oligomeric_count is not None
        and assembly_info.oligomeric_count > max_oligomeric_count
    ):
        return [
            f"oligomeric count {assembly_info.oligomeric_count} "
            f"({assembly_info.oligomeric_details}) > {max_oligomeric_count}"
        ]
    return []


def check_non_standard_residues(
    entity_infos: list[EntityCompositionInfo], allow_non_standard: bool = True
) -> list[str]:
    """L2 gate: reject non-standard residues, unless explicitly allowed.

    Informational by default (``allow_non_standard=True`` => never fails) --
    many good teaching structures use minor substitutions (e.g. SeMet/MSE for
    phasing). Set ``allow_non_standard=False`` to require a fully
    canonical-residue structure.
    """
    if allow_non_standard:
        return []
    flagged = [info for info in entity_infos if info.nstd_monomer]
    if not flagged:
        return []
    summary = ", ".join(
        f"entity {info.entity_id} ({info.non_std_monomer_count} non-standard)"
        for info in flagged
    )
    return [f"non-standard residues present: {summary}"]


def check_full_simulability(
    entry: CandidateEntry,
    assembly_info: AssemblyInfo | None = None,
    entity_infos: list[EntityCompositionInfo] | None = None,
    min_residues: int = 50,
    max_residues: int = 300,
    max_resolution: float = 2.5,
    max_unmodeled_fraction: float = 0.1,
    max_oligomeric_count: int | None = None,
    allow_non_standard_residues: bool = True,
) -> SimulabilityResult:
    """Full L2 gate: composes all four checks into one ``SimulabilityResult``.

    ``assembly_info``/``entity_infos`` are optional and, when absent, those
    two checks are SKIPPED, not failed -- they need composition.py's separate
    assembly/entity-level fetch (``fetch_oligomeric_state``/
    ``fetch_non_standard_residues``), which a caller may not have run yet.
    This is a deliberately different situation from ``entry.n_residues is
    None``: that field is data L1's OWN fetch should always provide, so its
    absence signals a fetch problem and DOES fail (see
    ``check_size_and_resolution``); a missing ``assembly_info`` just means
    "this check hasn't been run," not "it failed."
    """
    reasons = list(
        check_size_and_resolution(
            entry,
            min_residues=min_residues,
            max_residues=max_residues,
            max_resolution=max_resolution,
        ).reasons
    )
    reasons += check_completeness(entry, max_unmodeled_fraction=max_unmodeled_fraction)

    if assembly_info is not None:
        reasons += check_oligomeric_state(
            assembly_info, max_oligomeric_count=max_oligomeric_count
        )
    if entity_infos is not None:
        reasons += check_non_standard_residues(
            entity_infos, allow_non_standard=allow_non_standard_residues
        )

    return SimulabilityResult(pdb_id=entry.pdb_id, passed=not reasons, reasons=reasons)


def filter_simulable(
    entries: list[CandidateEntry],
    min_residues: int = 50,
    max_residues: int = 300,
    max_resolution: float = 2.5,
) -> tuple[list[CandidateEntry], list[SimulabilityResult]]:
    """Apply the L2 size/resolution gate to a batch of L1 survivors.

    Returns (entries that passed, results for every entry) -- the full results
    list is kept so a failing entry's ``reasons`` can still be surfaced in the
    output table's rationale, per PLAN.md §8 ("never just a pass/fail bit").

    Uses ``check_size_and_resolution`` only (no completeness/oligomeric-state/
    non-standard-residue checks) -- this function predates those and is kept
    as the simple, no-extra-fetch entry point. Use ``check_full_simulability``
    directly (per-entry) once ``composition.py``'s assembly/entity fetches are
    wired into a caller that has that data available.
    """
    results = [
        check_size_and_resolution(
            entry,
            min_residues=min_residues,
            max_residues=max_residues,
            max_resolution=max_resolution,
        )
        for entry in entries
    ]
    passed = [
        entry for entry, result in zip(entries, results, strict=True) if result.passed
    ]
    return passed, results

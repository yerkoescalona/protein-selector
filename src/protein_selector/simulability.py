"""L2 simulability checks: cheap, metadata-only gates on L1 survivors.

Per PLAN.md §3/§10 step 2, L2 tightens L1's coarse SQL-side filters (resolution
ceiling, atom-count ceiling) and adds the residue-count window PLAN.md §13
assumes for the Colab compute budget (~100-300 aa).

Implemented here, using only CandidateEntry fields L1 (candidates.py) already
fetches -- no additional network calls:

- Residue-count window and tightened resolution ceiling.

Deliberately NOT implemented yet (PLAN.md §3 also lists these under L2):

- Missing-loop/gap completeness (needs per-entry unobserved/zero-occupancy
  residue data -- likely the mmCIF `pdbx_unobs_or_zero_occ_residues` category,
  but the exact RCSB GraphQL field name is unverified against the live schema
  in this session; see PLAN.md §4b's Holdings-API caveat for the same
  no-network-access situation).
- Non-standard residues (needs per-entity/per-instance monomer composition,
  not yet fetched by L1).
- Oligomeric state (needs assembly-level chain-count data, e.g. something like
  `rcsb_assembly_info.polymer_entity_instance_count` -- name unverified).

Per PLAN.md §11 (anti-hallucination gate): do not hardcode an unverified RCSB
field name into a fetch call. Verify each against the live GraphQL schema (once
network access is available) before extending `candidates._ENTRY_RETURN_FIELDS`
or adding a new per-entity fetch, then implement the corresponding check here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from protein_selector.candidates import CandidateEntry


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

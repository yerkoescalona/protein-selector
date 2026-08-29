# Brief: tighten "organic ligand" filter + pre-MD gate for docking shortlist

## Problem 1 — "organic" ligand filter is too permissive

`src/protein_selector/docking/native_ligand.py::pick_largest_organic_ligand` defines
"organic" as "passed Meeko parameterization." Small polyatomic crystallization ions
(nitrate NO3, sulfate SO4, phosphate PO4, etc.) have real covalent bonds, so they pass
Meeko's chemistry checks even though they aren't meaningful biological ligands. Confirmed
live: `1LKS`/`1V7S` (both nitrate-only structures) were picked as "organic" and reached
`docking: success` in `cache/protein_selector.db`.

**Fix:** add an explicit denylist of common crystallization/counter-ion CCD codes
(NO3, SO4, PO4, CL, GOL, EDO, PEG, ACT, TRS, MES, ...) applied *before* the Meeko-passed
filter in `pick_largest_organic_ligand`, so these are excluded regardless of whether
RDKit/Meeko can parameterize them. See `scripts/course_candidates.sql`'s
`excluded_ccd_codes` CTE for a maintained reference list already used elsewhere in this
repo for the same judgment call.

## Problem 2 — PLIP zero-interaction cases may be real strictness, not a selection bug

Confirmed (via `stages/docking_common.py::resolve_docking_target` +
`nodes/dock_ligand.py::dock_ligand`): the receptor passed to PLIP is the MD-relaxed,
PDBFixer-heterogen-stripped structure, and only the ONE selected native ligand is aligned
back in — so `plip_analysis.py`'s `complex_.ligands[0]` is not grabbing a stray ion (ruled
this out; an earlier draft of this brief wrongly suspected it). 3 real candidates (186L,
1JJ9, 2B03) have excellent self-dock RMSD (0.65-1.65 Å) but PLIP reports zero interactions
of ANY kind, including `hydrophobic_contacts` — implausible for e.g. 186L, a T4 lysozyme
structure specifically about hydrophobic-cavity binding. Worth investigating PLIP's
distance/angle cutoffs, or treating "good RMSD, zero PLIP interactions" as a softer
pass/warn state rather than an outright `docking_quality` failure.

## Problem 3 — MD runs on candidates that can never pass docking anyway

`dock_ligand` requires `md_simulation` to have already succeeded (needs the
MD-relaxed structure as receptor, PLAN.md §18) — correct dependency order. But nothing
currently checks, *before* spending MD compute, whether a candidate even HAS an organic
(post-fix, non-ion) ligand. Since MD is the slow stage and ligand-agnostic (strips all
heterogens for its own protein-stability check), add a cheap pre-MD gate for the
docking-shortlist workflow specifically: skip MD for candidates with no
Meeko-parameterizable, non-denylisted ligand, since `resolve_docking_target` will reject
them at the docking stage regardless. Do NOT apply this gate to candidates only intended
for the standalone MD (ex03) exercise, which doesn't need a ligand at all.

## Reference

Reusable query for "real ligand" + full-pipeline-success candidates:
`scripts/course_candidates.sql`.

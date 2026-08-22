# Candidate assignment by topic + repeat-family distribution (2026-07-22)

Companion to `scripts/candidates_table_2026-07-20.md`'s 38-row full-pipeline set
(`md_simulation` + `docking` + `complex_md_simulation` all `success`). **Excludes rows
whose validated ligand is a crystallization/buffer artifact or a small molecule with no
real biological relevance to the protein** (see "Excluded rows" below for the full list
and reasoning) — 29 of the original 38 rows remain. Grouped by scientific topic, broad
group ordered from things students already have everyday intuition for toward more
abstract, purely protein-science topics — and *within* each group, rows that share the
same protein family or sub-theme (HIV protease, DHFR, Ras-GTPases, ...) are clustered
together explicitly. Judgment call, not derived from any DB field — re-evaluate if
teaching priorities shift.

**Rule for assigning:** within any cluster below, give at most one row to any one
student before doubling back to that cluster. If two students do end up in the same
cluster, tell them explicitly and reframe it as a comparison exercise rather than letting
it look like accidental duplication. Spread assignments across the lettered groups
first, then work within a group's clusters.

## Excluded rows (9 of 38) — artifact or no real biological relevance

| PDB ID | Ligand | Why excluded |
|---|---|---|
| 1HH7 | NH3 (ammonia) | Most plausibly a crystallization/buffer artifact near the heme edge, unrelated to cytochrome c2's electron-shuttle function. |
| 1RCE | BET (betaine) | Most plausibly a cryoprotectant artifact; ferritin's real biology (iron storage) isn't represented by this ligand at all. |
| 1VSF | EPE (HEPES) | A crystallization/purification buffer molecule, not a physiological integrase ligand. |
| 1P2S | ETF (trifluoroethanol) | A crystallization solvent — Ras's real ligand (GppNHp) was present in the crystal but failed the pipeline's parameterization check and isn't what got docked. |
| 1RWE | IPH (phenol) | A hexameric-insulin formulation/stabilizing agent, not a physiological ligand of this receptor-affinity-analogue construct. |
| 1O4M | MLA (malonic acid) | A small dicarboxylic-acid crystallization probe occupying the pTyr pocket — no physiological role for Src SH2. |
| 2PUO | NEQ (N-ethylmaleimide) | A cysteine-alkylating chemical reagent used to covalently modify the enzyme, not a reversible physiological ligand. |
| 2RB1 | 261 (2-ethoxyphenol) | Synthetic probe in the engineered T4 lysozyme L99A cavity — real biophysics, but the ligand itself has no natural biological role for this enzyme (its actual substrate is peptidoglycan). |
| 1OWY | PRY (2-propylaniline) | Same engineered-cavity system as 2RB1 (L99A/M102Q variant) — same reasoning, synthetic probe with no natural biological role. |

If you still want the T4 lysozyme cavity-mutant pair (2RB1/1OWY) for teaching binding
*thermodynamics* specifically (a legitimate, widely published use of this system, just
not "biological relevance" in the sense used here), they're easy to add back — see the
previous revision of this file in git history.

## A. Things students already recognize from daily life (4 rows, all singletons)

- **2WC6** — bombykol, the actual silk-moth sex pheromone, bound to its transport
  protein. Smell/pheromone biology, vivid with no chemistry background needed.
- **1HBP** — retinol (vitamin A) bound to its natural blood transport protein.
  Nutrition/vision-biology hook.
- **1LHN** — a natural androgen metabolite bound to sex hormone-binding globulin (SHBG),
  its genuine hormone-transport carrier.
- **2PK4** — epsilon-aminocaproic acid, a real antifibrinolytic drug, blocking
  plasminogen's lysine-binding site. Blood-clotting/first-aid relevance.

## B. Real medicines (11 rows, 3 clusters)

**Cluster B1 — HIV-1 protease inhibitors (5 rows, same enzyme/fold, 5 different
inhibitor chemotypes — assign at most one per student):**
- **3EKQ** — saquinavir, the first FDA-approved HIV protease inhibitor, vs. a real
  multi-drug-resistant clinical mutant. Strongest single hook in this cluster.
- **2O4N** — tipranavir, a second, structurally distinct approved HIV drug.
- **1FG6** — a peptidomimetic substrate-analogue inhibitor vs. a drug-resistant mutant.
- **1MEU** — DMP323, a non-peptidic cyclic-urea inhibitor, vs. a double mutant.
- **2WKZ** — a designed tertiary-alcohol transition-state-mimic inhibitor ("AHA599").

**Cluster B2 — DHFR / antifolate drugs (3 rows, same fold/mechanism — assign at most
one):**
- **3EIG** — methotrexate (chemotherapy/autoimmune-disease drug) vs. a
  methotrexate-resistant human DHFR mutant — drug + resistance mechanism in one
  structure.
- **3F0X** — a trimethoprim-class antibiotic (common UTI-antibiotic ingredient family)
  bound to *S. aureus* DHFR.
- **2FZJ** — the same trimethoprim-derivative class bound to mouse DHFR — pairs with
  3F0X for a species-selectivity comparison if deliberately assigning both.

**Cluster B3 — other antibacterial/anti-inflammatory drug targets (3 rows, unrelated to
each other, no repeat risk):**
- **1LQY** — actinonin, a natural-product antibiotic, vs. peptide deformylase.
- **1GRQ** — a chloramphenicol analogue vs. an antibiotic-resistance enzyme — topical
  antimicrobial-resistance angle.
- **1RMZ** — a designed inhibitor of human MMP-12, relevant to emphysema/vascular
  disease drug design.

## C. Disease biology and cell signaling (4 rows, 2 clusters)

**Cluster C1 — Ras-superfamily GTPase + GDP (3 rows, identical ligand, 3 different
GTPases — assign at most one):**
- **2QUZ** — H-Ras carrying K117R, a real human disease mutation (Costello syndrome).
- **1KAO** — Rap2A, same GDP-bound chemistry in a cell-adhesion-signaling GTPase.
- **2W2T** — Rac2 G12V, same GDP-bound chemistry in a cytoskeleton/immune-signaling
  GTPase.

**Cluster C2 — topical virology (1 row, singleton):**
- **3EWR** — a coronavirus (HCoV-229E) macrodomain with its natural ADP-ribose
  substrate — real antiviral-target biology.

## D. Classic enzyme mechanism (9 rows, 4 clusters)

**Cluster D1 — mutant-trapped substrate/product enzymes (2 rows, same "catalytically
dead mutant traps its own reaction chemistry" strategy):**
- **1JD3** — chorismate lyase trapped with its real reaction product (ubiquinone
  biosynthesis).
- **2JAC** — yeast glutaredoxin trapped with its real glutathione cosubstrate. Good to
  pair with 1JD3 as a "how do you catch an enzyme mid-reaction" comparison.

**Cluster D2 — small-molecule/lipid binding proteins (2 rows, unrelated proteins, same
general "carrier protein + its cargo" theme):**
- **1KQU** — human secreted phospholipase A2 + a fatty-acid-like substrate analogue.
- **2QO6** — a bile-acid binding protein + cholic acid, its genuine cargo.

**Cluster D3 — phospho-recognition signaling domains (2 rows, same general
"phosphorylated-ligand recognition module" theme):**
- **1O4B** — Src SH2 domain + a large designed bisphosphonate phosphotyrosine mimetic.
- **1W1D** — a PDK1 PH domain + its real physiological ligand, a phosphoinositide
  headgroup (IP4) — same "phospho-group recognition" theme, different domain family
  (PH vs. SH2) and here the ligand is genuine natural cargo, not a designed probe.

**Cluster D4 — singletons, no repeat risk (3 rows):**
- **1SYB** — staphylococcal nuclease + a nucleotide substrate/product analogue.
- **2JDC** — a glyphosate-resistance enzyme + oxidized coenzyme A — real agricultural
  biotechnology relevance.
- **2FKE** — FKBP12 (an immunophilin) + a large FK506-analogue antagonist — good "big,
  chemically complex ligand" case.

## E. Protein biophysics and real redox chemistry (1 row)

- **2VLZ** — a real redox intermediate (H2O2-driven myoglobin chemistry) — narrower and
  more specialized than most groups above, but a genuine biological reaction, not an
  artifact.

## How to use this for assignment

1. Assign across groups A–E first, one student per row, so the class samples different
   kinds of biology rather than clustering around whichever group is biggest.
2. Within any cluster (the bolded sub-lists above), give at most one row per student
   before doubling back to that same cluster.
3. Once every singleton row and every cluster across A–E has at least one assignee, only
   then double up within a cluster — and when doubling up, tell both students explicitly
   and reframe as a comparison assignment.

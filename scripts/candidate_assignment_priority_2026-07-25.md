# Candidate assignment by topic + repeat-family distribution (2026-07-25)

Supersedes `scripts/candidate_assignment_priority_2026-07-22.md`. Rebuilt from scratch
against the current `cache/protein_selector.db` (after merging a second external cache on
2026-07-25) using `scripts/course_candidates.sql` with both `dock.status = 'success'` and
`cmd.status = 'success'` uncommented — every row below has a real organic ligand and has
completed `md_simulation` + `docking` + `complex_md_simulation`, all three `success`. The
query now returns **88** candidates (up from 38 on 2026-07-22; all 38 previous rows are
still present, confirmed by diffing PDB ID sets before writing this file). Every new PDB
ID was live-fetched the same way as before (`scripts/student_ligand_table_prompt.md`'s
method: real RCSB PDB file for chain/COMPND/SOURCE, RCSB chemcomp API for ligand
chemistry, `meeko_parameterization` to resolve which ligand the pipeline actually docked
when several were present in the crystal).

**Excludes rows whose validated ligand is a crystallization/buffer artifact or a small
molecule with no real biological relevance to the protein** (same criterion as the
previous revision — see "Excluded rows" below). **20 of the 88 rows are excluded, leaving
68.**

**Rule for assigning:** within any cluster below, give at most one row to any one student
before doubling back to that cluster — three clusters are now large enough (7–12 rows)
that this matters a lot more than it did on 2026-07-22. If two students end up in the
same cluster, tell them explicitly and reframe it as a comparison exercise. Spread
assignments across the lettered groups first, then work within a group's clusters.

## Excluded rows (20 of 88) — artifact or no real biological relevance

**Carried over from the 2026-07-22 revision (9):** 1HH7 (NH3, buffer artifact), 1RCE
(BET, cryoprotectant), 1VSF (EPE/HEPES, buffer), 1P2S (ETF, solvent — Ras's real ligand
GppNHp failed parameterization here), 1RWE (IPH, insulin-formulation phenol), 1O4M (MLA,
crystallization probe in the SH2 pocket), 2PUO (NEQ, covalent chemical-modification
reagent), 2RB1 (261) and 1OWY (PRY) — both T4 lysozyme L99A engineered-cavity probes.

**New in this revision (11):**

| PDB ID | Ligand | Why excluded |
|---|---|---|
| 3G26 | MLA (malonic acid) | Bound to a Rous sarcoma virus capsid C-terminal domain dimerization mutant — no known biological role for malonic acid here; almost certainly a crystallization additive. |
| 1RUV | TBU (tert-butyl alcohol) | The entry's real story is a uridine-vanadate transition-state-analog complex, but TBU (a crystallization solvent) is what actually passed Meeko/got docked, not the vanadate complex. |
| 1V30 | NHE (CHES buffer) | A buffer molecule on an uncharacterized archaeal protein — no stated biological role. |
| 1VSI | EPE (HEPES) | Same buffer-artifact case as 1VSF (identical protein, ASV integrase core domain). |
| 2HX5 | ETX (2-ethoxyethanol) | A solvent-like small molecule on a putative thioesterase — no natural substrate relationship established. |
| 1OV7 | LYL (2-allyl-6-methyl-phenol) | T4 lysozyme L99A/M102Q engineered-cavity probe — same reasoning as 2RB1/1OWY (real biophysics, but the ligand has no natural biological role for lysozyme). |
| 1OWZ | 4FA (4-fluorophenethyl alcohol) | Same T4 lysozyme L99A/M102Q engineered cavity as 1OV7. |
| 2F32 | EGD (N-ethylguanidine) | A small guanidinium probe in an engineered lysozyme mutant (L20/R63A) — same "designed probe, no natural role" logic as the T4 lysozyme cavity rows. |
| 2BF3 | HTO (heptane-1,2,3-triol) | A cryoprotectant polyol on a monooxygenase effector protein — no biological role. |
| 2BBR | AZI (azide ion) | Bound to a viral apoptosis-inhibitor death-effector domain that works via protein-protein interaction, not small-molecule binding — azide here is almost certainly a crystallization additive. |
| 207L | SC2 (N-acetylcysteine) | A soak reagent probing an engineered free cysteine (C77A mutant) in human lysozyme — no natural biological role for lysozyme itself, same logic as excluding 1O4M/2PUO. |

## Repeat-family map — 3 large clusters need extra care

| Cluster | Size | PDB IDs |
|---|---|---|
| HIV-1 protease | **12** | 1FG6, 1MEU, 2O4N, 2WKZ, 3EKQ, 1QBR, 1QBU, 2HS2, 2IEN, 2P3C, 2QD8, 2Z4O |
| Ras-superfamily GTPase + nucleotide | **9** | 2QUZ, 1KAO, 2W2T, 1CTQ, 1ZW6, 1X1S, 1XTQ, 1Z22, 1R2Q |
| Dihydrofolate reductase (DHFR) | **7** | 3F0X, 2FZJ, 3EIG, 1DR3, 1OHJ, 1RX7, 3F91 |

These three clusters alone are 28 of the 68 kept rows — resist the temptation to fill a
big class roster mostly from these three just because they have the most rows available;
spread out into the smaller clusters and singletons first.

## A. Things students already recognize from daily life (9 rows, 3 clusters + 2 singletons)

**Cluster A1 — pheromone/chemosignaling proteins (2 rows, different species/senses,
good pair):**
- **2WC6** — bombykol, the actual silk-moth sex pheromone, bound to its insect
  odorant-binding transport protein.
- **1QY2** — a mouse pheromone-type odorant (2-isopropyl-3-methoxypyrazine) bound to
  Major Urinary Protein, the rodent analogue of an odorant/pheromone carrier — a direct
  mammalian counterpart to 2WC6's insect system.

**Cluster A2 — retinol-binding protein family (2 rows, same protein family, 2 species,
different ligand):**
- **1HBP** — bovine plasma retinol-binding protein + retinol (vitamin A), its classic
  natural cargo.
- **2WQ9** — the human orthologue, RBP4, bound instead to oleic acid (a common dietary
  fatty acid) — a real alternate-lipid complex, though retinol (not oleic acid) is RBP4's
  primary physiological cargo; flag that distinction if assigning both.

**Cluster A3 — SHBG + natural steroid hormones (2 rows, same protein, 2 different
natural androgens):**
- **1LHN** — SHBG's N-terminal domain + 5-alpha-androstane-3-beta,17-alpha-diol, a
  natural androgen metabolite.
- **1D2S** — the same domain + dihydrotestosterone (DHT), the more potent natural
  androgen — direct comparison of two real hormones in the same binding site.

**Singletons:**
- **2F8P** — Obelin, a Ca²⁺-triggered bioluminescent photoprotein from a jellyfish
  relative, captured with its actual light-emitting chromophore (coelenteramide) right
  after triggering bioluminescence. Vivid "why does this jellyfish glow" hook.
- **2PK4** — epsilon-aminocaproic acid, a real antifibrinolytic drug, blocking
  plasminogen's lysine-binding site.

## B. Real medicines (24 rows, 5 clusters)

**Cluster B1 — HIV-1 protease inhibitors (12 rows — by far the largest cluster in this
whole set; assign at most one or two per student, ever):**
- **3EKQ** — saquinavir, the first FDA-approved HIV protease inhibitor, vs. a real
  multi-drug-resistant clinical mutant. Strongest single hook.
- **2HS2** and **2IEN** — **darunavir** (ligand code 017; 2IEN's crystal calls it by its
  development code UIC-94017), a current front-line approved HIV protease inhibitor,
  bound to two different resistance mutants (M46L in 2HS2). Arguably the single best
  "real, current medicine" row in this entire cluster — pick this before the others if
  only assigning one.
- **2O4N** — tipranavir, a second, structurally distinct approved HIV drug.
- **2P3C** — the "TL-3" peptidomimetic inhibitor vs. subtype F HIV-1 protease.
- **2QD8** and **2Z4O** — GRL-98065, an experimental potent non-peptidic inhibitor, vs.
  an I84V resistance mutant (2QD8) and wild-type (2Z4O) — a clean mutant-vs-wild-type
  comparison pair if deliberately assigning both.
- **1QBR** and **1QBU** — two more nanomolar-potency experimental inhibitors from the
  same discovery paper, different diazepinone-class chemotypes.
- **1FG6**, **1MEU**, **2WKZ** — the remaining rows from the 2026-07-22 revision
  (peptidomimetic, cyclic-urea DMP323, tertiary-alcohol AHA599).

**Cluster B2 — DHFR / antifolate drugs (7 rows, same fold/mechanism — assign at most
one, maybe two for an explicit species-comparison pair):**
- **3EIG** — methotrexate vs. a methotrexate-resistant human DHFR mutant.
- **1RX7** — *E. coli* DHFR bound to **folate itself**, the enzyme's genuine natural
  substrate (not an inhibitor) — the cleanest "real substrate, not a drug" row in this
  cluster, good contrast to the rest.
- **1OHJ** — human DHFR + PT523, a designed lipophilic antifolate.
- **1DR3** — chicken liver DHFR + thio-NADP⁺ and biopterin — a cofactor-analogue
  complex, different angle (cofactor chemistry, not substrate/inhibitor).
- **3F0X**, **2FZJ**, **3F91** — trimethoprim-class inhibitors vs. *S. aureus*, mouse,
  and a human active-site mutant respectively.

**Cluster B3 — other antibacterial/antifungal drug targets (3 rows, unrelated to each
other):**
- **2IYS** — *Mycobacterium tuberculosis* shikimate kinase + shikimate, its genuine
  natural substrate — a validated TB drug target (shikimate pathway is absent in
  humans).
- **1STD** — scytalone dehydratase from the rice blast fungus + a designed inhibitor —
  a real agricultural fungicide target (melanin biosynthesis).
- **1LQY** — actinonin (natural-product antibiotic) vs. peptide deformylase.

**Cluster B4 — other real drug-design cases (2 rows):**
- **1RMZ** — a hydroxamate inhibitor of human MMP-12 (emphysema/vascular disease
  target).
- **1GRQ** — a chloramphenicol analogue vs. an antibiotic-resistance enzyme.

## C. Disease biology and cell signaling (10 rows, 2 clusters)

**Cluster C1 — Ras-superfamily GTPase + nucleotide (9 rows, the second-largest cluster
in this set — assign at most one, or two as an explicit comparison):**
- **1ZW6** — H-Ras Q61G, one of the most famous oncogenic Ras hotspot mutations in
  cancer biology, GTP-analogue (GppNHp)-bound "on" state. Strongest single hook in this
  cluster.
- **2QUZ** — H-Ras K117R, a real human disease mutation (Costello syndrome), GDP-bound
  "off" state — pairs directly with 1ZW6 for an on-state/off-state comparison in the
  same protein.
- **1CTQ** — wild-type H-Ras + GppNHp at 100 K, the reference "on" state structure.
- **1XTQ** — Rheb, the small GTPase that directly activates mTORC1 — real
  growth-signaling/cancer-pathway relevance, GDP-bound.
- **1X1S** — M-Ras + GppNHp, a third Ras-family paralogue.
- **1R2Q** — Rab5a, a vesicle-trafficking GTPase, GppNHp-bound, solved at very high
  (1.05 Å) resolution.
- **1Z22** — Rab23, another vesicle-trafficking GTPase, GDP-bound.
- **1KAO** — Rap2A + GDP (cell-adhesion signaling).
- **2W2T** — Rac2 G12V (cytoskeleton/immune signaling), GDP-bound.

**Cluster C2 — topical infectious-disease/virulence proteins (1 row, singleton):**
- **3EWR** — a coronavirus (HCoV-229E) macrodomain with its natural ADP-ribose
  substrate.

**Singleton:**
- **1Y9T** — MxiM, a *Shigella flexneri* type-III-secretion-system lipoprotein, bound to
  a real lysophospholipid — T3SS is a major bacterial-virulence-machine topic, and this
  is a genuine regulatory-lipid complex, not an incidental ligand.

## D. Classic enzyme mechanism (21 rows, 7 clusters)

**Cluster D1 — mutant-trapped substrate/product enzymes (2 rows):**
- **1JD3** — chorismate lyase trapped with its real reaction product.
- **2JAC** — yeast glutaredoxin trapped with its real glutathione cosubstrate.

**Cluster D2 — fatty-acid/lipid-binding protein (FABP/PLA2) family (4 rows, natural
cargo vs. designed inhibitor in the same protein family — good comparison set):**
- **2QO6** — a bile-acid binding protein + cholic acid, genuine natural cargo.
- **3FR2** — human adipocyte FABP4 + a designed FABP4 inhibitor (real diabetes/metabolic
  drug-design target) — direct natural-cargo-vs-designed-inhibitor contrast with 2QO6 in
  the same protein superfamily.
- **1KQU** — human secreted PLA2 + a fatty-acid-like substrate analogue.
- **2AZZ** — porcine pancreatic PLA2 + taurocholate, a real bile salt that activates PLA2
  in the gut — same enzyme family as 1KQU, different organism and a physiological
  activator rather than a substrate analogue.

**Cluster D3 — phospho-recognition signaling domains (3 rows):**
- **1O4B** — Src SH2 domain + a large designed bisphosphonate phosphotyrosine mimetic.
- **1IJR** — the closely related Lck SH2 domain (same Src-family kinase group) + a
  different nonpeptide phosphotyrosine mimetic — direct comparison to 1O4B across two
  Src-family kinases.
- **1W1D** — a PDK1 PH domain + its real physiological ligand, a phosphoinositide
  headgroup (IP4).

**Cluster D4 — nucleic-acid-cleaving enzymes + nucleotide product/analogue (4 rows,
comparable but not identical mechanisms — assign at most one or two):**
- **1RSN** — *Streptomyces* ribonuclease SA + a real 2',3'-cyclic-phosphorothioate
  transition-state mimic — directly illustrates this RNase family's actual catalytic
  mechanism.
- **1UCD** — a plant (bitter gourd) ribonuclease + its real reaction product, 5'-UMP.
- **1SYB** and **3ERO** — the *same* staphylococcal nuclease system (two different
  engineered variants) bound to the identical nucleotide analogue (THP) — pick only one
  of these two, they're near-duplicates.

**Cluster D5 — adenine phosphoribosyltransferase (APRT), human vs. parasite ortholog (2
rows, strong antiparasitic-drug-design comparison):**
- **1ORE** — human APRT + AMP, the genuine reaction product (APRT deficiency is a real
  human disease causing kidney stones).
- **1L1R** — the *Giardia lamblia* (a real human parasite) orthologue + PRPP, the
  genuine cosubstrate — direct human-vs-pathogen enzyme comparison, relevant to
  selective antiparasitic drug design.

**Cluster D6 — acetyltransferases + coenzyme A (2 rows):**
- **2JDC** — a glyphosate-resistance enzyme + oxidized CoA (agricultural biotech).
- **3F0A** — a putative archaeal N-acetyltransferase + acetyl-CoA, its genuine acyl-donor
  cosubstrate.

**Singletons (4 rows, no repeat risk):**
- **1SJW** — SnoaL, a polyketide cyclase from a natural-product (nogalamycin antibiotic)
  biosynthesis pathway, bound to a real late-pathway intermediate analogue.
- **2HL0** — the editing (proofreading) domain of an archaeal threonyl-tRNA synthetase +
  a substrate analogue — a direct illustration of translational-fidelity proofreading
  chemistry.
- **1X7N** — an archaeal phosphoglucose isomerase + a sugar-phosphate substrate
  analogue, core carbohydrate metabolism.
- **1Z4I** — human mitochondrial deoxyribonucleotidase (a real nucleotide-metabolism
  disease enzyme) + its natural substrate, dUMP.
- **2FKE** — FKBP12 (an immunophilin) + a large FK506-analogue antagonist.

## E. Protein biophysics and real redox chemistry (3 rows, 1 cluster)

**Cluster E1 — myoglobin ligand-binding/redox chemistry (2 rows, same protein, two
different exogenous small-molecule ligands probing heme-pocket chemistry):**
- **2VLZ** — horse myoglobin + hydrogen peroxide, a real reactive-oxygen redox
  intermediate (peroxymyoglobin).
- **2MYC** — sperm whale myoglobin + n-butyl isocyanide, a classic CO/O2-mimic ligand
  used to probe steric effects in the heme pocket.

**Singleton:**
- **2FAC** — *E. coli* acyl carrier protein loaded with its real acyl-phosphopantetheine
  cargo (a hexanoyl thioester) — the genuine "working" state of fatty-acid-synthase
  carrier chemistry.

## How to use this for assignment

1. Assign across groups A–E first, one student per row, so the class samples different
   kinds of biology rather than clustering around the three big clusters (HIV protease,
   Ras-GTPases, DHFR) just because they have the most rows.
2. Within any cluster (the bolded sub-lists above), give at most one row per student
   before doubling back to that same cluster — this matters far more this round given
   the 7–12-row clusters.
3. Once every singleton row and every smaller cluster across A–E has at least one
   assignee, only then reach further into the three big clusters — and when doubling up
   anywhere, tell both students explicitly and reframe as a comparison assignment.

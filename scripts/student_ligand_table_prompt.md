# Prompt: build a student-facing protein/chain/ligand table

Reusable recipe for turning `cache/protein_selector.db` candidates into an accurate,
no-ambiguity table for students doing the MD/docking exercises. Feed the "Prompt" section
below to an agent; the "Method" section is the checklist the agent should actually follow
(don't skip steps 2/3 — that's where the real mistakes are).

## Prompt

> Build a table for students with columns: protein number, protein ID, protein name,
> protein description, chain, residue count, ligand code, ligand description, and a
> plain-language description of the protein-ligand relationship. Use the N candidates from
> `scripts/course_candidates.sql` (uncomment `dock.status = 'success'` for only
> full-pipeline-confirmed ones). For each candidate: fetch the real PDB file from RCSB to
> get the actual chain ID(s) and COMPND protein name (don't guess "chain A" — some entries
> have multiple chains or unusual numbering). Fetch each ligand's real name/formula from
> RCSB's chemcomp REST API (don't describe ligand chemistry from memory). Cross-check
> `meeko_parameterization` for candidates with multiple non-polymer entities in the crystal
> — the ligand this pipeline actually validated/docked may not be the first/most obvious
> HETATM code, and students need to be told explicitly which one to use. Flag any such
> ambiguity in the table, don't silently resolve it. Follow the "Table specification"
> section below exactly for column order, content rules, and output format — don't
> improvise column meanings or add/drop columns.

## Table specification

Output ONE markdown table, one row per candidate, columns in this exact order. No merged
cells, no nested tables — if a cell needs a caveat, put it in that cell in parentheses or
as a trailing sentence, not a footnote students might miss.

| # | Column | Content rule |
|---|---|---|
| 1 | **#** | Sequential integer, 1..N, in the same order as the query result (residue count ascending, unless the table is explicitly re-sorted for teaching order — state which if so). This is the number students use to refer to "their" structure, so it must be stable across re-runs of the same query — don't renumber between drafts once shared with students. |
| 2 | **PDB ID** | The 4-character RCSB accession, uppercase, bold. This is the only column a student needs to fetch the real structure (`fetch {ID}` in PyMOL, or `https://files.rcsb.org/download/{ID}.pdb`) — must be exactly correct, this is the highest-consequence cell in the table. |
| 3 | **Protein Name** | The `COMPND MOLECULE:` value from the live-fetched PDB file, title-cased, plus the EC number in parens if `COMPND EC:` is present. Not the RCSB entry *title* (that describes the whole deposited experiment, e.g. "CRYSTAL STRUCTURE OF X COMPLEXED WITH Y" — too long and redundant with columns 8-9). |
| 4 | **Protein Description** | 1-2 sentences: organism (italicized binomial), broad biological role (textbook-level, e.g. "hydrolyzes bacterial peptidoglycan"), and anything pedagogically special about this specific construct (engineered mutant, cavity variant, etc., from the entry title/COMPND `ENGINEERED:` field). Keep to facts traceable to the PDB entry or well-established textbook biology — no speculation about *why* the depositors chose this ligand unless the entry title says so explicitly. |
| 5 | **Chain** | The exact protein chain letter(s) from `grep "^ATOM" ... awk '{print $5}'`, comma-separated if more than one. Never assume "A". If the ligand is on a different chain than the protein, say so here, not just in column 7. |
| 6 | **Residues** | Integer residue count from `candidates.n_residues` (already simulability-checked), cross-checked against the modeled-residue range in the live PDB file if there's any doubt about unmodeled loops. |
| 7 | **Ligand Code** | The exact 3-5 character CCD code students should select in their viewer — the ONE code the pipeline actually validated (per Method step 3 below), bolded. If the crystal has other HETATM codes present that are NOT the validated ligand (ions, buffer, a rejected alternate ligand), name them in a trailing parenthetical explicitly so students don't select the wrong one, e.g. "(crystal also contains HED, which failed parameterization — do not use)". |
| 8 | **Ligand Description** | Full chemical name + molecular formula + molecular weight, from RCSB's chemcomp API (Method step 4). One line, no interpretation yet — chemistry facts only, save biological interpretation for column 9. |
| 9 | **Protein–Ligand Relationship** | 2-4 sentences, grounded in the actual `validation.notes` evidence (self-dock RMSD + PLIP interaction-type counts, Method step 5) — name the specific interaction types found (e.g. "15 hydrophobic contacts, 0 H-bonds"), not a generic restatement of "binds in the active site." State plainly what kind of binding this is (catalytic substrate/product analog, structural cofactor, transport cargo, allosteric probe, crystallization artifact under study, etc.) and, if the PDB entry title itself makes a specific claim (e.g. "non-productive binding"), quote or reference it directly rather than paraphrasing loosely. |

Add one line immediately below the table (not inside it): a bolded "Important note for
students" callout listing any recurring gotchas (e.g. "always confirm you selected chain
A" or "watch for water/ion HETATMs that aren't the real ligand") — this is where general,
table-wide warnings belong, not repeated in every row's column 9.

## Method (what actually worked, 2026-07-19)

1. **Get the candidate list** from `scripts/course_candidates.sql` (or a raw query against
   `cache/protein_selector.db`'s `validation` table, `exercise='docking' AND status='success'`
   for the highest-confidence tier). Don't hand-pick from memory — always re-query, the DB
   is actively being filled and counts change between sessions.

2. **Fetch the real crystal PDB file for chain IDs and protein name** — don't infer from
   `candidates.polymer_entity_ids` (those are RCSB *entity* numbers, not chain letters, and
   this DB doesn't store chain letters anywhere):
   ```bash
   curl -s "https://files.rcsb.org/download/${PDB_ID}.pdb" > /tmp/${PDB_ID}.pdb
   grep "^ATOM" /tmp/${PDB_ID}.pdb | awk '{print $5}' | sort -u      # protein chain(s)
   grep "^HETATM" /tmp/${PDB_ID}.pdb | awk '{print $4, $5}' | sort -u  # (ligand code, chain)
   grep "^COMPND" /tmp/${PDB_ID}.pdb                                   # protein name, EC number
   ```

3. **Resolve which ligand was actually validated, if several are present in the crystal.**
   `ligand_ccd_codes` lists every non-polymer entity in the deposited structure, including
   crystallization additives and ions — NOT what the pipeline picked to dock. Cross-check
   `meeko_parameterization` (`passed=1`) for the specific CCD codes present; the pipeline's
   `pick_largest_organic_ligand` (see `src/protein_selector/domain/docking/native_ligand.py`)
   picks the largest Meeko-passing one. If a candidate has 2+ Meeko-passing ligands, or the
   HETATM list shows a code that failed Meeko, call this out explicitly in the table — this
   is exactly the kind of mistake a student will otherwise make (e.g. `186L` has both `HED`
   and `N4B` present; only `N4B` passed and was the one actually docked).

4. **Fetch real ligand chemistry from RCSB's Chemical Component Dictionary**, don't
   describe it from memory:
   ```bash
   curl -s "https://data.rcsb.org/rest/v1/core/chemcomp/${CCD_CODE}" | python3 -c "
   import json, sys
   d = json.load(sys.stdin)['chem_comp']
   print(d['name'], d['formula'], d['formula_weight'])
   "
   ```

5. **Pull the actual validation evidence** (self-dock RMSD, PLIP interaction counts) from
   `validation.notes` for `exercise='docking'` — use this to write the relationship
   description grounded in real numbers (e.g. "15 hydrophobic contacts, 0 H-bonds" for a
   cavity-binding case), not a generic restatement of the ligand's chemical class.

6. **State general protein function** (what the enzyme/transporter does biologically) as
   established textbook knowledge, clearly separated from the specific-complex facts in
   steps 2-5 which are all live-verified for this exact PDB entry.

## Anti-hallucination reminder

Same rule as this repo's `.claude/CLAUDE.md`: never invent a PDB ID, chain ID, CCD code,
or chemical name for this table. Every cell must trace to a live RCSB fetch, this repo's
own SQLite DB, or well-established textbook biology stated as such.

-- Reusable query: small(ish) proteins with a REAL organic ligand (no bare metal
-- ions, no metal clusters, no "hard to parametrize" cofactors, no small
-- polyatomic crystallization ions like nitrate/sulfate) that have ALSO
-- actually completed the full validation pipeline: MD simulation
-- (exercise="md_simulation"), AlphaFold DB modeling lookup (exercise="modeling"),
-- a real Vina self-dock + PLIP check (exercise="docking"), and optionally a real
-- receptor+ligand GAFF2/AMBER complex MD (exercise="complex_md_simulation",
-- PLAN.md §23a -- off by default, uncomment the cmd.status filter below).
--
-- Runs against the committed demo slice with no setup at all (88 rows there):
--   sqlite3 -header -column demo/protein_selector_demo.db < scripts/course_candidates.sql
-- or against a real run's own store:
--   sqlite3 -header -column cache/protein_selector.db < scripts/course_candidates.sql
--
-- Excludes (see protein-selector/.claude/CLAUDE.md "Bugs found via live
-- verification" -- this list is a judgment call, not derived from any schema
-- field, so revisit it by hand if the course's definition of "real ligand"
-- changes). **Kept in sync by hand with
-- src/protein_selector/domain/docking/native_ligand.py::_EXCLUDED_CCD_CODES** (one is
-- SQL, one is Python, no shared source -- re-verify both stay identical if
-- either changes):
--   * crystallization additives / cryoprotectants (SO4, GOL, EDO, PEG, ...)
--   * bare metal ions (FE, ZN, MG, CA, ...) -- single atom, not a real
--     protein-ligand *interaction* worth teaching
--   * small polyatomic crystallization ions (NO3, NO2) -- have real covalent
--     bonds so they pass RDKit/Meeko's chemistry checks cleanly, but aren't
--     meaningful biological ligands (confirmed live: 1LKS/1V7S, both
--     nitrate-only structures, reached docking:success before this fix)
--   * metal clusters and covalently-tricky cofactors (SF4, HEM, HEC, FAD,
--     FMN, BTN, COA, NAD, PLP, ...) -- real biology, but "too difficult to
--     parametrize" per instructor's explicit ask; drop if the course wants
--     to teach non-standard-residue/cofactor parametrization specifically.

WITH excluded_ccd_codes(ccd_code) AS (
  VALUES
    ('SO4'),('CL'),('NA'),('GOL'),('EDO'),('PO4'),('FMT'),('PEG'),('TRS'),
    ('MES'),('IPA'),('K'),('MOH'),('DCE'),('ACY'),('MRD'),('MLI'),('MPD'),
    ('BME'),('HOH'),('ACT'),('UNX'),('1PE'),('DMS'),('TLA'),('CIT'),('NH4'),
    ('BR'),('IOD'),('PGE'),
    ('FE'),('FE2'),('ZN'),('MG'),('CA'),('MN'),('CU'),('CD'),('HG'),('GA'),
    ('SR'),('CS'),('SCN'),('UNL'),('NI'),('LI'),('CO'),
    ('SF4'),('F3S'),('FES'),('HEM'),('HEC'),('RBF'),('FMN'),('FAD'),('BTN'),
    ('COA'),('NAD'),('GTP'),('GSP'),('PLP'),
    ('NO3'),('NO2')
),
real_ligands AS (
  SELECT pdb_id, GROUP_CONCAT(DISTINCT ccd_code) AS ligand_codes
  FROM ligand_ccd_codes
  WHERE ccd_code NOT IN (SELECT ccd_code FROM excluded_ccd_codes)
  GROUP BY pdb_id
)
SELECT
  c.pdb_id,
  c.title,
  c.n_residues,
  c.organism,
  rl.ligand_codes,
  s.passed                    AS simulability_passed,
  md.status                   AS md_simulation_status,
  md.failure_mode             AS md_simulation_failure_mode,
  md.effort_seconds           AS md_simulation_seconds,
  model.status                AS modeling_status,
  dock.status                 AS docking_status,
  dock.failure_mode           AS docking_failure_mode,
  dock.notes                  AS docking_notes,
  cmd.status                  AS complex_md_status,       -- PLAN.md §23a, GAFF2/AMBER
  cmd.failure_mode            AS complex_md_failure_mode, -- receptor+ligand MD from the
  cmd.notes                   AS complex_md_notes         -- real crystal ligand pose
FROM candidates c
JOIN real_ligands rl        ON rl.pdb_id = c.pdb_id
LEFT JOIN simulability s    ON s.pdb_id = c.pdb_id
LEFT JOIN validation md     ON md.pdb_id = c.pdb_id AND md.exercise = 'md_simulation'
LEFT JOIN validation model  ON model.pdb_id = c.pdb_id AND model.exercise = 'modeling'
LEFT JOIN validation dock   ON dock.pdb_id = c.pdb_id AND dock.exercise = 'docking'
LEFT JOIN validation cmd    ON cmd.pdb_id = c.pdb_id AND cmd.exercise = 'complex_md_simulation'
WHERE s.passed = 1
  AND md.status = 'success'          -- comment out to include not-yet-simulated candidates
  AND dock.status = 'success'        -- full-pipeline-confirmed candidates (comment out for a looser tier)
  AND cmd.status = 'success'         -- ALSO require complex-MD success (the 38-row full-pipeline tier)
ORDER BY c.n_residues ASC;

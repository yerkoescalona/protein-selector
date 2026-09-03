# protein-selector

Picks candidate proteins for a structural bioinformatics course, then proves each one is
teachable by actually running the exercise against it before a student ever sees it.

Choosing a teaching protein from metadata alone does not work: resolution, size and a bound
ligand tell you a structure is *nice*, not that the exercise will *run*. The failures that
ruin a class are the ones metadata cannot see. So this tool does not predict, it runs the
real pipelines and records what happened, per exercise.

```{toctree}
:maxdepth: 2
:caption: Guide

installation
usage
```

```{toctree}
:maxdepth: 2
:caption: Reference

api/index
```

## The pipeline

Layered filtering, cheap to expensive, ending in real validation rather than proxies:

| Stage | What it does | Survivors |
|---|---|---|
| hard filters | RCSB search: resolution, size, method | whole PDB |
| simulability | residue window, completeness, oligomeric state | hundreds |
| parameterizability | RDKit/Meeko on the bound ligand, fpocket | hundreds |
| literature | Europe PMC evidence counts | ~20-50 |
| validation | **real** test-MD, test-dock, AlphaFold DB lookup | ~20-50 |

Only the last stage costs real compute, and only candidates that survive everything above it
reach it. Results accumulate in SQLite, one table per stage; resume comes from the store
rather than from marker files, so a candidate already validated is never re-run.

## Project records

Design rationale lives in `PLAN.md` at the repository root: the layered-filtering decisions,
what was reversed and why, and the open work. It is a working record rather than reference
material, so it is deliberately not built into these pages.

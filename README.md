# protein-selector

Instructor tool for the *Structural Bioinformatics* Master's course (FHWN Tulln): finds
candidate proteins for the MD / docking / AlphaFold exercises and **a-priori validates**
them by actually attempting the real exercise pipelines, so the instructor knows — before
handing a protein to students — whether it's a clean intro case or something that will
break in class.

See [`PLAN.md`](PLAN.md) for the full design (layered filtering, the validation harness,
per-exercise difficulty scoring, and the reasoning behind every decision).

## Status

v0 seed: `src/protein_selector/find_small_proteins_with_ligands.py` — a two-stage UniProt→RCSB search with
size/resolution/method filters and a per-entry ligand check. This is being extended per
`PLAN.md` into the full layered pipeline (hard filters → simulability →
parameterizability → validation → per-exercise difficulty score).

## Relationship to the course repo

This repo is standalone and has no dependency on the course repo or its `exercises/`
submodule. The course consumes only this tool's **output** (a ranked CSV of candidate
proteins), vendored into `exercises/scripts/`. This tool never depends on the course's
toolchain, and the course never depends on this tool's toolchain (notably: no Java/p2rank
requirement leaks into the student environment).

## Setup

Managed with [`uv`](https://docs.astral.sh/uv/):

```bash
uv sync                      # base deps
uv sync --extra validate     # + the parameterizability stack (rdkit, meeko)
uv run python3 -m protein_selector.find_small_proteins_with_ligands
```

## Development

Lint and type-check before every commit:

```bash
uv run ruff check .
uv run ty check
```

## License

MIT

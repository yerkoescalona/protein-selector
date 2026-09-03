# API reference

Generated from the docstrings in `src/protein_selector`, so these pages cannot drift from
the code.

The package is organised by **discipline**, not by pipeline stage: a stage inserted later
does not force a rename, and the real cross-cutting concerns turned out to be infrastructure
(persistence, the validation contract) rather than biology, so those live in `core`.

```{toctree}
:maxdepth: 1

core
domain
nodes
pipelines
stages
runners
```

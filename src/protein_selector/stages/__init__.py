"""Independent, per-stage pipeline logic (PLAN.md §16), replacing ``pipeline.run_pipeline``.

Each module here owns one stage's orchestration (fetch/check/filter, persist, skip
already-done work) and exposes a plain ``run_<stage>_stage(...)`` function -- the unit a
Snakemake rule's thin `script:` wrapper calls directly, and the unit tests target. No
module here calls another stage's function; the Snakefile (or a caller wiring stages
manually) sequences them, passing each stage's own return value forward.
"""

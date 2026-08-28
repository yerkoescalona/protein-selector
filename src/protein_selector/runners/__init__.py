"""Execution runners: the layer that decides WHEN each stage runs (PLAN.md §31).

``stages/`` says what each step does; a runner says in what order and with what
parallelism. Snakemake (``Snakefile`` + ``workflow/scripts/``) is the incumbent;
``ray_runner`` is the evaluated replacement. Both call the same ``stages/``
functions and write to the same store, so they are interchangeable by design.
"""

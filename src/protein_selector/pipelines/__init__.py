"""Named recipes (PLAN.md §34).

One pipeline per file, named for the **outcome** -- *why* you run it, not what it does.
A pipeline composes stages, supplies the configuration, and is the thing a user actually
invokes. It may not reach past stages into individual nodes.

``single_pdb`` is the §22 single-candidate path (formerly ``stages/validate_one.py``,
which the §34 taxonomy identified as a pipeline misfiled as a stage).
"""

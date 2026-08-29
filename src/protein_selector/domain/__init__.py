"""The science library the nodes call (PLAN.md §34).

One package per biological/methodological discipline. This tier holds **adapters** (thin
wrappers over one external tool each), **validators** (compose adapters into a
``core.validation_result.ValidationResult``) and **stores** (persistence). It knows
nothing about pipelines, stages or nodes -- the dependency arrow points one way:

    pipelines -> stages -> nodes -> domain -> core

Grouped by discipline rather than by pipeline phase because a discipline name does not
need renaming when a phase is inserted later (the 2026-07-05 decision, preserved). What
changed in §34 is only that these packages now sit under ``domain/`` instead of at the
package root, so the tree states the tier instead of a `CONTEXT.md` paragraph doing it.
"""

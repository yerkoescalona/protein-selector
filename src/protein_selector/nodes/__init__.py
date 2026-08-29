"""Atomic units of work (PLAN.md §34).

One node per file, named **verb + thing** for what it does -- ``dock_ligand``,
``simulate_md``, ``count_literature``. A node is orchestration only: it decides what is
already persisted, calls one domain validator, persists the result, and reports status.
The science lives in ``domain/``; the ordering lives in ``stages/`` and ``pipelines/``.

Dependency rule (§34c): a node may import one validator, one store and ``core.config``.
It may not import another node -- if two nodes need the same logic, that logic belongs in
``domain/``.

Renamed from ``stages/`` in §34 N.4: these were never phases, they were single units of
work, and ``run_<x>_stage`` buried the real verb behind a vacuous one.
"""

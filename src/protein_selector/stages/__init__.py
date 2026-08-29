"""Phases -- groups of nodes that always travel together (PLAN.md §34).

One stage per file, named for **where you are** in the run, not what happens there:
``screening``, ``annotation``, ``chemistry``, ``validation``, ``reporting``.

A stage owns the ordering and concurrency of its nodes and nothing else. It may import
nodes; it may not reach past them into a validator, an adapter or a store (§34c). The
groupings here are not invented -- they are the concurrency structure the runner already
had: ``annotation``'s three nodes are exactly the three that fan out together after
screening, and ``validation``'s four are exactly the per-candidate chain
(§17c/§18: md -> pocket -> dock -> complex_md).

Note this folder previously held what are now ``nodes/`` -- see §34 N.4.
"""

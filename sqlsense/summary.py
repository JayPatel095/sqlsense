"""Plain-English walk of a parsed plan tree.

Rough notes / contract
----------------------
Input is always a PlanNode tree from parser.parse_plan. Three jobs here:

1. summarize(root) -> list[str]
   One sentence per *significant* node, pre-order (parents before children).
   Significant = anything except pure glue (Hash, Materialize, Memoize) —
   those repeat their child's numbers and add noise, skip them.
   Sentence shape: "<what> <where> returned N rows (planner estimated M)
   in T ms", with a " — estimate off by ~Kx" tail when the planner was
   badly wrong. Index scans read "Index Scan using <index> on <table>"
   (Postgres's own phrasing). Fields missing (plain EXPLAIN, no ANALYZE)
   -> just drop that clause, never crash.

2. top_nodes_by_time(root, n=3) -> list[PlanNode]
   Ranked by *total* time contribution. Two gotchas baked in:
   - actual_time_ms is a per-loop average -> multiply by actual_loops.
   - times are inclusive of children, so ancestors rank above their kids.
     Fine for v1 (it still points at the hot subtree); self-time needs
     child subtraction across loop counts — revisit if it misleads.

3. estimate_ratio / estimate_off
   ratio = plan_rows / actual_rows, both clamped to >= 1 so zero rows
   doesn't divide-by-zero (0 rows vs estimate 100k should still flag).
   Off = ratio > 10 or < 0.1 (brief's threshold). None when unknowable
   (no ANALYZE). This doubles as the M4 stale-statistics lint input.
"""

from __future__ import annotations

from .parser import PlanNode

GLUE_NODES = frozenset({"Hash", "Materialize", "Memoize"})

MISMATCH_FACTOR = 10.0


def estimate_ratio(node: PlanNode) -> float | None:
    raise NotImplementedError


def estimate_off(node: PlanNode) -> bool:
    raise NotImplementedError


def total_time_ms(node: PlanNode) -> float | None:
    raise NotImplementedError


def top_nodes_by_time(root: PlanNode, n: int = 3) -> list[PlanNode]:
    raise NotImplementedError


def summarize(root: PlanNode) -> list[str]:
    raise NotImplementedError

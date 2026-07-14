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
    if node.plan_rows is None or node.actual_rows is None:
        return None
    return max(node.plan_rows, 1) / max(node.actual_rows, 1)


def estimate_off(node: PlanNode) -> bool:
    ratio = estimate_ratio(node)
    if ratio is None:
        return False
    return ratio > MISMATCH_FACTOR or ratio < 1 / MISMATCH_FACTOR


def total_time_ms(node: PlanNode) -> float | None:
    if node.actual_time_ms is None:
        return None
    return node.actual_time_ms * (node.actual_loops or 1)


def _walk(node: PlanNode):
    yield node
    for child in node.children:
        yield from _walk(child)


def top_nodes_by_time(root: PlanNode, n: int = 3) -> list[PlanNode]:
    timed = [node for node in _walk(root) if total_time_ms(node) is not None]
    timed.sort(key=total_time_ms, reverse=True)
    return timed[:n]


def summarize(root: PlanNode) -> list[str]:
    return [
        _sentence(node) for node in _walk(root) if node.node_type not in GLUE_NODES
    ]


def _sentence(node: PlanNode) -> str:
    what = node.node_type
    if node.index_name and node.relation_name:
        what += f" using {node.index_name} on {node.relation_name}"
    elif node.relation_name:
        what += f" on {node.relation_name}"

    clauses = []
    if node.actual_rows is not None:
        total_rows = node.actual_rows * (node.actual_loops or 1)
        rows = f"returned {total_rows:,} rows"
        if node.actual_loops and node.actual_loops > 1:
            rows += f" across {node.actual_loops} loops"
        if node.plan_rows is not None:
            rows += f" (planner estimated {node.plan_rows:,})"
        clauses.append(rows)
    elif node.plan_rows is not None:
        clauses.append(f"is estimated to return {node.plan_rows:,} rows")

    time = total_time_ms(node)
    if time is not None:
        clauses.append(f"in {time:.1f} ms")

    sentence = f"{what} {' '.join(clauses)}".strip()

    ratio = estimate_ratio(node)
    if ratio is not None and estimate_off(node):
        factor = ratio if ratio >= 1 else 1 / ratio
        direction = "over" if ratio >= 1 else "under"
        sentence += f" — planner estimate off by ~{factor:,.0f}x ({direction})"
    return sentence

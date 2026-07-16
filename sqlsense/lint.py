"""Lint rules: (PlanNode) -> LintFinding | None.

Rough notes / contract
----------------------
A rule looks at ONE node and either fires or stays silent; lint_plan walks
the tree and applies every rule to every node. Findings carry severity
("warn" | "error"), a message saying what was observed, and a suggestion
that is actually actionable — a command or a change, not advice-shaped fog.

The five rules, and the judgment calls baked into them:

1. seq_scan_large_table (warn)
   The brief says actual_rows > 10000, but that's rows *returned* — the
   flagship query (SELECT ... WHERE customer_id = 42) returns only 100 of
   the 100k it reads, and it's exactly the case this rule exists for. So:
   rows SCANNED = (actual_rows + rows_removed_by_filter) * loops > 10000.
   Suggestion names the table and quotes the filter; the concrete
   CREATE INDEX statement is M5's job (needs sqlglot column extraction).

2. bad_row_estimate (warn)
   Reuses summary.estimate_off (>10x or <0.1x). Suggestion: ANALYZE <table>
   (or plain ANALYZE when the node has no relation). Skip nodes whose
   parent is equally off? No — dedup is presentation's problem, not lint's.

3. disk_spill (error)
   Hash node with hash_batches > 1, or Sort node with sort_space_type ==
   "Disk". Error, not warn: the query is actively doing I/O it shouldn't.
   Suggestion: raise work_mem (session-level first, not postgresql.conf).

4. nested_loop_large_outer (warn)
   Nested Loop whose outer child (children[0]) feeds > 1000 total rows:
   the inner side re-executes that many times — N+1 shape. Threshold is a
   guess; revisit with real-world plans.

5. low_selectivity_index_scan (warn)
   Index Scan where the post-index filter discards > 50% of fetched rows
   (removed / (removed + returned), per-loop values). The index is doing
   half a job; suggest a partial or composite index covering the filter.

Plan-level policy (Jay, 2026-07-16): rules DETECT node-locally, but
lint_plan decides what surfaces:

a. Repetition gating for index suggestions (rules 1 and 5). An index only
   clearly pays when the same access pattern is applied repeatedly, so
   these findings are kept only if the (relation, filter) pattern runs
   more than once in the plan — either one node re-executed via loops
   (nested-loop inner side: WHERE col = x per outer row) or the same
   pattern on 2+ nodes. A single one-shot scan stays silent.
   v1 matches filter text exactly; normalizing constants so that
   (col = 1) and (col = 2) count as the same pattern needs sqlglot (M5).

b. Dedup. Findings with identical (rule, suggestion) merge into one
   with a count — the same advice must never print twice.

lint_plan returns surviving findings in tree order (pre-order), rules in
the order above per node.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from .parser import PlanNode

LARGE_SCAN_ROWS = 10_000
LARGE_OUTER_ROWS = 1_000
FILTER_WASTE_FRACTION = 0.5


@dataclass
class LintFinding:
    rule: str
    severity: str  # "warn" | "error"
    message: str
    suggestion: str
    node: PlanNode
    count: int = 1  # identical findings merged by lint_plan


# rules whose advice is "build an index" — gated on pattern repetition
INDEX_SUGGESTION_RULES = frozenset(
    {"seq_scan_large_table", "low_selectivity_index_scan"}
)


Rule = Callable[[PlanNode], Optional[LintFinding]]


def _total_rows(node: PlanNode) -> int | None:
    """Rows a node produced across all loops (actual_rows is per-loop)."""
    if node.actual_rows is None:
        return None
    return node.actual_rows * (node.actual_loops or 1)


def seq_scan_large_table(node: PlanNode) -> LintFinding | None:
    if node.node_type != "Seq Scan" or node.actual_rows is None:
        return None
    scanned = (node.actual_rows + (node.rows_removed_by_filter or 0)) * (
        node.actual_loops or 1
    )
    if scanned <= LARGE_SCAN_ROWS:
        return None
    where = f" matching {node.filter_cond}" if node.filter_cond else ""
    return LintFinding(
        rule="seq_scan_large_table",
        severity="warn",
        message=(
            f"sequential scan read {scanned:,} rows from {node.relation_name} "
            f"to return {_total_rows(node):,}"
        ),
        suggestion=f"add an index on {node.relation_name}{where} so this becomes an index scan",
        node=node,
    )


def bad_row_estimate(node: PlanNode) -> LintFinding | None:
    from .summary import estimate_off, estimate_ratio

    if not estimate_off(node):
        return None
    ratio = estimate_ratio(node)
    factor = ratio if ratio >= 1 else 1 / ratio
    target = f"ANALYZE {node.relation_name}" if node.relation_name else "ANALYZE"
    return LintFinding(
        rule="bad_row_estimate",
        severity="warn",
        message=(
            f"planner estimated {node.plan_rows:,} rows for this {node.node_type} "
            f"but got {node.actual_rows:,} (~{factor:,.0f}x off)"
        ),
        suggestion=f"statistics may be stale — run {target}, then re-check the plan",
        node=node,
    )


def disk_spill(node: PlanNode) -> LintFinding | None:
    if node.node_type == "Hash" and (node.hash_batches or 1) > 1:
        detail = f"hash split into {node.hash_batches} batches"
    elif node.node_type == "Sort" and node.sort_space_type == "Disk":
        detail = "sort spilled to disk (external merge)"
    else:
        return None
    return LintFinding(
        rule="disk_spill",
        severity="error",
        message=f"{detail} — the working set does not fit in work_mem",
        suggestion="raise work_mem for this session (SET work_mem = '64MB') and re-run; tune globally only if it recurs",
        node=node,
    )


def nested_loop_large_outer(node: PlanNode) -> LintFinding | None:
    if node.node_type != "Nested Loop" or not node.children:
        return None
    outer_rows = _total_rows(node.children[0])
    if outer_rows is None or outer_rows <= LARGE_OUTER_ROWS:
        return None
    inner = node.children[1] if len(node.children) > 1 else None
    inner_name = inner.relation_name if inner and inner.relation_name else "the inner side"
    return LintFinding(
        rule="nested_loop_large_outer",
        severity="warn",
        message=(
            f"nested loop re-executes {inner_name} once per outer row "
            f"({outer_rows:,} times) — N+1 query shape"
        ),
        suggestion=(
            f"check that the join column on {inner_name} is indexed, "
            "or rewrite so the planner can hash/merge join"
        ),
        node=node,
    )


def low_selectivity_index_scan(node: PlanNode) -> LintFinding | None:
    if node.node_type != "Index Scan" or not node.rows_removed_by_filter:
        return None
    returned = node.actual_rows or 0
    fetched = returned + node.rows_removed_by_filter
    if fetched == 0 or node.rows_removed_by_filter / fetched <= FILTER_WASTE_FRACTION:
        return None
    return LintFinding(
        rule="low_selectivity_index_scan",
        severity="warn",
        message=(
            f"index {node.index_name} fetched {fetched:,} rows but the filter "
            f"{node.filter_cond} discarded {node.rows_removed_by_filter:,} of them"
        ),
        suggestion=(
            f"consider a partial or composite index on {node.relation_name} "
            f"covering {node.filter_cond}"
        ),
        node=node,
    )


RULES: list[Rule] = [
    seq_scan_large_table,
    bad_row_estimate,
    disk_spill,
    nested_loop_large_outer,
    low_selectivity_index_scan,
]


def _walk(node: PlanNode):
    yield node
    for child in node.children:
        yield from _walk(child)


def _pattern_applications(root: PlanNode) -> dict[tuple, int]:
    """How many times each (relation, filter) pattern executes in the plan."""
    counts: dict[tuple, int] = {}
    for node in _walk(root):
        if node.relation_name:
            key = (node.relation_name, node.filter_cond)
            counts[key] = counts.get(key, 0) + (node.actual_loops or 1)
    return counts


def lint_plan(root: PlanNode) -> list[LintFinding]:
    applications = _pattern_applications(root)

    detected = [
        finding for node in _walk(root) for rule in RULES if (finding := rule(node))
    ]

    # policy a: index suggestions only when the pattern repeats
    surfaced = [
        f
        for f in detected
        if f.rule not in INDEX_SUGGESTION_RULES
        or applications.get((f.node.relation_name, f.node.filter_cond), 0) > 1
    ]

    # policy b: identical advice prints once, with a count
    merged: dict[tuple[str, str], LintFinding] = {}
    for f in surfaced:
        key = (f.rule, f.suggestion)
        if key in merged:
            merged[key].count += 1
        else:
            merged[key] = f
    return list(merged.values())

"""Postgres EXPLAIN JSON -> typed PlanNode tree."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlanNode:
    node_type: str
    plan_rows: int | None = None
    actual_rows: int | None = None
    actual_time_ms: float | None = None
    actual_loops: int | None = None
    total_cost: float | None = None
    relation_name: str | None = None
    index_name: str | None = None
    filter_cond: str | None = None
    rows_removed_by_filter: int | None = None
    hash_batches: int | None = None
    sort_space_type: str | None = None
    children: list[PlanNode] = field(default_factory=list)


def parse_plan(explain_json: list | dict) -> PlanNode:
    """Parse loaded EXPLAIN (ANALYZE, FORMAT JSON) output into a PlanNode tree.

    Accepts either the one-element list envelope EXPLAIN produces
    ([{"Plan": {...}, "Execution Time": ...}]) or that element itself.

    Field name mapping (per node; absent keys stay None — field sets vary
    by node type and by whether ANALYZE ran):
        node_type      <- "Node Type"
        plan_rows      <- "Plan Rows"
        actual_rows    <- "Actual Rows"   (NB: per-loop average)
        actual_time_ms <- "Actual Total Time"
        actual_loops   <- "Actual Loops"
        total_cost     <- "Total Cost"
        relation_name  <- "Relation Name"
        index_name     <- "Index Name"
        filter_cond    <- "Filter"       (post-scan filter, not the index cond)
        rows_removed_by_filter <- "Rows Removed by Filter" (per-loop average)
        hash_batches   <- "Hash Batches" (on Hash nodes; > 1 means disk spill)
        sort_space_type <- "Sort Space Type" ("Memory" or "Disk", Sort nodes)

    Child nodes live under each node's "Plans" key.
    """
    doc = explain_json[0] if isinstance(explain_json, list) else explain_json
    return _parse_node(doc["Plan"])


def _parse_node(raw: dict) -> PlanNode:
    return PlanNode(
        node_type=raw["Node Type"],
        plan_rows=raw.get("Plan Rows"),
        actual_rows=raw.get("Actual Rows"),
        actual_time_ms=raw.get("Actual Total Time"),
        actual_loops=raw.get("Actual Loops"),
        total_cost=raw.get("Total Cost"),
        relation_name=raw.get("Relation Name"),
        index_name=raw.get("Index Name"),
        filter_cond=raw.get("Filter"),
        rows_removed_by_filter=raw.get("Rows Removed by Filter"),
        hash_batches=raw.get("Hash Batches"),
        sort_space_type=raw.get("Sort Space Type"),
        children=[_parse_node(child) for child in raw.get("Plans", [])],
    )

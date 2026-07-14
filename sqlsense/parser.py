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
        children=[_parse_node(child) for child in raw.get("Plans", [])],
    )

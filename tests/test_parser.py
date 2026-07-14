"""Acceptance tests for sqlsense.parser against real EXPLAIN fixtures.

Fixtures are genuine EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) output captured
by scripts/generate_fixtures.sh; assertions use their literal values.
"""

import json
from pathlib import Path

from sqlsense.parser import PlanNode, parse_plan

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    with open(FIXTURES / f"{name}.json") as f:
        return json.load(f)


def test_seq_scan_root_fields():
    node = parse_plan(load("seq_scan"))
    assert node.node_type == "Seq Scan"
    assert node.relation_name == "orders"
    assert node.plan_rows == 100
    assert node.actual_rows == 100
    assert node.actual_loops == 1
    assert node.total_cost == 2038.0
    assert node.actual_time_ms == 14.66
    assert node.children == []


def test_index_scan_captures_index_name():
    node = parse_plan(load("index_scan"))
    assert node.node_type == "Index Scan"
    assert node.relation_name == "orders"
    assert node.index_name == "orders_pkey"
    assert node.plan_rows == 1
    assert node.actual_rows == 1


def test_hash_join_tree_shape():
    node = parse_plan(load("hash_join"))
    assert node.node_type == "Hash Join"
    assert [c.node_type for c in node.children] == ["Seq Scan", "Hash"]
    outer, hash_side = node.children
    assert outer.relation_name == "orders"
    assert hash_side.relation_name is None  # Hash nodes have no relation
    assert [c.relation_name for c in hash_side.children] == ["customers"]


def test_nested_loop_children_and_loops():
    node = parse_plan(load("nested_loop"))
    assert node.node_type == "Nested Loop"
    outer, inner = node.children
    assert outer.index_name == "customers_pkey"
    assert outer.actual_rows == 9
    # inner scan ran once per outer row; actual_rows is the per-loop average
    assert inner.actual_loops == 9
    assert inner.actual_rows == 3


def test_nested_loop_preserves_planner_misestimate():
    node = parse_plan(load("nested_loop"))
    # the planner guessed 100000 rows; 27 came out — keep both intact,
    # M3's mismatch detection depends on them
    assert node.plan_rows == 100000
    assert node.actual_rows == 27


def test_sort_limit_nesting_depth():
    node = parse_plan(load("sort_limit"))
    assert node.node_type == "Limit"
    assert node.children[0].node_type == "Sort"
    assert node.children[0].children[0].node_type == "Seq Scan"
    assert node.children[0].children[0].actual_rows == 100000


def test_aggregate_over_seq_scan():
    node = parse_plan(load("aggregate"))
    assert node.node_type == "Aggregate"
    assert node.actual_rows == 1000
    assert [c.node_type for c in node.children] == ["Seq Scan"]


def test_accepts_unwrapped_envelope_element():
    # callers may hand over explain_json[0] instead of the full list
    wrapped = parse_plan(load("seq_scan"))
    unwrapped = parse_plan(load("seq_scan")[0])
    assert wrapped == unwrapped


def test_missing_analyze_fields_stay_none():
    # plain EXPLAIN (no ANALYZE) has no Actual* keys; parser must not crash
    plan = {"Plan": {"Node Type": "Seq Scan", "Plan Rows": 5, "Total Cost": 1.23}}
    node = parse_plan(plan)
    assert node.node_type == "Seq Scan"
    assert node.plan_rows == 5
    assert node.total_cost == 1.23
    assert node.actual_rows is None
    assert node.actual_time_ms is None
    assert node.relation_name is None
    assert node.children == []

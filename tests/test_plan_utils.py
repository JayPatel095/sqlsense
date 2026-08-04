"""Tests for sqlsense.plan_utils: tree traversal and row-estimate math."""

import json
from pathlib import Path

from sqlsense.parser import PlanNode, parse_plan
from sqlsense.plan_utils import estimate_off, estimate_ratio, walk

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> PlanNode:
    with open(FIXTURES / f"{name}.json") as f:
        return parse_plan(json.load(f))


# --- walk ---


def test_walk_yields_single_node_tree():
    node = PlanNode(node_type="Seq Scan")
    assert list(walk(node)) == [node]


def test_walk_is_pre_order_parents_before_children():
    leaf_a = PlanNode(node_type="Seq Scan")
    leaf_b = PlanNode(node_type="Index Scan")
    mid = PlanNode(node_type="Hash", children=[leaf_b])
    root = PlanNode(node_type="Hash Join", children=[leaf_a, mid])
    assert list(walk(root)) == [root, leaf_a, mid, leaf_b]


def test_walk_reaches_every_node_of_a_real_plan():
    root = load("hash_join")
    seen = list(walk(root))
    assert len(seen) > 1
    assert seen[0] is root
    for node in seen:
        for child in node.children:
            assert child in seen


# --- estimate_ratio / estimate_off ---


def test_accurate_estimate_is_not_off():
    node = load("seq_scan")  # planner said 100, got 100
    assert estimate_ratio(node) == 1.0
    assert estimate_off(node) is False


def test_wild_overestimate_is_off():
    node = load("nested_loop")  # planner said 100000, got 27
    ratio = estimate_ratio(node)
    assert ratio is not None and ratio > 1000
    assert estimate_off(node) is True


def test_underestimate_direction_also_flags():
    node = PlanNode(node_type="Seq Scan", plan_rows=10, actual_rows=500)
    assert estimate_off(node) is True


def test_zero_actual_rows_does_not_crash_and_flags():
    node = PlanNode(node_type="Seq Scan", plan_rows=100000, actual_rows=0)
    assert estimate_off(node) is True


def test_no_analyze_means_no_verdict():
    node = PlanNode(node_type="Seq Scan", plan_rows=5, actual_rows=None)
    assert estimate_ratio(node) is None
    assert estimate_off(node) is False

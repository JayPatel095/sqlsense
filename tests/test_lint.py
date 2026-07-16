"""Each rule gets at least one firing and one non-firing case.

Real fixtures are used where the planner produces the pattern naturally;
synthetic PlanNodes cover shapes the planner avoids on a healthy testdb
(large-outer nested loops, hash spills).
"""

import json
from pathlib import Path

from sqlsense.lint import (
    LintFinding,
    bad_row_estimate,
    disk_spill,
    lint_plan,
    low_selectivity_index_scan,
    nested_loop_large_outer,
    seq_scan_large_table,
)
from sqlsense.parser import PlanNode, parse_plan

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> PlanNode:
    with open(FIXTURES / f"{name}.json") as f:
        return parse_plan(json.load(f))


# --- 1. seq_scan_large_table ---


def test_seq_scan_fires_on_scanned_not_returned_rows():
    # returns only 100 rows but scanned 100k — must fire
    node = load("seq_scan")
    finding = seq_scan_large_table(node)
    assert finding is not None
    assert finding.severity == "warn"
    assert "orders" in finding.message
    assert "customer_id" in finding.suggestion  # quotes the filter
    assert "index" in finding.suggestion.lower()


def test_seq_scan_silent_on_small_table():
    # customers seq scan reads 200 rows total (hash_join's inner side)
    small_scan = load("hash_join").children[1].children[0]
    assert small_scan.node_type == "Seq Scan"
    assert seq_scan_large_table(small_scan) is None


def test_seq_scan_silent_on_other_node_types():
    assert seq_scan_large_table(load("index_scan")) is None


# --- 2. bad_row_estimate ---


def test_estimate_rule_fires_on_nested_loop_fixture():
    finding = bad_row_estimate(load("nested_loop"))
    assert finding is not None
    assert "ANALYZE" in finding.suggestion


def test_estimate_rule_names_relation_when_known():
    node = PlanNode(node_type="Seq Scan", relation_name="orders",
                    plan_rows=100_000, actual_rows=5)
    finding = bad_row_estimate(node)
    assert finding is not None
    assert "ANALYZE orders" in finding.suggestion


def test_estimate_rule_silent_when_accurate():
    assert bad_row_estimate(load("seq_scan")) is None


def test_estimate_rule_silent_without_analyze():
    node = PlanNode(node_type="Seq Scan", plan_rows=100_000)
    assert bad_row_estimate(node) is None


# --- 3. disk_spill ---


def test_spill_fires_on_disk_sort_fixture():
    finding = disk_spill(load("sort_spill"))
    assert finding is not None
    assert finding.severity == "error"
    assert "work_mem" in finding.suggestion


def test_spill_fires_on_multi_batch_hash():
    node = PlanNode(node_type="Hash", hash_batches=8)
    finding = disk_spill(node)
    assert finding is not None
    assert "work_mem" in finding.suggestion


def test_spill_silent_on_memory_sort():
    sort = load("sort_limit").children[0]
    assert sort.sort_space_type == "Memory"
    assert disk_spill(sort) is None


def test_spill_silent_on_single_batch_hash():
    hash_node = load("hash_join").children[1]
    assert hash_node.hash_batches == 1
    assert disk_spill(hash_node) is None


# --- 4. nested_loop_large_outer ---


def _nested_loop(outer_rows: int, loops: int = 1) -> PlanNode:
    return PlanNode(
        node_type="Nested Loop",
        children=[
            PlanNode(node_type="Seq Scan", relation_name="big",
                     actual_rows=outer_rows, actual_loops=loops),
            PlanNode(node_type="Index Scan", relation_name="small",
                     actual_rows=1, actual_loops=outer_rows * loops),
        ],
    )


def test_nested_loop_fires_on_large_outer():
    finding = nested_loop_large_outer(_nested_loop(50_000))
    assert finding is not None
    assert "N+1" in finding.message or "n+1" in finding.message.lower()


def test_nested_loop_counts_loops_in_outer_size():
    # 600 rows per loop x 2 loops = 1200 total > threshold
    assert nested_loop_large_outer(_nested_loop(600, loops=2)) is not None


def test_nested_loop_silent_on_small_outer():
    assert nested_loop_large_outer(load("nested_loop")) is None  # outer = 9 rows


# --- 5. low_selectivity_index_scan ---


def test_low_selectivity_fires_on_filtered_fixture():
    # index found 400 rows, filter threw away 300
    finding = low_selectivity_index_scan(load("index_scan_filtered"))
    assert finding is not None
    assert "status" in finding.suggestion  # quotes the discarding filter
    assert "partial" in finding.suggestion.lower() or "composite" in finding.suggestion.lower()


def test_low_selectivity_silent_without_filter():
    assert low_selectivity_index_scan(load("index_scan")) is None


def test_low_selectivity_silent_when_filter_cheap():
    node = PlanNode(node_type="Index Scan", relation_name="t", index_name="i",
                    actual_rows=90, rows_removed_by_filter=10,
                    filter_cond="(x = 1)")
    assert low_selectivity_index_scan(node) is None


# --- lint_plan walks everything ---


def test_lint_plan_collects_across_tree():
    findings = lint_plan(load("nested_loop"))
    rules_fired = {f.rule for f in findings}
    assert "bad_row_estimate" in rules_fired
    assert all(isinstance(f, LintFinding) for f in findings)


def test_lint_plan_clean_query_has_no_findings():
    assert lint_plan(load("index_scan")) == []


# --- plan-level policy: repetition gating ---


def test_one_shot_seq_scan_is_gated_at_plan_level():
    # the rule detects it node-locally, but a single application of
    # (customer_id = 1) doesn't justify an index suggestion on its own
    assert seq_scan_large_table(load("seq_scan")) is not None
    assert lint_plan(load("seq_scan")) == []


def test_one_shot_filtered_index_scan_is_gated_too():
    assert lint_plan(load("index_scan_filtered")) == []


def _repeated_inner_scan(loops: int) -> PlanNode:
    inner = PlanNode(
        node_type="Seq Scan", relation_name="orders",
        filter_cond="(customer_id = c.id)",
        actual_rows=5, rows_removed_by_filter=20_000,
        actual_loops=loops, plan_rows=5,
    )
    outer = PlanNode(node_type="Seq Scan", relation_name="customers",
                     actual_rows=loops, actual_loops=1, plan_rows=loops)
    return PlanNode(node_type="Nested Loop", actual_rows=5 * loops,
                    plan_rows=5 * loops, children=[outer, inner])


def test_filter_repeated_via_loops_fires():
    findings = lint_plan(_repeated_inner_scan(loops=100))
    assert any(f.rule == "seq_scan_large_table" for f in findings)


def test_same_filter_in_two_branches_fires_once_with_count():
    scan = dict(node_type="Seq Scan", relation_name="orders",
                filter_cond="(status = 'x')", actual_rows=20_000,
                rows_removed_by_filter=80_000, actual_loops=1, plan_rows=20_000)
    root = PlanNode(node_type="Append",
                    children=[PlanNode(**scan), PlanNode(**scan)])
    findings = [f for f in lint_plan(root) if f.rule == "seq_scan_large_table"]
    assert len(findings) == 1  # deduped: identical advice prints once
    assert findings[0].count == 2


# --- plan-level policy: dedup of identical suggestions ---


def test_identical_estimate_findings_merge():
    scan = dict(node_type="Seq Scan", relation_name="orders",
                plan_rows=100_000, actual_rows=5, actual_loops=1)
    root = PlanNode(node_type="Append",
                    children=[PlanNode(**scan), PlanNode(**scan)])
    findings = [f for f in lint_plan(root) if f.rule == "bad_row_estimate"]
    assert len(findings) == 1
    assert findings[0].count == 2


def test_distinct_suggestions_do_not_merge():
    # nested_loop fixture: root (no relation) says "run ANALYZE", inner
    # index scan says "run ANALYZE orders" — different advice, keep both
    findings = [f for f in lint_plan(load("nested_loop"))
                if f.rule == "bad_row_estimate"]
    assert len(findings) == 2

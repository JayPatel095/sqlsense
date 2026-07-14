"""Tests for sqlsense.summary against the committed EXPLAIN fixtures."""

import json
from pathlib import Path

from sqlsense.parser import PlanNode, parse_plan
from sqlsense.summary import (
    estimate_off,
    estimate_ratio,
    summarize,
    top_nodes_by_time,
    total_time_ms,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> PlanNode:
    with open(FIXTURES / f"{name}.json") as f:
        return parse_plan(json.load(f))


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


# --- total_time_ms ---


def test_total_time_multiplies_by_loops():
    inner = load("nested_loop").children[1]  # ran 9 times
    assert inner.actual_loops == 9
    assert total_time_ms(inner) == inner.actual_time_ms * 9


def test_total_time_none_without_analyze():
    assert total_time_ms(PlanNode(node_type="Seq Scan")) is None


# --- top_nodes_by_time ---


def test_top_nodes_ranked_descending():
    top = top_nodes_by_time(load("sort_limit"), n=3)
    assert len(top) == 3
    times = [total_time_ms(n) for n in top]
    assert times == sorted(times, reverse=True)
    # inclusive semantics: the root Limit carries the whole query's time
    assert top[0].node_type == "Limit"


def test_top_nodes_respects_n():
    assert len(top_nodes_by_time(load("hash_join"), n=2)) == 2


# --- summarize ---


def test_summarize_one_sentence_per_significant_node():
    # Hash Join / Seq Scan / Hash / Seq Scan -> Hash is glue, so 3 sentences
    sentences = summarize(load("hash_join"))
    assert len(sentences) == 3
    assert "Hash Join" in sentences[0]


def test_summarize_seq_scan_mentions_table_rows_and_estimate():
    (sentence,) = summarize(load("seq_scan"))
    assert "Seq Scan" in sentence and "orders" in sentence
    assert "100 rows" in sentence
    assert "estimated" in sentence


def test_summarize_index_scan_uses_postgres_phrasing():
    (sentence,) = summarize(load("index_scan"))
    assert "Index Scan using orders_pkey on orders" in sentence


def test_summarize_flags_bad_estimate():
    sentences = summarize(load("nested_loop"))
    assert "off by" in sentences[0]


def test_summarize_survives_plain_explain():
    node = PlanNode(node_type="Seq Scan", plan_rows=5, relation_name="t")
    (sentence,) = summarize(node)
    assert "Seq Scan" in sentence and "t" in sentence
    assert "ms" not in sentence  # no timing clause without ANALYZE

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

lint_plan returns findings in tree order (pre-order), rules in the order
above per node.
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


Rule = Callable[[PlanNode], Optional[LintFinding]]


def seq_scan_large_table(node: PlanNode) -> LintFinding | None:
    raise NotImplementedError


def bad_row_estimate(node: PlanNode) -> LintFinding | None:
    raise NotImplementedError


def disk_spill(node: PlanNode) -> LintFinding | None:
    raise NotImplementedError


def nested_loop_large_outer(node: PlanNode) -> LintFinding | None:
    raise NotImplementedError


def low_selectivity_index_scan(node: PlanNode) -> LintFinding | None:
    raise NotImplementedError


RULES: list[Rule] = [
    seq_scan_large_table,
    bad_row_estimate,
    disk_spill,
    nested_loop_large_outer,
    low_selectivity_index_scan,
]


def lint_plan(root: PlanNode) -> list[LintFinding]:
    raise NotImplementedError

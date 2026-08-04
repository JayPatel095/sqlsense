"""Shared plan-tree helpers: traversal and row-estimate math.

Extracted so lint and summary can both use them without lint importing a
presentation module. Nothing here formats or phrases anything.
"""

from __future__ import annotations

from collections.abc import Iterator

from .parser import PlanNode

MISMATCH_FACTOR = 10.0


def walk(node: PlanNode) -> Iterator[PlanNode]:
    """Yield every node in the tree, pre-order (parents before children)."""
    yield node
    for child in node.children:
        yield from walk(child)


def estimate_ratio(node: PlanNode) -> float | None:
    if node.plan_rows is None or node.actual_rows is None:
        return None
    return max(node.plan_rows, 1) / max(node.actual_rows, 1)


def estimate_off(node: PlanNode) -> bool:
    ratio = estimate_ratio(node)
    if ratio is None:
        return False
    return ratio > MISMATCH_FACTOR or ratio < 1 / MISMATCH_FACTOR

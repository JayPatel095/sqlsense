"""Run EXPLAIN against a connection and return the raw output."""

from __future__ import annotations

import json
import sqlite3

from .db import Connection, DatabaseError


def run_explain(conn: Connection, query: str) -> str:
    if conn.dialect == "postgres":
        return _explain_postgres(conn.raw, query)
    return _explain_sqlite(conn.raw, query)


def _explain_postgres(raw, query: str) -> str:
    import psycopg2

    # ANALYZE executes the query for real; roll back afterwards so
    # explaining an UPDATE/DELETE never persists changes.
    try:
        with raw.cursor() as cur:
            cur.execute(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {query}")
            plan = cur.fetchone()[0]
    except psycopg2.Error as exc:
        raw.rollback()
        detail = str(exc).strip().splitlines()
        raise DatabaseError(detail[0] if detail else "EXPLAIN failed") from exc
    raw.rollback()
    return json.dumps(plan, indent=2)


def _explain_sqlite(raw, query: str) -> str:
    # SQLite has no ANALYZE-style instrumentation: EXPLAIN QUERY PLAN is a
    # static plan with no timing or row counts (degraded mode by design).
    try:
        rows = raw.execute(f"EXPLAIN QUERY PLAN {query}").fetchall()
    except sqlite3.Error as exc:
        raise DatabaseError(str(exc)) from exc

    # Rows are (id, parent, notused, detail); indent children under parents.
    depth: dict[int, int] = {0: 0}
    lines = []
    for node_id, parent, _, detail in rows:
        depth[node_id] = depth.get(parent, 0) + 1
        lines.append("  " * (depth[node_id] - 1) + detail)
    return "\n".join(lines) if lines else "(empty plan)"

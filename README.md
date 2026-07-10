# sqlsense

A CLI that explains SQL query plans in plain English and tells you exactly what index to add.

```
sqlsense --db postgresql://localhost/mydb "SELECT * FROM tickets WHERE user_id = 42"
```

Runs `EXPLAIN ANALYZE` on a query, parses the execution plan, and prints:

- a plain-English summary of what the database is doing (scan types, which tables, estimated vs actual rows)
- lint findings with concrete suggestions (missing index, stale statistics, work_mem spills, N+1-shaped nested loops)
- an index coverage report with copy-pasteable `CREATE INDEX` statements

Supports PostgreSQL (full analysis) and SQLite (degraded mode: scan type and index usage only — SQLite's `EXPLAIN QUERY PLAN` has no timing or row counts).

**Status:** pre-code. See [PLAN.md](PLAN.md) for the roadmap and [docs/brief.md](docs/brief.md) for the full project brief.

## Why not an existing tool

| Tool | Gap |
|------|-----|
| pganalyze | hosted SaaS, requires an account, no CLI |
| explain.depesz.com | web paste tool, no linting, no index suggestions |
| pev2 | visual plan explorer, browser-only |

None work offline, produce machine-readable output, or hand you a `CREATE INDEX` statement.

## Stack

Python 3.10+, Click, psycopg2, sqlite3 (stdlib), Rich, sqlglot, pytest.

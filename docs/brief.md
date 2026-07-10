# sqlense — Claude Code session brief

## What this is

A CLI that runs `EXPLAIN ANALYZE` on a SQL query, parses the execution plan, and outputs a plain-English breakdown of what the database is doing — which indexes it's hitting, where the cost is, and concrete suggestions to fix it. Supports PostgreSQL and SQLite.

```
sqlense --db postgresql://localhost/mydb "SELECT * FROM tickets WHERE user_id = 42"
```

One-liner description: a CLI that explains SQL query plans in plain English and tells you exactly what index to add.

**Closest existing tools and the gap:**
- `pganalyze` — hosted SaaS, requires an account, no CLI
- `explain.depesz.com` — web paste tool, no linting, no index suggestions
- `pev2` — visual plan explorer, browser-only

None of them work offline, produce machine-readable output, or give you a `CREATE INDEX` statement to copy-paste.

**Stack:** Python 3.10+, Click (CLI), psycopg2 (Postgres), sqlite3 (stdlib), Rich (terminal output), pytest

---

## How to work on this

Work like a real project — spike, commit when something works, backtrack when it doesn't. Don't preserve broken state by pushing forward through it.

Commits should describe what actually changed, not which step you're on.

Good: `parse seq scan node from postgres json plan`, `add row estimate mismatch lint rule`, `fix rich tree crash on empty subplan`
Bad: `step 2`, `add feature`, `wip`

When you hit something that's harder than expected — say the Postgres JSON plan format has a quirk, or Rich's tree layout isn't rendering correctly — say so, try a different approach, and commit the working version. A messy path to a working result is fine. A clean path to a broken result isn't.

---

## The core loop (what matters most)

Everything else is secondary to this working:

```bash
sqlense --db postgresql://localhost/testdb "SELECT * FROM orders WHERE customer_id = 1"
```

Produces terminal output that includes:
- A plain-English summary of the plan (what scan type, which table, estimated vs actual rows)
- At least one lint finding with a concrete suggestion
- The top cost node highlighted

If you get this working against a local Postgres instance and nothing else, that's a shippable v0.1.

---

## Milestones (not steps — order may shift)

### M1: repo is runnable
- `pyproject.toml` with `sqlense` as a CLI entry point
- `sqlense --db <conn> "<query>"` connects to the DB and prints the raw EXPLAIN output
- Handles bad connection string gracefully (clear error message, not a Python traceback)
- Commit: `init: cli skeleton, db connection, raw explain output`

### M2: plan parser works
- Parse `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` output into a typed Python dataclass tree
- Each node captures: `node_type`, `actual_rows`, `actual_time_ms`, `plan_rows` (estimate), `total_cost`, `children`
- Tested against fixture JSON files — collect real plan output from a local Postgres instance and commit it as test fixtures
- Expected friction: Postgres plan JSON schema varies by node type (Seq Scan, Index Scan, Hash Join, Nested Loop each have different fields). Read the Postgres docs for `EXPLAIN` output format before writing the parser. Don't guess at field names.
- Commit when parser handles the 5 most common node types; iterate from there

### M3: plain-English summary
- Walk the parsed plan tree and emit one sentence per significant node
- Surface top 3 nodes by actual time with a simple ranking
- Row estimate mismatch detection: flag any node where `plan_rows / actual_rows > 10x` or `< 0.1x`
- This is mostly string formatting once M2 is solid — should go fast

### M4: lint rules
- A lint rule = a function `(PlanNode) -> Optional[LintFinding]`
- Each `LintFinding` has: `severity` (warn/error), `message`, `suggestion` (actionable string)
- Implement in priority order:
  1. Seq scan on large table (actual_rows > 10000) — suggest index
  2. Row estimate off by > 10x — suggest ANALYZE
  3. Hash join or sort spilling to disk (look for "Batches" > 1) — suggest increasing work_mem
  4. Nested loop with large outer relation — flag as potential N+1
  5. Index scan but filter removing > 50% of rows — suggest partial index
- Rules are the core IP of this tool — take time here. Each rule should have at least two pytest cases: one that fires, one that doesn't.

### M5: index coverage report
- Introspect the DB schema for tables referenced in the query
- For each filter/join column in the query, check if an index exists
- Emit a `CREATE INDEX` statement for each missing one
- Expected friction: parsing which columns a query filters on requires either regex heuristics or a SQL parser (`sqlglot` is the right library here — add it as a dependency). Don't roll your own SQL parser.

### M6: polish and package
- `--json` flag: emit full analysis as structured JSON
- Rich terminal output: plan tree, lint table, index report
- README with a GIF demo and a comparison table vs. existing tools
- Publish to PyPI

### Stretch: CI mode
- `sqlense --ci --max-cost 10000 query.sql` exits non-zero if lint rules fire or cost exceeds threshold
- Designed to be a pre-commit hook or GitHub Actions step
- Add a GitHub Actions workflow that runs `sqlense --ci` against a test Postgres container

---

## Known hard parts — flag these early

**Postgres plan JSON schema is inconsistent:** Field names differ between node types. `Seq Scan` has `Relation Name`; `Hash Join` has `Hash Cond`; `Index Scan` has `Index Name`. Write a flexible parser that extracts what's present per node rather than expecting a fixed schema. Test against real fixture files.

**SQLite's EXPLAIN is different:** SQLite uses `EXPLAIN QUERY PLAN` not `EXPLAIN ANALYZE`, and its output is plain text, not JSON. The output is much less detailed — no actual timing, no row counts. Handle SQLite as a degraded mode: you get scan type and index usage, but not timing or row estimates. Be upfront about this in the README.

**Column extraction from SQL:** To generate index suggestions you need to know which columns the query filters on. `sqlglot` parses SQL into an AST — use `sqlglot.parse_one(query).find_all(sqlglot.exp.Column)` to extract column references. Don't regex this.

**Rich tree with deep plans:** Postgres plans can be 15+ levels deep. Rich's `Tree` widget handles this fine, but very deep plans with long node descriptions will wrap badly in narrow terminals. Add a `--no-tree` flag that falls back to indented text output.

---

## Test fixtures

Commit real `EXPLAIN (FORMAT JSON)` output for at least these query patterns as `.json` files under `tests/fixtures/`:

- Seq scan (no index)
- Index scan (index hit)
- Hash join between two tables
- Nested loop
- Sort + limit
- Aggregate (GROUP BY)

Generate them against a local Postgres instance with a small test schema. Having real fixtures means the parser tests don't need a live DB.

---

## Repo layout

```
sqlense/
├── pyproject.toml
├── README.md
├── sqlense/
│   ├── __init__.py
│   ├── cli.py             # Click entry point
│   ├── db.py              # connection handling (postgres + sqlite)
│   ├── explain.py         # runs EXPLAIN ANALYZE, returns raw JSON
│   ├── parser.py          # JSON plan → PlanNode dataclass tree
│   ├── summary.py         # plain-English walk of the plan tree
│   ├── lint.py            # lint rules → LintFinding list
│   ├── index_report.py    # schema introspection + CREATE INDEX suggestions
│   └── output.py          # Rich terminal renderer + --json mode
└── tests/
    ├── fixtures/           # real EXPLAIN JSON output files
    ├── test_parser.py
    ├── test_lint.py
    └── test_summary.py
```

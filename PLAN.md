# sqlsense — working plan

Distilled from [docs/brief.md](docs/brief.md). Milestones, not steps — order may shift.

## Definition of shippable v0.1 (the core loop)

```bash
sqlsense --db postgresql://localhost/testdb "SELECT * FROM orders WHERE customer_id = 1"
```

must print:

- [ ] plain-English summary of the plan (scan type, table, estimated vs actual rows)
- [ ] at least one lint finding with a concrete suggestion
- [ ] the top cost node highlighted

Everything else is secondary to this.

## Milestones

### M1 — repo is runnable
- [x] `pyproject.toml` with `sqlsense` CLI entry point (Click)
- [x] `sqlsense --db <conn> "<query>"` connects and prints raw EXPLAIN output (verified on both Postgres and SQLite)
- [x] bad connection string → clear error message, not a traceback

### M2 — plan parser
- [ ] parse `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` into a `PlanNode` dataclass tree
- [ ] node fields: `node_type`, `actual_rows`, `actual_time_ms`, `plan_rows`, `total_cost`, `children`
- [ ] real fixture JSON files under `tests/fixtures/` (see fixture list below)
- [ ] handles the 5 most common node types before iterating further
- ⚠ field names vary per node type (`Relation Name` vs `Hash Cond` vs `Index Name`) — extract what's present, read the Postgres EXPLAIN docs first, don't guess

### M3 — plain-English summary
- [ ] one sentence per significant node
- [ ] top 3 nodes by actual time
- [ ] row estimate mismatch flag: `plan_rows / actual_rows` > 10x or < 0.1x

### M4 — lint rules (core IP — take time here)
Rule = `(PlanNode) -> Optional[LintFinding]`; finding = `severity`, `message`, `suggestion`.
Priority order; each rule gets ≥2 pytest cases (one fires, one doesn't):
- [ ] 1. seq scan on large table (actual_rows > 10000) → suggest index
- [ ] 2. row estimate off by > 10x → suggest ANALYZE
- [ ] 3. hash join / sort spilling to disk (`Batches` > 1) → suggest raising work_mem
- [ ] 4. nested loop with large outer relation → flag potential N+1
- [ ] 5. index scan with filter removing > 50% of rows → suggest partial index

### M5 — index coverage report
- [ ] introspect schema for tables referenced in the query
- [ ] check each filter/join column for an existing index
- [ ] emit `CREATE INDEX` for each missing one
- ⚠ use `sqlglot` for column extraction (`parse_one(query).find_all(exp.Column)`) — no regex, no hand-rolled parser

### M6 — polish and package
- [ ] `--json` flag: full analysis as structured JSON
- [ ] Rich output: plan tree, lint table, index report; `--no-tree` fallback for deep plans
- [ ] README with GIF demo + comparison table
- [ ] publish to PyPI

### Stretch — CI mode
- [ ] `sqlsense --ci --max-cost 10000 query.sql` exits non-zero on findings / cost threshold
- [ ] GitHub Actions workflow running against a test Postgres container

## Test fixtures to collect (real output, local Postgres)

- [ ] seq scan (no index)
- [ ] index scan (index hit)
- [ ] hash join between two tables
- [ ] nested loop
- [ ] sort + limit
- [ ] aggregate (GROUP BY)

## Known hard parts (flag early, don't push through broken state)

1. **Postgres plan JSON schema is inconsistent** across node types — flexible per-node extraction, tested against real fixtures.
2. **SQLite is a degraded mode** — `EXPLAIN QUERY PLAN`, plain text, no timing/rows. Be upfront in the README.
3. **Column extraction needs sqlglot**, not regex.
4. **Deep Rich trees wrap badly** in narrow terminals — `--no-tree` flag.

## Working conventions

- Spike, commit when something works, backtrack when it doesn't.
- Commit messages describe what changed (`parse seq scan node from postgres json plan`), not which step it is (`step 2`, `wip`).

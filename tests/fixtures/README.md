# EXPLAIN fixtures

Real `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` output, captured once and
committed so the test suite needs no database.

## Provenance

- **Postgres 17**, local, default config except where a fixture says otherwise.
- Schema and data: [`scripts/seed_testdb.sql`](../../scripts/seed_testdb.sql)
  — 1,000 customers, 100,000 orders, `ANALYZE`d. `orders.customer_id` is
  deliberately left unindexed so the seq-scan and index-suggestion rules have
  something real to fire on.
- Captured by [`scripts/generate_fixtures.sh`](../../scripts/generate_fixtures.sh),
  which holds the exact query behind each file.

Nothing in the JSON records the server version — Postgres doesn't emit it in
EXPLAIN output — so this note is the only provenance. Keep it accurate if the
fixtures are ever regenerated somewhere else. Node-type spelling and the shape
of the plan tree are what the parser and lint rules match on, and both can
shift between major versions.

| Fixture | Shape it pins down |
| --- | --- |
| `seq_scan` | seq scan on an unindexed column, accurate estimate |
| `index_scan` | primary-key lookup |
| `index_scan_filtered` | index scan whose filter discards ~75% of rows |
| `hash_join` | hash join with a Hash glue node |
| `nested_loop` | range join: nested loop, parameterized inner, wild estimate miss |
| `sort_limit` | top-N heapsort under a Limit |
| `sort_spill` | full sort spilling to disk, captured with `work_mem = 64kB` |
| `aggregate` | HashAggregate over a group-by |

## Regenerating

`scripts/generate_fixtures.sh [database-name]` rewrites **every** file. Tests
assert exact values from these, so timing-independent assertions can still
break when row counts or plan shapes move. Run pytest afterwards and either
update the stale assertions or `git restore` the files you didn't mean to
touch.

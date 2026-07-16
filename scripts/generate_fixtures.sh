#!/usr/bin/env bash
# Regenerate the EXPLAIN JSON test fixtures against a seeded local testdb.
# Usage: scripts/generate_fixtures.sh [database-name]
#
# Requires the schema from scripts/seed_testdb.sql. Timing values change
# between runs; node structure should stay stable for the same seed sizes.
set -euo pipefail

DB="${1:-testdb}"
OUT="$(dirname "$0")/../tests/fixtures"
mkdir -p "$OUT"

explain() { # <fixture-name> <query>
    psql -d "$DB" -qtA -c "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) $2" > "$OUT/$1.json"
    echo "wrote $1.json"
}

explain seq_scan        "SELECT * FROM orders WHERE customer_id = 1"
explain index_scan      "SELECT * FROM orders WHERE id = 42"
explain hash_join       "SELECT c.name, o.total FROM orders o JOIN customers c ON c.id = o.customer_id WHERE c.country = 'CA'"
# a range join can't be hashed or merged, so the planner has no alternative
# to a nested loop with a parameterized inner index scan
explain nested_loop     "SELECT c.name, o.total FROM customers c JOIN orders o ON o.id BETWEEN c.id AND c.id + 2 WHERE c.id < 10"
explain sort_limit      "SELECT * FROM orders ORDER BY total DESC LIMIT 10"
explain aggregate       "SELECT customer_id, count(*), sum(total) FROM orders GROUP BY customer_id"

# a full sort of 100k rows under a starved work_mem spills to disk
# (SET and EXPLAIN share one implicit transaction in a single -c)
psql -d "$DB" -qtA -c "SET work_mem='64kB'; EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) SELECT * FROM orders ORDER BY total" > "$OUT/sort_spill.json"
echo "wrote sort_spill.json"

# pk range keeps it an index scan; the status filter then discards ~75%
explain index_scan_filtered "SELECT * FROM orders WHERE id <= 400 AND status = 'pending'"

-- Seed schema for local development and fixture generation.
-- Usage: createdb testdb && psql -d testdb -f scripts/seed_testdb.sql
--
-- orders.customer_id is intentionally unindexed so seq-scan lint rules
-- and index suggestions have something real to fire on.

DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
    id         serial PRIMARY KEY,
    name       text NOT NULL,
    country    text NOT NULL
);

CREATE TABLE orders (
    id          serial PRIMARY KEY,
    customer_id integer NOT NULL REFERENCES customers (id),
    total       numeric(10, 2) NOT NULL,
    status      text NOT NULL,
    created_at  timestamptz NOT NULL
);

INSERT INTO customers (name, country)
SELECT
    'customer_' || g,
    (ARRAY['CA', 'US', 'GB', 'DE', 'IN'])[1 + g % 5]
FROM generate_series(1, 1000) AS g;

INSERT INTO orders (customer_id, total, status, created_at)
SELECT
    1 + g % 1000,
    round((random() * 500)::numeric, 2),
    (ARRAY['pending', 'shipped', 'delivered', 'cancelled'])[1 + g % 4],
    now() - (g % 365) * interval '1 day'
FROM generate_series(1, 100000) AS g;

ANALYZE customers;
ANALYZE orders;

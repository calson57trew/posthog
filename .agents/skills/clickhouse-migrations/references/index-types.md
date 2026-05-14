# ClickHouse Index Types Reference

This document covers the available index types in ClickHouse and when to use each one for PostHog migrations.

## Primary Key Indexes

ClickHouse uses a sparse primary index based on the `ORDER BY` clause of the table. This is the most important index and is always present.

```sql
-- The ORDER BY defines the primary index
CREATE TABLE posthog_db.my_table ON CLUSTER '{cluster}'
(
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    event VARCHAR,
    uuid UUID
)
ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog_db.my_table', '{replica}')
ORDER BY (team_id, toDate(timestamp), event, uuid);
```

**Rules:**
- Columns in `ORDER BY` must be a prefix of the `PRIMARY KEY` (or identical)
- Lower cardinality columns should come first
- Always include `team_id` as the first column for multi-tenant isolation

## Skip Indexes (Secondary Indexes)

Skip indexes allow ClickHouse to skip reading data granules that cannot contain matching rows.

### minmax

Stores the min and max value of a column per granule. Best for range queries on numeric or date columns.

```sql
ALTER TABLE posthog_db.my_table ON CLUSTER '{cluster}'
    ADD INDEX idx_timestamp_minmax (timestamp) TYPE minmax GRANULARITY 1;
```

**Use when:** Querying with `WHERE timestamp BETWEEN x AND y` on a column not in the primary key.

### set

Stores a set of distinct values per granule. Best for low-cardinality columns used in equality filters.

```sql
ALTER TABLE posthog_db.my_table ON CLUSTER '{cluster}'
    ADD INDEX idx_event_set (event) TYPE set(100) GRANULARITY 1;
```

**Parameter:** Maximum number of distinct values to store (0 = unlimited, but avoid this).

**Use when:** Filtering on `WHERE event = 'pageview'` for a column with limited distinct values.

### bloom_filter

Probabilistic data structure for membership testing. Good for high-cardinality string columns.

```sql
ALTER TABLE posthog_db.my_table ON CLUSTER '{cluster}'
    ADD INDEX idx_distinct_id_bloom (distinct_id) TYPE bloom_filter(0.01) GRANULARITY 1;
```

**Parameter:** False positive rate (0.01 = 1% false positives).

**Use when:** Filtering on UUIDs, session IDs, or other high-cardinality string identifiers.

### tokenbf_v1

Bloom filter variant that tokenizes strings. Useful for substring or token-based searches.

```sql
ALTER TABLE posthog_db.my_table ON CLUSTER '{cluster}'
    ADD INDEX idx_properties_token (properties) TYPE tokenbf_v1(32768, 3, 0) GRANULARITY 1;
```

**Parameters:** `(size_of_bloom_filter_in_bytes, number_of_hash_functions, random_seed)`

**Use when:** Searching within JSON strings or free-text fields.

### ngrambf_v1

N-gram bloom filter for substring matching.

```sql
ALTER TABLE posthog_db.my_table ON CLUSTER '{cluster}'
    ADD INDEX idx_url_ngram (current_url) TYPE ngrambf_v1(4, 32768, 3, 0) GRANULARITY 1;
```

**Parameters:** `(n, size_of_bloom_filter_in_bytes, number_of_hash_functions, random_seed)`

**Use when:** Performing `LIKE '%substring%'` queries on URL or path columns.

## Materializing Indexes After Creation

After adding a skip index, you must materialize it for existing data:

```sql
-- Trigger materialization
ALTER TABLE posthog_db.my_table ON CLUSTER '{cluster}'
    MATERIALIZE INDEX idx_event_set;

-- Check mutation progress
SELECT mutation_id, command, is_done, parts_to_do
FROM system.mutations
WHERE table = 'my_table' AND database = 'posthog_db'
ORDER BY create_time DESC
LIMIT 10;
```

## Dropping Indexes

```sql
ALTER TABLE posthog_db.my_table ON CLUSTER '{cluster}'
    DROP INDEX idx_event_set;
```

## Performance Considerations

- Skip indexes add overhead to **writes** — only add them if query patterns justify it
- `GRANULARITY` controls how many primary index granules are grouped; higher = less index data but coarser skipping
- Always benchmark with `EXPLAIN indexes = 1 SELECT ...` to verify the index is being used
- Bloom filters have false positives — they can skip granules but never produce false negatives

## PostHog-Specific Conventions

- Index names should follow `idx_{column}_{type}` pattern (e.g., `idx_session_id_bloom`)
- Always apply indexes `ON CLUSTER '{cluster}'` for distributed deployments
- Prefer `minmax` for timestamp range queries, `bloom_filter` for UUID lookups
- Avoid adding indexes to columns already covered by the `ORDER BY` primary index

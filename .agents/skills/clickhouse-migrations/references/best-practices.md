# ClickHouse Migration Best Practices

This document outlines best practices for writing safe, performant ClickHouse migrations in PostHog.

## General Principles

### 1. Always Use `IF NOT EXISTS` / `IF EXISTS`

Migrations must be idempotent. Use guards to prevent errors on re-runs:

```sql
-- Adding a column
ALTER TABLE events ADD COLUMN IF NOT EXISTS my_column String DEFAULT '';

-- Creating a table
CREATE TABLE IF NOT EXISTS my_table (...);

-- Dropping a column
ALTER TABLE events DROP COLUMN IF EXISTS old_column;
```

### 2. Prefer Non-Blocking Operations

Avoid operations that lock the entire table. ClickHouse mutations run asynchronously by default.

```sql
-- Good: runs asynchronously
ALTER TABLE events UPDATE my_column = 'value' WHERE condition;

-- Avoid synchronous mutations in production migrations
-- SET mutations_sync = 1;  -- Only use in tests
```

### 3. Use DEFAULT Values for New Columns

New columns should have sensible defaults to avoid NULL-handling complexity:

```sql
ALTER TABLE events
    ADD COLUMN IF NOT EXISTS feature_flags String DEFAULT '',
    ADD COLUMN IF NOT EXISTS feature_flags_set Array(String) DEFAULT [];
```

## Schema Design

### Choosing the Right Column Type

| Use Case | Recommended Type |
|----------|------------------|
| Short strings (IDs, names) | `String` |
| Long text / JSON blobs | `String` (compressed) |
| Flags / booleans | `UInt8` |
| Counts | `UInt64` |
| Timestamps | `DateTime64(6, 'UTC')` |
| Nullable fields | `Nullable(T)` — use sparingly |
| Low-cardinality strings | `LowCardinality(String)` |

### Avoid Nullable Unless Necessary

`Nullable` columns have overhead. Use sentinel values instead:

```sql
-- Prefer this
ADD COLUMN IF NOT EXISTS user_id String DEFAULT ''

-- Over this (unless NULL has semantic meaning)
ADD COLUMN IF NOT EXISTS user_id Nullable(String)
```

## Ordering and Dependencies

### Migration File Naming

Files must be sequentially numbered to ensure deterministic ordering:

```
0001_init.py
0002_add_events_table.py
0003_add_person_id_column.py
```

Never reuse or reorder existing numbers.

### Cross-Table Dependencies

If a migration depends on another table existing, add an explicit check:

```python
def migrate(client):
    # Ensure dependency exists before proceeding
    if not table_exists(client, 'persons'):
        raise RuntimeError("persons table must exist before this migration")
    client.execute("ALTER TABLE events ADD COLUMN IF NOT EXISTS person_id String DEFAULT ''")
```

## Performance Considerations

### Large Table Mutations

For tables with billions of rows, mutations can take hours. Strategies:

1. **Add column with DEFAULT** — instant, no rewrite needed
2. **Backfill in batches** — use a separate backfill script, not the migration itself
3. **Monitor mutation progress** — query `system.mutations`

```sql
-- Check pending mutations
SELECT database, table, mutation_id, command, is_done, latest_fail_reason
FROM system.mutations
WHERE is_done = 0
ORDER BY create_time DESC;
```

### Materialized Columns

For computed columns that are queried frequently, prefer materialized columns over views:

```sql
ALTER TABLE events
    ADD COLUMN IF NOT EXISTS event_date Date
    MATERIALIZED toDate(timestamp);
```

## Replicated Tables

For tables using `ReplicatedMergeTree`, DDL changes propagate automatically across replicas. However:

- Do **not** run the same `ALTER TABLE` on each replica manually
- Use `ON CLUSTER` syntax for distributed DDL when using a ClickHouse cluster

```sql
-- Single-node or replicated (handled automatically)
ALTER TABLE events ADD COLUMN IF NOT EXISTS new_col String DEFAULT '';

-- Cluster-wide DDL (only if using ON CLUSTER setup)
ALTER TABLE events ON CLUSTER '{cluster}' ADD COLUMN IF NOT EXISTS new_col String DEFAULT '';
```

## Rollback Strategy

ClickHouse does not support transactional DDL. Plan rollbacks explicitly:

1. **Column additions** — drop the column in the rollback migration
2. **Column drops** — avoid dropping until data is confirmed migrated; use a two-phase approach
3. **Table renames** — keep the old table until the new one is verified

See `rollback-strategies.md` for detailed patterns.

## Testing Checklist

Before merging a migration:

- [ ] Migration is idempotent (safe to run twice)
- [ ] Uses `IF NOT EXISTS` / `IF EXISTS` guards
- [ ] Tested locally with `pytest` (see `testing-guide.md`)
- [ ] No synchronous mutations on large tables
- [ ] Rollback path is documented or implemented
- [ ] Column types match existing conventions (see `column-types.md`)

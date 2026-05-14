# ClickHouse Migration Performance Tips

This guide covers performance considerations when writing ClickHouse migrations in PostHog.

## Avoid Blocking Operations

ClickHouse DDL operations can be resource-intensive. Follow these guidelines to minimize impact on production.

### Use `ALTER TABLE ... ADD COLUMN` Carefully

Adding a column with a `DEFAULT` expression that requires computation over existing rows will trigger a background mutation:

```sql
-- SLOW: triggers mutation over all existing data
ALTER TABLE sharded_events ADD COLUMN my_col UInt8 DEFAULT toUInt8(JSONExtractInt(properties, 'my_key'));

-- FAST: add with a static default, backfill separately
ALTER TABLE sharded_events ADD COLUMN my_col UInt8 DEFAULT 0;
```

### Prefer Lightweight Column Additions

Columns with constant defaults (including `0`, `''`, `NULL`) are added instantly — ClickHouse stores the default and does not rewrite data files:

```sql
-- Instant — no data rewrite
ALTER TABLE events ON CLUSTER '{cluster}' ADD COLUMN IF NOT EXISTS is_processed UInt8 DEFAULT 0;
```

## Backfills

When you need to populate a new column from existing data, use a separate `UPDATE` mutation and wait for it to complete before depending on the column values.

```sql
-- Step 1: add column (fast)
ALTER TABLE events ON CLUSTER '{cluster}' ADD COLUMN IF NOT EXISTS session_id String DEFAULT '';

-- Step 2: backfill (slow, runs in background)
ALTER TABLE events ON CLUSTER '{cluster}' UPDATE session_id = JSONExtractString(properties, '$session_id')
WHERE session_id = '' AND timestamp > now() - INTERVAL 90 DAY;
```

See `rollback-strategies.md` for how to track mutation progress.

## Partition Pruning

Where possible, scope `UPDATE`/`DELETE` mutations to specific partitions to reduce I/O:

```sql
-- Scoped to a single month partition
ALTER TABLE events ON CLUSTER '{cluster}'
UPDATE my_col = 1
WHERE toYYYYMM(timestamp) = 202401 AND team_id = 1;
```

## Index Considerations

### Skip Indexes

Adding a skip (secondary) index requires a full table scan to build the index granules. Schedule this during low-traffic windows:

```sql
ALTER TABLE events ON CLUSTER '{cluster}'
ADD INDEX IF NOT EXISTS idx_session_id session_id TYPE bloom_filter(0.01) GRANULARITY 1;

-- Must materialize explicitly
ALTER TABLE events ON CLUSTER '{cluster}' MATERIALIZE INDEX idx_session_id;
```

### Primary Key Changes

You **cannot** change the primary key of an existing table. Instead:
1. Create a new table with the desired key.
2. Insert data from the old table.
3. Rename tables atomically.

## Mutations Concurrency

ClickHouse processes mutations sequentially per table (one at a time). Avoid issuing multiple heavy mutations simultaneously:

```python
# In migration code — check for pending mutations before adding new ones
def wait_for_mutations(client, table: str, timeout_seconds: int = 300) -> None:
    import time
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        result = client.execute(
            "SELECT count() FROM system.mutations WHERE table = %(table)s AND is_done = 0",
            {"table": table},
        )
        if result[0][0] == 0:
            return
        time.sleep(5)
    raise TimeoutError(f"Mutations on {table} did not complete within {timeout_seconds}s")
```

## Replication Lag

On replicated clusters, DDL changes propagate asynchronously. Always use `ON CLUSTER '{cluster}'` and verify the change on all replicas before proceeding:

```sql
SELECT hostname(), is_leader, total_replicas, active_replicas
FROM system.replicas
WHERE table = 'events';
```

## Summary Checklist

| Concern | Recommendation |
|---|---|
| Adding column | Use static default; avoid computed defaults |
| Backfilling data | Use scoped `UPDATE` mutations with partition filter |
| Skip indexes | Materialize during off-peak hours |
| Multiple mutations | Wait for prior mutations before issuing new ones |
| Cluster-wide DDL | Always include `ON CLUSTER '{cluster}'` |
| Primary key change | Create new table and swap |

# ClickHouse Migration Rollback Strategies

This document outlines strategies for safely rolling back ClickHouse migrations in PostHog.

## Why Rollbacks Are Hard in ClickHouse

ClickHouse has limited support for transactional DDL. Unlike PostgreSQL, you cannot simply `ROLLBACK` a migration. This means:

- Column additions are generally safe to roll back (drop the column)
- Column removals are **destructive** and data is lost
- Table renames require careful coordination
- `ALTER TABLE ... MODIFY COLUMN` may rewrite data

## Safe Migration Patterns

### 1. Additive-Only Migrations (Preferred)

Always prefer adding new columns/tables rather than modifying or removing existing ones.

```sql
-- GOOD: Adding a new nullable column with a default
ALTER TABLE sharded_events
    ADD COLUMN IF NOT EXISTS my_new_column String DEFAULT ''
    ON CLUSTER '{cluster}';

ALTER TABLE events
    ADD COLUMN IF NOT EXISTS my_new_column String DEFAULT ''
    ON CLUSTER '{cluster}';
```

Rollback:
```sql
ALTER TABLE sharded_events
    DROP COLUMN IF EXISTS my_new_column
    ON CLUSTER '{cluster}';

ALTER TABLE events
    DROP COLUMN IF EXISTS my_new_column
    ON CLUSTER '{cluster}';
```

### 2. Two-Phase Column Removal

Never remove a column in a single migration if application code still references it.

**Phase 1** — Deploy code that stops reading/writing the column.

**Phase 2** — After confirming Phase 1 is stable (hours/days later), drop the column:

```sql
ALTER TABLE sharded_events
    DROP COLUMN IF EXISTS deprecated_column
    ON CLUSTER '{cluster}';
```

### 3. Index / Projection Rollbacks

Projections and secondary indexes can be dropped without data loss:

```sql
-- Rollback a projection
ALTER TABLE sharded_events
    DROP PROJECTION IF EXISTS my_projection
    ON CLUSTER '{cluster}';

-- Rollback a secondary index
ALTER TABLE sharded_events
    DROP INDEX IF EXISTS my_index
    ON CLUSTER '{cluster}';
```

### 4. Table Rename Rollback

```sql
-- Original rename
RENAME TABLE old_table TO new_table ON CLUSTER '{cluster}';

-- Rollback
RENAME TABLE new_table TO old_table ON CLUSTER '{cluster}';
```

> ⚠️ Ensure no queries are running against either table during a rename.

## Writing Reversible Migrations

Every migration in `posthog/migrations/` should include a rollback SQL comment block:

```python
# migration_0123_add_my_column.py

operations = [
    migrations.RunSQL(
        # --- Forward ---
        sql="""
        ALTER TABLE sharded_events
            ADD COLUMN IF NOT EXISTS my_column UInt8 DEFAULT 0
            ON CLUSTER '{cluster}';

        ALTER TABLE events
            ADD COLUMN IF NOT EXISTS my_column UInt8 DEFAULT 0
            ON CLUSTER '{cluster}';
        """,
        # --- Rollback ---
        reverse_sql="""
        ALTER TABLE sharded_events
            DROP COLUMN IF EXISTS my_column
            ON CLUSTER '{cluster}';

        ALTER TABLE events
            DROP COLUMN IF EXISTS my_column
            ON CLUSTER '{cluster}';
        """,
    )
]
```

## Emergency Rollback Checklist

1. **Identify the migration** — find the migration file and its `reverse_sql`.
2. **Check for data dependency** — has any data been written to new columns? Can it be reconstructed?
3. **Coordinate deploys** — roll back application code *before* rolling back the schema if columns are being removed.
4. **Run on a replica first** — test the rollback SQL on a non-production replica.
5. **Execute on cluster** — always use `ON CLUSTER '{cluster}'` for distributed tables.
6. **Verify replication** — confirm all replicas have applied the change via `system.replication_queue`.

## What Cannot Be Rolled Back

| Operation | Rollback Possible? | Notes |
|---|---|---|
| Add column | ✅ Yes | Drop the column |
| Drop column | ❌ No | Data is lost |
| Modify column type | ⚠️ Sometimes | Depends on type compatibility |
| Add index/projection | ✅ Yes | Drop it |
| Create table | ✅ Yes | Drop the table |
| Drop table | ❌ No | Data is lost |
| Insert data | ❌ No | Use soft deletes instead |

## References

- [ClickHouse ALTER TABLE docs](https://clickhouse.com/docs/en/sql-reference/statements/alter/)
- `posthog/migrations/` — existing migration examples
- `.agents/skills/clickhouse-migrations/SKILL.md` — migration authoring guide

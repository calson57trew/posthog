# ClickHouse Migration Patterns

This document describes common patterns and best practices for writing ClickHouse migrations in PostHog.

## Overview

ClickHouse migrations are managed differently from Django/PostgreSQL migrations. They are run as raw SQL files and must account for ClickHouse's distributed, columnar nature.

## File Naming Convention

Migration files follow the pattern:
```
{sequence_number}_{description}.sql
```

Example:
```
0001_persons_add_version_column.sql
0002_events_add_person_id_index.sql
```

## Common Migration Patterns

### 1. Adding a Column

ClickHouse supports `ADD COLUMN` with a default value. Always provide a default to avoid breaking existing data.

```sql
-- Add a nullable column
ALTER TABLE sharded_events
    ON CLUSTER '{cluster}'
    ADD COLUMN IF NOT EXISTS person_mode Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2) DEFAULT 'full';

-- Replicate to the distributed table
ALTER TABLE events
    ON CLUSTER '{cluster}'
    ADD COLUMN IF NOT EXISTS person_mode Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2) DEFAULT 'full';
```

**Key rules:**
- Always use `IF NOT EXISTS` to make migrations idempotent
- Always run on `ON CLUSTER '{cluster}'`
- Apply to both the sharded table and the distributed table

### 2. Adding an Index

ClickHouse supports several index types. Choose based on the query pattern.

```sql
-- Bloom filter index for low-cardinality string lookups
ALTER TABLE sharded_events
    ON CLUSTER '{cluster}'
    ADD INDEX IF NOT EXISTS minmax_event_type event_type TYPE minmax GRANULARITY 1;

-- Set index for equality checks on high-cardinality columns
ALTER TABLE sharded_events
    ON CLUSTER '{cluster}'
    ADD INDEX IF NOT EXISTS bf_person_id person_id TYPE bloom_filter() GRANULARITY 1;
```

**After adding an index, materialize it:**
```sql
ALTER TABLE sharded_events
    ON CLUSTER '{cluster}'
    MATERIALIZE INDEX minmax_event_type;
```

### 3. Creating a New Table

```sql
CREATE TABLE IF NOT EXISTS sharded_person_overrides
ON CLUSTER '{cluster}'
(
    team_id Int64,
    old_person_id UUID,
    override_person_id UUID,
    oldest_event DateTime64(6, 'UTC'),
    created_at DateTime64(6, 'UTC') DEFAULT now64(6, 'UTC'),
    version Int64 DEFAULT 1
)
ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{shard}/posthog.person_overrides',
    '{replica}',
    version
)
ORDER BY (team_id, old_person_id)
SETTINGS index_granularity = 8192;

-- Create the distributed table
CREATE TABLE IF NOT EXISTS person_overrides
ON CLUSTER '{cluster}'
AS sharded_person_overrides
ENGINE = Distributed('{cluster}', 'posthog', 'sharded_person_overrides', cityHash64(concat(toString(team_id), toString(old_person_id))));
```

### 4. Modifying a Column Type

ClickHouse does not support direct type changes on columns that are part of the `ORDER BY` key. For other columns:

```sql
-- Widen a numeric type
ALTER TABLE sharded_events
    ON CLUSTER '{cluster}'
    MODIFY COLUMN IF EXISTS distinct_id VARCHAR;
```

> ⚠️ **Warning:** Changing column types requires a full table scan and can be very slow on large tables. Always test on a staging environment first.

### 5. Dropping a Column

```sql
-- Always check that the column is no longer referenced in application code before dropping
ALTER TABLE sharded_events
    ON CLUSTER '{cluster}'
    DROP COLUMN IF EXISTS deprecated_column;

ALTER TABLE events
    ON CLUSTER '{cluster}'
    DROP COLUMN IF EXISTS deprecated_column;
```

## Idempotency

All migrations **must** be idempotent. Use:
- `IF NOT EXISTS` for `CREATE TABLE` and `ADD COLUMN`
- `IF EXISTS` for `DROP COLUMN` and `DROP TABLE`
- Check before modifying with a conditional in application code if SQL doesn't support it natively

## Testing Migrations Locally

1. Start the local ClickHouse instance:
   ```bash
   docker compose up clickhouse
   ```

2. Run migrations:
   ```bash
   python manage.py migrate_clickhouse
   ```

3. Verify the schema:
   ```bash
   docker exec -it posthog-clickhouse-1 clickhouse-client --query "DESCRIBE TABLE posthog.events"
   ```

## References

- [ClickHouse ALTER TABLE docs](https://clickhouse.com/docs/en/sql-reference/statements/alter/)
- [ClickHouse Data Skipping Indexes](https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/mergetree#table_engine-mergetree-data_skipping-indexes)
- See also: `database-indexes.md` in the `adding-personhog-rpc` skill for index strategy guidance

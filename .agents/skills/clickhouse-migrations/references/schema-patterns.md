# ClickHouse Schema Patterns

This reference covers common schema patterns used in PostHog's ClickHouse migrations.

## Table Engines

### ReplacingMergeTree
Use when you need deduplication based on a version column:

```sql
CREATE TABLE IF NOT EXISTS events
(
    uuid UUID,
    event VARCHAR,
    properties VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id VARCHAR,
    created_at DateTime64(6, 'UTC'),
    _timestamp DateTime,
    _offset UInt64
) ENGINE = ReplacingMergeTree(_timestamp)
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), event, cityHash64(distinct_id), uuid)
```

### CollapsingMergeTree
Use for mutable data with sign column:

```sql
CREATE TABLE IF NOT EXISTS person
(
    id UUID,
    created_at DateTime64,
    team_id Int64,
    properties VARCHAR,
    is_identified Int8,
    is_deleted Int8 DEFAULT 0,
    _timestamp DateTime,
    _offset UInt64,
    sign Int8 DEFAULT 1
) ENGINE = CollapsingMergeTree(sign)
ORDER BY (team_id, id)
```

## Distributed Tables

For sharded clusters, always create both local and distributed versions:

```sql
-- Local table (on each shard)
CREATE TABLE IF NOT EXISTS events_local ON CLUSTER '{cluster}'
(
    ...
) ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{shard}/{database}/events',
    '{replica}',
    _timestamp
)
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), event, cityHash64(distinct_id), uuid)

-- Distributed table (query layer)
CREATE TABLE IF NOT EXISTS events ON CLUSTER '{cluster}'
AS events_local
ENGINE = Distributed('{cluster}', currentDatabase(), events_local, rand())
```

## Adding Columns

### Safe Column Addition
Always use `IF NOT EXISTS` and provide defaults:

```sql
ALTER TABLE events
    ADD COLUMN IF NOT EXISTS elements_chain VARCHAR DEFAULT ''
```

### Materialized Columns
For computed columns that should be stored:

```sql
ALTER TABLE events
    ADD COLUMN IF NOT EXISTS $group_0 VARCHAR MATERIALIZED
        JSONExtractString(properties, '$group_0')
```

## Codec Patterns

Use appropriate codecs to reduce storage:

```sql
CREATE TABLE IF NOT EXISTS session_recording_events
(
    uuid UUID CODEC(ZSTD(1)),
    timestamp DateTime64(6, 'UTC') CODEC(Delta, ZSTD(1)),
    team_id Int64 CODEC(Delta, ZSTD(1)),
    distinct_id VARCHAR CODEC(ZSTD(1)),
    session_id VARCHAR CODEC(ZSTD(1)),
    window_id VARCHAR CODEC(ZSTD(1)),
    snapshot_data VARCHAR CODEC(ZSTD(1)),
    created_at DateTime64(6, 'UTC') CODEC(ZSTD(1))
) ENGINE = ReplacingMergeTree(created_at)
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), session_id, window_id, distinct_id, timestamp)
```

## Index Patterns

### Skipping Indexes
Add bloom filter indexes for high-cardinality string columns:

```sql
ALTER TABLE events
    ADD INDEX IF NOT EXISTS bf_distinct_id distinct_id
    TYPE bloom_filter(0.01)
    GRANULARITY 1
```

### Set Index
For low-cardinality columns used in WHERE clauses:

```sql
ALTER TABLE events
    ADD INDEX IF NOT EXISTS idx_event event
    TYPE set(100)
    GRANULARITY 4
```

## Partition Management

### TTL Policies
Define data retention at the table level:

```sql
ALTER TABLE events MODIFY TTL toDate(timestamp) + INTERVAL 1 YEAR
```

### Partition Pruning
Always include partition key in WHERE clauses for performance:

```sql
-- Good: uses partition pruning
SELECT count() FROM events
WHERE team_id = 1
  AND timestamp >= '2024-01-01'
  AND timestamp < '2024-02-01'

-- Bad: full table scan
SELECT count() FROM events
WHERE team_id = 1
```

## Naming Conventions

- Local tables: `{name}_local`
- Distributed tables: `{name}` (no suffix)
- Migration files: `NNNN_description.py` (zero-padded 4-digit number)
- Indexes: `idx_{column}` for standard, `bf_{column}` for bloom filters

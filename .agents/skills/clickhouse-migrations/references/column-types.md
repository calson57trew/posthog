# ClickHouse Column Types Reference

This reference covers the most commonly used ClickHouse column types in PostHog migrations, their use cases, and gotchas to watch out for.

## Numeric Types

### UInt8, UInt16, UInt32, UInt64
Use for non-negative integers. Prefer the smallest type that fits your data range.

```sql
-- Boolean flags (0 or 1)
flag UInt8 DEFAULT 0,

-- Counts that won't exceed ~65k
short_count UInt16,

-- Standard counts and IDs
count UInt32,

-- Large IDs, timestamps in microseconds
big_id UInt64,
```

### Int8, Int16, Int32, Int64
Use when negative values are possible.

```sql
-- Score that can be negative
score Int32 DEFAULT 0,
```

### Float32, Float64
Avoid where possible — use Decimal for financial data or integer representations (e.g., store milliseconds as UInt64).

```sql
-- Only when approximate values are acceptable
latitude Float64,
longitude Float64,
```

## String Types

### String
Variable-length byte string. Used for arbitrary text, JSON blobs, URLs.

```sql
properties String DEFAULT '{}',
distinct_id String,
```

### FixedString(N)
Fixed-length string, zero-padded. Use only when all values are exactly N bytes (e.g., UUIDs stored as raw bytes).

```sql
-- UUID stored as 16-byte raw value (rare — prefer String for readability)
uuid_bytes FixedString(16),
```

### LowCardinality(String)
Dictionary-encoded string. Use when the column has fewer than ~10,000 distinct values.

```sql
-- Event types, team names, status codes
event LowCardinality(String),
status LowCardinality(String) DEFAULT 'active',
```

**Warning:** Do not use `LowCardinality` on high-cardinality columns like `distinct_id` or `uuid` — it will degrade performance.

## Date and Time Types

### DateTime
Stores date and time with second precision. Always specify timezone explicitly.

```sql
created_at DateTime('UTC'),
```

### DateTime64(precision, timezone)
Stores date and time with sub-second precision. Use `3` for milliseconds, `6` for microseconds.

```sql
-- Millisecond precision (most common in PostHog)
timestamp DateTime64(3, 'UTC'),

-- Microsecond precision
high_res_timestamp DateTime64(6, 'UTC'),
```

### Date
Date only (no time). Useful for partitioning keys.

```sql
-- Used in PARTITION BY clauses
toDate(timestamp) -- expression, not a column type
```

## Nullable Types

Avoid `Nullable` where possible — it adds overhead and complicates queries. Use sentinel values or separate boolean flags instead.

```sql
-- Prefer this:
some_value String DEFAULT '',
has_some_value UInt8 DEFAULT 0,

-- Over this (avoid unless truly necessary):
some_value Nullable(String),
```

When `Nullable` is truly required:

```sql
external_id Nullable(String),
deleted_at Nullable(DateTime('UTC')),
```

## Array Types

```sql
-- Array of strings
tags Array(String) DEFAULT [],

-- Array of UInt64
related_ids Array(UInt64) DEFAULT [],
```

**Note:** Arrays cannot be used as primary key components.

## Map Types

Available in ClickHouse 21.1+. Useful for dynamic key-value data, but query syntax is more complex than JSON stored in String columns.

```sql
metadata Map(String, String) DEFAULT {},
```

## Enum Types

Use for columns with a small, fixed set of string values. More efficient than `LowCardinality(String)` for truly static enums.

```sql
state Enum8('pending' = 1, 'running' = 2, 'completed' = 3, 'failed' = 4),
```

**Warning:** Adding new Enum values requires an `ALTER TABLE` statement.

## Codecs (Compression)

Specify codecs to improve compression for specific data patterns:

```sql
-- Delta codec for monotonically increasing values (timestamps, auto-increment IDs)
timestamp DateTime64(3, 'UTC') CODEC(Delta, ZSTD(1)),

-- ZSTD for general-purpose compression
properties String CODEC(ZSTD(3)),

-- T64 for integer columns with small deltas
count UInt64 CODEC(T64, ZSTD(1)),
```

## Common Patterns in PostHog

```sql
-- Standard event-like table columns
team_id Int64,
uuid UUID,
distinct_id String,
event LowCardinality(String),
properties String DEFAULT '{}',
timestamp DateTime64(3, 'UTC'),
created_at DateTime('UTC') DEFAULT now(),
```

## Type Migration Gotchas

1. **Widening integers is safe** (`UInt32` → `UInt64`), narrowing is not.
2. **`String` → `LowCardinality(String)`** requires a full column rewrite via mutation.
3. **Adding `DEFAULT` to existing columns** does not backfill existing rows — use `ALTER TABLE ... UPDATE` for that.
4. **`Nullable` removal** requires a mutation to replace NULLs with sentinel values first.
5. **DateTime → DateTime64** is a breaking change requiring a new column + backfill strategy.

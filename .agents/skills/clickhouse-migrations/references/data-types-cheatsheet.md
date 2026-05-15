# ClickHouse Data Types Cheatsheet

Quick reference for choosing the right ClickHouse data types in PostHog migrations.

## Numeric Types

| Type | Range | Use Case |
|------|-------|----------|
| `UInt8` | 0–255 | Boolean flags, small enums |
| `UInt16` | 0–65535 | Small counters |
| `UInt32` | 0–4B | IDs, counts |
| `UInt64` | 0–18.4e18 | Large IDs, timestamps (epoch ms) |
| `Int8` | -128–127 | Signed small values |
| `Int32` | -2.1B–2.1B | Signed counters |
| `Int64` | -9.2e18–9.2e18 | Signed large values |
| `Float32` | ~7 decimal digits | Low-precision floats |
| `Float64` | ~15 decimal digits | High-precision floats |
| `Decimal(P, S)` | Configurable | Financial/exact arithmetic |

### Recommendations
- Prefer `UInt64` for event/person IDs — avoids overflow as data grows.
- Avoid `Float` for counts or monetary values; use `Decimal` or integer scaling.
- Use `UInt8` (0/1) for boolean columns instead of `Bool` for broader compatibility.

---

## String Types

| Type | Notes |
|------|-------|
| `String` | Variable-length, arbitrary bytes. Most common choice. |
| `FixedString(N)` | Exactly N bytes. Slightly faster for fixed-width values (e.g., UUIDs stored as bytes). |
| `LowCardinality(String)` | Dictionary-encoded. Use when cardinality < ~10k distinct values. |

### Recommendations
- Use `LowCardinality(String)` for columns like `event`, `team_id` (as string), `browser`, `os`.
- Avoid `LowCardinality` on high-cardinality columns (e.g., `distinct_id`, `uuid`) — it degrades performance.
- UUIDs: store as `UUID` type or `String`; avoid `FixedString(16)` unless you control serialization.

---

## Date & Time Types

| Type | Precision | Range |
|------|-----------|-------|
| `Date` | Day | 1970-01-01 – 2149-06-06 |
| `Date32` | Day | 1900-01-01 – 2299-12-31 |
| `DateTime` | Second | 1970-01-01 – 2106-02-07 |
| `DateTime64(3)` | Millisecond | Wide range |
| `DateTime64(6)` | Microsecond | Wide range |

### Recommendations
- Use `DateTime64(6, 'UTC')` for event timestamps — PostHog stores microsecond precision.
- Always specify timezone explicitly: `DateTime('UTC')` or `DateTime64(6, 'UTC')`.
- Use `toDate(timestamp)` in partition keys, not the raw `DateTime64`.

---

## UUID

```sql
-- Preferred for person_id, event uuid
uuid UUID

-- Default value
uuid UUID DEFAULT generateUUIDv4()
```

- Stored as 16 bytes internally (efficient).
- Displayed as standard hyphenated string.
- Use `toUUID('...')` for comparisons in queries.

---

## Nullable Types

```sql
-- Allowed but discouraged
value Nullable(Float64)

-- Preferred pattern: use sentinel values
value Float64 DEFAULT 0
name String DEFAULT ''
```

### Recommendations
- **Avoid `Nullable` in ORDER BY / PRIMARY KEY columns** — not supported.
- `Nullable` columns cannot be used in indexes.
- Prefer default sentinel values (`0`, `''`, `'unknown'`) over `Nullable` for performance.
- Only use `Nullable` when NULL has distinct semantic meaning from a default.

---

## Array & Map Types

```sql
-- Arrays
tags Array(String)
scores Array(Float64)

-- Maps (ClickHouse 21.1+)
properties Map(String, String)

-- Nested (legacy, avoid in new schemas)
Nested(
    key String,
    value String
)
```

### Recommendations
- Use `Array(String)` for simple multi-value columns.
- Use `Map(String, String)` for dynamic key-value properties where keys aren't known ahead of time.
- Avoid `Nested` in new migrations — it has surprising semantics and is harder to query.
- For PostHog event properties, `String` (JSON-encoded) is often simpler than `Map`.

---

## Enum Types

```sql
status Enum8('pending' = 1, 'active' = 2, 'deleted' = 3)
type Enum16('pageview' = 1, 'identify' = 2, 'custom' = 3)
```

- `Enum8` supports up to 256 values; `Enum16` up to 65536.
- More storage-efficient and faster than `LowCardinality(String)` for truly fixed sets.
- **Adding new enum values requires an ALTER TABLE** — prefer `LowCardinality(String)` if the set may grow.

---

## Codec Recommendations

```sql
-- Timestamps (monotonically increasing)
timestamp DateTime64(6, 'UTC') CODEC(Delta, ZSTD(1))

-- IDs / UUIDs
uuid UUID CODEC(ZSTD(1))

-- Low-entropy strings
event LowCardinality(String) CODEC(ZSTD(1))

-- Numeric counters
count UInt64 CODEC(Delta, ZSTD(1))
```

- `Delta` codec works best on monotonically increasing or slowly-changing numeric/date columns.
- `ZSTD(1)` is a good default compression for most columns.
- `LZ4` is faster to decompress but compresses less — use for hot read paths.

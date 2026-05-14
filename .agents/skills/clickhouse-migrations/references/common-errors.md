# Common ClickHouse Migration Errors

This reference covers frequently encountered errors when writing or running ClickHouse migrations in PostHog, along with their causes and resolutions.

---

## 1. `Code: 44. DB::Exception: Column ... already exists`

**Cause:** The migration attempts to `ADD COLUMN` but the column was already added (e.g., by a previous partial run or a manually applied change).

**Fix:** Use `ADD COLUMN IF NOT EXISTS`:

```sql
ALTER TABLE sharded_events
    ADD COLUMN IF NOT EXISTS my_new_column String DEFAULT ''
```

> Always prefer `IF NOT EXISTS` / `IF EXISTS` guards in migration DDL to make operations idempotent.

---

## 2. `Code: 48. DB::Exception: Mutations are not supported for ReplicatedMergeTree`

**Cause:** Trying to run an `UPDATE` or `DELETE` directly on a Replicated table without using the mutation API, or using an engine that does not support mutations.

**Fix:** Use `ALTER TABLE ... UPDATE` (mutation syntax) and ensure the table engine is `ReplicatedReplacingMergeTree` or similar that supports mutations:

```sql
ALTER TABLE events UPDATE properties = '' WHERE team_id = 0
```

Then wait for the mutation to complete before proceeding (see `wait_for_mutations` in testing-guide.md).

---

## 3. Migration applied on coordinator but not on shards

**Cause:** PostHog runs ClickHouse in a sharded cluster. DDL sent only to the coordinator node will not propagate automatically unless `ON CLUSTER` is specified.

**Fix:** Always include `ON CLUSTER '{cluster}'` in DDL statements:

```sql
ALTER TABLE sharded_events ON CLUSTER '{cluster}'
    ADD COLUMN IF NOT EXISTS my_new_column UInt8 DEFAULT 0
```

And apply the matching change to the distributed table when required:

```sql
ALTER TABLE writable_events ON CLUSTER '{cluster}'
    ADD COLUMN IF NOT EXISTS my_new_column UInt8 DEFAULT 0
```

---

## 4. `Code: 36. DB::Exception: Incorrect data type of MATERIALIZED expression`

**Cause:** The expression used for a `MATERIALIZED` column does not match the declared column type.

**Fix:** Cast explicitly:

```sql
ADD COLUMN IF NOT EXISTS is_identified UInt8
    MATERIALIZED toUInt8(JSONExtractBool(properties, '$is_identified'))
```

---

## 5. `Table ... is in readonly mode`

**Cause:** A replica has lost its ZooKeeper session or fallen behind and entered read-only mode. Migrations that run during this window will fail.

**Fix:**
- Wait for the replica to recover and re-sync with ZooKeeper.
- Check replica status: `SELECT * FROM system.replicas WHERE is_readonly = 1`
- In CI, ensure the ClickHouse container is fully healthy before running migrations.

---

## 6. `Code: 341. DB::Exception: Cannot DROP or DETACH INDEX ... Index does not exist`

**Cause:** Attempting to drop a secondary (data-skipping) index that was never created or was already removed.

**Fix:** Use `DROP INDEX IF EXISTS`:

```sql
ALTER TABLE events ON CLUSTER '{cluster}'
    DROP INDEX IF EXISTS my_index
```

---

## 7. Migration Python class not discovered

**Cause:** The migration file exists but the class is not named `Migration` or the file is not in the correct directory.

**Fix:**
- The class **must** be named exactly `Migration`.
- The file must live under `posthog/clickhouse/migrations/`.
- The filename must follow the pattern `NNNN_description.py` where `NNNN` is a zero-padded integer one higher than the current maximum.

```
posthog/clickhouse/migrations/
  0001_events_table.py
  0002_persons_table.py
  0042_my_new_migration.py   ← new file
```

---

## 8. `Code: 60. DB::Exception: Table ... doesn't exist`

**Cause:** The migration references a table that has not been created yet, or uses the wrong table name (e.g., `events` instead of `sharded_events`).

**Fix:** Double-check table names against `posthog/clickhouse/schema.py` and ensure dependent migrations run first by ordering file numbers correctly.

---

## Quick Checklist

Before submitting a migration PR, verify:

- [ ] DDL uses `IF NOT EXISTS` / `IF EXISTS` guards
- [ ] `ON CLUSTER '{cluster}'` is present for all DDL
- [ ] Both `sharded_*` and `writable_*` / distributed tables are updated where needed
- [ ] Migration class is named `Migration`
- [ ] File number is one higher than the current maximum
- [ ] Tests cover forward migration and (where applicable) rollback

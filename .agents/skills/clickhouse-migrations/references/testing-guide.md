# ClickHouse Migration Testing Guide

This guide covers how to test ClickHouse migrations locally and in CI before deploying to production.

## Local Testing Setup

### Prerequisites

- Docker and Docker Compose installed
- PostHog development environment set up
- ClickHouse client (`clickhouse-client`) available

### Starting ClickHouse Locally

```bash
docker compose -f docker-compose.dev.yml up clickhouse -d
```

Verify it's running:

```bash
clickhouse-client --host localhost --port 9000 --query "SELECT version()"
```

## Running Migrations

### Apply All Pending Migrations

```bash
python manage.py migrate_clickhouse
```

### Apply a Specific Migration

```bash
python manage.py migrate_clickhouse --upto 0042_my_new_migration
```

### Check Migration Status

```bash
python manage.py showmigrations_clickhouse
```

## Writing Tests for Migrations

### Unit Test Structure

Place migration tests in `posthog/clickhouse/migrations/tests/`.

```python
# posthog/clickhouse/migrations/tests/test_0042_my_migration.py
from posthog.clickhouse.client import sync_execute
from posthog.test.base import BaseTest


class Test0042MyMigration(BaseTest):
    """
    Tests for migration 0042: adds new column to events table.
    """

    def test_column_exists_after_migration(self):
        result = sync_execute(
            """
            SELECT name
            FROM system.columns
            WHERE table = 'sharded_events'
              AND database = currentDatabase()
              AND name = 'my_new_column'
            """
        )
        self.assertEqual(len(result), 1, "Expected column 'my_new_column' to exist")

    def test_column_has_correct_type(self):
        result = sync_execute(
            """
            SELECT type
            FROM system.columns
            WHERE table = 'sharded_events'
              AND database = currentDatabase()
              AND name = 'my_new_column'
            """
        )
        self.assertEqual(result[0][0], "Nullable(String)")
```

### Testing Data Integrity

When a migration backfills or transforms data, verify correctness:

```python
def test_backfill_preserves_row_count(self):
    before_count = sync_execute("SELECT count() FROM events")[0][0]
    # run migration logic here if needed
    after_count = sync_execute("SELECT count() FROM events")[0][0]
    self.assertEqual(before_count, after_count)
```

## Validating Index Changes

After adding or modifying indexes, confirm they appear in `system.data_skipping_indices`:

```sql
SELECT name, type, expr
FROM system.data_skipping_indices
WHERE table = 'sharded_events'
  AND database = currentDatabase();
```

## Common Pitfalls

### Mutations Are Async

`ALTER TABLE ... UPDATE` and `ALTER TABLE ... DELETE` are mutations and run asynchronously.
In tests, wait for completion:

```python
def wait_for_mutations(table: str, timeout: int = 30) -> None:
    import time
    start = time.time()
    while time.time() - start < timeout:
        pending = sync_execute(
            "SELECT count() FROM system.mutations WHERE table = %(table)s AND is_done = 0",
            {"table": table},
        )[0][0]
        if pending == 0:
            return
        time.sleep(1)
    raise TimeoutError(f"Mutations on {table} did not complete within {timeout}s")
```

### ReplicatedMergeTree in Tests

Local test environments often use `MergeTree` instead of `ReplicatedMergeTree`. Ensure your
migration SQL is compatible with both by using the `CLICKHOUSE_REPLICATION` setting:

```python
from posthog.settings import CLICKHOUSE_REPLICATION

engine = "ReplicatedMergeTree('/clickhouse/tables/{shard}/events', '{replica}')" if CLICKHOUSE_REPLICATION else "MergeTree()"
```

## CI Integration

Migrations are automatically tested in the `clickhouse-tests` GitHub Actions job.
To run the same suite locally:

```bash
python -m pytest posthog/clickhouse/migrations/tests/ -v
```

Always run migrations against a clean database snapshot before opening a PR to
catch issues early.

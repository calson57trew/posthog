# ClickHouse Migration Examples

Real-world examples of common migration patterns used in PostHog.

## Example 1: Adding a Nullable Column

```python
# migrations/0043_add_session_duration.py
from posthog.clickhouse.migrations.base import BaseMigration


class Migration(BaseMigration):
    """
    Adds session_duration_ms column to sharded_events table.
    This is a non-breaking change — existing rows will have NULL.
    """

    operations = [
        """
        ALTER TABLE sharded_events
        ON CLUSTER '{cluster}'
        ADD COLUMN IF NOT EXISTS session_duration_ms Nullable(UInt64)
        """,
        """
        ALTER TABLE events
        ON CLUSTER '{cluster}'
        ADD COLUMN IF NOT EXISTS session_duration_ms Nullable(UInt64)
        """,
    ]
```

## Example 2: Adding a Column with a Default Value

```python
# migrations/0044_add_person_mode.py
from posthog.clickhouse.migrations.base import BaseMigration


class Migration(BaseMigration):
    """
    Adds person_mode column with a default of 'full' to match existing behaviour.
    Uses LowCardinality(String) since cardinality is small and known.
    """

    operations = [
        """
        ALTER TABLE sharded_person
        ON CLUSTER '{cluster}'
        ADD COLUMN IF NOT EXISTS person_mode LowCardinality(String) DEFAULT 'full'
        """,
        """
        ALTER TABLE person
        ON CLUSTER '{cluster}'
        ADD COLUMN IF NOT EXISTS person_mode LowCardinality(String) DEFAULT 'full'
        """,
    ]
```

## Example 3: Creating a New Table

```python
# migrations/0045_create_heatmaps.py
from posthog.clickhouse.migrations.base import BaseMigration


CREATE_HEATMAPS_TABLE = """
CREATE TABLE IF NOT EXISTS sharded_heatmaps
ON CLUSTER '{cluster}'
(
    team_id          Int64,
    session_id       VARCHAR,
    window_id        VARCHAR,
    timestamp        DateTime64(6, 'UTC'),
    x                Int16,
    y                Int16,
    scale_factor     Int16,
    viewport_width   Int16,
    viewport_height  Int16,
    pointer_target_fixed UInt8,
    current_url      VARCHAR,
    type             LowCardinality(String),
    _timestamp       DateTime,
    _offset          UInt64
)
ENGINE = ReplicatedReplacingMergeTree(
    '/clickhouse/tables/{shard}/posthog.heatmaps',
    '{replica}',
    _timestamp
)
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), session_id, timestamp)
SETTINGS index_granularity = 512
"""

CREATE_HEATMAPS_DISTRIBUTED_TABLE = """
CREATE TABLE IF NOT EXISTS heatmaps
ON CLUSTER '{cluster}'
AS sharded_heatmaps
ENGINE = Distributed('{cluster}', posthog, sharded_heatmaps, rand())
"""


class Migration(BaseMigration):
    """
    Creates the heatmaps table for storing pointer/click heatmap events.
    Follows the sharded + distributed table pattern.
    """

    operations = [
        CREATE_HEATMAPS_TABLE,
        CREATE_HEATMAPS_DISTRIBUTED_TABLE,
    ]
```

## Example 4: Backfilling Data with a Materialized Column

```python
# migrations/0046_materialize_event_type.py
from posthog.clickhouse.migrations.base import BaseMigration


class Migration(BaseMigration):
    """
    Materializes $event_type from the properties JSON blob into its own column.
    The MATERIALIZED expression fills new rows automatically; existing rows
    require a background mutation triggered by the second operation.

    WARNING: This triggers a heavy mutation on large tables. Monitor with:
        SELECT * FROM system.mutations WHERE is_done = 0;
    """

    operations = [
        """
        ALTER TABLE sharded_events
        ON CLUSTER '{cluster}'
        ADD COLUMN IF NOT EXISTS mat_event_type VARCHAR
        MATERIALIZED JSONExtractString(properties, '$event_type')
        """,
        # Trigger backfill for existing rows
        """
        ALTER TABLE sharded_events
        ON CLUSTER '{cluster}'
        MATERIALIZE COLUMN mat_event_type
        """,
        """
        ALTER TABLE events
        ON CLUSTER '{cluster}'
        ADD COLUMN IF NOT EXISTS mat_event_type VARCHAR
        MATERIALIZED JSONExtractString(properties, '$event_type')
        """,
    ]
```

## Example 5: Dropping a Column Safely

Always drop in two phases to avoid query failures during deploy:

**Phase 1 — stop reading the column** (deploy code change first)

```python
# migrations/0047_drop_legacy_ingestion_source.py
from posthog.clickhouse.migrations.base import BaseMigration


class Migration(BaseMigration):
    """
    Drops the legacy `ingestion_source` column that was replaced by
    `lib_version` in migration 0031. Code references were removed in the
    previous release.
    """

    operations = [
        """
        ALTER TABLE sharded_events
        ON CLUSTER '{cluster}'
        DROP COLUMN IF EXISTS ingestion_source
        """,
        """
        ALTER TABLE events
        ON CLUSTER '{cluster}'
        DROP COLUMN IF EXISTS ingestion_source
        """,
    ]
```

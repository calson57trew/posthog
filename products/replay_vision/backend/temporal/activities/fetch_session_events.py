import json
import datetime as dt

from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.models import Team
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

from products.replay_vision.backend.temporal.state import (
    StateActivitiesEnum,
    get_data_str_from_redis,
    get_redis_state_client,
    store_data_in_redis,
)
from products.replay_vision.backend.temporal.types import FetchSessionEventsInputs, LensLlmInputs


def _to_jsonable(value: object) -> object:
    """Coerce ClickHouse row values to JSON-serializable forms (datetime → ISO string)."""
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    return value


@activity.defn
async def fetch_session_events_activity(inputs: FetchSessionEventsInputs) -> None:
    """Fetch analytics events for a session, stash in Redis for downstream activities.

    Idempotent — second call against the same observation finds the key and returns.
    """
    redis_client, redis_key = get_redis_state_client(
        label=StateActivitiesEnum.SESSION_EVENTS,
        state_id=str(inputs.observation_id),
    )
    assert redis_key is not None  # label + state_id always produce a key

    existing = await get_data_str_from_redis(redis_client, redis_key)
    if existing is not None:
        return

    team, payload = await sync_to_async(_fetch_payload)(inputs.team_id, inputs.session_id)
    if payload is None:
        raise ApplicationError(
            f"Session {inputs.session_id} has no events to analyze",
            non_retryable=True,
        )

    await store_data_in_redis(redis_client, redis_key, json.dumps(payload.model_dump()))


def _fetch_payload(team_id: int, session_id: str) -> tuple[Team, LensLlmInputs | None]:
    team = Team.objects.get(pk=team_id)
    events_obj = SessionReplayEvents()
    metadata = events_obj.get_metadata(session_id=session_id, team=team)
    if metadata is None:
        raise ApplicationError(f"No replay metadata found for session {session_id}", non_retryable=True)

    columns, rows = events_obj.get_events(session_id=session_id, team=team, metadata=metadata)
    if not columns or not rows:
        return team, None

    return team, LensLlmInputs(
        session_id=session_id,
        team_id=team_id,
        session_start_time=metadata["start_time"].isoformat(),
        session_end_time=metadata["end_time"].isoformat(),
        duration_seconds=float(metadata["duration"]),
        columns=list(columns),
        events=[[_to_jsonable(v) for v in row] for row in rows],
    )

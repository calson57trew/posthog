import json
import uuid
import datetime as dt
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.db import IntegrityError
from django.utils import timezone

import psycopg.errors
import temporalio.workflow as wf
from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import Organization, Team
from posthog.models.exported_asset import ExportedAsset
from posthog.models.user import User
from posthog.redis import get_async_client
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents

from products.replay_vision.backend.models.replay_lens import LensModel, LensType, ReplayLens
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.temporal import ACTIVITIES, ApplyLensWorkflow
from products.replay_vision.backend.temporal.activities.create_observation import create_observation_activity
from products.replay_vision.backend.temporal.activities.ensure_session_asset import ensure_session_asset_activity
from products.replay_vision.backend.temporal.activities.fetch_session_events import fetch_session_events_activity
from products.replay_vision.backend.temporal.activities.observation_state import (
    mark_observation_failed_activity,
    mark_observation_running_activity,
)
from products.replay_vision.backend.temporal.state import (
    StateActivitiesEnum,
    generate_state_key,
    get_data_class_from_redis,
    store_data_in_redis,
)
from products.replay_vision.backend.temporal.types import (
    ApplyLensInputs,
    CreateObservationInputs,
    CreateObservationOutput,
    EnsureSessionAssetInputs,
    EnsureSessionAssetOutput,
    FetchSessionEventsInputs,
    LensLlmInputs,
    MarkObservationFailedInputs,
    MarkObservationRunningInputs,
)


def _make_lens() -> ReplayLens:
    org = Organization.objects.create(name="vision-test-org")
    team = Team.objects.create(organization=org, name="vision-test-team")
    return ReplayLens.objects.create(
        team=team,
        name="t",
        lens_type=LensType.MONITOR,
        lens_config={"prompt": "p"},
        model=LensModel.GEMINI_3_FLASH,
    )


def _make_observation(lens: ReplayLens, **overrides) -> ReplayObservation:
    defaults: dict = {
        "lens": lens,
        "team": lens.team,
        "session_id": "sess-1",
        "triggered_by": ObservationTrigger.ON_DEMAND,
        "lens_version": lens.lens_version,
        "lens_config_snapshot": lens.lens_config,
    }
    defaults.update(overrides)
    return ReplayObservation.objects.create(**defaults)


@pytest.mark.django_db(transaction=True)
class TestCreateObservationActivity:
    def test_creates_row_in_pending_with_workflow_id_and_snapshot(self) -> None:
        lens = _make_lens()
        result = create_observation_activity(
            CreateObservationInputs(
                lens_id=lens.id,
                team_id=lens.team_id,
                session_id="sess-1",
                triggered_by=ObservationTrigger.ON_DEMAND,
                triggered_by_user_id=None,
                workflow_id="wf-xyz",
            )
        )

        assert result.was_created is True
        observation = ReplayObservation.objects.get(id=result.observation_id)
        assert observation.status == ObservationStatus.PENDING
        assert observation.workflow_id == "wf-xyz"
        assert observation.session_id == "sess-1"
        assert observation.triggered_by == ObservationTrigger.ON_DEMAND
        assert observation.lens_version == lens.lens_version
        assert observation.lens_config_snapshot == lens.lens_config
        assert observation.started_at is None  # set when transitioning to running, not here
        assert observation.completed_at is None

    def test_snapshot_is_frozen_against_later_lens_edits(self) -> None:
        lens = _make_lens()
        original_config = dict(lens.lens_config)
        result = create_observation_activity(
            CreateObservationInputs(
                lens_id=lens.id,
                team_id=lens.team_id,
                session_id="sess-1",
                triggered_by=ObservationTrigger.SCHEDULE,
                triggered_by_user_id=None,
                workflow_id="wf-1",
            )
        )

        lens.lens_config = {"prompt": "completely different prompt"}
        lens.save()

        observation = ReplayObservation.objects.get(id=result.observation_id)
        assert observation.lens_config_snapshot == original_config

    def test_returns_existing_observation_on_unique_conflict(self) -> None:
        lens = _make_lens()
        existing = _make_observation(lens, session_id="sess-dup")

        result = create_observation_activity(
            CreateObservationInputs(
                lens_id=lens.id,
                team_id=lens.team_id,
                session_id="sess-dup",
                triggered_by=ObservationTrigger.ON_DEMAND,
                triggered_by_user_id=None,
                workflow_id="wf-second",
            )
        )

        assert result == CreateObservationOutput(observation_id=existing.id, was_created=False)
        # The original row wasn't touched.
        existing.refresh_from_db()
        assert existing.workflow_id != "wf-second"

    def test_propagates_non_unique_integrity_errors(self) -> None:
        # FK/CHECK violations must surface as activity failures, not silently fall into the dedup path.
        lens = _make_lens()
        fk_error = IntegrityError("insert or update on table violates foreign key constraint")
        fk_error.__cause__ = psycopg.errors.ForeignKeyViolation("violation")

        with patch.object(ReplayObservation.objects, "create", side_effect=fk_error):
            with pytest.raises(IntegrityError):
                create_observation_activity(
                    CreateObservationInputs(
                        lens_id=lens.id,
                        team_id=lens.team_id,
                        session_id="sess-fk",
                        triggered_by=ObservationTrigger.ON_DEMAND,
                        triggered_by_user_id=None,
                        workflow_id="wf-fk",
                    )
                )

        assert not ReplayObservation.objects.filter(lens=lens, session_id="sess-fk").exists()

    @pytest.mark.parametrize(
        "case",
        ["lens_does_not_exist", "lens_belongs_to_other_team"],
    )
    def test_raises_when_lens_not_found_for_team(self, case: str) -> None:
        lens = _make_lens()
        if case == "lens_does_not_exist":
            lens_id, team_id = uuid.uuid4(), lens.team_id
        else:
            lens_id, team_id = lens.id, lens.team_id + 999

        with pytest.raises(ValueError):
            create_observation_activity(
                CreateObservationInputs(
                    lens_id=lens_id,
                    team_id=team_id,
                    session_id="sess-1",
                    triggered_by=ObservationTrigger.ON_DEMAND,
                    triggered_by_user_id=None,
                    workflow_id="wf-1",
                )
            )

    def test_raises_when_user_is_not_in_lens_organization(self) -> None:
        lens = _make_lens()
        outsider_org = Organization.objects.create(name="other-org")
        outsider = User.objects.create_and_join(organization=outsider_org, email="x@x.com", password=None)

        with pytest.raises(ValueError, match="not a member"):
            create_observation_activity(
                CreateObservationInputs(
                    lens_id=lens.id,
                    team_id=lens.team_id,
                    session_id="sess-1",
                    triggered_by=ObservationTrigger.ON_DEMAND,
                    triggered_by_user_id=outsider.id,
                    workflow_id="wf-1",
                )
            )

    def test_accepts_user_in_lens_organization(self) -> None:
        lens = _make_lens()
        member = User.objects.create_and_join(organization=lens.team.organization, email="m@m.com", password=None)

        result = create_observation_activity(
            CreateObservationInputs(
                lens_id=lens.id,
                team_id=lens.team_id,
                session_id="sess-1",
                triggered_by=ObservationTrigger.ON_DEMAND,
                triggered_by_user_id=member.id,
                workflow_id="wf-1",
            )
        )
        assert result.was_created is True


@pytest.mark.django_db(transaction=True)
class TestObservationStateActivities:
    def test_mark_running_stamps_started_at(self) -> None:
        lens = _make_lens()
        observation = _make_observation(lens, workflow_id="wf-1")
        assert observation.status == ObservationStatus.PENDING

        mark_observation_running_activity(MarkObservationRunningInputs(observation_id=observation.id))

        observation.refresh_from_db()
        assert observation.status == ObservationStatus.RUNNING
        assert observation.workflow_id == "wf-1"
        assert observation.started_at is not None

    def test_mark_failed_records_reason_and_completed_at(self) -> None:
        lens = _make_lens()
        observation = _make_observation(lens)
        observation.status = ObservationStatus.RUNNING
        observation.started_at = timezone.now()
        observation.save(update_fields=["status", "started_at"])

        mark_observation_failed_activity(
            MarkObservationFailedInputs(observation_id=observation.id, error_reason="bad output")
        )

        observation.refresh_from_db()
        assert observation.status == ObservationStatus.FAILED
        assert observation.error_reason == "bad output"
        assert observation.completed_at is not None

    @pytest.mark.parametrize("terminal_status", [ObservationStatus.SUCCEEDED, ObservationStatus.FAILED])
    def test_terminal_status_is_not_overwritten_by_state_activities(self, terminal_status: str) -> None:
        # Bounded UPDATE protects against retries that race past a settled row.
        lens = _make_lens()
        observation = _make_observation(lens)
        observation.status = terminal_status
        observation.completed_at = timezone.now()
        observation.error_reason = "original"
        observation.save(update_fields=["status", "completed_at", "error_reason"])

        mark_observation_running_activity(MarkObservationRunningInputs(observation_id=observation.id))
        mark_observation_failed_activity(
            MarkObservationFailedInputs(observation_id=observation.id, error_reason="late failure")
        )

        observation.refresh_from_db()
        assert observation.status == terminal_status
        assert observation.error_reason == "original"

    def test_mark_running_is_idempotent_against_already_running_rows(self) -> None:
        # `started_at` must survive at-least-once retries; duration metrics depend on it.
        lens = _make_lens()
        observation = _make_observation(lens)
        mark_observation_running_activity(MarkObservationRunningInputs(observation_id=observation.id))
        observation.refresh_from_db()
        first_started_at = observation.started_at
        assert first_started_at is not None

        mark_observation_running_activity(MarkObservationRunningInputs(observation_id=observation.id))
        observation.refresh_from_db()
        assert observation.started_at == first_started_at


@pytest.mark.django_db(transaction=True)
class TestFetchSessionEventsActivity:
    def _make_session_replay_events_mock(
        self,
        metadata: dict | None,
        columns: list[str] | None,
        rows: list[tuple] | None,
    ) -> MagicMock:
        mock_obj = MagicMock(spec=SessionReplayEvents)
        mock_obj.get_metadata.return_value = metadata
        mock_obj.get_events.return_value = (columns, rows)
        return mock_obj

    @pytest.mark.asyncio
    async def test_stashes_lens_llm_inputs_in_redis(self) -> None:
        lens = await sync_to_async(_make_lens)()
        observation_id = uuid.uuid4()
        start = dt.datetime(2026, 5, 12, 10, 0, 0, tzinfo=dt.UTC)
        end = dt.datetime(2026, 5, 12, 10, 5, 0, tzinfo=dt.UTC)
        metadata = {"start_time": start, "end_time": end, "duration": 300}

        mock_obj = self._make_session_replay_events_mock(
            metadata,
            ["event", "timestamp", "$session_id"],
            [("$pageview", start, "sess-1")],
        )

        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            await fetch_session_events_activity(
                FetchSessionEventsInputs(
                    observation_id=observation_id,
                    team_id=lens.team_id,
                    session_id="sess-1",
                )
            )

        redis_client = get_async_client()
        key = generate_state_key(label=StateActivitiesEnum.SESSION_EVENTS, state_id=str(observation_id))
        stored = await get_data_class_from_redis(redis_client, key, target_class=LensLlmInputs)
        assert stored is not None
        assert stored.session_id == "sess-1"
        assert stored.team_id == lens.team_id
        assert stored.columns == ["event", "timestamp", "$session_id"]
        assert stored.events == [["$pageview", start.isoformat(), "sess-1"]]
        assert stored.session_start_time == start.isoformat()
        assert stored.duration_seconds == 300.0

    @pytest.mark.asyncio
    async def test_is_idempotent_when_redis_already_has_payload(self) -> None:
        lens = await sync_to_async(_make_lens)()
        observation_id = uuid.uuid4()
        # Pre-populate Redis as if a previous run had finished.
        redis_client = get_async_client()
        key = generate_state_key(label=StateActivitiesEnum.SESSION_EVENTS, state_id=str(observation_id))
        existing = LensLlmInputs(
            session_id="sess-1",
            team_id=lens.team_id,
            session_start_time="2026-05-12T10:00:00+00:00",
            session_end_time="2026-05-12T10:05:00+00:00",
            duration_seconds=300.0,
            columns=["event"],
            events=[["$pageview"]],
        )
        await store_data_in_redis(redis_client, key, json.dumps(existing.model_dump()))

        mock_obj = MagicMock(spec=SessionReplayEvents)
        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            await fetch_session_events_activity(
                FetchSessionEventsInputs(
                    observation_id=observation_id,
                    team_id=lens.team_id,
                    session_id="sess-1",
                )
            )

        mock_obj.get_metadata.assert_not_called()
        mock_obj.get_events.assert_not_called()

    @pytest.mark.asyncio
    async def test_raises_non_retryable_when_session_has_no_events(self) -> None:
        lens = await sync_to_async(_make_lens)()
        observation_id = uuid.uuid4()
        metadata = {
            "start_time": dt.datetime(2026, 5, 12, tzinfo=dt.UTC),
            "end_time": dt.datetime(2026, 5, 12, 0, 5, tzinfo=dt.UTC),
            "duration": 300,
        }
        mock_obj = self._make_session_replay_events_mock(metadata, [], [])

        with patch(
            "products.replay_vision.backend.temporal.activities.fetch_session_events.SessionReplayEvents",
            return_value=mock_obj,
        ):
            with pytest.raises(ApplicationError) as exc_info:
                await fetch_session_events_activity(
                    FetchSessionEventsInputs(
                        observation_id=observation_id,
                        team_id=lens.team_id,
                        session_id="sess-empty",
                    )
                )
            assert exc_info.value.non_retryable is True


@pytest.mark.django_db(transaction=True)
class TestEnsureSessionAssetActivity:
    @pytest.mark.asyncio
    async def test_creates_new_asset_with_vision_render_params(self) -> None:
        lens = await sync_to_async(_make_lens)()
        result = await ensure_session_asset_activity(
            EnsureSessionAssetInputs(team_id=lens.team_id, session_id="sess-fresh")
        )
        assert isinstance(result, EnsureSessionAssetOutput)

        asset = await ExportedAsset.objects.aget(pk=result.asset_id)
        assert asset.team_id == lens.team_id
        assert asset.export_format == "video/mp4"
        assert asset.is_system is True
        ctx = asset.export_context or {}
        assert ctx["session_recording_id"] == "sess-fresh"
        assert ctx["playback_speed"] == 8
        assert ctx["recording_fps"] == 3
        assert ctx["show_metadata_footer"] is True

    @pytest.mark.asyncio
    async def test_reuses_existing_system_asset_for_same_session(self) -> None:
        lens = await sync_to_async(_make_lens)()
        first = await ensure_session_asset_activity(
            EnsureSessionAssetInputs(team_id=lens.team_id, session_id="sess-reuse")
        )
        second = await ensure_session_asset_activity(
            EnsureSessionAssetInputs(team_id=lens.team_id, session_id="sess-reuse")
        )
        assert first.asset_id == second.asset_id

        @sync_to_async
        def _count() -> int:
            return ExportedAsset.objects.filter(
                team_id=lens.team_id, export_context__session_recording_id="sess-reuse"
            ).count()

        assert await _count() == 1

    @pytest.mark.asyncio
    async def test_refreshes_export_context_on_reuse_without_clobbering_outputs(self) -> None:
        lens = await sync_to_async(_make_lens)()
        first = await ensure_session_asset_activity(
            EnsureSessionAssetInputs(team_id=lens.team_id, session_id="sess-stale")
        )

        # Simulate a previous rasterize run that wrote the s3 uri + fingerprint, AND a stale render-param drift.
        @sync_to_async
        def _mutate() -> None:
            asset = ExportedAsset.objects.get(pk=first.asset_id)
            ctx = dict(asset.export_context or {})
            ctx["playback_speed"] = 999  # drifted
            ctx["render_fingerprint"] = "abcdef"
            ctx["content_location"] = "s3://prior/video.mp4"
            asset.export_context = ctx
            asset.save(update_fields=["export_context"])

        await _mutate()

        await ensure_session_asset_activity(EnsureSessionAssetInputs(team_id=lens.team_id, session_id="sess-stale"))

        asset = await ExportedAsset.objects.aget(pk=first.asset_id)
        # Render params got snapped back; output fields stayed put so the rasterize cache can still hit.
        ctx = asset.export_context or {}
        assert ctx["playback_speed"] == 8
        assert ctx["render_fingerprint"] == "abcdef"
        assert ctx["content_location"] == "s3://prior/video.mp4"


def _stub_rasterize_workflow() -> type:
    @wf.defn(name="rasterize-recording")
    class StubRasterize:
        @wf.run
        async def run(self, _inputs: Any) -> None:
            return None

    return StubRasterize


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_apply_lens_workflow_drives_full_pipeline_with_stub_terminal() -> None:
    """End-to-end with real DB + Redis; fetch + rasterize child are stubbed."""
    lens = await sync_to_async(_make_lens)()
    workflow_id = f"replay-vision-apply-lens-{lens.id}-sess-1"

    @activity.defn(name="fetch_session_events_activity")
    async def stub_fetch(_inputs: FetchSessionEventsInputs) -> None:
        return None

    real_activities: list[Callable[..., Any]] = [
        create_observation_activity,
        mark_observation_running_activity,
        mark_observation_failed_activity,
        ensure_session_asset_activity,
        stub_fetch,
    ]

    with ThreadPoolExecutor(max_workers=4) as executor:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue="replay-vision-test-queue",
                workflows=[ApplyLensWorkflow, _stub_rasterize_workflow()],
                activities=real_activities,
                activity_executor=executor,
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await env.client.execute_workflow(
                    ApplyLensWorkflow.run,
                    ApplyLensInputs(
                        lens_id=lens.id,
                        session_id="sess-1",
                        team_id=lens.team_id,
                        triggered_by=ObservationTrigger.ON_DEMAND,
                        triggered_by_user_id=None,
                    ),
                    id=workflow_id,
                    task_queue="replay-vision-test-queue",
                )

    @sync_to_async
    def _reload_observation() -> ReplayObservation:
        return ReplayObservation.objects.get(lens=lens, session_id="sess-1")

    final = await _reload_observation()
    assert final.status == ObservationStatus.FAILED
    assert "stub" in final.error_reason.lower()
    assert final.workflow_id == workflow_id

    # The asset was created as a side effect of the workflow path.
    @sync_to_async
    def _asset_exists() -> bool:
        return ExportedAsset.objects.filter(
            team_id=lens.team_id,
            export_context__session_recording_id="sess-1",
            is_system=True,
        ).exists()

    assert await _asset_exists() is True


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_apply_lens_workflow_marks_failed_when_fetch_raises() -> None:
    """A fetch failure surfaces via mark_failed + workflow re-raise (not the stub reason)."""
    lens = await sync_to_async(_make_lens)()
    workflow_id = f"replay-vision-apply-lens-{lens.id}-sess-broken"

    @activity.defn(name="fetch_session_events_activity")
    async def stub_fetch(_inputs: FetchSessionEventsInputs) -> None:
        raise ApplicationError("no events", non_retryable=True)

    real_activities: list[Callable[..., Any]] = [
        create_observation_activity,
        mark_observation_running_activity,
        mark_observation_failed_activity,
        ensure_session_asset_activity,
        stub_fetch,
    ]

    with ThreadPoolExecutor(max_workers=4) as executor:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue="replay-vision-test-queue",
                workflows=[ApplyLensWorkflow, _stub_rasterize_workflow()],
                activities=real_activities,
                activity_executor=executor,
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                with pytest.raises(WorkflowFailureError):
                    await env.client.execute_workflow(
                        ApplyLensWorkflow.run,
                        ApplyLensInputs(
                            lens_id=lens.id,
                            session_id="sess-broken",
                            team_id=lens.team_id,
                            triggered_by=ObservationTrigger.ON_DEMAND,
                            triggered_by_user_id=None,
                        ),
                        id=workflow_id,
                        task_queue="replay-vision-test-queue",
                    )

    @sync_to_async
    def _reload_observation() -> ReplayObservation:
        return ReplayObservation.objects.get(lens=lens, session_id="sess-broken")

    final = await _reload_observation()
    assert final.status == ObservationStatus.FAILED
    assert "no events" in final.error_reason.lower()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_apply_lens_workflow_no_ops_when_observation_already_exists() -> None:
    """If a row already owns (lens, session_id), the workflow exits without touching it."""
    lens = await sync_to_async(_make_lens)()
    existing = await sync_to_async(_make_observation)(
        lens,
        session_id="sess-dup",
        workflow_id="prior-workflow",
        status=ObservationStatus.SUCCEEDED,
        completed_at=timezone.now(),
    )

    workflow_id = f"replay-vision-apply-lens-{lens.id}-sess-dup"
    with ThreadPoolExecutor(max_workers=4) as executor:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue="replay-vision-test-queue",
                workflows=[ApplyLensWorkflow, _stub_rasterize_workflow()],
                activities=ACTIVITIES,
                activity_executor=executor,
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await env.client.execute_workflow(
                    ApplyLensWorkflow.run,
                    ApplyLensInputs(
                        lens_id=lens.id,
                        session_id="sess-dup",
                        team_id=lens.team_id,
                        triggered_by=ObservationTrigger.ON_DEMAND,
                        triggered_by_user_id=None,
                    ),
                    id=workflow_id,
                    task_queue="replay-vision-test-queue",
                )

    # Existing row stays exactly as it was — no new rows created.
    @sync_to_async
    def _check() -> tuple[int, ReplayObservation]:
        rows = ReplayObservation.objects.filter(lens=lens, session_id="sess-dup")
        return rows.count(), rows.get()

    count, observation = await _check()
    assert count == 1
    assert observation.id == existing.id
    assert observation.workflow_id == "prior-workflow"
    assert observation.status == ObservationStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_apply_lens_workflow_orchestrates_activities_in_order() -> None:
    """Mock every activity + rasterize child — verify the orchestration order."""
    calls: list[str] = []
    new_observation_id = uuid.uuid4()

    @activity.defn(name="create_observation_activity")
    async def stub_create(_inputs: CreateObservationInputs) -> CreateObservationOutput:
        calls.append("create")
        return CreateObservationOutput(observation_id=new_observation_id, was_created=True)

    @activity.defn(name="mark_observation_running_activity")
    async def stub_running(_inputs: MarkObservationRunningInputs) -> None:
        calls.append("running")

    @activity.defn(name="fetch_session_events_activity")
    async def stub_fetch(_inputs: FetchSessionEventsInputs) -> None:
        calls.append("fetch")

    @activity.defn(name="ensure_session_asset_activity")
    async def stub_ensure(_inputs: EnsureSessionAssetInputs) -> EnsureSessionAssetOutput:
        calls.append("ensure_asset")
        return EnsureSessionAssetOutput(asset_id=42)

    @wf.defn(name="rasterize-recording")
    class StubRasterize:
        @wf.run
        async def run(self, _inputs: Any) -> None:
            calls.append("rasterize")
            return None

    @activity.defn(name="mark_observation_failed_activity")
    async def stub_failed(_inputs: MarkObservationFailedInputs) -> None:
        calls.append("failed")

    lens_id = uuid.uuid4()
    workflow_id = f"replay-vision-apply-lens-{lens_id}-sess-x"
    activities: list[Callable[..., Any]] = [stub_create, stub_running, stub_fetch, stub_ensure, stub_failed]

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="replay-vision-test-queue",
            workflows=[ApplyLensWorkflow, StubRasterize],
            activities=activities,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                ApplyLensWorkflow.run,
                ApplyLensInputs(
                    lens_id=lens_id,
                    session_id="sess-x",
                    team_id=1,
                    triggered_by=ObservationTrigger.SCHEDULE,
                    triggered_by_user_id=None,
                ),
                id=workflow_id,
                task_queue="replay-vision-test-queue",
            )

    assert calls == ["create", "running", "fetch", "ensure_asset", "rasterize", "failed"]


@pytest.mark.asyncio
async def test_apply_lens_workflow_exits_when_create_returns_was_created_false() -> None:
    """If create activity returns was_created=False, the workflow exits without further activities."""
    calls: list[str] = []

    @activity.defn(name="create_observation_activity")
    async def stub_create(inputs: CreateObservationInputs) -> CreateObservationOutput:
        calls.append("create")
        return CreateObservationOutput(observation_id=uuid.uuid4(), was_created=False)

    @activity.defn(name="mark_observation_running_activity")
    async def stub_running(inputs: MarkObservationRunningInputs) -> None:
        calls.append("running")

    @activity.defn(name="mark_observation_failed_activity")
    async def stub_failed(inputs: MarkObservationFailedInputs) -> None:
        calls.append("failed")

    activities: list[Callable[..., Any]] = [stub_create, stub_running, stub_failed]

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="replay-vision-test-queue",
            workflows=[ApplyLensWorkflow],
            activities=activities,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                ApplyLensWorkflow.run,
                ApplyLensInputs(
                    lens_id=uuid.uuid4(),
                    session_id="sess-y",
                    team_id=1,
                    triggered_by=ObservationTrigger.ON_DEMAND,
                    triggered_by_user_id=None,
                ),
                id="wf-y",
                task_queue="replay-vision-test-queue",
            )

    assert calls == ["create"]

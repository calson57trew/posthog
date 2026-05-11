import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from django.utils import timezone

from asgiref.sync import sync_to_async
from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models import Organization, Team

from products.replay_vision.backend.models.replay_lens import LensModel, LensType, ReplayLens
from products.replay_vision.backend.models.replay_observation import (
    ObservationStatus,
    ObservationTrigger,
    ReplayObservation,
)
from products.replay_vision.backend.temporal import ACTIVITIES, ApplyLensWorkflow
from products.replay_vision.backend.temporal.activities.create_observation import create_observation_activity
from products.replay_vision.backend.temporal.activities.observation_state import (
    mark_observation_failed_activity,
    mark_observation_running_activity,
)
from products.replay_vision.backend.temporal.types import (
    ApplyLensInputs,
    CreateObservationInputs,
    CreateObservationOutput,
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
                lens_id=str(lens.id),
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
                lens_id=str(lens.id),
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
                lens_id=str(lens.id),
                team_id=lens.team_id,
                session_id="sess-dup",
                triggered_by=ObservationTrigger.ON_DEMAND,
                triggered_by_user_id=None,
                workflow_id="wf-second",
            )
        )

        assert result == CreateObservationOutput(observation_id=str(existing.id), was_created=False)
        # The original row wasn't touched.
        existing.refresh_from_db()
        assert existing.workflow_id != "wf-second"

    def test_raises_when_lens_missing_or_wrong_team(self) -> None:
        lens = _make_lens()
        with pytest.raises(ValueError):
            create_observation_activity(
                CreateObservationInputs(
                    lens_id=str(uuid.uuid4()),
                    team_id=lens.team_id,
                    session_id="sess-1",
                    triggered_by=ObservationTrigger.ON_DEMAND,
                    triggered_by_user_id=None,
                    workflow_id="wf-1",
                )
            )

        with pytest.raises(ValueError):
            create_observation_activity(
                CreateObservationInputs(
                    lens_id=str(lens.id),
                    team_id=lens.team_id + 999,
                    session_id="sess-1",
                    triggered_by=ObservationTrigger.ON_DEMAND,
                    triggered_by_user_id=None,
                    workflow_id="wf-1",
                )
            )


@pytest.mark.django_db(transaction=True)
class TestObservationStateActivities:
    def test_mark_running_stamps_started_at(self) -> None:
        lens = _make_lens()
        observation = _make_observation(lens, workflow_id="wf-1")
        assert observation.status == ObservationStatus.PENDING

        mark_observation_running_activity(MarkObservationRunningInputs(observation_id=str(observation.id)))

        observation.refresh_from_db()
        assert observation.status == ObservationStatus.RUNNING
        # workflow_id is set at create time and untouched here.
        assert observation.workflow_id == "wf-1"
        assert observation.started_at is not None

    def test_mark_failed_records_reason_and_completed_at(self) -> None:
        lens = _make_lens()
        observation = _make_observation(lens)
        observation.status = ObservationStatus.RUNNING
        observation.started_at = timezone.now()
        observation.save(update_fields=["status", "started_at"])

        mark_observation_failed_activity(
            MarkObservationFailedInputs(observation_id=str(observation.id), error_reason="bad output")
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

        mark_observation_running_activity(MarkObservationRunningInputs(observation_id=str(observation.id)))
        mark_observation_failed_activity(
            MarkObservationFailedInputs(observation_id=str(observation.id), error_reason="late failure")
        )

        observation.refresh_from_db()
        assert observation.status == terminal_status
        assert observation.error_reason == "original"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_apply_lens_workflow_creates_row_then_marks_failed_with_stub_reason() -> None:
    """End-to-end: workflow creates the observation, then drives it pending → running → failed."""
    lens = await sync_to_async(_make_lens)()
    workflow_id = f"replay-vision-apply-lens-{lens.id}-sess-1"

    with ThreadPoolExecutor(max_workers=4) as executor:
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue="replay-vision-test-queue",
                workflows=[ApplyLensWorkflow],
                activities=ACTIVITIES,
                activity_executor=executor,
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await env.client.execute_workflow(
                    ApplyLensWorkflow.run,
                    ApplyLensInputs(
                        lens_id=str(lens.id),
                        session_id="sess-1",
                        team_id=lens.team_id,
                        triggered_by=ObservationTrigger.ON_DEMAND,
                        triggered_by_user_id=None,
                    ),
                    id=workflow_id,
                    task_queue="replay-vision-test-queue",
                )

    @sync_to_async
    def _reload() -> ReplayObservation:
        return ReplayObservation.objects.get(lens=lens, session_id="sess-1")

    final = await _reload()
    assert final.status == ObservationStatus.FAILED
    assert "stub" in final.error_reason.lower()
    assert final.workflow_id == workflow_id
    assert final.started_at is not None
    assert final.completed_at is not None


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
                workflows=[ApplyLensWorkflow],
                activities=ACTIVITIES,
                activity_executor=executor,
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await env.client.execute_workflow(
                    ApplyLensWorkflow.run,
                    ApplyLensInputs(
                        lens_id=str(lens.id),
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
    """Mock all three activities — verify the workflow calls them in the right order with the right inputs."""
    calls: list[tuple[str, dict]] = []
    new_observation_id = str(uuid.uuid4())

    @activity.defn(name="create_observation_activity")
    async def stub_create(inputs: CreateObservationInputs) -> CreateObservationOutput:
        calls.append(
            (
                "create",
                {
                    "lens_id": inputs.lens_id,
                    "session_id": inputs.session_id,
                    "triggered_by": inputs.triggered_by,
                    "workflow_id": inputs.workflow_id,
                },
            )
        )
        return CreateObservationOutput(observation_id=new_observation_id, was_created=True)

    @activity.defn(name="mark_observation_running_activity")
    async def stub_running(inputs: MarkObservationRunningInputs) -> None:
        calls.append(("running", {"observation_id": inputs.observation_id}))

    @activity.defn(name="mark_observation_failed_activity")
    async def stub_failed(inputs: MarkObservationFailedInputs) -> None:
        calls.append(("failed", {"observation_id": inputs.observation_id, "error_reason": inputs.error_reason}))

    lens_id = str(uuid.uuid4())
    workflow_id = f"replay-vision-apply-lens-{lens_id}-sess-x"

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="replay-vision-test-queue",
            workflows=[ApplyLensWorkflow],
            activities=[stub_create, stub_running, stub_failed],
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

    assert [name for name, _ in calls] == ["create", "running", "failed"]
    assert calls[0][1] == {
        "lens_id": lens_id,
        "session_id": "sess-x",
        "triggered_by": ObservationTrigger.SCHEDULE,
        "workflow_id": workflow_id,
    }
    assert calls[1][1] == {"observation_id": new_observation_id}
    assert calls[2][1]["observation_id"] == new_observation_id
    assert "stub" in calls[2][1]["error_reason"].lower()


@pytest.mark.asyncio
async def test_apply_lens_workflow_exits_when_create_returns_was_created_false() -> None:
    """If create activity returns was_created=False, the workflow exits without further activities."""
    calls: list[str] = []

    @activity.defn(name="create_observation_activity")
    async def stub_create(inputs: CreateObservationInputs) -> CreateObservationOutput:
        calls.append("create")
        return CreateObservationOutput(observation_id=str(uuid.uuid4()), was_created=False)

    @activity.defn(name="mark_observation_running_activity")
    async def stub_running(inputs: MarkObservationRunningInputs) -> None:
        calls.append("running")

    @activity.defn(name="mark_observation_failed_activity")
    async def stub_failed(inputs: MarkObservationFailedInputs) -> None:
        calls.append("failed")

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="replay-vision-test-queue",
            workflows=[ApplyLensWorkflow],
            activities=[stub_create, stub_running, stub_failed],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                ApplyLensWorkflow.run,
                ApplyLensInputs(
                    lens_id=str(uuid.uuid4()),
                    session_id="sess-y",
                    team_id=1,
                    triggered_by=ObservationTrigger.ON_DEMAND,
                    triggered_by_user_id=None,
                ),
                id="wf-y",
                task_queue="replay-vision-test-queue",
            )

    assert calls == ["create"]

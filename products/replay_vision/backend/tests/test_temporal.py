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
from products.replay_vision.backend.temporal.activities.observation_state import (
    mark_observation_failed_activity,
    mark_observation_running_activity,
)
from products.replay_vision.backend.temporal.types import (
    ApplyLensInputs,
    MarkObservationFailedInputs,
    MarkObservationRunningInputs,
)


def _make_lens_and_observation() -> tuple[ReplayLens, ReplayObservation]:
    org = Organization.objects.create(name="vision-test-org")
    team = Team.objects.create(organization=org, name="vision-test-team")
    lens = ReplayLens.objects.create(
        team=team,
        name="t",
        lens_type=LensType.MONITOR,
        lens_config={"prompt": "p"},
        model=LensModel.GEMINI_3_FLASH,
    )
    observation = ReplayObservation.objects.create(
        lens=lens,
        team=team,
        session_id="sess-1",
        triggered_by=ObservationTrigger.ON_DEMAND,
        lens_version=lens.lens_version,
        lens_config_snapshot=lens.lens_config,
    )
    return lens, observation


@pytest.mark.django_db(transaction=True)
class TestObservationStateActivities:
    def test_mark_running_stamps_workflow_id_and_started_at(self) -> None:
        _lens, observation = _make_lens_and_observation()
        assert observation.status == ObservationStatus.PENDING

        mark_observation_running_activity(
            MarkObservationRunningInputs(observation_id=str(observation.id), workflow_id="wf-1")
        )

        observation.refresh_from_db()
        assert observation.status == ObservationStatus.RUNNING
        assert observation.workflow_id == "wf-1"
        assert observation.started_at is not None

    def test_mark_failed_records_reason_and_completed_at(self) -> None:
        _lens, observation = _make_lens_and_observation()
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
        _lens, observation = _make_lens_and_observation()
        observation.status = terminal_status
        observation.completed_at = timezone.now()
        observation.error_reason = "original"
        observation.save(update_fields=["status", "completed_at", "error_reason"])

        mark_observation_running_activity(
            MarkObservationRunningInputs(observation_id=str(observation.id), workflow_id="wf-late")
        )
        mark_observation_failed_activity(
            MarkObservationFailedInputs(observation_id=str(observation.id), error_reason="late failure")
        )

        observation.refresh_from_db()
        assert observation.status == terminal_status
        assert observation.workflow_id == ""
        assert observation.error_reason == "original"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_apply_lens_workflow_marks_running_then_failed_with_stub_reason() -> None:
    """End-to-end: workflow drives the observation through pending → running → failed."""
    lens, observation = await sync_to_async(_make_lens_and_observation)()

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
                        observation_id=str(observation.id),
                        lens_id=str(lens.id),
                        session_id="sess-1",
                        team_id=lens.team_id,
                    ),
                    id=f"replay-vision-apply-lens-{observation.id}",
                    task_queue="replay-vision-test-queue",
                )

    @sync_to_async
    def _reload() -> ReplayObservation:
        return ReplayObservation.objects.get(id=observation.id)

    final = await _reload()
    assert final.status == ObservationStatus.FAILED
    assert "stub" in final.error_reason.lower()
    assert final.workflow_id == f"replay-vision-apply-lens-{observation.id}"
    assert final.started_at is not None
    assert final.completed_at is not None


@pytest.mark.asyncio
async def test_apply_lens_workflow_orchestrates_state_activities_in_order() -> None:
    """Mock the state activities — verify the workflow calls them in the right order with the right inputs."""
    calls: list[tuple[str, dict]] = []

    @activity.defn(name="mark_observation_running_activity")
    async def stub_running(inputs: MarkObservationRunningInputs) -> None:
        calls.append(("running", {"observation_id": inputs.observation_id, "workflow_id": inputs.workflow_id}))

    @activity.defn(name="mark_observation_failed_activity")
    async def stub_failed(inputs: MarkObservationFailedInputs) -> None:
        calls.append(("failed", {"observation_id": inputs.observation_id, "error_reason": inputs.error_reason}))

    observation_id = str(uuid.uuid4())
    workflow_id = f"replay-vision-apply-lens-{observation_id}"

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="replay-vision-test-queue",
            workflows=[ApplyLensWorkflow],
            activities=[stub_running, stub_failed],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                ApplyLensWorkflow.run,
                ApplyLensInputs(
                    observation_id=observation_id,
                    lens_id=str(uuid.uuid4()),
                    session_id="sess-x",
                    team_id=1,
                ),
                id=workflow_id,
                task_queue="replay-vision-test-queue",
            )

    assert [name for name, _ in calls] == ["running", "failed"]
    assert calls[0][1] == {"observation_id": observation_id, "workflow_id": workflow_id}
    assert calls[1][1]["observation_id"] == observation_id
    assert "stub" in calls[1][1]["error_reason"].lower()

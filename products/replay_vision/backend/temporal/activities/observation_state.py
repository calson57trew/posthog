import uuid

from django.utils import timezone

from temporalio import activity

from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.temporal.types import MarkObservationFailedInputs, MarkObservationRunningInputs


@activity.defn
def mark_observation_running_activity(inputs: MarkObservationRunningInputs) -> None:
    """Flip pending → running and stamp started_at.

    workflow_id is set at row creation, so this activity only handles the state
    transition. Bounded UPDATE on `status__in=(pending, running)` so a Temporal retry
    that reruns the activity after we already moved on stays a no-op.
    """
    observation_pk = uuid.UUID(inputs.observation_id)
    ReplayObservation.objects.filter(
        pk=observation_pk,
        status__in=[ObservationStatus.PENDING, ObservationStatus.RUNNING],
    ).update(
        status=ObservationStatus.RUNNING,
        started_at=timezone.now(),
    )


@activity.defn
def mark_observation_failed_activity(inputs: MarkObservationFailedInputs) -> None:
    """Flip pending/running → failed with an error_reason.

    Same bounded UPDATE: a retried call after the row has already settled to
    succeeded won't trample it back to failed.
    """
    observation_pk = uuid.UUID(inputs.observation_id)
    ReplayObservation.objects.filter(
        pk=observation_pk,
        status__in=[ObservationStatus.PENDING, ObservationStatus.RUNNING],
    ).update(
        status=ObservationStatus.FAILED,
        error_reason=inputs.error_reason,
        completed_at=timezone.now(),
    )

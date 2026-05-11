import copy
import uuid

from django.db import IntegrityError, transaction

from temporalio import activity

from products.replay_vision.backend.models.replay_lens import ReplayLens
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.temporal.types import CreateObservationInputs, CreateObservationOutput


@activity.defn
def create_observation_activity(inputs: CreateObservationInputs) -> CreateObservationOutput:
    """Snapshot the lens config + version and INSERT the observation row in `pending`.

    On `UNIQUE(lens_id, session_id)` conflict: return `was_created=False` so the
    workflow can exit cleanly without racing the row that already owns the slot.
    """
    lens_pk = uuid.UUID(inputs.lens_id)
    lens = ReplayLens.objects.filter(pk=lens_pk, team_id=inputs.team_id).first()
    if lens is None:
        raise ValueError(f"ReplayLens {inputs.lens_id} not found for team {inputs.team_id}")

    try:
        with transaction.atomic():
            observation = ReplayObservation.objects.create(
                lens=lens,
                team=lens.team,
                session_id=inputs.session_id,
                status=ObservationStatus.PENDING,
                workflow_id=inputs.workflow_id,
                lens_version=lens.lens_version,
                lens_config_snapshot=copy.deepcopy(lens.lens_config),
                triggered_by=inputs.triggered_by,
                triggered_by_user_id=inputs.triggered_by_user_id,
            )
    except IntegrityError:
        existing = ReplayObservation.objects.get(lens_id=lens_pk, session_id=inputs.session_id)
        return CreateObservationOutput(observation_id=str(existing.id), was_created=False)

    return CreateObservationOutput(observation_id=str(observation.id), was_created=True)

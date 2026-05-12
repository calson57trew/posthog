import copy

from django.db import IntegrityError, transaction

import psycopg.errors
from temporalio import activity

from posthog.models.organization import OrganizationMembership

from products.replay_vision.backend.models.replay_lens import ReplayLens
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.temporal.types import CreateObservationInputs, CreateObservationOutput


@activity.defn
def create_observation_activity(inputs: CreateObservationInputs) -> CreateObservationOutput:
    """Snapshot the lens config + version and INSERT the observation row in `pending`.

    On `UNIQUE(lens_id, session_id)` conflict: return `was_created=False` so the
    workflow can exit cleanly without racing the row that already owns the slot.
    """
    lens = ReplayLens.objects.filter(pk=inputs.lens_id, team_id=inputs.team_id).first()
    if lens is None:
        raise ValueError(f"ReplayLens {inputs.lens_id} not found for team {inputs.team_id}")

    if inputs.triggered_by_user_id is not None:
        # Triggers are trusted today (DRF auth on /observe/, internal schedule), but the activity
        # is the persistence boundary — verify the user is in the lens's organization so a future
        # trigger can't stamp an unrelated user onto the row.
        is_member = OrganizationMembership.objects.filter(
            user_id=inputs.triggered_by_user_id,
            organization_id=lens.team.organization_id,
        ).exists()
        if not is_member:
            raise ValueError(
                f"User {inputs.triggered_by_user_id} is not a member of lens {inputs.lens_id}'s organization"
            )

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
    except IntegrityError as e:
        # Narrow to the dedup case so FK violations (lens/team/user deleted mid-flight) surface as
        # activity failures instead of silently falling into the "existing row" path.
        if not isinstance(e.__cause__, psycopg.errors.UniqueViolation):
            raise
        existing = ReplayObservation.objects.get(lens_id=inputs.lens_id, session_id=inputs.session_id)
        return CreateObservationOutput(observation_id=existing.id, was_created=False)

    return CreateObservationOutput(observation_id=observation.id, was_created=True)

from pydantic import BaseModel

from products.replay_vision.backend.models.replay_observation import ObservationTrigger


class ApplyLensInputs(BaseModel, frozen=True):
    """Input to ApplyLensWorkflow."""

    lens_id: str
    session_id: str
    team_id: int
    triggered_by: ObservationTrigger
    triggered_by_user_id: int | None = None


class CreateObservationInputs(BaseModel, frozen=True):
    lens_id: str
    team_id: int
    session_id: str
    triggered_by: ObservationTrigger
    triggered_by_user_id: int | None
    workflow_id: str


class CreateObservationOutput(BaseModel, frozen=True):
    """`was_created=False` means the row already existed; the caller should no-op."""

    observation_id: str
    was_created: bool


class MarkObservationRunningInputs(BaseModel, frozen=True):
    observation_id: str


class MarkObservationFailedInputs(BaseModel, frozen=True):
    observation_id: str
    error_reason: str

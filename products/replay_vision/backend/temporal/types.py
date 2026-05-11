from pydantic import BaseModel


class ApplyLensInputs(BaseModel, frozen=True):
    """Input to ApplyLensWorkflow.

    Carries no observation state — the workflow creates the row itself in its first
    activity. The trigger only supplies the lens, the session it picked, the team
    boundary, and how the workflow was kicked off.
    """

    lens_id: str
    session_id: str
    team_id: int
    triggered_by: str  # ObservationTrigger value: "schedule" | "on_demand"
    triggered_by_user_id: int | None = None


class CreateObservationInputs(BaseModel, frozen=True):
    lens_id: str
    team_id: int
    session_id: str
    triggered_by: str
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

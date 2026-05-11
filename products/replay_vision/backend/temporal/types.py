from pydantic import BaseModel


class ApplyLensInputs(BaseModel, frozen=True):
    """Input to ApplyLensWorkflow.

    Identifies the row that holds workflow state plus the (lens, session) pair the
    workflow operates on. Lens config is read out of the observation snapshot — not
    re-fetched — so concurrent lens edits don't retro-mutate an in-flight run.
    """

    observation_id: str
    lens_id: str
    session_id: str
    team_id: int


class MarkObservationRunningInputs(BaseModel, frozen=True):
    observation_id: str
    workflow_id: str


class MarkObservationFailedInputs(BaseModel, frozen=True):
    observation_id: str
    error_reason: str

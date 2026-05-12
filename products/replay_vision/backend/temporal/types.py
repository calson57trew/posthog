from typing import Any
from uuid import UUID

from pydantic import BaseModel

from products.replay_vision.backend.models.replay_observation import ObservationTrigger


class ApplyLensInputs(BaseModel, frozen=True):
    """Input to ApplyLensWorkflow."""

    lens_id: UUID
    session_id: str
    team_id: int
    triggered_by: ObservationTrigger
    triggered_by_user_id: int | None = None


class CreateObservationInputs(BaseModel, frozen=True):
    lens_id: UUID
    team_id: int
    session_id: str
    triggered_by: ObservationTrigger
    triggered_by_user_id: int | None
    workflow_id: str


class CreateObservationOutput(BaseModel, frozen=True):
    """`was_created=False` means the row already existed; the caller should no-op."""

    observation_id: UUID
    was_created: bool


class MarkObservationRunningInputs(BaseModel, frozen=True):
    observation_id: UUID


class MarkObservationFailedInputs(BaseModel, frozen=True):
    observation_id: UUID
    error_reason: str


class FetchSessionEventsInputs(BaseModel, frozen=True):
    observation_id: UUID
    team_id: int
    session_id: str


class LensLlmInputs(BaseModel, frozen=True):
    """Per-session analytics events + recording metadata, stashed in Redis between activities."""

    session_id: str
    team_id: int
    session_start_time: str  # ISO 8601
    session_end_time: str  # ISO 8601
    duration_seconds: float
    columns: list[str]
    events: list[list[Any]]


class EnsureSessionAssetInputs(BaseModel, frozen=True):
    team_id: int
    session_id: str


class EnsureSessionAssetOutput(BaseModel, frozen=True):
    asset_id: int

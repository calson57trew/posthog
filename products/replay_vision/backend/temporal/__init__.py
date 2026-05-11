from products.replay_vision.backend.temporal.activities import (
    mark_observation_failed_activity,
    mark_observation_running_activity,
)
from products.replay_vision.backend.temporal.workflow import ApplyLensWorkflow

WORKFLOWS = [ApplyLensWorkflow]
ACTIVITIES = [
    mark_observation_running_activity,
    mark_observation_failed_activity,
]

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "ApplyLensWorkflow",
    "mark_observation_failed_activity",
    "mark_observation_running_activity",
]

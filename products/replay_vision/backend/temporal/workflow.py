import datetime as dt

import temporalio.workflow as wf
from temporalio import common

from posthog.temporal.common.base import PostHogWorkflow

from products.replay_vision.backend.temporal.activities import (
    create_observation_activity,
    mark_observation_failed_activity,
    mark_observation_running_activity,
)
from products.replay_vision.backend.temporal.constants import APPLY_LENS_WORKFLOW_NAME
from products.replay_vision.backend.temporal.types import (
    ApplyLensInputs,
    CreateObservationInputs,
    CreateObservationOutput,
    MarkObservationFailedInputs,
    MarkObservationRunningInputs,
)

_STATE_ACTIVITY_RETRY = common.RetryPolicy(
    initial_interval=dt.timedelta(seconds=1),
    maximum_interval=dt.timedelta(seconds=10),
    maximum_attempts=5,
)

_STUB_NOT_IMPLEMENTED_REASON = (
    "ApplyLensWorkflow is a stub: the rasterize → upload → call-provider → emit-event pipeline "
    "is not implemented yet. The observation row is exercised end-to-end so wiring can be verified."
)


@wf.defn(name=APPLY_LENS_WORKFLOW_NAME)
class ApplyLensWorkflow(PostHogWorkflow):
    """Apply one lens to one session.

    Owns the observation row's entire lifecycle: snapshots the lens config,
    INSERTs the row, and drives it through the state machine.

    STUB: marks the observation running, then immediately failed. The real workflow
    will rasterize the session, upload the video to the provider, call the LLM, and
    emit `$replay_lens` + flip succeeded in one terminal activity (see master plan).
    """

    inputs_cls = ApplyLensInputs

    @wf.run
    async def run(self, inputs: ApplyLensInputs) -> None:
        workflow_id = wf.info().workflow_id

        create_result: CreateObservationOutput = await wf.execute_activity(
            create_observation_activity,
            CreateObservationInputs(
                lens_id=inputs.lens_id,
                team_id=inputs.team_id,
                session_id=inputs.session_id,
                triggered_by=inputs.triggered_by,
                triggered_by_user_id=inputs.triggered_by_user_id,
                workflow_id=workflow_id,
            ),
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=_STATE_ACTIVITY_RETRY,
        )
        if not create_result.was_created:
            # An existing observation already owns this (lens, session_id) — exit so we don't
            # double-process. The original workflow drives that row to completion.
            return

        observation_id = create_result.observation_id
        await wf.execute_activity(
            mark_observation_running_activity,
            MarkObservationRunningInputs(observation_id=observation_id),
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=_STATE_ACTIVITY_RETRY,
        )
        await wf.execute_activity(
            mark_observation_failed_activity,
            MarkObservationFailedInputs(
                observation_id=observation_id,
                error_reason=_STUB_NOT_IMPLEMENTED_REASON,
            ),
            start_to_close_timeout=dt.timedelta(seconds=30),
            retry_policy=_STATE_ACTIVITY_RETRY,
        )

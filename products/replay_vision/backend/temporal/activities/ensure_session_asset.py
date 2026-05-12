import datetime as dt

from django.db import transaction
from django.utils.timezone import now

from asgiref.sync import sync_to_async
from temporalio import activity

from posthog.models.exported_asset import ExportedAsset

from products.replay_vision.backend.temporal.types import EnsureSessionAssetInputs, EnsureSessionAssetOutput

# Render params match the session-summary path so the rasterize fingerprint cache hits across products.
_EXPORT_FORMAT = "video/mp4"
_PLAYBACK_SPEED = 8
_RECORDING_FPS = 3
_SHOW_METADATA_FOOTER = True
_ASSET_EXPIRES_AFTER_DAYS = 90


def _render_context(session_id: str) -> dict:
    return {
        "session_recording_id": session_id,
        "playback_speed": _PLAYBACK_SPEED,
        "recording_fps": _RECORDING_FPS,
        "show_metadata_footer": _SHOW_METADATA_FOOTER,
    }


def _refresh_existing_asset(asset_id: int, session_id: str) -> None:
    """SELECT FOR UPDATE serializes this with finalize_rasterization's own JSONB write."""
    desired = _render_context(session_id)
    with transaction.atomic():
        asset = ExportedAsset.objects.select_for_update().get(pk=asset_id)
        ctx = dict(asset.export_context or {})
        # Only overwrite the params we own; preserve any output fields (s3 uri, fingerprint).
        for key, value in desired.items():
            ctx[key] = value
        if ctx != asset.export_context:
            asset.export_context = ctx
            asset.save(update_fields=["export_context"])


@activity.defn
async def ensure_session_asset_activity(inputs: EnsureSessionAssetInputs) -> EnsureSessionAssetOutput:
    """Get-or-create the ExportedAsset that `RasterizeRecordingWorkflow` needs as input.

    Reuses any existing system-owned asset for `(team, session)` so its stored
    `render_fingerprint` + `content_location` can serve a cache hit on subsequent runs.
    """
    existing = await ExportedAsset.objects.filter(
        team_id=inputs.team_id,
        export_format=_EXPORT_FORMAT,
        export_context__session_recording_id=inputs.session_id,
        is_system=True,
    ).afirst()

    if existing is not None:
        await sync_to_async(_refresh_existing_asset)(existing.id, inputs.session_id)
        return EnsureSessionAssetOutput(asset_id=existing.id)

    created_at = now()
    asset = await ExportedAsset.objects.acreate(
        team_id=inputs.team_id,
        export_format=_EXPORT_FORMAT,
        export_context=_render_context(inputs.session_id),
        created_at=created_at,
        expires_after=created_at + dt.timedelta(days=_ASSET_EXPIRES_AFTER_DAYS),
        is_system=True,
    )
    return EnsureSessionAssetOutput(asset_id=asset.id)

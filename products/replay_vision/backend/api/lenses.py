import copy
from typing import Any, NoReturn, cast

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import QuerySet

import structlog
import django_filters
from asgiref.sync import async_to_sync
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.models.user import User
from posthog.temporal.common.client import sync_connect

from products.replay_vision.backend.api.constants import VISION_TAG
from products.replay_vision.backend.api.observations import ReplayObservationSerializer
from products.replay_vision.backend.feature_flag import ReplayVisionEnabledPermission
from products.replay_vision.backend.models.replay_lens import LensModel, LensProvider, LensType, ReplayLens
from products.replay_vision.backend.models.replay_observation import ObservationTrigger, ReplayObservation
from products.replay_vision.backend.temporal.constants import APPLY_LENS_WORKFLOW_NAME
from products.replay_vision.backend.temporal.types import ApplyLensInputs

logger = structlog.get_logger(__name__)


class ReplayLensSerializer(serializers.ModelSerializer):
    name = serializers.CharField(
        max_length=255,
        help_text="Human-readable lens name. Unique within the team.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Free-form description shown in the lens management UI.",
    )
    lens_type = serializers.ChoiceField(
        choices=LensType.choices,
        help_text="What the lens does: monitor, classifier, scorer, summarizer, or indexer.",
    )
    # TODO: validate `lens_config` shape per `lens_type` via Pydantic discriminated union (deferred to follow-up PR)
    lens_config = serializers.JSONField(
        help_text="Type-specific configuration. Always includes `prompt`; classifiers add `tags`, scorers add `scale`, etc.",
    )
    # TODO: type `query` against `posthog.schema.RecordingsQuery` (deferred to follow-up PR)
    query = serializers.JSONField(
        required=False,
        help_text="Persisted `RecordingsQuery` shape used to pick candidate sessions. `date_from`/`date_to` are stripped on save — the schedule controls time, not the user.",
    )
    sampling_rate = serializers.FloatField(
        required=False,
        min_value=0.0,
        max_value=1.0,
        help_text="0..1 random downsample applied after the query matches. Defaults to 1.0 (no downsampling).",
    )
    provider = serializers.ChoiceField(
        choices=LensProvider.choices,
        required=False,
        help_text="LLM provider. v1 is Google-only.",
    )
    model = serializers.ChoiceField(
        choices=LensModel.choices,
        help_text="Concrete model to use for this lens.",
    )
    enabled = serializers.BooleanField(
        required=False,
        help_text="When false, the reconciler removes the lens's Temporal schedule. On-demand triggers still work.",
    )
    emits_signals = serializers.BooleanField(
        required=False,
        help_text="When true, the prompt is augmented with the Signal side mission and the lens emits PostHog Signals.",
    )

    lens_version = serializers.IntegerField(
        read_only=True,
        help_text="Increments on every config-changing save. Observations snapshot this value.",
    )
    last_swept_at = serializers.DateTimeField(
        read_only=True,
        help_text="Watermark for the lens's last scheduled fire. Mirrors Temporal schedule state for recovery.",
    )
    created_by = UserBasicSerializer(
        read_only=True,
        allow_null=True,
        help_text="User who created the lens.",
    )

    class Meta:
        model = ReplayLens
        fields = [
            "id",
            "name",
            "description",
            "lens_type",
            "lens_config",
            "query",
            "sampling_rate",
            "provider",
            "model",
            "enabled",
            "emits_signals",
            "lens_version",
            "last_swept_at",
            "created_at",
            "created_by",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "lens_version",
            "last_swept_at",
            "created_at",
            "created_by",
            "updated_at",
        ]

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        # Surface the (team_id, name) uniqueness as a 400 instead of letting the DB raise 500.
        name = attrs.get("name")
        if name is not None:
            team = self.context["get_team"]()
            duplicates = ReplayLens.objects.filter(team=team, name=name)
            if self.instance is not None:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                raise serializers.ValidationError({"name": "A lens with this name already exists in this team."})
        return attrs

    def create(self, validated_data: dict[str, Any]) -> ReplayLens:
        team = self.context["get_team"]()
        user = cast(User, self.context["request"].user)
        try:
            return ReplayLens.objects.create(team=team, created_by=user, **validated_data)
        except IntegrityError as e:
            self._reraise_unique_name_violation(e)

    def update(self, instance: ReplayLens, validated_data: dict[str, Any]) -> ReplayLens:
        try:
            return super().update(instance, validated_data)
        except IntegrityError as e:
            self._reraise_unique_name_violation(e)

    @staticmethod
    def _reraise_unique_name_violation(error: IntegrityError) -> NoReturn:
        # Narrow to the unique-name constraint so other future constraints aren't mis-reported as duplicates.
        if "replay_lens_unique_team_name" in str(error):
            raise serializers.ValidationError({"name": "A lens with this name already exists in this team."})
        raise error


class ReplayLensFilter(django_filters.FilterSet):
    enabled = django_filters.BooleanFilter(
        field_name="enabled",
        help_text="Filter to enabled vs disabled lenses.",
    )
    lens_type = django_filters.ChoiceFilter(
        field_name="lens_type",
        choices=LensType.choices,
        help_text="Filter by lens type (monitor, classifier, scorer, summarizer, indexer).",
    )
    emits_signals = django_filters.BooleanFilter(
        field_name="emits_signals",
        help_text="Filter to lenses that emit Signals.",
    )
    order_by = django_filters.OrderingFilter(
        fields=(
            ("name", "name"),
            ("created_at", "created_at"),
            ("updated_at", "updated_at"),
            ("lens_type", "lens_type"),
        ),
        help_text="Sort lenses by name, created_at, updated_at, or lens_type. Prefix with `-` for descending.",
    )

    class Meta:
        model = ReplayLens
        fields = ["enabled", "lens_type", "emits_signals"]


class ObserveRequestSerializer(serializers.Serializer):
    """Body of POST /vision/lenses/{id}/observe/."""

    session_id = serializers.CharField(
        max_length=200,
        help_text="ID of the session recording to apply the lens to.",
    )


@extend_schema(tags=[VISION_TAG])
class ReplayLensViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    """CRUD for Replay Vision lenses."""

    scope_object = "replay_lens"
    # Custom @action methods don't fall under the default read/write action lists, so personal API
    # keys would 403 silently. List the action explicitly so :write tokens can call it.
    scope_object_write_actions = ["create", "update", "partial_update", "patch", "destroy", "observe"]
    permission_classes = [ReplayVisionEnabledPermission]
    serializer_class = ReplayLensSerializer
    queryset = ReplayLens.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = ReplayLensFilter
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def safely_get_queryset(self, queryset: QuerySet[ReplayLens]) -> QuerySet[ReplayLens]:
        return queryset.filter(team_id=self.team_id).select_related("created_by").order_by("name", "id")

    @extend_schema(
        request=ObserveRequestSerializer,
        responses={
            201: ReplayObservationSerializer,
            200: ReplayObservationSerializer,
        },
    )
    @action(detail=True, methods=["post"], url_path="observe")
    def observe(self, request: Request, **kwargs: Any) -> Response:
        """Apply this lens to one specific session, on demand.

        Bypasses the lens's query and sampling. Idempotent against the
        `UNIQUE(lens, session_id)` constraint — a second call for the same session
        returns the existing observation (200) rather than creating a duplicate.
        """
        lens = self.get_object()
        # Reading observation output reveals the underlying recording's contents, so triggering one
        # requires session_recording read in addition to the replay_lens write scope.
        if not self.user_access_control.check_access_level_for_resource("session_recording", required_level="viewer"):
            raise PermissionDenied("Triggering an on-demand observation requires session_recording read access.")

        body = ObserveRequestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        session_id: str = body.validated_data["session_id"]
        user = cast(User, request.user)

        try:
            with transaction.atomic():
                observation = ReplayObservation.objects.create(
                    lens=lens,
                    team=lens.team,
                    session_id=session_id,
                    triggered_by=ObservationTrigger.ON_DEMAND,
                    triggered_by_user=user,
                    lens_version=lens.lens_version,
                    lens_config_snapshot=copy.deepcopy(lens.lens_config),
                )
        except IntegrityError:
            existing = ReplayObservation.objects.get(lens=lens, session_id=session_id)
            return Response(ReplayObservationSerializer(existing).data, status=status.HTTP_200_OK)

        # workflow_id is derived from observation.id so it's stable: a duplicate dispatch (e.g. retry
        # after a transient failure between the row insert and start_workflow) coalesces in Temporal.
        workflow_id = f"replay-vision-apply-lens-{observation.id}"
        try:
            client = sync_connect()
            async_to_sync(client.start_workflow)(  # type: ignore[misc]
                APPLY_LENS_WORKFLOW_NAME,  # type: ignore[arg-type]
                ApplyLensInputs(
                    observation_id=str(observation.id),
                    lens_id=str(lens.id),
                    session_id=session_id,
                    team_id=lens.team_id,
                ),
                id=workflow_id,
                task_queue=settings.REPLAY_VISION_TASK_QUEUE,
            )
        except Exception as exc:
            # Don't strand the row in pending if dispatch fails — the user gets an error and the row
            # records why. Temporal's WorkflowAlreadyStarted is benign (same observation_id ⇒ same
            # workflow_id ⇒ same in-flight workflow); treat it as success.
            if type(exc).__name__ == "WorkflowAlreadyStartedError":
                logger.info("replay_vision.observe.workflow_already_started", workflow_id=workflow_id)
            else:
                logger.exception("replay_vision.observe.workflow_start_failed", workflow_id=workflow_id)
                observation.mark_failed(f"Failed to start workflow: {type(exc).__name__}: {exc}")
                observation.refresh_from_db()
                return Response(
                    ReplayObservationSerializer(observation).data,
                    status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

        return Response(ReplayObservationSerializer(observation).data, status=status.HTTP_201_CREATED)

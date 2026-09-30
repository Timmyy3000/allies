import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone

# ruff: noqa: RUF012


class PushSubscription(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey("auths.User", on_delete=models.CASCADE)
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE)
    family = models.ForeignKey("auths.SessionFamily", on_delete=models.CASCADE)
    browser_id = models.UUIDField()
    binding_id = models.UUIDField(unique=True)
    registration_digest = models.CharField(max_length=64)
    endpoint_digest = models.CharField(max_length=64)
    secret = models.BinaryField(default=bytes)
    state = models.CharField(
        max_length=16,
        default="active",
        choices=(("active", "Active"), ("revoked", "Revoked")),
    )
    presence = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("endpoint_digest",),
                condition=Q(state="active"),
                name="push_active_endpoint_uniq",
            ),
            models.UniqueConstraint(
                fields=("owner", "browser_id"),
                condition=Q(state="active"),
                name="push_active_browser_uniq",
            ),
        ]


class PushNotification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    identity = models.CharField(max_length=100, unique=True)
    kind = models.CharField(
        max_length=24,
        choices=tuple(
            (v, v)
            for v in (
                "approval_needed",
                "routine_completed",
                "routine_failed",
                "reply_completed",
            )
        ),
    )
    owner = models.ForeignKey("auths.User", on_delete=models.CASCADE)
    workspace = models.ForeignKey("workspaces.Workspace", on_delete=models.CASCADE)
    ally = models.ForeignKey("allies.Ally", on_delete=models.CASCADE)
    conversation = models.ForeignKey("chat.Conversation", on_delete=models.CASCADE)
    approval = models.ForeignKey(
        "activities.Approval", on_delete=models.CASCADE, null=True
    )
    routine_approval = models.ForeignKey(
        "routines.RoutineApprovalProjection", on_delete=models.CASCADE, null=True
    )
    reply = models.ForeignKey(
        "chat.AssistantReply", on_delete=models.CASCADE, null=True
    )
    result = models.ForeignKey(
        "activities.RoutineResultProjection", on_delete=models.CASCADE, null=True
    )
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()


class PushDelivery(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subscription = models.ForeignKey(PushSubscription, on_delete=models.CASCADE)
    notification = models.ForeignKey(PushNotification, on_delete=models.CASCADE)
    binding_id = models.UUIDField()
    state = models.CharField(
        max_length=16,
        default="pending",
        choices=tuple(
            (v, v)
            for v in ("pending", "sending", "sent", "suppressed", "retired", "failed")
        ),
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    lease_until = models.DateTimeField(null=True)
    safe_error_code = models.CharField(max_length=40, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("subscription", "notification"), name="push_delivery_pair_uniq"
            ),
            models.CheckConstraint(
                condition=Q(attempts__lte=3), name="push_attempts_bounded"
            ),
        ]

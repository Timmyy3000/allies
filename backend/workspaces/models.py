from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

# Django model metaclasses intentionally consume mutable Meta collections.
# ruff: noqa: RUF012


class WorkspaceKind(models.TextChoices):
    PERSONAL = "personal", "Personal"


class RuntimeIntentMode(models.TextChoices):
    OFF = "off", "Off"
    COMPOSING = "composing", "Composing"
    OPEN = "open", "Open"


class MembershipRole(models.TextChoices):
    OWNER = "owner", "Owner"


class MembershipStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"


class Workspace(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(
        max_length=20, choices=WorkspaceKind.choices, default=WorkspaceKind.PERSONAL
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="owned_workspaces",
    )
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    runtime_intent_mode = models.CharField(
        max_length=16,
        choices=RuntimeIntentMode.choices,
        default=RuntimeIntentMode.COMPOSING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("owner",),
                condition=Q(kind=WorkspaceKind.PERSONAL),
                name="workspace_one_personal_owner_uniq",
            ),
            models.CheckConstraint(
                condition=Q(kind=WorkspaceKind.PERSONAL, owner__isnull=False)
                | ~Q(kind=WorkspaceKind.PERSONAL),
                name="workspace_personal_owner_required_chk",
            ),
        ]
        indexes = [
            models.Index(fields=("owner", "kind"), name="workspace_owner_kind_idx")
        ]

    def __str__(self) -> str:
        return str(self.id)


class Membership(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
    )
    role = models.CharField(max_length=20, choices=MembershipRole.choices)
    status = models.CharField(max_length=20, choices=MembershipStatus.choices)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "user"),
                name="workspace_membership_workspace_user_uniq",
            ),
            models.CheckConstraint(
                condition=Q(
                    role=MembershipRole.OWNER,
                    status__in=[MembershipStatus.ACTIVE, MembershipStatus.INACTIVE],
                ),
                name="workspace_membership_role_status_chk",
            ),
        ]
        indexes = [
            models.Index(fields=("user", "status"), name="ws_member_user_status_idx")
        ]

    def __str__(self) -> str:
        return f"{self.workspace_id}:{self.user_id}"

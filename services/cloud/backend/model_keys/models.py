"""Workspace-held model-provider keys and each Ally's desired model source.

A key value is sealed in ``ModelKey.ciphertext`` and leaves Cloud only through
the credential broker. ``AllyModelSelection`` is the desired state for one
Ally; ``synced`` says whether Foundry has accepted it. No row means the Ally
runs on the org default.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

# Django model metaclasses intentionally consume mutable Meta collections.
# ruff: noqa: RUF012

# Static-key providers Hermes supports, mapped to the profile env name.
PROVIDERS = {
    "opencode-zen": "OPENCODE_ZEN_API_KEY",
    "opencode-go": "OPENCODE_GO_API_KEY",
}
REFERENCE_PREFIX = "allies-key://model-keys/"
REASONING_LEVELS = ("high", "xhigh")


class SelectionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CONNECTED = "connected", "Connected"
    DEGRADED = "degraded", "Needs attention"


class ModelKey(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="model_keys",
    )
    provider = models.CharField(max_length=32)
    ciphertext = models.BinaryField()
    key_hint = models.CharField(max_length=4)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    connected_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "provider"),
                condition=Q(revoked_at__isnull=True),
                name="model_key_one_active_per_provider",
            ),
        ]

    def __str__(self) -> str:
        return str(self.id)

    @property
    def reference(self) -> str:
        return f"{REFERENCE_PREFIX}{self.id}"


class AllyModelSelection(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    ally = models.OneToOneField(
        "allies.Ally",
        on_delete=models.CASCADE,
        related_name="model_selection",
    )
    model_key = models.ForeignKey(
        ModelKey,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="selections",
    )
    foundry_profile_id = models.UUIDField()
    model = models.CharField(max_length=128, blank=True, default="")
    reasoning = models.CharField(max_length=8, blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=SelectionStatus.choices,
        default=SelectionStatus.PENDING,
    )
    synced = models.BooleanField(default=False)
    revision = models.PositiveIntegerField(default=1)
    sync_attempts = models.PositiveSmallIntegerField(default=0)
    synced_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("synced", "updated_at"),
                name="model_selection_sync_idx",
            ),
        ]

    def __str__(self) -> str:
        return str(self.id)

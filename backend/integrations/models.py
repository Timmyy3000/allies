"""Generic tenant-scoped integration secrets and per-Ally grants.

One ``IntegrationSecret`` row serves every provider (Gmail first): it holds
an encrypted refresh credential plus the granted scope set. Per-Ally access
is a separate ``AllyIntegrationGrant`` row so revoking one Ally never touches
the account connection. ``GmailConnectSession`` tracks the short-lived OAuth
handshake between begin and callback.
"""

from __future__ import annotations

import uuid

from django.db import models

# Django model metaclasses intentionally consume mutable Meta collections.
# ruff: noqa: RUF012

PROVIDER_GMAIL = "gmail"

GRANT_READ = "read"
GRANT_SEND = "send"
GRANT_LEVELS = (GRANT_READ, GRANT_SEND)


class IntegrationSecret(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="integration_secrets",
    )
    provider_key = models.CharField(max_length=32)
    account_ref_hash = models.CharField(max_length=64)
    account_email = models.CharField(max_length=254, default="")
    ciphertext = models.BinaryField()
    key_version = models.PositiveIntegerField(default=1)
    scope_set = models.JSONField(default=list)
    generation_epoch = models.PositiveIntegerField(default=1)
    connected_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("workspace", "provider_key", "account_ref_hash"),
                name="integration_secret_workspace_provider_account_uniq",
            ),
            models.UniqueConstraint(
                fields=("workspace", "provider_key"),
                condition=models.Q(revoked_at__isnull=True),
                name="integration_secret_one_active_provider_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=("workspace", "provider_key"),
                name="integration_secret_workspace_provider_idx",
            ),
        ]

    def __str__(self) -> str:
        return str(self.id)


class AllyIntegrationGrant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    secret = models.ForeignKey(
        IntegrationSecret,
        on_delete=models.CASCADE,
        related_name="ally_grants",
    )
    ally = models.ForeignKey(
        "allies.Ally",
        on_delete=models.CASCADE,
        related_name="integration_grants",
    )
    level = models.CharField(max_length=8)
    grant_generation = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        "auths.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="granted_integration_access",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("secret", "ally"),
                name="ally_integration_grant_secret_ally_uniq",
            ),
        ]

    def __str__(self) -> str:
        return str(self.id)


class GmailConnectSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="gmail_connect_sessions",
    )
    state_hash = models.CharField(max_length=64, unique=True)
    sealed_handshake = models.TextField()
    entry_point = models.CharField(max_length=16)
    ally = models.ForeignKey(
        "allies.Ally",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="gmail_connect_sessions",
    )
    idempotency_key = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("workspace", "created_at"),
                name="gmail_connect_session_workspace_created_idx",
            ),
        ]

    def __str__(self) -> str:
        return str(self.id)

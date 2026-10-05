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
PROVIDER_CALENDAR = "calendar"

GRANT_READ = "read"
GRANT_SEND = "send"
GRANT_WRITE = "write"
PROVIDER_GRANT_LEVELS = {
    PROVIDER_GMAIL: (GRANT_READ, GRANT_SEND),
    PROVIDER_CALENDAR: (GRANT_READ, GRANT_WRITE),
}


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
                name="int_secret_ws_provider_idx",
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
                name="gmail_conn_ws_created_idx",
            ),
        ]

    def __str__(self) -> str:
        return str(self.id)


class IntegrationToolCall(models.Model):
    """One relayed integration tool call, replayed by ``(message, call_id)``.

    ``consumed_ref`` marks the send confirmation a call used; the unique
    constraint makes each confirmation send at most once.
    """

    message = models.ForeignKey("chat.Message", on_delete=models.CASCADE)
    call_id = models.UUIDField()
    request_digest = models.CharField(max_length=64)
    response = models.JSONField()
    consumed_ref = models.CharField(max_length=36, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("message", "call_id"), name="integration_tool_call_uniq"
            ),
            models.UniqueConstraint(
                fields=("consumed_ref",), name="integration_tool_ref_uniq"
            ),
        ]


class SafeInput(models.Model):
    """A user-entered login; ``sealed`` is vault ciphertext of username and password."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="safe_inputs"
    )
    name = models.CharField(max_length=80)
    website = models.CharField(max_length=253)
    sealed = models.BinaryField()
    created_by = models.ForeignKey(
        "auths.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return str(self.id)


class SafeInputGrant(models.Model):
    safe_input = models.ForeignKey(
        SafeInput, on_delete=models.CASCADE, related_name="grants"
    )
    ally = models.ForeignKey(
        "allies.Ally", on_delete=models.CASCADE, related_name="safe_input_grants"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("safe_input", "ally"), name="safe_input_grant_uniq"
            ),
        ]


class SafeInputRequest(models.Model):
    PENDING, SAVED, ALLOWED, DENIED = "pending", "saved", "allowed", "denied"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="+"
    )
    ally = models.ForeignKey("allies.Ally", on_delete=models.CASCADE, related_name="+")
    safe_input = models.ForeignKey(
        SafeInput, null=True, blank=True, on_delete=models.CASCADE, related_name="+"
    )
    name = models.CharField(max_length=80)
    website = models.CharField(max_length=253)
    status = models.CharField(max_length=8, default=PENDING)
    created_at = models.DateTimeField(auto_now_add=True)


class AllyBrowser(models.Model):
    ally = models.OneToOneField(
        "allies.Ally", on_delete=models.CASCADE, related_name="browser"
    )
    profile_id = models.CharField(max_length=64, blank=True, default="")
    pending_clear_sites = models.JSONField(default=list)


class BrowserSession(models.Model):
    """One Browser Use session; also the usage record for billing."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(
        "workspaces.Workspace", on_delete=models.CASCADE, related_name="+"
    )
    ally = models.ForeignKey(
        "allies.Ally", on_delete=models.CASCADE, related_name="browser_sessions"
    )
    browser_use_id = models.CharField(max_length=64, blank=True, default="")
    cdp_url = models.TextField(blank=True, default="")
    live_url = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)

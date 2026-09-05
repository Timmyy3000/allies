"""Durable authentication/account nouns.

The services in :mod:`auths.services` own workflows.  These models only carry
state and database-level invariants so callers cannot bypass identity and
session uniqueness by accident.
"""

# Django model metaclasses intentionally consume mutable Meta collections.
# ruff: noqa: RUF012

from __future__ import annotations

import uuid
from datetime import timedelta

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Provider(models.TextChoices):
    FAKE = "fake", "Fake"
    GOOGLE = "google", "Google"


class FlowPurpose(models.TextChoices):
    SIGN_IN = "sign_in", "Sign in"
    LINK = "link", "Link identity"


class NativeTransactionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CLAIMED = "claimed", "Claimed"
    COMPLETED = "completed", "Completed"
    DENIED = "denied", "Denied"
    FAILED = "failed", "Failed"


class NativeCompletionMode(models.TextChoices):
    REDIRECT = "redirect", "Redirect"
    MANUAL_CODE = "manual_code", "Manual code"


class SessionClientKind(models.TextChoices):
    BROWSER = "browser", "Browser"
    NATIVE = "native", "Native"


class AvatarStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    READY = "ready", "Ready"
    REPLACED = "replaced", "Replaced"
    DELETED = "deleted", "Deleted"
    REJECTED = "rejected", "Rejected"


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    def _create(self, *, is_staff: bool, is_superuser: bool, **extra_fields):
        password = extra_fields.pop("password", None)
        user = self.model(
            is_staff=is_staff,
            is_superuser=is_superuser,
            **extra_fields,
        )
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, **extra_fields):
        return self._create(
            is_staff=False,
            is_superuser=False,
            **extra_fields,
        )

    def create_superuser(self, **extra_fields):
        return self._create(
            is_staff=True,
            is_superuser=True,
            **extra_fields,
        )


class User(AbstractBaseUser, PermissionsMixin):
    """The sole Cloud principal."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now, editable=False)

    objects = UserManager()

    USERNAME_FIELD = "id"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        ordering = ("id",)
        indexes = [
            models.Index(fields=("is_active", "id"), name="auth_user_active_idx")
        ]

    def __str__(self) -> str:
        return str(self.id)

    def get_username(self) -> str:
        return str(self.id)


class ExternalIdentity(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="external_identities"
    )
    provider = models.CharField(max_length=32, choices=Provider.choices)
    subject = models.CharField(max_length=255)
    issuer = models.CharField(max_length=255, blank=True)
    email_snapshot = models.EmailField(blank=True)
    email_verified = models.BooleanField(default=False)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    email_verification_source = models.CharField(max_length=32, blank=True)
    display_name_snapshot = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("provider", "subject"),
                name="auth_identity_provider_subject_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        email_verified=False,
                        email_verified_at__isnull=True,
                        email_verification_source="",
                    )
                    | Q(
                        email_verified=True,
                        provider=Provider.GOOGLE,
                        email_snapshot__gt="",
                        email_verified_at__isnull=False,
                        email_verification_source="google",
                    )
                ),
                name="auth_identity_verified_email_coherent",
            ),
        ]
        indexes = [
            models.Index(
                fields=("user", "provider"), name="auth_identity_user_prov_idx"
            )
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.subject}"


class UserProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    display_name = models.CharField(max_length=80, blank=True)
    current_avatar = models.ForeignKey(
        "AvatarAsset",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="current_for_profiles",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(display_name__isnull=False),
                name="auth_profile_display_name_not_null",
            )
        ]


class AuthFlow(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    state_digest = models.CharField(max_length=64, unique=True, editable=False)
    flow_cookie_digest = models.CharField(max_length=64, editable=False)
    browser_binding_digest = models.CharField(max_length=64, editable=False)
    provider = models.CharField(max_length=32, choices=Provider.choices)
    purpose = models.CharField(max_length=16, choices=FlowPurpose.choices)
    redirect_to = models.CharField(max_length=500)
    callback_uri = models.CharField(max_length=500)
    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="auth_flows",
    )
    session_family = models.ForeignKey(
        "SessionFamily",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="auth_flows",
    )
    nonce_digest = models.CharField(max_length=64, editable=False)
    nonce_sealed = models.TextField(editable=False)
    pkce_verifier_sealed = models.TextField(editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        user__isnull=True,
                        purpose=FlowPurpose.SIGN_IN,
                        session_family__isnull=True,
                    )
                    | Q(
                        user__isnull=False,
                        purpose=FlowPurpose.LINK,
                        session_family__isnull=False,
                    )
                ),
                name="auth_flow_purpose_binding_chk",
            )
        ]
        indexes = [
            models.Index(
                fields=("expires_at", "consumed_at"),
                name="auth_flow_expiry_consumed_idx",
            )
        ]


class NativeAuthorizationTransaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    state_digest = models.CharField(max_length=64, unique=True, editable=False)
    provider = models.CharField(max_length=32, choices=Provider.choices)
    callback_uri = models.CharField(max_length=500)
    redirect_uri = models.CharField(max_length=500)
    completion_mode = models.CharField(
        max_length=16,
        choices=NativeCompletionMode.choices,
        default=NativeCompletionMode.REDIRECT,
        db_default=models.Value("redirect"),
    )
    app_state_sealed = models.TextField(editable=False)
    code_challenge = models.CharField(max_length=128, editable=False)
    nonce_digest = models.CharField(max_length=64, editable=False)
    nonce_sealed = models.TextField(editable=False)
    pkce_verifier_sealed = models.TextField(editable=False)
    status = models.CharField(
        max_length=16,
        choices=NativeTransactionStatus.choices,
        default=NativeTransactionStatus.PENDING,
    )
    claim_digest = models.CharField(max_length=64, blank=True, editable=False)
    claimed_at = models.DateTimeField(null=True, blank=True)
    claim_expires_at = models.DateTimeField(null=True, blank=True)
    terminal_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        status=NativeTransactionStatus.PENDING,
                        terminal_at__isnull=True,
                    )
                    | Q(
                        status=NativeTransactionStatus.CLAIMED,
                        claimed_at__isnull=False,
                        claim_expires_at__isnull=False,
                        terminal_at__isnull=True,
                    )
                    | Q(
                        status__in=(
                            NativeTransactionStatus.COMPLETED,
                            NativeTransactionStatus.DENIED,
                            NativeTransactionStatus.FAILED,
                        ),
                        terminal_at__isnull=False,
                    )
                ),
                name="auth_native_tx_status_coherent",
            ),
        ]
        indexes = [
            models.Index(
                fields=("status", "expires_at"), name="auth_native_tx_state_exp_idx"
            ),
            models.Index(
                fields=("status", "claim_expires_at"),
                name="auth_native_tx_claim_exp_idx",
            ),
            models.Index(
                fields=("status", "terminal_at"),
                name="auth_native_tx_terminal_idx",
            ),
        ]


class NativeExchangeCode(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction = models.OneToOneField(
        NativeAuthorizationTransaction,
        on_delete=models.PROTECT,
        related_name="exchange_code",
    )
    code_digest = models.CharField(max_length=64, unique=True, editable=False)
    code_sealed = models.TextField(editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="native_exchange_codes"
    )
    redirect_uri = models.CharField(max_length=500)
    code_challenge = models.CharField(max_length=128, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("expires_at", "consumed_at"),
                name="auth_native_code_exp_cons_idx",
            ),
        ]


class SessionFamily(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="session_families"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(default=timezone.now)
    idle_expires_at = models.DateTimeField()
    absolute_expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=64, blank=True)
    client_kind = models.CharField(
        max_length=16,
        choices=SessionClientKind.choices,
        default=SessionClientKind.BROWSER,
    )

    class Meta:
        indexes = [
            models.Index(fields=("user",), name="auth_family_user_idx"),
            models.Index(
                fields=("revoked_at", "absolute_expires_at", "idle_expires_at"),
                name="auth_family_state_idx",
            ),
        ]

    def __str__(self) -> str:
        return str(self.id)

    def is_active(self, now=None) -> bool:
        now = now or timezone.now()
        return (
            self.revoked_at is None
            and self.absolute_expires_at > now
            and self.idle_expires_at > now
            and self.user.is_active
        )


class RefreshToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    family = models.ForeignKey(
        SessionFamily, on_delete=models.CASCADE, related_name="refresh_tokens"
    )
    token_digest = models.CharField(max_length=128, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("family",),
                condition=Q(used_at__isnull=True),
                name="auth_refresh_one_unused_per_family_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=("family", "expires_at"), name="auth_refresh_family_expiry_idx"
            )
        ]


class AvatarAsset(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="avatar_assets"
    )
    object_key = models.CharField(max_length=500, unique=True, editable=False)
    status = models.CharField(
        max_length=16, choices=AvatarStatus.choices, default=AvatarStatus.PENDING
    )
    expected_content_type = models.CharField(max_length=64)
    expected_size = models.PositiveIntegerField()
    expected_sha256 = models.CharField(max_length=64)
    actual_content_type = models.CharField(max_length=64, blank=True)
    actual_size = models.PositiveIntegerField(null=True, blank=True)
    actual_sha256 = models.CharField(max_length=64, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    eligible_at = models.DateTimeField(null=True, blank=True)
    cleanup_attempts = models.PositiveIntegerField(default=0)
    cleanup_last_error = models.CharField(max_length=255, blank=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("user", "created_at"), name="auth_avatar_user_created_idx"
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(expected_size__gt=0), name="auth_avatar_expected_size_chk"
            ),
            models.CheckConstraint(
                condition=Q(expected_sha256__regex=r"^[0-9a-fA-F]{64}$"),
                name="auth_avatar_expected_sha_chk",
            ),
        ]

    def __str__(self) -> str:
        return str(self.id)


def default_session_expiry(now=None) -> tuple:
    now = now or timezone.now()
    return now + timedelta(days=14), now + timedelta(days=30)

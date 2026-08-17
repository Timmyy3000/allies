from django.db import models
from django.db.models import Q

from common.identifiers import new_public_id

# Django model metaclasses intentionally consume mutable Meta collections.
# ruff: noqa: RUF012


def new_entry_public_id() -> str:
    return new_public_id("wle")


class WaitlistEntry(models.Model):
    public_id = models.CharField(
        max_length=40, unique=True, editable=False, default=new_entry_public_id
    )
    attempt_id_digest = models.CharField(max_length=64, unique=True, editable=False)
    attempt_token_digest = models.CharField(max_length=64, unique=True, editable=False)
    completion_digest = models.CharField(max_length=64, blank=True, editable=False)
    generation_claimed_at = models.DateTimeField(null=True, blank=True, editable=False)

    name = models.CharField(max_length=80)
    appearance_catalog_version = models.CharField(max_length=32)
    appearance_key = models.CharField(max_length=128)
    job = models.TextField()
    personality = models.TextField(blank=True)

    greeting_text = models.TextField(blank=True)
    greeting_policy_version = models.CharField(max_length=32, blank=True)
    greeting_generated_at = models.DateTimeField(null=True, blank=True)

    reply_text = models.TextField(blank=True)
    reply_recorded_at = models.DateTimeField(null=True, blank=True)
    email_normalized = models.EmailField(blank=True)
    consent_version = models.CharField(max_length=64, blank=True)
    joined_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=("expires_at", "id"), name="waitlist_entry_retention_idx"
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(email_normalized="", consent_version="", joined_at__isnull=True)
                    | Q(
                        email_normalized__gt="",
                        consent_version__gt="",
                        joined_at__isnull=False,
                    )
                ),
                name="waitlist_entry_join_fields_coherent",
            ),
            models.CheckConstraint(
                condition=(
                    Q(greeting_text="", greeting_generated_at__isnull=True)
                    | Q(greeting_text__gt="", greeting_generated_at__isnull=False)
                ),
                name="waitlist_entry_greeting_fields_coherent",
            ),
            models.CheckConstraint(
                condition=(
                    Q(reply_text="", reply_recorded_at__isnull=True)
                    | Q(reply_text__gt="", reply_recorded_at__isnull=False)
                ),
                name="waitlist_entry_reply_fields_coherent",
            ),
        ]

    def __str__(self) -> str:
        return self.public_id

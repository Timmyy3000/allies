# ruff: noqa: RUF012

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("runtime", "0008_runtime_credentials_and_claim_receipts"),
    ]

    operations = [
        migrations.AddField(
            model_name="runtimeprofile",
            name="cleanup_completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="runtimeprofile",
            name="cleanup_context_digest",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="runtimeprofile",
            name="cleanup_operation_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="runtimeprofile",
            name="cleanup_receipt_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="runtimeprofile",
            name="cleanup_request_digest",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="runtimeprofile",
            name="cleanup_result_code",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="runtimeprofile",
            name="cleanup_retry_after",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="runtimeprofile",
            name="hermes_profile_key_version",
            # Existing rows predate the deterministic v1 algorithm.  Keep
            # their immutable key and mark them legacy for explicit audit.
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="runtimeprofile",
            name="lifecycle_epoch",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="runtimeprofile",
            name="lifecycle_state",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("active", "Active"),
                    ("cleanup_pending", "Cleanup pending"),
                    ("deprovisioned", "Deprovisioned"),
                    ("repair_required", "Repair required"),
                ],
                default="active",
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name="runtimeprofile",
            name="materialized_generation",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="runtimeprofile",
            name="seed_fingerprint",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="runtimeprofile",
            name="seed_version",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AlterField(
            model_name="runtimeprofile",
            name="hermes_profile_key_version",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AlterField(
            model_name="runtimeprofile",
            name="lifecycle_state",
            field=models.CharField(
                choices=[
                    ("pending", "Pending"),
                    ("active", "Active"),
                    ("cleanup_pending", "Cleanup pending"),
                    ("deprovisioned", "Deprovisioned"),
                    ("repair_required", "Repair required"),
                ],
                default="pending",
                max_length=24,
            ),
        ),
        migrations.AddConstraint(
            model_name="runtimeprofile",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "lifecycle_state__in",
                        [
                            "pending",
                            "active",
                            "cleanup_pending",
                            "deprovisioned",
                            "repair_required",
                        ],
                    )
                ),
                name="runtime_profile_lifecycle_state_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="runtimeprofile",
            constraint=models.CheckConstraint(
                condition=models.Q(("hermes_profile_key_version__in", [0, 1])),
                name="runtime_profile_key_version_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="runtimeprofile",
            constraint=models.CheckConstraint(
                condition=models.Q(("seed_version__gt", 0)),
                name="runtime_profile_seed_version_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="runtimeprofile",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("seed_fingerprint", ""),
                    ("seed_fingerprint__regex", "^[0-9a-f]{64}$"),
                    _connector="OR",
                ),
                name="runtime_profile_seed_fingerprint_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="runtimeprofile",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("cleanup_context_digest", ""),
                    ("cleanup_context_digest__regex", "^[0-9a-f]{64}$"),
                    _connector="OR",
                ),
                name="runtime_profile_cleanup_context_digest_valid",
            ),
        ),
        migrations.AddConstraint(
            model_name="runtimeprofile",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("cleanup_request_digest", ""),
                    ("cleanup_request_digest__regex", "^[0-9a-f]{64}$"),
                    _connector="OR",
                ),
                name="runtime_profile_cleanup_request_digest_valid",
            ),
        ),
    ]

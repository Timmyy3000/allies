# ruff: noqa: RUF012

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("runtime", "0009_fnd006_profile_lifecycle"),
    ]

    operations = [
        migrations.AddField(
            model_name="runtimeprofile",
            name="cleanup_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="runtimeprofile",
            name="materialization_operation_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="runtimeprofile",
            name="materialization_receipt_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="runtimeprofile",
            name="materialization_request_digest",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="runtimeprofile",
            name="materialization_result_code",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="runtimeprofile",
            name="seed_payload",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddConstraint(
            model_name="runtimeprofile",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("materialization_request_digest", ""),
                    ("materialization_request_digest__regex", "^[0-9a-f]{64}$"),
                    _connector="OR",
                ),
                name="runtime_profile_materialization_digest_valid",
            ),
        ),
    ]

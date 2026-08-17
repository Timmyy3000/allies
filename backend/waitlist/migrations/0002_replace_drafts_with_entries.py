# ruff: noqa: RUF012

from django.db import migrations, models

import waitlist.models


class Migration(migrations.Migration):
    dependencies = [("waitlist", "0001_initial")]

    operations = [
        migrations.DeleteModel(name="WaitlistOperation"),
        migrations.DeleteModel(name="WaitlistDraft"),
        migrations.CreateModel(
            name="WaitlistEntry",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "public_id",
                    models.CharField(
                        default=waitlist.models.new_entry_public_id,
                        editable=False,
                        max_length=40,
                        unique=True,
                    ),
                ),
                (
                    "attempt_id_digest",
                    models.CharField(editable=False, max_length=64, unique=True),
                ),
                (
                    "attempt_token_digest",
                    models.CharField(editable=False, max_length=64, unique=True),
                ),
                (
                    "completion_digest",
                    models.CharField(blank=True, editable=False, max_length=64),
                ),
                (
                    "generation_claimed_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                ("name", models.CharField(max_length=80)),
                ("appearance_catalog_version", models.CharField(max_length=32)),
                ("appearance_key", models.CharField(max_length=128)),
                ("job", models.TextField()),
                ("personality", models.TextField(blank=True)),
                ("greeting_text", models.TextField(blank=True)),
                (
                    "greeting_policy_version",
                    models.CharField(blank=True, max_length=32),
                ),
                ("greeting_generated_at", models.DateTimeField(blank=True, null=True)),
                ("reply_text", models.TextField(blank=True)),
                ("reply_recorded_at", models.DateTimeField(blank=True, null=True)),
                ("email_normalized", models.EmailField(blank=True, max_length=254)),
                ("consent_version", models.CharField(blank=True, max_length=64)),
                ("joined_at", models.DateTimeField(blank=True, null=True)),
                ("expires_at", models.DateTimeField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["expires_at", "id"], name="waitlist_entry_retention_idx"
                    )
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            ("consent_version", ""),
                            ("email_normalized", ""),
                            ("joined_at__isnull", True),
                            _connector="AND",
                        )
                        | models.Q(
                            ("consent_version__gt", ""),
                            ("email_normalized__gt", ""),
                            ("joined_at__isnull", False),
                            _connector="AND",
                        ),
                        name="waitlist_entry_join_fields_coherent",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("greeting_generated_at__isnull", True),
                            ("greeting_text", ""),
                        )
                        | models.Q(
                            ("greeting_generated_at__isnull", False),
                            ("greeting_text__gt", ""),
                        ),
                        name="waitlist_entry_greeting_fields_coherent",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("reply_recorded_at__isnull", True), ("reply_text", "")
                        )
                        | models.Q(
                            ("reply_recorded_at__isnull", False), ("reply_text__gt", "")
                        ),
                        name="waitlist_entry_reply_fields_coherent",
                    ),
                ],
            },
        ),
    ]

import uuid
from typing import ClassVar

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies: ClassVar = [
        ("runtime", "0035_profile_native_openrouter_provider"),
    ]

    operations: ClassVar = [
        migrations.CreateModel(
            name="MessageStopFence",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("cloud_conversation_id", models.UUIDField()),
                ("cloud_message_id", models.UUIDField()),
                ("requested_at", models.DateTimeField(auto_now_add=True)),
                (
                    "workspace",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="runtime.workspace",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=(
                            "workspace",
                            "cloud_conversation_id",
                            "cloud_message_id",
                        ),
                        name="runtime_message_stop_identity",
                    )
                ],
            },
        ),
    ]

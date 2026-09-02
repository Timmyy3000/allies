# ruff: noqa: RUF012

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("runtime", "0012_conversation_binding_session_nullable"),
    ]

    operations = [
        migrations.AddField(
            model_name="workspace",
            name="activation_claim_expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="workspace",
            name="activation_claim_token",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
    ]

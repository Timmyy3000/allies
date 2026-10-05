# Generated migration metadata intentionally uses mutable class attributes.
# ruff: noqa: RUF012

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("activities", "0003_approval_activity_approval_and_more")]

    operations = [
        migrations.AddField(
            model_name="approval",
            name="explanation",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]

# ruff: noqa: RUF012

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("runtime", "0013_workspace_activation_claim"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="executionevent",
            name="runtime_event_sequence_positive",
        ),
        migrations.AddConstraint(
            model_name="executionevent",
            constraint=models.CheckConstraint(
                condition=models.Q(sequence__gt=0) & models.Q(sequence__lte=100001),
                name="runtime_event_sequence_positive",
            ),
        ),
    ]

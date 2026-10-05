from typing import ClassVar

from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies: ClassVar = [
        ("runtime", "0016_merge_20260904_0927"),
    ]

    operations: ClassVar = [
        migrations.AddField(
            model_name="executioneventdelivery",
            name="repair_cycle",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddConstraint(
            model_name="executioneventdelivery",
            constraint=models.CheckConstraint(
                condition=Q(repair_cycle__gte=0),
                name="runtime_delivery_repair_cycle_nonnegative",
            ),
        ),
    ]

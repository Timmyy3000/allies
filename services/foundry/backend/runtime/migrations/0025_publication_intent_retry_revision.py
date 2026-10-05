# ruff: noqa: RUF012

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("runtime", "0024_publication_intent")]

    operations = [
        migrations.AddField(
            model_name="publicationintent",
            name="cloud_retry_revision",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        )
    ]

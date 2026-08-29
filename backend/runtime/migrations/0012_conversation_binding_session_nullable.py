from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("runtime", "0011_cld005_gateway"),
    ]

    operations = [
        migrations.AlterField(
            model_name="conversationbinding",
            name="hermes_session_id",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]

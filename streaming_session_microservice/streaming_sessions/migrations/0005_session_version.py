from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("streaming_sessions", "0004_auto_20260913_1152"),
    ]

    operations = [
        migrations.AddField(
            model_name="session",
            name="version",
            field=models.PositiveIntegerField(default=0),
        ),
    ]

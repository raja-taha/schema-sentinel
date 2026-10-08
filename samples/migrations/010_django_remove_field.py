"""Django migration — RemoveField is a drop-column contract break."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0009_previous"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="orders",
            name="status",
        ),
        migrations.AddField(
            model_name="orders",
            name="state",
            field="models.CharField(max_length=32, null=True)",
        ),
    ]

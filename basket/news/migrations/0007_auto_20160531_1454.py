from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("news", "0006_merge"),
    ]

    operations = [
        migrations.AddField(
            model_name="newsletter",
            name="transactional",
            field=models.BooleanField(
                default=False,
                help_text="Whether this newsletter is purely for transactional messaging (e.g. Firefox Mobile download link emails).",
            ),
        ),
        migrations.AlterField(
            model_name="newsletter",
            name="vendor_id",
            field=models.CharField(
                help_text="The backend vendor's identifier for this newsletter",
                max_length=128,
                blank=True,
            ),
        ),
    ]

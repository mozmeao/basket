# -*- coding: utf-8 -*-


from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("news", "0008_auto_20160605_1345"),
    ]

    operations = [
        migrations.CreateModel(
            name="TransactionalEmailMessage",
            fields=[
                (
                    "message_id",
                    models.SlugField(
                        help_text=(
                            b"The ID for the message that will be used by clients"
                        ),
                        serialize=False,
                        primary_key=True,
                    ),
                ),
                (
                    "vendor_id",
                    models.CharField(
                        help_text=b"The backend vendor's identifier for this message",
                        max_length=50,
                    ),
                ),
                (
                    "description",
                    models.CharField(
                        help_text=b"Optional short description of this message",
                        max_length=200,
                        blank=True,
                    ),
                ),
                (
                    "languages",
                    models.CharField(
                        help_text=(
                            b"Comma-separated list of the language codes that this"
                            b" newsletter supports"
                        ),
                        max_length=200,
                    ),
                ),
            ],
        ),
    ]

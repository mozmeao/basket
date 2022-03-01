# -*- coding: utf-8 -*-


from django.db import migrations, models
import django.utils.timezone
import jsonfield.fields


class Migration(migrations.Migration):

    dependencies = [
        ("news", "0003_auto_20151202_0808"),
    ]

    operations = [
        migrations.CreateModel(
            name="QueuedTask",
            fields=[
                (
                    "id",
                    models.AutoField(
                        verbose_name="ID",
                        serialize=False,
                        auto_created=True,
                        primary_key=True,
                    ),
                ),
                (
                    "when",
                    models.DateTimeField(
                        default=django.utils.timezone.now,
                        editable=False,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("args", jsonfield.fields.JSONField(default=[])),
                ("kwargs", jsonfield.fields.JSONField(default={})),
            ],
            options={"ordering": ["pk"]},
        ),
    ]

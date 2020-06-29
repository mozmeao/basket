# -*- coding: utf-8 -*-


from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("news", "0007_auto_20160531_1454"),
    ]

    operations = [
        migrations.AlterField(
            model_name="failedtask",
            name="task_id",
            field=models.CharField(max_length=255),
        ),
    ]

# -*- coding: utf-8 -*-


from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("news", "0010_auto_20160607_0815"),
    ]

    operations = [
        migrations.RemoveField(model_name="newsletter", name="confirm_message"),
        migrations.RemoveField(model_name="newsletter", name="transactional"),
        migrations.RemoveField(model_name="newsletter", name="welcome"),
        migrations.AlterField(
            model_name="newsletter",
            name="vendor_id",
            field=models.CharField(
                help_text=b"The backend vendor's identifier for this newsletter",
                max_length=128,
            ),
        ),
    ]

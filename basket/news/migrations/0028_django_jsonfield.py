# Generated by Django 3.2.19 on 2023-05-16 22:50

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("news", "0027_alter_newsletter_requires_double_optin"),
    ]

    operations = [
        migrations.AlterField(
            model_name="commonvoiceupdate",
            name="data",
            field=models.JSONField(),
        ),
        migrations.AlterField(
            model_name="failedtask",
            name="args",
            field=models.JSONField(default=list),
        ),
        migrations.AlterField(
            model_name="failedtask",
            name="kwargs",
            field=models.JSONField(default=dict),
        ),
        migrations.AlterField(
            model_name="queuedtask",
            name="args",
            field=models.JSONField(default=list),
        ),
        migrations.AlterField(
            model_name="queuedtask",
            name="kwargs",
            field=models.JSONField(default=dict),
        ),
    ]

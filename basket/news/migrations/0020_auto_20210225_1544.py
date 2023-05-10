# Generated by Django 2.2.17 on 2021-02-25 15:44

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("news", "0019_acoustictxemailmessage"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="acoustictxemailmessage",
            options={
                "ordering": ["message_id"],
                "verbose_name": "Acoustic Transact message",
            },
        ),
        migrations.AddField(
            model_name="acoustictxemailmessage",
            name="private",
            field=models.BooleanField(
                default=False,
                help_text="Whether this email is private. Private emails are not allowed to be sent via the normal API.",
            ),
        ),
    ]

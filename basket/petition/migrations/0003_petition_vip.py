# Generated by Django 3.2.22 on 2023-11-08 18:15

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("petition", "0002_petition_tweaks"),
    ]

    operations = [
        migrations.AddField(
            model_name="petition",
            name="vip",
            field=models.BooleanField(default=False),
        ),
    ]

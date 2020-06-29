# -*- coding: utf-8 -*-


from django.db import migrations


def convert_transactionals(apps, schema_editor):
    Newsletter = apps.get_model("news", "Newsletter")
    TransactionalEmailMessage = apps.get_model("news", "TransactionalEmailMessage")
    for nl in Newsletter.objects.filter(transactional=True):
        TransactionalEmailMessage.objects.create(
            message_id=nl.slug,
            vendor_id=nl.welcome,
            languages=nl.languages,
            description=nl.description,
        )
        nl.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("news", "0009_transactionalemailmessage"),
    ]

    operations = [
        migrations.RunPython(convert_transactionals),
    ]

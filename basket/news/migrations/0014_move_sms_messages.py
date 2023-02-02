# -*- coding: utf-8 -*-


from django.db import migrations


def move_sms_messages(apps, schema_editor):
    SMSMessage = apps.get_model("news", "SMSMessage")
    LocalizedSMSMessage = apps.get_model("news", "LocalizedSMSMessage")
    for sms in SMSMessage.objects.all():
        LocalizedSMSMessage.objects.create(
            message_id=sms.message_id,
            vendor_id=sms.vendor_id,
            description=sms.description,
            language="en-US",
            country="us",
        )


class Migration(migrations.Migration):
    dependencies = [
        ("news", "0013_auto_20170907_1216"),
    ]

    operations = [
        migrations.RunPython(move_sms_messages),
    ]

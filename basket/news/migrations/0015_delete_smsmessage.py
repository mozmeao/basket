# -*- coding: utf-8 -*-


from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('news', '0014_move_sms_messages'),
    ]

    operations = [
        migrations.DeleteModel(
            name='SMSMessage',
        ),
    ]

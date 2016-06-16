# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations


FIELD_MAP = {
    'ABOUT_MOBILE': 'Interest_Android__c',
    'ABOUT_MOZILLA': 'Sub_About_Mozilla__c',
    'APP_DEV': 'Sub_Apps_And_Hacks__c',
    'CONNECTED_DEVICES': 'Sub_Connected_Devices__c',
    'DEV_EVENTS': 'Sub_Dev_Events__c',
    'FIREFOX_ACCOUNTS_JOURNEY': 'Sub_Firefox_Accounts_Journey__c',
    'FIREFOX_DESKTOP': 'Interest_Firefox_Desktop__c',
    'FIREFOX_FRIENDS': 'Sub_Firefox_Friends__c',
    'FIREFOX_IOS': 'Interest_Firefox_iOS__c',
    'FOUNDATION': 'Sub_Mozilla_Foundation__c',
    'GAMEDEV_CONF': 'Sub_Game_Dev_Conference__c',
    'GET_INVOLVED': 'Sub_Get_Involved__c',
    'MAKER_PARTY': 'Sub_Maker_Party__c',
    'MOZFEST': 'Sub_Mozilla_Festival__c',
    'MOZILLA_AND_YOU': 'Sub_Firefox_And_You__c',
    'MOZILLA_GENERAL': 'Interest_Mozilla__c',
    'MOZILLA_PHONE': 'Sub_Mozillans__c',
    'MOZ_LEARN': 'Sub_Mozilla_Learning_Network__c',
    'SHAPE_WEB': 'Sub_Shape_Of_The_Web__c',
    'STUDENT_AMBASSADORS': 'Sub_Student_Ambassador__c',
    'VIEW_SOURCE_GLOBAL': 'Sub_View_Source_Global__c',
    'VIEW_SOURCE_NA': 'Sub_View_Source_NAmerica__c',
    'WEBMAKER': 'Sub_Webmaker__c',
    'TEST_PILOT': 'Sub_Test_Pilot__c',
    'IOS_TEST_FLIGHT': 'Sub_Test_Flight__c',
}


def convert_vendor_id(apps, schema_editor):
    Newsletter = apps.get_model('news', 'Newsletter')
    for nl in Newsletter.objects.all():
        if nl.vendor_id in FIELD_MAP:
            nl.vendor_id = FIELD_MAP[nl.vendor_id]
            nl.save()


class Migration(migrations.Migration):

    dependencies = [
        ('news', '0003_auto_20151202_0808'),
    ]

    operations = [
        migrations.RunPython(convert_vendor_id),
    ]

# -*- coding: utf-8 -*-
import datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models


class Migration(SchemaMigration):

    def forwards(self, orm):
        # Adding model 'LocaleStewards'
        db.create_table(u'news_localestewards', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('interest', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['news.Interest'])),
            ('locale', self.gf('news.fields.LocaleField')(max_length=32)),
            ('emails', self.gf('news.fields.CommaSeparatedEmailField')()),
        ))
        db.send_create_signal(u'news', ['LocaleStewards'])

        # Adding unique constraint on 'LocaleStewards', fields ['interest', 'locale']
        db.create_unique(u'news_localestewards', ['interest_id', 'locale'])

        # Renaming field 'Interest.steward_emails'
        db.rename_column(u'news_interest', 'steward_emails', 'default_steward_emails')


    def backwards(self, orm):
        # Removing unique constraint on 'LocaleStewards', fields ['interest', 'locale']
        db.delete_unique(u'news_localestewards', ['interest_id', 'locale'])

        # Deleting model 'LocaleStewards'
        db.delete_table(u'news_localestewards')

        # Renaming field 'Interest.default_steward_emails'
        db.rename_column(u'news_interest', 'default_steward_emails', 'steward_emails')


    models = {
        u'news.apiuser': {
            'Meta': {'object_name': 'APIUser'},
            'api_key': ('django.db.models.fields.CharField', [], {'default': "'b00db0d0-98a6-402e-a149-8627184dd33e'", 'max_length': '40', 'db_index': 'True'}),
            'enabled': ('django.db.models.fields.BooleanField', [], {'default': 'True'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '256'})
        },
        u'news.failedtask': {
            'Meta': {'object_name': 'FailedTask'},
            'args': ('jsonfield.fields.JSONField', [], {'default': '[]'}),
            'einfo': ('django.db.models.fields.TextField', [], {'default': 'None', 'null': 'True'}),
            'exc': ('django.db.models.fields.TextField', [], {'default': 'None', 'null': 'True'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'kwargs': ('jsonfield.fields.JSONField', [], {'default': '{}'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '255'}),
            'task_id': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '255'}),
            'when': ('django.db.models.fields.DateTimeField', [], {'default': 'datetime.datetime.now'})
        },
        u'news.interest': {
            'Meta': {'object_name': 'Interest'},
            '_welcome_id': ('django.db.models.fields.CharField', [], {'max_length': '64', 'blank': 'True'}),
            'default_steward_emails': ('news.fields.CommaSeparatedEmailField', [], {'blank': 'True'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'interest_id': ('django.db.models.fields.SlugField', [], {'unique': 'True', 'max_length': '50'}),
            'title': ('django.db.models.fields.CharField', [], {'max_length': '128'})
        },
        u'news.localestewards': {
            'Meta': {'unique_together': "(('interest', 'locale'),)", 'object_name': 'LocaleStewards'},
            'emails': ('news.fields.CommaSeparatedEmailField', [], {}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'interest': ('django.db.models.fields.related.ForeignKey', [], {'to': u"orm['news.Interest']"}),
            'locale': ('news.fields.LocaleField', [], {'max_length': '32'})
        },
        u'news.newsletter': {
            'Meta': {'ordering': "['order']", 'object_name': 'Newsletter'},
            'active': ('django.db.models.fields.BooleanField', [], {'default': 'True'}),
            'confirm_message': ('django.db.models.fields.CharField', [], {'max_length': '64', 'blank': 'True'}),
            'description': ('django.db.models.fields.CharField', [], {'max_length': '256', 'blank': 'True'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'languages': ('django.db.models.fields.CharField', [], {'max_length': '200'}),
            'order': ('django.db.models.fields.IntegerField', [], {'default': '0'}),
            'requires_double_optin': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'show': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'slug': ('django.db.models.fields.SlugField', [], {'unique': 'True', 'max_length': '50'}),
            'title': ('django.db.models.fields.CharField', [], {'max_length': '128'}),
            'vendor_id': ('django.db.models.fields.CharField', [], {'max_length': '128'}),
            'welcome': ('django.db.models.fields.CharField', [], {'max_length': '64', 'blank': 'True'})
        },
        u'news.subscriber': {
            'Meta': {'object_name': 'Subscriber'},
            'email': ('django.db.models.fields.EmailField', [], {'max_length': '75', 'primary_key': 'True'}),
            'fxa_id': ('django.db.models.fields.CharField', [], {'db_index': 'True', 'max_length': '100', 'null': 'True', 'blank': 'True'}),
            'token': ('django.db.models.fields.CharField', [], {'default': "'740188d2-4d22-4ab6-94cf-17710b8f1e4a'", 'max_length': '40', 'db_index': 'True'})
        }
    }

    complete_apps = ['news']

# -*- coding: utf-8 -*-
import datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models


class Migration(SchemaMigration):

    def forwards(self, orm):
        # Adding field 'Subscriber.fxa_id'
        db.add_column(u'news_subscriber', 'fxa_id',
                      self.gf('django.db.models.fields.CharField')(db_index=True, max_length=100, null=True, blank=True),
                      keep_default=False)


    def backwards(self, orm):
        # Deleting field 'Subscriber.fxa_id'
        db.delete_column(u'news_subscriber', 'fxa_id')


    models = {
        u'news.apiuser': {
            'Meta': {'object_name': 'APIUser'},
            'api_key': ('django.db.models.fields.CharField', [], {'default': "'c17bac3d-1abd-4d6c-801e-866671c77dfd'", 'max_length': '40', 'db_index': 'True'}),
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
            'token': ('django.db.models.fields.CharField', [], {'default': "'b498d69d-441a-46fa-818d-faa447a5acd1'", 'max_length': '40', 'db_index': 'True'})
        }
    }

    complete_apps = ['news']
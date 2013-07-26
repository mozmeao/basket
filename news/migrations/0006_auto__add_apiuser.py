# -*- coding: utf-8 -*-
import datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models


class Migration(SchemaMigration):

    def forwards(self, orm):
        # Adding model 'APIUser'
        db.create_table('news_apiuser', (
            ('id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('name', self.gf('django.db.models.fields.CharField')(max_length=256)),
            ('api_key', self.gf('django.db.models.fields.CharField')(default='fa8347f2-14fe-45db-a62f-4d6e4d88b62e', max_length=40, db_index=True)),
            ('enabled', self.gf('django.db.models.fields.BooleanField')(default=True)),
        ))
        db.send_create_signal('news', ['APIUser'])


    def backwards(self, orm):
        # Deleting model 'APIUser'
        db.delete_table('news_apiuser')


    models = {
        'news.apiuser': {
            'Meta': {'object_name': 'APIUser'},
            'api_key': ('django.db.models.fields.CharField', [], {'default': "'e420aec3-106f-4b17-9126-43a1356504d8'", 'max_length': '40', 'db_index': 'True'}),
            'enabled': ('django.db.models.fields.BooleanField', [], {'default': 'True'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '256'})
        },
        'news.newsletter': {
            'Meta': {'ordering': "['order']", 'object_name': 'Newsletter'},
            'active': ('django.db.models.fields.BooleanField', [], {'default': 'True'}),
            'confirm_message': ('django.db.models.fields.CharField', [], {'max_length': '64', 'blank': 'True'}),
            'description': ('django.db.models.fields.CharField', [], {'max_length': '256', 'blank': 'True'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'languages': ('django.db.models.fields.CharField', [], {'max_length': '200'}),
            'order': ('django.db.models.fields.IntegerField', [], {'default': '0'}),
            'requires_double_optin': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'show': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'slug': ('django.db.models.fields.SlugField', [], {'unique': 'True', 'max_length': '50'}),
            'title': ('django.db.models.fields.CharField', [], {'max_length': '128'}),
            'vendor_id': ('django.db.models.fields.CharField', [], {'max_length': '128'}),
            'welcome': ('django.db.models.fields.CharField', [], {'max_length': '64', 'blank': 'True'})
        },
        'news.subscriber': {
            'Meta': {'object_name': 'Subscriber'},
            'email': ('django.db.models.fields.EmailField', [], {'max_length': '75', 'primary_key': 'True'}),
            'token': ('django.db.models.fields.CharField', [], {'default': "'f02e8016-94e3-49be-8cd0-8dfa0d0fb5f9'", 'max_length': '40', 'db_index': 'True'})
        }
    }

    complete_apps = ['news']
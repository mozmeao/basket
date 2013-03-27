# -*- coding: utf-8 -*-
import datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models


class Migration(SchemaMigration):

    def forwards(self, orm):
        # Changing field 'Subscriber.token'
        db.alter_column('news_subscriber', 'token', self.gf('django.db.models.fields.CharField')(max_length=40))
        # Adding index on 'Subscriber', fields ['token']
        db.create_index('news_subscriber', ['token'])


    def backwards(self, orm):
        # Removing index on 'Subscriber', fields ['token']
        db.delete_index('news_subscriber', ['token'])
        # Changing field 'Subscriber.token'
        db.alter_column('news_subscriber', 'token', self.gf('django.db.models.fields.CharField')(max_length=1024))


    models = {
        'news.newsletter': {
            'Meta': {'object_name': 'Newsletter'},
            'active': ('django.db.models.fields.BooleanField', [], {'default': 'True'}),
            'description': ('django.db.models.fields.CharField', [], {'max_length': '256', 'blank': 'True'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'languages': ('django.db.models.fields.CharField', [], {'max_length': '200'}),
            'show': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'slug': ('django.db.models.fields.SlugField', [], {'unique': 'True', 'max_length': '50'}),
            'title': ('django.db.models.fields.CharField', [], {'max_length': '128'}),
            'vendor_id': ('django.db.models.fields.CharField', [], {'max_length': '128'}),
            'welcome': ('django.db.models.fields.CharField', [], {'max_length': '64', 'blank': 'True'})
        },
        'news.subscriber': {
            'Meta': {'object_name': 'Subscriber'},
            'email': ('django.db.models.fields.EmailField', [], {'max_length': '75', 'primary_key': 'True'}),
            'token': ('django.db.models.fields.CharField', [], {'default': "'9101c0ce-cac8-4cf4-8126-22df89512f32'", 'max_length': '40', 'db_index': 'True'})
        }
    }

    complete_apps = ['news']

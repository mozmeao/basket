# -*- coding: utf-8 -*-
import datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models


class Migration(SchemaMigration):

    def forwards(self, orm):
        # Adding field 'Newsletter.requires_double_optin'
        db.add_column('news_newsletter', 'requires_double_optin',
                      self.gf('django.db.models.fields.BooleanField')(default=False),
                      keep_default=False)


    def backwards(self, orm):
        # Deleting field 'Newsletter.requires_double_optin'
        db.delete_column('news_newsletter', 'requires_double_optin')


    models = {
        'news.newsletter': {
            'Meta': {'object_name': 'Newsletter'},
            'active': ('django.db.models.fields.BooleanField', [], {'default': 'True'}),
            'description': ('django.db.models.fields.CharField', [], {'max_length': '256', 'blank': 'True'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'languages': ('django.db.models.fields.CharField', [], {'max_length': '200'}),
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
            'token': ('django.db.models.fields.CharField', [], {'default': "'0b1108ee-4a68-48b3-9481-3e81ec586f9e'", 'max_length': '40', 'db_index': 'True'})
        }
    }

    complete_apps = ['news']

# -*- coding: utf-8 -*-
import datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models


class Migration(SchemaMigration):

    def forwards(self, orm):
        # Adding model 'Subscriber'
        db.create_table('news_subscriber', (
            ('email', self.gf('django.db.models.fields.EmailField')(max_length=75, primary_key=True)),
            ('token', self.gf('django.db.models.fields.CharField')(default='b2b2a68b-202e-4519-a39d-e854ff09afd2', max_length=1024)),
        ))
        db.send_create_signal('news', ['Subscriber'])

        # Adding model 'Newsletter'
        db.create_table('news_newsletter', (
            ('id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('slug', self.gf('django.db.models.fields.SlugField')(unique=True, max_length=50)),
            ('title', self.gf('django.db.models.fields.CharField')(max_length=128)),
            ('description', self.gf('django.db.models.fields.CharField')(max_length=256, blank=True)),
            ('show', self.gf('django.db.models.fields.BooleanField')(default=False)),
            ('active', self.gf('django.db.models.fields.BooleanField')(default=True)),
            ('welcome', self.gf('django.db.models.fields.CharField')(max_length=64, blank=True)),
            ('vendor_id', self.gf('django.db.models.fields.CharField')(max_length=128)),
            ('languages', self.gf('django.db.models.fields.CharField')(max_length=200)),
        ))
        db.send_create_signal('news', ['Newsletter'])


    def backwards(self, orm):
        # Deleting model 'Subscriber'
        db.delete_table('news_subscriber')

        # Deleting model 'Newsletter'
        db.delete_table('news_newsletter')


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
            'token': ('django.db.models.fields.CharField', [], {'default': "'010e36cf-41b8-49e9-ac75-0b081b80f477'", 'max_length': '1024'})
        }
    }

    complete_apps = ['news']
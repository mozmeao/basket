# -*- coding: utf-8 -*-
import datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models


class Migration(SchemaMigration):

    def forwards(self, orm):
        # Adding model 'BlockedEmail'
        db.create_table(u'news_blockedemail', (
            (u'id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('email_domain', self.gf('django.db.models.fields.CharField')(max_length=50)),
        ))
        db.send_create_signal(u'news', ['BlockedEmail'])


    def backwards(self, orm):
        # Deleting model 'BlockedEmail'
        db.delete_table(u'news_blockedemail')


    models = {
        u'news.apiuser': {
            'Meta': {'object_name': 'APIUser'},
            'api_key': ('django.db.models.fields.CharField', [], {'default': "'d637403e-2efb-4300-9f26-e352d82dc106'", 'max_length': '40', 'db_index': 'True'}),
            'enabled': ('django.db.models.fields.BooleanField', [], {'default': 'True'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '256'})
        },
        u'news.blockedemail': {
            'Meta': {'object_name': 'BlockedEmail'},
            'email_domain': ('django.db.models.fields.CharField', [], {'max_length': '50'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'})
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
        u'news.newslettergroup': {
            'Meta': {'object_name': 'NewsletterGroup'},
            'active': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'description': ('django.db.models.fields.CharField', [], {'max_length': '256', 'blank': 'True'}),
            u'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'newsletters': ('django.db.models.fields.related.ManyToManyField', [], {'related_name': "'newsletter_groups'", 'symmetrical': 'False', 'to': u"orm['news.Newsletter']"}),
            'show': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'slug': ('django.db.models.fields.SlugField', [], {'unique': 'True', 'max_length': '50'}),
            'title': ('django.db.models.fields.CharField', [], {'max_length': '128'})
        },
        u'news.subscriber': {
            'Meta': {'object_name': 'Subscriber'},
            'email': ('django.db.models.fields.EmailField', [], {'max_length': '75', 'primary_key': 'True'}),
            'fxa_id': ('django.db.models.fields.CharField', [], {'db_index': 'True', 'max_length': '100', 'null': 'True', 'blank': 'True'}),
            'token': ('django.db.models.fields.CharField', [], {'default': "'f7e6b06b-17cd-46f1-bb17-18c7fe489792'", 'max_length': '40', 'db_index': 'True'})
        }
    }

    complete_apps = ['news']
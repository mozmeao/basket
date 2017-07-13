# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
import jsonfield.fields
import basket.news.models
import basket.news.fields
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='APIUser',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('name', models.CharField(help_text=b'Descriptive name of this user', max_length=256)),
                ('api_key', models.CharField(default=basket.news.models.get_uuid, max_length=40, db_index=True)),
                ('enabled', models.BooleanField(default=True)),
            ],
            options={
                'verbose_name': 'API User',
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='BlockedEmail',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('email_domain', models.CharField(max_length=50)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='FailedTask',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('when', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('task_id', models.CharField(unique=True, max_length=255)),
                ('name', models.CharField(max_length=255)),
                ('args', jsonfield.fields.JSONField(default=[])),
                ('kwargs', jsonfield.fields.JSONField(default={})),
                ('exc', models.TextField(default=None, help_text='repr(exception)', null=True)),
                ('einfo', models.TextField(default=None, help_text='repr(einfo)', null=True)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='Interest',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('title', models.CharField(help_text=b'Public name of interest in English', max_length=128)),
                ('interest_id', models.SlugField(help_text=b'The ID for the interest that will be used by clients', unique=True)),
                ('_welcome_id', models.CharField(help_text=b'The ID of the welcome message sent for this interest. This is the HTML version of the message; append _T to this ID to get the ID of the text-only version.  If blank, welcome message ID will be assumed to be the same as the interest_id', max_length=64, verbose_name=b'Welcome ID', blank=True)),
                ('default_steward_emails', basket.news.fields.CommaSeparatedEmailField(help_text=b"Comma-separated list of the default / en-US stewards' email addresses.", verbose_name=b'Default / en-US Steward Emails', blank=True)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='LocaleStewards',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('locale', basket.news.fields.LocaleField(max_length=32, choices=[('ach', 'ach (Acholi)'), ('af', 'af (Afrikaans)'), ('ak', 'ak (Akan)'), ('am-et', 'am-et (Amharic)'), ('an', 'an (Aragonese)'), ('ar', 'ar (Arabic)'), ('as', 'as (Assamese)'), ('ast', 'ast (Asturian)'), ('az', 'az (Azerbaijani)'), ('be', 'be (Belarusian)'), ('bg', 'bg (Bulgarian)'), ('bn-BD', 'bn-BD (Bengali (Bangladesh))'), ('bn-IN', 'bn-IN (Bengali (India))'), ('br', 'br (Breton)'), ('bs', 'bs (Bosnian)'), ('ca', 'ca (Catalan)'), ('ca-valencia', 'ca-valencia (Catalan (Valencian))'), ('cs', 'cs (Czech)'), ('csb', 'csb (Kashubian)'), ('cy', 'cy (Welsh)'), ('da', 'da (Danish)'), ('dbg', 'dbg (Debug Robot)'), ('de', 'de (German)'), ('de-AT', 'de-AT (German (Austria))'), ('de-CH', 'de-CH (German (Switzerland))'), ('de-DE', 'de-DE (German (Germany))'), ('dsb', 'dsb (Lower Sorbian)'), ('el', 'el (Greek)'), ('en-AU', 'en-AU (English (Australian))'), ('en-CA', 'en-CA (English (Canadian))'), ('en-GB', 'en-GB (English (British))'), ('en-NZ', 'en-NZ (English (New Zealand))'), ('en-US', 'en-US (English (US))'), ('en-ZA', 'en-ZA (English (South African))'), ('eo', 'eo (Esperanto)'), ('es', 'es (Spanish)'), ('es-AR', 'es-AR (Spanish (Argentina))'), ('es-CL', 'es-CL (Spanish (Chile))'), ('es-ES', 'es-ES (Spanish (Spain))'), ('es-MX', 'es-MX (Spanish (Mexico))'), ('et', 'et (Estonian)'), ('eu', 'eu (Basque)'), ('fa', 'fa (Persian)'), ('ff', 'ff (Fulah)'), ('fi', 'fi (Finnish)'), ('fj-FJ', 'fj-FJ (Fijian)'), ('fr', 'fr (French)'), ('fur-IT', 'fur-IT (Friulian)'), ('fy-NL', 'fy-NL (Frisian)'), ('ga', 'ga (Irish)'), ('ga-IE', 'ga-IE (Irish)'), ('gd', 'gd (Gaelic (Scotland))'), ('gl', 'gl (Galician)'), ('gu', 'gu (Gujarati)'), ('gu-IN', 'gu-IN (Gujarati (India))'), ('he', 'he (Hebrew)'), ('hi', 'hi (Hindi)'), ('hi-IN', 'hi-IN (Hindi (India))'), ('hr', 'hr (Croatian)'), ('hsb', 'hsb (Upper Sorbian)'), ('hu', 'hu (Hungarian)'), ('hy-AM', 'hy-AM (Armenian)'), ('id', 'id (Indonesian)'), ('is', 'is (Icelandic)'), ('it', 'it (Italian)'), ('ja', 'ja (Japanese)'), ('ja-JP-mac', 'ja-JP-mac (Japanese)'), ('ka', 'ka (Georgian)'), ('kk', 'kk (Kazakh)'), ('km', 'km (Khmer)'), ('kn', 'kn (Kannada)'), ('ko', 'ko (Korean)'), ('ku', 'ku (Kurdish)'), ('la', 'la (Latin)'), ('lg', 'lg (Luganda)'), ('lij', 'lij (Ligurian)'), ('lo', 'lo (Lao)'), ('lt', 'lt (Lithuanian)'), ('lv', 'lv (Latvian)'), ('mai', 'mai (Maithili)'), ('mg', 'mg (Malagasy)'), ('mi', 'mi (Maori (Aotearoa))'), ('mk', 'mk (Macedonian)'), ('ml', 'ml (Malayalam)'), ('mn', 'mn (Mongolian)'), ('mr', 'mr (Marathi)'), ('ms', 'ms (Malay)'), ('my', 'my (Burmese)'), ('nb-NO', 'nb-NO (Norwegian (Bokm\xe5l))'), ('ne-NP', 'ne-NP (Nepali)'), ('nl', 'nl (Dutch)'), ('nn-NO', 'nn-NO (Norwegian (Nynorsk))'), ('nr', 'nr (Ndebele, South)'), ('nso', 'nso (Northern Sotho)'), ('oc', 'oc (Occitan (Lengadocian))'), ('or', 'or (Oriya)'), ('pa', 'pa (Punjabi)'), ('pa-IN', 'pa-IN (Punjabi (India))'), ('pl', 'pl (Polish)'), ('pt-BR', 'pt-BR (Portuguese (Brazilian))'), ('pt-PT', 'pt-PT (Portuguese (Portugal))'), ('rm', 'rm (Romansh)'), ('ro', 'ro (Romanian)'), ('ru', 'ru (Russian)'), ('rw', 'rw (Kinyarwanda)'), ('sa', 'sa (Sanskrit)'), ('sah', 'sah (Sakha)'), ('si', 'si (Sinhala)'), ('sk', 'sk (Slovak)'), ('sl', 'sl (Slovenian)'), ('son', 'son (Songhai)'), ('sq', 'sq (Albanian)'), ('sr', 'sr (Serbian)'), ('sr-Cyrl', 'sr-Cyrl (Serbian)'), ('sr-Latn', 'sr-Latn (Serbian)'), ('ss', 'ss (Siswati)'), ('st', 'st (Southern Sotho)'), ('sv-SE', 'sv-SE (Swedish)'), ('sw', 'sw (Swahili)'), ('ta', 'ta (Tamil)'), ('ta-IN', 'ta-IN (Tamil (India))'), ('ta-LK', 'ta-LK (Tamil (Sri Lanka))'), ('te', 'te (Telugu)'), ('th', 'th (Thai)'), ('tn', 'tn (Tswana)'), ('tr', 'tr (Turkish)'), ('ts', 'ts (Tsonga)'), ('tt-RU', 'tt-RU (Tatar)'), ('uk', 'uk (Ukrainian)'), ('ur', 'ur (Urdu)'), ('uz', 'uz (Uzbek)'), ('ve', 've (Venda)'), ('vi', 'vi (Vietnamese)'), ('wo', 'wo (Wolof)'), ('x-testing', 'x-testing (Testing)'), ('xh', 'xh (Xhosa)'), ('zh-CN', 'zh-CN (Chinese (Simplified))'), ('zh-TW', 'zh-TW (Chinese (Traditional))'), ('zu', 'zu (Zulu)')])),
                ('emails', basket.news.fields.CommaSeparatedEmailField(help_text=b"Comma-separated list of the stewards' email addresses.")),
                ('interest', models.ForeignKey(to='news.Interest')),
            ],
            options={
                'verbose_name': 'Locale Steward',
                'verbose_name_plural': 'Locale Stewards',
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='Newsletter',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('slug', models.SlugField(help_text=b'The ID for the newsletter that will be used by clients', unique=True)),
                ('title', models.CharField(help_text=b'Public name of newsletter in English', max_length=128)),
                ('description', models.CharField(help_text=b'One-line description of newsletter in English', max_length=256, blank=True)),
                ('show', models.BooleanField(default=False, help_text=b'Whether to show this newsletter in lists of newsletters, even to non-subscribers')),
                ('active', models.BooleanField(default=True, help_text=b'Whether this newsletter is active. Inactive newsletters are only shown to those who are already subscribed, and might have other differences in behavior.')),
                ('welcome', models.CharField(help_text=b'The ID of the welcome message sent for this newsletter. This is the HTML version of the message; append _T to this ID to get the ID of the text-only version.  If blank, no welcome is sent', max_length=64, blank=True)),
                ('vendor_id', models.CharField(help_text=b"The backend vendor's identifier for this newsletter", max_length=128)),
                ('languages', models.CharField(help_text=b'Comma-separated list of the language codes that this newsletter supports', max_length=200)),
                ('requires_double_optin', models.BooleanField(default=False, help_text=b'True if subscribing to this newsletter requires someoneto respond to a confirming email.')),
                ('order', models.IntegerField(default=0, help_text=b'Order to display the newsletters on the web site. Newsletters with lower order numbers will display first.')),
                ('confirm_message', models.CharField(help_text=b"The ID of the confirm message sent for this newsletter.That's the one that says 'please click here to confirm'.If blank, a default message based on the user's language is sent.", max_length=64, blank=True)),
            ],
            options={
                'ordering': ['order'],
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='NewsletterGroup',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('slug', models.SlugField(help_text=b'The ID for the group that will be used by clients', unique=True)),
                ('title', models.CharField(help_text=b'Public name of group in English', max_length=128)),
                ('description', models.CharField(help_text=b'One-line description of group in English', max_length=256, blank=True)),
                ('show', models.BooleanField(default=False, help_text=b'Whether to show this group in lists of newsletters and groups, even to non-subscribers')),
                ('active', models.BooleanField(default=False, help_text=b'Whether this group should be considered when subscription requests are received.')),
                ('newsletters', models.ManyToManyField(related_name='newsletter_groups', to='news.Newsletter')),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='SMSMessage',
            fields=[
                ('message_id', models.SlugField(help_text=b'The ID for the message that will be used by clients', serialize=False, primary_key=True)),
                ('vendor_id', models.CharField(help_text=b"The backend vendor's identifier for this message", max_length=50)),
                ('description', models.CharField(help_text=b'Optional short description of this message', max_length=200, blank=True)),
            ],
            options={
                'verbose_name': 'SMS message',
            },
            bases=(models.Model,),
        ),
        migrations.CreateModel(
            name='Subscriber',
            fields=[
                ('email', models.EmailField(max_length=75, serialize=False, primary_key=True)),
                ('token', models.CharField(default=basket.news.models.get_uuid, max_length=40, db_index=True)),
                ('fxa_id', models.CharField(db_index=True, max_length=100, null=True, blank=True)),
            ],
            options={
            },
            bases=(models.Model,),
        ),
        migrations.AlterUniqueTogether(
            name='localestewards',
            unique_together=set([('interest', 'locale')]),
        ),
    ]

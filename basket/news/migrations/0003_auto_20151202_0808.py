# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations
import basket.news.fields


class Migration(migrations.Migration):

    dependencies = [
        ('news', '0002_delete_subscriber'),
    ]

    operations = [
        migrations.AddField(
            model_name='newsletter',
            name='private',
            field=models.BooleanField(default=False, help_text=b'Whether this newsletter is private. Private newsletters require the subscribe requests to use an API key.'),
            preserve_default=True,
        ),
        migrations.AlterField(
            model_name='localestewards',
            name='locale',
            field=basket.news.fields.LocaleField(max_length=32, choices=[('ach', 'ach (Acholi)'), ('af', 'af (Afrikaans)'), ('ak', 'ak (Akan)'), ('am-et', 'am-et (Amharic)'), ('an', 'an (Aragonese)'), ('ar', 'ar (Arabic)'), ('as', 'as (Assamese)'), ('ast', 'ast (Asturian)'), ('az', 'az (Azerbaijani)'), ('be', 'be (Belarusian)'), ('bg', 'bg (Bulgarian)'), ('bm', 'bm (Bambara)'), ('bn-BD', 'bn-BD (Bengali (Bangladesh))'), ('bn-IN', 'bn-IN (Bengali (India))'), ('br', 'br (Breton)'), ('brx', 'brx (Bodo)'), ('bs', 'bs (Bosnian)'), ('ca', 'ca (Catalan)'), ('ca-valencia', 'ca-valencia (Catalan (Valencian))'), ('cak', 'cak (Kaqchikel)'), ('cs', 'cs (Czech)'), ('csb', 'csb (Kashubian)'), ('cy', 'cy (Welsh)'), ('da', 'da (Danish)'), ('dbg', 'dbg (Debug Robot)'), ('de', 'de (German)'), ('de-AT', 'de-AT (German (Austria))'), ('de-CH', 'de-CH (German (Switzerland))'), ('de-DE', 'de-DE (German (Germany))'), ('dsb', 'dsb (Lower Sorbian)'), ('ee', 'ee (Ewe)'), ('el', 'el (Greek)'), ('en-AU', 'en-AU (English (Australian))'), ('en-CA', 'en-CA (English (Canadian))'), ('en-GB', 'en-GB (English (British))'), ('en-NZ', 'en-NZ (English (New Zealand))'), ('en-US', 'en-US (English (US))'), ('en-ZA', 'en-ZA (English (South African))'), ('eo', 'eo (Esperanto)'), ('es', 'es (Spanish)'), ('es-AR', 'es-AR (Spanish (Argentina))'), ('es-CL', 'es-CL (Spanish (Chile))'), ('es-ES', 'es-ES (Spanish (Spain))'), ('es-MX', 'es-MX (Spanish (Mexico))'), ('et', 'et (Estonian)'), ('eu', 'eu (Basque)'), ('fa', 'fa (Persian)'), ('ff', 'ff (Fulah)'), ('fi', 'fi (Finnish)'), ('fj-FJ', 'fj-FJ (Fijian)'), ('fr', 'fr (French)'), ('fur-IT', 'fur-IT (Friulian)'), ('fy-NL', 'fy-NL (Frisian)'), ('ga', 'ga (Irish)'), ('ga-IE', 'ga-IE (Irish)'), ('gd', 'gd (Gaelic (Scotland))'), ('gl', 'gl (Galician)'), ('gu', 'gu (Gujarati)'), ('gu-IN', 'gu-IN (Gujarati (India))'), ('ha', 'ha (Hausa)'), ('he', 'he (Hebrew)'), ('hi', 'hi (Hindi)'), ('hi-IN', 'hi-IN (Hindi (India))'), ('hr', 'hr (Croatian)'), ('hsb', 'hsb (Upper Sorbian)'), ('hu', 'hu (Hungarian)'), ('hy-AM', 'hy-AM (Armenian)'), ('id', 'id (Indonesian)'), ('ig', 'ig (Igbo)'), ('is', 'is (Icelandic)'), ('it', 'it (Italian)'), ('ja', 'ja (Japanese)'), ('ja-JP-mac', 'ja-JP-mac (Japanese)'), ('ka', 'ka (Georgian)'), ('kk', 'kk (Kazakh)'), ('km', 'km (Khmer)'), ('kn', 'kn (Kannada)'), ('ko', 'ko (Korean)'), ('kok', 'kok (Konkani)'), ('ks', 'ks (Kashmiri)'), ('ku', 'ku (Kurdish)'), ('la', 'la (Latin)'), ('lg', 'lg (Luganda)'), ('lij', 'lij (Ligurian)'), ('ln', 'ln (Lingala)'), ('lo', 'lo (Lao)'), ('lt', 'lt (Lithuanian)'), ('lv', 'lv (Latvian)'), ('mai', 'mai (Maithili)'), ('mg', 'mg (Malagasy)'), ('mi', 'mi (Maori (Aotearoa))'), ('mk', 'mk (Macedonian)'), ('ml', 'ml (Malayalam)'), ('mn', 'mn (Mongolian)'), ('mr', 'mr (Marathi)'), ('ms', 'ms (Malay)'), ('my', 'my (Burmese)'), ('nb-NO', 'nb-NO (Norwegian (Bokm\xe5l))'), ('ne-NP', 'ne-NP (Nepali)'), ('nl', 'nl (Dutch)'), ('nn-NO', 'nn-NO (Norwegian (Nynorsk))'), ('nr', 'nr (Ndebele, South)'), ('nso', 'nso (Northern Sotho)'), ('oc', 'oc (Occitan (Lengadocian))'), ('or', 'or (Oriya)'), ('pa', 'pa (Punjabi)'), ('pa-IN', 'pa-IN (Punjabi (India))'), ('pl', 'pl (Polish)'), ('pt-BR', 'pt-BR (Portuguese (Brazilian))'), ('pt-PT', 'pt-PT (Portuguese (Portugal))'), ('rm', 'rm (Romansh)'), ('ro', 'ro (Romanian)'), ('ru', 'ru (Russian)'), ('rw', 'rw (Kinyarwanda)'), ('sa', 'sa (Sanskrit)'), ('sah', 'sah (Sakha)'), ('sat', 'sat (Santali)'), ('si', 'si (Sinhala)'), ('sk', 'sk (Slovak)'), ('sl', 'sl (Slovenian)'), ('son', 'son (Songhai)'), ('sq', 'sq (Albanian)'), ('sr', 'sr (Serbian)'), ('sr-Cyrl', 'sr-Cyrl (Serbian)'), ('sr-Latn', 'sr-Latn (Serbian)'), ('ss', 'ss (Siswati)'), ('st', 'st (Southern Sotho)'), ('sv-SE', 'sv-SE (Swedish)'), ('sw', 'sw (Swahili)'), ('ta', 'ta (Tamil)'), ('ta-IN', 'ta-IN (Tamil (India))'), ('ta-LK', 'ta-LK (Tamil (Sri Lanka))'), ('te', 'te (Telugu)'), ('th', 'th (Thai)'), ('tl', 'tl (Tagalog)'), ('tn', 'tn (Tswana)'), ('tr', 'tr (Turkish)'), ('ts', 'ts (Tsonga)'), ('tsz', 'tsz (Pur\xe9pecha)'), ('tt-RU', 'tt-RU (Tatar)'), ('uk', 'uk (Ukrainian)'), ('ur', 'ur (Urdu)'), ('uz', 'uz (Uzbek)'), ('ve', 've (Venda)'), ('vi', 'vi (Vietnamese)'), ('wo', 'wo (Wolof)'), ('x-testing', 'x-testing (Testing)'), ('xh', 'xh (Xhosa)'), ('yo', 'yo (Yoruba)'), ('zh-CN', 'zh-CN (Chinese (Simplified))'), ('zh-TW', 'zh-TW (Chinese (Traditional))'), ('zu', 'zu (Zulu)')]),
            preserve_default=True,
        ),
    ]

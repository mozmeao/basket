# Generated by Django 4.2.11 on 2024-03-22 18:31

from django.db import migrations, models

import basket.news.fields


class Migration(migrations.Migration):
    dependencies = [
        ("news", "0030_alter_localestewards_unique_together_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="BrazeTxEmailMessage",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("message_id", models.SlugField(help_text="The ID for the message that will be used by clients")),
                ("description", models.CharField(blank=True, help_text="Optional short description of this message", max_length=200)),
                (
                    "language",
                    basket.news.fields.LocaleField(
                        choices=[
                            ("ach", "ach (Acholi)"),
                            ("af", "af (Afrikaans)"),
                            ("ak", "ak (Akan)"),
                            ("am-et", "am-et (Amharic)"),
                            ("an", "an (Aragonese)"),
                            ("ar", "ar (Arabic)"),
                            ("as", "as (Assamese)"),
                            ("ast", "ast (Asturian)"),
                            ("az", "az (Azerbaijani)"),
                            ("azz", "azz (Highland Puebla Nahuatl)"),
                            ("be", "be (Belarusian)"),
                            ("bg", "bg (Bulgarian)"),
                            ("bm", "bm (Bambara)"),
                            ("bn", "bn (Bengali)"),
                            ("bn-BD", "bn-BD (Bengali (Bangladesh))"),
                            ("bn-IN", "bn-IN (Bengali (India))"),
                            ("bo", "bo (Tibetan)"),
                            ("br", "br (Breton)"),
                            ("brx", "brx (Bodo)"),
                            ("bs", "bs (Bosnian)"),
                            ("ca", "ca (Catalan)"),
                            ("ca-valencia", "ca-valencia (Catalan (Valencian))"),
                            ("cak", "cak (Kaqchikel)"),
                            ("ckb", "ckb (Central Kurdish)"),
                            ("crh", "crh (Crimean Tatar)"),
                            ("cs", "cs (Czech)"),
                            ("csb", "csb (Kashubian)"),
                            ("cy", "cy (Welsh)"),
                            ("da", "da (Danish)"),
                            ("dbg", "dbg (Debug Robot)"),
                            ("de", "de (German)"),
                            ("de-AT", "de-AT (German (Austria))"),
                            ("de-CH", "de-CH (German (Switzerland))"),
                            ("de-DE", "de-DE (German (Germany))"),
                            ("dsb", "dsb (Lower Sorbian)"),
                            ("ee", "ee (Ewe)"),
                            ("el", "el (Greek)"),
                            ("en-AU", "en-AU (English (Australian))"),
                            ("en-CA", "en-CA (English (Canadian))"),
                            ("en-GB", "en-GB (English (British))"),
                            ("en-NZ", "en-NZ (English (New Zealand))"),
                            ("en-US", "en-US (English (US))"),
                            ("en-ZA", "en-ZA (English (South African))"),
                            ("eo", "eo (Esperanto)"),
                            ("es", "es (Spanish)"),
                            ("es-AR", "es-AR (Spanish (Argentina))"),
                            ("es-CL", "es-CL (Spanish (Chile))"),
                            ("es-ES", "es-ES (Spanish (Spain))"),
                            ("es-MX", "es-MX (Spanish (Mexico))"),
                            ("et", "et (Estonian)"),
                            ("eu", "eu (Basque)"),
                            ("fa", "fa (Persian)"),
                            ("ff", "ff (Fulah)"),
                            ("fi", "fi (Finnish)"),
                            ("fj-FJ", "fj-FJ (Fijian)"),
                            ("fr", "fr (French)"),
                            ("fur-IT", "fur-IT (Friulian)"),
                            ("fy-NL", "fy-NL (Frisian)"),
                            ("ga", "ga (Irish)"),
                            ("ga-IE", "ga-IE (Irish)"),
                            ("gd", "gd (Gaelic (Scotland))"),
                            ("gl", "gl (Galician)"),
                            ("gn", "gn (Guarani)"),
                            ("gu", "gu (Gujarati)"),
                            ("gu-IN", "gu-IN (Gujarati (India))"),
                            ("ha", "ha (Hausa)"),
                            ("he", "he (Hebrew)"),
                            ("hi", "hi (Hindi)"),
                            ("hi-IN", "hi-IN (Hindi (India))"),
                            ("hr", "hr (Croatian)"),
                            ("hsb", "hsb (Upper Sorbian)"),
                            ("hu", "hu (Hungarian)"),
                            ("hy-AM", "hy-AM (Armenian)"),
                            ("hye", "hye (Armenian Eastern Classic Orthography)"),
                            ("ia", "ia (Interlingua)"),
                            ("id", "id (Indonesian)"),
                            ("ig", "ig (Igbo)"),
                            ("is", "is (Icelandic)"),
                            ("it", "it (Italian)"),
                            ("ja", "ja (Japanese)"),
                            ("ja-JP-mac", "ja-JP-mac (Japanese)"),
                            ("ka", "ka (Georgian)"),
                            ("kab", "kab (Kabyle)"),
                            ("kk", "kk (Kazakh)"),
                            ("km", "km (Khmer)"),
                            ("kn", "kn (Kannada)"),
                            ("ko", "ko (Korean)"),
                            ("kok", "kok (Konkani)"),
                            ("ks", "ks (Kashmiri)"),
                            ("ku", "ku (Kurdish)"),
                            ("la", "la (Latin)"),
                            ("lg", "lg (Luganda)"),
                            ("lij", "lij (Ligurian)"),
                            ("ln", "ln (Lingala)"),
                            ("lo", "lo (Lao)"),
                            ("lt", "lt (Lithuanian)"),
                            ("ltg", "ltg (Latgalian)"),
                            ("lv", "lv (Latvian)"),
                            ("mai", "mai (Maithili)"),
                            ("meh", "meh (Mixteco Yucuhiti)"),
                            ("mg", "mg (Malagasy)"),
                            ("mi", "mi (Maori (Aotearoa))"),
                            ("mk", "mk (Macedonian)"),
                            ("ml", "ml (Malayalam)"),
                            ("mn", "mn (Mongolian)"),
                            ("mr", "mr (Marathi)"),
                            ("ms", "ms (Malay)"),
                            ("my", "my (Burmese)"),
                            ("nb-NO", "nb-NO (Norwegian (Bokmål))"),
                            ("ne-NP", "ne-NP (Nepali)"),
                            ("nl", "nl (Dutch)"),
                            ("nn-NO", "nn-NO (Norwegian (Nynorsk))"),
                            ("nr", "nr (Ndebele, South)"),
                            ("nso", "nso (Northern Sotho)"),
                            ("oc", "oc (Occitan (Lengadocian))"),
                            ("or", "or (Odia)"),
                            ("pa", "pa (Punjabi)"),
                            ("pa-IN", "pa-IN (Punjabi (India))"),
                            ("pl", "pl (Polish)"),
                            ("pt-BR", "pt-BR (Portuguese (Brazilian))"),
                            ("pt-PT", "pt-PT (Portuguese (Portugal))"),
                            ("rm", "rm (Romansh)"),
                            ("ro", "ro (Romanian)"),
                            ("ru", "ru (Russian)"),
                            ("rw", "rw (Kinyarwanda)"),
                            ("sa", "sa (Sanskrit)"),
                            ("sah", "sah (Sakha)"),
                            ("sat", "sat (Santali)"),
                            ("sc", "sc (Sardinian)"),
                            ("scn", "scn (Sicilian)"),
                            ("sco", "sco (Scots)"),
                            ("si", "si (Sinhala)"),
                            ("sk", "sk (Slovak)"),
                            ("sl", "sl (Slovenian)"),
                            ("son", "son (Songhai)"),
                            ("sq", "sq (Albanian)"),
                            ("sr", "sr (Serbian)"),
                            ("sr-Cyrl", "sr-Cyrl (Serbian)"),
                            ("sr-Latn", "sr-Latn (Serbian)"),
                            ("ss", "ss (Siswati)"),
                            ("st", "st (Southern Sotho)"),
                            ("sv-SE", "sv-SE (Swedish)"),
                            ("sw", "sw (Swahili)"),
                            ("szl", "szl (Silesian)"),
                            ("ta", "ta (Tamil)"),
                            ("ta-IN", "ta-IN (Tamil (India))"),
                            ("ta-LK", "ta-LK (Tamil (Sri Lanka))"),
                            ("te", "te (Telugu)"),
                            ("tg", "tg (Tajik)"),
                            ("th", "th (Thai)"),
                            ("tl", "tl (Tagalog)"),
                            ("tn", "tn (Tswana)"),
                            ("tr", "tr (Turkish)"),
                            ("trs", "trs (Triqui)"),
                            ("ts", "ts (Tsonga)"),
                            ("tsz", "tsz (Purépecha)"),
                            ("tt-RU", "tt-RU (Tatar)"),
                            ("uk", "uk (Ukrainian)"),
                            ("ur", "ur (Urdu)"),
                            ("uz", "uz (Uzbek)"),
                            ("ve", "ve (Venda)"),
                            ("vi", "vi (Vietnamese)"),
                            ("wo", "wo (Wolof)"),
                            ("x-testing", "x-testing (Testing)"),
                            ("xh", "xh (Xhosa)"),
                            ("yo", "yo (Yoruba)"),
                            ("zh-CN", "zh-CN (Chinese (Simplified))"),
                            ("zh-TW", "zh-TW (Chinese (Traditional))"),
                            ("zu", "zu (Zulu)"),
                        ],
                        default="en-US",
                        max_length=32,
                    ),
                ),
                (
                    "private",
                    models.BooleanField(
                        default=False,
                        help_text="Whether this email is private. Private emails are not allowed to be sent via the normal subscribe API.",
                    ),
                ),
            ],
            options={
                "verbose_name": "Braze transactional email",
                "ordering": ["message_id"],
                "unique_together": {("message_id", "language")},
            },
        ),
    ]

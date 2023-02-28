# -*- coding: utf-8 -*-


from django.db import migrations, models

import basket.news.fields


class Migration(migrations.Migration):
    dependencies = [
        ("news", "0012_auto_20170713_1021"),
    ]

    operations = [
        migrations.CreateModel(
            name="LocalizedSMSMessage",
            fields=[
                (
                    "id",
                    models.AutoField(
                        verbose_name="ID",
                        serialize=False,
                        auto_created=True,
                        primary_key=True,
                    ),
                ),
                (
                    "message_id",
                    models.SlugField(
                        help_text=b"The ID for the message that will be used by clients",
                    ),
                ),
                (
                    "vendor_id",
                    models.CharField(
                        help_text=b"The backend vendor's identifier for this message",
                        max_length=50,
                    ),
                ),
                (
                    "description",
                    models.CharField(
                        help_text=b"Optional short description of this message",
                        max_length=200,
                        blank=True,
                    ),
                ),
                (
                    "language",
                    basket.news.fields.LocaleField(
                        default=b"en-US",
                        max_length=32,
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
                            ("be", "be (Belarusian)"),
                            ("bg", "bg (Bulgarian)"),
                            ("bm", "bm (Bambara)"),
                            ("bn-BD", "bn-BD (Bengali (Bangladesh))"),
                            ("bn-IN", "bn-IN (Bengali (India))"),
                            ("br", "br (Breton)"),
                            ("brx", "brx (Bodo)"),
                            ("bs", "bs (Bosnian)"),
                            ("ca", "ca (Catalan)"),
                            ("ca-valencia", "ca-valencia (Catalan (Valencian))"),
                            ("cak", "cak (Kaqchikel)"),
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
                            ("id", "id (Indonesian)"),
                            ("ig", "ig (Igbo)"),
                            ("is", "is (Icelandic)"),
                            ("it", "it (Italian)"),
                            ("ja", "ja (Japanese)"),
                            ("ja-JP-mac", "ja-JP-mac (Japanese)"),
                            ("ka", "ka (Georgian)"),
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
                            ("mg", "mg (Malagasy)"),
                            ("mi", "mi (Maori (Aotearoa))"),
                            ("mk", "mk (Macedonian)"),
                            ("ml", "ml (Malayalam)"),
                            ("mn", "mn (Mongolian)"),
                            ("mr", "mr (Marathi)"),
                            ("ms", "ms (Malay)"),
                            ("my", "my (Burmese)"),
                            ("nb-NO", "nb-NO (Norwegian (Bokm\xe5l))"),
                            ("ne-NP", "ne-NP (Nepali)"),
                            ("nl", "nl (Dutch)"),
                            ("nn-NO", "nn-NO (Norwegian (Nynorsk))"),
                            ("nr", "nr (Ndebele, South)"),
                            ("nso", "nso (Northern Sotho)"),
                            ("oc", "oc (Occitan (Lengadocian))"),
                            ("or", "or (Oriya)"),
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
                            ("ta", "ta (Tamil)"),
                            ("ta-IN", "ta-IN (Tamil (India))"),
                            ("ta-LK", "ta-LK (Tamil (Sri Lanka))"),
                            ("te", "te (Telugu)"),
                            ("th", "th (Thai)"),
                            ("tl", "tl (Tagalog)"),
                            ("tn", "tn (Tswana)"),
                            ("tr", "tr (Turkish)"),
                            ("ts", "ts (Tsonga)"),
                            ("tsz", "tsz (Pur\xe9pecha)"),
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
                    ),
                ),
                (
                    "country",
                    basket.news.fields.CountryField(
                        default=b"us",
                        max_length=3,
                        choices=[
                            ("ad", "ad (Andorra)"),
                            ("ae", "ae (U.A.E.)"),
                            ("af", "af (Afghanistan)"),
                            ("ag", "ag (Antigua and Barbuda)"),
                            ("ai", "ai (Anguilla)"),
                            ("al", "al (Albania)"),
                            ("am", "am (Armenia)"),
                            ("an", "an (Netherlands Antilles)"),
                            ("ao", "ao (Angola)"),
                            ("aq", "aq (Antarctica)"),
                            ("ar", "ar (Argentina)"),
                            ("as", "as (American Samoa)"),
                            ("at", "at (Austria)"),
                            ("au", "au (Australia)"),
                            ("aw", "aw (Aruba)"),
                            ("ax", "ax (\xc5land Islands)"),
                            ("az", "az (Azerbaijan)"),
                            ("ba", "ba (Bosnia and Herzegovina)"),
                            ("bb", "bb (Barbados)"),
                            ("bd", "bd (Bangladesh)"),
                            ("be", "be (Belgium)"),
                            ("bf", "bf (Burkina Faso)"),
                            ("bg", "bg (Bulgaria)"),
                            ("bh", "bh (Bahrain)"),
                            ("bi", "bi (Burundi)"),
                            ("bj", "bj (Benin)"),
                            ("bl", "bl (Saint Barth\xe9lemy)"),
                            ("bm", "bm (Bermuda)"),
                            ("bn", "bn (Brunei Darussalam)"),
                            ("bo", "bo (Bolivia)"),
                            ("br", "br (Brazil)"),
                            ("bs", "bs (Bahamas)"),
                            ("bt", "bt (Bhutan)"),
                            ("bv", "bv (Bouvet Island)"),
                            ("bw", "bw (Botswana)"),
                            ("by", "by (Belarus)"),
                            ("bz", "bz (Belize)"),
                            ("ca", "ca (Canada)"),
                            ("cc", "cc (Cocos (Keeling) Islands)"),
                            ("cd", "cd (Congo-Kinshasa)"),
                            ("cf", "cf (Central African Republic)"),
                            ("cg", "cg (Congo-Brazzaville)"),
                            ("ch", "ch (Switzerland)"),
                            ("ci", "ci (Ivory Coast)"),
                            ("ck", "ck (Cook Islands)"),
                            ("cl", "cl (Chile)"),
                            ("cm", "cm (Cameroon)"),
                            ("cn", "cn (China)"),
                            ("co", "co (Colombia)"),
                            ("cr", "cr (Costa Rica)"),
                            ("cu", "cu (Cuba)"),
                            ("cv", "cv (Cape Verde)"),
                            ("cx", "cx (Christmas Island)"),
                            ("cy", "cy (Cyprus)"),
                            ("cz", "cz (Czech Republic)"),
                            ("de", "de (Germany)"),
                            ("dj", "dj (Djibouti)"),
                            ("dk", "dk (Denmark)"),
                            ("dm", "dm (Dominica)"),
                            ("do", "do (Dominican Republic)"),
                            ("dz", "dz (Algeria)"),
                            ("ec", "ec (Ecuador)"),
                            ("ee", "ee (Estonia)"),
                            ("eg", "eg (Egypt)"),
                            ("eh", "eh (Western Sahara)"),
                            ("er", "er (Eritrea)"),
                            ("es", "es (Spain)"),
                            ("et", "et (Ethiopia)"),
                            ("fi", "fi (Finland)"),
                            ("fj", "fj (Fiji)"),
                            ("fk", "fk (Falkland Islands (Malvinas))"),
                            ("fm", "fm (Micronesia)"),
                            ("fo", "fo (Faroe Islands)"),
                            ("fr", "fr (France)"),
                            ("ga", "ga (Gabon)"),
                            ("gb", "gb (United Kingdom)"),
                            ("gd", "gd (Grenada)"),
                            ("ge", "ge (Georgia)"),
                            ("gf", "gf (French Guiana)"),
                            ("gg", "gg (Guernsey)"),
                            ("gh", "gh (Ghana)"),
                            ("gi", "gi (Gibraltar)"),
                            ("gl", "gl (Greenland)"),
                            ("gm", "gm (Gambia)"),
                            ("gn", "gn (Guinea)"),
                            ("gp", "gp (Guadeloupe)"),
                            ("gq", "gq (Equatorial Guinea)"),
                            ("gr", "gr (Greece)"),
                            ("gs", "gs (South Georgia and the South Sandwich Islands)"),
                            ("gt", "gt (Guatemala)"),
                            ("gu", "gu (Guam)"),
                            ("gw", "gw (Guinea-Bissau)"),
                            ("gy", "gy (Guyana)"),
                            ("hk", "hk (Hong Kong)"),
                            ("hm", "hm (Heard Island and McDonald Islands)"),
                            ("hn", "hn (Honduras)"),
                            ("hr", "hr (Croatia)"),
                            ("ht", "ht (Haiti)"),
                            ("hu", "hu (Hungary)"),
                            ("id", "id (Indonesia)"),
                            ("ie", "ie (Ireland)"),
                            ("il", "il (Israel)"),
                            ("im", "im (Isle of Man)"),
                            ("in", "in (India)"),
                            ("io", "io (British Indian Ocean Territory)"),
                            ("iq", "iq (Iraq)"),
                            ("ir", "ir (Iran)"),
                            ("is", "is (Iceland)"),
                            ("it", "it (Italy)"),
                            ("je", "je (Jersey)"),
                            ("jm", "jm (Jamaica)"),
                            ("jo", "jo (Jordan)"),
                            ("jp", "jp (Japan)"),
                            ("ke", "ke (Kenya)"),
                            ("kg", "kg (Kyrgyzstan)"),
                            ("kh", "kh (Cambodia)"),
                            ("ki", "ki (Kiribati)"),
                            ("km", "km (Comoros)"),
                            ("kn", "kn (Saint Kitts and Nevis)"),
                            ("kp", "kp (North Korea)"),
                            ("kr", "kr (South Korea)"),
                            ("kw", "kw (Kuwait)"),
                            ("ky", "ky (Cayman Islands)"),
                            ("kz", "kz (Kazakhstan)"),
                            ("la", "la (Laos)"),
                            ("lb", "lb (Lebanon)"),
                            ("lc", "lc (Saint Lucia)"),
                            ("li", "li (Liechtenstein)"),
                            ("lk", "lk (Sri Lanka)"),
                            ("lr", "lr (Liberia)"),
                            ("ls", "ls (Lesotho)"),
                            ("lt", "lt (Lithuania)"),
                            ("lu", "lu (Luxembourg)"),
                            ("lv", "lv (Latvia)"),
                            ("ly", "ly (Libya)"),
                            ("ma", "ma (Morocco)"),
                            ("mc", "mc (Monaco)"),
                            ("md", "md (Moldova)"),
                            ("me", "me (Montenegro)"),
                            ("mf", "mf (Saint Martin)"),
                            ("mg", "mg (Madagascar)"),
                            ("mh", "mh (Marshall Islands)"),
                            ("mk", "mk (Macedonia, F.Y.R. of)"),
                            ("ml", "ml (Mali)"),
                            ("mm", "mm (Myanmar)"),
                            ("mn", "mn (Mongolia)"),
                            ("mo", "mo (Macao)"),
                            ("mp", "mp (Northern Mariana Islands)"),
                            ("mq", "mq (Martinique)"),
                            ("mr", "mr (Mauritania)"),
                            ("ms", "ms (Montserrat)"),
                            ("mt", "mt (Malta)"),
                            ("mu", "mu (Mauritius)"),
                            ("mv", "mv (Maldives)"),
                            ("mw", "mw (Malawi)"),
                            ("mx", "mx (Mexico)"),
                            ("my", "my (Malaysia)"),
                            ("mz", "mz (Mozambique)"),
                            ("na", "na (Namibia)"),
                            ("nc", "nc (New Caledonia)"),
                            ("ne", "ne (Niger)"),
                            ("nf", "nf (Norfolk Island)"),
                            ("ng", "ng (Nigeria)"),
                            ("ni", "ni (Nicaragua)"),
                            ("nl", "nl (Netherlands)"),
                            ("no", "no (Norway)"),
                            ("np", "np (Nepal)"),
                            ("nr", "nr (Nauru)"),
                            ("nu", "nu (Niue)"),
                            ("nz", "nz (New Zealand)"),
                            ("om", "om (Oman)"),
                            ("pa", "pa (Panama)"),
                            ("pe", "pe (Peru)"),
                            ("pf", "pf (French Polynesia)"),
                            ("pg", "pg (Papua New Guinea)"),
                            ("ph", "ph (Philippines)"),
                            ("pk", "pk (Pakistan)"),
                            ("pl", "pl (Poland)"),
                            ("pm", "pm (Saint Pierre and Miquelon)"),
                            ("pn", "pn (Pitcairn)"),
                            ("pr", "pr (Puerto Rico)"),
                            ("ps", "ps (Occupied Palestinian Territory)"),
                            ("pt", "pt (Portugal)"),
                            ("pw", "pw (Palau)"),
                            ("py", "py (Paraguay)"),
                            ("qa", "qa (Qatar)"),
                            ("re", "re (Reunion)"),
                            ("ro", "ro (Romania)"),
                            ("rs", "rs (Serbia)"),
                            ("ru", "ru (Russian Federation)"),
                            ("rw", "rw (Rwanda)"),
                            ("sa", "sa (Saudi Arabia)"),
                            ("sb", "sb (Solomon Islands)"),
                            ("sc", "sc (Seychelles)"),
                            ("sd", "sd (Sudan)"),
                            ("se", "se (Sweden)"),
                            ("sg", "sg (Singapore)"),
                            ("sh", "sh (Saint Helena)"),
                            ("si", "si (Slovenia)"),
                            ("sj", "sj (Svalbard and Jan Mayen)"),
                            ("sk", "sk (Slovakia)"),
                            ("sl", "sl (Sierra Leone)"),
                            ("sm", "sm (San Marino)"),
                            ("sn", "sn (Senegal)"),
                            ("so", "so (Somalia)"),
                            ("sr", "sr (Suriname)"),
                            ("st", "st (Sao Tome and Principe)"),
                            ("sv", "sv (El Salvador)"),
                            ("sy", "sy (Syria)"),
                            ("sz", "sz (Swaziland)"),
                            ("tc", "tc (Turks and Caicos Islands)"),
                            ("td", "td (Chad)"),
                            ("tf", "tf (French Southern Territories)"),
                            ("tg", "tg (Togo)"),
                            ("th", "th (Thailand)"),
                            ("tj", "tj (Tajikistan)"),
                            ("tk", "tk (Tokelau)"),
                            ("tl", "tl (Timor-Leste)"),
                            ("tm", "tm (Turkmenistan)"),
                            ("tn", "tn (Tunisia)"),
                            ("to", "to (Tonga)"),
                            ("tr", "tr (Turkey)"),
                            ("tt", "tt (Trinidad and Tobago)"),
                            ("tv", "tv (Tuvalu)"),
                            ("tw", "tw (Taiwan)"),
                            ("tz", "tz (Tanzania)"),
                            ("ua", "ua (Ukraine)"),
                            ("ug", "ug (Uganda)"),
                            ("um", "um (United States Minor Outlying Islands)"),
                            ("us", "us (United States)"),
                            ("uy", "uy (Uruguay)"),
                            ("uz", "uz (Uzbekistan)"),
                            ("va", "va (Vatican City)"),
                            ("vc", "vc (Saint Vincent and the Grenadines)"),
                            ("ve", "ve (Venezuela)"),
                            ("vg", "vg (British Virgin Islands)"),
                            ("vi", "vi (U.S. Virgin Islands)"),
                            ("vn", "vn (Vietnam)"),
                            ("vu", "vu (Vanuatu)"),
                            ("wf", "wf (Wallis and Futuna)"),
                            ("ws", "ws (Samoa)"),
                            ("ye", "ye (Yemen)"),
                            ("yt", "yt (Mayotte)"),
                            ("za", "za (South Africa)"),
                            ("zm", "zm (Zambia)"),
                            ("zw", "zw (Zimbabwe)"),
                        ],
                    ),
                ),
            ],
            options={"verbose_name": "Localized SMS message"},
        ),
        migrations.AlterUniqueTogether(
            name="localizedsmsmessage",
            unique_together=set([("message_id", "language", "country")]),
        ),
    ]

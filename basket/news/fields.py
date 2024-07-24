from django.db import models

from product_details import product_details

from basket.news.country_codes import SFDC_COUNTRIES

ENGLISH_LANGUAGE_CHOICES = sorted(
    [(key, f"{key} ({value['English']})") for key, value in product_details.languages.items()],
)
COUNTRY_CHOICES = sorted(
    [(key, f"{key} ({value})") for key, value in SFDC_COUNTRIES.items()],
)


class CountryField(models.CharField):
    description = "CharField for storing a country code."

    def __init__(self, *args, **kwargs):
        defaults = {
            "max_length": 3,
            "choices": COUNTRY_CHOICES,
        }
        for key, value in defaults.items():
            kwargs.setdefault(key, value)

        super().__init__(*args, **kwargs)


class LocaleField(models.CharField):
    description = "CharField for storing a locale code."

    def __init__(self, *args, **kwargs):
        defaults = {
            "max_length": 32,
            "choices": ENGLISH_LANGUAGE_CHOICES,
        }
        for key, value in defaults.items():
            kwargs.setdefault(key, value)

        super().__init__(*args, **kwargs)

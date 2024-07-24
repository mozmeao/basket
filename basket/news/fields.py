from django.db import models

from product_details import product_details

ENGLISH_LANGUAGE_CHOICES = sorted(
    [(key, f"{key} ({value['English']})") for key, value in product_details.languages.items()],
)


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

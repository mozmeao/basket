from django.core.exceptions import ValidationError
from django.db import models

import product_details


class Subscription(models.Model):
    email = models.EmailField()
    campaign = models.CharField(max_length=255)
    active = models.BooleanField(default=True)
    source = models.CharField(max_length=255, blank=True)
    locale = models.CharField(max_length=10, blank=True, default='en-US')

    def clean(self):
        if self.locale == '':
            self.locale = 'en-US'
        if self.locale not in product_details.languages.keys():
            raise ValidationError("Not a valid language")

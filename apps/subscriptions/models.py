from django.core.exceptions import ValidationError
from django.db import models

import product_details


class Subscription(models.Model):
    email = models.EmailField(db_index=True)
    campaign = models.CharField(max_length=255, db_index=True)
    active = models.BooleanField(default=True)
    source = models.CharField(max_length=255, blank=True)
    locale = models.CharField(max_length=10, blank=True, default='en-US')
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (('email', 'campaign'),)

    def clean(self):
        if self.locale == '':
            self.locale = 'en-US'
        if self.locale not in product_details.languages.keys():
            raise ValidationError("Not a valid language")

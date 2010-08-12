from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation.trans_real import to_language


class Subscriber(models.Model):
    email = models.EmailField(db_index=True)

    def __str__(self):
        return self.email

class Subscription(models.Model):
    subscriber = models.ForeignKey(Subscriber, related_name='subscriptions')
    campaign = models.CharField(max_length=255, db_index=True)
    active = models.BooleanField(default=True)
    source = models.CharField(max_length=255, blank=True)
    locale = models.CharField(max_length=30, blank=True, default='en-US')
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    country = models.CharField(max_length=10, blank=True, default='us')

    class Meta:
        unique_together = (('subscriber', 'campaign'),)

    def clean(self):
        if self.locale == '':
            self.locale = 'en-US'

        # convert locale codes (en_US) to lang code (en-us)
        self.locale = to_language(self.locale)

        if self.locale.lower() not in settings.LANGUAGES_LOWERED:
            raise ValidationError("Not a valid language")

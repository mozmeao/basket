from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Subscriber(models.Model):
    email = models.EmailField(db_index=True)
    
class Subscription(models.Model):
    subscriber = models.ForeignKey(Subscriber)
    campaign = models.CharField(max_length=255, db_index=True)
    active = models.BooleanField(default=True)
    source = models.CharField(max_length=255, blank=True)
    locale = models.CharField(max_length=10, blank=True, default='en-US')
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (('subscriber', 'campaign'),)

    def clean(self):
        if self.locale == '':
            self.locale = 'en-US'
        if self.locale not in settings.LANGUAGES:
            raise ValidationError("Not a valid language")

from django.db import models


class Subscription(models.Model):
    email = models.EmailField()
    campaign = models.CharField(max_length=255)
    active = models.BooleanField(default=True)
    source = models.CharField(max_length=255, blank=True)

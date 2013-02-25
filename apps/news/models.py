from uuid import uuid4

from django.db import models


class SubscriberManager(models.Manager):
    def get_and_sync(self, email, token):
        """
        Get the subscriber for the email and token and ensure that such a
        subscriber exists.
        """
        sub, created = self.get_or_create(
            email=email,
            defaults={'token': token},
        )
        if not created and sub.token != token:
            sub.token = token
            sub.save()

        return sub


class Subscriber(models.Model):
    email = models.EmailField(primary_key=True)
    token = models.CharField(max_length=1024, default=lambda: str(uuid4()))

    objects = SubscriberManager()

from django.db import models

from subscriptions.models import Subscriber


class Recipient(models.Model):
    """
    A mapping between templates and subscribers, keeping track of people who
    have already received a specific template.
    """
    subscriber = models.ForeignKey(Subscriber, related_name='received')
    email_id = models.CharField(max_length=255)
    created = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        unique_together = (('subscriber', 'email_id'),)

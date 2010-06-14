from django.db import models

from subscriptions.models import Subscriber


class Email(models.Model):
    """An email template, to be sent to subscribers."""
    name = models.CharField(max_length=255, db_index=True)
    subject = models.CharField(max_length=255)
    text = models.TextField()
    html = models.TextField(blank=True, help_text=(
        'Keep empty for text-only mail. Otherwise, make this the HTML version '
        'of the email. HTML-only emails are not allowed.'))
    recipients = models.ManyToManyField(Subscriber, through='Recipient',
                                        related_name='received')
    emailer_class = models.CharField(max_length=255, blank=True, help_text=(
        'Python class name of custom Emailer to use. Example: '
        '<code>emailer.emailers.MyFancyEmailer</code><br/>Keep empty for '
        'default Emailer.'))


class Recipient(models.Model):
    """
    A mapping between templates and subscribers, keeping track of people who
    have already received a specific template.
    """
    subscriber = models.ForeignKey(Subscriber)
    email = models.ForeignKey(Email)
    created = models.DateTimeField(auto_now_add=True, editable=False)

    class Meta:
        unique_together = (('subscriber', 'email'),)

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.urlresolvers import get_callable
from django.db import models

from greatape import MailChimp

import emailer
from subscriptions.models import Subscriber

mailchimp = MailChimp(settings.MAILCHIMP_API_KEY)


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
    from_name = models.CharField(max_length=255, blank=True, help_text=(
        "The sender's name (not an email address)"))
    from_email = models.EmailField(blank=True, help_text=(
        "The sender's address e.g. campaign@mozilla.com"))
    reply_to_email = models.EmailField(blank=True, help_text=(
        "The reply-to address"))
    mailchimp_campaign = models.CharField(max_length=20, blank=True)
    mailchimp_list = models.CharField(max_length=20, blank=True, help_text=(
        "MailChimp list ID."
        "Only required if you're using the MailChimp emailer."
        "You can find this in the MailChimp list admin page."))

    def get_emailer_callable(self):
        return get_callable(self.emailer_class or 'emailer.base.BaseEmailer')

    def clean(self):
        if issubclass(self.get_emailer_callable(),
                      emailer.base.MailChimpEmailer):

            if not self.mailchimp_list:
                raise ValidationError("A MailChimp list ID is required.")

    def save(self):
        if issubclass(self.get_emailer_callable(),
                      emailer.base.MailChimpEmailer):

            if not self.mailchimp_campaign:
                self.create_mailchimp_campaign()
            else:
                self.update_mailchimp_campaign()

        super(Email, self).save()

    def update_mailchimp_campaign(self):
        """Update the MailChimp campaign"""

        mailchimp.campaignUpdate(cid=self.mailchimp_campaign, name='list_id',
                                 value=self.mailchimp_list)
        mailchimp.campaignUpdate(cid=self.mailchimp_campaign, name='subject',
                                 value=self.subject)
        updates = {
            'list_id':    self.mailchimp_list,
            'subject':    self.subject,
            'from_email': settings.DEFAULT_FROM_EMAIL,
            'from_name':  settings.DEFAULT_FROM_NAME,
            'auto_footer': False,
            'content': {
                'html': self.html,
                'text': self.text,
            }
        }
        for name, update in updates.items():
            mailchimp.campaignUpdate(cid=self.mailchimp_campaign, name=name,
                                     value=update)

    def create_mailchimp_campaign(self):
        """Create a MailChimp campaign and store its ID."""

        type = 'trans'
        options = {
            'list_id':    self.mailchimp_list,
            'subject':    self.subject,
            'from_email': self.from_email,
            'from_name':  self.from_name,
            'auto_footer': False,
        }
        content = {
            'html': self.html,
            'text': self.text,
        }
        cid = mailchimp.campaignCreate(type=type, options=options,
                                       content=content)
        self.mailchimp_campaign = cid


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

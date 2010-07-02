import commonware.log

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core import mail

from greatape import MailChimp

from emailer.models import Recipient
from subscriptions.models import Subscriber


log = commonware.log.getLogger('basket')

mailchimp = MailChimp(settings.MAILCHIMP_API_KEY)


class BaseEmailer(object):
    """
    Base Emailer class.

    Given a template and a campaign, emails all active subscribers to that
    campaign that haven't received that email yet.

    Subclass and override to change behavior, such as excluding recipients
    based on complex criteria. For an example, check out
    lib/custom_emailers/*.py.
    """
    def __init__(self, campaign, email, force=False):
        """Initialize emailer with campaign name and email model instance."""
        self.email = email
        self.campaign = campaign
        self.force = force

    def get_subject(self):
        """Return the email subject."""
        return self.email.subject

    def get_text(self):
        """Return the plain text email message."""
        return self.email.text

    def get_html(self):
        """Return the HTML text of the email message."""
        return self.email.html

    def get_from(self):
        """Return "from" email address."""
        return settings.DEFAULT_FROM_EMAIL

    def get_recipients(self):
        """
        Return all subscribers to the chosen campaign that are active and have
        not yet received this email.
        """
        recipients = Subscriber.objects.filter(
            subscriptions__campaign=self.campaign, subscriptions__active=True)
        if not self.force:
            recipients = recipients.exclude(received=self.email)
        return recipients

    def get_headers(self):
        """Return additional headers."""
        return {
            'X-Mailer': 'Basket Emailer %s' % (
                '.'.join(map(str, settings.VERSION)))}

    def send_email(self):
        """Send out the email and record the recipients."""
        recipients = self.get_recipients()
        if not recipients:
            log.info('Nothing to do: List of recipients is empty.')
            return

        log.info('Establishing SMTP connection...')
        connection = mail.get_connection()
        connection.open()

        for recipient in recipients:
            msg = mail.EmailMultiAlternatives(
                subject=self.get_subject(),
                body=self.get_text(),
                from_email=self.get_from(),
                to=(recipient.email,),
                headers=self.get_headers())

            html = self.get_html()
            if html:
                msg.attach_alternative(html, 'text/html')

            try:
                log.info('Sending email to %s' % recipient.email)
                msg.send(fail_silently=False)
            except Exception, e:
                log.warning('Sending email to %s failed: %s' % (
                    recipient.email, e))
            else:
                log.info('Email sent to %s' % recipient.email)
                sent = Recipient(subscriber=recipient, email=self.email)
                try:
                    sent.validate_unique()
                except ValidationError, e:
                    # Already exists? Sending was probably forced.
                    pass
                else:
                    sent.save()

        connection.close()


class MailChimpEmailer(BaseEmailer):
    """
    Send email using MailChimp lists and transactional campaigns
    """

    def send_email(self):
        """Send out the email and record the recipients."""
        recipients = self.get_recipients()
        if not recipients:
            log.info('Nothing to do: List of recipients is empty.')
            return

        # MailChimp recommends max batch size of 10K
        recipients = recipients[0:10000]

        batch = [dict(EMAIL=x.email, EMAIL_TYPE='html') for x in recipients]

        ret = mailchimp.listBatchSubscribe(id=self.email.mailchimp_list,
                                           batch=batch, double_optin=False)

        failed = [x['row']['EMAIL'] for x in ret['errors']]

        for recipient in recipients:
            if recipient.email in failed:
                log.error('Failed to subscribe %s' % recipient.email)
            else:
                log.info('Subscribed %s' % recipient.email)
                sent = Recipient(subscriber=recipient, email=self.email)
                try:
                    sent.validate_unique()
                except ValidationError:
                    # Already exists? Sending was probably forced.
                    pass
                else:
                    sent.save()

        mailchimp.campaignSendNow(cid=self.email.mailchimp_campaign)

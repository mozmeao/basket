from email import Charset

from django.conf import settings
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.urlresolvers import get_callable
from django.utils import translation
from django.utils.encoding import force_unicode

import commonware.log
import jingo
import tower

from emailer.models import Recipient
from html2text import html2text
from subscriptions.models import Subscription


log = commonware.log.getLogger('basket')

charsets = {
    'ja': 'ISO-2022-JP',
    'it': 'ISO-8859-1',
    'de': 'ISO-8859-15',
    'fr': 'ISO-8859-15',
    'zh-CN': 'GB18030',
    'ko': 'EUC-KR',
    'cs': 'ISO-8859-2',
    'tr': 'ISO-8859-9',
}
for c in charsets.values():
    Charset.add_charset(c)


class Email(object):

    id = 'email-id'
    subject = 'subject'
    lang = settings.LANGUAGE_CODE
    encoding = settings.DEFAULT_CHARSET
    from_email = settings.DEFAULT_FROM_EMAIL
    from_name = settings.DEFAULT_FROM_NAME
    reply_email = settings.DEFAULT_FROM_EMAIL
    emailer_class = 'emailer.Emailer'
    template = 'test'

    @classmethod
    def get(cls, name):
        email = get_callable(name)    
        return email()

    @property
    def html(self):
        path = 'emails/{0}.html'.format(self.template)
        return jingo.env.get_template(path).render({'lang': self.lang})

    @property
    def text(self):
        return html2text(self.html)

    def _activate_lang(self):
        tower.activate(self.lang)
        lang = translation.get_language()
        if lang in charsets:
            self.encoding = charsets[lang]
        elif lang[:2] in charsets:
             self.encoding = charsets[lang[:2]]
        else:
             self.encoding = settings.DEFAULT_CHARSET

    def emailer(self, campaign, email, force=False):
        emailer_class = get_callable(self.emailer_class)    
        return emailer_class(campaign, email, force)

    def message(self, address):
        self._activate_lang()

        d = {
            'subject': force_unicode(self.subject),
            'from_email': u'{0} <{1}>'.format(self.from_name, self.from_email),
            'body': self.text,
            'headers': {
                'Reply-To': self.reply_email,
                'X-Mailer': 'Basket Emailer %s' % (
                    '.'.join(map(str, settings.VERSION)))}
        }

        msg = mail.EmailMultiAlternatives(to=(address,), **d)
        msg.encoding = self.encoding
        msg.attach_alternative(self.html, 'text/html')
        return msg


class Emailer(object):
    """
    Base Emailer class.

    Given a template and a campaign, emails all active subscribers to that
    campaign that haven't received that email yet.

    Subclass and override to change behavior, such as excluding subscriptions
    based on complex criteria. For an example, check out
    lib/custom_emailers/*.py.
    """
    def __init__(self, campaign, email, force=False):
        """Initialize emailer with campaign name and email model instance."""
        self.campaign = campaign
        self.email = email
        self.force = force

    def get_subscriptions(self):
        """
        Return all subscribers to the chosen campaign that are active and have
        not yet received this email.
        """
        subscriptions = Subscription.objects.filter(
            campaign=self.campaign, active=True)
        if not self.force:
            subscriptions = subscriptions.exclude(
                subscriber__received__email_id=self.email.id)
        return subscriptions

    def send_email(self):
        """Send out the email and record the subscriptions."""

        subscriptions = self.get_subscriptions()
        if not subscriptions:
            log.info('Nothing to do: List of subscriptions is empty.')
            return

        emails = dict((s.subscriber.email, s) for s in subscriptions)

        messages = []
        for (address, subscription) in emails.items():
            self.email.lang = subscription.locale
            msg = self.email.message(address)
            messages.append(msg)

        log.info('Establishing SMTP connection...')
        connection = mail.get_connection()
        connection.open()

        # We don't want to silence connection errors, but now we want to see
        # (success, failed) from send_messages).
        connection.fail_silently = True
        success, failed = connection.send_messages(messages)

        log.info('%d failed messages' % len(failed))
        log.debug([x.to for x in failed])
        log.info('%d successful messages' % len(success))

        for msg in success:
            dest = msg.to[0]
            sent = Recipient(subscriber_id=emails[dest].id, email_id=self.email.id)
            try:
                sent.validate_unique()
            except ValidationError, e:
                # Already exists? Sending was probably forced.
                pass
            else:
                sent.save()

        connection.close()

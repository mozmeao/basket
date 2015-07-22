from uuid import uuid4

from django.conf import settings
from django.core.mail import send_mail
from django.db import models
from django.template.loader import render_to_string
from django.utils.timezone import now

import product_details
from celery.task import subtask
from jsonfield import JSONField

from news.fields import CommaSeparatedEmailField, LocaleField


def get_uuid():
    """Needed because Django can't make migrations when using lambda."""
    return str(uuid4())


class BlockedEmail(models.Model):
    email_domain = models.CharField(max_length=50)


class Newsletter(models.Model):
    slug = models.SlugField(
        unique=True,
        help_text="The ID for the newsletter that will be used by clients",
    )
    title = models.CharField(
        max_length=128,
        help_text="Public name of newsletter in English",
    )
    description = models.CharField(
        max_length=256,
        help_text="One-line description of newsletter in English",
        blank=True,
    )
    show = models.BooleanField(
        default=False,
        help_text="Whether to show this newsletter in lists of newsletters, "
                  "even to non-subscribers",
    )
    active = models.BooleanField(
        default=True,
        help_text="Whether this newsletter is active. Inactive newsletters "
                  "are only shown to those who are already subscribed, and "
                  "might have other differences in behavior.",
    )
    # Note: use .welcome_id property to get this field or the default
    welcome = models.CharField(
        max_length=64,
        help_text="The ID of the welcome message sent for this newsletter. "
                  "This is the HTML version of the message; append _T to this "
                  "ID to get the ID of the text-only version.  If blank, "
                  "no welcome is sent",
        blank=True,
    )
    vendor_id = models.CharField(
        max_length=128,
        help_text="The backend vendor's identifier for this newsletter",
    )
    languages = models.CharField(
        max_length=200,
        help_text="Comma-separated list of the language codes that this "
                  "newsletter supports",
    )
    requires_double_optin = models.BooleanField(
        default=False,
        help_text="True if subscribing to this newsletter requires someone"
                  "to respond to a confirming email.",
    )
    order = models.IntegerField(
        default=0,
        help_text="Order to display the newsletters on the web site. "
                  "Newsletters with lower order numbers will display first."
    )
    confirm_message = models.CharField(
        max_length=64,
        help_text="The ID of the confirm message sent for this newsletter."
                  "That's the one that says 'please click here to confirm'."
                  "If blank, a default message based on the user's language "
                  "is sent.",
        blank=True,
    )

    def __unicode__(self):
        return self.title

    class Meta(object):
        ordering = ['order']

    def save(self, *args, **kwargs):
        # Strip whitespace from langs before save
        # Also confirm_message or welcome
        self.languages = self.languages.replace(" ", "")
        self.welcome = self.welcome.strip()
        self.confirm_message = self.confirm_message.strip()
        super(Newsletter, self).save(*args, **kwargs)

    @property
    def welcome_id(self):
        """Return newsletter's welcome message ID, or the default one"""
        return self.welcome or settings.DEFAULT_WELCOME_MESSAGE_ID

    @property
    def language_list(self):
        """Return language codes for this newsletter as a list"""
        return [x.strip() for x in self.languages.split(",")]


class NewsletterGroup(models.Model):
    slug = models.SlugField(
        unique=True,
        help_text='The ID for the group that will be used by clients',
    )
    title = models.CharField(
        max_length=128,
        help_text='Public name of group in English',
    )
    description = models.CharField(
        max_length=256,
        help_text='One-line description of group in English',
        blank=True,
    )
    show = models.BooleanField(
        default=False,
        help_text='Whether to show this group in lists of newsletters and groups, '
                  'even to non-subscribers',
    )
    active = models.BooleanField(
        default=False,
        help_text='Whether this group should be considered when subscription '
                  'requests are received.',
    )
    newsletters = models.ManyToManyField(Newsletter, related_name='newsletter_groups')

    def newsletter_slugs(self):
        return [nl.slug for nl in self.newsletters.all()]


class APIUser(models.Model):
    """On some API calls, an API key must be passed that must
    exist in this table."""
    name = models.CharField(
        max_length=256,
        help_text="Descriptive name of this user"
    )
    api_key = models.CharField(max_length=40,
                               default=get_uuid,
                               db_index=True)
    enabled = models.BooleanField(default=True)

    class Meta:
        verbose_name = "API User"

    @classmethod
    def is_valid(cls, api_key):
        return cls.objects.filter(api_key=api_key, enabled=True).exists()


def _is_query_dict(arg):
    """Returns boolean True if arg appears to have been a QueryDict."""
    if not isinstance(arg, dict):
        return False

    return all(isinstance(i, list) for i in arg.values())


class FailedTask(models.Model):
    when = models.DateTimeField(editable=False, default=now)
    task_id = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255)
    args = JSONField(null=False, default=[])
    kwargs = JSONField(null=False, default={})
    exc = models.TextField(null=True, default=None, help_text=u"repr(exception)")
    einfo = models.TextField(null=True, default=None, help_text=u"repr(einfo)")

    def __unicode__(self):
        return self.task_id

    def formatted_call(self):
        """Return a string that could be evalled to repeat the original call"""
        formatted_args = [repr(arg) for arg in self.args]
        formatted_kwargs = [u"%s=%r" % (key, val) for key, val in self.kwargs.iteritems()]
        return u"%s(%s)" % (
            self.name,
            u", ".join(formatted_args + formatted_kwargs)
        )

    @property
    def filtered_args(self):
        """
        Convert args that came from QueryDict instances to regular dicts.

        This is necessary because some tasks were bing called with QueryDict
        instances, and whereas the Pickle for the task worked fine, storing
        the args as JSON resulted in the dicts actually being a dict full
        of length 1 lists instead of strings. This converts them back when
        it finds them.

        This only needs to exist while we have old failure instances around.

        @return: list args: serialized QueryDicts converted to plain dicts.
        """
        # TODO remove after old failed tasks are deleted
        args = self.args
        for i, arg in enumerate(args):
            if _is_query_dict(arg):
                args[i] = dict((key, arg[key][0]) for key in arg)

        return args

    def retry(self):
        # Meet the new task,
        # same as the old task.
        new_task = subtask(self.name, args=self.filtered_args, kwargs=self.kwargs)
        # Queue the new task.
        new_task.apply_async()
        # Forget the old task
        self.delete()


class Interest(models.Model):
    title = models.CharField(
        max_length=128,
        help_text='Public name of interest in English',
    )
    interest_id = models.SlugField(
        unique=True, db_index=True,
        help_text='The ID for the interest that will be used by clients',
    )
    # Note: use .welcome_id property to get this field or the default
    _welcome_id = models.CharField(
        max_length=64,
        help_text='The ID of the welcome message sent for this interest. '
                  'This is the HTML version of the message; append _T to this '
                  'ID to get the ID of the text-only version.  If blank, '
                  'welcome message ID will be assumed to be the same as '
                  'the interest_id',
        blank=True,
        verbose_name='Welcome ID',
    )
    default_steward_emails = CommaSeparatedEmailField(
        blank=True,
        help_text='Comma-separated list of the default / en-US stewards\' email addresses.',
        verbose_name='Default / en-US Steward Emails',
    )

    @property
    def welcome_id(self):
        return self._welcome_id or self.interest_id

    def notify_stewards(self, name, email, lang, message):
        """
        Send an email to the stewards about a new interested
        subscriber.
        """
        email_body = render_to_string('news/get_involved/steward_email.txt', {
            'contributor_name': name,
            'contributor_email': email,
            'interest': self,
            'lang': lang,
            'message': message,
        })

        # Find the right stewards for the given language.
        try:
            stewards = self.localestewards_set.get(locale=lang)
            emails = stewards.emails
        except LocaleStewards.DoesNotExist:
            emails = self.default_steward_emails
        emails = emails.split(',')

        send_mail('Inquiry about {0}'.format(self.title), email_body, 'basket@basket.mozilla.org',
                  emails)

    def __unicode__(self):
        return self.title


class LocaleStewards(models.Model):
    """
    List of steward emails for a specific interest-locale combination.
    """
    interest = models.ForeignKey(Interest)
    locale = LocaleField()
    emails = CommaSeparatedEmailField(
        blank=False,
        help_text='Comma-separated list of the stewards\' email addresses.',
    )

    class Meta:
        unique_together = ('interest', 'locale')
        verbose_name = 'Locale Steward'
        verbose_name_plural = 'Locale Stewards'

    def __unicode__(self):
        return u'Stewards for {lang_code} ({lang_name})'.format(
            lang_code=self.locale,
            lang_name=product_details.languages[self.locale]['English'],
        )


class SMSMessage(models.Model):
    message_id = models.SlugField(
        primary_key=True,
        help_text='The ID for the message that will be used by clients',
    )
    vendor_id = models.CharField(
        max_length=50,
        help_text="The backend vendor's identifier for this message",
    )
    description = models.CharField(
        max_length=200, blank=True,
        help_text='Optional short description of this message'
    )

    class Meta:
        verbose_name = "SMS message"

from uuid import uuid4

from jsonfield import JSONField

from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils.timezone import now


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
            # FIXME: this could mean there's another record in Exact Target
            # with the other token

        return sub


class Subscriber(models.Model):
    email = models.EmailField(primary_key=True)
    token = models.CharField(max_length=40, default=lambda: str(uuid4()),
                             db_index=True)

    objects = SubscriberManager()


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

        # Cannot import earlier due to circular import
        from news.newsletters import clear_newsletter_cache

        # Newsletter data might have changed, forget our cached version of it
        clear_newsletter_cache()

    @property
    def welcome_id(self):
        """Return newsletter's welcome message ID, or the default one"""
        return self.welcome or settings.DEFAULT_WELCOME_MESSAGE_ID

    @property
    def language_list(self):
        """Return language codes for this newsletter as a list"""
        return [x.strip() for x in self.languages.split(",")]


@receiver(post_delete, sender=Newsletter)
def post_newsletter_delete(sender, **kwargs):
    # Cannot import earlier due to circular import
    from news.newsletters import clear_newsletter_cache
    clear_newsletter_cache()


class APIUser(models.Model):
    """On some API calls, an API key must be passed that must
    exist in this table."""
    name = models.CharField(
        max_length=256,
        help_text="Descriptive name of this user"
    )
    api_key = models.CharField(max_length=40,
                               default=lambda: str(uuid4()),
                               db_index=True)
    enabled = models.BooleanField(default=True)

    class Meta:
        verbose_name = "API User"

    @classmethod
    def is_valid(cls, api_key):
        return cls.objects.filter(api_key=api_key, enabled=True).exists()


class FailedTask(models.Model):
    when = models.DateTimeField(editable=False, default=now)
    task_id = models.CharField(max_length=255, unique=True)
    name = models.CharField(max_length=255)
    args = JSONField(null=False, default=[])
    kwargs = JSONField(null=False, default={})
    exc = models.TextField(null=True, default=None, help_text=u"repr(exception)")
    einfo = models.TextField(null=True, default=None, help_text=u"repr(einfo)")

    def __unicode__(self):
        return u"%s --> %r, %r" % (self.formatted_call(), self.exc, self.einfo)

    def formatted_call(self):
        """Return a string that could be evalled to repeat the original call"""
        formatted_args = [repr(arg) for arg in self.args]
        formatted_kwargs = [u"%s=%r" % (key, val) for key, val in self.kwargs.iteritems()]
        return u"%s(%s)" % (
            self.name,
            u", ".join(formatted_args + formatted_kwargs)
        )

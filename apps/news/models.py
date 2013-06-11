from uuid import uuid4

from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver


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
    slug = models.SlugField(unique=True)
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
                  "default is %s." % settings.DEFAULT_WELCOME_MESSAGE_ID,
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

    def __unicode__(self):
        return self.title

    def save(self, *args, **kwargs):
        # Strip whitespace from langs before save
        self.languages = self.languages.replace(" ", "")
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

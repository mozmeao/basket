from uuid import uuid4

from django.conf import settings
from django.db import models
from django.utils.timezone import now

import sentry_sdk

from basket import metrics
from basket.base.rq import get_enqueue_kwargs, get_queue
from basket.news.fields import LocaleField


def get_uuid():
    """Needed because Django can't make migrations when using lambda."""
    return str(uuid4())


class BlockedEmail(models.Model):
    email_domain = models.CharField(max_length=50)

    def __str__(self):  # pragma: no cover
        return self.email_domain


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
        help_text="Whether to show this newsletter in lists of newsletters, even to non-subscribers",
    )
    active = models.BooleanField(
        default=True,
        help_text=(
            "Whether this newsletter is active. Inactive newsletters "
            "are only shown to those who are already subscribed, and "
            "might have other differences in behavior."
        ),
    )
    private = models.BooleanField(
        default=False,
        help_text="Whether this newsletter is private. Private newsletters require the subscribe requests to use an API key.",
    )
    indent = models.BooleanField(
        default=False,
        help_text="Whether this newsletter is indented in the email preference center.",
    )
    vendor_id = models.CharField(
        max_length=128,
        help_text="The backend vendor's identifier for this newsletter",
    )
    languages = models.CharField(
        max_length=200,
        help_text="Comma-separated list of the language codes that this newsletter supports",
    )
    requires_double_optin = models.BooleanField(
        default=False,
        help_text="True if subscribing to this newsletter requires someone to respond to a confirming email.",
    )
    firefox_confirm = models.BooleanField(
        default=False,
        help_text="Whether to send the Firefox or Mozilla branded confirmation message for this newsletter",
    )
    is_mofo = models.BooleanField(
        default=False,
        help_text="True if subscribing to this newsletter should mark someone as relevant to the Mozilla Foundation",
    )
    is_waitlist = models.BooleanField(
        default=False,
        help_text="True if the newsletter is a waiting list. A waitlist can have additional arbitrary fields.",
    )
    order = models.IntegerField(
        default=0,
        help_text="Order to display the newsletters on the web site. Newsletters with lower order numbers will display first.",
    )

    class Meta:
        ordering = ["order"]

    def __str__(self):  # pragma: no cover
        return self.title

    def save(self, *args, **kwargs):
        # Strip whitespace from langs before save
        self.languages = self.languages.replace(" ", "")
        super().save(*args, **kwargs)

    @property
    def language_list(self):
        """Return language codes for this newsletter as a list"""
        return [x.strip() for x in self.languages.split(",") if x.strip()]


class NewsletterGroup(models.Model):
    slug = models.SlugField(
        unique=True,
        help_text="The ID for the group that will be used by clients",
    )
    title = models.CharField(
        max_length=128,
        help_text="Public name of group in English",
    )
    description = models.CharField(
        max_length=256,
        help_text="One-line description of group in English",
        blank=True,
    )
    show = models.BooleanField(
        default=False,
        help_text="Whether to show this group in lists of newsletters and groups, even to non-subscribers",
    )
    active = models.BooleanField(
        default=False,
        help_text="Whether this group should be considered when subscription requests are received.",
    )
    newsletters = models.ManyToManyField(Newsletter, related_name="newsletter_groups")

    def __str__(self):  # pragma: no cover
        return f"{self.title} ({self.slug})"

    def newsletter_slugs(self):
        return [nl.slug for nl in self.newsletters.all()]


class APIUser(models.Model):
    """On some API calls, an API key must be passed that must
    exist in this table."""

    name = models.CharField(max_length=256, help_text="Descriptive name of this user")
    api_key = models.CharField(max_length=40, default=get_uuid, db_index=True)
    enabled = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)
    last_accessed = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "API User"

    def __str__(self):  # pragma: no cover
        return f"{self.name} ({self.api_key})"

    @classmethod
    def is_valid(cls, api_key: str) -> bool:
        """
        Checks if the API key is valid and enabled.

        Updates the `last_accessed` field if the key is valid.

        Returns:
            bool: True if the API key is valid and enabled, False otherwise.

        """
        try:
            obj = cls.objects.get(api_key=api_key)
            if obj.enabled:
                obj.last_accessed = now()
                obj.save(update_fields=["last_accessed"])
                metrics.incr("api.key.is_valid", tags=["value:true"])
                return True
        except APIUser.DoesNotExist:
            pass

        metrics.incr("api.key.is_valid", tags=["value:false"])
        return False


def _is_query_dict(arg):
    """Returns boolean True if arg appears to have been a QueryDict."""
    if not isinstance(arg, dict):
        return False

    return all(isinstance(i, list) for i in arg.values())


class QueuedTask(models.Model):
    when = models.DateTimeField(editable=False, default=now)
    name = models.CharField(max_length=255)
    args = models.JSONField(null=False, default=list)
    kwargs = models.JSONField(null=False, default=dict)

    class Meta:
        ordering = ["pk"]

    def __str__(self):  # pragma: no cover
        return f"{self.name} {self.args} {self.kwargs}"

    def retry(self):
        kwargs = get_enqueue_kwargs(self.name)
        get_queue().enqueue(self.name, args=self.args, kwargs=self.kwargs, **kwargs)
        # Forget the old task.
        self.delete()


class FailedTask(models.Model):
    when = models.DateTimeField(editable=False, default=now)
    task_id = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    args = models.JSONField(null=False, default=list)
    kwargs = models.JSONField(null=False, default=dict)
    exc = models.TextField(null=True, default=None, help_text="repr(exception)")  # noqa
    einfo = models.TextField(null=True, default=None, help_text="repr(einfo)")  # noqa

    def __str__(self):  # pragma: no cover
        return self.task_id

    def formatted_call(self):
        """Return a string that could be evalled to repeat the original call"""
        formatted_args = [repr(arg) for arg in self.args]
        formatted_kwargs = [f"{key}={val!r}" for key, val in self.kwargs.items()]
        return f"{self.name}({', '.join(formatted_args + formatted_kwargs)})"

    def retry(self):
        kwargs = get_enqueue_kwargs(self.name)
        get_queue().enqueue(self.name, args=self.args, kwargs=self.kwargs, **kwargs)
        # Forget the old task
        self.delete()


class BrazeTxEmailMessageManager(models.Manager):
    def get_message(self, message_id, language):
        message = None
        req_language = language  # Store this for error reporting below.
        language = language.strip() or "en-US"
        exc = BrazeTxEmailMessage.DoesNotExist
        try:
            # try to get the exact language
            message = self.get(message_id=message_id, language=language)
        except exc:
            if "-" in language:
                language = language.split("-")[0]

            try:
                # failing above, try to get the language prefix
                message = self.get(message_id=message_id, language__startswith=language)
            except exc:
                try:
                    # failing above, try to get the default language
                    message = self.get(message_id=message_id, language="en-US")
                except exc:
                    # couldn't find a message. give up.
                    with sentry_sdk.isolation_scope() as scope:
                        scope.set_tag("language", req_language)
                        scope.set_tag("message_id", message_id)
                        sentry_sdk.capture_exception()

        return message

    def get_tx_message_ids(self):
        return list(set(list(self.filter(private=False).values_list("message_id", flat=True)) + list(settings.BRAZE_MESSAGE_ID_MAP.keys())))


class BrazeTxEmailMessage(models.Model):
    message_id = models.SlugField(
        help_text="The ID for the message that will be used by clients",
    )
    description = models.CharField(
        max_length=200,
        blank=True,
        help_text="Optional short description of this message",
    )
    language = LocaleField(default="en-US")
    private = models.BooleanField(
        default=False,
        help_text="Whether this email is private. Private emails are not allowed to be sent via the normal subscribe API.",
    )

    objects = BrazeTxEmailMessageManager()

    class Meta:
        unique_together = ["message_id", "language"]
        verbose_name = "Braze transactional email"
        ordering = ["message_id"]

    def __str__(self):  # pragma: no cover
        return f"{self.message_id}: {self.language}"

from urllib.parse import urljoin

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlsafe_base64_encode

from basket.petition.tasks import send_email_confirmation


class Petition(models.Model):
    # Displayed to the user:
    name = models.CharField(max_length=255)
    email = models.EmailField()
    title = models.CharField(max_length=255, blank=True)
    affiliation = models.CharField(max_length=255, blank=True)
    # Admin use:
    verified_general = models.BooleanField(default=False, help_text="General spot-check verification")
    verified_linkedin = models.BooleanField(default=False, help_text="LinkedIn verification")
    verified_research = models.BooleanField(default=False, help_text="Research verification")
    approved = models.BooleanField(default=False)
    vip = models.BooleanField(default=False)
    # Internal use:
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    referrer = models.TextField(blank=True)
    token = models.UUIDField()
    email_confirmed = models.BooleanField(default=False)
    created = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "petition"
        verbose_name = "Petition"
        verbose_name_plural = "Petitions"

    def __str__(self):
        return f"{self.name}, {self.title} ({self.email})"

    def send_email_confirmation(self):
        # Send email confirmation.
        pidb64 = urlsafe_base64_encode(str(self.pk).encode())
        confirm_link = urljoin(settings.SITE_URL, reverse("confirm-token", args=[pidb64, self.token]))
        send_email_confirmation.delay(self.name, self.email, confirm_link)

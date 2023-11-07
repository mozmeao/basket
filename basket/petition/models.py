from django.db import models
from django.utils import timezone


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

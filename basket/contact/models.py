from django.db import models

DEST_TYPES = [("gsheet", "Google Sheet")]
# v1 only offers gsheet as an admin choice. more destinations will follow.

STATUS = [("queued", "queued"), ("delivered", "delivered"), ("failed", "failed")]

class FormRoute(models.Model):
    form_id = models.SlugField(unique=True, help_text='e.g. "enterprise-contact"')
    name = models.CharField(max_length=255, help_text='e.g. "Enterprise Contact Form"')
    active = models.BooleanField(default=False)
    created_by = models.CharField(max_length=255, help_text="Email, for audit trail")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):  # pragma: no cover
        return f"{self.name} ({self.form_id})"


class FormDestination(models.Model):
    route = models.ForeignKey(FormRoute, on_delete=models.CASCADE, related_name="destinations")
    dest_type = models.CharField(max_length=20, choices=DEST_TYPES)
    label = models.CharField(max_length=255)
    config = models.JSONField(help_text='gsheet: {"sheet_id": "...", "tab": "Responses"}')
    field_map = models.JSONField(help_text='gsheet: {"email": "A", "first_name": "B"} -- CMS field to column letter')
    active = models.BooleanField(default=True)
    # No ignore_unmapped field -- v1 always discards unmapped fields at delivery time,
    # matching what's stated in the Springfield-facing contract.

    def __str__(self):  # pragma: no cover
        return f"{self.label} ({self.dest_type})"


class FormSubmission(models.Model):
    route = models.ForeignKey(FormRoute, on_delete=models.PROTECT, related_name="submissions")
    payload = models.JSONField(help_text="Raw, unmodified CMS data")
    source_url = models.URLField(blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS, default="queued")

    def __str__(self):  # pragma: no cover
        return f"{self.route.form_id} @ {self.received_at:%Y-%m-%d %H:%M}"

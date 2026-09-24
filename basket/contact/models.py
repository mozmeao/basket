from django.core.exceptions import ValidationError
from django.db import models

DEST_TYPES = [("gsheet", "Google Sheet")]

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
    field_map = models.JSONField(
        help_text='gsheet: {"email": "Business Email", "first_name": "First Name"} -- CMS field to the '
        "sheet's own header text (row 1), matched at delivery time -- not a fixed column letter, so "
        "reordering columns or adding new ones later doesn't misalign already-delivered rows."
    )
    active = models.BooleanField(default=True)
    next_row = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Sheet row the next gsheet delivery will claim; managed automatically, do not edit.",
    )

    def __str__(self):  # pragma: no cover
        return f"{self.label} ({self.dest_type})"

    def clean(self):
        super().clean()
        # full_clean() calls this even after required-field errors, so values may be empty.
        if self.dest_type == "gsheet" and self.config:
            if not isinstance(self.config, dict):
                raise ValidationError({"config": "gsheet config must be a JSON object."})
            missing = [key for key in ("sheet_id", "tab") if not isinstance(self.config.get(key), str) or not self.config[key].strip()]
            if missing:
                raise ValidationError({"config": f"gsheet config needs non-empty values for: {', '.join(missing)}"})

        if self.dest_type == "gsheet" and self.field_map:
            if not isinstance(self.field_map, dict):
                raise ValidationError({"field_map": "gsheet field_map must be a JSON object mapping CMS field to header text."})

            bad = {field: header for field, header in self.field_map.items() if not isinstance(header, str) or not header.strip()}
            if bad:
                raise ValidationError({"field_map": f"gsheet field_map values must be non-empty header text: {bad}"})

            headers = list(self.field_map.values())
            duplicates = {header for header in headers if headers.count(header) > 1}
            if duplicates:
                raise ValidationError({"field_map": f"gsheet field_map headers must be unique -- mapped more than once: {duplicates}"})


class FormSubmission(models.Model):
    route = models.ForeignKey(FormRoute, on_delete=models.PROTECT, related_name="submissions")
    payload = models.JSONField(help_text="Raw, unmodified CMS data")
    source_url = models.URLField(blank=True, max_length=2000)
    received_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS, default="queued")

    def __str__(self):  # pragma: no cover
        return f"{self.route.form_id} @ {self.received_at:%Y-%m-%d %H:%M}"


class FormDelivery(models.Model):
    # Per-destination status, plus the claimed row so an RQ retry reuses it.
    submission = models.ForeignKey(FormSubmission, on_delete=models.CASCADE, related_name="deliveries")
    destination = models.ForeignKey(FormDestination, on_delete=models.CASCADE, related_name="deliveries")
    status = models.CharField(max_length=20, choices=STATUS, default="queued")
    row_number = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        unique_together = ("submission", "destination")

    def __str__(self):  # pragma: no cover
        return f"{self.submission_id} -> {self.destination_id} @ row {self.row_number}"

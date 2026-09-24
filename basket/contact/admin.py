from django.contrib import admin, messages

from .intake_tasks import deliver_to_gsheet
from .models import FormDelivery, FormDestination, FormRoute, FormSubmission


class FormDestinationInline(admin.TabularInline):
    model = FormDestination
    extra = 1
    readonly_fields = ["next_row"]


@admin.register(FormRoute)
class FormRouteAdmin(admin.ModelAdmin):
    inlines = [FormDestinationInline]
    list_display = ["form_id", "name", "active", "created_by", "created_at"]
    actions = ["test_delivery"]

    @admin.action(description="Send a test submission through each active destination (writes a real row to the configured destination)")
    def test_delivery(self, request, queryset):
        for route in queryset:
            destinations = route.destinations.filter(active=True)
            if not destinations.exists():
                self.message_user(request, f"{route.form_id}: no active destinations to test.", messages.WARNING)
                continue

            fields = {field for destination in destinations for field in destination.field_map} | {"email", "first_name"}
            data = {field: f"basket-admin-test_{field}" for field in fields}
            data["email"] = "basket-admin-test_email@example.invalid"

            submission = FormSubmission.objects.create(
                route=route,
                payload={"form_id": route.form_id, "data": data, "source_url": ""},
            )
            for destination in destinations:
                if destination.dest_type != "gsheet":
                    msg = f"{route.form_id} -> {destination.label}: skipped, unsupported dest_type {destination.dest_type!r}."
                    self.message_user(request, msg, messages.WARNING)
                    continue
                try:
                    deliver_to_gsheet(submission.id, destination.id)
                except Exception as exc:
                    self.message_user(request, f"{route.form_id} -> {destination.label}: failed ({exc})", messages.ERROR)
                else:
                    self.message_user(request, f"{route.form_id} -> {destination.label}: delivered successfully.", messages.SUCCESS)


class FormDeliveryInline(admin.TabularInline):
    model = FormDelivery
    fields = ["destination", "status", "row_number"]
    readonly_fields = ["destination", "status", "row_number"]
    extra = 0
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(FormSubmission)
class FormSubmissionAdmin(admin.ModelAdmin):
    inlines = [FormDeliveryInline]
    list_display = ["route", "status", "received_at", "source_url"]
    list_filter = ["status", "route"]
    readonly_fields = ["route", "payload", "source_url", "received_at", "status"]

    def has_add_permission(self, request):
        # Audit trail: only the intake endpoint and the test action create these.
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

from django.contrib import admin

from basket.petition.models import Petition


@admin.register(Petition)
class PetitionAdmin(admin.ModelAdmin):
    date_hierarchy = "created"
    ordering = ["-created"]
    list_display = [
        "name",
        "email",
        "title",
        "affiliation",
        "email_confirmed",
        "verified_general",
        "verified_linkedin",
        "verified_research",
        "approved",
    ]
    search_fields = ["name", "email", "title", "affiliation"]
    list_filter = ["email_confirmed", "verified_general", "verified_linkedin", "verified_research", "approved"]
    list_editable = ["verified_general", "verified_linkedin", "verified_research", "approved"]
    readonly_fields = ["ip", "user_agent", "referrer", "token", "email_confirmed", "created"]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "email",
                    "title",
                    "affiliation",
                    "email_confirmed",
                    "verified_general",
                    "verified_linkedin",
                    "verified_research",
                    "approved",
                )
            },
        ),
        (
            "Internal",
            {
                "fields": (
                    "ip",
                    "user_agent",
                    "referrer",
                    "token",
                    "created",
                ),
                "classes": ("collapse",),
            },
        ),
    )

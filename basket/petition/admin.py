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
        "vip",
    ]
    search_fields = ["name", "email", "title", "affiliation"]
    list_filter = ["email_confirmed", "verified_general", "verified_linkedin", "verified_research", "approved", "vip"]
    list_editable = ["verified_general", "verified_linkedin", "verified_research", "approved", "vip"]
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
                    "vip",
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

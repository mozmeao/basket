from django.conf import settings
from django.contrib import admin
from django.urls import path

import requests

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

    def get_urls(self):
        if settings.PETITION_BUILD_HOOK_URL is None:
            return super().get_urls()

        admin_urls = super().get_urls()
        urls = [
            path("publish/", self.admin_site.admin_view(self.publish), name="publish_petitions"),
        ]
        return urls + admin_urls

    def publish(self, request):
        if settings.PETITION_BUILD_HOOK_URL is None:
            return super().changelist_view(request)

        requests.post(
            settings.PETITION_BUILD_HOOK_URL,
            data={"trigger_title": "Publish petitions from Basket"},
        )
        self.message_user(request, "Petitions published.")
        return super().changelist_view(request)

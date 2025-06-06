from django.conf import settings
from django.contrib import admin, messages
from django.template.defaultfilters import pluralize

from product_details import product_details

from basket.news.models import (
    APIUser,
    BlockedEmail,
    BrazeTxEmailMessage,
    FailedTask,
    Newsletter,
    NewsletterGroup,
    QueuedTask,
)


class LanguageFilter(admin.SimpleListFilter):
    """Only show languages in the filter that are used in a message"""

    title = "language"
    parameter_name = "language"

    def lookups(self, request, model_admin):
        qs = model_admin.get_queryset(request)
        langs = sorted(set(qs.values_list("language", flat=True)))
        return [(k, f"{k} ({product_details.languages[k]['English']})") for k in langs]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(language=self.value())


@admin.register(BrazeTxEmailMessage)
class BrazeTxEmailMessageAdmin(admin.ModelAdmin):
    fields = ("message_id", "language", "description", "private")
    list_display = ("message_id", "language", "description", "private")
    search_fields = ("message_id", "description")
    list_filter = ("private", "message_id", LanguageFilter)


@admin.register(BlockedEmail)
class BlockedEmailAdmin(admin.ModelAdmin):
    fields = ("email_domain",)
    list_display = ("email_domain",)


@admin.register(NewsletterGroup)
class NewsletterGroupAdmin(admin.ModelAdmin):
    fields = ("title", "slug", "description", "show", "active", "newsletters")
    list_display = ("title", "slug", "show", "active")
    list_display_links = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}


@admin.register(APIUser)
class APIUserAdmin(admin.ModelAdmin):
    list_display = ("name", "enabled", "created", "last_accessed")
    readonly_fields = ("api_key", "created", "last_accessed")


@admin.register(Newsletter)
class NewsletterAdmin(admin.ModelAdmin):
    fields = (
        "title",
        "slug",
        "vendor_id",
        "description",
        "languages",
        "show",
        "order",
        "active",
        "indent",
        "requires_double_optin",
        "firefox_confirm",
        "private",
        "is_mofo",
        "is_waitlist",
    )
    list_display = (
        "order",
        "title",
        "slug",
        "vendor_id",
        "languages",
        "show",
        "active",
        "indent",
        "requires_double_optin",
        "firefox_confirm",
        "private",
        "is_mofo",
        "is_waitlist",
    )
    list_display_links = ("title", "slug")
    list_editable = (
        "order",
        "show",
        "active",
        "indent",
        "requires_double_optin",
        "firefox_confirm",
        "private",
        "is_mofo",
    )
    list_filter = (
        "show",
        "active",
        "requires_double_optin",
        "firefox_confirm",
        "private",
        "is_mofo",
        "is_waitlist",
    )
    prepopulated_fields = {"slug": ("title",)}
    search_fields = ("title", "slug", "description", "vendor_id")


class TaskNameFilter(admin.SimpleListFilter):
    """Filter to provide nicer names for task names."""

    title = "task name"
    parameter_name = "name"

    def lookups(self, request, model_admin):
        qs = model_admin.get_queryset(request)
        names = qs.values_list("name", flat=True).distinct().order_by("name")
        return [(name, name.rsplit(".", 1)[1].replace("_", " ")) for name in names]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(name=self.value())

        return queryset


@admin.register(QueuedTask)
class QueuedTaskAdmin(admin.ModelAdmin):
    list_display = ("when", "name")
    list_filter = (TaskNameFilter,)
    search_fields = ("name",)
    date_hierarchy = "when"
    actions = ["retry_task_action"]

    @admin.action(description="Process task(s)")
    def retry_task_action(self, request, queryset):
        """Admin action to retry some tasks that were queued for maintenance"""
        if settings.MAINTENANCE_MODE:
            messages.error(request, "Maintenance mode enabled. Tasks not processed.")
            return

        count = 0
        for old_task in queryset:
            old_task.retry()
            count += 1
        messages.info(request, f"Queued {count} task{pluralize(count)} to process.")


@admin.register(FailedTask)
class FailedTaskAdmin(admin.ModelAdmin):
    list_display = ("when", "name", "formatted_call", "exc")
    list_filter = (TaskNameFilter,)
    search_fields = ("name", "exc")
    date_hierarchy = "when"
    actions = ["retry_task_action"]

    @admin.action(description="Retry task(s)")
    def retry_task_action(self, request, queryset):
        """Admin action to retry some tasks that have failed previously"""
        count = 0
        for old_task in queryset:
            old_task.retry()
            count += 1
        messages.info(request, f"Queued {count} task{pluralize(count)} to try again.")


@admin.register(admin.models.LogEntry)
class LogEntryAdmin(admin.ModelAdmin):
    list_display = ("action_time", "user", "__str__")
    list_filter = ("user", "content_type")

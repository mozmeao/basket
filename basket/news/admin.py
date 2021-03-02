from django.conf import settings
from django.contrib import admin, messages

from product_details import product_details

from basket.news.models import (
    AcousticTxEmailMessage,
    APIUser,
    BlockedEmail,
    FailedTask,
    Interest,
    LocaleStewards,
    Newsletter,
    NewsletterGroup,
    QueuedTask,
    TransactionalEmailMessage,
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


class TransactionalEmailAdmin(admin.ModelAdmin):
    fields = ("message_id", "vendor_id", "languages", "description")
    list_display = ("message_id", "vendor_id", "languages", "description")


class AcousticTxEmailMessageAdmin(admin.ModelAdmin):
    fields = ("message_id", "vendor_id", "language", "description", "private")
    list_display = ("message_id", "vendor_id", "language", "description", "private")
    search_fields = ("message_id", "vendor_id", "description")
    list_filter = ("private", "message_id", "vendor_id", LanguageFilter)


class BlockedEmailAdmin(admin.ModelAdmin):
    fields = ("email_domain",)
    list_display = ("email_domain",)


class NewsletterGroupAdmin(admin.ModelAdmin):
    fields = ("title", "slug", "description", "show", "active", "newsletters")
    list_display = ("title", "slug", "show", "active")
    list_display_links = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}


class LocaleStewardsInline(admin.TabularInline):
    model = LocaleStewards
    fields = ("locale", "emails")


class InterestAdmin(admin.ModelAdmin):
    fields = ("title", "interest_id", "_welcome_id", "default_steward_emails")
    list_display = ("title", "interest_id", "_welcome_id", "default_steward_emails")
    list_editable = ("interest_id", "_welcome_id", "default_steward_emails")
    prepopulated_fields = {"interest_id": ("title",)}
    inlines = [LocaleStewardsInline]


class APIUserAdmin(admin.ModelAdmin):
    list_display = ("name", "enabled")


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
        "private",
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
        "private",
    )
    list_display_links = ("title", "slug")
    list_editable = (
        "order",
        "show",
        "active",
        "indent",
        "requires_double_optin",
        "private",
    )
    list_filter = ("show", "active", "requires_double_optin", "private")
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


class QueuedTaskAdmin(admin.ModelAdmin):
    list_display = ("when", "name")
    list_filter = (TaskNameFilter,)
    search_fields = ("name",)
    date_hierarchy = "when"
    actions = ["retry_task_action"]

    def retry_task_action(self, request, queryset):
        """Admin action to retry some tasks that were queued for maintenance"""
        if settings.MAINTENANCE_MODE:
            messages.error(request, "Maintenance mode enabled. Tasks not processed.")
            return

        count = 0
        for old_task in queryset:
            old_task.retry()
            count += 1
        messages.info(
            request, "Queued %d task%s to process" % (count, "" if count == 1 else "s"),
        )

    retry_task_action.short_description = "Process task(s)"


class FailedTaskAdmin(admin.ModelAdmin):
    list_display = ("when", "name", "formatted_call", "exc")
    list_filter = (TaskNameFilter,)
    search_fields = ("name", "exc")
    date_hierarchy = "when"
    actions = ["retry_task_action"]

    def retry_task_action(self, request, queryset):
        """Admin action to retry some tasks that have failed previously"""
        count = 0
        for old_task in queryset:
            old_task.retry()
            count += 1
        messages.info(
            request,
            "Queued %d task%s to try again" % (count, "" if count == 1 else "s"),
        )

    retry_task_action.short_description = "Retry task(s)"


class LogEntryAdmin(admin.ModelAdmin):
    list_display = ("action_time", "user", "__str__")
    list_filter = ("user", "content_type")


admin.site.register(TransactionalEmailMessage, TransactionalEmailAdmin)
admin.site.register(AcousticTxEmailMessage, AcousticTxEmailMessageAdmin)
admin.site.register(APIUser, APIUserAdmin)
admin.site.register(BlockedEmail, BlockedEmailAdmin)
admin.site.register(FailedTask, FailedTaskAdmin)
admin.site.register(QueuedTask, QueuedTaskAdmin)
admin.site.register(Interest, InterestAdmin)
admin.site.register(Newsletter, NewsletterAdmin)
admin.site.register(NewsletterGroup, NewsletterGroupAdmin)
admin.site.register(admin.models.LogEntry, LogEntryAdmin)

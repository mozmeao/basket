from django.contrib import admin, messages

from news.models import (APIUser, BlockedEmail, FailedTask, Interest, LocaleStewards, Newsletter,
                         NewsletterGroup, SMSMessage)


class SMSMessageAdmin(admin.ModelAdmin):
    fields = ('message_id', 'vendor_id', 'description')
    list_display = ('message_id', 'vendor_id', 'description')
    list_editable = ('vendor_id',)


class BlockedEmailAdmin(admin.ModelAdmin):
    fields = ('email_domain',)
    list_display = ('email_domain',)


class NewsletterGroupAdmin(admin.ModelAdmin):
    fields = ('title', 'slug', 'description', 'show', 'active', 'newsletters')
    list_display = ('title', 'slug', 'show', 'active')
    list_display_links = ('title', 'slug')
    prepopulated_fields = {"slug": ("title",)}


class LocaleStewardsInline(admin.TabularInline):
    model = LocaleStewards
    fields = ('locale', 'emails')


class InterestAdmin(admin.ModelAdmin):
    fields = ('title', 'interest_id', '_welcome_id', 'default_steward_emails')
    list_display = ('title', 'interest_id', '_welcome_id', 'default_steward_emails')
    list_editable = ('interest_id', '_welcome_id', 'default_steward_emails')
    prepopulated_fields = {'interest_id': ('title',)}
    inlines = [LocaleStewardsInline]


class APIUserAdmin(admin.ModelAdmin):
    list_display = ('name', 'enabled')


class NewsletterAdmin(admin.ModelAdmin):
    fields = ('title', 'slug', 'vendor_id', 'welcome', 'confirm_message',
              'description', 'languages', 'show', 'order', 'active',
              'requires_double_optin')
    list_display = ('order', 'title', 'slug', 'vendor_id', 'welcome',
                    'confirm_message', 'languages', 'show', 'active',
                    'requires_double_optin')
    list_display_links = ('title', 'slug')
    list_editable = ('order', 'show', 'active', 'requires_double_optin')
    list_filter = ('show', 'active', 'requires_double_optin')
    prepopulated_fields = {"slug": ("title",)}
    search_fields = ('title', 'slug', 'description', 'vendor_id')


class TaskNameFilter(admin.SimpleListFilter):
    """Filter to provide nicer names for task names."""
    title = 'task name'
    parameter_name = 'name'

    def lookups(self, request, model_admin):
        qs = model_admin.queryset(request)
        names = qs.values_list('name', flat=True).distinct().order_by('name')
        return [(name, name.rsplit('.', 1)[1].replace('_', ' ')) for name in names]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(name=self.value())

        return queryset


class FailedTaskAdmin(admin.ModelAdmin):
    list_display = ('when', 'name', 'formatted_call', 'exc')
    list_filter = (TaskNameFilter,)
    search_fields = ('name', 'exc')
    date_hierarchy = 'when'
    actions = ['retry_task_action']

    def retry_task_action(self, request, queryset):
        """Admin action to retry some tasks that have failed previously"""
        count = 0
        for old_task in queryset:
            old_task.retry()
            count += 1
        messages.info(request, "Queued %d task%s to try again" % (count, '' if count == 1 else 's'))
    retry_task_action.short_description = u"Retry task(s)"


admin.site.register(SMSMessage, SMSMessageAdmin)
admin.site.register(APIUser, APIUserAdmin)
admin.site.register(BlockedEmail, BlockedEmailAdmin)
admin.site.register(FailedTask, FailedTaskAdmin)
admin.site.register(Interest, InterestAdmin)
admin.site.register(Newsletter, NewsletterAdmin)
admin.site.register(NewsletterGroup, NewsletterGroupAdmin)

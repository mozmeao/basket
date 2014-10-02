from django.contrib import admin, messages

from .models import APIUser, FailedTask, Interest, Newsletter, Subscriber


class InterestAdmin(admin.ModelAdmin):
    fields = ('title', 'interest_id', '_welcome_id', 'steward_emails')
    list_display = ('title', 'interest_id', '_welcome_id', 'steward_emails')
    list_editable = ('interest_id', '_welcome_id', 'steward_emails')
    prepopulated_fields = {'interest_id': ('title',)}


admin.site.register(Interest, InterestAdmin)


class APIUserAdmin(admin.ModelAdmin):
    list_display = ('name', 'enabled')


admin.site.register(APIUser, APIUserAdmin)


class SubscriberAdmin(admin.ModelAdmin):
    fields = ('email', 'token', 'fxa_id')
    list_display = ('email', 'token', 'fxa_id')
    search_fields = ('email', 'token', 'fxa_id')


admin.site.register(Subscriber, SubscriberAdmin)


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


admin.site.register(Newsletter, NewsletterAdmin)


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


admin.site.register(FailedTask, FailedTaskAdmin)

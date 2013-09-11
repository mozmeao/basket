from django.contrib import admin, messages

from .models import APIUser, FailedTask, Newsletter, Subscriber


class APIUserAdmin(admin.ModelAdmin):
    list_display = ('name', 'enabled')


admin.site.register(APIUser, APIUserAdmin)


class SubscriberAdmin(admin.ModelAdmin):
    fields = ('email', 'token')
    list_display = ('email', 'token')
    search_fields = ('email', 'token')


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


class FailedTaskAdmin(admin.ModelAdmin):
    list_display = ('when', 'name', 'formatted_call', 'exc')
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

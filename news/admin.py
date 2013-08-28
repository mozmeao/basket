from django.contrib import admin

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
    list_display = ('when', '__unicode__')


admin.site.register(FailedTask, FailedTaskAdmin)

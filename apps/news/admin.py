from django.contrib import admin

from .models import Newsletter, Subscriber


class SubscriberAdmin(admin.ModelAdmin):
    fields = ('email', 'token')
    list_display = ('email', 'token')
    search_fields = ('email', 'token')


admin.site.register(Subscriber, SubscriberAdmin)


class NewsletterAdmin(admin.ModelAdmin):
    fields = ('title', 'slug', 'vendor_id', 'welcome', 'description',
              'languages', 'show', 'active', 'requires_double_optin')
    list_display = ('title', 'slug', 'vendor_id', 'welcome',
                    'languages', 'show', 'active', 'requires_double_optin')
    list_filter = ('show', 'active', 'requires_double_optin')
    prepopulated_fields = {"slug": ("title",)}
    search_fields = ('title', 'slug', 'description', 'vendor_id')


admin.site.register(Newsletter, NewsletterAdmin)

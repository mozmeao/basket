from django.contrib import admin

from .models import Newsletter, Subscriber


class SubscriberAdmin(admin.ModelAdmin):
    fields = ('email', 'token')
    list_display = ('email', 'token')
    search_fields = ('email', 'token')


admin.site.register(Subscriber, SubscriberAdmin)


class NewsletterAdmin(admin.ModelAdmin):
    list_display = ['title', 'show', 'active', 'description', 'welcome',
                    'languages']


admin.site.register(Newsletter, NewsletterAdmin)

from django.contrib import admin

from .models import Email


class EmailAdmin(admin.ModelAdmin):
    list_display = ('name', 'short_text', 'recipient_count')
    ordering = ('name',)

    def short_text(self, obj):
        short = obj.text[:80]
        if len(obj.text) > 80:
            short += '...'
        return short
    short_text.short_description = 'Text'

    def recipient_count(self, obj):
        return obj.recipients.count()

from django.contrib import admin

from .models import Email


class EmailAdmin(admin.ModelAdmin):
    list_display = ('name', 'short_subject', 'short_text', 'recipient_count')
    ordering = ('name',)

    def short_subject(self, obj):
        short = obj.subject[:80]
        if len(obj.subject) > 80:
            short += '...'
        return short
    short_subject.short_description = 'Subject'

    def short_text(self, obj):
        short = obj.text[:80]
        if len(obj.text) > 80:
            short += '...'
        return short
    short_text.short_description = 'Text'

    def recipient_count(self, obj):
        return obj.recipients.count()

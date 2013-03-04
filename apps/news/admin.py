from django.contrib import admin

from .models import Subscriber


class SubscriberAdmin(admin.ModelAdmin):
    model = Subscriber
    fields = ('email', 'token')
    list_display = ('email', 'token')
    search_fields = ('email', 'token')

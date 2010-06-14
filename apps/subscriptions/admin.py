from django.contrib import admin
from .models import Subscription, Subscriber


class SubscriptionInline(admin.TabularInline):
    model = Subscription


class SubscriberAdmin(admin.ModelAdmin):
    list_display = ('email', 'subscription_count')
    inlines = [SubscriptionInline,]

    def subscription_count(self, obj):
        return obj.subscriptions.count()

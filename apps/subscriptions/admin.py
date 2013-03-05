from django.contrib import admin
from .models import Subscription, Subscriber


class SubscriptionInline(admin.TabularInline):
    model = Subscription


class SubscriptionAdmin(admin.ModelAdmin):
    model = Subscription
    fields = ('subscriber', 'campaign', 'source', 'locale', 'created', 'active',)
    readonly_fields = ('subscriber', 'created')
    list_display = ('subscriber', 'campaign', 'source', 'locale', 'created',)
    list_filter = ('campaign', 'locale',)
    search_fields = ['subscriber__email', 'source']
    actions_on_top = False
    actions_on_bottom = False

class SubscriberAdmin(admin.ModelAdmin):
    list_display = ('email', 'subscription_count')
    inlines = [SubscriptionInline,]

    def subscription_count(self, obj):
        return obj.subscriptions.count()


admin.site.register(Subscription, SubscriptionAdmin)
admin.site.register(Subscriber, SubscriberAdmin)

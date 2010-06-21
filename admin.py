from django.contrib import admin
from django.contrib.auth.models import Group, User
from django.contrib.auth.admin import GroupAdmin, UserAdmin

from piston.models import Consumer
from basketauth.admin import ConsumerAdmin
from emailer.admin import EmailAdmin
from emailer.models import Email
from subscriptions.admin import SubscriptionAdmin
from subscriptions.models import Subscription


class BasketAdmin(admin.sites.AdminSite):
    pass

site = BasketAdmin()
site.register(Group, GroupAdmin)
site.register(User, UserAdmin)
site.register(Consumer, ConsumerAdmin)
site.register(Subscription, SubscriptionAdmin)
site.register(Email, EmailAdmin)

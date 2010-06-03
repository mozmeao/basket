from django.conf.urls.defaults import *
from piston.resource import Resource

from basketauth import BasketAuthentication
from .handlers import SubscriptionHandler

auth = BasketAuthentication()

subscribe = Resource(handler=SubscriptionHandler, authentication=auth)

urlpatterns = patterns('',
    url('^subscribe/$', subscribe),
)

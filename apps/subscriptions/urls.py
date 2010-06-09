from django.conf.urls.defaults import *

from piston.resource import Resource

from piston.authentication import NoAuthentication
from .handlers import SubscriptionHandler

auth = NoAuthentication()

subscribe = Resource(handler=SubscriptionHandler, authentication=auth)

urlpatterns = patterns('',
    url('^subscribe/$', subscribe, name='subscriptions.subscribe'),
)

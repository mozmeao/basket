from django.conf.urls.defaults import *

from piston.authentication import NoAuthentication

from csrf_exempt_resource import CsrfExemptResource
from .handlers import SubscriptionHandler


auth = NoAuthentication()

subscribe = CsrfExemptResource(handler=SubscriptionHandler, authentication=auth)

urlpatterns = patterns('',
    url('^subscribe/$', subscribe, name='subscriptions.subscribe'),
)



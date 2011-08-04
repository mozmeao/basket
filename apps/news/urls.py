from django.conf.urls.defaults import *
from views import subscribe, unsubscribe, user

urlpatterns = patterns('',
    url('^subscribe/$', subscribe),
    url('^unsubscribe/(.*)/$', unsubscribe),
    url('^user/(.*)/$', user)
)

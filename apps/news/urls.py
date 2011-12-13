from django.conf.urls.defaults import *
from views import (subscribe, unsubscribe, user,
                   delete_user, debug_user, custom_unsub_reason)

urlpatterns = patterns('',
    url('^subscribe/$', subscribe),
    url('^unsubscribe/(.*)/$', unsubscribe),
    url('^user/(.*)/$', user),
    url('^delete/(.*)/$', delete_user),
    url('^debug-user/$', debug_user),

    url('^custom_unsub_reason/$', custom_unsub_reason)
)

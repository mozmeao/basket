from django.conf.urls.defaults import *
from views import (subscribe, subscribe_sms, unsubscribe, user, confirm,
                   debug_user, custom_unsub_reason, custom_student_reps)

urlpatterns = patterns('',
    url('^subscribe/$', subscribe),
    url('^subscribe_sms/$', subscribe_sms),
    url('^unsubscribe/(.*)/$', unsubscribe),
    url('^user/(.*)/$', user),
    url('^confirm/(.*)/$', confirm),
    url('^debug-user/$', debug_user),

    url('^custom_unsub_reason/$', custom_unsub_reason),
    url('^custom_student_reps/$', custom_student_reps),
)

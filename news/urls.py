from django.conf.urls import patterns, url

from .views import (subscribe, subscribe_sms, unsubscribe, user, confirm,
                    debug_user, custom_unsub_reason, custom_update_phonebook,
                    custom_update_student_ambassadors, newsletters)


urlpatterns = patterns('',
    url('^subscribe/$', subscribe),
    url('^subscribe_sms/$', subscribe_sms),
    url('^unsubscribe/(.*)/$', unsubscribe),
    url('^user/(.*)/$', user),
    url('^confirm/(.*)/$', confirm),
    url('^debug-user/$', debug_user),

    url('^custom_unsub_reason/$', custom_unsub_reason),
    url('^custom_update_student_ambassadors/(.*)/$',
        custom_update_student_ambassadors),
    url('^custom_update_phonebook/(.*)/$', custom_update_phonebook),

    url('^newsletters/$', newsletters, name='newsletters_api'),
)

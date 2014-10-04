from django.conf.urls import patterns, url

from .views import (confirm, custom_unsub_reason, custom_update_phonebook,
                    custom_update_student_ambassadors, debug_user,
                    fxa_register, get_involved, list_newsletters, lookup_user, newsletters,
                    send_recovery_message, subscribe, subscribe_sms,
                    unsubscribe, user)


urlpatterns = patterns('',  # noqa
    url('^get-involved/$', get_involved),
    url('^fxa-register/$', fxa_register),
    url('^subscribe/$', subscribe),
    url('^subscribe_sms/$', subscribe_sms),
    url('^unsubscribe/(.*)/$', unsubscribe),
    url('^user/(.*)/$', user),
    url('^confirm/(.*)/$', confirm),
    url('^debug-user/$', debug_user),
    url('^lookup-user/$', lookup_user, name='lookup_user'),
    url('^recover/$', send_recovery_message, name='send_recovery_message'),

    url('^custom_unsub_reason/$', custom_unsub_reason),
    url('^custom_update_student_ambassadors/(.*)/$',
        custom_update_student_ambassadors),
    url('^custom_update_phonebook/(.*)/$', custom_update_phonebook),

    url('^newsletters/$', newsletters, name='newsletters_api'),
    url('^$', list_newsletters),
)

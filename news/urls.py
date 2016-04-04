from django.conf.urls import url

from .views import (confirm, custom_unsub_reason, custom_update_phonebook,
                    custom_update_student_ambassadors, debug_user,
                    fxa_activity, fxa_register, get_involved, list_newsletters, lookup_user,
                    newsletters, send_recovery_message, subscribe, subscribe_sms, sync_route,
                    unsubscribe, user)


def token_url(url_prefix, *args, **kwargs):
    """Require a properly formatted token as the last component of the URL."""
    url_re = '^{0}/(?P<token>[0-9A-Fa-f-]{{36}})/$'.format(url_prefix)
    return url(url_re, *args, **kwargs)


urlpatterns = (
    url('^get-involved/$', get_involved),
    url('^fxa-register/$', fxa_register),
    url('^fxa-activity/$', fxa_activity),
    url('^subscribe/$', subscribe),
    url('^subscribe_sms/$', subscribe_sms),
    token_url('unsubscribe', unsubscribe),
    token_url('user', user),
    token_url('confirm', confirm),
    url('^debug-user/$', debug_user),
    url('^lookup-user/$', lookup_user, name='lookup_user'),
    url('^recover/$', send_recovery_message, name='send_recovery_message'),

    url('^custom_unsub_reason/$', custom_unsub_reason),
    token_url('custom_update_student_ambassadors', custom_update_student_ambassadors),
    token_url('custom_update_phonebook', custom_update_phonebook),

    url('^newsletters/$', newsletters, name='newsletters_api'),
    url('^$', list_newsletters),
) + sync_route.urlpatterns

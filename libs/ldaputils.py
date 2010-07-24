import ldap

from django.conf import settings
from django.utils.encoding import smart_str

import commonware.log


log = commonware.log.getLogger('ldap')


def connect_ldap():
    server = '{host}:{port}'.format(**settings.LDAP)

    log.info("Initializing new LDAP connection")
    l = ldap.initialize(server)
    l.network_timeout = settings.LDAP_TIMEOUT
    l.timelimit = settings.LDAP_TIMEOUT
    l.timeout = settings.LDAP_TIMEOUT
    l.simple_bind_s(settings.LDAP['user'], settings.LDAP['password'])
    return l


def has_account(email):
    try:
        l = connect_ldap()
        resp = l.search_st(settings.LDAP['search_base'], ldap.SCOPE_SUBTREE,
                          '(mail={mail})'.format(mail=email), ['mail'], timeout=settings.LDAP_TIMEOUT)
        return bool(resp)
    except ldap.TIMEOUT:
        log.warning("ldap search timed out")
        return False
    except ldap.NO_SUCH_OBJECT:
        log.debug("no account found")
        return False

def subscription_has_account(subscription):
    return has_account(smart_str(subscription.subscriber.email))

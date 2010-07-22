import ldap

from django.conf import settings

import commonware.log


log = commonware.log.getLogger('basket')

_conn_cache = {}


def connect_ldap():
    server = '{host}:{port}'.format(**settings.LDAP)

    if server in _conn_cache:
        log.debug("using cached LDAP connection")
        return _conn_cache[server]

    log.info("Initializing new LDAP connection")
    l = ldap.initialize(server)
    l.simple_bind_s(settings.LDAP['user'], settings.LDAP['password'])
    _conn_cache[server] = l
    return l


def has_account(email):
    l = connect_ldap()
    try:
        resp = l.search_s(settings.LDAP['search_base'], ldap.SCOPE_SUBTREE,
                          '(mail={mail})'.format(mail=email), ['mail'])
        return bool(resp)
    except ldap.NO_SUCH_OBJECT:
        log.debug("no account found")
        return False

def subscription_has_account(subscription):
    return has_account(subscription.subscriber.email)

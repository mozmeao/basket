import ldap

from django.conf import settings


def connect_ldap():
    server = '{host}:{port}'.format(**settings.LDAP)
    l = ldap.initialize(server)
    l.simple_bind_s(settings.LDAP['user'], settings.LDAP['password'])
    return l


def has_account(email):
    l = connect_ldap()
    try:
        resp = l.search_s(settings.LDAP['search_base'], ldap.SCOPE_SUBTREE,
                          '(mail={mail})'.format(mail=email), ['mail'])
        return bool(resp)
    except ldap.NO_SUCH_OBJECT:
        return False

def subscription_has_account(subscription):
    return has_account(subscription.subscriber.email)

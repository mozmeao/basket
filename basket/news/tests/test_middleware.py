from django.test import RequestFactory, override_settings

from mock import Mock

from basket.news.middleware import EnforceHostnameMiddleware, is_ip_address


def test_is_ip_address():
    assert is_ip_address('1.2.3.4')
    assert is_ip_address('192.168.1.1')
    assert not is_ip_address('basket.mozilla.org')
    assert not is_ip_address('42.basket.mozilla.org')


@override_settings(DEBUG=False, ENFORCE_HOSTNAME=['basket.mozilla.org'])
def test_enforce_hostname_middleware():
    get_resp_mock = Mock()
    mw = EnforceHostnameMiddleware(get_resp_mock)
    req = RequestFactory().get('/', HTTP_HOST='basket.mozilla.org')
    resp = mw(req)
    get_resp_mock.assert_called_once_with(req)

    get_resp_mock.reset_mock()
    req = RequestFactory().get('/', HTTP_HOST='basket.allizom.org')
    resp = mw(req)
    get_resp_mock.assert_not_called()
    assert resp.status_code == 301
    assert resp['location'] == 'http://basket.mozilla.org/'

    # IP address should not redirect
    get_resp_mock.reset_mock()
    req = RequestFactory().get('/', HTTP_HOST='123.123.123.123')
    resp = mw(req)
    get_resp_mock.assert_called_once_with(req)

    # IP with port should also work
    get_resp_mock.reset_mock()
    req = RequestFactory().get('/', HTTP_HOST='1.2.3.4:12345')
    resp = mw(req)
    get_resp_mock.assert_called_once_with(req)

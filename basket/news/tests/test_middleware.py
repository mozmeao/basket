from basket.news.middleware import is_ip_address


def test_is_ip_address():
    assert is_ip_address('1.2.3.4')
    assert is_ip_address('192.168.1.1')
    assert not is_ip_address('basket.mozilla.org')
    assert not is_ip_address('42.basket.mozilla.org')

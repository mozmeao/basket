from types import SimpleNamespace

import pytest

from basket.base.throttling import MultiPeriodThrottle, WebhookIdentifierThrottle


def test_rate_parser():
    th = MultiPeriodThrottle("1/s")
    assert th.parse_rate(None) == (None, None)
    assert th.parse_rate("1/s") == (1, 1)
    assert th.parse_rate("1/s") == (1, 1)
    assert th.parse_rate("100/10s") == (100, 10)
    assert th.parse_rate("100/10") == (100, 10)
    assert th.parse_rate("5/m") == (5, 60)
    assert th.parse_rate("500/10m") == (500, 600)
    assert th.parse_rate("10/h") == (10, 3600)
    assert th.parse_rate("1000/2h") == (1000, 7200)
    assert th.parse_rate("100/d") == (100, 86400)
    assert th.parse_rate("10_000/7d") == (10000, 86400 * 7)

    with pytest.raises(ValueError):
        th.parse_rate("42")


def test_webhook_identifier_throttle_keys_on_body_identifier():
    th = WebhookIdentifierThrottle("4/5m")
    key = th.get_cache_key(SimpleNamespace(body=b'{"fxa_id": "abc"}'))
    assert key and "webhook" in key and "abc" in key


def test_webhook_identifier_throttle_precedence():
    # basket_token takes precedence over fxa_id/email.
    th = WebhookIdentifierThrottle("4/5m")
    key = th.get_cache_key(SimpleNamespace(body=b'{"basket_token": "tok", "fxa_id": "abc"}'))
    assert "tok" in key


def test_webhook_identifier_throttle_no_identifier_is_unthrottled():
    th = WebhookIdentifierThrottle("4/5m")
    assert th.get_cache_key(SimpleNamespace(body=b"{}")) is None


def test_webhook_identifier_throttle_malformed_body_is_unthrottled():
    th = WebhookIdentifierThrottle("4/5m")
    assert th.get_cache_key(SimpleNamespace(body=b"not json")) is None

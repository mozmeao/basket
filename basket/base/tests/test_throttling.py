import pytest

from basket.base.throttling import MultiPeriodThrottle


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

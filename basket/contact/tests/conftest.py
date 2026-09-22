import hashlib
import hmac
import time

from django.core.cache import cache

import pytest


@pytest.fixture(autouse=True)
def clear_ratelimit_cache():
    # django-ratelimit counters live in the (redis) default cache and outlive the
    # test run, so a stale count from a previous test leaks into the next one.
    cache.clear()
    yield


def sign_intake_body(user, body, timestamp=None):
    """Sign `body` the way IntakeAuth expects: t=<timestamp>,v1=<hmac-sha256 hex>."""
    ts = timestamp if timestamp is not None else int(time.time())
    sig = hmac.new(user.hmac_secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return ts, sig

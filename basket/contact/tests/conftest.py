from django.core.cache import cache

import pytest


@pytest.fixture(autouse=True)
def clear_ratelimit_cache():
    # django-ratelimit counters live in the (redis) default cache and outlive the
    # test run, so a stale count from a previous test leaks into the next one.
    cache.clear()
    yield

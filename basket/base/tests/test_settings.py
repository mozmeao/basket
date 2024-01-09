from unittest import mock

from django.conf import settings


def test_redis():
    """
    Test default cache backend is Redis.
    """
    # Note: If this fails after upgrading to Django >= 4, it's because the `django_cache_url`
    # switches to using the built-in Django `RedisCache`. This is a reminder to remove the
    # `django_redis` dependency and update this test.
    with mock.patch.dict("os.environ", {"REDIS_URL": "redis://localhost:6379/0"}):
        assert settings.CACHES["default"]["BACKEND"] == "django.core.cache.backends.redis.RedisCache"

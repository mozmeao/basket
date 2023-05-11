from django.test import TestCase
from django.test.utils import override_settings


class TestSettings(TestCase):
    @override_settings(REDIS_URL="redis://localhost:6379/0")
    def test_hiredis(self):
        """
        Test that the hiredis parser is used when the REDIS_URL scheme is set to `hiredis://`.
        """
        from django.conf import settings

        # Note: If this fails after upgrading to Django >= 4, it's because the `django_cache_url`
        # switches to using the built-in Django `RedisCache`. This is a reminder to remove the
        # `django_redis` dependency and update this test.
        assert settings.CACHES["default"]["BACKEND"] == "django_redis.cache.RedisCache"
        assert settings.CACHES["default"]["OPTIONS"]["PARSER_CLASS"] == "redis.connection.HiredisParser"

import functools

from markus.testing import MetricsMock

default_app_config = "basket.news.apps.BasketNewsConfig"


def mock_metrics(f):
    @functools.wraps(f)
    def wrapper(self, *args, **kwargs):
        with MetricsMock() as mm:
            return f(self, mm, *args, **kwargs)

    return wrapper

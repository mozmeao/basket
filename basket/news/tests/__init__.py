import functools
from unittest.mock import patch

from markus.testing import MetricsMock


def mock_metrics(f):
    @functools.wraps(f)
    def wrapper(self, *args, **kwargs):
        with MetricsMock() as mm:
            return f(self, mm, *args, **kwargs)

    return wrapper


class ViewsPatcherMixin:
    def _patch_views(self, name):
        patcher = patch("basket.news.views." + name)
        setattr(self, name, patcher.start())
        self.addCleanup(patcher.stop)


class TasksPatcherMixin:
    def _patch_tasks(self, name):
        patcher = patch("basket.news.tasks." + name)
        setattr(self, name, patcher.start())
        self.addCleanup(patcher.stop)

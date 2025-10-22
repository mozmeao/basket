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


def assert_called_with_subset(mock_method, *expected_args, **expected_kwargs):
    """Assert that mock was called with at least the specified args/kwargs"""
    assert mock_method.called, f"{mock_method} was not called"

    actual_args, actual_kwargs = mock_method.call_args

    # Check positional args
    if len(expected_args) > len(actual_args):
        raise AssertionError(f"Expected at least {len(expected_args)} args, got {len(actual_args)}")

    for i, expected_arg in enumerate(expected_args):
        if actual_args[i] != expected_arg:
            raise AssertionError(f"Arg {i}: expected {expected_arg}, got {actual_args[i]}")

    # Check keyword args
    for key, expected_value in expected_kwargs.items():
        if key not in actual_kwargs:
            raise AssertionError(f"Expected keyword arg '{key}' not found")
        if actual_kwargs[key] != expected_value:
            raise AssertionError(f"Kwarg '{key}': expected {expected_value}, got {actual_kwargs[key]}")

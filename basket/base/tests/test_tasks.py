import contextlib
import io
from time import time
from unittest import mock

from django.test import override_settings

from freezegun import freeze_time

from basket.base.tasks import snitch


@freeze_time("2023-01-02 12:34:56.123456")
@override_settings(SNITCH_ID="999")
@mock.patch("basket.base.tasks.requests.post")
def test_snitch(mock_post, metricsmock):
    seconds_ago = time() - 1
    snitch(seconds_ago)
    mock_post.assert_called_with("https://nosnch.in/999", data={"m": 1000})
    metricsmock.assert_timing_once("task.snitch", 1000)


@freeze_time("2023-01-02 12:34:56.123456")
@override_settings(SNITCH_ID="999")
@mock.patch("basket.base.tasks.requests.post")
def test_snitch_with_worker(mock_post, metricsmock):
    seconds_ago = time() - 1
    snitch.delay(seconds_ago)

    mock_post.assert_called_with("https://nosnch.in/999", data={"m": 1000})
    metricsmock.assert_timing_once("task.snitch", 1000)


@freeze_time("2023-01-02 12:34:56.123456")
@override_settings(SNITCH_ID=None)
@mock.patch("basket.base.tasks.requests.post")
def test_snitch_not_configured(mock_post, metricsmock):
    seconds_ago = time() - 1

    with contextlib.redirect_stdout(io.StringIO()) as f:
        snitch(seconds_ago)

    mock_post.assert_not_called()
    assert f.getvalue() == "Snitch: 1000ms\n"
    metricsmock.assert_not_timing("task.snitch")

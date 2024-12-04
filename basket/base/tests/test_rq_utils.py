from unittest.mock import patch

from django.conf import settings
from django.test.utils import override_settings

import pytest
from rq.job import Job, JobStatus
from rq.serializers import JSONSerializer

from basket.base.rq import (
    IGNORE_ERROR_MSGS,
    get_queue,
    get_redis_connection,
    get_worker,
    rq_exponential_backoff,
    store_task_exception_handler,
)
from basket.base.tests.tasks import failing_job, retryable_job
from basket.news.models import FailedTask
from basket.news.utils import NewsletterException


@pytest.mark.django_db
class TestRQUtils:
    def setup_method(self, method):
        self.queue = get_queue()

    def teardown_method(self, method):
        self.queue.empty()

    @override_settings(RQ_MAX_RETRIES=10)
    def test_rq_exponential_backoff(self):
        """
        Test that the exponential backoff function returns the correct number
        of retries, with a minimum of 60 seconds between retries.
        """
        with patch("basket.base.rq.random") as mock_random:
            mock_random.randrange.side_effect = [120 * 2**n for n in range(settings.RQ_MAX_RETRIES)]
            assert rq_exponential_backoff() == [120, 240, 480, 960, 1920, 3840, 7680, 15360, 30720, 61440]

    @override_settings(RQ_MAX_RETRIES=10, DEBUG=True)
    def test_rq_exponential_backoff_with_debug(self):
        """
        Test that the exponential backoff function returns shorter retries during DEBUG mode.
        """
        assert rq_exponential_backoff() == [5, 5, 5, 5, 5, 5, 5, 5, 5, 5]

    @override_settings(RQ_URL="redis://redis:6379/2")
    def test_get_redis_connection(self):
        """
        Test that the get_redis_connection function returns a Redis connection with params we expect.
        """
        # Test passing a URL explicitly.
        connection = get_redis_connection("redis://redis-host:6379/9", force=True)
        assert connection.connection_pool.connection_kwargs == {"host": "redis-host", "port": 6379, "db": 9}

        # Test with no URL argument, but with RQ_URL in the settings.
        # Note: The RQ_URL being used also sets this back to the "default" for tests that follow.
        connection = get_redis_connection(force=True)
        assert connection.connection_pool.connection_kwargs == {"host": "redis", "port": 6379, "db": 2}

    @override_settings(REDIS_URL=None, RQ_URL=None)
    def test_get_redis_connection_none(self):
        """
        Test that the get_redis_connection raises an exception when no URL is provided.
        """
        with pytest.raises(ValueError):
            get_redis_connection(force=True)

        # Set back to the "default" for tests that follow since the connection is cached in the module.
        get_redis_connection("redis://redis:6379/2", force=True)

    def test_get_queue(self):
        """
        Test that the get_queue function returns a RQ queue with params we expect.
        """
        queue = get_queue()

        assert queue.name == "default"
        assert queue._is_async is False  # Only during testing.
        assert queue.connection == get_redis_connection()
        assert queue.serializer == JSONSerializer

    def test_get_worker(self):
        """
        Test that the get_worker function returns a RQ worker with params we expect.
        """
        worker = get_worker()
        assert worker.queues == [self.queue]
        assert worker.disable_default_exception_handler is True
        assert worker._exc_handlers == [store_task_exception_handler]
        assert worker.serializer == JSONSerializer

    @override_settings(
        RQ_EXCEPTION_HANDLERS=["basket.base.rq.store_task_exception_handler"],
        RQ_IS_ASYNC=True,
    )
    def test_on_failure(self, metricsmock):
        """
        Test that the on_failure function creates a FailedTask object and sends
        statsd metrics.
        """
        assert FailedTask.objects.count() == 0

        args = ["arg1"]
        kwargs = {"arg2": "foo"}
        job = failing_job.delay(*args, **kwargs)

        worker = get_worker()
        assert worker._exc_handlers == [store_task_exception_handler]
        worker.work(burst=True)  # Burst = worker will quit after all jobs consumed.

        assert job.is_failed

        assert FailedTask.objects.count() == 1
        fail = FailedTask.objects.get()
        assert fail.name == "basket.base.tests.tasks.failing_job"
        assert fail.task_id is not None
        assert fail.args == args
        assert fail.kwargs == kwargs
        assert fail.exc == "ValueError('An exception to trigger the failure handler.')"
        assert "Traceback (most recent call last):" in fail.einfo
        assert "ValueError: An exception to trigger the failure handler." in fail.einfo
        metricsmock.assert_timing_once("task.timings", tags=["task:basket.base.tests.tasks.failing_job", "status:failure"])
        metricsmock.assert_incr_once("base.tasks.failed", tags=["task:basket.base.tests.tasks.failing_job"])

    @override_settings(
        RQ_EXCEPTION_HANDLERS=["basket.base.rq.store_task_exception_handler"],
        RQ_IS_ASYNC=True,
        RQ_MAX_RETRIES=3,
    )
    def test_retry_allowed(self, metricsmock):
        """
        Test that the error raised from `retryable_job` is actually retried.
        """
        job = retryable_job.delay("arg1")

        worker = get_worker()
        assert worker._exc_handlers == [store_task_exception_handler]
        worker.work(burst=True)  # Burst = worker will quit after all jobs consumed.

        job.refresh()

        assert job._status == JobStatus.SCHEDULED
        assert job.retries_left == 2

    @override_settings(MAINTENANCE_MODE=True)
    def test_on_failure_maintenance(self, metricsmock):
        """
        Test that the on_failure callback does nothing if we're in maintenance mode.
        """
        assert FailedTask.objects.count() == 0

        failing_job.delay()

        worker = get_worker()
        worker.work(burst=True)  # Burst = worker will quit after all jobs consumed.

        assert FailedTask.objects.count() == 0
        metricsmock.assert_incr_once("basket.base.tests.tasks.failing_job.queued")
        metricsmock.assert_not_incr("basket.base.tests.tasks.failing_job.failure")
        metricsmock.assert_not_incr("news.tasks.failure_total")

    @patch("basket.base.rq.sentry_sdk")
    def test_rq_exception_handler(self, mock_sentry_sdk, metricsmock):
        """
        Test that the exception handler creates a FailedTask object.
        """
        args = ["arg1"]
        kwargs = {"kwarg1": "kwarg1"}

        job = Job.create(
            func=print,
            args=args,
            kwargs=kwargs,
            connection=self.queue.connection,
            id="job1",
            meta={"task_name": "job.failed"},
        )
        assert FailedTask.objects.count() == 0

        with pytest.raises(ValueError) as e:
            # This is only here to generate the exception values.
            raise ValueError("This is a fake exception")
        job.set_status(JobStatus.FAILED)

        store_task_exception_handler(job, e.type, e.value, e.tb)

        assert FailedTask.objects.count() == 1
        failed_job = FailedTask.objects.get()
        assert failed_job.task_id == job.id
        assert failed_job.name == "job.failed"
        assert failed_job.args == args
        assert failed_job.kwargs == kwargs
        assert failed_job.exc == "ValueError('This is a fake exception')"
        assert "Traceback (most recent call last):" in failed_job.einfo
        assert "ValueError: This is a fake exception" in failed_job.einfo

        metricsmock.assert_incr_once("base.tasks.failed", tags=["task:job.failed"])

        assert mock_sentry_sdk.capture_exception.call_count == 1
        mock_sentry_sdk.isolation_scope.return_value.__enter__.return_value.set_tag.assert_called_once_with("action", "failed")

    @patch("basket.base.rq.sentry_sdk")
    def test_rq_exception_error_ignore(self, mock_sentry_sdk, metricsmock):
        job = Job.create(func=print, meta={"task_name": "job.ignore_error"}, connection=self.queue.connection)
        job.set_status(JobStatus.FAILED)

        for error_str in IGNORE_ERROR_MSGS:
            store_task_exception_handler(job, Exception, Exception(error_str), None)

            metricsmock.assert_not_incr("base.tasks.failed")

            assert mock_sentry_sdk.capture_exception.call_count == 1
            mock_sentry_sdk.isolation_scope.return_value.__enter__.return_value.set_tag.assert_called_once_with("action", "ignored")

            metricsmock.clear_records()
            mock_sentry_sdk.reset_mock()

        # Also test IGNORE_ERROR_MSGS_RE.
        store_task_exception_handler(job, Exception, Exception("campaignId 123 not found"), None)

        metricsmock.assert_not_incr("base.tasks.failed")

        assert mock_sentry_sdk.capture_exception.call_count == 1
        mock_sentry_sdk.isolation_scope.return_value.__enter__.return_value.set_tag.assert_called_once_with("action", "ignored")

    @patch("basket.base.rq.sentry_sdk")
    def test_rq_exception_handler_snitch(self, mock_sentry_sdk):
        """
        Test that the exception handler returns early if it's a snitch job.
        """
        job = Job.create(func=print, meta={"task_name": "job.endswith.snitch"}, connection=self.queue.connection)

        assert FailedTask.objects.count() == 0

        store_task_exception_handler(job)

        assert FailedTask.objects.count() == 0
        assert mock_sentry_sdk.capture_exception.call_count == 0

    @patch("basket.base.rq.sentry_sdk")
    def test_rq_exception_handler_retry_allowed(self, mock_sentry_sdk, metricsmock):
        job = Job.create(func=print, meta={"task_name": "job.rescheduled"}, connection=self.queue.connection)
        job.retries_left = 1
        job.retry_intervals = [1]

        with pytest.raises(NewsletterException) as e:
            # This is only here to generate the exception values.
            raise NewsletterException("This is a fake exception")

        job.set_status(JobStatus.FAILED)

        assert FailedTask.objects.count() == 0

        store_task_exception_handler(job, e.type, e.value, e.tb)

        assert FailedTask.objects.count() == 0
        metricsmock.assert_incr_once("base.tasks.retried", tags=["task:job.rescheduled"])
        assert mock_sentry_sdk.capture_exception.call_count == 1
        mock_sentry_sdk.isolation_scope.return_value.__enter__.return_value.set_tag.assert_called_once_with("action", "retried")

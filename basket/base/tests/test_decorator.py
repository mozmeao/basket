from unittest import mock
from unittest.mock import patch

from django.test import TestCase
from django.test.utils import override_settings

from basket.base.decorators import rq_task
from basket.base.rq import get_worker
from basket.base.tests.tasks import empty_job
from basket.news.models import QueuedTask


class TestDecorator(TestCase):
    @override_settings(RQ_RESULT_TTL=0)
    @override_settings(RQ_MAX_RETRIES=0)
    @patch("basket.base.decorators.rq_job")
    @patch("basket.base.rq.Callback")
    @patch("basket.base.rq.Queue")
    @patch("basket.base.rq.time")
    def test_rq_task(
        self,
        mock_time,
        mock_queue,
        mock_callback,
        mock_rq_job,
    ):
        """
        Test that the decorator passes the correct arguments to the RQ job.
        """
        mock_time.return_value = 123456789
        mock_queue.connection.return_value = "connection"

        @rq_task
        def test_func():
            pass

        mock_rq_job.assert_called_once_with(
            mock_queue(),
            connection=mock_queue().connection,
            meta={
                "task_name": f"{self.__module__}.TestDecorator.test_rq_task.<locals>.test_func",
                "start_time": 123456789,
            },
            retry=None,  # Retry logic is tested above, so no need to test it here.
            result_ttl=0,
            on_failure=mock_callback(),
            on_success=mock_callback(),
        )

    @override_settings(MAINTENANCE_MODE=True)
    @override_settings(READ_ONLY_MODE=False)
    @patch("basket.base.decorators.statsd")
    def test_maintenance_mode_no_readonly(self, mock_statsd):
        """
        Test that the decorator doesn't run the task if maintenance mode is on.
        """

        assert QueuedTask.objects.count() == 0

        empty_job.delay()

        mock_statsd.incr.assert_called_once_with("basket.base.tests.tasks.empty_job.queued")
        assert QueuedTask.objects.count() == 1

    @override_settings(MAINTENANCE_MODE=True)
    @override_settings(READ_ONLY_MODE=True)
    @patch("basket.base.decorators.statsd")
    def test_maintenance_mode_readonly(self, mock_statsd):
        """
        Test that the decorator doesn't run the task if maintenance mode is on
        and the task isn't queued because we're in READ_ONLY_MODE.
        """

        assert QueuedTask.objects.count() == 0

        empty_job.delay()

        mock_statsd.incr.assert_called_once_with("basket.base.tests.tasks.empty_job.not_queued")
        assert QueuedTask.objects.count() == 0

    @patch("basket.base.rq.statsd")
    def test_job_success(self, mock_statsd):
        """
        Test that the decorator marks the job as successful if the task runs
        successfully.
        """
        empty_job.delay("arg1")

        worker = get_worker()
        worker.work(burst=True)  # Burst = worker will quit after all jobs consumed.

        assert mock_statsd.incr.call_count == 2
        mock_statsd.incr.assert_any_call("basket.base.tests.tasks.empty_job.success")
        mock_statsd.incr.assert_any_call("news.tasks.success_total")
        assert mock_statsd.timing.call_count == 2
        mock_statsd.timing.assert_has_calls(
            [
                mock.call("basket.base.tests.tasks.empty_job.duration", mock.ANY),
                mock.call("news.tasks.duration_total", mock.ANY),
            ]
        )
